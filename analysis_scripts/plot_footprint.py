#!/usr/bin/env python3
"""Map the mean source-receptor relationship of a FLEXPART-WRF backward run.

Averages the footprint over the releases in a time window and integrates it through
height. Works on a file from reduce_output.py or straight on flxout_dNN.nc.

Usage:
    ./plot_footprint.py footprints_d01.nc --start 2022-05-28 --end 2022-05-29
    ./plot_footprint.py flxout_d02_20220626_230000.nc --below 1000
"""
import argparse
import datetime as dt
import os
import re

import numpy as np
import xarray as xr

DECADES = 4.0                       # colour scale span below the maximum
DOMAIN_RE = re.compile(r"_d(\d+)_")
GRID_VARS = ("XLONG", "XLAT", "XLONG_CORNER", "XLAT_CORNER")
DATE_FORMATS = (("%Y-%m-%d %H:%M:%S", True), ("%Y-%m-%d %H:%M", True),
                ("%Y%m%d_%H%M%S", True), ("%Y-%m-%d", False), ("%Y%m%d", False))


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


def open_footprints(path, header=None, species=0, chunk=50):
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


def parse_date(text, end=False):
    """A date on the command line; a bare day means the whole day when it is --end."""
    for fmt, has_time in DATE_FORMATS:
        try:
            when = dt.datetime.strptime(text, fmt)
        except ValueError:
            continue
        if end and not has_time:
            when += dt.timedelta(days=1, seconds=-1)
        return np.datetime64(when, "s")
    raise SystemExit(f"cannot read {text!r} as a date: use YYYY-MM-DD[ HH:MM]")


def select_releases(fp, start, end):
    """The releases arriving inside the window, as a boolean mask."""
    times = fp["release_time"].values.astype("datetime64[s]")
    mask = np.ones(times.shape, dtype=bool)
    if start is not None:
        mask &= times >= start
    if end is not None:
        mask &= times <= end
    if not mask.any():
        raise SystemExit(f"no release arrives between {start} and {end}; the run covers "
                         f"{times.min()} .. {times.max()}")
    return mask


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", help="footprints_dNN.nc from reduce_output.py, or flxout_dNN.nc")
    ap.add_argument("--start", metavar="DATE", help="first release arrival to average")
    ap.add_argument("--end", metavar="DATE", help="last release arrival to average")
    ap.add_argument("--below", type=float, metavar="METRES",
                    help="use only the output layers below this height (default: all)")
    ap.add_argument("--header", metavar="FILE", help="the header file, if not beside the input")
    ap.add_argument("--species", type=int, default=0, metavar="N",
                    help="which species, 0-based (default: 0)")
    ap.add_argument("--label", default="Average SRR (s)", help="colourbar label")
    ap.add_argument("--title", help="plot title (default: the file and the window)")
    ap.add_argument("--cmap", default="RdYlBu_r", help="matplotlib colormap")
    ap.add_argument("--vmin", type=float, help="colour scale minimum")
    ap.add_argument("--vmax", type=float, help="colour scale maximum")
    ap.add_argument("-o", "--output", metavar="PNG",
                    help="where to write (default: from the input name)")
    a = ap.parse_args(argv)

    fp, grid, attrs = open_footprints(a.input, a.header, a.species)
    start = parse_date(a.start) if a.start else None
    end = parse_date(a.end, end=True) if a.end else None
    mask = select_releases(fp, start, end)
    sel = fp.isel(releases=np.flatnonzero(mask))

    if a.below is not None:
        if "ztop" not in sel.coords:
            raise SystemExit("--below needs the layer tops: rebuild the file with "
                             "reduce_output.py, or point at the raw flxout")
        keep = sel["ztop"].values <= a.below
        if not keep.any():
            raise SystemExit(f"no output layer lies below {a.below:g} m; the lowest top "
                             f"is {sel['ztop'].values.min():g} m")
        sel = sel.isel(bottom_top=np.flatnonzero(keep))

    times = sel["release_time"].values.astype("datetime64[s]")
    window = f"{str(times.min())[:16]} .. {str(times.max())[:16]} UTC"
    print(f"{os.path.basename(a.input)}: {mask.sum()} of {fp.sizes['releases']} releases, "
          f"{sel.sizes['bottom_top']} of {fp.sizes['bottom_top']} layers")
    print(f"  arrivals {window}")

    field = (sel.sum("bottom_top").sum("releases") / sel.sizes["releases"]).values
    print(f"  mean column-integrated SRR: max {np.nanmax(field):.4g} s, "
          f"{100.0 * np.count_nonzero(field) / field.size:.1f}% of cells touched")

    stem = os.path.splitext(os.path.basename(a.input))[0]
    out = a.output or f"{stem}_footprint.png"
    title = a.title or f"Mean footprint, {mask.sum()} releases\n{window}"
    plot_map(field, grid, attrs, a.label, title, out, a.cmap, a.vmin, a.vmax)


if __name__ == "__main__":
    main()
