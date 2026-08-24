# FLEXPART v11 on Roihu (CSC)

Compile-and-run guide for the INAR working version of **FLEXPART v11**, the standard
(global) Lagrangian particle dispersion model, driven by ECMWF meteorology.

```bash
# the short version, once you know what you are doing
ssh -A -X <username>@roihu-cpu.csc.fi
cd /projappl/project_XXXXXXX/$USER/FLEXPART/FLEXPART_v11
./compile_roihu.sh                              # -> bin/FLEXPART_ETA, bin/FLEXPART
cd /scratch/project_XXXXXXX/$USER/FLEXPART/mycase
sbatch --account=project_XXXXXXX run_flexpart.slurm
```

The input files come from **flex_extract**, so set that up first:
[`../FLEX_EXTRACT/`](../FLEX_EXTRACT/).

---

## 1. What this code is

This is **not** an untouched release from flexpart.eu. It is the INAR working copy of
FLEXPART 11, with local modifications:

- `src/chemistry_mod.f90` — the reagent arrays (OH and friends, for the Linear
  Chemistry Module) are allocated to the **chemical field's own grid** instead of the
  meteorological one. With a regional retrieval and a global OH field the old code
  wrote past the end of the array inside `nf90_get_var` and the run died in `malloc`.
- `src/com_mod.f90`, `src/readoptions_mod.f90` — a `PFALLOFF` rate-law selector in
  `REAGENTS`/`SPECIES`: `0` keeps the modified-Arrhenius form, `1` selects a Troe
  pressure-dependent falloff.

The `*.f90_original` files next to them are the upstream versions, so the change is
always one `diff` away:

```bash
diff src/chemistry_mod.f90_original src/chemistry_mod.f90
```

Do not replace `src/` with a fresh upstream download expecting the same results.

Cite Pisso et al. (2019), Geosci. Model Dev. 12, 4955–4997, plus the v11 reference
once published. Upstream documentation lives in [`documentation/docs/`](documentation/docs/)
and at <https://flexpart.img.univie.ac.at/docs>.

### FLEXPART v11 vs FLEXPART-WRF, in one table

If you have used [`../WRF-FLEXPART/`](../WRF-FLEXPART/), these are the differences that
will trip you up:

| | FLEXPART v11 | FLEXPART-WRF 3.3.2 |
|---|---|---|
| Input meteorology | ECMWF GRIB from flex_extract | your own `wrfout` netCDF |
| Configuration | **many** files in an `options/` directory, plus `pathnames` | one `flexwrf.input` |
| File format | Fortran **namelists** (`&COMMAND`, `&RELEASE`, ...) | positional, fixed-layout |
| Horizontal coordinates | degrees, always | WRF grid metres or degrees |
| Parallelism | OpenMP only, **one node** | OpenMP or MPI+OpenMP |
| Array sizes | allocated at run time | fixed in `par_mod.f90`, rebuild to change |
| Extra library | **ecCodes** (GRIB) | — |

The last two are the good news: v11 has no `maxspec`, `maxpart` or `nxmax` to raise,
so a bigger domain or more species needs more memory, not a rebuild.

### Repository layout

```
FLEXPART_v11/
├── compile_roihu.sh       one-command build (this is what you run)
├── compile_roihu.slurm    optional: the same build as a batch job
├── roihu_env.sh           the module stack; sourced by build AND run scripts
├── makefile.roihu         Roihu-adapted makefile (see section 6)
├── src/                   the Fortran sources
├── options/               the option files a run needs, as defaults to copy
├── options.reference/     upstream reference copies, including the old formats
├── examples/              upstream example option sets (Tracer, Aerosol, Nuclear)
├── documentation/         upstream mkdocs documentation
├── containers/            upstream Docker/Singularity recipes (not used on Roihu)
├── tests/                 upstream test cases
├── run/                   templates + generators + the Slurm script
├── build/                 created by the build, one dir per flavour (git-ignored)
├── bin/                   the executables land here (git-ignored)
└── local_reference/       your own namelists, logs and old runs (git-ignored)
```

---

## 2. Getting the code onto Roihu

