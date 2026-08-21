#!/usr/bin/env python3
"""Generate the RELEASES blocks of a FLEXPART-WRF flexwrf.input file.

Backward (receptor-oriented) runs typically release particles from the same box once
per hour over the whole simulation period, which means hundreds or thousands of nearly
identical 12-line blocks. This writes them -- and, with --input, writes them straight
into the flexwrf.input file you point it at:

    ./generate_releases.py --input flexwrf.input --wrf /scratch/.../wrfout/ \\
        --lat 28.309 --lon -16.499 --box 1000 --z1 0 --z2 10 --npart 10000

Give the release position in degrees (--lat/--lon, or the corners --lat1/--lon1/
--lat2/--lon2) and it is converted to the WRF grid metres FLEXPART wants, using the
XLONG/XLAT fields of the wrfout file named by --wrf. Grid metres (--x1/--y1/--x2/--y2)
still work if you prefer them.

--outgrid additionally rebuilds the OUTGRID section to match the WRF grid exactly --
same origin, same cell size, same extent, or a coarser multiple of it with
--outgrid-res. The vertical levels are yours to choose: an explicit --levels list,
even spacing with --dz/--ztop or --nlevels/--ztop, or logarithmic spacing that keeps
the resolution near the ground where a footprint run needs it:

    ./generate_releases.py --input flexwrf.input --wrf /scratch/.../wrfout/ \\
        --lat 28.309 --lon -16.499 --outgrid --log-levels 20 --zfirst 20 --ztop 7000

Everything after the NUMPOINT line is replaced by the new blocks, NUMPOINT is set to
their count, and the original is kept as flexwrf.input.bak. Without --start / --end the
release period is taken from the simulation beginning/ending dates already in that
file, so the releases always fit inside the modelled window.

Without --input the blocks go to stdout (or -o FILE) and NUMPOINT is yours to set:

    ./generate_releases.py --start "20220508 040000" --end "20220627 000000" \\
        --x1 177000 --y1 98000 --x2 178000 --y2 99000 > releases.txt
    # -> "1196 release blocks -> set NUMPOINT to 1196" on stderr

Coordinate units follow RELEASE_COORD / OUTGRID_COORD in flexwrf.input: 0 = WRF grid
metres, 1 = degrees. This script writes metres and sets both switches to 0 for you.

Written for the FLEXPART-WRF setup at INAR / University of Helsinki.
"""
import argparse
import os
import re
import shutil
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # for wrfgrid.py

NUMPOINT_RE = re.compile(r"^(?P<pre>\s*)(?P<val>\S+)(?P<gap>\s+)(?P<rest>NUMPOINT\b.*)$")
DATE_RE = re.compile(r"^\s*(\d{8})\s+(\d{6})\b")
OUTGRID_HEAD_RE = re.compile(r"^=+\s*FORMER OUTGRID FILE\s*=+\s*$", re.I)
SEPARATOR_RE = re.compile(r"^=====")


def keyword_re(word):
    return re.compile(rf"^(?P<pre>\s*)(?P<val>\S+)(?P<gap>\s+)(?P<rest>{word}\b.*)$")


def parse_stamp(text):
    compact = text.replace(" ", "").replace("-", "").replace(":", "")
    if len(compact) == 8:
        return datetime.strptime(compact, "%Y%m%d")
    if len(compact) == 14:
        return datetime.strptime(compact, "%Y%m%d%H%M%S")
    raise argparse.ArgumentTypeError(
        f"cannot read date/time {text!r} -- use YYYYMMDD or 'YYYYMMDD HHMMSS'")


def release_block(t_start, t_end, name, a):
    """One 12-line RELEASE block plus its trailing blank line."""
    return (
        f" {t_start.strftime('%Y%m%d %H%M%S')}    ID1, IT1 beginning date and time of release\n"
        f" {t_end.strftime('%Y%m%d %H%M%S')}    ID2, IT2 ending date and time of release\n"
        f" {a.x1}          XPOINT1 (real) longitude [deg] of lower left corner\n"
        f" {a.y1}          YPOINT1 (real) latitude [deg] of lower left corner\n"
        f" {a.x2}          XPOINT2 (real) longitude [deg] of upper right corner\n"
        f" {a.y2}          YPOINT2 (real) latitude [DEG] of upper right corner\n"
        f" {a.kindz}                  KINDZ (int) 1 for m above ground, 2 for m above sea level, 3 pressure\n"
        f" {a.z1:.4f}             ZPOINT1 (real) lower z-level\n"
        f" {a.z2:.4f}           ZPOINT2 (real) upper z-level\n"
        f" {a.npart}               NPART (int) total number of particles to be released\n"
        f" {a.xmass}           XMASS (real) total mass emitted\n"
        f" {name}  NAME OF RELEASE LOCATION\n"
        f"\n"
    )


