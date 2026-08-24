#!/usr/bin/env python3
"""Generate the FLEXPART v11 AVAILABLE file from a directory of flex_extract output.

AVAILABLE lists, in chronological order, every wind field FLEXPART may use and the
GRIB file that holds it. flex_extract writes one file per time step, named
<PREFIX><YYMMDDHH> (e.g. EA18010100 for 2018-01-01 00 UTC), so this script only has
to scan the directory, sort, and lay the rows out in the exact columns FLEXPART reads.

The layout is NOT free-form. `readavailable` in src/readoptions_mod.f90:210 does

    read(unitavailab,'(i8,1x,i6,2(6x,a255))',end=99) ldat,ltim,fname

which means, counting columns from 1:

    1-8    YYYYMMDD
    9      one blank
    10-15  HHMMSS
    16-21  six blanks, skipped
    22-    the file name, taken up to its first blank

so anything after the first blank following the name (flex_extract writes "ON DISK")
is a comment. Getting a column wrong does not produce an error message: FLEXPART
reads a garbage date and either drops the field or stops with "NO WIND FIELDS
AVAILABLE FOR SELECTED TIME PERIOD".

*** Three header lines, not two. ***  readavailable skips exactly three lines
(`do i=1,3; read(unitavailab,*); end do`) before the first record. The older
generateAVAILABLE.py in local_reference/ wrote only two, so FLEXPART silently ate the
first wind field of every run — the field was in the file but never used, and the
simulation started an hour late with no warning. This script always writes three.

Examples
--------
  # every field in the directory
  ./generate_available.py /scratch/project_XXXXXXX/$USER/FLEXPART/ERA5/

  # restrict to the simulation period, write next to the pathnames file
  ./generate_available.py /scratch/.../ERA5/ --start 20180101 --end "20180201 000000"

  # drive FLEXPART with 3-hourly fields although flex_extract retrieved hourly ones
  ./generate_available.py /scratch/.../ERA5/ --every 10800

  # take the times from the GRIB headers instead of the file names, and print them
  ./generate_available.py /scratch/.../ERA5/ --from-grib -o -

Written for the FLEXPART v11 setup at INAR / University of Helsinki.
"""
import argparse
import glob
import os
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, timedelta

# The three lines readavailable skips. The text is irrelevant, the count is not.
HEADER = [
    "DATE     TIME       FILENAME             SPECIFICATIONS",
    "YYYYMMDD HHMISS      name of the file(up to 80 characters)",
    "________ ______      __________________________________________________",
]

NAME_COL = 22    # column the file name must start in (1-based)
NAME_WIDTH = 80  # width of the name field before the "ON DISK" comment

# par_mod.f90:122 — idiffnorm=10800, idiffmax=2*idiffnorm.
IDIFFNORM = 10800   # 3 h: a bigger gap degrades the simulation (FLEXPART warns)
IDIFFMAX = 21600    # 6 h: a bigger gap makes FLEXPART skip trajectories entirely

# flex_extract output: a letter prefix (EA, EN, EI, OD, ...) then the time stamp.
# Two-digit year (the flex_extract default, EA18010100) or four-digit (EA2018010100).
# An optional tail covers ensemble members (".001") and any suffix.
NAME_RE = re.compile(
    r"^(?P<prefix>[A-Za-z]{1,4})"
    r"(?P<stamp>\d{10}|\d{8})"
    r"(?P<tail>\D.*|)$")

# flex_extract leaves its working files next to its output whenever INPUTDIR and
# OUTPUTDIR are the same directory (the INAR run_local.sh sets both to the same path
# on /scratch). Several of them would sail through NAME_RE — "flux18010100" parses as
# prefix "flux" plus a perfectly good time stamp — and listing one in AVAILABLE makes
# FLEXPART read a file with no wind fields in it. Skip them by name.
#   flux*            the accumulated flux fields, merged into the real output file
#   *_1, *_2         precipitation sub-grid steps from RRINT=1, also already merged
#   fort.*, OG_*     Fortran units and the orography/land-sea mask
#   rr_grib_dummy*   the template used to build the disaggregated precipitation
SKIP_RE = re.compile(
    r"^(flux|fort\.|OG_|rr_grib_dummy|mars_requests|VERTICAL)"
    r"|(_[12]$)"
    r"|(\.(idx|csv|log|tmp|nml|bak)$)", re.I)


