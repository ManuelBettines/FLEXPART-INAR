#!/usr/bin/env python3
"""Reduce a FLEXPART-WRF run to one footprint per release.

Sums CONC over the output steps and copies the grid, the release times and the global
attributes into the result, so the file is self-contained: every other script here then
needs nothing but this one file.

Usage:
    ./reduce_output.py flxout_d01_20220626_230000.nc
    ./reduce_output.py flxout_d02_20220626_230000.nc -o footprints_d02.nc --chunk 100
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
    """When each release ends, i.e. when its air is at the receptor.

    ReleaseTstart_end holds seconds from the run start, negative for a backward run, so
    the later of the two bounds is the arrival.
    """
    for key in ("SIMULATION_START_DATE", "SIMULATION_START_TIME"):
        if key not in attrs:
            raise SystemExit(f"the output file has no {key} attribute: it is not a "
                             f"FLEXPART-WRF output file")
    start = dt.datetime.strptime(f"{int(attrs['SIMULATION_START_DATE']):08d}"
                                 f"{int(attrs['SIMULATION_START_TIME']):06d}",
                                 "%Y%m%d%H%M%S")
    ends = np.asarray(header["ReleaseTstart_end"].values, dtype="float64").max(axis=-1)
    return np.array([np.datetime64(start + dt.timedelta(seconds=float(s)), "s")
                     for s in ends])


def footprints(ds, species):
    """CONC(releases, bottom_top, south_north, west_east), summed over the output steps."""
    conc = ds["CONC"]
    if "releases" not in conc.dims:
        raise SystemExit("CONC has no releases dimension: this is a forward run, and "
                         "these scripts analyse backward (receptor-oriented) runs")
    if "species" in conc.dims:
        if not 0 <= species < conc.sizes["species"]:
            raise SystemExit(f"--species must be between 0 and {conc.sizes['species'] - 1}")
        conc = conc.isel(species=species)
    if "ageclass" in conc.dims:
        conc = conc.sum("ageclass")          # age classes partition the same particles
    return conc.sum("Time").transpose("releases", "bottom_top", "south_north", "west_east")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("flxout", help="the FLEXPART-WRF output file to reduce")
    ap.add_argument("-o", "--output", metavar="FILE",
                    help="where to write (default: footprints_dNN.nc beside the input)")
    ap.add_argument("--header", metavar="FILE",
                    help="the header file (default: header_dNN.nc beside the input)")
    ap.add_argument("--species", type=int, default=0, metavar="N",
                    help="which species, 0-based, if the run has several (default: 0)")
    ap.add_argument("--chunk", type=int, default=50, metavar="N",
                    help="output steps read at a time (default: 50)")
    a = ap.parse_args(argv)

    if not os.path.exists(a.flxout):
        raise SystemExit(f"no such file: {a.flxout}")
    header_path = a.header or find_header(a.flxout)
    dom = domain_of(a.flxout)
    out = a.output or os.path.join(os.path.dirname(os.path.abspath(a.flxout)),
                                   f"footprints_d{dom:02d}.nc" if dom else "footprints.nc")

    ds = xr.open_dataset(a.flxout, chunks={"Time": a.chunk})
    header = xr.open_dataset(header_path)
    missing = [v for v in GRID_VARS + ("ZTOP", "ReleaseTstart_end") if v not in header]
    if missing:
        raise SystemExit(f"{header_path} is not a FLEXPART-WRF header file "
                         f"(no {', '.join(missing)})")

    fp = footprints(ds, a.species)
    ny, nx = fp.sizes["south_north"], fp.sizes["west_east"]
    if header["XLAT"].shape != (ny, nx):
        raise SystemExit(f"{os.path.basename(header_path)} is "
                         f"{header['XLAT'].shape[1]} x {header['XLAT'].shape[0]} but "
                         f"{os.path.basename(a.flxout)} is {nx} x {ny}: they are from "
                         f"different runs")

    times = release_times(header, ds.attrs)
    if len(times) != fp.sizes["releases"]:
        raise SystemExit(f"{os.path.basename(header_path)} lists {len(times)} releases "
                         f"but the output file has {fp.sizes['releases']}")

    reduced = fp.rename("CONC").to_dataset()
    reduced = reduced.assign_coords(release_time=("releases", times),
                                    ztop=("bottom_top", header["ZTOP"].values))
    for name in GRID_VARS:
        reduced[name] = (("south_north", "west_east"), header[name].values)
    reduced.attrs = dict(ds.attrs)
    reduced.attrs["history"] = (f"{dt.datetime.now():%Y-%m-%d %H:%M} reduce_output.py: "
                                f"CONC summed over Time from "
                                f"{os.path.basename(a.flxout)}")
    reduced["CONC"].attrs = {"description": "SOURCE-RECEPTOR RELATIONSHIP", "units": "s"}
    reduced["ztop"].attrs = {"description": "TOP OF OUTPUT LAYER", "units": "m"}

    print(f"{os.path.basename(a.flxout)}: {nx} x {ny} x {fp.sizes['bottom_top']} cells, "
          f"{fp.sizes['releases']} releases, {ds.sizes['Time']} output steps")
    print(f"  grid and release times from {os.path.basename(header_path)}")
    print(f"  releases arrive {str(times[0])[:16]} .. {str(times[-1])[:16]} UTC")
    print(f"  writing {out}")

    from dask.diagnostics import ProgressBar
    with ProgressBar():
        reduced.to_netcdf(out, format="NETCDF4", encoding={"CONC": {
            "zlib": True, "complevel": 4,
            "chunksizes": (1, fp.sizes["bottom_top"], ny, nx)}})
    print(f"wrote {out} ({os.path.getsize(out) / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
