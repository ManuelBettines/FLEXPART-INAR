# FLEXPART-WRF v3.3.2 on Roihu (CSC)

Compile-and-run guide for the INAR working version of **FLEXPART-WRF 3.3.2**, the
offline Lagrangian dispersion model driven by WRF output.

---

## 1. What this code is

This is **not** the official release from flexpart.eu. It is the "INAR working copy" of
FLEXPART-WRF 3.3.2, modified originally by **Diego Aliaga**, and further modfied by **Manuel Bettineschi**. See
[`src/README.md`](src/README.md) for the modification notes and
[`src/README.txt`](src/README.txt) for Brioude's upstream release notes.

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
# Login to Roihu
ssh -A -X <username>@roihu-cpu.csc.fi 

# Clone the repository to your project folder
cd /projappl/project_XXXXXXX/$USER
git clone git@github.com:ManuelBettines/FLEXPART-INAR.git FLEXPART

# Move to the WRF-FLEXPART folder for all the following steps
cd FLEXPART/WRF-FLEXPART
```

---

## 3. Compiling

WRF-FLEXPART is written in Fortran, which means it needs to be compiled before you can use it. On Roihu you can compile the code simply by running the following command:

```bash
./compile_roihu.sh           
```

It takes roughly a minute and at the end of the compilation you should get the following message:
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
| `flexwrf33_gnu_omp` | **the "standard" reccomended choice** — one node, many threads. |
| `flexwrf33_gnu_mpi` | hybrid MPI+OpenMP across several nodes. **Do NOT use** (currently it has a bug which make the particle count "explode"). |
| `flexwrf33_gnu_serial` | debugging and quick tests.  |

### Warnings you can ignore during the build

A clean build emits about a dozen warnings per flavour. They all come from upstream
legacy Fortran and are covered by the `-std=legacy` / `-fallow-invalid-boz` /
`-fallow-argument-mismatch` flags:

What you should **not** ignore is anything labelled `Error:` — the build stops there
and the summary reports `FAILED`. If you get an error during the compilation, please contact manuel.bettineschi@helsinki.fi.

---

## 4. Preparing a run

Before launching a simulation you need to set up two main files: the `flexwrf.input` file, and the `AVAILABLE` file. 

### 4.1 The input file, and its three path lines

In the run folde you will find the `flexwrf.input.template` file.
```bash
# Create a new input file based on the template file. The flexwrf.input is the file you will actually modify. 
cp flexwrf.input.template flexwrf.input
```

The first thing you should modify in the `flexwrf.input` are the path to: 1) the folder where you want the FLEXPART output: 2) the folder where you have your WRF simulation output; 3) the path to the `AVAILABLE` file (see section 4.2 for how to generate it).

```
=====================FORMER PATHNAMES FILE===================
/scratch/<PROJECT>/<user>/FLEXPART/output/<case>/     <- line 2: OUTPUT directory
/scratch/<PROJECT>/<user>/WRF/wrfout_d01/             <- line 3: directory holding the wrfout files
/projappl/<PROJECT>/<user>/.../run/AVAILABLE1         <- line 4: the AVAILABLE file for that domain
=============================================================
```

### 4.2 The AVAILABLE file

The `AVAILABLE` file maps every time step to the wrfout file that contains it.

You can automatically generate the `AVAILABLE` file by running the following command:
```bash
# You should use the same path as in the line 3 of the flexwrf.input file
./generate_available.py /scratch/<PROJECT>/<user>/WRF/wrfout_d01/
```
It only needs the path to the WRF output and the script will generate automatically the file needed by WRF-FLEXPART.

### 4.3 The releases and the output grid

`generate_releases.py` fills in the two long sections of `flexwrf.input`: the RELEASES
blocks (a 12-line block per release — hundreds of them for a backward run) and, with
`--outgrid`, the OUTGRID section. One command does both:

```bash
# Example on how to modify the flexwrf.input to include releases and outgrid definition
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

