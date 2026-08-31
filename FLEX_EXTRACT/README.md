# flex_extract 7.1.3 on Roihu (CSC)

Setup-and-run guide for **flex_extract**, which retrieves meteorological fields from
ECMWF and converts them into the GRIB files **FLEXPART v11** reads. It is a
pre-processing step, not a model: run it first, then point FLEXPART at its output
([`../FLEXPART_v11/`](../FLEXPART_v11/)).

---

## 1. What this is

flex_extract does two things:

1. **Retrieves** the fields FLEXPART needs — winds, temperature, humidity, surface
   fields, fluxes — from the Copernicus Climate Data Store (ERA5) or from ECMWF's MARS
   archive (operational data, member-state accounts only).
2. **Converts** them: it computes the vertical velocity in ECMWF's native hybrid
   coordinate with the Fortran program `calc_etadot`, disaggregates the accumulated
   precipitation, and concatenates everything into one GRIB file per time step, named
   `<PREFIX><YYMMDDHH>` (e.g. `EA18010100`).

That second step is why this is not simply a download script, and why it has to be
compiled.

Authors: Anne Tipka (formerly Philipp), Leopold Haimberger and Petra Seibert. Upstream
documentation: `Documentation/html/index.html`, or
<https://www.flexpart.eu/flex_extract/>.

### Repository layout

```
FLEX_EXTRACT/
├── setup_roihu.sh         one-command install (this is what you run)
├── roihu_env.sh           modules + virtualenv; sourced by setup AND run scripts
├── Run/
│   ├── Control/           the CONTROL files: one per retrieval configuration
│   ├── run_local.sh       upstream launcher; INPUTDIR/OUTPUTDIR live here
│   ├── run_flex_extract.slurm   submit one retrieval
│   ├── submit_chain.sh    split a long period into chained jobs
│   └── run_bologna.sh, run_reading.sh   upstream, for running INSIDE ECMWF
├── Source/
│   ├── Python/            the retrieval and conversion driver
│   └── Fortran/           calc_etadot, and makefile_roihu
├── Templates/             job and namelist templates
├── Documentation/         upstream HTML documentation
└── local_reference/       your own CONTROL copies, logs and old runs (git-ignored)
```

The upstream `setup_local_*.sh` / `setup_*.sh` scripts are kept for reference but **do
not work here**: they select makefiles with hard-coded Puhti/Mahti library paths,
including a hand-built emoslib that does not exist on Roihu. Use `setup_roihu.sh`.

---

## 2. Before you start: access, keys and a virtualenv

This is the part that takes days, not minutes. Do it before you need the data.

### 2.1 ERA5 through the CDS

1. Register at <https://cds.climate.copernicus.eu/> and log in.
2. Accept the licence for **ERA5 complete** and **ERA5 single levels** in the web
   interface. Each dataset has to be accepted once; a retrieval against an unaccepted
   licence fails with an HTTP 403 that says nothing useful.
3. Put your API key in `~/.cdsapirc`, then `chmod 600 ~/.cdsapirc`:

   ```
   url: https://cds.climate.copernicus.eu/api
   key: <your-key>
   ```

Retrievals are **queued at ECMWF**. A fortnight of hourly ERA5 on 137 levels can sit in
the queue for hours before a byte arrives. Plan for it — that, not compute, is what
`submit_chain.sh` (section 5) works around.

### 2.2 MARS / operational data

Needs an ECMWF account attached to a member-state institution, plus `~/.ecmwfapirc`.
For the `ecs`/`hpc` install targets — flex_extract running *inside* ECMWF and shipping
the result back through an ecaccess gateway — see the upstream documentation and
`Run/run_bologna.sh`. Everything below assumes the local (CDS) mode.

### 2.3 The python environment

flex_extract needs `cdsapi`, `ecmwf-api-client`, `genshi`, `numpy` and the **ecCodes
python bindings**. Build the virtualenv once:

```bash
source /projappl/project_XXXXXXX/$USER/FLEXPART/FLEX_EXTRACT/roihu_env.sh   # modules
python3 -m venv $HOME/flex_extract_venv
source $HOME/flex_extract_venv/bin/activate
pip install --upgrade pip
pip install cdsapi ecmwf-api-client genshi numpy eccodes
```

From then on `roihu_env.sh` activates `$HOME/flex_extract_venv` automatically; point it
elsewhere with `FE_VENV=/path/to/venv`. It also prints, in every install and job log,
whether each of the five modules imports — so a missing dependency shows up before a
request is queued, not after.

---

## 3. Installing

```bash
# Login to Roihu
ssh -A -X <username>@roihu-cpu.csc.fi

# Clone the repository to your project folder
cd /projappl/project_XXXXXXX/$USER
git clone git@github.com:ManuelBettines/FLEXPART-INAR.git FLEXPART

# Move to the FLEX_EXTRACT folder and install
cd FLEXPART/FLEX_EXTRACT
./setup_roihu.sh
```

The script sources [`roihu_env.sh`](roihu_env.sh), checks the python side and the API
keys, and compiles `calc_etadot`. At the end you should get:

