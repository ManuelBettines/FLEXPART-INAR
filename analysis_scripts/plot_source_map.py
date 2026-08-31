#!/usr/bin/env python3
"""Map the source regions of a measured concentration (concentration-weighted footprint).

Each release is tagged with the value measured at the receptor when its air arrived, that
value is spread over the output layers following the vertical profile of the footprint,
and the result is averaged over the releases that touched each cell.

Usage:
    ./plot_source_map.py footprints_d01.nc --obs IZO_SO2.txt --skiprows 4 \
        --value-col "So2 (ppb)" --label "SRC to SO2 [ppbv]"
    ./plot_source_map.py flxout_d02_20220626_230000.nc --obs msa.csv --save-nc src_msa.nc
"""
import argparse
import datetime as dt
import os
import re

import numpy as np
import pandas as pd
import xarray as xr

DECADES = 4.0                       # colour scale span below the maximum
DOMAIN_RE = re.compile(r"_d(\d+)_")
GRID_VARS = ("XLONG", "XLAT", "XLONG_CORNER", "XLAT_CORNER")


def domain_of(path):
    m = DOMAIN_RE.search(os.path.basename(path))
    return int(m.group(1)) if m else None


def find_header(flx, name=None):
    """The header of this run, beside the output file or in the current directory."""
    dom = domain_of(flx)
    name = name or (f"header_d{dom:02d}.nc" if dom else "header_d01.nc")
    folder = os.path.dirname(os.path.abspath(flx))
    for hit in (os.path.join(folder, name), os.path.join(os.getcwd(), name)):
        if os.path.exists(hit):
            return hit
    raise SystemExit(f"no {name} beside {flx}: FLEXPART-WRF writes it into the output "
                     f"directory, and the grid and the release times come from it")


def release_times(header, attrs):
    """When each release ends, i.e. when its air is at the receptor."""
    start = dt.datetime.strptime(f"{int(attrs['SIMULATION_START_DATE']):08d}"
                                 f"{int(attrs['SIMULATION_START_TIME']):06d}",
                                 "%Y%m%d%H%M%S")
    ends = np.asarray(header["ReleaseTstart_end"].values, dtype="float64").max(axis=-1)
    return np.array([np.datetime64(start + dt.timedelta(seconds=float(s)), "s")
                     for s in ends])


def open_footprints(path, header=None, species=0, chunk=10):
    """CONC(releases, bottom_top, south_north, west_east) plus the grid and the attributes.

    Accepts a file from reduce_output.py, or a raw flxout_dNN.nc, which still has the
    Time dimension and keeps its grid and release times in header_dNN.nc.
    """
    if not os.path.exists(path):
        raise SystemExit(f"no such file: {path}")
    with xr.open_dataset(path) as probe:
        raw = "Time" in probe.dims
    ds = xr.open_dataset(path, chunks={"Time": chunk} if raw else {})
    if "CONC" not in ds:
        raise SystemExit(f"{path} has no CONC variable: it is not a FLEXPART-WRF output")

    fp = ds["CONC"]
    if "releases" not in fp.dims:
        raise SystemExit("CONC has no releases dimension: this is a forward run, and "
                         "these scripts analyse backward (receptor-oriented) runs")
    if "species" in fp.dims:
        fp = fp.isel(species=species)
    if "ageclass" in fp.dims:
        fp = fp.sum("ageclass")
    if raw:
        fp = fp.sum("Time")
        hdr = xr.open_dataset(header or find_header(path))
        grid = {name: hdr[name].values for name in GRID_VARS}
        fp = fp.assign_coords(release_time=("releases", release_times(hdr, ds.attrs)),
                              ztop=("bottom_top", hdr["ZTOP"].values))
    else:
        missing = [v for v in GRID_VARS if v not in ds]
        if missing:
            raise SystemExit(f"{path} has no {', '.join(missing)}: rebuild it with "
                             f"reduce_output.py, which copies the grid in")
        grid = {name: ds[name].values for name in GRID_VARS}
    fp = fp.transpose("releases", "bottom_top", "south_north", "west_east")
    return fp.chunk({"releases": chunk}), grid, ds.attrs


def cell_edges(sw):
    """(ny+1, nx+1) cell edges from the (ny, nx) lower-left corners.

    The far east and north edges are not stored, so they follow the last spacing.
    """
    e = np.empty((sw.shape[0] + 1, sw.shape[1] + 1), dtype=float)
    e[:-1, :-1] = sw
    e[:-1, -1] = 2 * sw[:, -1] - sw[:, -2]
    e[-1, :-1] = 2 * sw[-1, :] - sw[-2, :]
    e[-1, -1] = 2 * e[-2, -1] - e[-3, -1]
    return e


