# FLEXPART at INAR — Roihu (CSC) setup

Lagrangian particle dispersion modelling at the **Institute for Atmospheric and Earth
System Research (INAR), University of Helsinki**, on **Roihu** (CSC supercomputer).

Everything here assumes you are working on (and have access to) **Roihu**.

---

## What is in this repository?

| Folder | What it is | Use it when |
|---|---|---|
| [`WRF-FLEXPART/`](WRF-FLEXPART/) | **FLEXPART-WRF v3.3.2** — offline dispersion driven by your own WRF output | You are working on complex terrain and need high spatial resolution. You need to have WRF output already available. **Not** reccomended for most cases |
| [`FLEXPART_v11/`](FLEXPART_v11/) | **FLEXPART v11** — the standard model, driven by ECMWF (ERA5 / operational) data | You want global or continental-scale runs and/or complex terrain is not a problem. Reccomended for most cases  |
| [`FLEX_EXTRACT/`](FLEX_EXTRACT/) | **flex_extract** — retrieves and prepares the ECMWF input files that FLEXPART v11 needs | Always, before running FLEXPART v11 |

Each folder has its own `README.md` with the full compile-and-run instructions for
Roihu. Start there.

### Which one do I want?

- Driving the dispersion with **your own WRF simulation** (nested domains, km-scale,
  a specific campaign) → `WRF-FLEXPART/`.
- Driving it with **ECMWF data** → `FLEX_EXTRACT/` to get the input, then
  `FLEXPART_v11/` to run it.

The two model versions have **different input file formats and different output
formats**; they are not drop-in replacements for each other.

### The same shape in every folder

Each of the three folders is laid out the same way, so what you learn in one carries
over:

| File | What it does |
|---|---|
| `roihu_env.sh` | the module stack. **Sourced** by the build and the run scripts, so the two can never drift apart. Never run it |
| `compile_roihu.sh` / `setup_roihu.sh` | one command, no modules to load first, a build summary at the end |
| `makefile.roihu` / `makefile_roihu` | the Roihu-adapted makefile; every change from upstream is marked `# ROIHU:` |
| `run/` (or `Run/`) | templates, the generators that fill them in, and the Slurm scripts |
| `local_reference/` | your own namelists, logs and old binaries. Git-ignored, never pushed |
| `README.md` | compile, prepare, submit, troubleshoot |

Nothing hard-codes a CSC project number: pass it as `sbatch --account=project_XXXXXXX`,
or export `SBATCH_ACCOUNT` once in your `~/.bashrc`.

### A typical ECMWF-driven run, end to end

```bash
# 1. retrieve the meteorology (hours to days — it queues at ECMWF)
cd FLEX_EXTRACT && ./setup_roihu.sh
cd Run && sbatch --account=project_XXXXXXX run_flex_extract.slurm CONTROL_EA5.MyCase

# 2. build the model (minutes, on the login node)
cd ../../FLEXPART_v11 && ./compile_roihu.sh

# 3. set the case up on /scratch
mkdir -p /scratch/project_XXXXXXX/$USER/FLEXPART/mycase
cd       /scratch/project_XXXXXXX/$USER/FLEXPART/mycase
cp -r /projappl/.../FLEXPART_v11/options .
cp    /projappl/.../FLEXPART_v11/run/* .
mv    pathnames.template pathnames        # then edit its four lines

./generate_available.py /scratch/project_XXXXXXX/$USER/FLEXPART/ERA5/MyCase/
./generate_releases.py --command options/COMMAND -o options/RELEASES \
     --control /projappl/.../FLEX_EXTRACT/Run/Control/CONTROL_EA5.MyCase \
     --lat 60.2 --lon 24.96 --box 10 --npart 20000 --outgrid options/OUTGRID \
     --log-levels 20 --ztop 20000

# 4. run
sbatch --account=project_XXXXXXX run_flexpart.slurm
```

Two couplings between the folders are easy to miss, and both are documented in the
folder READMEs:

- **`RRINT` (CONTROL) ↔ `numpf` (`par_mod.f90`)** — the number of precipitation fields
  the retrieval writes and the number FLEXPART is compiled to read must agree. Both
  are set to the "new" scheme here (`RRINT 1`, `numpf=3`).
- **the retrieved domain ↔ the release box and output grid** — everything FLEXPART
  does must fit inside `LEFT`/`RIGHT`/`LOWER`/`UPPER`. `generate_releases.py --control`
  checks it for you.

---

## Getting the code on Roihu

Log in to the **CPU** login node and clone into `/projappl`, not into `$HOME`:

```bash
ssh -A -X <username>@roihu-cpu.csc.fi

# code lives in /projappl (backed up, quota for software)
cd /projappl/project_XXXXXXX/$USER
git clone git@github.com:ManuelBettines/FLEXPART-INAR.git FLEXPART
cd FLEXPART
```

Where things belong on Roihu:

| Path | For |
|---|---|
| `/projappl/project_XXXXXXX/$USER/` | source code, executables, namelists — this repo |
| `/scratch/project_XXXXXXX/$USER/` | wrfout / ECMWF input and model output (large, **not backed up, auto-cleaned**) |

Replace `project_XXXXXXX` with your own CSC project. Nothing in this repository
hard-codes a project number; you pass it to `sbatch --account=...` at submission time.

---

## Official resources and docs

- **FLEXPART home page** — <https://www.flexpart.eu/>
- **flex_extract** — <https://www.flexpart.eu/flex_extract/>
- **CSC Roihu user documentation** — <https://docs.csc.fi/>

### How to cite

- **FLEXPART-WRF**: Brioude, J., Arnold, D., Stohl, A., et al. (2013): *The Lagrangian
  particle dispersion model FLEXPART-WRF version 3.1*, Geosci. Model Dev., **6**,
  1889–1904. <https://doi.org/10.5194/gmd-6-1889-2013>
- **FLEXPART v10/v11**: Pisso, I., et al. (2019): *The Lagrangian particle dispersion
  model FLEXPART version 10.4*, Geosci. Model Dev., **12**, 4955–4997.
  <https://doi.org/10.5194/gmd-12-4955-2019>

---

## License

**GNU General Public License v3 or later** — see [`LICENSE`](LICENSE) for the full text.

`WRF-FLEXPART/src/` is FLEXPART-WRF v3.3.2, copyright J. Brioude, D. Arnold, A. Stohl
and the other FLEXPART authors named in the file headers, released under the GPLv3.
This repository redistributes it under the same terms, along with the Roihu build and
run scripts. Files modified at INAR carry a dated modification notice in their header,
as GPLv3 §5(a) requires.

A few files under `src/` come from third parties and keep their own (GPL-compatible)
licenses, stated in their headers:

| File(s) | Origin | License |
|---|---|---|
| `mt_stream.f90`, `gf2xe.f90`, `mt_kind_defs.f90` | K.-I. Ishikawa, Mersenne Twister | 3-clause BSD |
| `ranlux.f90` | F. James, CERN | see header |
| `map_proj_wrf_subaa.f90` | NOAA/OAR/FSL | public domain, open-source disclaimer |

`FLEXPART_v11/src/` is FLEXPART 11, GPLv3-or-later (`SPDX-License-Identifier:
GPL-3.0-or-later` in the file headers), with the INAR modifications described in
[`FLEXPART_v11/README.md`](FLEXPART_v11/README.md) section 1; the upstream version of
each modified file is kept beside it as `*.f90_original`.

`FLEX_EXTRACT/` is a different licence: © 2014–2020 Anne Philipp, Leopold Haimberger
and Petra Seibert under **CC-BY-4.0** (`FLEX_EXTRACT/LICENSE.md`), except the Fortran
sources under `FLEX_EXTRACT/Source/Fortran/`, which are GPL-2.0.

Citing the papers below is an academic courtesy, not a license condition — but please do it.

---

## Contacts
For questions, suggestions, request, or any other thing you can contact:
manuel.bettineschi@helsinki.fi