def parse_stamp(text):
    """Accept 'YYYYMMDD', 'YYYYMMDD HHMMSS' or 'YYYYMMDDHHMMSS' on the command line."""
    compact = text.replace(" ", "").replace("-", "").replace(":", "").replace("_", "")
    if len(compact) == 8:
        return datetime.strptime(compact, "%Y%m%d")
    if len(compact) == 14:
        return datetime.strptime(compact, "%Y%m%d%H%M%S")
    raise argparse.ArgumentTypeError(
        f"cannot read date/time {text!r} -- use YYYYMMDD or 'YYYYMMDD HHMMSS'")


def time_from_name(name, century):
    """Time of a flex_extract file from its name, or None if the name does not fit."""
    m = NAME_RE.match(name)
    if not m:
        return None
    stamp = m.group("stamp")
    try:
        if len(stamp) == 10:                      # YYYYMMDDHH
            return datetime.strptime(stamp, "%Y%m%d%H")
        yy = int(stamp[:2])                       # YYMMDDHH
        year = century + yy if yy < 70 else (century - 100) + yy
        return datetime.strptime(f"{year:04d}{stamp[2:]}", "%Y%m%d%H")
    except ValueError:
        return None


# ---------------------------------------------------------------- reading GRIB

def time_from_grib_python(path):
    """First field's validity time via the ecCodes python bindings, or None."""
    try:
        import eccodes
    except ImportError:
        return None
    try:
        with open(path, "rb") as fh:
            gid = eccodes.codes_grib_new_from_file(fh)
            if gid is None:
                return None
            try:
                date = eccodes.codes_get(gid, "dataDate")
                time = eccodes.codes_get(gid, "dataTime")
                step = eccodes.codes_get(gid, "step")
            finally:
                eccodes.codes_release(gid)
    except Exception:
        return None
    base = datetime.strptime(f"{date:08d}{time // 100:02d}{time % 100:02d}", "%Y%m%d%H%M")
    return base + timedelta(hours=int(step))


