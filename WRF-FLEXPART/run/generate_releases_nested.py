#!/usr/bin/env python3
"""Set up a NESTED FLEXPART-WRF run: releases, both output grids, and the nest paths.

This is the two-domain counterpart of generate_releases.py. You point it at the
mother wrfout (d01) and the nest wrfout (d02) and it writes, into one flexwrf.input:

  * the nest's wrfout directory and its AVAILABLE file, appended to the PATHNAMES
    block -- this is what makes FLEXPART read d02 winds at all (readinput.f90:110);
  * NESTED_OUTPUT = 1, plus the OUTGRID_NEST section covering the d02 footprint,
    placed in the mother's grid metres the way gridcheck_nests.f90 computes it;
  * the main OUTGRID section covering d01, exactly as generate_releases.py does;
  * the RELEASES blocks, with the release box checked against d02 rather than d01.

    ./generate_releases_nested.py --input flexwrf.input \\
        --wrf /scratch/.../wrfout_d01/ --wrf-nest /scratch/.../wrfout_d02/ \\
        --lat 28.309 --lon -16.499 --box 1000 \\
        --outgrid --outgrid-res 3000 --log-levels 20 --zfirst 20 --ztop 7000

Why one nested run and not two separate ones
--------------------------------------------
A particle uses the innermost nest that contains it and switches on the fly
(advance.f90:295-302), so in a nested run a trajectory is driven by d02 winds inside
the nest and d01 winds outside, and can re-enter. In a d02-only run a particle that
crosses the nest edge is killed for good (advance.f90:1157-1161), which truncates
backward footprints at the boundary and biases the strip just inside it low. The two
setups are not equivalent; this script builds the nested one.

Note the two independent meanings of "nest":
  * nested INPUT  -- d02 wind fields, switched on by the extra PATHNAMES lines;
  * nested OUTPUT -- a second, finer sampling grid over the same particles, switched
    on by NESTED_OUTPUT and the OUTGRID_NEST section.
This script sets up both, since wanting one without the other is unusual. Use
--no-nested-output to drive with d02 winds but keep a single output grid.

The AVAILABLE files
-------------------
Generate them first; FLEXPART requires the nest's time steps to be *identical* to the
mother's and stops otherwise (readinput.f90:916-925):

    ./generate_available.py /scratch/.../wrfout/ --outdir .
    # -> AVAILABLE1 (d01), AVAILABLE2 (d02)

This script re-checks that agreement over the simulation window before writing.

The vertical levels work exactly as in generate_releases.py (--levels, --dz,
--nlevels or --log-levels with --ztop). The nested output grid has no levels of its
own -- FLEXPART shares numzgrid between the two grids (readinput.f90:1174-1199).

Written for the FLEXPART-WRF setup at INAR / University of Helsinki.
"""
import argparse
import glob
import os
import re
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import wrfgrid
from generate_releases import (
    SEPARATOR_RE,
    build_levels,
    find_numpoint,
    keyword_re,
    outgrid_lines,
    parse_stamp,
    read_input,
    release_block,
    replace_outgrid,
    set_switch,
    write_input,
)

PATHNAMES_HEAD_RE = re.compile(r"^=+\s*FORMER PATHNAMES FILE\s*=+\s*$", re.I)
OUTGRID_NEST_HEAD_RE = re.compile(r"^=+\s*OUTGRID_NEST\s*=+\s*$", re.I)
OUTGRID_NEST_HEADER = "================OUTGRID_NEST=========================="

PATH_MAXLEN = 120   # com_mod.f90:48, character :: path(...)*120
NXMAXN, NYMAXN = 400, 283   # par_mod.f90:167, the nest field dimensions compiled in


# ------------------------------------------------------------------- nest geometry

def nest_footprint(mother, nest):
    """(x0, y0, x1, y1) of the nest in mother grid metres.

    Reproduces gridcheck_nests.f90:386-391 and 502-505 exactly, so what we write
    lines up with the bounds FLEXPART itself will compute:

        dumc   = (m-1)/(2m)                  with m = PARENT_GRID_RATIO
        xmet0n = xmet0 + dx*(i_parent_start - dumc)
        x_max  = xmet0n + (nxn-1)*dxn

    `i_parent_start` there is the file attribute minus one (line 109), i.e. the
    zero-based index of the parent cell whose lower-left corner the nest's cell
    (0,0) sits on; xmet0 = ymet0 = 0 in FLEXPART-WRF (gridcheck.f90:145).
    """
    m = nest.parent_grid_ratio
    if m < 1:
        raise SystemExit(f"{nest.name}: PARENT_GRID_RATIO = {m}, which cannot be right")
    dumc = (m - 1) / (2.0 * m)
    x0 = mother.dx * ((nest.i_parent_start - 1) - dumc)
    y0 = mother.dy * ((nest.j_parent_start - 1) - dumc)
    return x0, y0, x0 + (nest.nx - 1) * nest.dx, y0 + (nest.ny - 1) * nest.dy