def projection(attrs, lat):
    """The map projection of the run, from its global attributes."""
    import cartopy.crs as ccrs
    r = float(attrs.get("EARTH_RADIUS_M", 6370000.0))
    globe = ccrs.Globe(ellipse=None, semimajor_axis=r, semiminor_axis=r)
    lon0 = float(attrs.get("STAND_LON", attrs.get("CEN_LON", 0.0)))
    lat0 = float(attrs.get("CEN_LAT", lat.mean()))
    t1 = float(attrs.get("TRUELAT1", lat0))
    t2 = float(attrs.get("TRUELAT2", t1))
    code = int(attrs.get("MAP_PROJ", 0))
    if code == 1:
        return ccrs.LambertConformal(central_longitude=lon0, central_latitude=lat0,
                                     standard_parallels=(t1, t2), globe=globe)
    if code == 2:
        return ccrs.Stereographic(central_longitude=lon0, central_latitude=lat0,
                                  true_scale_latitude=t1, globe=globe)
    if code == 3:
        return ccrs.Mercator(central_longitude=lon0, latitude_true_scale=t1, globe=globe)
    return ccrs.PlateCarree(central_longitude=lon0, globe=globe)


def plot_map(field, grid, attrs, label, title, out, cmap="RdYlBu_r",
             vmin=None, vmax=None):
    """One pcolormesh on the run's own projection, on a log colour scale."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import cartopy.crs as ccrs
    import cartopy.feature as cfeature
    from matplotlib.colors import LogNorm

    positive = field[np.isfinite(field) & (field > 0)]
    if positive.size == 0:
        raise SystemExit("the selected field is empty: nothing to plot")
    vmax = float(vmax if vmax is not None else positive.max())
    vmin = float(vmin if vmin is not None else vmax * 10.0 ** (-DECADES))
    norm = LogNorm(vmin=vmin, vmax=vmax)
    lon_e, lat_e = cell_edges(grid["XLONG_CORNER"]), cell_edges(grid["XLAT_CORNER"])
    extent = [lon_e.min(), lon_e.max(), lat_e.min(), lat_e.max()]

    fig = plt.figure(figsize=(8.0, 6.4), layout="constrained")
    ax = fig.add_subplot(1, 1, 1, projection=projection(attrs, grid["XLAT"]))
    ax.set_extent(extent, crs=ccrs.PlateCarree())
    scale = "10m" if (extent[1] - extent[0]) < 15.0 else "50m"
    ax.add_feature(cfeature.OCEAN.with_scale("50m"), facecolor="#eaf1f6", zorder=0)
    ax.add_feature(cfeature.LAND.with_scale("50m"), facecolor="#f7f7f4", zorder=0)
    ax.add_feature(cfeature.COASTLINE.with_scale(scale), linewidth=0.6,
                   edgecolor="#4d5b66", zorder=3)
    ax.add_feature(cfeature.BORDERS.with_scale(scale), linewidth=0.5,
                   edgecolor="#7d8a94", linestyle="--", zorder=3)
    gl = ax.gridlines(draw_labels=True, linewidth=0.3, color="#b0b0b0", alpha=0.7)
    gl.top_labels = gl.right_labels = False
    gl.x_inline = gl.y_inline = False           # Lambert defaults to inline labels
    gl.xlabel_style = gl.ylabel_style = {"size": 11}

    mesh = ax.pcolormesh(lon_e, lat_e, np.ma.masked_less(field, vmin), norm=norm,
                         cmap=cmap, shading="flat", zorder=2,
                         transform=ccrs.PlateCarree())
    cb = fig.colorbar(mesh, ax=ax, pad=0.03, shrink=0.85, aspect=28, extend="both")
    cb.set_label(label, fontsize=13)
    cb.ax.tick_params(labelsize=11)
    ax.set_title(title, fontsize=13)
    fig.savefig(out, dpi=200)
    print(f"wrote {out}")


def read_observations(path, times, time_col, value_col, skiprows, sep, time_format):
    """The measured value for every release, averaged over the release interval.

    Anything the record does not cover comes back as NaN, and those releases are then
    left out of the average.
    """
    if not os.path.exists(path):
        raise SystemExit(f"no such file: {path}")
    try:
        df = pd.read_csv(path, skiprows=skiprows, sep=sep,
                         engine="python" if len(sep) > 1 else "c")
    except (pd.errors.ParserError, UnicodeDecodeError) as exc:
        raise SystemExit(f"cannot read {path}: {exc.args[0].splitlines()[0]}\n"
                         f"give the preamble length with --skiprows and the column "
                         f"separator with --sep")
    if len(df.columns) < 2:
        raise SystemExit(f"{path} has one column: give the right separator with --sep")
    time_col = time_col or df.columns[0]
    value_col = value_col or df.columns[1]
    for col, flag in ((time_col, "--time-col"), (value_col, "--value-col")):
        if col not in df.columns:
            raise SystemExit(f"{flag} {col!r} is not in {path}; it has: "
                             f"{', '.join(map(str, df.columns))}")

    stamps = pd.to_datetime(df[time_col], format=time_format, errors="coerce")
    if stamps.isna().all():
        raise SystemExit(f"no date in column {time_col!r} of {path} could be read; "
                         f"give the layout with --time-format, e.g. '%m/%d/%Y %H:%M'")
    series = pd.Series(pd.to_numeric(df[value_col], errors="coerce").values,
                       index=stamps).dropna(how="all")
    series = series[series.index.notna()].sort_index()

    index = pd.DatetimeIndex(times)
    if len(index) > 1:
        # bins are labelled at their left edge, so a release gets the interval that
        # starts when its air arrives -- the convention of the original scripts
        step = pd.Timedelta(np.median(np.diff(index.values)))
        series = series.resample(step).mean()
    return series.reindex(index).values


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", help="footprints_dNN.nc from reduce_output.py, or flxout_dNN.nc")
    ap.add_argument("--obs", required=True, metavar="FILE",
                    help="the measurements: a text table with a date and a value column")
    ap.add_argument("--time-col", metavar="NAME", help="date column (default: the first)")
    ap.add_argument("--value-col", metavar="NAME", help="value column (default: the second)")
    ap.add_argument("--skiprows", type=int, default=0, metavar="N",
                    help="header lines to skip before the column names (default: 0)")
    ap.add_argument("--sep", default=",", help="column separator (default: ',')")
    ap.add_argument("--time-format", metavar="FMT",
                    help="strptime layout of the date column (default: let pandas guess)")
    ap.add_argument("--header", metavar="FILE", help="the header file, if not beside the input")
    ap.add_argument("--species", type=int, default=0, metavar="N",
                    help="which species, 0-based (default: 0)")
    ap.add_argument("--chunk", type=int, default=10, metavar="N",
                    help="releases held in memory at a time (default: 10)")
    ap.add_argument("--label", default="Source contribution", help="colourbar label")
    ap.add_argument("--title", help="plot title (default: the file and the window)")
    ap.add_argument("--cmap", default="RdYlBu_r", help="matplotlib colormap")
    ap.add_argument("--vmin", type=float, help="colour scale minimum")
    ap.add_argument("--vmax", type=float, help="colour scale maximum")
    ap.add_argument("--save-nc", metavar="FILE", help="also write the map as NetCDF")
    ap.add_argument("-o", "--output", metavar="PNG",
                    help="where to write (default: from the input name)")
    a = ap.parse_args(argv)

    fp, grid, attrs = open_footprints(a.input, a.header, a.species, a.chunk)
    times = fp["release_time"].values.astype("datetime64[s]")
    obs = read_observations(a.obs, times, a.time_col, a.value_col, a.skiprows, a.sep,
                            a.time_format)

    column = fp.sum(("bottom_top", "south_north", "west_east")).values
    usable = np.isfinite(obs) & (column > 0)
    if not usable.any():
        raise SystemExit(f"no release has both a measurement and a footprint; the run "
                         f"covers {times.min()} .. {times.max()} and {os.path.basename(a.obs)} "
                         f"covers a different period")
    keep = np.flatnonzero(usable)
    sel = fp.isel(releases=keep)
    values = xr.DataArray(obs[keep], dims="releases", coords={"releases": sel["releases"]})

    print(f"{os.path.basename(a.input)}: {len(keep)} of {len(times)} releases have a "
          f"measurement and a non-empty footprint")
    print(f"  arrivals {str(times[keep].min())[:16]} .. {str(times[keep].max())[:16]} UTC")
    print(f"  {a.obs}: {np.nanmin(obs[keep]):.4g} .. {np.nanmax(obs[keep]):.4g}, "
          f"mean {np.nanmean(obs[keep]):.4g}")

    # the vertical profile of each release's footprint, used to spread its measured
    # value over the output layers
    profile = sel.sum(("south_north", "west_east"))
    profile = profile / profile.sum("bottom_top")
    weighted = values * profile * (sel != 0)
    counts = (weighted != 0).sum("releases")
    field = (weighted.sum("releases") / counts.where(counts > 0)).sum("bottom_top")
    field = field.compute()

    finite = field.values[np.isfinite(field.values)]
    print(f"  source map: max {finite.max():.4g}, "
          f"{100.0 * np.count_nonzero(finite) / field.size:.1f}% of cells touched")

    stem = os.path.splitext(os.path.basename(a.input))[0]
    out = a.output or f"{stem}_source_map.png"
    title = a.title or (f"Source contribution, {len(keep)} releases\n"
                        f"{str(times[keep].min())[:16]} .. {str(times[keep].max())[:16]} UTC")
    plot_map(field.values, grid, attrs, a.label, title, out, a.cmap, a.vmin, a.vmax)

    if a.save_nc:
        result = field.rename("SRC").to_dataset()
        for name in GRID_VARS:
            result[name] = (("south_north", "west_east"), grid[name])
        result.attrs = dict(attrs)
        result.attrs["history"] = (f"{dt.datetime.now():%Y-%m-%d %H:%M} plot_source_map.py: "
                                   f"{os.path.basename(a.input)} weighted by "
                                   f"{os.path.basename(a.obs)}")
        result.to_netcdf(a.save_nc, format="NETCDF4")
        print(f"wrote {a.save_nc}")


if __name__ == "__main__":
    main()
