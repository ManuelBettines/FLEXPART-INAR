#!/usr/bin/env python3
"""Write the FLEXPART v11 RELEASES file (and, with --outgrid, the OUTGRID file).

A v11 RELEASES file is Fortran namelist: one &RELEASES_CTRL group naming the species,
then one &RELEASE group per release. A backward (footprint) run releases every hour
over the whole simulation period, so the file is hundreds of near-identical blocks —
exactly the thing not to write by hand.

    ./generate_releases.py --command ../options/COMMAND -o ../options/RELEASES \\
        --lat -15.79 --lon -71.86 --box 10 --z1 5967 --z2 6067 --zkind 2 \\
        --specnum 23 --mass 8.6924e4 --npart 240000 --every 86400

The simulation period and direction come from the COMMAND file, so the releases cannot
fall outside it — which is the error FLEXPART reports as

    FLEXPART MODEL ERROR
    Release starts before simulation begins or ends after simulation stops.

and which readreleases (src/readoptions_mod.f90:2505) raises for BOTH directions,
because for a backward run readcommand swaps the two dates internally: whatever the
direction, every release must lie inside [IBDATE IBTIME, IEDATE IETIME] as written in
COMMAND.

With --outgrid it also writes the OUTGRID file. Note that NUMXGRID/NUMYGRID count
grid CELLS, not points, despite the "= No. of cells + 1" comment in the file shipped
upstream: readoutgrid checks `outlon0 + numxgrid*dxout` against the edge of the
meteorological domain (src/readoptions_mod.f90:1576).

Give --control (a flex_extract CONTROL file) and both the release box and the output
grid are checked against the area that was actually retrieved, which is the other way
a run dies minutes after submission:

    #### FLEXPART MODEL ERROR! PART OF OUTPUT GRID IS OUTSIDE MODEL DOMAIN.

Re-run it with different options as often as you like: it rewrites, it does not
append, and it keeps the previous file as FILE.bak.

Written for the FLEXPART v11 setup at INAR / University of Helsinki.
"""
import argparse
import math
import os
import re
import shutil
import sys
from datetime import datetime, timedelta

MAXOUTLEV = 500     # readoptions_mod.f90:1519
MAXSPEC_NML = 50    # readreleases allocates specnum_rel with nspec_init=50

ZKIND_HELP = {1: "m above ground", 2: "m above sea level", 3: "pressure (hPa)"}


# ---------------------------------------------------------------- small helpers

def parse_stamp(text):
    """'YYYYMMDD', 'YYYYMMDD HHMMSS' or 'YYYYMMDDHHMMSS' -> datetime."""
    compact = text.replace(" ", "").replace("-", "").replace(":", "").replace("_", "")
    if len(compact) == 8:
        return datetime.strptime(compact, "%Y%m%d")
    if len(compact) == 14:
        return datetime.strptime(compact, "%Y%m%d%H%M%S")
    raise argparse.ArgumentTypeError(
        f"cannot read date/time {text!r} -- use YYYYMMDD or 'YYYYMMDD HHMMSS'")


def read_command(path):
    """Simulation period and direction from a COMMAND file -> (start, end, ldirect)."""
    try:
        text = open(path).read()
    except OSError as exc:
        raise SystemExit(f"cannot read {path}: {exc}")

    def get(key, default=None):
        m = re.search(rf"^\s*{key}\s*=\s*(-?\d+)", text, re.M | re.I)
        if m:
            return int(m.group(1))
        if default is not None:
            return default
        raise SystemExit(f"{path}: no {key} found — is this a v11 namelist COMMAND?")

    ibdate, ibtime = get("IBDATE"), get("IBTIME", 0)
    iedate, ietime = get("IEDATE"), get("IETIME", 0)
    ldirect = get("LDIRECT", 1)
    start = datetime.strptime(f"{ibdate:08d}{ibtime:06d}", "%Y%m%d%H%M%S")
    end = datetime.strptime(f"{iedate:08d}{ietime:06d}", "%Y%m%d%H%M%S")
    if end <= start:
        raise SystemExit(f"{path}: IEDATE/IETIME is not after IBDATE/IBTIME")
    return start, end, ldirect