# ------------------------------------------------------------- flexwrf.input I/O

def read_input(path):
    """-> (lines, index of the NUMPOINT line, simulation start, simulation end)."""
    try:
        with open(path) as fh:
            lines = fh.read().splitlines()
    except OSError as exc:
        raise SystemExit(f"cannot read {path}: {exc}")

    numpoint = None
    sim_start = sim_end = None
    for i, line in enumerate(lines):
        if numpoint is None and NUMPOINT_RE.match(line):
            numpoint = i
        low = line.lower()
        if "date of simulation" in low:
            m = DATE_RE.match(line)
            if m:
                when = datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
                if "beginning" in low:
                    sim_start = when
                elif "ending" in low:
                    sim_end = when
    if numpoint is None:
        raise SystemExit(
            f"{path} has no NUMPOINT line -- is it really a flexwrf.input file?")
    return lines, numpoint, sim_start, sim_end


def set_value(line, value, word="NUMPOINT"):
    """Replace the value on a switch line, keeping the comment column."""
    m = keyword_re(word).match(line)
    width = len(m.group("val")) + len(m.group("gap"))
    gap = " " * max(1, width - len(str(value)))
    return f"{m.group('pre')}{value}{gap}{m.group('rest')}"


def set_switch(lines, word, value):
    """Set a COMMAND switch (RELEASE_COORD, OUTGRID_COORD, ...) if it is not already."""
    rx = keyword_re(word)
    for i, line in enumerate(lines):
        m = rx.match(line)
        if m:
            if m.group("val") != str(value):
                lines[i] = set_value(line, value, word)
                print(f"{word} was {m.group('val')}, set to {value}", file=sys.stderr)
            return True
    print(f"warning: no {word} line found -- check it by hand", file=sys.stderr)
    return False


