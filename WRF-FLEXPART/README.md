# FLEXPART-WRF v3.3.2 on Roihu (CSC)

Compile-and-run guide for the INAR working version of **FLEXPART-WRF 3.3.2**, the
offline Lagrangian dispersion model driven by WRF output.

```bash
# the short version, once you know what you are doing
ssh -A -X <username>@roihu-cpu.csc.fi
cd /projappl/project_XXXXXXX/$USER/FLEXPART/WRF-FLEXPART
./compile_roihu.sh                              # -> bin/flexwrf33_gnu_{serial,omp,mpi}
cd run && sbatch --account=project_XXXXXXX run_flexwrf_omp.slurm
```

---

## 1. What this code is

This is **not** the official release from flexpart.eu. It is the INAR working copy of
FLEXPART-WRF 3.3.2, modified by **Diego Aliaga** and **Manuel Bettineschi**, and used
for the SALTENA campaign in Bolivia and for the Izaña campaign (among others). See
[`src/README.md`](src/README.md) for the modification notes and
[`src/README.txt`](src/README.txt) for Brioude's upstream release notes.

Practical consequences:

- Behaviour slightly differs from the official release in places (surface-layer handling,
  reading PBLH from WRF, comparison operators). Do not assume upstream documentation
  describes this binary exactly.
- Do not replace `src/` with a fresh upstream download expecting the same results.

Cite Brioude et al. (2013), Geosci. Model Dev. 6, 1889–1904.

### Repository layout

```
WRF-FLEXPART/
├── compile_roihu.sh       one-command build (this is what you run)
├── compile_roihu.slurm    optional: the same build as a batch job
├── roihu_env.sh           the module stack; sourced by build AND run scripts
├── makefile.roihu         Roihu-adapted makefile (see section 6)
├── src/                   the Fortran sources
├── examples/              Brioude's upstream example input files (see section 4.6)
├── run/                   templates + generators + Slurm scripts
├── build/                 created by the build, one dir per flavour (git-ignored)
├── bin/                   the executables land here (git-ignored)
└── local_reference/       your own namelists and logs (git-ignored)
```

---

## 2. Getting the code onto Roihu

```bash
ssh -A -X <username>@roihu-cpu.csc.fi 

cd /projappl/project_XXXXXXX/$USER
git clone git@github.com:ManuelBettines/FLEXPART-INAR.git FLEXPART
cd FLEXPART/WRF-FLEXPART
```

Code in `/projappl`; wrfout input and model output in `/scratch`. 

---

## 3. Compiling

**You do not need to load any modules or source anything first.** Just run:

```bash
./compile_roihu.sh           
```

It takes a few minutes and is small enough for the login node.

The script sources [`roihu_env.sh`](roihu_env.sh) itself — that is what loads the
module stack and works out the netCDF flags — then builds each flavour in its **own**
directory under `build/`, and installs the result into `bin/`.

At the end of the compilation you should get the following message:
```
==============================================================================
 BUILD SUMMARY
==============================================================================
 FLAVOUR  STATUS   BINARY
 serial   OK       /projappl/project_XXXXXXX/$USER/FLEXPART/WRF-FLEXPART/bin/flexwrf33_gnu_serial (1.1M)
 omp      OK       /projappl/project_XXXXXXX/$USER/FLEXPART/WRF-FLEXPART/bin/flexwrf33_gnu_omp (1.1M)
 mpi      OK       /projappl/project_XXXXXXX/$USER/FLEXPART/WRF-FLEXPART/bin/flexwrf33_gnu_mpi (512)

 All requested flavours built. Binaries are in /projappl/project_XXXXXXX/$USER/FLEXPART/WRF-FLEXPART/bin/
 Next: see README.md -> 'Preparing a run' and run/run_flexwrf_omp.slurm
==============================================================================
```

Per-flavour logs are kept in `build/build_<flavour>.log`.

### Which flavour should I use?