def read_control(path):
    """Retrieved area from a flex_extract CONTROL file -> (lon0, lat0, lon1, lat1, res).

    LEFT/RIGHT/LOWER/UPPER and GRID are what flex_extract sends to MARS/CDS, so they
    are exactly the edges of the GRIB fields FLEXPART will read.
    """
    try:
        text = open(path).read()
    except OSError as exc:
        raise SystemExit(f"cannot read {path}: {exc}")

    def get(key):
        m = re.search(rf"^\s*{key}\s+(-?[\d.]+)", text, re.M | re.I)
        return float(m.group(1)) if m else None

    left, right = get("LEFT"), get("RIGHT")
    lower, upper = get("LOWER"), get("UPPER")
    grid = get("GRID")
    if None in (left, right, lower, upper):
        print(f"warning: {path} has no LEFT/RIGHT/LOWER/UPPER (a global retrieval?); "
              f"skipping the domain check", file=sys.stderr)
        return None
    return left, lower, right, upper, grid


def fmt_seconds(sec):
    sec = int(sec)
    if sec % 86400 == 0:
        return f"{sec // 86400} day(s)"
    if sec % 3600 == 0:
        return f"{sec // 3600} h"
    if sec % 60 == 0:
        return f"{sec // 60} min"
    return f"{sec} s"


# ---------------------------------------------------------------- the release box

def release_box(a, ap):
    """-> (lon1, lat1, lon2, lat2), the SW and NE corners of the release box."""
    corners = (a.lon1, a.lat1, a.lon2, a.lat2)
    centre = (a.lon, a.lat)
    if all(v is not None for v in corners):
        if any(v is not None for v in centre):
            ap.error("give either --lat/--lon (+ --box) or the four corners, not both")
        lon1, lat1, lon2, lat2 = corners
    elif all(v is not None for v in centre):
        if a.box_deg is not None:
            dlat = dlon = a.box_deg / 2.0
        else:
            # --box is a side length in km; convert with the local metre-per-degree.
            half = a.box / 2.0
            dlat = half / 111.32
            coslat = math.cos(math.radians(a.lat))
            if abs(coslat) < 1e-6:
                ap.error("--box in km is meaningless at the pole; use --box-deg")
            dlon = half / (111.32 * coslat)
        lon1, lon2 = a.lon - dlon, a.lon + dlon
        lat1, lat2 = a.lat - dlat, a.lat + dlat
    else:
        ap.error("where is the release? give --lat and --lon (with --box or "
                 "--box-deg), or all four of --lon1 --lat1 --lon2 --lat2")

    if lon2 < lon1 or lat2 < lat1:
        ap.error("the release box corners are the wrong way round: give the "
                 "south-west corner (--lon1/--lat1) first")
    if not -90.0 <= lat1 <= 90.0 or not -90.0 <= lat2 <= 90.0:
        ap.error("release latitudes must be within [-90, 90]")
    return lon1, lat1, lon2, lat2


def check_in_domain(what, lon1, lat1, lon2, lat2, domain):
    """Warn if a box is not inside the retrieved meteorological domain."""
    if domain is None:
        return
    dlon0, dlat0, dlon1, dlat1 = domain[:4]
    outside = []
    if lon1 < dlon0 - 1e-6 or lon2 > dlon1 + 1e-6:
        outside.append(f"longitude {lon1:g}..{lon2:g} vs {dlon0:g}..{dlon1:g}")
    if lat1 < dlat0 - 1e-6 or lat2 > dlat1 + 1e-6:
        outside.append(f"latitude {lat1:g}..{lat2:g} vs {dlat0:g}..{dlat1:g}")
    if outside:
        print(f"ERROR-IN-WAITING: the {what} is not inside the retrieved domain "
              f"({'; '.join(outside)}). FLEXPART will stop.", file=sys.stderr)
    else:
        print(f"{what} is inside the retrieved domain", file=sys.stderr)


