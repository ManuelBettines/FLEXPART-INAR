#!/usr/bin/env python3
"""Generate FLEXPART-WRF AVAILABLE file(s) by scanning a directory of wrfout files.

AVAILABLE tells FLEXPART, for every time step it may use, which wrfout file holds that
time frame. Three header lines (skipped by the model) then one row per time step:

    YYYYMMDD HHMMSS<TAB><TAB>'wrfout_dNN_YYYY-MM-DD_HH:MM:SS' ' '

Point this script at the directory that holds the wrfout files and it works the rest
out on its own: which domains exist, how many time frames each file contains, and what
the output interval is (hourly, 3-hourly, 6-hourly, one frame per file, ...). The
frame times are read from the `Times` variable inside each file, so a file holding 24
hourly frames produces 24 rows all naming that same file -- which is what FLEXPART
needs, since `readwind.f90` scans a file's `Times` for the step it wants.

Examples
--------
  # every wrfout in the directory, one AVAILABLE per domain found
  ./generate_available.py /scratch/project/user/WRF/wrfout/

  # only domain 1, to a named file
  ./generate_available.py /scratch/.../wrfout/ --domain 1 -o AVAILABLE1

  # restrict to the simulation period, print to stdout
  ./generate_available.py /scratch/.../wrfout/ --start 20220321 --end 20220627 -o -

"""
import argparse
import glob
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta

HEADER = [
    "XXXXXX EMPTY LINES XXXXXXXXX",
    "XXXXXX EMPTY LINES XXXXXXXX",
    "YYYYMMDD HHMMSS   name of the file(up to 80 characters)",
]

MAXWF = 50000  # par_mod.f90: maximum number of wind fields FLEXPART accepts

# wrfout_d01_2022-03-21_00:00:00 , also the colon-free variant WRF writes on
# file systems that dislike ':' (wrfout_d01_2022-03-21_00_00_00)
NAME_RE = re.compile(
    r"^(?P<prefix>.+)_d(?P<domain>\d+)_"
    r"(?P<stamp>\d{4}-\d{2}-\d{2}_\d{2}[:_]\d{2}[:_]\d{2})(?P<tail>.*)$")

WRF_TIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{2}[:_]\d{2}[:_]\d{2}$")


def parse_stamp(text):
    """Accept 'YYYYMMDD', 'YYYYMMDD HHMMSS' or 'YYYYMMDDHHMMSS'."""
    compact = text.replace(" ", "").replace("-", "").replace(":", "").replace("_", "")
    if len(compact) == 8:
        return datetime.strptime(compact, "%Y%m%d")
    if len(compact) == 14:
        return datetime.strptime(compact, "%Y%m%d%H%M%S")
    raise argparse.ArgumentTypeError(
        f"cannot read date/time {text!r} -- use YYYYMMDD or 'YYYYMMDD HHMMSS'")


def parse_wrf_time(text):
    """'2022-03-21_00:00:00' (or with '_' instead of ':') -> datetime."""
    text = text.strip().strip("\x00").strip()
    if not WRF_TIME_RE.match(text):
        return None
    d, t = text.split("_", 1)
    return datetime.strptime(d + "_" + t.replace("_", ":"), "%Y-%m-%d_%H:%M:%S")


# ---------------------------------------------------------------- reading Times

def times_via_netcdf4(path):
    """Frame times from the netCDF `Times` variable, or None if unavailable."""
    try:
        import netCDF4
    except ImportError:
        return None
    try:
        with netCDF4.Dataset(path) as ds:
            if "Times" not in ds.variables:
                return None
            raw = netCDF4.chartostring(ds.variables["Times"][:])
    except Exception:
        return None
    times = [parse_wrf_time(str(s)) for s in raw.flatten()]
    return [t for t in times if t is not None] or None


