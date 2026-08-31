#!/usr/bin/env python3
"""Per-release exposure to a time-varying emission field (accumulated mass exposure).

For every release, walks back through the output steps and multiplies the footprint at
each step by the emission field *at that same hour*, summing over the domain. One number
per release per species, which is what separates this from time_over.py and its
static map.

Needs the raw flxout, not a reduced file: the output steps have to still be there.

Usage:
    ./ame_timeseries.py flxout_d01_20230430_230000.nc --emis EMISSION_MILAN.nc \
        --var MONOT NOx SO2_a --emis-level 1 -o AME_Milan.csv
    ./ame_timeseries.py flxout_d02_20220626_230000.nc --emis emis.nc --var SO2 \
        --hours 48 --below 1000
"""
import argparse
import datetime as dt
import os
import re

import numpy as np
import xarray as xr

DOMAIN_RE = re.compile(r"_d(\d+)_")
HOURS = 72.0                        # length of the backward window
X_ALIASES = ("west_east", "x", "lon", "longitude", "nx")
Y_ALIASES = ("south_north", "y", "lat", "latitude", "ny")
Z_ALIASES = ("bottom_top", "z", "lev", "level", "presnivs", "nz")
TIME_COORDS = ("Times", "time", "time_counter", "valid_time", "XTIME", "Time")


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
                     f"directory, and the release times come from it")


def release_times(header, attrs):
    """When each release ends, i.e. when its air is at the receptor."""
    start = dt.datetime.strptime(f"{int(attrs['SIMULATION_START_DATE']):08d}"
                                 f"{int(attrs['SIMULATION_START_TIME']):06d}",
                                 "%Y%m%d%H%M%S")
    ends = np.asarray(header["ReleaseTstart_end"].values, dtype="float64").max(axis=-1)
    return np.array([np.datetime64(start + dt.timedelta(seconds=float(s)), "s")
                     for s in ends])


def parse_stamps(values):
    """WRF '20220626_230000' and CHIMERE '20220626230000.000' both hold 14 digits."""
    out = []
    for value in values:
        if isinstance(value, bytes):
            value = value.decode()
        digits = re.sub(r"\D", "", str(value))[:14]
        out.append(np.datetime64(dt.datetime.strptime(digits, "%Y%m%d%H%M%S"), "s")
                   if len(digits) == 14 else np.datetime64("NaT", "s"))
    return np.array(out, dtype="datetime64[s]")


def stamps_of(ds, name):
    """The times of a char time variable, joining the character dimension if there is one."""
    raw = ds[name].values
    if raw.ndim == 2 and raw.dtype.kind in "SU":
        raw = [b"".join(row).decode() if raw.dtype.kind == "S" else "".join(row)
               for row in raw]
    return parse_stamps(np.atleast_1d(raw))


def dataset_times(ds, path):
    """The time axis of a dataset, as datetime64, whatever it chose to call it."""
    for name in TIME_COORDS:
        if name in ds.variables and ds[name].dtype.kind == "M":
            return np.asarray(ds[name].values, dtype="datetime64[s]"), ds[name].dims[0]
    for name in TIME_COORDS:
        if name in ds.variables and ds[name].dtype.kind in "SU":
            stamps = stamps_of(ds, name)
            if not np.isnat(stamps).all():
                return stamps, ds[name].dims[0]
    raise SystemExit(f"{path} has no readable time axis (looked for "
                     f"{', '.join(TIME_COORDS)}); if the field is static, use "
                     f"time_over.py instead")


def standard_dims(da, path, var):
    """Rename whatever the file calls x/y/z to the FLEXPART output names."""
    renames = {}
    for dim in da.dims:
        low = str(dim).lower()
        if low in X_ALIASES:
            renames[dim] = "west_east"
        elif low in Y_ALIASES:
            renames[dim] = "south_north"
        elif low in Z_ALIASES:
            renames[dim] = "bottom_top"
    missing = {"west_east", "south_north"} - set(renames.values())
    if missing:
        raise SystemExit(f"cannot tell which dimensions of {var} in {path} are "
                         f"{' and '.join(sorted(missing))}; it has "
                         f"{', '.join(map(str, da.dims))}")
    return da.rename(renames)