# ---------------------------------------------------------------- release times

def release_times(a, ap, sim_start, sim_end):
    """-> [(start, end), ...] one entry per &RELEASE block."""
    start = a.start or sim_start
    every = timedelta(seconds=a.every)
    duration = timedelta(seconds=a.duration if a.duration is not None else a.every)
    if a.duration == 0:
        duration = timedelta(0)

    # Default: keep releasing until the LAST one ends at the simulation end.
    end = a.end or (sim_end - duration)
    if end < start:
        ap.error(f"nothing to release: the last release would have to start at "
                 f"{end:%Y-%m-%d %H:%M} but the first is at {start:%Y-%m-%d %H:%M} "
                 f"(a release of {fmt_seconds(duration.total_seconds())} has to fit "
                 f"inside the simulation period)")

    out, t = [], start
    while t <= end:
        out.append((t, t + duration))
        if every.total_seconds() == 0:
            break
        t += every
    if not out:
        ap.error("no releases generated — check --start/--end/--every")

    first, last = out[0][0], out[-1][1]
    if first < sim_start or last > sim_end:
        print(f"ERROR-IN-WAITING: releases run {first:%Y-%m-%d %H:%M} -> "
              f"{last:%Y-%m-%d %H:%M} but the simulation period in COMMAND is "
              f"{sim_start:%Y-%m-%d %H:%M} -> {sim_end:%Y-%m-%d %H:%M}. FLEXPART "
              f"stops with 'Release starts before simulation begins or ends after "
              f"simulation stops'.", file=sys.stderr)
    return out


# ---------------------------------------------------------------- rendering

def releases_text(a, blocks, box, masses):
    """The whole RELEASES file: banner, &RELEASES_CTRL, then one &RELEASE per block."""
    lon1, lat1, lon2, lat2 = box
    stars = "*" * 111

    def banner(text=""):
        return "*" + text.center(109) + "*"

    head = [
        stars,
        banner(),
        banner(f"FLEXPART v11 RELEASES — {len(blocks)} release(s), "
               f"{a.npart} particles each"),
        banner(f"generated by generate_releases.py on {datetime.now():%Y-%m-%d %H:%M}"),
        banner(),
        stars,
        "&RELEASES_CTRL",
        f" NSPEC      = {len(a.specnum):11d}, ! Total number of species",
        f" SPECNUM_REL= {', '.join(str(s) for s in a.specnum):>11}, "
        f"! Species number(s), i.e. SPECIES/SPECIES_NNN",
        " /",
    ]

    # MASS is an array of NSPEC values; a single species is just a one-element list.
    mass_str = ", ".join(f"{m:.4E}" for m in masses)
    body = []
    for i, (t1, t2) in enumerate(blocks, start=a.first_index):
        # character*40 in readreleases; a longer comment is silently truncated.
        comment = f'"{a.name}{i}"'[:40]
        body += [
            "&RELEASE",
            f" IDATE1  = {t1:%Y%m%d}, ! Release start date, YYYYMMDD",
            f" ITIME1  =   {t1:%H%M%S}, ! Release start time in UTC, HHMISS",
            f" IDATE2  = {t2:%Y%m%d}, ! Release end date",
            f" ITIME2  =   {t2:%H%M%S}, ! Release end time",
            f" LON1    = {lon1:14.5f}, ! Left longitude of release box",
            f" LON2    = {lon2:14.5f}, ! Right longitude of release box",
            f" LAT1    = {lat1:14.5f}, ! Lower latitude of release box",
            f" LAT2    = {lat2:14.5f}, ! Upper latitude of release box",
            f" Z1      = {a.z1:14.3f}, ! Lower height of release box",
            f" Z2      = {a.z2:14.3f}, ! Upper height of release box",
            f" ZKIND   = {a.zkind:14d}, ! Reference level ({ZKIND_HELP[a.zkind]})",
            f" MASS    = {mass_str:>14}, ! Total mass emitted, one value per species",
            f" PARTS   = {a.npart:14d}, ! Number of particles released",
            f" COMMENT = {comment:>14}, ! Comment",
            " /",
        ]
    return "\n".join(head + body) + "\n"