```bash
ssh -A -X <username>@roihu-cpu.csc.fi

cd /projappl/project_XXXXXXX/$USER
git clone git@github.com:ManuelBettines/FLEXPART-INAR.git FLEXPART
cd FLEXPART/FLEXPART_v11
```

Code in `/projappl`; ECMWF input and model output in `/scratch`.

---

## 3. Compiling

**You do not need to load any modules or source anything first.** Just run:

```bash
./compile_roihu.sh
```

It takes a few minutes and is small enough for the login node.

The script sources [`roihu_env.sh`](roihu_env.sh) itself — that is what loads the
module stack (gcc, OpenMPI, HDF5, netCDF **and ecCodes**) and works out the include
and link flags — then builds each flavour in its **own** directory under `build/`, and
installs the result into `bin/`.

At the end you should get:

```
==============================================================================
 BUILD SUMMARY
==============================================================================
 FLAVOUR    STATUS   BINARY
 eta        OK       /projappl/.../FLEXPART_v11/bin/FLEXPART_ETA (2.7M)
 meter      OK       /projappl/.../FLEXPART_v11/bin/FLEXPART (2.7M)

 All requested flavours built. Binaries are in /projappl/.../FLEXPART_v11/bin/
 Next: see README.md -> 'Preparing a run' and run/run_flexpart.slurm
==============================================================================
```

Per-flavour logs are kept in `build/build_<flavour>.log`.

### Which flavour should I use?

The four flavours are two independent switches: the vertical coordinate, and the
output format.

| Flavour | Binary | When |
|---|---|---|
| `eta` | `FLEXPART_ETA` | **the standard choice** — trajectories in ECMWF's native hybrid (eta) coordinate, netCDF output. Requires ECMWF data (which is what flex_extract gives you) |
| `meter` | `FLEXPART` | metre coordinates; needed for GFS input, and the fallback if an eta run misbehaves |
| `eta_bin` | `FLEXPART_ETA_BIN` | as `eta` but FLEXPART's own binary output — only if you have a reader for it |
| `meter_bin` | `FLEXPART_BIN` | as `meter`, binary output |

```bash
./compile_roihu.sh eta            # just the one you need
./compile_roihu.sh all -j 16      # all four
./compile_roihu.sh eta --clean    # rebuild from scratch
./compile_roihu.sh eta --debug    # -O0 -g -fbacktrace, lands in bin/FLEXPART_ETA_dbg
```

**There is no MPI flavour, and that is not an omission.** FLEXPART v11 has no MPI code
— v10.4's MPI layer was replaced by OpenMP over the particle loop. `src/` contains no
`mpi_mod.f90` and nothing is guarded by `#ifdef usempi`; the upstream makefile's
`mpi=yes` switch only ever defined an unused preprocessor symbol, and is dropped in
`makefile.roihu`. One task, many threads, one node. Asking Slurm for several nodes
leaves all but the first idle.

### Parameters you may still want to change

Everything that used to be a compile-time array bound is allocated at run time in v11,
so `par_mod.f90` is much less interesting than in FLEXPART-WRF. Two exceptions matter:

| `par_mod.f90` | Value here | Meaning |
|---|---|---|
| `numpf` (line 190) | **3** | number of precipitation fields per time step in the GRIB input |
| `idiffnorm`, `idiffmax` (line 122) | 10800, 21600 | normal / maximum spacing of the wind fields, in seconds |

`numpf=3` is a **hard coupling to flex_extract**: it means the input must carry the
disaggregated sub-grid precipitation, which is what `RRINT 1` in the CONTROL file
produces. Get the pair wrong and the run stops early with

```
*** ERROR: additional precip fields available        ***
*** You must use them, set numpf=3 and recompile     ***
```

(RRINT 1 in CONTROL, numpf 1 in par_mod) or

```
Conditions for precipitation interpolation not fulfilled! Please check number of
precipitation fields per type in GRIB files and numpf parameter in par_mod.f90.
```

(RRINT 0 in CONTROL, numpf 3 here). The INAR CONTROL files all set `RRINT 1`, so
leave `numpf=3` alone unless you are reading somebody else's retrieval.

`idiffnorm` also constrains the COMMAND file: `LSYNCTIME` must be **≤ 5400 s**
(`idiffnorm/2`), or readcommand stops.