The `generate_releases.py` script has many different flags, you do not necesserally need them all. What you need depends on yours needs. Here you can find an explanation of all the different flags.

**The flags**

| Flag | Required | Default | What it does |
|---|---|---|---|
| `--input FILE` | yes | — | the `flexwrf.input` to fill in |
| `--wrf PATH` | yes | — | a wrfout file, or the directory holding them (the **lowest domain** is used — grid metres are measured on the mother domain) |
| `--start "YYYYMMDD HHMMSS"` | no | same as the simulation start time in flxwrf.input | first release time |
| `--end "YYYYMMDD HHMMSS"` | no | same as the simulation end time in flxwrf.input | last release time |
| `--lat` / `--lon` | yes | — | centre of the release box, in degrees |
| `--box METRES` | no | `1000` | side of the box around `--lat/--lon` |
| `--z1` / `--z2` | no | `0` / `10` | bottom and top of the release, in metres above ground |
| `--npart N` | no | `10000` | particles per release |
| `--outgrid` | no | off | rebuild the OUTGRID section to cover the whole WRF domain |
| `--outgrid-res METRES` | no | the WRF `DX` | spatial resolution of the FLEXPART output cells (it can be set different from the WRF resolution) |

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

### 4.4 Two WRF domains: `generate_releases_nested.py`

WRF-FLEXPART allows you to perform simulation using two nested domains. If your WRF run has a nest (`d01` + `d02`) and you want FLEXPART to use both, use
`generate_releases_nested.py`. It takes **exactly the same flags plus `--wrf-nest`**:

```bash
./generate_releases_nested.py --input flexwrf.input \
    --wrf /scratch/.../wrfout_d01/ --wrf-nest /scratch/.../wrfout_d02/ \
    --start "20140201 000000" --end "20140301 000000" \
    --lat 45.3775 --lon 11.94 --box 15000 --z1 0 --z2 10 --npart 10000 \
    --outgrid --log-levels 20 --zfirst 10 --ztop 10000
```

On top of what the single-domain script does, it:

- **writes the PATHNAMES block for you** — both wrfout directories and both AVAILABLE
  files, in the order FLEXPART expects.
- sets `NESTED_OUTPUT = 1` and writes the `OUTGRID_NEST` section covering the `d02`
  domain.
- checks the release box against **`d02`**, not `d01`, and reports how far it sits
  from the nest edge.

| Extra flag | Required | Default | What it does |
|---|---|---|---|
| `--wrf-nest PATH` | yes | — | the `d02` wrfout file or its directory (the **highest** domain is used) |
| `--margin CELLS` | no | `0` | inset the nested output grid this many `d02` cells from the nest boundary |
| `--outgrid-nest-res METRES` | no | the `d02` `DX` | spatial resolution of the nested FLEXPART output cells |
| `--no-nested-output` | no | off | drive with `d02` winds but keep a single output grid |
| `--available` / `--available-nest` | no | the one in the input file / `AVAILABLE2` beside it | where the AVAILABLE files are |

You should generate the AVAILABLE file also for the nested domain **first** (name them AVAILABLE1 and AVAILABLE2 for the parent and nested domains, respectively).

### 4.5 Switches worth understanding
The `flxwrf.input` file include many other flags that you can modify. Here's a brief description of the main flags. 

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

This looks fatal but **is not**, the `stop` is deliberately commented out in
`src/readinput.f90:584`, because reading PBLH from WRF is exactly what Diego's
modification re-enabled. The run continues normally. 

---

## 5. Submitting
If you setted up the files correctly, you are now ready to lauch the simulation. You can do it with the following command:
```bash
# Modify XXXXXXX with you actual project number
sbatch --account=project_XXXXXXX run_flexwrf_omp.slurm      # single node, OpenMP
```

Monitor with `squeue --me`, and the `flexwrf_<jobid>.out` / `.err` files.

---

## 6. Troubleshooting
To be written... In the meantime you can contact: manuel.bettineschi@helsinki.fi
