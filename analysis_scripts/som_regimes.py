#!/usr/bin/env python3
"""Cluster the release footprints into transport regimes with a self-organising map.

Each release is one sample (its column-integrated footprint, standardised cell by cell).
Writes the cluster of every release, a map of every neuron's weights, and the map of
which neuron dominates each grid cell.

Needs minisom and scikit-learn on top of the usual stack.

Usage:
    ./som_regimes.py footprints_d01.nc --shape 3x2
    ./som_regimes.py footprints_d02.nc --shape 4x3 --iterations 200000 -o som_d02
"""
import argparse
import datetime as dt
import os
import re

import numpy as np
import xarray as xr

DOMAIN_RE = re.compile(r"_d(\d+)_")
SHAPE_RE = re.compile(r"^(\d+)x(\d+)$")
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


def parse_shape(text):
    m = SHAPE_RE.match(text)
    if not m:
        raise SystemExit(f"cannot read {text!r} as a SOM shape: use COLSxROWS, e.g. 3x2")
    return int(m.group(1)), int(m.group(2))


def plot_neurons(weights, counts, grid, attrs, som_x, som_y, out, cmap):
    """One map per neuron, on a colour scale shared by all of them."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import cartopy.crs as ccrs
    import cartopy.feature as cfeature

    lon_e, lat_e = cell_edges(grid["XLONG_CORNER"]), cell_edges(grid["XLAT_CORNER"])
    extent = [lon_e.min(), lon_e.max(), lat_e.min(), lat_e.max()]
    limit = float(np.nanmax(np.abs(weights)))
    crs = projection(attrs, grid["XLAT"])

    fig, axes = plt.subplots(som_y, som_x, figsize=(4.6 * som_x, 3.8 * som_y),
                             squeeze=False, subplot_kw={"projection": crs},
                             layout="constrained")
    scale = "10m" if (extent[1] - extent[0]) < 15.0 else "50m"
    for j in range(som_y):
        for i in range(som_x):
            ax = axes[j][i]
            ax.set_extent(extent, crs=ccrs.PlateCarree())
            ax.add_feature(cfeature.OCEAN.with_scale("50m"), facecolor="#eaf1f6", zorder=0)
            ax.add_feature(cfeature.LAND.with_scale("50m"), facecolor="#f7f7f4", zorder=0)
            ax.add_feature(cfeature.COASTLINE.with_scale(scale), linewidth=0.6,
                           edgecolor="#4d5b66", zorder=3)
            ax.add_feature(cfeature.BORDERS.with_scale(scale), linewidth=0.5,
                           edgecolor="#7d8a94", linestyle="--", zorder=3)
            gl = ax.gridlines(draw_labels=True, linewidth=0.3, color="#b0b0b0", alpha=0.7)
            gl.top_labels = gl.right_labels = False
            gl.x_inline = gl.y_inline = False
            gl.xlabel_style = gl.ylabel_style = {"size": 9}
            k = j * som_x + i
            mesh = ax.pcolormesh(lon_e, lat_e, weights[i, j], cmap=cmap, shading="flat",
                                 vmin=-limit, vmax=limit, zorder=2,
                                 transform=ccrs.PlateCarree())
            ax.set_title(f"regime {k} -- {counts[k]} releases", fontsize=12)
    cb = fig.colorbar(mesh, ax=axes, pad=0.02, shrink=0.85, aspect=30)
    cb.set_label("neuron weight (standardised SRR)", fontsize=12)
    fig.savefig(out, dpi=180)
    print(f"wrote {out}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", help="footprints_dNN.nc from reduce_output.py, or flxout_dNN.nc")
    ap.add_argument("--shape", default="3x2", metavar="COLSxROWS",
                    help="SOM grid, e.g. 3x2 for six regimes (default: 3x2)")
    ap.add_argument("--iterations", type=int, default=100000, metavar="N",
                    help="training iterations (default: 100000)")
    ap.add_argument("--sigma", type=float, default=1.0, help="initial neighbourhood radius")
    ap.add_argument("--learning-rate", type=float, default=0.5, help="initial learning rate")
    ap.add_argument("--topology", default="hexagonal", choices=("hexagonal", "rectangular"))
    ap.add_argument("--seed", type=int, default=123, help="random seed (default: 123)")
    ap.add_argument("--below", type=float, metavar="METRES",
                    help="use only the output layers below this height (default: all)")
    ap.add_argument("--header", metavar="FILE", help="the header file, if not beside the input")
    ap.add_argument("--species", type=int, default=0, metavar="N",
                    help="which species, 0-based (default: 0)")
    ap.add_argument("--verbose", action="store_true",
                    help="show MiniSom's training progress")
    ap.add_argument("--cmap", default="RdYlBu_r", help="matplotlib colormap")
    ap.add_argument("-o", "--output", metavar="PREFIX",
                    help="prefix for the three output files (default: from the input name)")
    a = ap.parse_args(argv)

    som_x, som_y = parse_shape(a.shape)
    try:
        from minisom import MiniSom
        from sklearn.preprocessing import StandardScaler
    except ImportError as exc:
        raise SystemExit(f"{exc.name} is not installed: pip install minisom scikit-learn")

    fp, grid, attrs = open_footprints(a.input, a.header, a.species)
    if a.below is not None:
        keep = fp["ztop"].values <= a.below
        if not keep.any():
            raise SystemExit(f"no output layer lies below {a.below:g} m; the lowest top "
                             f"is {fp['ztop'].values.min():g} m")
        fp = fp.isel(bottom_top=np.flatnonzero(keep))

    column = fp.sum("bottom_top")
    ny, nx = column.sizes["south_north"], column.sizes["west_east"]
    samples = column.values.reshape(column.sizes["releases"], ny * nx).astype("float32")
    samples = np.nan_to_num(samples)
    if samples.shape[0] < som_x * som_y:
        raise SystemExit(f"{samples.shape[0]} releases cannot fill {som_x * som_y} "
                         f"neurons: use a smaller --shape")

    scaled = StandardScaler().fit_transform(samples)
    print(f"{os.path.basename(a.input)}: {samples.shape[0]} releases x {ny * nx} cells, "
          f"{som_x}x{som_y} = {som_x * som_y} regimes")

    som = MiniSom(x=som_x, y=som_y, input_len=scaled.shape[1], sigma=a.sigma,
                  learning_rate=a.learning_rate, neighborhood_function="gaussian",
                  activation_distance="euclidean", topology=a.topology,
                  decay_function="linear_decay_to_zero", random_seed=a.seed)
    som.random_weights_init(scaled)
    print(f"  training {a.iterations} iterations...")
    som.train_random(scaled, a.iterations, verbose=a.verbose)
    print(f"  quantisation error {som.quantization_error(scaled):.4g}")

    # MiniSom indexes neurons (i, j) = (column, row); flatten row-major to a regime number
    bmus = np.array([som.winner(sample) for sample in scaled])
    labels = bmus[:, 1] * som_x + bmus[:, 0]
    counts = np.bincount(labels, minlength=som_x * som_y)
    weights = som.get_weights().reshape(som_x, som_y, ny, nx)

    stem = a.output or os.path.splitext(os.path.basename(a.input))[0] + "_som"
    times = fp["release_time"].values.astype("datetime64[s]")
    with open(f"{stem}_clusters.csv", "w") as fh:
        fh.write("release,release_time,regime\n")
        for r, (when, label) in enumerate(zip(times, labels)):
            fh.write(f"{r},{when},{label}\n")
    print(f"wrote {stem}_clusters.csv")
    for k, n in enumerate(counts):
        print(f"  regime {k}: {n} releases ({100.0 * n / len(labels):.1f}%)")

    plot_neurons(weights, counts, grid, attrs, som_x, som_y,
                 f"{stem}_neurons.png", a.cmap)

    flat = weights.transpose(1, 0, 2, 3).reshape(som_x * som_y, ny, nx)
    dominant = xr.DataArray(np.argmax(flat, axis=0).astype("int16"),
                            dims=("south_north", "west_east"), name="dominant_regime")
    dominant.attrs["description"] = (f"regime (0-{som_x * som_y - 1}) whose neuron has "
                                     f"the largest weight in this cell")
    result = dominant.to_dataset()
    for name in GRID_VARS:
        result[name] = (("south_north", "west_east"), grid[name])
    result.attrs = dict(attrs)
    result.attrs["history"] = (f"{dt.datetime.now():%Y-%m-%d %H:%M} som_regimes.py "
                               f"{som_x}x{som_y} on {os.path.basename(a.input)}")
    result.to_netcdf(f"{stem}_dominant.nc", format="NETCDF4")
    print(f"wrote {stem}_dominant.nc")


if __name__ == "__main__":
    main()