def outgrid_lines(grid, res, levels):
    """The FORMER OUTGRID FILE block covering the whole WRF domain."""
    xmax, ymax = grid.extent_m()
    numx, numy = int(xmax // res), int(ymax // res)
    if numx < 1 or numy < 1:
        raise SystemExit(f"--outgrid-res {res:g} m is larger than the WRF domain")
    rows = [
        (0, "OUTLONLEFT", "geograhical longitude of lower left corner of output grid"),
        (0, "OUTLATLOWER", "geographical latitude of lower left corner of output grid"),
        (numx, "NUMXGRID", "number of grid points in x direction (= # of cells )"),
        (numy, "NUMYGRID", "number of grid points in y direction (= # of cells )"),
        (0, "OUTGRIDDEF", "outgrid defined 0=using grid distance, 1=upperright corner coordinate"),
        (f"{res:g}", "DXOUTLON", "grid distance in x direction or upper right corner of output grid"),
        (f"{res:g}", "DYOUTLON", "grid distance in y direction or upper right corner of output grid"),
        (len(levels), "NUMZGRID", "number of vertical levels"),
    ]
    out = [f"  {str(v):<19}{k:<16}{c}" for v, k, c in rows]
    out += [f"  {z:<19.1f}{'LEVEL':<16}height of level (upper boundary)" for z in levels]
    print(f"outgrid: {numx} x {numy} cells of {res:g} m covering "
          f"0 .. {numx * res:.0f} m x 0 .. {numy * res:.0f} m of the WRF grid "
          f"({grid.nx} x {grid.ny} points at {grid.dx:g} m), "
          f"{len(levels)} levels up to {levels[-1]:g} m", file=sys.stderr)
    if numx * res < xmax or numy * res < ymax:
        print(f"note: {xmax - numx * res:.0f} m in x and {ymax - numy * res:.0f} m in y "
              f"of the WRF domain are left out (domain not a whole number of output "
              f"cells)", file=sys.stderr)
    return out


def replace_outgrid(lines, block):
    """Swap the FORMER OUTGRID FILE section for `block`; returns the new line list."""
    start = None
    for i, line in enumerate(lines):
        if OUTGRID_HEAD_RE.match(line):
            start = i
            break
    if start is None:
        raise SystemExit("no '=== FORMER OUTGRID FILE ===' section found in the input "
                         "file, cannot write the output grid")
    end = next((i for i in range(start + 1, len(lines)) if SEPARATOR_RE.match(lines[i])),
               None)
    if end is None:
        raise SystemExit("the FORMER OUTGRID FILE section has no closing '=====' line")
    return lines[:start + 1] + block + lines[end:]


def find_numpoint(lines):
    for i, line in enumerate(lines):
        if NUMPOINT_RE.match(line):
            return i
    raise SystemExit("no NUMPOINT line -- is it really a flexwrf.input file?")


def write_input(path, out_path, lines, numpoint, blocks, count, backup):
    head = lines[:numpoint + 1]
    head[numpoint] = set_value(head[numpoint], count)
    text = "\n".join(head) + "\n" + "".join(blocks)
    if out_path is None:
        if backup:
            shutil.copy2(path, path + ".bak")
            print(f"backed up {path} -> {path}.bak", file=sys.stderr)
        out_path = path
    with open(out_path, "w") as fh:
        fh.write(text)
    return out_path


def build_levels(a, ap):
    """The vertical levels of the output grid, from --levels, --dz, --nlevels or --log."""
    given = [x is not None for x in (a.levels, a.dz, a.nlevels, a.log_levels)]
    if sum(given) != 1:
        ap.error("--outgrid needs the vertical resolution: one of --levels, "
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

    levels, z = [], 0.0
    for k in range(n):
        z += dz1 * ratio ** k
        levels.append(z)
    levels[-1] = a.ztop  # exactly, not 6999.97
    print(f"log levels: {n} layers from {dz1:g} m thick at the ground to "
          f"{levels[-1] - levels[-2]:.0f} m at the top (ratio {ratio:.3f}), "
          f"reaching {a.ztop:g} m", file=sys.stderr)
    return levels


def resolve_position(a, ap):
    """Fill a.x1/y1/x2/y2 (grid metres, as strings) from whatever the user gave."""
    ll_corners = [a.lat1, a.lon1, a.lat2, a.lon2]
    point = [a.lat, a.lon]
    if any(v is not None for v in ll_corners) and any(v is not None for v in point):
        ap.error("give either --lat/--lon or the corners --lat1/--lon1/--lat2/--lon2")
    if any(v is not None for v in ll_corners) and not all(v is not None for v in ll_corners):
        ap.error("--lat1, --lon1, --lat2 and --lon2 must all be given together")
    if (a.lat is None) != (a.lon is None):
        ap.error("--lat and --lon must be given together")
    degrees = a.lat is not None or a.lat1 is not None
    grid = None

    if a.wrf:
        import wrfgrid
        grid = wrfgrid.WrfGrid(wrfgrid.find_wrfout(a.wrf))
        print(grid.describe(), file=sys.stderr)
        if not grid.is_mother():
            print(f"warning: {grid.name} is not the mother domain; FLEXPART grid metres "
                  f"are measured on the FIRST domain, so point --wrf at its d01 file",
                  file=sys.stderr)
    elif degrees or a.outgrid:
        ap.error("--wrf is required to turn degrees into grid metres and to build the "
                 "output grid: give the wrfout file (or its directory)")

    if degrees:
        if a.lat is not None:                       # centre point + box size
            half = a.box / 2.0
            x, y, err = grid.ll_to_xymeter(a.lon, a.lat)
            corners = [(x - half, y - half), (x + half, y + half)]
            print(f"release centre {a.lat} N {a.lon} E -> x = {x:.1f} m, y = {y:.1f} m "
                  f"(grid fit {err:.1f} m), box {a.box:g} m", file=sys.stderr)
        else:                                       # two corners
            x1, y1, e1 = grid.ll_to_xymeter(a.lon1, a.lat1)
            x2, y2, e2 = grid.ll_to_xymeter(a.lon2, a.lat2)
            corners = [(min(x1, x2), min(y1, y2)), (max(x1, x2), max(y1, y2))]
            print(f"release box {a.lat1} N {a.lon1} E .. {a.lat2} N {a.lon2} E -> "
                  f"x {corners[0][0]:.1f} .. {corners[1][0]:.1f} m, "
                  f"y {corners[0][1]:.1f} .. {corners[1][1]:.1f} m "
                  f"(grid fit {max(e1, e2):.1f} m)", file=sys.stderr)
        (a.x1, a.y1), (a.x2, a.y2) = [(f"{v:.1f}" for v in c) for c in corners]

    if grid is not None:
        xmax, ymax = grid.extent_m()
        for label, value, limit in (("x", a.x1, xmax), ("x", a.x2, xmax),
                                    ("y", a.y1, ymax), ("y", a.y2, ymax)):
            v = float(value)
            if v < 0 or v > limit:
                print(f"warning: release {label} = {v:.1f} m is outside the domain "
                      f"(0 .. {limit:.0f} m); FLEXPART will stop", file=sys.stderr)
    return grid


# ---------------------------------------------------------------------- driver

def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Generate FLEXPART-WRF RELEASES blocks, optionally writing them "
                    "into a flexwrf.input file.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("\n\n", 1)[1])
    ap.add_argument("--input", metavar="FLEXWRF_INPUT",
                    help="flexwrf.input to write the releases into: everything after "
                         "its NUMPOINT line is replaced by the new blocks and NUMPOINT "
                         "is updated (original kept as FILE.bak)")
    ap.add_argument("--start", type=parse_stamp,
                    help="start of the FIRST release, YYYYMMDD or 'YYYYMMDD HHMMSS' "
                         "(default with --input: the simulation beginning date)")
    ap.add_argument("--end", type=parse_stamp,
                    help="no release starts after this time, inclusive (default with "
                         "--input: the last release ends at the simulation end)")
    ap.add_argument("--every", type=int, default=3600,
                    help="seconds between consecutive releases (default: 3600)")
    ap.add_argument("--duration", type=int, default=None,
                    help="length of one release in seconds (default: same as --every, "
                         "i.e. back-to-back releases with no gap)")
    ap.add_argument("--wrf", metavar="PATH",
                    help="wrfout file (or the directory holding them; the lowest "
                         "domain is used) whose grid degrees are converted against, "
                         "and which --outgrid is built from")
    pos = ap.add_argument_group(
        "release position",
        "in degrees (--lat/--lon or the four corner options, needs --wrf) or "
        "directly in WRF grid metres (--x1/--y1/--x2/--y2)")
    pos.add_argument("--lat", type=float, help="latitude of the release centre [deg]")
    pos.add_argument("--lon", type=float, help="longitude of the release centre [deg]")
    pos.add_argument("--box", type=float, default=1000.0, metavar="METRES",
                     help="side of the release box around --lat/--lon "
                          "(default: 1000 m)")
    pos.add_argument("--lat1", type=float, help="latitude of the lower-left corner")
    pos.add_argument("--lon1", type=float, help="longitude of the lower-left corner")
    pos.add_argument("--lat2", type=float, help="latitude of the upper-right corner")
    pos.add_argument("--lon2", type=float, help="longitude of the upper-right corner")
    pos.add_argument("--x1", default="98000", help="XPOINT1, lower-left x [grid m]")
    pos.add_argument("--y1", default="177000", help="YPOINT1, lower-left y [grid m]")
    pos.add_argument("--x2", default="99000", help="XPOINT2, upper-right x [grid m]")
    pos.add_argument("--y2", default="178000", help="YPOINT2, upper-right y [grid m]")
    og = ap.add_argument_group(
        "output grid",
        "with --outgrid the OUTGRID section is rebuilt from the WRF grid named by "
        "--wrf; the vertical levels are yours to choose")
    og.add_argument("--outgrid", action="store_true",
                    help="rewrite the OUTGRID section to cover the WRF domain "
                         "(needs --input and --wrf)")
    og.add_argument("--outgrid-res", type=float, metavar="METRES",
                    help="output cell size (default: the WRF dx; use a multiple of it "
                         "for a coarser grid)")
    og.add_argument("--levels", metavar="LIST",
                    help="output level tops in metres, e.g. \"250,500,1000,2000\"")
    og.add_argument("--dz", type=float, metavar="METRES",
                    help="evenly spaced levels of this thickness, up to --ztop")
    og.add_argument("--nlevels", type=int, metavar="N",
                    help="N evenly spaced levels up to --ztop")
    og.add_argument("--log-levels", type=int, metavar="N", dest="log_levels",
                    help="N logarithmically spaced levels from --zfirst up to --ztop: "
                         "thin layers near the ground, thicker aloft")
    og.add_argument("--zfirst", type=float, default=50.0, metavar="METRES",
                    help="thickness of the lowest layer for --log-levels; every layer "
                         "above is a constant factor thicker (default: 50 m)")
    og.add_argument("--ztop", type=float, metavar="METRES",
                    help="top of the output grid, for --dz / --nlevels")
    ap.add_argument("--kindz", type=int, default=1, choices=(1, 2, 3),
                    help="1 = m above ground, 2 = m above sea level, 3 = pressure")
    ap.add_argument("--z1", type=float, default=0.0, help="ZPOINT1, lower z-level")
    ap.add_argument("--z2", type=float, default=10.0, help="ZPOINT2, upper z-level")
    ap.add_argument("--npart", type=int, default=10000,
                    help="particles released per block (default: 10000)")
    ap.add_argument("--xmass", default=".1000E+0",
                    help="total mass emitted per block (default: .1000E+0)")
    ap.add_argument("--name", default="release",
                    help="release name stem; blocks are named release1, release2, ... "
                         "(default: release)")
    ap.add_argument("--first-index", type=int, default=1,
                    help="index of the first release name (default: 1)")
    ap.add_argument("--no-backup", action="store_true",
                    help="with --input, do not keep a .bak copy")
    ap.add_argument("-o", "--output", metavar="FILE",
                    help="write here instead of stdout; with --input, write the "
                         "complete new input file here and leave the original alone")
    a = ap.parse_args(argv)

    if a.every <= 0:
        ap.error("--every must be positive")
    if a.outgrid and not a.input:
        ap.error("--outgrid rewrites the OUTGRID section, so it needs --input")
    if a.box <= 0:
        ap.error("--box must be positive")
    duration = timedelta(seconds=a.duration if a.duration is not None else a.every)

    levels = build_levels(a, ap) if a.outgrid else None
    grid = resolve_position(a, ap)

    lines = numpoint = sim_start = sim_end = None
    if a.input:
        lines, numpoint, sim_start, sim_end = read_input(a.input)
        if sim_start and sim_end:
            print(f"{a.input}: simulation {sim_start:%Y-%m-%d %H:%M} -> "
                  f"{sim_end:%Y-%m-%d %H:%M}", file=sys.stderr)

    start, end = a.start, a.end
    if start is None:
        if sim_start is None:
            ap.error("--start is required (no simulation beginning date found"
                     + (f" in {a.input}" if a.input else ""))
        start = sim_start
        print(f"--start not given, using the simulation start {start:%Y%m%d %H%M%S}",
              file=sys.stderr)
    if end is None:
        if sim_end is None:
            ap.error("--end is required (no simulation ending date found"
                     + (f" in {a.input}" if a.input else ""))
        end = sim_end - duration  # so the last release still ends inside the window
        print(f"--end not given, no release starts after {end:%Y%m%d %H%M%S} so the "
              f"last one ends by the simulation end {sim_end:%Y%m%d %H%M%S}",
              file=sys.stderr)
    if end < start:
        ap.error("--end is before --start (with --input, check that the simulation "
                 "window is longer than one release)")

    blocks = []
    t = start
    index = a.first_index
    while t <= end:
        blocks.append(release_block(t, t + duration, f"{a.name}{index}", a))
        t += timedelta(seconds=a.every)
        index += 1
    last_end = start + (len(blocks) - 1) * timedelta(seconds=a.every) + duration

    if sim_start and start < sim_start:
        print(f"warning: first release {start:%Y%m%d %H%M%S} is before the simulation "
              f"start {sim_start:%Y%m%d %H%M%S}; FLEXPART will reject it", file=sys.stderr)
    if sim_end and last_end > sim_end:
        print(f"warning: last release ends {last_end:%Y%m%d %H%M%S}, after the "
              f"simulation end {sim_end:%Y%m%d %H%M%S}; FLEXPART will reject it",
              file=sys.stderr)

    if a.input:
        if a.outgrid:
            res = a.outgrid_res or grid.dx
            if res <= 0:
                ap.error("--outgrid-res must be positive")
            lines = replace_outgrid(lines, outgrid_lines(grid, res, levels))
            set_switch(lines, "OUTGRID_COORD", 0)
            numpoint = find_numpoint(lines)
        set_switch(lines, "RELEASE_COORD", 0)
        written = write_input(a.input, a.output, lines, numpoint, blocks,
                              len(blocks), not a.no_backup)
        print(f"{len(blocks)} release blocks, {start:%Y%m%d %H%M%S} -> "
              f"{last_end:%Y%m%d %H%M%S}; NUMPOINT set to {len(blocks)} in {written}",
              file=sys.stderr)
        return

    text = "".join(blocks)
    if a.output:
        with open(a.output, "w") as fh:
            fh.write(text)
    else:
        sys.stdout.write(text)
    # NUMPOINT in flexwrf.input must equal this number.
    print(f"{len(blocks)} release blocks -> set NUMPOINT to {len(blocks)}",
          file=sys.stderr)


if __name__ == "__main__":
    main()