def outgrid_text(lon0, lat0, numx, numy, dx, dy, levels):
    head = [
        "!" + "*" * 78,
        "!" + " " * 78 + "!",
        "!      Input file for the Lagrangian particle dispersion model FLEXPART"
        .ljust(79) + "!",
        "!                       Please specify your output grid".ljust(79) + "!",
        "!" + " " * 78 + "!",
        "! NUMXGRID / NUMYGRID count grid CELLS, not points: the grid spans".ljust(79) + "!",
        "!   OUTLON0 .. OUTLON0 + NUMXGRID*DXOUT   (and the same in y),".ljust(79) + "!",
        "! all of which must lie inside the meteorological domain.".ljust(79) + "!",
        "! OUTHEIGHTS are the UPPER boundaries of the layers, in metres above ground."
        .ljust(79) + "!",
        "!" + " " * 78 + "!",
        "!" + "*" * 78,
        "&OUTGRID",
        "",
        f" OUTLON0={lon0:12.4f},",
        f" OUTLAT0={lat0:12.4f},",
        f" NUMXGRID={numx:11d},",
        f" NUMYGRID={numy:11d},",
        f" DXOUT={dx:14.5f},",
        f" DYOUT={dy:14.5f},",
    ]
    lev = ", ".join(f"{z:g}." if float(z).is_integer() else f"{z:g}" for z in levels)
    head.append(f" OUTHEIGHTS= {lev}")
    head.append(" /")
    return "\n".join(head) + "\n"


# ---------------------------------------------------------------- output levels

def build_levels(a, ap):
    """The vertical levels of the output grid: --levels, --dz, --nlevels or --log."""
    given = [x is not None for x in (a.levels, a.dz, a.nlevels, a.log_levels)]
    if sum(given) != 1:
        ap.error("--outgrid needs the vertical resolution: exactly one of --levels, "
                 "--dz (with --ztop), --nlevels (with --ztop) or --log-levels "
                 "(with --ztop)")
    if a.levels:
        try:
            levels = [float(v) for v in re.split(r"[,\s]+", a.levels.strip()) if v]
        except ValueError:
            ap.error("--levels must be a comma- or space-separated list of heights")
    else:
        if a.ztop is None:
            ap.error("--dz/--nlevels/--log-levels need --ztop, the top of the output "
                     "grid in metres")
        if a.ztop <= 0:
            ap.error("--ztop must be positive")
        if a.dz is not None:
            if a.dz <= 0:
                ap.error("--dz must be positive")
            n = int(round(a.ztop / a.dz))
            levels = [a.dz * k for k in range(1, n + 1)]
        elif a.nlevels is not None:
            if a.nlevels < 1:
                ap.error("--nlevels must be at least 1")
            levels = [a.ztop * k / a.nlevels for k in range(1, a.nlevels + 1)]
        else:
            levels = log_levels(a, ap)
    if not levels:
        ap.error("no output levels")
    levels = [round(z, 1) for z in levels]
    if levels[0] <= 0 or any(b <= x for x, b in zip(levels, levels[1:])):
        ap.error("output levels must be positive and strictly increasing (with "
                 "--log-levels, raise --zfirst or ask for fewer levels)")
    if len(levels) > MAXOUTLEV:
        ap.error(f"{len(levels)} levels exceeds maxoutlev = {MAXOUTLEV} "
                 f"(readoptions_mod.f90:1519)")
    return levels