def read_emissions(path, variables, level, shape, times, chunk):
    """Each emission field on the output grid, aligned to the FLEXPART output steps."""
    if not os.path.exists(path):
        raise SystemExit(f"no such file: {path}")
    ds = xr.open_dataset(path, chunks={})
    stamps, time_dim = dataset_times(ds, path)

    fields = {}
    for var in variables:
        if var not in ds:
            raise SystemExit(f"{path} has no variable {var!r}; it has: "
                             f"{', '.join(map(str, ds.data_vars))}")
        da = standard_dims(ds[var], path, var)
        da = da.swap_dims({time_dim: "emis_time"}) if time_dim in da.dims else da
        if "emis_time" not in da.dims:
            raise SystemExit(f"{var} in {path} does not vary in time; use "
                             f"time_over.py for a static field")
        da = da.assign_coords(emis_time=("emis_time", stamps))
        if "bottom_top" in da.dims:
            if not 0 <= level < da.sizes["bottom_top"]:
                raise SystemExit(f"--emis-level must be between 0 and "
                                 f"{da.sizes['bottom_top'] - 1} for {var}")
            da = da.isel(bottom_top=level)
        da = da.squeeze(drop=True)
        if (da.sizes["south_north"], da.sizes["west_east"]) != shape:
            raise SystemExit(f"{var} in {path} is {da.sizes['west_east']} x "
                             f"{da.sizes['south_north']} but the output grid is "
                             f"{shape[1]} x {shape[0]}: the emissions must be on the "
                             f"FLEXPART output grid")
        # one emission field per output step; steps the inventory does not cover are NaN
        aligned = da.reindex(emis_time=times, method="nearest",
                             tolerance=np.timedelta64(30, "m"))
        fields[var] = aligned.rename({"emis_time": "Time"}).chunk({"Time": chunk})
    return fields, stamps


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("flxout", help="the raw FLEXPART-WRF output file")
    ap.add_argument("--emis", required=True, metavar="FILE",
                    help="NetCDF holding the time-varying emissions, on the output grid")
    ap.add_argument("--var", required=True, nargs="+", metavar="NAME",
                    help="which emission variables to accumulate")
    ap.add_argument("--emis-level", type=int, default=0, metavar="N",
                    help="model level of the emissions, if they have one (default: 0)")
    ap.add_argument("--hours", type=float, default=HOURS, metavar="H",
                    help=f"length of the backward window (default: {HOURS:g})")
    ap.add_argument("--below", type=float, metavar="METRES",
                    help="use only the output layers below this height (default: all)")
    ap.add_argument("--header", metavar="FILE", help="the header file, if not beside the input")
    ap.add_argument("--species", type=int, default=0, metavar="N",
                    help="which FLEXPART species, 0-based (default: 0)")
    ap.add_argument("--chunk", type=int, default=10, metavar="N",
                    help="output steps held in memory at a time (default: 10)")
    ap.add_argument("-o", "--output", metavar="CSV",
                    help="where to write (default: from the input name)")
    a = ap.parse_args(argv)

    if not os.path.exists(a.flxout):
        raise SystemExit(f"no such file: {a.flxout}")
    ds = xr.open_dataset(a.flxout, chunks={"Time": a.chunk})
    if "Time" not in ds.dims:
        raise SystemExit(f"{a.flxout} has no Time dimension: this needs the raw flxout, "
                         f"not a file from reduce_output.py, because the emissions vary "
                         f"in time")
    if "CONC" not in ds:
        raise SystemExit(f"{a.flxout} has no CONC variable: it is not a FLEXPART-WRF output")

    fp = ds["CONC"]
    if "releases" not in fp.dims:
        raise SystemExit("CONC has no releases dimension: this is a forward run, and "
                         "these scripts analyse backward (receptor-oriented) runs")
    if "species" in fp.dims:
        fp = fp.isel(species=a.species)
    if "ageclass" in fp.dims:
        fp = fp.sum("ageclass")

    header = xr.open_dataset(a.header or find_header(a.flxout))
    arrivals = release_times(header, ds.attrs)
    times = stamps_of(ds, "Times")
    if np.isnat(times).any():
        raise SystemExit(f"{a.flxout} has output steps with an unreadable Times entry")

    if a.below is not None:
        ztop = header["ZTOP"].values
        keep = ztop <= a.below
        if not keep.any():
            raise SystemExit(f"no output layer lies below {a.below:g} m; the lowest top "
                             f"is {ztop.min():g} m")
        fp = fp.isel(bottom_top=np.flatnonzero(keep))
    fp = fp.sum("bottom_top").transpose("Time", "releases", "south_north", "west_east")

    shape = (fp.sizes["south_north"], fp.sizes["west_east"])
    fields, emis_stamps = read_emissions(a.emis, a.var, a.emis_level, shape, times, a.chunk)

    covered = int(np.isfinite(fields[a.var[0]].isel(south_north=0, west_east=0).values).sum())
    print(f"{os.path.basename(a.flxout)}: {fp.sizes['releases']} releases, "
          f"{fp.sizes['Time']} output steps, {shape[1]} x {shape[0]} cells")
    print(f"  output steps {str(times.min())[:16]} .. {str(times.max())[:16]} UTC")
    print(f"  {os.path.basename(a.emis)}: {str(emis_stamps.min())[:16]} .. "
          f"{str(emis_stamps.max())[:16]} UTC, matching {covered} of {len(times)} steps")
    if covered == 0:
        raise SystemExit("the emission file covers none of the output steps")

    # the domain total of footprint x emissions, for every (output step, release) pair;
    # each release then sums the steps inside its own backward window
    from dask.diagnostics import ProgressBar
    print(f"  accumulating {', '.join(a.var)} over a {a.hours:g} h window...")
    with ProgressBar():
        products = {var: (fp * field.fillna(0.0))
                    .sum(("south_north", "west_east")).compute().values
                    for var, field in fields.items()}

    window = np.timedelta64(int(round(a.hours * 3600)), "s")
    ame = {var: np.zeros(fp.sizes["releases"]) for var in a.var}
    steps = np.zeros(fp.sizes["releases"], dtype=int)
    for r, arrival in enumerate(arrivals):
        inside = (times <= arrival) & (times > arrival - window)
        steps[r] = inside.sum()
        for var in a.var:
            ame[var][r] = products[var][inside, r].sum()
    if not steps.any():
        raise SystemExit(f"no release has any output step inside a {a.hours:g} h window; "
                         f"the arrivals ({str(arrivals.min())[:16]} .. "
                         f"{str(arrivals.max())[:16]}) and the output steps do not line up")
    print(f"  window holds {steps.min()}..{steps.max()} output steps per release")

    stem = os.path.splitext(os.path.basename(a.flxout))[0]
    out = a.output or f"{stem}_AME.csv"
    with open(out, "w") as fh:
        fh.write("release_time," + ",".join(a.var) + "\n")
        for r, arrival in enumerate(arrivals):
            fh.write(f"{arrival}," + ",".join(f"{ame[var][r]:.6g}" for var in a.var) + "\n")
    for var in a.var:
        print(f"  {var}: {ame[var].min():.4g} .. {ame[var].max():.4g}, "
              f"mean {ame[var].mean():.4g}")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