### Warnings you can ignore during the build

`-Wall` is only on in the `--debug` build, so a normal build is quiet apart from a
handful of unused-variable and unused-dummy-argument notes from upstream code. What
you should **not** ignore is anything labelled `Error:` — the build stops there and
the summary reports `FAILED`.

---

## 4. Preparing a run

Work in a per-case directory on `/scratch`, not in the repository:

```bash
mkdir -p /scratch/project_XXXXXXX/$USER/FLEXPART/volcano_2018
cd       /scratch/project_XXXXXXX/$USER/FLEXPART/volcano_2018

cp -r /projappl/project_XXXXXXX/$USER/FLEXPART/FLEXPART_v11/options .
cp    /projappl/project_XXXXXXX/$USER/FLEXPART/FLEXPART_v11/run/* .
mv    pathnames.template pathnames
```

Then edit the four lines of `pathnames` (4.1) and the `FP_ROOT` line at the top of
`run_flexpart.slurm` (section 5).

A v11 case directory then holds:

```
volcano_2018/
├── pathnames            four lines: where everything else is
├── AVAILABLE            generated, see 4.2
├── options/             COMMAND, RELEASES, OUTGRID, SPECIES/, ... see 4.3
└── run_flexpart.slurm   the job script
```

### 4.1 `pathnames`, and its four lines

FLEXPART reads `pathnames` from the directory you launch it in (or from the file named
on the command line). Four lines, in this order — `readpaths`,
`src/readoptions_mod.f90:1861`:

```
options/                                              <- 1: the options directory
/scratch/<PROJECT>/<user>/FLEXPART/output/<case>/     <- 2: OUTPUT directory
/scratch/<PROJECT>/<user>/FLEXPART/ERA5/<case>/       <- 3: the GRIB files
AVAILABLE                                             <- 4: the AVAILABLE file
============================================
```

- The **first three are directories and must end in `/`.** FLEXPART pads a missing
  slash and tells you it did (`WARNING: path not ending in /` ... `fix: padded with /`),
  so this one is survivable.
- **Each path is at most 120 characters** (`character :: path(...)*120`,
  `src/com_mod.f90:44`), and is truncated at its **first blank**. A path with a space
  in it silently becomes a different path. CSC paths get long; check with:

  ```bash
  awk 'NR<=4 {print length($0), $0}' pathnames
  ```
- Line 2 is the only one FLEXPART does not create for you. `run_flexpart.slurm`
  creates it, and checks the other three exist, before launching anything.
- For nested meteorology, add **two** lines per nest after the `=====` separator (nest
  GRIB directory, then nest AVAILABLE), up to `maxnests = 5`. Every nest must have
  *exactly* the same time steps as the mother domain or readavailable stops.

### 4.2 The AVAILABLE file

`AVAILABLE` maps every time step to the GRIB file that holds it: three header lines,
then one row per step. Generate it:

```bash
./generate_available.py /scratch/<PROJECT>/<user>/FLEXPART/ERA5/<case>/
```

That is all it needs — flex_extract names its output `<PREFIX><YYMMDDHH>`
(`EA18010100`), so the script reads the times straight off the names, sorts them,
writes `./AVAILABLE`, and tells you what it found:

```
scanning 744 file(s)
744 wind fields, 2018-01-01 00:00 -> 2018-01-31 23:00, every 1 h
reminder: LSYNCTIME in COMMAND must be <= 5400 s
-> /scratch/.../volcano_2018/AVAILABLE
```

Two things it protects you from:

- **The three header lines.** `readavailable` skips exactly three lines before the
  first record (`src/readoptions_mod.f90:205`). The older `generateAVAILABLE.py`
  (now in `local_reference/`) wrote two, so FLEXPART silently ate the first wind field
  of every run — present in the file, never used, no warning.
- **flex_extract's working files.** When `INPUTDIR` and `OUTPUTDIR` are the same
  directory — which is how the INAR `run_local.sh` is set up — `flux18010100`,
  `EA18010100_1`, `fort.15` and `OG_OROLSM__SL.*` sit right next to the real output.
  `flux18010100` parses as a perfectly good name and would end up in AVAILABLE,
  pointing FLEXPART at a file with no wind fields in it. They are skipped by name
  (`--keep-work-files` if you ever need them listed).