def check_nest(mother, nest):
    """Everything gridcheck_nests.f90 would stop on, reported now instead."""
    if nest.grid_id == mother.grid_id:
        raise SystemExit(f"--wrf and --wrf-nest are the same domain (GRID_ID "
                         f"{mother.grid_id}); point --wrf-nest at the inner domain")
    if not mother.is_mother():
        raise SystemExit(f"--wrf must be the MOTHER domain: FLEXPART grid metres are "
                         f"measured on the first domain, but {mother.name} has "
                         f"GRID_ID {mother.grid_id}")
    if nest.parent_id != mother.grid_id:
        print(f"warning: {nest.name} has PARENT_ID {nest.parent_id} but "
              f"{mother.name} is GRID_ID {mother.grid_id}; if d02 is nested inside "
              f"another nest rather than d01, that intermediate domain has to be "
              f"given to FLEXPART too", file=sys.stderr)
    if nest.map_proj != mother.map_proj:
        raise SystemExit(f"MAP_PROJ differs ({mother.map_proj} vs {nest.map_proj}); "
                         f"gridcheck_nests.f90:173 stops on this")
    if mother.nz is not None and nest.nz is not None and mother.nz != nest.nz:
        raise SystemExit(f"the two domains have different numbers of vertical levels "
                         f"({mother.nz} vs {nest.nz}); gridcheck_nests.f90:150-159 "
                         f"stops on this (nuvzn/nuvz differ)")

    ratio = mother.dx / nest.dx
    if abs(ratio - nest.parent_grid_ratio) > 1e-6:
        print(f"warning: dx ratio {ratio:.4f} does not match PARENT_GRID_RATIO "
              f"{nest.parent_grid_ratio}; the nest placement below may be off",
              file=sys.stderr)
    if nest.nx > NXMAXN or nest.ny > NYMAXN:
        print(f"warning: the nest is {nest.nx} x {nest.ny} points but par_mod.f90 is "
              f"compiled with nxmaxn = {NXMAXN}, nymaxn = {NYMAXN}; raise them and "
              f"rebuild, or FLEXPART will stop reading the nest", file=sys.stderr)

    x0, y0, x1, y1 = nest_footprint(mother, nest)
    xmax, ymax = mother.extent_m()
    print(f"nest footprint on the mother grid: x {x0:.0f} .. {x1:.0f} m, "
          f"y {y0:.0f} .. {y1:.0f} m  (mother spans 0 .. {xmax:.0f} x 0 .. {ymax:.0f} m, "
          f"i_parent_start = {nest.i_parent_start}, j = {nest.j_parent_start}, "
          f"ratio {nest.parent_grid_ratio})", file=sys.stderr)

    # gridcheck_nests.f90:513 -- xln/yln >= 0 and xrn/yrn <= nx-1 / ny-1
    if (x0 < 0 or y0 < 0 or x1 > (mother.nx - 1) * mother.dx
            or y1 > (mother.ny - 1) * mother.dy):
        raise SystemExit(
            "the nest does not fit inside the mother domain as FLEXPART measures it "
            f"(needs 0 <= x <= {(mother.nx - 1) * mother.dx:.0f} m, "
            f"0 <= y <= {(mother.ny - 1) * mother.dy:.0f} m); "
            "gridcheck_nests.f90:513 would stop the run")

    # independent cross-check: invert the nest's own corner lat/lon on the mother grid
    try:
        cx, cy, _ = mother.ll_to_xymeter(float(nest.lon[0, 0]), float(nest.lat[0, 0]))
    except Exception as exc:                                    # pragma: no cover
        print(f"note: could not cross-check the nest corner ({exc})", file=sys.stderr)
    else:
        off = max(abs(cx - x0), abs(cy - y0))
        if off > 0.5 * mother.dx:
            print(f"warning: the nest corner from I/J_PARENT_START ({x0:.0f}, "
                  f"{y0:.0f} m) and from its own XLONG/XLAT ({cx:.0f}, {cy:.0f} m) "
                  f"disagree by {off:.0f} m, more than half a mother cell. Are these "
                  f"two files from the same WRF run?", file=sys.stderr)
        else:
            print(f"nest corner cross-check: XLONG/XLAT agrees to {off:.0f} m",
                  file=sys.stderr)
    return x0, y0, x1, y1