| Binary | When |
|---|---|
| `flexwrf33_gnu_omp` | **the "standard" choice** — one node, many threads. |
| `flexwrf33_gnu_mpi` | hybrid MPI+OpenMP across several nodes. Only when one node is not enough; it scales with particle count, not with output grid size (rank 0 gathers the fields). |
| `flexwrf33_gnu_serial` | debugging and quick tests. |

### Warnings you can ignore during the build

A clean build emits about a dozen warnings per flavour. They all come from upstream
legacy Fortran and are covered by the `-std=legacy` / `-fallow-invalid-boz` /
`-fallow-argument-mismatch` flags:

What you should **not** ignore is anything labelled `Error:` — the build stops there
and the summary reports `FAILED`.

---

## 4. Preparing a run

Work in a per-case directory on `/scratch`, not in the repository:

```bash
mkdir -p /scratch/project_XXXXXXX/$USER/FLEXPART/izana_backward
cd       /scratch/project_XXXXXXX/$USER/FLEXPART/izana_backward
cp /projappl/project_XXXXXXX/$USER/FLEXPART/WRF-FLEXPART/run/* .
```

### 4.1 The input file, and its three path lines

FLEXPART-WRF reads **one** file (different if compared to the "normal" FLEXPART verision, which splits into PATHNAMES, COMMAND,
AGECLASSES, OUTGRID, RECEPTORS, SPECIES and RELEASES). Start from
[`run/flexwrf.input.template`](run/flexwrf.input.template).

It is a **positional, fixed-layout file**: the model reads the first token of each
line and ignores the rest, so you may edit the trailing comments but **never add,
remove or reorder lines**, and never touch the `=====` separators.

Lines 2–4 are bare paths with no comment column, and they are the most common source
of a failed run:

```
=====================FORMER PATHNAMES FILE===================
/scratch/<PROJECT>/<user>/FLEXPART/output/<case>/     <- line 2: OUTPUT directory
/scratch/<PROJECT>/<user>/WRF/wrfout_d01/             <- line 3: directory holding the wrfout files
/projappl/<PROJECT>/<user>/.../run/AVAILABLE1         <- line 4: the AVAILABLE file for that domain
=============================================================
```

- The **trailing slash on the two directories is required.**
- **Each path must be at most 120 characters** (`character :: path(...)*120`,
  `src/com_mod.f90:48`). A longer path is silently truncated and you get
  `#### FLEXPART MODEL ERROR! FILE ####` with a **blank** file name — with no hint that
  length was the problem. CSC paths get long fast, so check:

  ```bash
  awk '/^====/{n++} n==1 && NR>1 {print length($0), $0}' flexwrf.input
  ```

  If you are over, shorten the case directory name or run from a shorter parent.
- With more than one domain, lines 3 and 4 repeat per domain, parent first —
  `generate_releases_nested.py` writes that for you (section 4.4), and
  [`examples/flexwrf.input.backward2`](examples/) shows the layout.

### 4.2 The AVAILABLE file

`AVAILABLE` maps every time step to the wrfout file that contains it: three header
lines, then one row per step.

You can automatically generate the `AVAILABLE` file by running the following command:
```bash
./generate_available.py /scratch/<PROJECT>/<user>/WRF/wrfout_d01/
```
It only needs the path to the WRF output and the script will generate automatically the file needed by WRF-FLEXPART.

### 4.3 The releases and the output grid

`generate_releases.py` fills in the two long sections of `flexwrf.input`: the RELEASES
blocks (a 12-line block per release — hundreds of them for a backward run) and, with
`--outgrid`, the OUTGRID section. One command does both:

```bash
./generate_releases.py --input flexwrf.input --wrf /scratch/project_2018181/GV/run/EU15/ \
    --start "20140201 000000" --end "20140301 000000" \
    --lat 45.3775 --lon 11.94 --box 15000 --z1 0 --z2 10 --npart 10000 \
    --outgrid --log-levels 20 --zfirst 10 --ztop 10000
```