The columns are not free-form. `readavailable` reads
`'(i8,1x,i6,2(6x,a255))'`, i.e. `YYYYMMDD`, a blank, `HHMMSS`, six blanks, then the
name from **column 22**; everything after the first blank following the name is a
comment (flex_extract writes `ON DISK`). A misplaced column does not produce an error,
just a garbage date.

| Flag | Default | What it does |
|---|---|---|
| `-o FILE` | `AVAILABLE` | where to write it; `-` means stdout |
| `--start` / `--end` | the whole directory | drop steps outside the period (`YYYYMMDD` or `'YYYYMMDD HHMMSS'`) |
| `--every SECONDS` | every field present | use only every Nth field, e.g. `10800` for 3-hourly from hourly output. Must divide the native spacing, and stay ≤ 21600 |
| `--from-grib` | off | take the time from each file's GRIB header (`dataDate`/`dataTime`/`step`) instead of its name — slower, but it verifies the retrieval |
| `--pattern GLOB` | `*` | narrow the scan, e.g. `'EA*'` |
| `--century YYYY` | 2000 | how to read the two-digit year in the names |
| `-v` | off | print the time found for every file |

It refuses to be quiet about gaps: a hole larger than `idiffmax` (6 h) is reported as
`ERROR-IN-WAITING`, because FLEXPART's response is to skip trajectories across it —
a warning in the log, not a crash, and easy to miss in a 36-hour job.

### 4.3 The options directory

| File | What it is | Edit it? |
|---|---|---|
| `COMMAND` | direction, period, output intervals, all the switches | **yes**, every run |
| `RELEASES` | what is released, where and when | **yes** — with `generate_releases.py` (4.4) |
| `OUTGRID` | the output grid | **yes** — `generate_releases.py --outgrid` |
| `OUTGRID_NEST` | nested output grid, only if `NESTED_OUTPUT=1` | rarely |
| `AGECLASSES` | age spectra, only if `LAGESPECTRA=1` | rarely |
| `PARTOPTIONS` | which particle fields are written when `IPOUT>0` | sometimes |
| `RECEPTORS` | receptor points, only if `IND_RECEPTOR>0` | sometimes |
| `SPECIES/` | the species database (`SPECIES_NNN`, plus named ones) | no, pick from it |
| `REAGENTS`, `oh_fields/` | chemical reagents for `LCMOUTPUT=1` | path only |
| `IGBP_int1.dat`, `sfcdata.t`, `sfcdepo.t` | land use and surface tables | never |
| `INITCONC`, `SATELLITES` | initial conditions / satellite sampling | rarely |

`REAGENTS` contains an **absolute** path to `options/oh_fields/`; fix it to your own
checkout before switching the Linear Chemistry Module on. Everything else works from
the copied directory as it stands.

The files in `examples/` (Tracer, Aerosol, Nuclear) are complete upstream option sets
and are the fastest way to see a working combination. `options.reference/` holds the
upstream copies including the **old, non-namelist** formats — useful for reading an
inherited v9/v10 setup, not for running v11, which stops with

```
RELEASE either having unrecognised entries, or in old format, please update to
namelist format.
```

### 4.4 Releases and the output grid

`generate_releases.py` writes the whole `RELEASES` file, and with `--outgrid` the
`OUTGRID` file too. One command does both:

```bash
./generate_releases.py --command options/COMMAND -o options/RELEASES \
    --control /projappl/.../FLEX_EXTRACT/Run/Control/CONTROL_EA5.VolcanoSA \
    --lat -15.79 --lon -71.86 --box 10 --z1 5967 --z2 6067 --zkind 2 \
    --specnum 23 --mass 8.6924e4 --npart 240000 --every 86400 \
    --outgrid options/OUTGRID --log-levels 20 --zfirst 50 --ztop 20000
```

That releases SO₂ daily from a 10 km box around Sabancaya between 5967 and 6067 m
a.s.l., over the whole period in `COMMAND`, and writes an output grid covering the
whole retrieved domain with 20 levels that are thin near the ground. The previous
files are kept as `.bak`. Re-run it as often as you like: it rewrites, it does not
append.

