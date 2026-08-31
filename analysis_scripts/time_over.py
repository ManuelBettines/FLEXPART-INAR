#!/usr/bin/env python3
"""Per-release residence time weighted by a static surface field.

Multiplies each release's column-integrated footprint by a map on the same grid (tree
cover, an emission inventory, a land/sea mask) and sums it over the domain, giving one
number per release -- e.g. the time the arriving air spent over forest.

Usage:
    ./time_over.py footprints_d01.nc --field geo_em_with_TCD.nc --var TCD \
        --missing 255 --scale 0.01 -o time_over_forest.csv
    ./time_over.py footprints_d02.nc --field emis.nc --var SO2 --bbox -20 -12 26 32
"""
import argparse
import datetime as dt
import os
import re

import numpy as np
import xarray as xr

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


def read_field(path, var, shape, missing, scale):
    """The static map, checked against the output grid and reduced to 2-D."""
    if not os.path.exists(path):
        raise SystemExit(f"no such file: {path}")
    ds = xr.open_dataset(path)
    if var not in ds:
        raise SystemExit(f"{path} has no variable {var!r}; it has: "
                         f"{', '.join(map(str, ds.data_vars))}")
    field = ds[var].squeeze(drop=True)         # geo_em files carry a length-1 Time
    if field.ndim != 2:
        raise SystemExit(f"{var} in {path} is {field.ndim}-dimensional "
                         f"({', '.join(field.dims)}): give a 2-D surface field")
    if field.shape != shape:
        raise SystemExit(f"{var} in {path} is {field.shape[1]} x {field.shape[0]} but "
                         f"the output grid is {shape[1]} x {shape[0]}: the static field "
                         f"must be on the FLEXPART output grid")
    field = field.rename({field.dims[0]: "south_north", field.dims[1]: "west_east"})
    if missing is not None:
        field = field.where(field != missing, 0.0)
    return field * scale


def bbox_mask(grid, bbox):
    """Cells whose centre lies inside lon0 lon1 lat0 lat1."""
    lon0, lon1, lat0, lat1 = bbox
    inside = ((grid["XLONG"] >= lon0) & (grid["XLONG"] <= lon1)
              & (grid["XLAT"] >= lat0) & (grid["XLAT"] <= lat1))
    if not inside.any():
        raise SystemExit(f"--bbox {lon0} {lon1} {lat0} {lat1} does not overlap the "
                         f"domain, which spans {grid['XLONG'].min():.2f}.."
                         f"{grid['XLONG'].max():.2f} E, {grid['XLAT'].min():.2f}.."
                         f"{grid['XLAT'].max():.2f} N")
    return xr.DataArray(inside, dims=("south_north", "west_east"))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", help="footprints_dNN.nc from reduce_output.py, or flxout_dNN.nc")
    ap.add_argument("--field", required=True, metavar="FILE",
                    help="NetCDF holding the static map, on the output grid")
    ap.add_argument("--var", required=True, metavar="NAME", help="which variable to use")
    ap.add_argument("--scale", type=float, default=1.0, metavar="F",
                    help="multiply the static field by this (e.g. 0.01 for percent)")
    ap.add_argument("--missing", type=float, metavar="V",
                    help="value that means no data in the static field, set to 0 "
                         "(e.g. 255 in WRF geo_em fields)")
    ap.add_argument("--bbox", type=float, nargs=4, metavar=("LON0", "LON1", "LAT0", "LAT1"),
                    help="restrict the sum to this lon/lat box (default: whole domain)")
    ap.add_argument("--below", type=float, metavar="METRES",
                    help="use only the output layers below this height (default: all)")
    ap.add_argument("--header", metavar="FILE", help="the header file, if not beside the input")
    ap.add_argument("--species", type=int, default=0, metavar="N",
                    help="which species, 0-based (default: 0)")
    ap.add_argument("--chunk", type=int, default=50, metavar="N",
                    help="releases held in memory at a time (default: 50)")
    ap.add_argument("-o", "--output", metavar="CSV",
                    help="where to write (default: from the input name)")
    a = ap.parse_args(argv)

    fp, grid, _ = open_footprints(a.input, a.header, a.species, a.chunk)
    field = read_field(a.field, a.var, (fp.sizes["south_north"], fp.sizes["west_east"]),
                       a.missing, a.scale)

    if a.below is not None:
        keep = fp["ztop"].values <= a.below
        if not keep.any():
            raise SystemExit(f"no output layer lies below {a.below:g} m; the lowest top "
                             f"is {fp['ztop'].values.min():g} m")
        fp = fp.isel(bottom_top=np.flatnonzero(keep))

    weight = field
    if a.bbox:
        weight = weight.where(bbox_mask(grid, a.bbox), 0.0)

    print(f"{os.path.basename(a.input)}: {fp.sizes['releases']} releases, "
          f"{fp.sizes['bottom_top']} layers")
    print(f"  weighting by {a.var} from {os.path.basename(a.field)}: "
          f"{float(weight.min()):.4g} .. {float(weight.max()):.4g}"
          + (f", inside {a.bbox}" if a.bbox else ""))

    from dask.diagnostics import ProgressBar
    with ProgressBar():
        series = (fp.sum("bottom_top") * weight).sum(("south_north", "west_east")).compute()

    values = series.values
    times = fp["release_time"].values.astype("datetime64[s]")
    stem = os.path.splitext(os.path.basename(a.input))[0]
    out = a.output or f"{stem}_{a.var}.csv"
    with open(out, "w") as fh:
        fh.write(f"release_time,{a.var}\n")
        for when, value in zip(times, values):
            fh.write(f"{when},{value:.6g}\n")
    print(f"  {a.var}: {values.min():.4g} .. {values.max():.4g}, mean {values.mean():.4g}")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
