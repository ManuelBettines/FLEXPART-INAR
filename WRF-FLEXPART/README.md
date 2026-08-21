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
FLEXPART-WRF 3.3.2, modified by **Diego Aliaga**, and used
for the SALTENA campaign in Bolivia and for the Izaña campaign (among others). See
[`src/README.md`](src/README.md) for the modification notes and
[`src/README.txt`](src/README.txt) for Brioude's upstream release notes.

Practical consequences:

- Behaviour slightly differs from the official release in places (surface-layer handling,
  reading PBLH from WRF, comparison operators). Do not assume upstream documentation
  describes this binary exactly.
- Do not replace `src/` with a fresh upstream download expecting the same results.
- Upstream, for reference: <https://www.flexpart.eu/wiki/FpLimitedareaWrf>

Cite Brioude et al. (2013), Geosci. Model Dev. 6, 1889–1904.

### Repository layout

```
WRF-FLEXPART/
├── compile_roihu.sh       one-command build (this is what you run)
├── compile_roihu.slurm    optional: the same build as a batch job
├── roihu_env.sh           the module stack; sourced by build AND run scripts
├── makefile.roihu         Roihu-adapted makefile (see section 6)
├── src/                   the Fortran sources
├── examples/              Brioude's upstream example input files (see section 5.5)
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
 serial   OK       /projappl/project_2018181/bettines/FLEXPART/WRF-FLEXPART/bin/flexwrf33_gnu_serial (1.1M)
 omp      OK       /projappl/project_2018181/bettines/FLEXPART/WRF-FLEXPART/bin/flexwrf33_gnu_omp (1.1M)
 mpi      OK       /projappl/project_2018181/bettines/FLEXPART/WRF-FLEXPART/bin/flexwrf33_gnu_mpi (512)

 All requested flavours built. Binaries are in /projappl/project_2018181/$USER/FLEXPART/WRF-FLEXPART/bin/
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

## 5. Preparing a run

Work in a per-case directory on `/scratch`, not in the repository:

```bash
mkdir -p /scratch/project_XXXXXXX/$USER/FLEXPART/izana_backward
cd       /scratch/project_XXXXXXX/$USER/FLEXPART/izana_backward
cp /projappl/project_XXXXXXX/$USER/FLEXPART/WRF-FLEXPART/run/* .
```

### 5.1 The input file, and its three path lines

FLEXPART-WRF reads **one** file (historically split into PATHNAMES, COMMAND,
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
  awk 'NR>=2 && NR<=4 {print length($0), $0}' flexwrf.input
  ```

  If you are over, shorten the case directory name or run from a shorter parent.
- FLEXPART does **not** create the output directory. The supplied Slurm scripts do it
  for you (they read line 2); if you launch by hand, `mkdir -p` it yourself.
- With more than one domain, lines 3 and 4 repeat per domain — see
  [`examples/flexwrf.input.backward2`](examples/) for the two-domain layout.

### 5.2 The AVAILABLE file

`AVAILABLE` maps every time step to the wrfout file that contains it: three header
lines, then one row per step.

The catch: WRF normally writes **several time frames per file**, so all the rows
belonging to one file must name that **same** file — the one stamped at the file's
start time, not at the time step. Generate it rather than writing it by hand:

```bash
# one wrfout file per day holding 24 hourly frames (the Izana setup)
./generate_available.py --start 20220321 --end "20220627 000000" > AVAILABLE1

# domain 2, 30-minute frames, 6 frames (3 h) per file
./generate_available.py --start 20220321 --end "20220627 000000" \
    --domain 2 --interval 1800 --hours-per-file 3 > AVAILABLE2

./generate_available.py --help
```

Sanity-check it against reality — a missing file is only discovered mid-run:

```bash
awk 'NR>3 {gsub(/'"'"'/,"",$3); print $3}' AVAILABLE1 | sort -u | \
  while read f; do [ -f "/scratch/.../wrfout/$f" ] || echo "MISSING: $f"; done
```

### 5.3 The RELEASES blocks

A backward run usually releases from the same box every hour, which means hundreds to
thousands of near-identical 12-line blocks. Generate them:

```bash
./generate_releases.py --start "20220508 040000" --end "20220627 000000" \
    --x1 177000 --y1 98000 --x2 178000 --y2 99000 \
    --z1 0 --z2 10 --npart 10000 > releases.txt
# -> "1196 release blocks -> set NUMPOINT to 1196"   (on stderr)
```

Then append `releases.txt` after the release header of your input file and put that
count on the `NUMPOINT` line:

```bash
head -n 86 flexwrf.input.template > flexwrf.input   # everything up to NUMPOINT
cat releases.txt >> flexwrf.input
sed -i 's/^ 1                  NUMPOINT/ 1196               NUMPOINT/' flexwrf.input
```

Coordinate units follow `RELEASE_COORD` in the input file: `0` = WRF grid metres
(what the numbers above are), `1` = degrees lat/lon.

### 5.4 Switches worth understanding

| Switch | Notes |
|---|---|
| `LDIRECT` | `1` forward, `-1` backward (source–receptor / footprint runs) |
| `IOUT` | `1` concentration, `2` mixing ratio, `3` both, `4` plume trajectory, `5` = 1+4 |
| `IOUTTYPE` | `0` binary, `1` ASCII, `2` **netCDF** — use 2; the build has netCDF-4 output enabled |
| `NCTIMEREC` | time frames per netCDF file (only with `IOUTTYPE=2`) |
| `IOUTPUTFOREACHREL` | `1` = one output field per release. With ~1000 releases this makes a **lot** of output — check your `/scratch` quota first |
| `NESTED_OUTPUT` | nested output grid; needs `maxnests` to be large enough |
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

### 5.5 A note on `examples/`

The files in `examples/` are Brioude's upstream test cases. They are useful as a
**format reference**, but they will not run against this binary unchanged: they use
`NAGECLASS = 2` and multiple species, while the committed `par_mod.f90` has
`maxageclass = 1` and `maxspec = 1`. Either raise those limits and rebuild
(section 2), or just read the files for their layout.

### 5.6 Checking an input file without burning a job

The serial binary parses the whole input and reports the first problem in seconds:

```bash
../bin/flexwrf33_gnu_serial flexwrf.input 2>&1 | head -40
```

Reaching `Opening file: .../AVAILABLE1 for reading` means every section parsed. Anything
earlier is a formatting or limits problem.

---

## 6. Submitting

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

## 7. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `cannot execute binary file: Exec format error` | Built on the aarch64 (GPU) side, submitted to a CPU partition, or vice versa. Rebuild on `roihu-cpu.csc.fi`. |
| `roihu_env.sh` aborts with "this is a aarch64 node" | Same thing, caught early. Log in to the CPU login node. |
| `module load` fails / no `mpif90` | Wrong `gcc` for the architecture: x86_64 needs `gcc/15.2.0`, aarch64 `gcc/14.3.0`. Check with `module spider netcdf-fortran`. |
| `NC_FLIBS is empty — you must 'source roihu_env.sh'` | You ran `make` directly. Use `compile_roihu.sh`. |
| `error while loading shared libraries: libnetcdff.so` | The job did not load the build modules. Use the supplied Slurm scripts, or `source roihu_env.sh` first. |
| `No rule to make target 'xxx.o'` | Something in `OBJECTS` has no source file. See section 8. |
| `#### FLEXPART MODEL ERROR! ... CANNOT BE OPENED` | A path in lines 2–4 of the input file is wrong, or a directory is missing its trailing slash, or the output directory does not exist. |
| Same error, but the file name printed is **blank** | The path is longer than the 120-character limit and was truncated. Section 5.1. |
| `NUMBER OF AGE CLASSES GREATER THAN MAXIMUM ALLOWED` | `NAGECLASS > maxageclass` — section 2. |
| `SFC_OPTION = 1 ... no longer supported` | **Not fatal.** Stale message; see section 5.4. |
| Job runs but the output directory stays empty | The run has not reached the first output interval yet, or line 2 points somewhere unexpected. Check the `.out` log. |
| Output full of `NaN` | Very likely uninitialised variables under gcc 15 `-O3` — this bit CHIMERE on the same machine. `-finit-local-zero` is already in the flags for that reason; if NaN still appears, rebuild with the debug flags commented in `makefile.roihu` (`-O0 -g -fbacktrace -ffpe-trap=invalid -finit-real=snan`) and read the backtrace. |
| Build races with `-j` | `./compile_roihu.sh omp -j 1`. The dependency fixes in `makefile.roihu` should make this unnecessary — please report it if it happens. |

---

## 8. What was changed for Roihu

`makefile.roihu` is a copy of the upstream `src/makefile.mom` with every deviation
marked `# ROIHU:`. `src/` itself is untouched, so the model physics is exactly what
INAR has been running.

| Change | Why |
|---|---|
| netCDF flags come from `nf-config` via `roihu_env.sh` instead of one `$NETCDF` prefix | Roihu installs netcdf-c and netcdf-fortran under **separate** Spack prefixes, and uses `lib` vs `lib64` inconsistently, so `-I$NETCDF/include -L$NETCDF/lib -lnetcdff` cannot work |
| dropped `${OPENMPI_INSTALL_ROOT}` from the mpi target | a Puhti-only variable, unset on Roihu (it silently expanded to `-I/include`); the `mpif90` wrapper already provides the MPI paths |
| added `-fallow-argument-mismatch` | gfortran ≥ 10 rejects the old-style `mpif.h` calls in `send*_mpi.f90` |
| `rm -f` in `clean` | the old `rm` failed, and aborted the build, on a clean tree |
| fixed `$(MPI_ONLY_OBJECTS)` → `$(MPI_ONLY_OBJS)` (and the serial/omp equivalents), plus explicit inter-module dependencies | those variables never existed, so `make -j` raced on `par_mod.mod` and had to be run twice. It now completes in one pass. |
| moved `gf2xe.o` and `ranlux.o` into `MODOBJS` | they define modules (`gf2xe`, `luxury`) that other files `use` |
| removed `cmapf1.0.o`, `distance.o`, `distance2.o`, `outgrid_init_nest.o` from `OBJECTS` | **these source files do not exist in this tree.** `cmapf1.0` was folded into `cmapf_mod.f90`; the other three are unreferenced (`outgrid_init_nest` only appears in a commented-out call at `flexwrf_mpi.f90:247`; the live code uses `outgrid_init_nest_reg`/`_irreg`). Keeping them made a clean checkout fail with `No rule to make target` — the old build only worked because stale `.o` files were lying around. |
| each flavour builds in its own `build/<flavour>/` | the link step is `$(FC) *.o`, so serial/omp/mpi objects sharing a directory silently produce a mixed binary |

Compiler flags kept from upstream: `-O3 -m64 -mcmodel=medium -fconvert=little-endian
-finit-local-zero -fno-range-check -std=legacy -fallow-invalid-boz
-ffree-line-length-none`. `-finit-local-zero` is load-bearing on gcc 15 — see the NaN
row in section 7. `-fconvert=little-endian` must match whatever reads the binary
`partposit*` particle dumps.

### Building somewhere other than Roihu

For testing the build logic on a machine with a system gfortran and netCDF-Fortran
(no modules, no Slurm):

```bash
FLEXWRF_SKIP_MODULES=1 ./compile_roihu.sh all
```

This skips `module purge/load` and the architecture check, and takes the netCDF flags
from whatever `nf-config` is on `PATH`. It proves the build works; it does **not**
prove anything about Roihu's gcc 15 toolchain.