Two checks it does that save a job:

- every release must lie inside the period in `COMMAND` — for **both** directions,
  because readcommand swaps the two dates internally for a backward run, so the
  window is always `[IBDATE IBTIME, IEDATE IETIME]` as written;
- with `--control`, the release box **and** the output grid must lie inside the area
  flex_extract actually retrieved (`LEFT`/`RIGHT`/`LOWER`/`UPPER`). This is the
  `#### PART OF OUTPUT GRID IS OUTSIDE MODEL DOMAIN ####` stop, which otherwise
  arrives a few minutes into the job.

**Where it writes**

| Flag | Required | Default | What it does |
|---|---|---|---|
| `-o FILE` | no | `./RELEASES` | the RELEASES file to write; `-` means stdout |
| `--command FILE` | in practice | — | the COMMAND file: gives the period and direction, and every release is checked against them |
| `--control FILE` | no | — | a flex_extract CONTROL file, for the domain check |
| `--no-backup` | no | keeps `FILE.bak` | skip the backup copy |

**When to release**

| Flag | Default | What it does |
|---|---|---|
| `--start "YYYYMMDD HHMMSS"` | the simulation start | first release |
| `--end "YYYYMMDD HHMMSS"` | so the last release ends at the simulation end | no release starts after this |
| `--every SECONDS` | `3600` | spacing between releases |
| `--duration SECONDS` | same as `--every` | length of one release (back-to-back by default); `0` for instantaneous |

**Where to release** — centre + size, or corners:

| Flag | Default | What it does |
|---|---|---|
| `--lat` / `--lon` | — | centre of the release box, in degrees |
| `--box KM` | `10` | side of the box around `--lat/--lon`, in km (converted with the local `cos(lat)`) |
| `--box-deg DEG` | — | side of the box in degrees instead |
| `--lon1 --lat1 --lon2 --lat2` | — | box corners (SW first) instead of centre + size |
| `--z1` / `--z2` | `0` / `100` | bottom and top of the release |
| `--zkind {1,2,3}` | `1` | `1` m above ground, `2` m above sea level, `3` pressure in hPa |

**What to release**

| Flag | Default | What it does |
|---|---|---|
| `--specnum N` | `24` (AIRTRACER) | the `NNN` of `options/SPECIES/SPECIES_NNN`; repeat for several species |
| `--mass KG` | `1.0` | mass per release **per species**; repeat in the same order as `--specnum`. Irrelevant for backward runs |
| `--npart N` | `10000` | particles per release. Zero makes FLEXPART stop |
| `--name STEM` | `release` | blocks are commented `release1`, `release2`, ... (40 characters max) |
| `--first-index N` | `1` | number the first block from here |

**The output grid** — only with `--outgrid`:

| Flag | Default | What it does |
|---|---|---|
| `--outgrid [FILE]` | off (`OUTGRID`) | also write the OUTGRID file |
| `--outlon0 --outlat0 --outlon1 --outlat1` | the retrieved domain (needs `--control`) | corners of the output grid, in degrees |
| `--res DEG` | the retrieval's `GRID` | cell size; `--dxout`/`--dyout` to set them separately |
| `--levels "250,500,2000"` | one of these four is required | exactly these level tops, in metres |
| `--dz METRES --ztop METRES` | — | evenly spaced levels of this thickness |
| `--nlevels N --ztop METRES` | — | N evenly spaced levels |
| `--log-levels N --ztop METRES` | — | N levels, thin at the ground and thickening with height |
| `--zfirst METRES` | `50` | thickness of the lowest layer, with `--log-levels` |

`--log-levels 20 --zfirst 50 --ztop 20000` gives level tops of

```
50  113  193  294  421  581  784  1039  1362  1770  2285  2935  3756  4793
6101  7754  9840  12474  15800  20000
```

— six levels below 800 m, where 20 evenly spaced ones would have put the whole
boundary layer in a single 1 km slab. That is usually what you want for a footprint
run. Note that `NUMXGRID`/`NUMYGRID` count **cells**, not points, whatever the comment
in older copies of `OUTGRID` says: readoutgrid checks
`outlon0 + numxgrid*dxout` against the edge of the meteorological domain
(`src/readoptions_mod.f90:1576`).

