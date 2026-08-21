#!/usr/bin/env python3
"""Generate a FLEXPART-WRF AVAILABLE file.

AVAILABLE tells FLEXPART, for every time step it may need, which wrfout file holds
that time frame. It has three header lines (skipped by the model) followed by one
row per time step:

    YYYYMMDD HHMMSS<TAB><TAB>'wrfout_dNN_YYYY-MM-DD_HH:MM:SS' ' '

The subtlety is that WRF usually writes SEVERAL time frames per file. If your WRF run
writes one file per day holding 24 hourly frames, then all 24 rows of that day must
name the SAME file — the one stamped at the start of the file, not at the time step.
That is what --hours-per-file does (24 = one file per day, the default; 1 = one file
per time step).

Examples
--------
  # one wrfout file per day, hourly frames (the Izana setup)
  ./generate_available.py --start 20220321 --end 20220627 > AVAILABLE1

  # domain 2, 30-min frames, 6 frames per file
  ./generate_available.py --start 20220321 --end 20220627 \\
      --domain 2 --interval 1800 --hours-per-file 3 > AVAILABLE2

Written for the FLEXPART-WRF setup at INAR / University of Helsinki.
"""
import argparse
import sys
from datetime import datetime, timedelta

HEADER = [
    "XXXXXX EMPTY LINES XXXXXXXXX",
    "XXXXXX EMPTY LINES XXXXXXXX",
    "YYYYMMDD HHMMSS   name of the file(up to 80 characters)",
]


def parse_stamp(text):
    """Accept 'YYYYMMDD', 'YYYYMMDD HHMMSS' or 'YYYYMMDDHHMMSS'."""
    compact = text.replace(" ", "").replace("-", "").replace(":", "")
    if len(compact) == 8:
        return datetime.strptime(compact, "%Y%m%d")
    if len(compact) == 14:
        return datetime.strptime(compact, "%Y%m%d%H%M%S")
    raise argparse.ArgumentTypeError(
        f"cannot read date/time {text!r} — use YYYYMMDD or 'YYYYMMDD HHMMSS'")


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Generate a FLEXPART-WRF AVAILABLE file (writes to stdout).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("Examples")[1] if "Examples" in __doc__ else None)
    ap.add_argument("--start", required=True, type=parse_stamp,
                    help="first time step, YYYYMMDD or 'YYYYMMDD HHMMSS'")
    ap.add_argument("--end", required=True, type=parse_stamp,
                    help="last time step (inclusive)")
    ap.add_argument("--interval", type=int, default=3600,
                    help="seconds between wrfout time frames (default: 3600)")
    ap.add_argument("--hours-per-file", type=float, default=24.0,
                    help="hours of data in ONE wrfout file (default: 24, i.e. one "
                         "file per day; use 1 for one file per hourly frame)")
    ap.add_argument("--domain", type=int, default=1,
                    help="WRF domain number, the NN in wrfout_dNN (default: 1)")
    ap.add_argument("--prefix", default="wrfout",
                    help="file name prefix (default: wrfout)")
    ap.add_argument("--no-header", action="store_true",
                    help="omit the three header lines")
    ap.add_argument("-o", "--output", help="write here instead of stdout")
    args = ap.parse_args(argv)

    if args.end < args.start:
        ap.error("--end is before --start")
    if args.interval <= 0:
        ap.error("--interval must be positive")
    if args.hours_per_file <= 0:
        ap.error("--hours-per-file must be positive")

    file_span = timedelta(hours=args.hours_per_file)
    step = timedelta(seconds=args.interval)

    lines = [] if args.no_header else list(HEADER)
    t = args.start
    while t <= args.end:
        # start time of the wrfout file that contains this frame
        n_files = int((t - args.start) / file_span)
        file_start = args.start + n_files * file_span
        name = (f"{args.prefix}_d{args.domain:02d}_"
                f"{file_start.strftime('%Y-%m-%d_%H:%M:%S')}")
        lines.append(f"{t.strftime('%Y%m%d %H%M%S')}\t\t'{name}' ' '")
        t += step

    text = "\n".join(lines) + "\n"
    if args.output:
        with open(args.output, "w") as fh:
            fh.write(text)
        print(f"wrote {len(lines)} lines to {args.output}", file=sys.stderr)
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()
