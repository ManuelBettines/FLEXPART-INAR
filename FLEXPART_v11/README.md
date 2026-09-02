# FLEXPART v11 on Roihu

Compile-and-run guide for the "INAR working version" of **FLEXPART v11**, the standard Lagrangian particle dispersion model, driven by ECMWF meteorology.

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

The original version of each modified file is kept beside it as `*.f90_original`, so
the change is one `diff` away:

```bash
diff src/chemistry_mod.f90_original src/chemistry_mod.f90
```

If you do not plan to use the Linear Chemistry Module these modifications do not affect you (you can ignore this).


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
└── bin/                   the executables land here (git-ignored)
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
├── pathnames               four lines: where everything else is
├── generate_available.py   see section 4.2
├── generate_releases.py    see section 4.4
├── options/                COMMAND, RELEASES, OUTGRID, SPECIES/, ... see 4.3
└── run_flexpart.slurm      the job script
```

### 4.1 The `pathnames` file, and its four lines

FLEXPART reads `pathnames` from the directory you launch it in. Four lines, in this
order:

```
options/                                              <- line 1: the options directory
/scratch/<PROJECT>/<user>/FLEXPART/output/<case>/     <- line 2: OUTPUT directory
/scratch/<PROJECT>/<user>/FLEXPART/ERA5/<case>/       <- line 3: the ERA5 files (from flex_extract)
AVAILABLE                                             <- line 4: the AVAILABLE file
============================================
```

### 4.2 The AVAILABLE file

The `AVAILABLE` file maps every time step to the ERA5 file that contains it.

You can generate it automatically by running:

```bash
# Use the same path as line 3 of pathnames
./generate_available.py /scratch/<PROJECT>/<user>/FLEXPART/ERA5/<case>/
```

### 4.3 The options directory

| File | What it is | Do you need to edit it? |
|---|---|---|
| `COMMAND` | direction, period, output intervals, all the switches | **yes**, every run |
| `RELEASES` | what is released, where and when | **yes** — with `generate_releases.py` (4.4) |
| `OUTGRID` | the output grid | **yes** — `generate_releases.py --outgrid` |
| `OUTGRID_NEST` | nested output grid, only if `NESTED_OUTPUT=1` | only if you want two domains (or more) |
| `AGECLASSES` | age spectra, only if `LAGESPECTRA=1` | only if you want the trajecotry of a given lenght (in hours) |
| `PARTOPTIONS` | which particle fields are written when `IPOUT>0` | usually no |
| `RECEPTORS` | receptor points, only if `IND_RECEPTOR>0` | usually no |
| `SPECIES/` | the species database (`SPECIES_NNN`, plus named ones) | usually no, pick from it |
| `REAGENTS`, `oh_fields/` | chemical reagents for `LCMOUTPUT=1` | only if you use the Linear Chemistry Module (see below) |
| `IGBP_int1.dat`, `sfcdata.t`, `sfcdepo.t` | land use and surface tables | never |
| `INITCONC`, `SATELLITES` | initial conditions / satellite sampling | usually no |

`REAGENTS` contains an **absolute** path to `options/oh_fields/`; fix it to your own
checkout before switching the Linear Chemistry Module on. Everything else works from
the copied directory as it stands.

`examples/` (Tracer, Aerosol, Nuclear) holds complete upstream option sets and is the
fastest way to see a working combination.

### 4.4 The releases and the output grid

`generate_releases.py` writes the whole `RELEASES` file and, with `--outgrid`, the
`OUTGRID` file too. One command does both:

```bash
# Example: SO2 released hourly from a 10 km box around Sabancaya
./generate_releases.py --command options/COMMAND -o options/RELEASES \
    --control /projappl/.../FLEX_EXTRACT/Run/Control/CONTROL_EA5.VolcanoSA \
    --lat -15.79 --lon -71.86 --box 10 --z1 5967 --z2 6067 --zkind 2 \
    --specnum 23 --mass 8.6924e4 --npart 10000 --every 3600 \
    --outgrid options/OUTGRID --log-levels 20 --zfirst 50 --ztop 20000
```

That releases SO₂ hourly between 5967 and 6067 m a.s.l. over the whole period in
`COMMAND`, and writes an output grid covering the whole retrieved domain with 20 levels
that are thin near the ground. The previous files are kept as `.bak`. Re-run it as
often as you like: it rewrites, it does not append.

The script has many flags; you do not need them all. What you need depends on your
case.

**Where it writes**

| Flag | Required | Default | What it does |
|---|---|---|---|
| `-o FILE` | no | `./RELEASES` | the RELEASES file to write; `-` means stdout |
| `--command FILE` | yes | — | the COMMAND file used: gives the period and direction, and every release is checked against them |
| `--control FILE` | no, but it is reccomened | — | a flex_extract CONTROL file (same one used for the ERA5 retrival), for the domain check |

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
| `--z1` / `--z2` | `0` / `100` | bottom and top of the release |
| `--zkind {1,2,3}` | `1` | `1` m above ground, `2` m above sea level, `3` pressure in hPa |

**What to release**

| Flag | Default | What it does |
|---|---|---|
| `--specnum N` | `24` (AIRTRACER) | the `NNN` of `options/SPECIES/SPECIES_NNN` |
| `--mass KG` | `1.0` | mass per release |
| `--npart N` | `10000` | particles per release |

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

---

## 5. Submitting

If you set the files up correctly, you are almost ready to launch the simulation.
Before launching the simulation you need to modify the `run_flexpart.slurm` file, you have to chnage the following line:

```bash
# Change this with the actual path where you compiled the code
P_ROOT="${FP_ROOT:-/projappl/project_XXXXXX/$USER/FLEXPART/FLEXPART_v11}"
```

Now you are ready to submit the simulation:

```bash
# Modify XXXXXXX with your actual project number
sbatch --account=project_XXXXXXX run_flexpart.slurm
```

The script sources `roihu_env.sh`, so the modules at run time are exactly the ones used
at build time. `--account` is deliberately not hard-coded; pass it on the command line,
or export `SBATCH_ACCOUNT=project_XXXXXXX` in your `~/.bashrc`.

Monitor with `squeue --me`, `seff <jobid>` (efficiency, after it finishes) and the
`flexpart_<jobid>.out` / `.err` files.

At the end of the simulation you should get the following message (in the `flexpart_<jobid>.out` file):
```
 CONGRATULATIONS: YOU HAVE SUCCESSFULLY COMPLETED A FLEXPART MODEL RUN!
==============================================================================
 end: Wed Sep  2 07:30:28 AM EEST 2026   exit code: 0
 output in: /scratch/project_XXXXXX/<user>/FLEXPART/mycase/
==============================================================================
```

---

## 6. Troubleshooting

To be written, in the meantime, contact manuel.bettineschi@helsinki.fi