### 4.5 Switches worth understanding, in `COMMAND`

| Switch | Notes |
|---|---|
| `LDIRECT` | `1` forward, `-1` backward (source–receptor / footprint runs) |
| `IBDATE`/`IBTIME`, `IEDATE`/`IETIME` | the simulation period. Every release must be inside it, in both directions |
| `LOUTSTEP` / `LOUTAVER` / `LOUTSAMPLE` | output interval / averaging window / sampling interval, in seconds. `LOUTAVER ≤ LOUTSTEP` |
| `LSYNCTIME` | the global time step; **must be ≤ 5400 s** (`idiffnorm/2`) |
| `CTL`, `IFINE` | negative `CTL` uses `LSYNCTIME` in the boundary layer; `CTL > 1` makes the ABL step `TL/CTL` and is what you want with `CBLFLAG=1` |
| `IOUT` | `1` mass, `2` mixing ratio, `3` both, `4` plume, `5` = 1+4; **+8** also turns netCDF output on |
| `LNETCDFOUT` | `1` (the default) gives netCDF gridded output. Requires an `ncf=yes` build — the `eta` and `meter` flavours |
| `IPOUT` | particle dump: `0` off, `1` every output step, `2` only at the end. Needs a netCDF build; the fields written are chosen in `PARTOPTIONS` |
| `IOUTPUTFOREACHRELEASE` | `1` = one output field per release. With ~1000 releases this is a **lot** of output — check your `/scratch` quota first |
| `LOUTRESTART` | interval for restart files, `-1` to switch off. Set it on long jobs and restart with `IPIN=1` |
| `MAXTHREADGRID` | threads used for the grid computations; 1 (no grid parallelism) up to ~16. Higher costs memory |
| `NESTED_OUTPUT` | writes `OUTGRID_NEST` as well |
| `LAGESPECTRA` | age spectra; needs `AGECLASSES` |
| `IND_SOURCE` / `IND_RECEPTOR` | mass vs mixing ratio at source/receptor; `IND_RECEPTOR` 3/4 give backward wet/dry deposition |
| `LCMOUTPUT` | the Linear Chemistry Module; needs `REAGENTS` and the OH fields |
| `NXSHIFT` | shift of the global met data; **0 for a regional retrieval**, 359 for global ECMWF |

### 4.6 Checking an input file without burning a job

FLEXPART parses everything before it reads the first wind field, so a short
interactive run on the login node finds most mistakes in seconds:

```bash
source /projappl/.../FLEXPART_v11/roihu_env.sh
/projappl/.../FLEXPART_v11/bin/FLEXPART_ETA pathnames 2>&1 | head -60
```

Reaching `Reading windfields` (or the first `gridcheck` output) means `pathnames`,
`COMMAND`, `RELEASES`, `OUTGRID` and `SPECIES` all parsed. Stop it with Ctrl-C — do
not let a real run continue on a login node.

---

## 5. Submitting

```bash
sbatch --account=project_XXXXXXX run_flexpart.slurm
```

The script sources `../roihu_env.sh`, so **the modules at run time are exactly the
ones used at build time** — that is why no `LD_LIBRARY_PATH` has to be set. (The old
`launch_flexpart_mpi.sh`, now in `local_reference/`, hard-coded a 300-character Puhti
`LD_LIBRARY_PATH`; do not copy it.)

Edit the `#SBATCH` header and the CONFIGURATION block at the top of the script:

| Setting | Default | Notes |
|---|---|---|
| `--partition` | `small` | `test` for a quick check; see `sinfo` and the CSC docs |
| `--cpus-per-task` | 32 | becomes `OMP_NUM_THREADS`; do not exceed the cores on a node (`sinfo -o "%P %c"`) |
| `--nodes` | 1 | leave it at 1 — there is no MPI (section 3) |
| `--mem` | 64G | v11 allocates by run size: particles, output grid and the met domain. Large grids with `IOUTPUTFOREACHRELEASE=1` need much more |
| `--time` | 36:00:00 | check the partition's limit; for longer runs set `LOUTRESTART` and restart with `IPIN=1` |
| `FP_ROOT` | `/projappl/project_XXXXXXX/$USER/FLEXPART/FLEXPART_v11` | **edit this** — the case directory is on `/scratch` and the code on `/projappl`, so there is no relative default. `FP_BIN` and the environment file are derived from it |
| `FP_BIN` | `$FP_ROOT/bin/FLEXPART_ETA` | which executable |
| `FP_PATHNAMES` | `pathnames` | which pathnames file |

