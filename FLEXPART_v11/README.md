# FLEXPART v11 on Roihu (CSC)

Compile-and-run guide for the INAR working version of **FLEXPART v11**, the standard
(global) Lagrangian particle dispersion model, driven by ECMWF meteorology.

The meteorological input comes from **flex_extract**, so set that up first:
[`../FLEX_EXTRACT/`](../FLEX_EXTRACT/).

---

## 1. What this code is

This is **not** an untouched release from flexpart.eu. It is the INAR working copy of
FLEXPART 11, modified by **Manuel Bettineschi**:

- `src/chemistry_mod.f90` — the reagent arrays (OH and friends, for the Linear
  Chemistry Module) are allocated on the **chemical field's own grid** instead of the
  meteorological one. With a regional retrieval and a global OH field the original
  code wrote past the end of the array and the run died in `malloc`.
- `src/com_mod.f90`, `src/readoptions_mod.f90` — a `PFALLOFF` rate-law selector in
  `REAGENTS`/`SPECIES`: `0` keeps the modified-Arrhenius form, `1` selects a Troe
  pressure-dependent falloff.

The upstream version of each modified file is kept beside it as `*.f90_original`, so
the change is one `diff` away:

```bash
diff src/chemistry_mod.f90_original src/chemistry_mod.f90
```

Do not replace `src/` with a fresh upstream download expecting the same results.

### Repository layout

```
FLEXPART_v11/
├── compile_roihu.sh       one-command build (this is what you run)
├── compile_roihu.slurm    optional: the same build as a batch job
├── roihu_env.sh           the module stack; sourced by build AND run scripts
├── makefile.roihu         Roihu-adapted makefile
├── src/                   the Fortran sources
├── options/               the option files a run needs, as defaults to copy
├── options.reference/     upstream reference copies, including the old formats
├── examples/              upstream example option sets (Tracer, Aerosol, Nuclear)
├── documentation/         upstream mkdocs documentation
├── tests/                 upstream test cases
├── run/                   templates + generators + the Slurm script
├── build/                 created by the build, one dir per flavour (git-ignored)
├── bin/                   the executables land here (git-ignored)
└── local_reference/       your own namelists, logs and old runs (git-ignored)
```

---

## 2. Getting the code onto Roihu

```bash
# Login to Roihu
ssh -A -X <username>@roihu-cpu.csc.fi

# Clone the repository to your project folder
cd /projappl/project_XXXXXXX/$USER
git clone git@github.com:ManuelBettines/FLEXPART-INAR.git FLEXPART

# Move to the FLEXPART_v11 folder for all the following steps
cd FLEXPART/FLEXPART_v11
```

Code lives in `/projappl`; ECMWF input and model output in `/scratch`.

---

## 3. Compiling

FLEXPART is written in Fortran and has to be compiled before you can use it. You do
**not** need to load any module first — just run:

```bash
./compile_roihu.sh
```

It takes a few minutes and is small enough for the login node. At the end you should
get:

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

| Binary | When |
|---|---|
| `FLEXPART_ETA` (`eta`) | **the standard recommended choice** — trajectories in ECMWF's native hybrid (eta) coordinate, netCDF output |
| `FLEXPART` (`meter`) | metre coordinates; needed for GFS input, and the fallback if an eta run misbehaves |
| `FLEXPART_ETA_BIN` (`eta_bin`) | as `eta`, but FLEXPART's own binary output — only if you have a reader for it |
| `FLEXPART_BIN` (`meter_bin`) | as `meter`, binary output |

```bash
./compile_roihu.sh eta            # just the one you need
./compile_roihu.sh all -j 16      # all four
./compile_roihu.sh eta --clean    # rebuild from scratch
./compile_roihu.sh eta --debug    # -O0 -g -fbacktrace, lands in bin/FLEXPART_ETA_dbg
```

### Parameters you may still want to change

Almost everything that used to be a compile-time array bound is allocated at run time,
so `par_mod.f90` is much less interesting than in FLEXPART-WRF. Two exceptions:

| `par_mod.f90` | Value here | Meaning |
|---|---|---|
| `numpf` (line 190) | **3** | number of precipitation fields per time step in the GRIB input |
| `idiffnorm`, `idiffmax` (line 122) | 10800, 21600 | normal / maximum spacing of the wind fields, in seconds |

`numpf=3` is a **hard coupling to flex_extract**: the input must carry the
disaggregated sub-grid precipitation, which is what `RRINT 1` in the CONTROL file
produces. All INAR CONTROL files set `RRINT 1`, so leave `numpf=3` alone unless you
are reading somebody else's retrieval. Get the pair wrong and the run stops early (see
section 6).