def outgrid_nest_lines(mother, nest, res, margin):
    """The OUTGRID_NEST block: origin and extent in mother grid metres, no levels.

    readinput.f90:1181-1199 reads exactly seven values here and derives the far
    corner as x0 + dxoutn*numxgridn; the vertical levels are shared with the main
    grid, so none are written.
    """
    x0, y0, x1, y1 = nest_footprint(mother, nest)
    if margin:
        inset = margin * nest.dx, margin * nest.dy
        x0, x1 = x0 + inset[0], x1 - inset[0]
        y0, y1 = y0 + inset[1], y1 - inset[1]
        if x1 <= x0 or y1 <= y0:
            raise SystemExit(f"--margin {margin} eats the whole nest "
                             f"({nest.nx} x {nest.ny} points)")
    numx, numy = int((x1 - x0) // res), int((y1 - y0) // res)
    if numx < 1 or numy < 1:
        raise SystemExit(f"--outgrid-nest-res {res:g} m is larger than the nest "
                         f"({x1 - x0:.0f} x {y1 - y0:.0f} m)")
    rows = [
        (f"{x0:.1f}", "OUTLONLEFT", "lower left corner of the nested output grid [grid m]"),
        (f"{y0:.1f}", "OUTLATLOWER", "lower left corner of the nested output grid [grid m]"),
        (numx, "NUMXGRID", "number of grid points in x direction (= # of cells )"),
        (numy, "NUMYGRID", "number of grid points in y direction (= # of cells )"),
        (0, "OUTGRIDDEF", "outgrid defined 0=using grid distance, 1=upperright corner coordinate"),
        (f"{res:g}", "DXOUTLON", "grid distance in x direction or upper right corner of output grid"),
        (f"{res:g}", "DYOUTLON", "grid distance in y direction or upper right corner of output grid"),
    ]
    print(f"outgrid nest: {numx} x {numy} cells of {res:g} m covering "
          f"{x0:.0f} .. {x0 + numx * res:.0f} m x {y0:.0f} .. {y0 + numy * res:.0f} m "
          f"of the mother grid, sharing the main grid's vertical levels",
          file=sys.stderr)
    if margin:
        print(f"  (inset {margin} nest cells = {margin * nest.dx:.0f} m from the d02 "
              f"boundary)", file=sys.stderr)
    else:
        print("  note: this reaches the d02 edge, where WRF's own boundary relaxation "
              "zone (typically 5 cells) is nudged toward d01 and particles start "
              "crossing into the coarse fields -- --margin 5 trims it", file=sys.stderr)
    return [f"  {str(v):<19}{k:<16}{c}" for v, k, c in rows]


def get_switch(lines, word):
    """The current value of a COMMAND switch, or None if the line is not there."""
    rx = keyword_re(word)
    for line in lines:
        m = rx.match(line)
        if m:
            return m.group("val")
    return None


def replace_outgrid_nest(lines, block):
    """Swap the OUTGRID_NEST section for `block`, inserting it if there is none.

    A template with NESTED_OUTPUT = 0 has no such section, so the common case is the
    insert: it goes straight after the main OUTGRID block, which SEPARATOR_RE ends.
    """
    for i, line in enumerate(lines):
        if OUTGRID_NEST_HEAD_RE.match(line):
            end = next((k for k in range(i + 1, len(lines))
                        if SEPARATOR_RE.match(lines[k])), None)
            if end is None:
                raise SystemExit("the OUTGRID_NEST section has no closing '=====' line")
            return lines[:i + 1] + block + lines[end:]

    start = next((i for i, line in enumerate(lines)
                  if re.match(r"^=+\s*FORMER OUTGRID FILE\s*=+\s*$", line, re.I)), None)
    if start is None:
        raise SystemExit("no '=== FORMER OUTGRID FILE ===' section to attach the "
                         "nested output grid to")
    end = next((k for k in range(start + 1, len(lines)) if SEPARATOR_RE.match(lines[k])),
               None)
    if end is None:
        raise SystemExit("the FORMER OUTGRID FILE section has no closing '=====' line")
    print("no OUTGRID_NEST section in the input file; inserting one", file=sys.stderr)
    return lines[:end] + [OUTGRID_NEST_HEADER] + block + lines[end:]


def drop_outgrid_nest(lines):
    """Remove an OUTGRID_NEST section, for --no-nested-output on a file that has one."""
    for i, line in enumerate(lines):
        if OUTGRID_NEST_HEAD_RE.match(line):
            end = next((k for k in range(i + 1, len(lines))
                        if SEPARATOR_RE.match(lines[k])), None)
            if end is None:
                raise SystemExit("the OUTGRID_NEST section has no closing '=====' line")
            print("NESTED_OUTPUT is 0, dropping the OUTGRID_NEST section",
                  file=sys.stderr)
            return lines[:i] + lines[end:]
    return lines


# ----------------------------------------------------------------------- pathnames

def read_pathnames(lines):
    """-> (index of the header line, index of the closing '=====', the block)."""
    start = next((i for i, line in enumerate(lines) if PATHNAMES_HEAD_RE.match(line)),
                 None)
    if start is None:
        raise SystemExit("no '=== FORMER PATHNAMES FILE ===' section in the input file")
    end = next((k for k in range(start + 1, len(lines)) if SEPARATOR_RE.match(lines[k])),
               None)
    if end is None:
        raise SystemExit("the PATHNAMES section has no closing '=====' line")
    block = lines[start + 1:end]
    if len(block) < 3:
        raise SystemExit(f"the PATHNAMES section has {len(block)} line(s); it needs at "
                         f"least three (output dir, wrfout dir, AVAILABLE)")
    return start, end, block


def check_path(path, what):
    """FLEXPART truncates a path at its first blank and holds 120 characters."""
    if " " in path.strip():
        raise SystemExit(f"{what} contains a space: {path!r}. readinput.f90:104 cuts "
                         f"the path at the first blank, so FLEXPART would silently "
                         f"read the wrong location")
    if len(path) > PATH_MAXLEN:
        raise SystemExit(f"{what} is {len(path)} characters, over the {PATH_MAXLEN} "
                         f"that com_mod.f90:48 allows: {path}")
    if not os.path.exists(path):
        print(f"warning: {what} does not exist here: {path}", file=sys.stderr)


def as_dir(path):
    """A directory path with the trailing slash FLEXPART concatenates against."""
    if os.path.isfile(path):
        path = os.path.dirname(os.path.abspath(path))
    return path.rstrip("/") + "/"


def write_pathnames(lines, nest_dir, nest_available, mother_dir=None,
                    mother_available=None):
    """Keep the three mother paths (or replace them) and set the nest pair after."""
    start, end, block = read_pathnames(lines)
    out_dir, wrf_dir, available = block[0].strip(), block[1].strip(), block[2].strip()
    old_nests = (len(block) - 3) // 2
    if mother_dir:
        wrf_dir = mother_dir
    if mother_available:
        available = mother_available
    if old_nests:
        print(f"replacing the {old_nests} nest path pair(s) already in PATHNAMES",
              file=sys.stderr)

    check_path(out_dir, "the output directory")
    check_path(wrf_dir, "the mother wrfout directory")
    check_path(available, "the mother AVAILABLE file")
    check_path(nest_dir, "the nest wrfout directory")
    check_path(nest_available, "the nest AVAILABLE file")

    new = [out_dir, wrf_dir, available, nest_dir, nest_available]
    print(f"pathnames: nest {nest_dir} with {nest_available}", file=sys.stderr)
    return lines[:start + 1] + new + lines[end:]


# ------------------------------------------------------------------ AVAILABLE check

def available_times(path):
    """The time column of an AVAILABLE file, or None if it cannot be read."""
    try:
        with open(path) as fh:
            rows = fh.read().splitlines()[3:]       # three header lines
    except OSError:
        return None
    times = []
    for row in rows:
        parts = row.split()
        if len(parts) < 2:
            continue
        try:
            times.append(datetime.strptime(parts[0] + parts[1], "%Y%m%d%H%M%S"))
        except ValueError:
            continue
    return times or None


def check_available(mother_available, nest_available, sim_start, sim_end):
    """readinput.f90:916-925 stops unless the nest has the mother's exact time steps."""
    a = available_times(mother_available)
    b = available_times(nest_available)
    if a is None or b is None:
        missing = [p for p, t in ((mother_available, a), (nest_available, b))
                   if t is None]
        print(f"note: could not read {', '.join(missing)}; generate them with "
              f"generate_available.py and FLEXPART will check the time steps itself",
              file=sys.stderr)
        return
    if sim_start and sim_end:   # FLEXPART only counts steps inside the window
        a = [t for t in a if sim_start <= t <= sim_end]
        b = [t for t in b if sim_start <= t <= sim_end]
    if a == b:
        print(f"AVAILABLE check: both domains have the same {len(a)} time step(s) in "
              f"the simulation window", file=sys.stderr)
        return
    print(f"warning: the AVAILABLE files disagree inside the simulation window "
          f"(mother {len(a)} steps, nest {len(b)}); readinput.f90:916 stops the run "
          f"unless they are identical", file=sys.stderr)
    for label, diff in (("only in the mother", sorted(set(a) - set(b))),
                        ("only in the nest", sorted(set(b) - set(a)))):
        if diff:
            print(f"         {label}: {diff[0]:%Y-%m-%d %H:%M}"
                  f"{f' ... ({len(diff)} steps)' if len(diff) > 1 else ''}",
                  file=sys.stderr)


# -------------------------------------------------------------------- wrfout lookup

def pick_wrfout(path, want_domain=None, innermost=False):
    """A wrfout file from a file/dir/glob; from a directory pick a single domain."""
    if os.path.isfile(path):
        return path
    files = (sorted(glob.glob(os.path.join(path, "wrfout_d*"))) if os.path.isdir(path)
             else sorted(glob.glob(path)))
    files = [f for f in files if os.path.isfile(f)]
    if not files:
        raise SystemExit(f"no wrfout files at {path}")

    def domain(f):
        m = wrfgrid.NAME_RE.search(os.path.basename(f))
        return int(m.group("domain")) if m else 99

    if want_domain is not None:
        hits = [f for f in files if domain(f) == want_domain]
        if not hits:
            raise SystemExit(f"no d{want_domain:02d} files at {path}; found domains "
                             f"{sorted({domain(f) for f in files})}")
        return hits[0]
    domains = sorted({domain(f) for f in files})
    pick = domains[-1] if innermost else domains[0]
    if len(domains) > 1:
        print(f"{path} holds domains {domains}; using d{pick:02d} "
              f"(--{'nest-' if innermost else ''}domain overrides)", file=sys.stderr)
    return next(f for f in files if domain(f) == pick)


# ------------------------------------------------------------------------- position

def resolve_position(a, ap, mother, nest):
    """Fill a.x1/y1/x2/y2 in mother grid metres and check the box lands inside d02."""
    ll_corners = [a.lat1, a.lon1, a.lat2, a.lon2]
    if any(v is not None for v in ll_corners) and (a.lat is not None or a.lon is not None):
        ap.error("give either --lat/--lon or the corners --lat1/--lon1/--lat2/--lon2")
    if any(v is not None for v in ll_corners) and not all(v is not None for v in ll_corners):
        ap.error("--lat1, --lon1, --lat2 and --lon2 must all be given together")
    if (a.lat is None) != (a.lon is None):
        ap.error("--lat and --lon must be given together")

    if a.lat is not None:                               # centre point + box size
        half = a.box / 2.0
        x, y, err = mother.ll_to_xymeter(a.lon, a.lat)
        corners = [(x - half, y - half), (x + half, y + half)]
        print(f"release centre {a.lat} N {a.lon} E -> x = {x:.1f} m, y = {y:.1f} m "
              f"on the mother grid (fit {err:.1f} m), box {a.box:g} m", file=sys.stderr)
    elif a.lat1 is not None:                            # two corners
        x1, y1, e1 = mother.ll_to_xymeter(a.lon1, a.lat1)
        x2, y2, e2 = mother.ll_to_xymeter(a.lon2, a.lat2)
        corners = [(min(x1, x2), min(y1, y2)), (max(x1, x2), max(y1, y2))]
        print(f"release box -> x {corners[0][0]:.1f} .. {corners[1][0]:.1f} m, "
              f"y {corners[0][1]:.1f} .. {corners[1][1]:.1f} m on the mother grid "
              f"(fit {max(e1, e2):.1f} m)", file=sys.stderr)
    else:                                               # given in grid metres already
        corners = [(float(a.x1), float(a.y1)), (float(a.x2), float(a.y2))]
    (a.x1, a.y1), (a.x2, a.y2) = [tuple(f"{v:.1f}" for v in c) for c in corners]

    xmax, ymax = mother.extent_m()
    for label, v, limit in (("x", corners[0][0], xmax), ("x", corners[1][0], xmax),
                            ("y", corners[0][1], ymax), ("y", corners[1][1], ymax)):
        if v < 0 or v > limit:
            print(f"warning: release {label} = {v:.1f} m is outside the mother domain "
                  f"(0 .. {limit:.0f} m); FLEXPART will stop", file=sys.stderr)

    nx0, ny0, nx1, ny1 = nest_footprint(mother, nest)
    inside = (nx0 <= corners[0][0] and corners[1][0] <= nx1
              and ny0 <= corners[0][1] and corners[1][1] <= ny1)
    if not inside:
        print(f"warning: the release box is NOT inside d02 (x {nx0:.0f} .. {nx1:.0f} m, "
              f"y {ny0:.0f} .. {ny1:.0f} m). The run is still valid -- particles will "
              f"just start on the coarse fields -- but a receptor placed outside the "
              f"nest is usually a mistake", file=sys.stderr)
    else:
        edge = min(corners[0][0] - nx0, nx1 - corners[1][0],
                   corners[0][1] - ny0, ny1 - corners[1][1])
        print(f"release box is inside d02, {edge / 1000:.1f} km from its nearest edge",
              file=sys.stderr)
        if edge < 10 * nest.dx:
            print(f"warning: that is within {10 * nest.dx / 1000:.0f} km of the nest "
                  f"boundary, where particles cross into the coarse fields almost "
                  f"immediately and the nest buys you little", file=sys.stderr)


# --------------------------------------------------------------------------- driver

def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Set up a nested (two-domain) FLEXPART-WRF run: nest paths, both "
                    "output grids and the RELEASES blocks, written into flexwrf.input.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("\n\n", 1)[1])
    ap.add_argument("--input", metavar="FLEXWRF_INPUT", required=True,
                    help="flexwrf.input to rewrite: PATHNAMES gains the nest, "
                         "NESTED_OUTPUT is set, the output grids are rebuilt and "
                         "everything after NUMPOINT becomes the new release blocks "
                         "(original kept as FILE.bak)")
    dom = ap.add_argument_group("domains")
    dom.add_argument("--wrf", metavar="PATH", required=True,
                     help="mother-domain wrfout file, or the directory holding them "
                          "(the lowest domain is taken). Grid metres are measured on "
                          "this domain")
    dom.add_argument("--wrf-nest", metavar="PATH", required=True, dest="wrf_nest",
                     help="nest wrfout file, or the directory holding them (the "
                          "highest domain is taken)")
    dom.add_argument("--domain", type=int, metavar="NN",
                     help="pick this domain from --wrf instead of the lowest")
    dom.add_argument("--nest-domain", type=int, metavar="NN", dest="nest_domain",
                     help="pick this domain from --wrf-nest instead of the highest")
    dom.add_argument("--nest-dir", metavar="DIR", dest="nest_dir",
                     help="wrfout directory written into PATHNAMES for the nest "
                          "(default: the directory of --wrf-nest)")
    dom.add_argument("--available-nest", metavar="FILE", dest="available_nest",
                     help="AVAILABLE file for the nest (default: AVAILABLE2 beside "
                          "the mother's AVAILABLE already in the input file)")
    dom.add_argument("--wrf-dir", metavar="DIR", dest="wrf_dir",
                     help="overwrite the mother wrfout directory in PATHNAMES too")
    dom.add_argument("--available", metavar="FILE",
                     help="overwrite the mother AVAILABLE path in PATHNAMES too")

    pos = ap.add_argument_group(
        "release position",
        "in degrees (--lat/--lon or the four corner options) or directly in mother "
        "grid metres (--x1/--y1/--x2/--y2); the box is checked against d02")
    pos.add_argument("--lat", type=float, help="latitude of the release centre [deg]")
    pos.add_argument("--lon", type=float, help="longitude of the release centre [deg]")
    pos.add_argument("--box", type=float, default=1000.0, metavar="METRES",
                     help="side of the release box around --lat/--lon (default: 1000 m)")
    pos.add_argument("--lat1", type=float, help="latitude of the lower-left corner")
    pos.add_argument("--lon1", type=float, help="longitude of the lower-left corner")
    pos.add_argument("--lat2", type=float, help="latitude of the upper-right corner")
    pos.add_argument("--lon2", type=float, help="longitude of the upper-right corner")
    pos.add_argument("--x1", default="98000", help="XPOINT1, lower-left x [grid m]")
    pos.add_argument("--y1", default="177000", help="YPOINT1, lower-left y [grid m]")
    pos.add_argument("--x2", default="99000", help="XPOINT2, upper-right x [grid m]")
    pos.add_argument("--y2", default="178000", help="YPOINT2, upper-right y [grid m]")

    og = ap.add_argument_group(
        "output grids",
        "the main grid covers d01, the nested grid covers d02; both share the "
        "vertical levels, which FLEXPART keeps in one numzgrid")
    og.add_argument("--outgrid", action="store_true",
                    help="rebuild the main OUTGRID section from the mother domain")
    og.add_argument("--outgrid-res", type=float, metavar="METRES", dest="outgrid_res",
                    help="main output cell size (default: the mother dx)")
    og.add_argument("--outgrid-nest-res", type=float, metavar="METRES",
                    dest="outgrid_nest_res",
                    help="nested output cell size (default: the nest dx)")
    og.add_argument("--margin", type=int, default=0, metavar="CELLS",
                    help="inset the nested output grid this many NEST cells from the "
                         "d02 boundary; 5 skips WRF's usual relaxation zone "
                         "(default: 0, cover d02 exactly)")
    og.add_argument("--no-nested-output", action="store_true", dest="no_nested_output",
                    help="drive with d02 winds but keep a single output grid: sets "
                         "NESTED_OUTPUT to 0 and writes no OUTGRID_NEST section")
    og.add_argument("--levels", metavar="LIST",
                    help="output level tops in metres, e.g. \"250,500,1000,2000\"")
    og.add_argument("--dz", type=float, metavar="METRES",
                    help="evenly spaced levels of this thickness, up to --ztop")
    og.add_argument("--nlevels", type=int, metavar="N",
                    help="N evenly spaced levels up to --ztop")
    og.add_argument("--log-levels", type=int, metavar="N", dest="log_levels",
                    help="N logarithmically spaced levels from --zfirst up to --ztop")
    og.add_argument("--zfirst", type=float, default=50.0, metavar="METRES",
                    help="thickness of the lowest layer for --log-levels (default: 50)")
    og.add_argument("--ztop", type=float, metavar="METRES",
                    help="top of the output grid, for --dz / --nlevels / --log-levels")

    rel = ap.add_argument_group("releases")
    rel.add_argument("--start", type=parse_stamp,
                     help="start of the FIRST release (default: the simulation "
                          "beginning date in the input file)")
    rel.add_argument("--end", type=parse_stamp,
                     help="no release starts after this (default: so the last one "
                          "ends at the simulation end)")
    rel.add_argument("--every", type=int, default=3600,
                     help="seconds between consecutive releases (default: 3600)")
    rel.add_argument("--duration", type=int, default=None,
                     help="length of one release in seconds (default: same as --every)")
    rel.add_argument("--kindz", type=int, default=1, choices=(1, 2, 3),
                     help="1 = m above ground, 2 = m above sea level, 3 = pressure")
    rel.add_argument("--z1", type=float, default=0.0, help="ZPOINT1, lower z-level")
    rel.add_argument("--z2", type=float, default=10.0, help="ZPOINT2, upper z-level")
    rel.add_argument("--npart", type=int, default=10000,
                     help="particles released per block (default: 10000)")
    rel.add_argument("--xmass", default=".1000E+0",
                     help="total mass emitted per block (default: .1000E+0)")
    rel.add_argument("--name", default="release", help="release name stem")
    rel.add_argument("--first-index", type=int, default=1, dest="first_index",
                     help="index of the first release name (default: 1)")

    ap.add_argument("--no-backup", action="store_true", dest="no_backup",
                    help="do not keep a .bak copy of the input file")
    ap.add_argument("-o", "--output", metavar="FILE",
                    help="write the new input file here and leave the original alone")
    a = ap.parse_args(argv)

    if a.every <= 0:
        ap.error("--every must be positive")
    if a.box <= 0:
        ap.error("--box must be positive")
    if a.margin < 0:
        ap.error("--margin cannot be negative")
    if a.outgrid_res is not None and a.outgrid_res <= 0:
        ap.error("--outgrid-res must be positive")
    if a.outgrid_nest_res is not None and a.outgrid_nest_res <= 0:
        ap.error("--outgrid-nest-res must be positive")
    duration = timedelta(seconds=a.duration if a.duration is not None else a.every)
    levels = build_levels(a, ap) if a.outgrid else None

    # ------------------------------------------------------------------ the grids
    mother = wrfgrid.WrfGrid(pick_wrfout(a.wrf, a.domain))
    nest = wrfgrid.WrfGrid(pick_wrfout(a.wrf_nest, a.nest_domain, innermost=True))
    print("mother " + mother.describe(), file=sys.stderr)
    print("nest   " + nest.describe(), file=sys.stderr)
    check_nest(mother, nest)
    resolve_position(a, ap, mother, nest)

    # ------------------------------------------------------------- the input file
    lines, numpoint, sim_start, sim_end = read_input(a.input)
    if sim_start and sim_end:
        print(f"{a.input}: simulation {sim_start:%Y-%m-%d %H:%M} -> "
              f"{sim_end:%Y-%m-%d %H:%M}", file=sys.stderr)

    _, _, pathblock = read_pathnames(lines)
    mother_available = a.available or pathblock[2].strip()
    nest_available = a.available_nest or os.path.join(
        os.path.dirname(mother_available) or ".", "AVAILABLE2")
    nest_dir = as_dir(a.nest_dir or a.wrf_nest)
    check_available(mother_available, nest_available, sim_start, sim_end)

    # ------------------------------------------------------------------- releases
    start, end = a.start, a.end
    if start is None:
        if sim_start is None:
            ap.error(f"--start is required (no simulation beginning date in {a.input})")
        start = sim_start
        print(f"--start not given, using the simulation start {start:%Y%m%d %H%M%S}",
              file=sys.stderr)
    if end is None:
        if sim_end is None:
            ap.error(f"--end is required (no simulation ending date in {a.input})")
        end = sim_end - duration
        print(f"--end not given, no release starts after {end:%Y%m%d %H%M%S} so the "
              f"last one ends by the simulation end {sim_end:%Y%m%d %H%M%S}",
              file=sys.stderr)
    if end < start:
        ap.error("--end is before --start (is the simulation window longer than one "
                 "release?)")

    blocks, t, index = [], start, a.first_index
    while t <= end:
        blocks.append(release_block(t, t + duration, f"{a.name}{index}", a))
        t += timedelta(seconds=a.every)
        index += 1
    last_end = start + (len(blocks) - 1) * timedelta(seconds=a.every) + duration
    if sim_start and start < sim_start:
        print(f"warning: first release {start:%Y%m%d %H%M%S} is before the simulation "
              f"start; FLEXPART will reject it", file=sys.stderr)
    if sim_end and last_end > sim_end:
        print(f"warning: last release ends {last_end:%Y%m%d %H%M%S}, after the "
              f"simulation end; FLEXPART will reject it", file=sys.stderr)

    # ----------------------------------------------------------------- the rewrite
    lines = write_pathnames(lines, nest_dir, nest_available,
                            as_dir(a.wrf_dir) if a.wrf_dir else None, a.available)
    set_switch(lines, "RELEASE_COORD", 0)
    if a.outgrid:
        res = a.outgrid_res or mother.dx
        lines = replace_outgrid(lines, outgrid_lines(mother, res, levels))
        set_switch(lines, "OUTGRID_COORD", 0)
    if a.no_nested_output:
        set_switch(lines, "NESTED_OUTPUT", 0)
        lines = drop_outgrid_nest(lines)
    else:
        # OUTGRID_COORD is one switch for BOTH grids (readinput.f90:1204), and the
        # nest block below is written in grid metres. Flipping it to 0 under a main
        # grid whose numbers are degrees would silently reinterpret them, so refuse
        # instead and let --outgrid rebuild that grid in metres as well.
        if not a.outgrid and get_switch(lines, "OUTGRID_COORD") not in (None, "0"):
            ap.error("OUTGRID_COORD is 1 (degrees) in the input file, but the nested "
                     "output grid is written in grid metres and FLEXPART uses one "
                     "switch for both grids. Rerun with --outgrid (plus the level "
                     "options) so the main grid is rebuilt in metres too")
        set_switch(lines, "NESTED_OUTPUT", 1)
        set_switch(lines, "OUTGRID_COORD", 0)
        lines = replace_outgrid_nest(
            lines, outgrid_nest_lines(mother, nest,
                                      a.outgrid_nest_res or nest.dx, a.margin))
    numpoint = find_numpoint(lines)

    written = write_input(a.input, a.output, lines, numpoint, blocks, len(blocks),
                          not a.no_backup)
    print(f"{len(blocks)} release blocks, {start:%Y%m%d %H%M%S} -> "
          f"{last_end:%Y%m%d %H%M%S}; NUMPOINT set to {len(blocks)} in {written}",
          file=sys.stderr)


if __name__ == "__main__":
    main()