`--account` is deliberately not hard-coded, so the scripts work for everyone at INAR.
Pass it on the command line, or export `SBATCH_ACCOUNT=project_XXXXXXX` in your
`~/.bashrc`.

Monitor with `squeue --me`, `seff <jobid>` (efficiency after it finishes) and the
`flexpart_<jobid>.out` / `.err` files.

---

## 6. Troubleshooting

**`EC_FLIBS is empty — you must 'source roihu_env.sh' before running make`**
You ran `make` by hand in `src/`. Use `./compile_roihu.sh`, or source the environment
first. The upstream makefiles (`src/makefile_gfortran`) additionally require `CPATH`
and `LIBRARY_PATH` to be set, which Roihu's modules do not reliably do — that is the
whole reason `makefile.roihu` exists.

**`f77: command not found`**
You ran an upstream makefile, which never sets `FC`, so make fell back to its built-in
default. `makefile.roihu` sets it (and note that `FC ?= gfortran` does *not* fix this:
make's built-in `FC` counts as defined, so `?=` never fires).

**`Can't open module file 'grib_api.mod'`**
ecCodes is not loaded, or its module does not export a prefix `roihu_env.sh`
recognises. Check `module spider eccodes`, then
`FP11_ECCODES=eccodes/<version> ./compile_roihu.sh`, or set `ECCODES_DIR` by hand.

**`#### FLEXPART MODEL ERROR! AVAILABLE FILE ... CANNOT BE OPENED`**
Line 4 of `pathnames` is wrong, or relative to a different directory than the one you
launched from. Note the path is truncated at its first blank.

**`NO WIND FIELDS AVAILABLE FOR SELECTED TIME PERIOD`**
The period in `COMMAND` and the rows in `AVAILABLE` do not overlap — check for the
two-vs-three header line problem (4.2), and remember FLEXPART only uses fields within
one day either side of the simulation period.

**`FILE AVAILABLE IS CORRUPT. THE WIND FIELDS ARE NOT IN TEMPORAL ORDER`**
Two rows with the same or decreasing time. `generate_available.py` sorts and
de-duplicates, so this means the file was edited by hand.

**`Release starts before simulation begins or ends after simulation stops`**
A release outside `[IBDATE IBTIME, IEDATE IETIME]`. Regenerate `RELEASES` with
`--command options/COMMAND` and the script will not let it happen.

**`RELEASE either having unrecognised entries, or in old format`**
A v9/v10-style positional `RELEASES` file. v11 wants namelists; see
`options.reference/RELEASES` for the old format and `options/RELEASES` for the new.

**`#### PART OF OUTPUT GRID IS OUTSIDE MODEL DOMAIN`**
`OUTLON0 + NUMXGRID*DXOUT` (or the y equivalent) reaches past the edge of the
retrieval. Remember `NUMXGRID` counts cells. Regenerate with
`generate_releases.py --outgrid --control <CONTROL file>`.

**`set numpf to 3 in par_mod.f90` / `Conditions for precipitation interpolation not fulfilled`**
The `RRINT` setting of the retrieval and `numpf` in `par_mod.f90` disagree — see
section 3.

**Illegal instruction (SIGILL) in a job that compiled fine**
A binary built with a wider instruction set than the compute node supports.
`makefile.roihu` defaults to `-march=core-avx2` for exactly this reason; if you built
with `--arch native` on the login node, rebuild without it.

**The job runs but the output is all zeros**
Usually the release is outside the output grid, the release height is above the top
level, or `IOUT`/`LNETCDFOUT` selected a format you are not reading. Check the
`Particles released (numpartmax)` line in the log first.