def log_levels(a, ap):
    """N levels whose THICKNESS grows geometrically: thin near the ground, thick aloft.

    The first layer is --zfirst metres thick and each one after it is `r` times the one
    below, with `r` chosen so the top layer ends exactly at --ztop. For a footprint run
    the surface layer is the one that matters, and this keeps it thin without spending
    all the levels on the free troposphere.
    """
    n = a.log_levels
    if n < 2:
        ap.error("--log-levels must be at least 2 (use --levels for a single level)")
    dz1 = a.zfirst
    if dz1 <= 0:
        ap.error("--zfirst must be positive")
    if dz1 * n >= a.ztop:
        ap.error(f"--zfirst {dz1:g} m x {n} levels already reaches {dz1 * n:g} m; for "
                 f"levels that grow with height give a smaller --zfirst, fewer levels, "
                 f"or a higher --ztop (now {a.ztop:g} m)")

    def total(r):  # depth reached by n layers with ratio r
        return dz1 * n if abs(r - 1.0) < 1e-12 else dz1 * (r ** n - 1.0) / (r - 1.0)

    lo, hi = 1.0, 2.0
    while total(hi) < a.ztop:
        hi *= 2.0
        if hi > 1e3:
            ap.error("cannot fit logarithmic levels into --ztop; check --zfirst")
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if total(mid) < a.ztop:
            lo = mid
        else:
            hi = mid
    ratio = 0.5 * (lo + hi)

    levels, z, dz = [], 0.0, dz1
    for _ in range(n):
        z += dz
        levels.append(z)
        dz *= ratio
    levels[-1] = a.ztop
    return levels