That releases 10 000 particles hourly from a 15 km box around the given point, from
1 February to 1 March, and writes an output grid on the WRF grid with 20 levels that
are thin near the ground. Everything after the `NUMPOINT` line is replaced, `NUMPOINT`
is set to the number of blocks, `RELEASE_COORD` and `OUTGRID_COORD` are set to `0`
(metres, which is what gets written), and the previous file is kept as
`flexwrf.input.bak`.

Re-run it with different options as often as you like: it rewrites, it does not append.
`--wrf` is read for its grid only — the wrfout directory and `AVAILABLE1` in the
PATHNAMES block stay yours to set (section 4.1). The nested script in section 4.4
writes those too.

**The flags**

| Flag | Required | Default | What it does |
|---|---|---|---|
| `--input FILE` | yes | — | the `flexwrf.input` to fill in |
| `--wrf PATH` | yes | — | a wrfout file, or the directory holding them (the **lowest domain** is used — grid metres are measured on the mother domain) |
| `--start "YYYYMMDD HHMMSS"` | no | the simulation start in `--input` | first release |
| `--end "YYYYMMDD HHMMSS"` | no | so the last release ends at the simulation end | no release starts after this |
| `--lat` / `--lon` | yes | — | centre of the release box, in degrees |
| `--box METRES` | no | `1000` | side of the box around `--lat/--lon` |
| `--z1` / `--z2` | no | `0` / `10` | bottom and top of the release, in metres above ground |
| `--npart N` | no | `10000` | particles per release |
| `--outgrid` | no | off | rebuild the OUTGRID section to cover the whole WRF domain |
| `--outgrid-res METRES` | no | the WRF `DX` | coarser output cells; `3000` on a 1 km run cuts the output volume ninefold |

Everything else it writes has a default you rarely need to change: releases are
**hourly and back-to-back** (`--every 3600`), heights are **metres above ground**
(`--kindz 1`), each release emits `.1000E+0` of mass (`--xmass`) and the blocks are
named `release1, release2, ...` (`--name`). The previous file is always kept as
`FILE.bak` unless you pass `--no-backup`, and `-o FILE` writes the result elsewhere
and leaves the original alone.

**Choosing the vertical levels** — one of these four, only with `--outgrid`:

| Flag | What it does |
|---|---|
| `--levels "250,500,2000"` | exactly these level tops, in metres |
| `--dz METRES --ztop METRES` | evenly spaced levels of this thickness |
| `--nlevels N --ztop METRES` | N evenly spaced levels |
| `--log-levels N --ztop METRES` | N levels, thin at the ground and thickening with height; `--zfirst METRES` sets the lowest layer's thickness (default `50`) |

`--log-levels 20 --zfirst 10 --ztop 10000` gives the level tops

```
10    23.4   41.3   65.3   97.3   140.2  197.7  274.5  377.4  515
699.2 945.6  1275.5 1716.8 2307.5 3097.9 4155.6 5571   7465.2 10000
```

— nine levels below 500 m, where 20 evenly spaced ones would have put the first at
500 m. That is usually what you want for a footprint run.

### 4.4 Two WRF domains: `generate_releases_nested.py`

If your WRF run has a nest (`d01` + `d02`) and you want FLEXPART to use both, use
`generate_releases_nested.py`. It takes **exactly the same flags plus `--wrf-nest`**:

```bash
./generate_releases_nested.py --input flexwrf.input \
    --wrf /scratch/.../wrfout_d01/ --wrf-nest /scratch/.../wrfout_d02/ \
    --start "20140201 000000" --end "20140301 000000" \
    --lat 45.3775 --lon 11.94 --box 15000 --z1 0 --z2 10 --npart 10000 \
    --outgrid --log-levels 20 --zfirst 10 --ztop 10000 --margin 5
```