```
==============================================================================
 INSTALL SUMMARY
==============================================================================
 calc_etadot : OK   .../Source/Fortran/calc_etadot -> .../calc_etadot_fast.out

 Next: edit Run/Control/<your CONTROL file>, then
         cd Run && sbatch --account=project_XXXXXXX run_flex_extract.slurm
==============================================================================
```

```bash
./setup_roihu.sh --check    # report the environment, install nothing
./setup_roihu.sh --clean    # remove the previous build first
```

**About the makefile.** [`Source/Fortran/makefile_roihu`](Source/Fortran/makefile_roihu)
is derived from upstream's `makefile_fast`; every deviation is marked `# ROIHU:`. It
needs no emoslib (the FFT routines that ship in `Source/Fortran/` are used instead), and
the ecCodes paths come from `roihu_env.sh` and are baked into the binary with
`-Wl,-rpath`, because `submit.py` launches `calc_etadot` as a plain subprocess.
`-fdefault-real-8` and `-fconvert=big-endian` are not negotiable: the intermediate
`fort.*` files are big-endian doubles and the python side assumes exactly that.

---

## 4. Preparing a retrieval: the CONTROL file

Everything about a retrieval is in one CONTROL file under `Run/Control/`. Start from
`CONTROL_EA5` (ERA5, regional) or copy one of the campaign files; the full parameter
list with defaults is in `Run/Control/CONTROL.documentation`.

```
START_DATE 20180101
END_DATE   20180131
DTIME 1                       # output every 1 h
TYPE AN AN AN ...             # analysis at every time
TIME 00 01 02 ... 23
STEP 00 00 00 ... 00
ACCTYPE FC                    # fluxes come from the forecast
ACCTIME 06/18
ACCMAXSTEP 12
CLASS EA                      # EA = ERA5
STREAM OPER
GRID 0.25                     # output resolution, degrees
LEFT -136.                    # the domain, degrees
LOWER -57.
UPPER 13.
RIGHT 0.
LEVELIST 1/to/137             # all model levels
RESOL 159                     # spectral truncation for the etadot computation
ETA 1                         # take etadot from MARS rather than computing it
CWC 1                         # cloud water content, for wet deposition
PREFIX EA                     # output files are named EA<YYMMDDHH>
RRINT 1                       # NEW precipitation disaggregation -- see below
ECTRANS 1
```

### The parameters that matter most

| Parameter | Notes |
|---|---|
| `START_DATE` / `END_DATE` | inclusive. Without `END_DATE` you get one day |
| `DTIME` | spacing of the output fields, in hours. FLEXPART wants ≤ 3 h (`idiffmax`); 1 h is what INAR uses |
| `LEFT` / `RIGHT` / `LOWER` / `UPPER` | the domain. **Everything FLEXPART does must fit inside it** — release boxes and the whole output grid |
| `GRID` | horizontal resolution in degrees. 0.25 is ERA5's native grid; coarser costs less to retrieve and to run |
| `LEVELIST` | `1/to/137` is the full ERA5 column. Truncating it saves a lot of data but caps the model top |
| `RESOL` | spectral truncation used when computing etadot. Higher is more accurate and much slower |
| `PREFIX` | the two letters at the front of every output file name |
| `RRINT` | **1** for the new precipitation disaggregation — see below |
| `CWC` | cloud water, needed for in-cloud scavenging |
| `PUBLIC` / `REQUEST` | set in `run_local.sh`, not here: `PUBLIC=1` uses the public CDS datasets; `REQUEST=2` submits the request *and* writes `mars_requests.csv`, the record of what was actually asked for |

### `RRINT 1` and `numpf` — the coupling that bites

`RRINT 1` selects the *new* precipitation disaggregation, which writes **three**
precipitation fields per time step instead of one. FLEXPART v11 has to be compiled to
expect the same number: `numpf` in `../FLEXPART_v11/src/par_mod.f90` is **3** in this
repository.

Get the pair wrong and the FLEXPART run — not this one — stops early:

| CONTROL | `numpf` | What FLEXPART says |
|---|---|---|
| `RRINT 1` | 3 | (correct) |
| `RRINT 1` | 1 | `*** ERROR: additional precip fields available *** You must use them, set numpf=3 and recompile` |
| `RRINT 0` | 3 | `Conditions for precipitation interpolation not fulfilled!` |

All the INAR CONTROL files set `RRINT 1`. Keep it that way unless you also change
`par_mod.f90` and rebuild FLEXPART.

### Where the output goes

`INPUTDIR` and `OUTPUTDIR` are set in [`Run/run_local.sh`](Run/run_local.sh), not in the
CONTROL file. Put both on `/scratch`:

```bash
INPUTDIR='/scratch/project_XXXXXXX/<user>/FLEXPART/ERA5/<case>'
OUTPUTDIR='/scratch/project_XXXXXXX/<user>/FLEXPART/ERA5/<case>'
```

`INPUTDIR` is the working directory and `OUTPUTDIR` is where the finished `EA*` files
land. Pointing both at the same directory works and is what INAR has always done, but
then the working files (`flux*`, `fort.*`, `OG_OROLSM__SL.*`, the `*_1`/`*_2`
precipitation sub-steps) sit right next to the output. That matters when you build the
AVAILABLE file: `flux18010100` looks exactly like a valid field name.
`FLEXPART_v11/run/generate_available.py` skips them by name — but if you write AVAILABLE
by hand, do not list them.