def times_via_ncdump(path):
    """Same, via the `ncdump` command line tool (no python netCDF module needed)."""
    try:
        out = subprocess.run(["ncdump", "-v", "Times", path],
                             capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    body = out.stdout.split("Times =", 1)
    if len(body) < 2:
        return None
    times = [parse_wrf_time(s) for s in re.findall(r'"([^"]*)"', body[1])]
    return [t for t in times if t is not None] or None


def frame_times(path, mode):
    """All time frames inside one wrfout file, plus how we found them."""
    if mode != "names":
        for reader, tag in ((times_via_netcdf4, "netCDF4"), (times_via_ncdump, "ncdump")):
            times = reader(path)
            if times:
                return sorted(set(times)), tag
        if mode == "read":
            raise SystemExit(
                f"cannot read the Times variable of {path}\n"
                "install the python netCDF4 module, put `ncdump` on PATH, or rerun "
                "with --from-names (optionally with --assume-interval)")
    return None, "names"


# ---------------------------------------------------------------- file scanning

def collect_files(paths, pattern):
    """Expand directories/globs/files into a flat, de-duplicated list of wrfout files."""
    found = []
    for p in paths:
        if os.path.isdir(p):
            found.extend(sorted(glob.glob(os.path.join(p, pattern))))
        else:
            hits = sorted(glob.glob(p))
            if not hits:
                raise SystemExit(f"no such file or directory: {p}")
            found.extend(hits)
    files, seen = [], set()
    for f in found:
        real = os.path.realpath(f)
        if os.path.isfile(f) and real not in seen:
            seen.add(real)
            files.append(f)
    return files


def scan(files, mode, verbose):
    """-> {domain: [(time, filename), ...]}, sorted, plus a per-domain reader tally."""
    per_domain = defaultdict(list)
    readers = Counter()
    unnamed = []
    for path in files:
        name = os.path.basename(path)
        m = NAME_RE.match(name)
        if not m:
            unnamed.append(name)
            continue
        domain = int(m.group("domain"))
        stamp = parse_wrf_time(m.group("stamp"))
        times, tag = frame_times(path, mode)
        readers[tag] += 1
        if times is None:  # name-only fallback: the file name is its single frame
            times = [stamp]
        elif verbose:
            print(f"  {name}: {len(times)} frame(s)", file=sys.stderr)
        for t in times:
            per_domain[domain].append((t, name))
    if unnamed:
        print(f"warning: ignoring {len(unnamed)} file(s) whose name is not "
              f"<prefix>_dNN_YYYY-MM-DD_HH:MM:SS, e.g. {unnamed[0]}", file=sys.stderr)
    for rows in per_domain.values():
        rows.sort(key=lambda r: (r[0], r[1]))
    return per_domain, readers


def expand_from_names(rows, interval):
    """Name-only mode: fill each file's frames from its stamp up to the next file."""
    if interval is None or len(rows) < 2:
        return rows
    step = timedelta(seconds=interval)
    out = []
    for i, (start, name) in enumerate(rows):
        stop = rows[i + 1][0] if i + 1 < len(rows) else start + step
        t = start
        while t < stop:
            out.append((t, name))
            t += step
    return out


def thin(rows, every, domain):
    """Keep one step every `every` seconds, counted from the first one."""
    native = Counter((rows[i + 1][0] - rows[i][0]).total_seconds()
                     for i in range(len(rows) - 1)).most_common(1)[0][0]
    if every % native != 0:
        raise SystemExit(
            f"d{domain:02d}: the frames are {fmt_seconds(native)} apart, so --every "
            f"{fmt_seconds(every)} cannot be taken from them -- use a whole multiple "
            f"of {fmt_seconds(native)}")
    t0 = rows[0][0]
    kept = [r for r in rows if (r[0] - t0).total_seconds() % every == 0]
    if len(kept) < 2:
        raise SystemExit(
            f"d{domain:02d}: --every {fmt_seconds(every)} leaves only {len(kept)} "
            f"time step(s) -- the period is too short for it")
    print(f"d{domain:02d}: --every {fmt_seconds(every)} keeps {len(kept)} of "
          f"{len(rows)} time steps", file=sys.stderr)
    return kept


def dedupe(rows, domain):
    """FLEXPART needs strictly increasing times; keep the first file for each."""
    out, dropped = [], 0
    for t, name in rows:
        if out and out[-1][0] == t:
            if out[-1][1] != name:
                dropped += 1
            continue
        out.append((t, name))
    if dropped:
        print(f"warning: d{domain:02d}: {dropped} duplicate time step(s) appear in "
              f"more than one file; kept the alphabetically first file", file=sys.stderr)
    return out


def describe(rows, domain):
    """Report the detected output interval and any gaps, on stderr."""
    if len(rows) < 2:
        return
    gaps = Counter((rows[i + 1][0] - rows[i][0]).total_seconds()
                   for i in range(len(rows) - 1))
    step, n = gaps.most_common(1)[0]
    files = len({name for _, name in rows})
    print(f"d{domain:02d}: {len(rows)} time steps in {files} file(s), "
          f"{rows[0][0]:%Y-%m-%d %H:%M} -> {rows[-1][0]:%Y-%m-%d %H:%M}, "
          f"every {fmt_seconds(step)}", file=sys.stderr)
    if len(gaps) > 1:
        odd = sorted(g for g in gaps if g != step)
        print(f"warning: d{domain:02d}: irregular spacing -- also "
              f"{', '.join(fmt_seconds(g) for g in odd[:5])}"
              f"{' ...' if len(odd) > 5 else ''}. Missing wrfout files?", file=sys.stderr)
    if len(rows) > MAXWF:
        print(f"warning: d{domain:02d}: {len(rows)} rows exceeds maxwf={MAXWF} "
              f"(par_mod.f90); FLEXPART will stop unless you shorten the period",
              file=sys.stderr)


def check_nests(prepared):
    """FLEXPART stops unless every nest has exactly the mother's time steps
    (readinput.f90:915) -- say so here rather than 50 minutes into the run."""
    if len(prepared) < 2:
        return
    mother, rows0 = prepared[0]
    times0 = [t for t, _ in rows0]
    for domain, rows in prepared[1:]:
        times = [t for t, _ in rows]
        if times == times0:
            continue
        missing = sorted(set(times0) - set(times))
        extra = sorted(set(times) - set(times0))
        print(f"warning: d{domain:02d} has {len(times)} time steps but the mother "
              f"domain d{mother:02d} has {len(times0)}; FLEXPART requires them to be "
              f"identical and will stop.", file=sys.stderr)
        if missing:
            print(f"         d{domain:02d} is missing e.g. {missing[0]:%Y-%m-%d %H:%M}",
                  file=sys.stderr)
        if extra:
            print(f"         d{domain:02d} has extra e.g. {extra[0]:%Y-%m-%d %H:%M}",
                  file=sys.stderr)
        print(f"         fix the WRF output, or thin both with --every",
              file=sys.stderr)


def fmt_seconds(sec):
    sec = int(sec)
    if sec % 3600 == 0:
        return f"{sec // 3600} h"
    if sec % 60 == 0:
        return f"{sec // 60} min"
    return f"{sec} s"


def render(rows, header=True):
    lines = [] if not header else list(HEADER)
    lines += [f"{t:%Y%m%d %H%M%S}\t\t'{name}' ' '" for t, name in rows]
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Generate FLEXPART-WRF AVAILABLE file(s) from a directory of "
                    "wrfout files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("Examples")[1] if "Examples" in __doc__ else None)
    ap.add_argument("paths", nargs="+", metavar="PATH",
                    help="directory holding the wrfout files (or individual files / "
                         "shell globs)")
    ap.add_argument("--pattern", default="wrfout_d*",
                    help="glob used inside a directory (default: wrfout_d*)")
    ap.add_argument("--domain", type=int, action="append", dest="domains",
                    help="only this WRF domain, the NN in wrfout_dNN; repeatable "
                         "(default: every domain found)")
    ap.add_argument("--start", type=parse_stamp,
                    help="drop time steps before this (YYYYMMDD or 'YYYYMMDD HHMMSS')")
    ap.add_argument("--end", type=parse_stamp,
                    help="drop time steps after this; a bare date means 00:00:00 of "
                         "that day, so give 'YYYYMMDD 230000' to keep the whole day")
    ap.add_argument("--every", type=int, metavar="SECONDS",
                    help="use only every SECONDS of the frames present, e.g. 3600 to "
                         "drive FLEXPART with hourly wind fields when WRF wrote every "
                         "10 min (must be a multiple of the frame spacing)")
    ap.add_argument("--from-names", action="store_true",
                    help="do not open the files; take one time frame per file from "
                         "its name (see --assume-interval)")
    ap.add_argument("--assume-interval", type=int, metavar="SECONDS",
                    help="with --from-names, the spacing of the frames inside each "
                         "file, used to fill the rows between consecutive files")
    ap.add_argument("--no-header", action="store_true",
                    help="omit the three header lines")
    ap.add_argument("--outdir", default=".",
                    help="where the AVAILABLE files are written (default: .)")
    ap.add_argument("-o", "--output", metavar="FILE",
                    help="write to this file instead of AVAILABLE<n>; '-' means "
                         "stdout. Only with a single domain")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="report the frame count of every file")
    args = ap.parse_args(argv)

    if args.end and args.start and args.end < args.start:
        ap.error("--end is before --start")
    if args.assume_interval is not None and args.assume_interval <= 0:
        ap.error("--assume-interval must be positive")
    if args.every is not None and args.every <= 0:
        ap.error("--every must be positive")

    files = collect_files(args.paths, args.pattern)
    if not files:
        raise SystemExit(
            f"no files matching {args.pattern!r} in: {', '.join(args.paths)}")
    print(f"scanning {len(files)} file(s)", file=sys.stderr)

    mode = "names" if args.from_names else "read"
    per_domain, readers = scan(files, mode, args.verbose)
    if not per_domain:
        raise SystemExit("no wrfout files with a recognisable name were found")
    if readers:
        how = ", ".join(f"{n} via {tag}" for tag, n in readers.items())
        print(f"time frames read: {how}", file=sys.stderr)

    domains = sorted(per_domain)
    if args.domains:
        missing = sorted(set(args.domains) - set(domains))
        if missing:
            raise SystemExit(
                f"domain(s) {', '.join(f'd{d:02d}' for d in missing)} not found; "
                f"present: {', '.join(f'd{d:02d}' for d in domains)}")
        domains = sorted(set(args.domains))
    if args.output and args.output != "-" and len(domains) > 1:
        ap.error("-o/--output needs a single domain; use --domain or --outdir")

    prepared = []
    for domain in domains:
        rows = per_domain[domain]
        if args.from_names:
            rows = expand_from_names(rows, args.assume_interval)
        rows = dedupe(rows, domain)
        if args.start:
            rows = [r for r in rows if r[0] >= args.start]
        if args.end:
            rows = [r for r in rows if r[0] <= args.end]
        if not rows:
            print(f"warning: d{domain:02d}: no time steps left after --start/--end",
                  file=sys.stderr)
            continue
        if args.every:
            rows = thin(rows, args.every, domain)
        describe(rows, domain)
        prepared.append((domain, rows))

    check_nests(prepared)

    for n, (domain, rows) in enumerate(prepared, start=1):
        text = render(rows, header=not args.no_header)
        if args.output == "-":
            sys.stdout.write(text)
            continue
        target = args.output or os.path.join(args.outdir, f"AVAILABLE{n}")
        os.makedirs(os.path.dirname(os.path.abspath(target)), exist_ok=True)
        with open(target, "w") as fh:
            fh.write(text)
        print(f"d{domain:02d} -> {target}", file=sys.stderr)

    if len(domains) > 1 and not args.output:
        print("remember: in flexwrf.input the parent domain comes first; AVAILABLE1 "
              "is d%02d, AVAILABLE2 is d%02d, ..." % (domains[0], domains[1]),
              file=sys.stderr)


if __name__ == "__main__":
    main()