On top of what the single-domain script does, it:

- **writes the PATHNAMES block for you** — both wrfout directories and both AVAILABLE
  files, in the order FLEXPART expects. The nest pair is what actually switches on
  nested input; without it `d02` is ignored no matter what else you set. Only the
  output directory on line 2 is left alone;
- sets `NESTED_OUTPUT = 1` and writes the `OUTGRID_NEST` section covering the `d02`
  footprint, computed with FLEXPART's own placement formula
  (`src/gridcheck_nests.f90:386`) so it lands exactly where the model expects. The
  nested grid shares the main grid's vertical levels — FLEXPART keeps one `NUMZGRID`
  for both, so there is nothing extra to choose;
- checks the release box against **`d02`**, not `d01`, and reports how far it sits
  from the nest edge.

| Extra flag | Required | Default | What it does |
|---|---|---|---|
| `--wrf-nest PATH` | yes | — | the `d02` wrfout file or its directory (the **highest** domain is used) |
| `--margin CELLS` | no | `0` | inset the nested output grid this many `d02` cells from the nest boundary; `5` clears WRF's relaxation zone |
| `--outgrid-nest-res METRES` | no | the `d02` `DX` | coarser cells for the nested output grid |
| `--no-nested-output` | no | off | drive with `d02` winds but keep a single output grid |
| `--available` / `--available-nest` | no | the one in the input file / `AVAILABLE2` beside it | where the AVAILABLE files are |
| `--domain` / `--nest-domain NN` | no | lowest / highest | pick specific domains when a directory holds three or more |

Generate the AVAILABLE files **first** — FLEXPART requires the nest's time steps to be
identical to the mother's and stops otherwise, and this script re-checks that before
writing:

```bash
./generate_available.py /scratch/.../wrfout/      # -> AVAILABLE1 (d01), AVAILABLE2 (d02)
```

It also fails early, with the source line, on the things `gridcheck_nests.f90` would
otherwise stop on halfway into a job: a different `MAP_PROJ`, `STAND_LON` or
`TRUELAT1/2`, a different number of vertical levels, a nest that does not fit inside
the mother domain, or a nest larger than the `nxmaxn`/`nymaxn` compiled into
`par_mod.f90`.

**If your fine domain was run separately (`ndown`).** `ndown` re-runs the inner domain
as its *own* `d01`, so its wrfout says `GRID_ID 1, PARENT_ID 0, I_PARENT_START 1,
PARENT_GRID_RATIO 1` — the nesting metadata is gone even though the grid is still
aligned to the parent. Two symptoms follow:

- the script cannot read the placement off the file, so it **derives it from the two
  grids** instead — inverting the fine grid's corner on the mother grid and checking
  the result is a whole number of coarse cells. It prints what it found:
  `derived placement: I_PARENT_START = 41, J_PARENT_START = 31, ratio 3`. If the
  grids are not aligned it stops and says so, because FLEXPART's nesting assumes the
  fine cells tile the coarse ones exactly;
- **FLEXPART still reads those attributes itself** and stops with
  `gridcheck_nests fatal error -- parent grid not found for l = 1`
  (`src/gridcheck_nests.f90:402`). Nothing in `flexwrf.input` overrides this. The
  script prints the `ncatted` command that writes the attributes back onto the fine
  wrfout files; run it (on a backup — it edits in place), then rerun the script and
  it will report `from the attributes` instead of `from the geometry`.

### 4.5 Switches worth understanding