`idiffnorm` also constrains the COMMAND file: `LSYNCTIME` must be **≤ 5400 s**
(`idiffnorm/2`), or readcommand stops.

### Warnings you can ignore during the build

`-Wall` is only on in the `--debug` build, so a normal build is quiet apart from a
handful of unused-variable notes from upstream code. What you should **not** ignore is
anything labelled `Error:` — the build stops there and the summary reports `FAILED`.
If you get an error during the compilation, please contact
manuel.bettineschi@helsinki.fi.

---

## 4. Preparing a run

Work in a per-case directory on `/scratch`, not in the repository:

```bash
mkdir -p /scratch/project_XXXXXXX/$USER/FLEXPART/mycase
cd       /scratch/project_XXXXXXX/$USER/FLEXPART/mycase

cp -r /projappl/project_XXXXXXX/$USER/FLEXPART/FLEXPART_v11/options .
cp    /projappl/project_XXXXXXX/$USER/FLEXPART/FLEXPART_v11/run/* .
mv    pathnames.template pathnames
```

The case directory then holds:

```
mycase/
├── pathnames            four lines: where everything else is
├── AVAILABLE            generated, see 4.2
├── options/             COMMAND, RELEASES, OUTGRID, SPECIES/, ... see 4.3
└── run_flexpart.slurm   the job script
```

### 4.1 The `pathnames` file, and its four lines

FLEXPART reads `pathnames` from the directory you launch it in. Four lines, in this
order:

```
options/                                              <- line 1: the options directory
/scratch/<PROJECT>/<user>/FLEXPART/output/<case>/     <- line 2: OUTPUT directory
/scratch/<PROJECT>/<user>/FLEXPART/ERA5/<case>/       <- line 3: the GRIB files
AVAILABLE                                             <- line 4: the AVAILABLE file
============================================
```

- The **first three are directories and must end in `/`** (FLEXPART pads a missing
  slash and tells you it did).
- **Each path is at most 120 characters** and is truncated at its **first blank**. A
  path with a space in it silently becomes a different path. CSC paths get long; check
  with `awk 'NR<=4 {print length($0), $0}' pathnames`.
- Line 2 is the only one FLEXPART does not create for you. `run_flexpart.slurm`
  creates it, and checks the other three exist, before launching anything.
- For nested meteorology, add **two** lines per nest after the `=====` separator (nest
  GRIB directory, then nest AVAILABLE), up to `maxnests = 5`. Every nest must have
  *exactly* the same time steps as the mother domain.

### 4.2 The AVAILABLE file

The `AVAILABLE` file maps every time step to the GRIB file that contains it.

You can generate it automatically by running:

```bash
# Use the same path as line 3 of pathnames
./generate_available.py /scratch/<PROJECT>/<user>/FLEXPART/ERA5/<case>/
```

That is all it needs. It reads the times off the flex_extract file names
(`<PREFIX><YYMMDDHH>`, e.g. `EA18010100`), sorts them, skips flex_extract's working
files (`flux*`, `fort.*`, `OG_OROLSM__SL.*`, `*_1`), writes `./AVAILABLE`, and reports
what it found:

```
scanning 744 file(s)
744 wind fields, 2018-01-01 00:00 -> 2018-01-31 23:00, every 1 h
reminder: LSYNCTIME in COMMAND must be <= 5400 s
-> /scratch/.../mycase/AVAILABLE
```

A gap larger than `idiffmax` (6 h) is reported as `ERROR-IN-WAITING`: FLEXPART's
response to a gap is to skip trajectories across it — a warning in the log, not a
crash, and easy to miss in a 36-hour job.

Do **not** write the file by hand. `readavailable` skips exactly three header lines and
reads fixed columns; the old `generateAVAILABLE.py` (now in `local_reference/`) wrote
two headers, so FLEXPART silently ate the first wind field of every run.

| Flag | Default | What it does |
|---|---|---|
| `-o FILE` | `AVAILABLE` | where to write it; `-` means stdout |
| `--start` / `--end` | the whole directory | drop steps outside the period (`YYYYMMDD` or `'YYYYMMDD HHMMSS'`) |
| `--every SECONDS` | every field present | use only every Nth field, e.g. `10800` for 3-hourly from hourly output. Must divide the native spacing, and stay ≤ 21600 |
| `--from-grib` | off | take the time from each file's GRIB header instead of its name — slower, but it verifies the retrieval |
| `--pattern GLOB` | `*` | narrow the scan, e.g. `'EA*'` |
| `--century YYYY` | 2000 | how to read the two-digit year in the names |
| `-v` | off | print the time found for every file |

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

