# FLEXPART at INAR — Roihu (CSC) setup

Lagrangian particle dispersion modelling at the **Institute for Atmospheric and Earth
System Research (INAR), University of Helsinki**, on **Roihu**, the CSC supercomputer.

Everything here assumes you are working **on Roihu**. The scripts load Roihu's module
stack and submit to Roihu's Slurm partitions; they are not meant to be run on a laptop
or on Puhti/Mahti/LUMI without changes.

---

## What is in this repository

| Folder | What it is | Use it when |
|---|---|---|
| [`WRF-FLEXPART/`](WRF-FLEXPART/) | **FLEXPART-WRF v3.3.2** (INAR working version) — offline dispersion driven by your own WRF output | You have run WRF yourself and want dispersion on that grid, at that resolution |
| [`FLEXPART_v11/`](FLEXPART_v11/) | **FLEXPART v11** — the standard global model, driven by ECMWF (ERA5 / operational) data | You want global or continental-scale runs and do not need your own WRF meteorology |
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

---

## Getting the code on Roihu

Log in to the **CPU** login node and clone into `/projappl`, not into `$HOME`:

```bash
ssh -A -X <username>@roihu-cpu.csc.fi

# code lives in /projappl (backed up, quota for software)
cd /projappl/project_XXXXXXX/$USER
git clone <this-repo-url> FLEXPART
cd FLEXPART
```

Where things belong on Roihu:

| Path | For |
|---|---|
| `/projappl/project_XXXXXXX/$USER/` | source code, executables, namelists — this repo |
| `/scratch/project_XXXXXXX/$USER/` | wrfout / ECMWF input and model output (large, **not backed up, auto-cleaned**) |
| `$HOME` | small personal config only — the quota is tiny, do not build here |

Replace `project_XXXXXXX` with your own CSC project. Nothing in this repository
hard-codes a project number; you pass it to `sbatch --account=...` at submission time.

### A word on Roihu's two architectures

Roihu is architecturally split, and **binaries do not run across the two sides**
(you get `cannot execute binary file: Exec format error`):

| Side | Login node | Partitions | Compiler in the module stack |
|---|---|---|---|
| **x86_64** | `roihu-cpu.csc.fi` | `test`, `interactive`, `small`, `medium`, `large`, `longrun`, `hugemem` | `gcc/15.2.0` |
| **aarch64** (Grace) | `roihu-gpu-login2` | `gpu*` | `gcc/14.3.0` |

FLEXPART is CPU-only, so **build on `roihu-cpu.csc.fi` and submit to the CPU
partitions**. The build scripts refuse to run on the wrong architecture rather than
producing a binary that dies at submission time.

---

## Official FLEXPART resources

- **FLEXPART home page** — <https://www.flexpart.eu/>
- **Source and issue tracker (GitLab)** — <https://www.flexpart.eu/gitlab/flexpart>
- **FLEXPART v11 documentation** — <https://www.flexpart.eu/wiki/FpRoadmap>
- **FLEXPART-WRF** — <https://www.flexpart.eu/wiki/FpLimitedareaWrf>
- **flex_extract** — <https://www.flexpart.eu/flex_extract/>
- **CSC Roihu user documentation** — <https://docs.csc.fi/>

### How to cite

- **FLEXPART-WRF**: Brioude, J., Arnold, D., Stohl, A., et al. (2013): *The Lagrangian
  particle dispersion model FLEXPART-WRF version 3.1*, Geosci. Model Dev., **6**,
  1889–1904. <https://doi.org/10.5194/gmd-6-1889-2013>
- **FLEXPART v10/v11**: Pisso, I., et al. (2019): *The Lagrangian particle dispersion
  model FLEXPART version 10.4*, Geosci. Model Dev., **12**, 4955–4997.
  <https://doi.org/10.5194/gmd-12-4955-2019>

Please also cite the papers listed in each model's own documentation for the specific
schemes you switch on.

---

## Conventions in this repository

- **No CSC project number is hard-coded.** Pass `--account=project_XXXXXXX` to
  `sbatch`, or set `SBATCH_ACCOUNT` in your `~/.bashrc`.
- **Executables and object files are never committed.** They depend on the compiler,
  the module stack, and (for FLEXPART-WRF) the domain sizes compiled into the source.
  Always rebuild.
- **Large generated namelists are not committed either.** Each model folder ships
  templates and the scripts that generate the big files.
- **`local_reference/` folders are git-ignored** — they are for keeping your own
  working namelists and logs next to the code without pushing them to GitHub.