| Switch | Notes |
|---|---|
| `LDIRECT` | `1` forward, `-1` backward (source–receptor / footprint runs) |
| `IOUT` | `1` concentration, `2` mixing ratio, `3` both, `4` plume trajectory, `5` = 1+4 |
| `IOUTTYPE` | `0` binary, `1` ASCII, `2` **netCDF** — use 2; the build has netCDF-4 output enabled |
| `NCTIMEREC` | time frames per netCDF file (only with `IOUTTYPE=2`) |
| `IOUTPUTFOREACHREL` | `1` = one output field per release. With ~1000 releases this makes a **lot** of output — check your `/scratch` quota first |
| `NESTED_OUTPUT` | nested output grid, and the `OUTGRID_NEST` section that must follow it; set by `generate_releases_nested.py` (section 4.4) |
| `LAGESPECTRA` / `NAGECLASS` | age spectra; `NAGECLASS` must be `<= maxageclass` (section 2) |
| `SFC_OPTION` | `0` = diagnose u*, heat flux, PBLH; `1` = take them from WRF (see below) |
| `TURB_OPTION` | `0` none, `1` diagnosed (FLEXPART-ECMWF style), `2`/`3` from WRF TKE |
| `WIND_OPTION` | `0` snapshot, `1` time-averaged, `2` snapshot eta-dot, `-1` w from divergence |
| `OUTGRID_COORD` / `RELEASE_COORD` | `0` WRF grid metres, `1` lat/lon — they are independent |

**About `SFC_OPTION = 1`:** the model prints

```
 #### FLEXPART MODEL ERROR! SFC_OPTION =           1
 #### Reading from WRF no longer supported.
 be careful option added by Diego
```

This looks fatal but **is not** — the `stop` is deliberately commented out in
`src/readinput.f90:584`, because reading PBLH from WRF is exactly what Aliaga's
modification re-enabled. The message is stale upstream text. The run continues
normally, and this is the setting the INAR Izaña runs use.

### 4.6 A note on `examples/`

The files in `examples/` are Brioude's upstream test cases. They are useful as a
**format reference**, but they will not run against this binary unchanged: they use
`NAGECLASS = 2` and multiple species, while the committed `par_mod.f90` has
`maxageclass = 1` and `maxspec = 1`. Either raise those limits and rebuild
(section 2), or just read the files for their layout.

### 4.7 Checking an input file without burning a job

The serial binary parses the whole input and reports the first problem in seconds:

```bash
../bin/flexwrf33_gnu_serial flexwrf.input 2>&1 | head -40
```

Reaching `Opening file: .../AVAILABLE1 for reading` means every section parsed. Anything
earlier is a formatting or limits problem.

---

## 5. Submitting

```bash
sbatch --account=project_XXXXXXX run_flexwrf_omp.slurm      # single node, OpenMP
sbatch --account=project_XXXXXXX run_flexwrf_mpi.slurm      # multi-node, MPI+OpenMP
```

Both scripts `source ../roihu_env.sh`, so **the modules at run time are exactly the
ones used at build time** — that is why no `LD_LIBRARY_PATH` has to be set. If you
launch the binary yourself, source that file first.

Edit the `#SBATCH` header and the CONFIGURATION block at the top of the script:

| Setting | Default | Notes |
|---|---|---|
| `--partition` | `small` (omp) / `medium` (mpi) | `test` for a quick check; see `sinfo` and the CSC docs for the limits |
| `--cpus-per-task` | 32 | becomes `OMP_NUM_THREADS`; do not exceed the cores on a node (`sinfo -o "%P %c"`) |
| `--mem` | 64G | raise it for large domains — the arrays are sized by `par_mod.f90`, not by the run |
| `--time` | 36:00:00 | check the partition's limit before requesting it |
| `FLEXWRF_BIN` | `../bin/flexwrf33_gnu_omp` | which executable |
| `FLEXWRF_INPUT` | `flexwrf.input` | which input file |

`--account` is deliberately not hard-coded, so the scripts work for everyone at INAR.
Pass it on the command line, or export `SBATCH_ACCOUNT=project_XXXXXXX` in your
`~/.bashrc`.

Monitor with `squeue --me`, `seff <jobid>` (efficiency after it finishes) and the
`flexwrf_<jobid>.out` / `.err` files.

---

## 6. Troubleshooting

