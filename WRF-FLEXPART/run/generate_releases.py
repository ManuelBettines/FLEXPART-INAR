#!/usr/bin/env python3
"""Generate the RELEASES blocks of a FLEXPART-WRF flexwrf.input file.

Backward (receptor-oriented) runs typically release particles from the same box once
per hour over the whole simulation period, which means hundreds or thousands of nearly
identical 12-line blocks. This writes them -- and, with --input, writes them straight
into the flexwrf.input file you point it at:

    ./generate_releases.py --input flexwrf.input \\
        --x1 177000 --y1 98000 --x2 178000 --y2 99000 --z1 0 --z2 10 --npart 10000

That replaces everything after the NUMPOINT line with the new blocks, sets NUMPOINT to
their count, and keeps a copy of the original in flexwrf.input.bak. Without --start /
--end the release period is taken from the simulation beginning/ending dates already in
that file, so the releases always fit inside the modelled window.

Without --input the blocks go to stdout (or -o FILE) and NUMPOINT is yours to set:

    ./generate_releases.py --start "20220508 040000" --end "20220627 000000" \\
        --x1 177000 --y1 98000 --x2 178000 --y2 99000 > releases.txt
    # -> "1196 release blocks -> set NUMPOINT to 1196" on stderr

Coordinate units follow RELEASE_COORD in flexwrf.input: 0 = WRF grid metres (the
default here, and what --x1/--y1/--x2/--y2 mean below), 1 = degrees lat/lon.

Written for the FLEXPART-WRF setup at INAR / University of Helsinki.
"""
import argparse
import os
import re
import shutil
import sys
from datetime import datetime, timedelta

NUMPOINT_RE = re.compile(r"^(?P<pre>\s*)(?P<val>\S+)(?P<gap>\s+)(?P<rest>NUMPOINT\b.*)$")
DATE_RE = re.compile(r"^\s*(\d{8})\s+(\d{6})\b")


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


def set_numpoint(line, count):
    """Replace the value on the NUMPOINT line, keeping the comment column."""
    m = NUMPOINT_RE.match(line)
    width = len(m.group("val")) + len(m.group("gap"))
    gap = " " * max(1, width - len(str(count)))
    return f"{m.group('pre')}{count}{gap}{m.group('rest')}"


def write_input(path, out_path, lines, numpoint, blocks, count, backup):
    head = lines[:numpoint + 1]
    head[numpoint] = set_numpoint(head[numpoint], count)
    text = "\n".join(head) + "\n" + "".join(blocks)
    if out_path is None:
        if backup:
            shutil.copy2(path, path + ".bak")
            print(f"backed up {path} -> {path}.bak", file=sys.stderr)
        out_path = path
    with open(out_path, "w") as fh:
        fh.write(text)
    return out_path


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
    ap.add_argument("--x1", default="98000", help="XPOINT1, lower-left x")
    ap.add_argument("--y1", default="177000", help="YPOINT1, lower-left y")
    ap.add_argument("--x2", default="99000", help="XPOINT2, upper-right x")
    ap.add_argument("--y2", default="178000", help="YPOINT2, upper-right y")
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
    duration = timedelta(seconds=a.duration if a.duration is not None else a.every)

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