def time_from_grib_cli(path):
    """Same, via the `grib_get` command line tool that ships with ecCodes."""
    try:
        out = subprocess.run(
            ["grib_get", "-w", "count=1", "-p", "dataDate,dataTime,step", path],
            capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0 or not out.stdout.strip():
        return None
    parts = out.stdout.split()
    if len(parts) < 3:
        return None
    try:
        date, time, step = int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError:
        return None
    base = datetime.strptime(f"{date:08d}{time // 100:02d}{time % 100:02d}", "%Y%m%d%H%M")
    return base + timedelta(hours=step)


def time_from_grib(path):
    for reader in (time_from_grib_python, time_from_grib_cli):
        t = reader(path)
        if t is not None:
            return t
    return None


# ---------------------------------------------------------------- file scanning

def collect_files(paths, pattern, skip_work_files=True):
    """Expand directories/globs/files into a flat, de-duplicated list."""
    found = []
    for p in paths:
        if os.path.isdir(p):
            found.extend(sorted(glob.glob(os.path.join(p, pattern))))
        else:
            hits = sorted(glob.glob(p))
            if not hits:
                raise SystemExit(f"no such file or directory: {p}")
            found.extend(hits)
    files, seen, skipped = [], set(), []
    for f in found:
        real = os.path.realpath(f)
        if not os.path.isfile(f) or real in seen:
            continue
        seen.add(real)
        if skip_work_files and SKIP_RE.search(os.path.basename(f)):
            skipped.append(os.path.basename(f))
            continue
        files.append(f)
    if skipped:
        print(f"skipping {len(skipped)} flex_extract working file(s) such as "
              f"{skipped[0]} (--keep-work-files to list them anyway)",
              file=sys.stderr)
    return files


def scan(files, from_grib, century, verbose):
    """-> [(time, filename), ...] sorted, plus a tally of how the times were found."""
    rows, how = [], Counter()
    unnamed = []
    for path in files:
        name = os.path.basename(path)
        t = None
        if from_grib:
            t = time_from_grib(path)
            if t is not None:
                how["GRIB header"] += 1
        if t is None:
            t = time_from_name(name, century)
            if t is not None:
                how["file name"] += 1
        if t is None:
            unnamed.append(name)
            continue
        if verbose:
            print(f"  {name}: {t:%Y-%m-%d %H:%M}", file=sys.stderr)
        rows.append((t, name))
    if unnamed:
        print(f"warning: ignoring {len(unnamed)} file(s) whose name is not "
              f"<PREFIX><YYMMDDHH>, e.g. {unnamed[0]}. Use --pattern to narrow the "
              f"scan, or --from-grib to take the time from the GRIB header instead.",
              file=sys.stderr)
    if from_grib and how["file name"]:
        print(f"warning: {how['file name']} file(s) had no readable GRIB header; fell "
              f"back to their names. Is ecCodes available? (module load eccodes)",
              file=sys.stderr)
    rows.sort(key=lambda r: (r[0], r[1]))
    return rows, how


def dedupe(rows):
    """FLEXPART stops on non-increasing times; keep the first file for each time."""
    out, dropped = [], []
    for t, name in rows:
        if out and out[-1][0] == t:
            dropped.append((t, name))
            continue
        out.append((t, name))
    if dropped:
        print(f"warning: {len(dropped)} file(s) share a time with another file and "
              f"were dropped (FLEXPART requires strictly increasing times); e.g. "
              f"{dropped[0][1]} at {dropped[0][0]:%Y-%m-%d %H:%M}", file=sys.stderr)
    return out


def thin(rows, every):
    """Keep one field every `every` seconds, counted from the first one."""
    native = Counter((rows[i + 1][0] - rows[i][0]).total_seconds()
                     for i in range(len(rows) - 1)).most_common(1)[0][0]
    if every % native != 0:
        raise SystemExit(
            f"the fields are {fmt_seconds(native)} apart, so --every "
            f"{fmt_seconds(every)} cannot be taken from them -- use a whole multiple "
            f"of {fmt_seconds(native)}")
    t0 = rows[0][0]
    kept = [r for r in rows if (r[0] - t0).total_seconds() % every == 0]
    if len(kept) < 2:
        raise SystemExit(
            f"--every {fmt_seconds(every)} leaves only {len(kept)} field(s) -- the "
            f"period is too short for it")
    print(f"--every {fmt_seconds(every)} keeps {len(kept)} of {len(rows)} fields",
          file=sys.stderr)
    return kept


def describe(rows):
    """Report the detected interval and any gap FLEXPART will complain about."""
    if len(rows) < 2:
        print("warning: fewer than two wind fields — FLEXPART needs at least two",
              file=sys.stderr)
        return
    gaps = Counter((rows[i + 1][0] - rows[i][0]).total_seconds()
                   for i in range(len(rows) - 1))
    step, _ = gaps.most_common(1)[0]
    print(f"{len(rows)} wind fields, {rows[0][0]:%Y-%m-%d %H:%M} -> "
          f"{rows[-1][0]:%Y-%m-%d %H:%M}, every {fmt_seconds(step)}", file=sys.stderr)

    if len(gaps) > 1:
        odd = sorted(g for g in gaps if g != step)
        print(f"warning: irregular spacing -- also "
              f"{', '.join(fmt_seconds(g) for g in odd[:5])}"
              f"{' ...' if len(odd) > 5 else ''}. Missing files from flex_extract?",
              file=sys.stderr)
    biggest = max(gaps)
    if biggest > IDIFFMAX:
        first = next(rows[i][0] for i in range(len(rows) - 1)
                     if (rows[i + 1][0] - rows[i][0]).total_seconds() == biggest)
        print(f"ERROR-IN-WAITING: a {fmt_seconds(biggest)} gap after "
              f"{first:%Y-%m-%d %H:%M} exceeds idiffmax = {fmt_seconds(IDIFFMAX)} "
              f"(par_mod.f90:122). FLEXPART will skip trajectories across it.",
              file=sys.stderr)
    elif biggest > IDIFFNORM:
        print(f"warning: the largest gap ({fmt_seconds(biggest)}) exceeds idiffnorm = "
              f"{fmt_seconds(IDIFFNORM)}; FLEXPART will warn about degraded quality.",
              file=sys.stderr)

    # LSYNCTIME in COMMAND must be <= idiffnorm/2 (readoptions_mod.f90:1004), and it
    # is the interval people most often get wrong after changing the met resolution.
    print(f"reminder: LSYNCTIME in COMMAND must be <= {IDIFFNORM // 2} s",
          file=sys.stderr)


def fmt_seconds(sec):
    sec = int(sec)
    if sec % 3600 == 0:
        return f"{sec // 3600} h"
    if sec % 60 == 0:
        return f"{sec // 60} min"
    return f"{sec} s"


def render(rows, header=True):
    """Lay the rows out in the fixed columns readavailable expects."""
    lines = list(HEADER) if header else []
    for t, name in rows:
        if len(name) > NAME_WIDTH:
            print(f"warning: name longer than {NAME_WIDTH} characters: {name}",
                  file=sys.stderr)
        line = f"{t:%Y%m%d} {t:%H%M%S}      {name:<{NAME_WIDTH}} ON DISK"
        # Cheap insurance against someone editing the f-string above.
        assert line.index(name) == NAME_COL - 1, "file name must start in column 22"
        lines.append(line.rstrip())
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Generate the FLEXPART v11 AVAILABLE file from a directory of "
                    "flex_extract GRIB files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("Examples")[1] if "Examples" in __doc__ else None)
    ap.add_argument("paths", nargs="+", metavar="PATH",
                    help="directory holding the flex_extract output (or individual "
                         "files / shell globs)")
    ap.add_argument("--pattern", default="*",
                    help="glob used inside a directory (default: *). Use e.g. 'EA*' "
                         "if the directory also holds other files")
    ap.add_argument("--start", type=parse_stamp,
                    help="drop fields before this (YYYYMMDD or 'YYYYMMDD HHMMSS')")
    ap.add_argument("--end", type=parse_stamp,
                    help="drop fields after this; a bare date means 00:00:00 of that "
                         "day, so give 'YYYYMMDD 230000' to keep the whole day")
    ap.add_argument("--every", type=int, metavar="SECONDS",
                    help="use only every SECONDS of the fields present, e.g. 10800 to "
                         "drive FLEXPART with 3-hourly fields when flex_extract "
                         "retrieved hourly ones (must be a multiple of the spacing, "
                         f"and <= idiffmax = {IDIFFMAX} s)")
    ap.add_argument("--from-grib", action="store_true",
                    help="read the validity time out of each GRIB file (dataDate, "
                         "dataTime, step) instead of trusting the file name. Slower, "
                         "but it also verifies the retrieval")
    ap.add_argument("--century", type=int, default=2000, metavar="YYYY",
                    help="century for two-digit years in file names (default 2000, "
                         "so EA18010100 is 2018; years >= 70 fall to the previous "
                         "century)")
    ap.add_argument("--no-header", action="store_true",
                    help="omit the three header lines (you almost never want this: "
                         "FLEXPART skips exactly three lines before the first record)")
    ap.add_argument("-o", "--output", metavar="FILE", default="AVAILABLE",
                    help="where to write it (default: ./AVAILABLE); '-' means stdout")
    ap.add_argument("--keep-work-files", action="store_true",
                    help="do not skip flex_extract working files (flux*, *_1, *_2, "
                         "fort.*, OG_*) that sit next to the output when INPUTDIR and "
                         "OUTPUTDIR are the same directory")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="print the time found for every file")
    args = ap.parse_args(argv)

    if args.end and args.start and args.end < args.start:
        ap.error("--end is before --start")
    if args.every is not None and args.every <= 0:
        ap.error("--every must be positive")

    files = collect_files(args.paths, args.pattern, not args.keep_work_files)
    if not files:
        raise SystemExit(
            f"no files matching {args.pattern!r} in: {', '.join(args.paths)}")
    print(f"scanning {len(files)} file(s)", file=sys.stderr)

    rows, how = scan(files, args.from_grib, args.century, args.verbose)
    if not rows:
        raise SystemExit(
            "no file could be dated. flex_extract names its output "
            "<PREFIX><YYMMDDHH> (e.g. EA18010100); if yours differ, use --from-grib.")
    if how:
        print("times from: " + ", ".join(f"{n} via {tag}" for tag, n in how.items()),
              file=sys.stderr)

    rows = dedupe(rows)
    if args.start:
        rows = [r for r in rows if r[0] >= args.start]
    if args.end:
        rows = [r for r in rows if r[0] <= args.end]
    if not rows:
        raise SystemExit("no fields left after --start/--end")
    if args.every:
        rows = thin(rows, args.every)

    describe(rows)

    text = render(rows, header=not args.no_header)
    if args.output == "-":
        sys.stdout.write(text)
        return
    target = os.path.abspath(args.output)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w") as fh:
        fh.write(text)
    print(f"-> {target}", file=sys.stderr)
    print("remember: line 4 of 'pathnames' must point at this file, and line 3 at the "
          "directory holding the GRIB files (with a trailing /)", file=sys.stderr)


if __name__ == "__main__":
    main()