`examples/` (Tracer, Aerosol, Nuclear) holds complete upstream option sets and is the
fastest way to see a working combination. `options.reference/` holds the **old,
non-namelist** formats — useful for reading an inherited v9/v10 setup, not for running
v11.

### 4.4 The releases and the output grid

`generate_releases.py` writes the whole `RELEASES` file and, with `--outgrid`, the
`OUTGRID` file too. One command does both:

```bash
# Example: SO2 released daily from a 10 km box around Sabancaya
./generate_releases.py --command options/COMMAND -o options/RELEASES \
    --control /projappl/.../FLEX_EXTRACT/Run/Control/CONTROL_EA5.VolcanoSA \
    --lat -15.79 --lon -71.86 --box 10 --z1 5967 --z2 6067 --zkind 2 \
    --specnum 23 --mass 8.6924e4 --npart 240000 --every 86400 \
    --outgrid options/OUTGRID --log-levels 20 --zfirst 50 --ztop 20000
```

That releases SO₂ daily between 5967 and 6067 m a.s.l. over the whole period in
`COMMAND`, and writes an output grid covering the whole retrieved domain with 20 levels
that are thin near the ground. The previous files are kept as `.bak`. Re-run it as
often as you like: it rewrites, it does not append.

Two checks it does that save a job:

- every release must lie inside the period in `COMMAND` — for **both** directions,
  because readcommand swaps the two dates internally for a backward run;
- with `--control`, the release box **and** the output grid must lie inside the area
  flex_extract actually retrieved (`LEFT`/`RIGHT`/`LOWER`/`UPPER`). This is the
  `#### PART OF OUTPUT GRID IS OUTSIDE MODEL DOMAIN ####` stop, which otherwise arrives
  a few minutes into the job.

The script has many flags; you do not need them all. What you need depends on your
case.

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

**Choosing the vertical levels** — one of these four, only with `--outgrid`:

| Flag | What it does |
|---|---|
| `--levels "250,500,2000"` | exactly these level tops, in metres |
| `--dz METRES --ztop METRES` | evenly spaced levels of this thickness |
| `--nlevels N --ztop METRES` | N evenly spaced levels |
| `--log-levels N --ztop METRES` | N levels, thin at the ground and thickening with height; `--zfirst METRES` sets the lowest layer's thickness (default `50`) |

`--log-levels 20 --zfirst 50 --ztop 20000` gives level tops of

```
50  113  193  294  421  581  784  1039  1362  1770  2285  2935  3756  4793
6101  7754  9840  12474  15800  20000
```

— six levels below 800 m, where 20 evenly spaced ones would have put the whole
boundary layer in a single 1 km slab. That is usually what you want for a footprint
run. Note that `NUMXGRID`/`NUMYGRID` count **cells**, not points, whatever the comment
in older copies of `OUTGRID` says.

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
| `IOUTPUTFOREACHRELEASE` | `1` = one output field per release. With ~1000 releases this makes a **lot** of output — check your `/scratch` quota first |
| `LOUTRESTART` | interval for restart files, `-1` to switch off. Set it on long jobs and restart with `IPIN=1` |
| `MAXTHREADGRID` | threads used for the grid computations; 1 (no grid parallelism) up to ~16. Higher costs memory |
| `NESTED_OUTPUT` | writes `OUTGRID_NEST` as well |
| `LAGESPECTRA` | age spectra; needs `AGECLASSES` |
| `IND_SOURCE` / `IND_RECEPTOR` | mass vs mixing ratio at source/receptor; `IND_RECEPTOR` 3/4 give backward wet/dry deposition |
| `LCMOUTPUT` | the Linear Chemistry Module; needs `REAGENTS` and the OH fields |
| `NXSHIFT` | shift of the global met data; **0 for a regional retrieval**, 359 for global ECMWF |

### 4.6 Checking your input files without burning a job

FLEXPART parses everything before it reads the first wind field, so a short interactive
run on the login node finds most mistakes in seconds:

```bash
source /projappl/.../FLEXPART_v11/roihu_env.sh
/projappl/.../FLEXPART_v11/bin/FLEXPART_ETA pathnames 2>&1 | head -60
```