def write_out(path, text, backup):
    path = os.path.abspath(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if backup and os.path.exists(path):
        shutil.copy2(path, path + ".bak")
        print(f"kept the previous file as {path}.bak", file=sys.stderr)
    with open(path, "w") as fh:
        fh.write(text)
    print(f"-> {path}", file=sys.stderr)


# ---------------------------------------------------------------- main

def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Write the FLEXPART v11 RELEASES file (and optionally OUTGRID).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="See README.md section 4 for worked examples.")

    g = ap.add_argument_group("where it writes")
    g.add_argument("-o", "--output", default="RELEASES", metavar="FILE",
                   help="the RELEASES file to write (default: ./RELEASES); '-' means "
                        "stdout")
    g.add_argument("--command", metavar="FILE",
                   help="the COMMAND file of the run; the simulation period and "
                        "direction are read from it and every release is checked "
                        "against them. Strongly recommended")
    g.add_argument("--control", metavar="FILE",
                   help="a flex_extract CONTROL file; the release box and output grid "
                        "are checked against the area that was retrieved")
    g.add_argument("--no-backup", action="store_true",
                   help="do not keep the previous file as FILE.bak")

    g = ap.add_argument_group("when to release")
    g.add_argument("--start", type=parse_stamp, metavar="'YYYYMMDD HHMMSS'",
                   help="first release (default: the simulation start in --command)")
    g.add_argument("--end", type=parse_stamp, metavar="'YYYYMMDD HHMMSS'",
                   help="no release starts after this (default: so that the last one "
                        "ends at the simulation end)")
    g.add_argument("--every", type=int, default=3600, metavar="SECONDS",
                   help="spacing between releases (default: 3600)")
    g.add_argument("--duration", type=int, metavar="SECONDS",
                   help="length of one release (default: same as --every, i.e. "
                        "back-to-back; 0 makes each one instantaneous)")

    g = ap.add_argument_group("where to release")
    g.add_argument("--lat", type=float, help="centre of the release box, in degrees")
    g.add_argument("--lon", type=float, help="centre of the release box, in degrees")
    g.add_argument("--box", type=float, default=10.0, metavar="KM",
                   help="side of the box around --lat/--lon, in km (default: 10)")
    g.add_argument("--box-deg", type=float, metavar="DEG", dest="box_deg",
                   help="side of the box in degrees instead of km")
    g.add_argument("--lon1", type=float, help="west edge of the box (with --lat1 etc.)")
    g.add_argument("--lat1", type=float, help="south edge of the box")
    g.add_argument("--lon2", type=float, help="east edge of the box")
    g.add_argument("--lat2", type=float, help="north edge of the box")
    g.add_argument("--z1", type=float, default=0.0, metavar="METRES",
                   help="bottom of the release box (default: 0)")
    g.add_argument("--z2", type=float, default=100.0, metavar="METRES",
                   help="top of the release box (default: 100)")
    g.add_argument("--zkind", type=int, default=1, choices=(1, 2, 3),
                   help="1 = m above ground (default), 2 = m above sea level, "
                        "3 = pressure in hPa")

    g = ap.add_argument_group("what to release")
    g.add_argument("--specnum", type=int, action="append", metavar="N",
                   help="species number, i.e. the NNN of options/SPECIES/SPECIES_NNN; "
                        "repeat for several species (default: 24, AIRTRACER)")
    g.add_argument("--mass", type=float, action="append", metavar="KG",
                   help="mass released per release and per species; repeat in the "
                        "same order as --specnum (default: 1.0). For a backward run "
                        "the value is irrelevant, use 1.0")
    g.add_argument("--npart", type=int, default=10000, metavar="N",
                   help="particles per release (default: 10000)")
    g.add_argument("--name", default="release", metavar="STEM",
                   help="blocks are commented release1, release2, ... (default: "
                        "'release'). The comment is truncated to 40 characters")
    g.add_argument("--first-index", type=int, default=1, metavar="N",
                   dest="first_index",
                   help="number the first block from here instead of 1")

    g = ap.add_argument_group("the output grid (only with --outgrid)")
    g.add_argument("--outgrid", metavar="FILE", nargs="?", const="OUTGRID",
                   help="also write an OUTGRID file here (default name: OUTGRID)")
    g.add_argument("--outlon0", type=float, help="west edge of the output grid")
    g.add_argument("--outlat0", type=float, help="south edge of the output grid")
    g.add_argument("--outlon1", type=float, help="east edge of the output grid")
    g.add_argument("--outlat1", type=float, help="north edge of the output grid")
    g.add_argument("--res", type=float, metavar="DEG",
                   help="output cell size in degrees (sets both DXOUT and DYOUT)")
    g.add_argument("--dxout", type=float, metavar="DEG", help="DXOUT, if not --res")
    g.add_argument("--dyout", type=float, metavar="DEG", help="DYOUT, if not --res")
    g.add_argument("--levels", metavar="LIST",
                   help="exactly these level tops, in metres: '250,500,2000'")
    g.add_argument("--dz", type=float, metavar="METRES",
                   help="evenly spaced levels of this thickness, up to --ztop")
    g.add_argument("--nlevels", type=int, metavar="N",
                   help="N evenly spaced levels up to --ztop")
    g.add_argument("--log-levels", type=int, metavar="N", dest="log_levels",
                   help="N levels, thin at the ground and thickening with height, "
                        "up to --ztop")
    g.add_argument("--zfirst", type=float, default=50.0, metavar="METRES",
                   help="thickness of the lowest layer with --log-levels (default: 50)")
    g.add_argument("--ztop", type=float, metavar="METRES",
                   help="top of the output grid, for --dz/--nlevels/--log-levels")

    a = ap.parse_args(argv)

    a.specnum = a.specnum or [24]
    if len(a.specnum) > MAXSPEC_NML:
        ap.error(f"at most {MAXSPEC_NML} species can be given in RELEASES")
    masses = a.mass or [1.0]
    if len(masses) == 1 and len(a.specnum) > 1:
        masses = masses * len(a.specnum)
    if len(masses) != len(a.specnum):
        ap.error(f"{len(a.specnum)} species but {len(masses)} --mass value(s): give "
                 f"one --mass per --specnum, or a single one for all of them")
    if a.npart <= 0:
        ap.error("--npart must be positive (a release with zero particles makes "
                 "FLEXPART stop: 'At least for one release point, there are zero "
                 "particles released')")
    if a.every < 0 or (a.duration is not None and a.duration < 0):
        ap.error("--every and --duration cannot be negative")
    if a.z2 < a.z1:
        ap.error("--z2 is below --z1")

    domain = read_control(a.control) if a.control else None

    if a.command:
        sim_start, sim_end, ldirect = read_command(a.command)
        print(f"COMMAND: {'forward' if ldirect > 0 else 'backward'} run, "
              f"{sim_start:%Y-%m-%d %H:%M} -> {sim_end:%Y-%m-%d %H:%M}", file=sys.stderr)
    else:
        if not a.start or not a.end:
            ap.error("without --command you must give both --start and --end")
        sim_start, sim_end, ldirect = a.start, a.end, 1
        print("note: no --command given, so the releases are not checked against the "
              "simulation period", file=sys.stderr)

    box = release_box(a, ap)
    blocks = release_times(a, ap, sim_start, sim_end)
    check_in_domain("release box", *box, domain)

    print(f"{len(blocks)} release(s), {a.npart} particles each "
          f"({len(blocks) * a.npart:,} in total), every "
          f"{fmt_seconds(a.every)} from {blocks[0][0]:%Y-%m-%d %H:%M} to "
          f"{blocks[-1][1]:%Y-%m-%d %H:%M}", file=sys.stderr)
    print(f"box {box[0]:g}..{box[2]:g} E, {box[1]:g}..{box[3]:g} N, "
          f"{a.z1:g}..{a.z2:g} ({ZKIND_HELP[a.zkind]})", file=sys.stderr)

    text = releases_text(a, blocks, box, masses)
    if a.output == "-":
        sys.stdout.write(text)
    else:
        write_out(a.output, text, not a.no_backup)

    # ---- the output grid -------------------------------------------------------
    if a.outgrid:
        need = (a.outlon0, a.outlat0, a.outlon1, a.outlat1)
        if any(v is None for v in need):
            if domain is None:
                ap.error("--outgrid needs --outlon0/--outlat0/--outlon1/--outlat1, or "
                         "a --control file to take the retrieved domain from")
            lon0, lat0, lon1, lat1 = domain[:4]
            print("output grid: covering the whole retrieved domain", file=sys.stderr)
        else:
            lon0, lat0, lon1, lat1 = need
        dx = a.dxout if a.dxout is not None else a.res
        dy = a.dyout if a.dyout is not None else a.res
        if dx is None or dy is None:
            if domain is not None and domain[4]:
                dx = dy = domain[4]
                print(f"output grid: no --res given, using the retrieval's GRID "
                      f"({dx:g} deg)", file=sys.stderr)
            else:
                ap.error("--outgrid needs --res (or --dxout and --dyout)")
        if dx <= 0 or dy <= 0:
            ap.error("the output cell size must be positive")

        numx = int(math.floor((lon1 - lon0) / dx + 1e-9))
        numy = int(math.floor((lat1 - lat0) / dy + 1e-9))
        if numx < 1 or numy < 1:
            ap.error(f"a cell size of {dx:g} x {dy:g} deg is larger than the requested "
                     f"output area")
        levels = build_levels(a, ap)

        check_in_domain("output grid", lon0, lat0, lon0 + numx * dx,
                        lat0 + numy * dy, domain)
        print(f"output grid: {numx} x {numy} cells of {dx:g} x {dy:g} deg covering "
              f"{lon0:g}..{lon0 + numx * dx:g} E, {lat0:g}..{lat0 + numy * dy:g} N, "
              f"{len(levels)} levels up to {levels[-1]:g} m", file=sys.stderr)
        if abs(lon0 + numx * dx - lon1) > 1e-6 or abs(lat0 + numy * dy - lat1) > 1e-6:
            print(f"note: the area is not a whole number of cells; the grid stops at "
                  f"{lon0 + numx * dx:g} E / {lat0 + numy * dy:g} N", file=sys.stderr)

        write_out(a.outgrid, outgrid_text(lon0, lat0, numx, numy, dx, dy, levels),
                  not a.no_backup)


if __name__ == "__main__":
    main()