Sizes are not small: hourly ERA5 on 137 levels over a South-American domain is roughly
0.5 GB per day of output, and the intermediate files are larger still. Check your quota
(`csc-projects`, `lfs quota`) before starting a year.

---

## 5. Submitting

### One period

```bash
cd Run
# Modify XXXXXXX with your actual project number
sbatch --account=project_XXXXXXX run_flex_extract.slurm CONTROL_EA5.MyCase
```

The argument is the **basename** of a file in `Run/Control/`. Without an argument, the
`CONTROLFILE` set in `run_local.sh` is used. The script sources `../roihu_env.sh` (so
the ecCodes the python bindings load is the one `calc_etadot` was linked against),
creates `INPUTDIR` and `OUTPUTDIR`, and then runs the unmodified upstream
`run_local.sh`.

One task on one node is right: flex_extract spends most of its wall time waiting for
ECMWF, and `calc_etadot` is called once per time step. There is nothing to parallelise
across nodes.

### A long period, as a chain

```bash
cd Run
export SBATCH_ACCOUNT=project_XXXXXXX
bash submit_chain.sh Control/CONTROL_EA5.VolcanoSA 15
```

That reads `START_DATE`/`END_DATE` from the base CONTROL file, splits the period into
15-day chunks, writes one CONTROL copy per chunk
(`CONTROL_EA5.VolcanoSA.20180104`, ...) and submits one job per chunk, each depending on
the previous one with `--dependency=afterany`. Slurm then runs them strictly
back-to-back, and no single job has to finish a year's retrieval inside the 36 h
wall-time limit.

Both arguments are optional (`Control/CONTROL_EA5` and 15 days by default) and can also
come from `FE_BASE_CONTROL` / `FE_CHUNK_DAYS`. Export `SBATCH_ACCOUNT` first, or the
`sbatch` calls inside will fail for want of an account.

Monitor with `squeue --me`; logs land in `Run/logs/`. To stop a chain, `scancel` **all**
of its jobs — with `afterany`, cancelling only the running one just releases the next.

The generated chunk CONTROL files are output, not source, and are git-ignored. The set
from the 2018 Sabancaya campaign is kept in `local_reference/volcano_sabancaya/` as a
record of what was run.

### Handing over to FLEXPART

When the retrieval is done:

```bash
cd /scratch/project_XXXXXXX/$USER/FLEXPART/mycase
/projappl/.../FLEXPART_v11/run/generate_available.py \
    /scratch/project_XXXXXXX/$USER/FLEXPART/ERA5/<case>/
```

which writes `AVAILABLE` and reports the period and spacing it found. Then follow
[`../FLEXPART_v11/README.md`](../FLEXPART_v11/README.md) section 4.

---

## 6. Troubleshooting

**`ECCODES_INCLUDE_DIR is not set — source ../../roihu_env.sh first`**
You ran `make` by hand in `Source/Fortran/`. Use `./setup_roihu.sh`.

**Compilation fails with `Can't open module file 'grib_api.mod'` or `-lemosR64` not found**
You are using an upstream makefile, which points at Mahti paths and an emoslib that does
not exist on Roihu. Use `./setup_roihu.sh`.

**`ImportError: libeccodes.so.0: cannot open shared object file`**
The python bindings and the loaded ecCodes module disagree, usually because the venv was
built against a different one. Re-source `roihu_env.sh` and
`pip install --force-reinstall eccodes`.

**HTTP 403 from the CDS**
The dataset licence has not been accepted for your account. Log in to the CDS web
interface, open the dataset, accept, retry. It is per dataset — ERA5 complete and ERA5
single levels are separate.

**The job finishes in seconds with no output**
Almost always `~/.cdsapirc` is missing or malformed, or `CONTROLFILE` names a file that
does not exist in `Run/Control/`.

**A retrieval hangs for hours**
That is usually normal — the request is queued at ECMWF. `mars_requests.csv` in the
working directory records what was asked for (`REQUEST=2` in `run_local.sh`), and the
CDS web interface shows the queue position. Split the period with `submit_chain.sh`
rather than raising the wall time.

**`No space left on device` / quota exceeded mid-retrieval**
The intermediate files are bigger than the output. Retrieve in chunks, and clean
`INPUTDIR` between them if it is separate from `OUTPUTDIR`.

**FLEXPART later complains about precipitation fields**
`RRINT` in this CONTROL file and `numpf` in `FLEXPART_v11/src/par_mod.f90` disagree —
see section 4.

Anything else: manuel.bettineschi@helsinki.fi

---

## License

Upstream flex_extract is © 2014–2020 Anne Philipp, Leopold Haimberger and Petra Seibert,
licensed **CC-BY-4.0** (`LICENSE.md`); the Fortran sources under `Source/Fortran/` carry
`SPDX-License-Identifier: GPL-2.0`. The Roihu setup and run scripts added here are
released under the same terms as the files they accompany.
