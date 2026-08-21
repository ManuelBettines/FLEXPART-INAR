#!/usr/bin/env python3
"""Generate the RELEASES blocks for a FLEXPART-WRF flexwrf.input file.

Backward (receptor-oriented) runs typically release particles from the same box once
per hour over the whole simulation period, which means hundreds or thousands of nearly
identical 12-line blocks. This writes them.

Output is ONLY the release blocks — paste them at the end of flexwrf.input, after the
NUMPOINT line, and set NUMPOINT to the count this script reports on stderr:

    ./generate_releases.py --start "20220508 040000" --end "20220627 000000" \\
        --x1 177000 --y1 98000 --x2 178000 --y2 99000 \\
        --z1 0 --z2 10 --npart 10000 > releases.txt
    # -> "1196 release blocks" on stderr; put 1196 on the NUMPOINT line

Coordinate units follow RELEASE_COORD in flexwrf.input: 0 = WRF grid metres (the
default here, and what --x1/--y1/--x2/--y2 mean below), 1 = degrees lat/lon.

Written for the FLEXPART-WRF setup at INAR / University of Helsinki.
"""
import argparse
import sys
from datetime import datetime, timedelta


def parse_stamp(text):
    compact = text.replace(" ", "").replace("-", "").replace(":", "")
    if len(compact) == 8:
        return datetime.strptime(compact, "%Y%m%d")
    if len(compact) == 14:
        return datetime.strptime(compact, "%Y%m%d%H%M%S")
    raise argparse.ArgumentTypeError(
        f"cannot read date/time {text!r} — use YYYYMMDD or 'YYYYMMDD HHMMSS'")


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


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Generate FLEXPART-WRF RELEASES blocks (writes to stdout).")
    ap.add_argument("--start", required=True, type=parse_stamp,
                    help="start of the FIRST release, YYYYMMDD or 'YYYYMMDD HHMMSS'")
    ap.add_argument("--end", required=True, type=parse_stamp,
                    help="no release starts after this time (inclusive)")
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
    ap.add_argument("-o", "--output", help="write here instead of stdout")
    a = ap.parse_args(argv)

    if a.end < a.start:
        ap.error("--end is before --start")
    if a.every <= 0:
        ap.error("--every must be positive")
    duration = timedelta(seconds=a.duration if a.duration is not None else a.every)

    blocks = []
    t = a.start
    index = a.first_index
    while t <= a.end:
        blocks.append(release_block(t, t + duration, f"{a.name}{index}", a))
        t += timedelta(seconds=a.every)
        index += 1

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