Reaching `Reading windfields` (or the first `gridcheck` output) means `pathnames`,
`COMMAND`, `RELEASES`, `OUTGRID` and `SPECIES` all parsed. Stop it with Ctrl-C — do not
let a real run continue on a login node.

---

## 5. Submitting

If you set the files up correctly, you are ready to launch the simulation:

```bash
# Modify XXXXXXX with your actual project number
sbatch --account=project_XXXXXXX run_flexpart.slurm
```

Before the first submission, edit the `#SBATCH` header and the CONFIGURATION block at
the top of the script:

| Setting | Default | Notes |
|---|---|---|
| `FP_ROOT` | `/projappl/project_XXXXXXX/$USER/FLEXPART/FLEXPART_v11` | **edit this** — the case directory is on `/scratch` and the code on `/projappl`, so there is no relative default |
| `FP_BIN` | `$FP_ROOT/bin/FLEXPART_ETA` | which executable |
| `FP_PATHNAMES` | `pathnames` | which pathnames file |
| `--partition` | `small` | `test` for a quick check |
| `--cpus-per-task` | 32 | becomes `OMP_NUM_THREADS`; do not exceed the cores on a node (`sinfo -o "%P %c"`) |
| `--nodes` | 1 | leave it at 1 — there is no MPI (section 3) |
| `--mem` | 64G | v11 allocates by run size: particles, output grid and met domain. Large grids with `IOUTPUTFOREACHRELEASE=1` need much more |
| `--time` | 36:00:00 | for longer runs set `LOUTRESTART` and restart with `IPIN=1` |

The script sources `roihu_env.sh`, so the modules at run time are exactly the ones used
at build time. `--account` is deliberately not hard-coded; pass it on the command line,
or export `SBATCH_ACCOUNT=project_XXXXXXX` in your `~/.bashrc`.

Monitor with `squeue --me`, `seff <jobid>` (efficiency, after it finishes) and the
`flexpart_<jobid>.out` / `.err` files.

---

## 6. Troubleshooting

**`EC_FLIBS is empty — you must 'source roihu_env.sh' before running make`**
You ran `make` by hand in `src/`. Use `./compile_roihu.sh`.

**`f77: command not found`**
You ran an upstream makefile, which never sets `FC`. Use `./compile_roihu.sh`.

**`Can't open module file 'grib_api.mod'`**
ecCodes is not loaded. Check `module spider eccodes`, then
`FP11_ECCODES=eccodes/<version> ./compile_roihu.sh`.

**`#### FLEXPART MODEL ERROR! AVAILABLE FILE ... CANNOT BE OPENED`**
Line 4 of `pathnames` is wrong, or relative to a different directory than the one you
launched from. The path is truncated at its first blank.

**`NO WIND FIELDS AVAILABLE FOR SELECTED TIME PERIOD`**
The period in `COMMAND` and the rows in `AVAILABLE` do not overlap. Regenerate
AVAILABLE with `generate_available.py`; FLEXPART only uses fields within one day either
side of the simulation period.

**`FILE AVAILABLE IS CORRUPT. THE WIND FIELDS ARE NOT IN TEMPORAL ORDER`**
Two rows with the same or decreasing time — the file was edited by hand.

**`Release starts before simulation begins or ends after simulation stops`**
A release outside `[IBDATE IBTIME, IEDATE IETIME]`. Regenerate `RELEASES` with
`--command options/COMMAND`.

**`RELEASE either having unrecognised entries, or in old format`**
A v9/v10-style positional `RELEASES` file. v11 wants namelists.

**`#### PART OF OUTPUT GRID IS OUTSIDE MODEL DOMAIN`**
`OUTLON0 + NUMXGRID*DXOUT` (or the y equivalent) reaches past the edge of the
retrieval. `NUMXGRID` counts cells. Regenerate with
`generate_releases.py --outgrid --control <CONTROL file>`.

**`set numpf to 3 in par_mod.f90` / `Conditions for precipitation interpolation not fulfilled`**
`RRINT` in the flex_extract CONTROL file and `numpf` in `par_mod.f90` disagree — see
section 3.

**Illegal instruction (SIGILL) in a job that compiled fine**
A binary built with a wider instruction set than the compute node supports. Rebuild
without `--arch native`.

**The job runs but the output is all zeros**
Usually the release is outside the output grid, the release height is above the top
level, or `IOUT`/`LNETCDFOUT` selected a format you are not reading. Check the
`Particles released (numpartmax)` line in the log first.

Anything else: manuel.bettineschi@helsinki.fi
