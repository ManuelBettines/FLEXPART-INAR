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

Citing the papers below is an academic courtesy, not a license condition — but please do it.

---

## Contacts
For questions, suggestions, request, or any other thing you can contact:
manuel.bettineschi@helsinki.fi
