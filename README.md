# FLEXPART at INAR — Roihu setup and guide

Lagrangian particle dispersion modelling at the **Institute for Atmospheric and Earth
System Research (INAR), University of Helsinki**, on **Roihu** (CSC supercomputer).

Everything here assumes you are working on (and have access to) Roihu.

---

## 1. What is in this repository

| Folder | What it is | Use it when |
|---|---|---|
| [`FLEXPART_v11/`](FLEXPART_v11/) | **FLEXPART v11** — the standard model, driven by ECMWF (ERA5 / operational) data | You want global or continental-scale runs, and complex terrain is not a problem. **Recommended for most cases** |
| [`FLEX_EXTRACT/`](FLEX_EXTRACT/) | **flex_extract** — retrieves and prepares the ECMWF input files FLEXPART v11 needs | Always, before running FLEXPART v11 |
| [`WRF-FLEXPART/`](WRF-FLEXPART/) | **FLEXPART-WRF v3.3.2** — offline dispersion driven by your own WRF output | You are working on complex terrain and need high spatial resolution, and you already have WRF output. **Not** recommended for most cases |
| [`analysis_scripts/`](analysis_scripts/) | post-processing scripts for WRF-FLEXPART. If you want to use them for a "normal" FLEXPART run, you need to adapt them | After a WRF-FLEXPART run |

**Each folder has its own `README.md`** with the full compile-and-run instructions for
Roihu.

---

## 2. Getting the code onto Roihu

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
| `/projappl/project_XXXXXXX/$USER/` | source code, executables, namelists — this repository |
| `/scratch/project_XXXXXXX/$USER/` | wrfout / ECMWF input and model output (large, **not backed up, auto-cleaned**) |

Replace `project_XXXXXXX` with your own CSC project. Nothing in this repository
hard-codes a project number: pass it as `sbatch --account=project_XXXXXXX`, or export
`SBATCH_ACCOUNT=project_XXXXXXX` once in your `~/.bashrc`.

---

## 3. Selected applications at INAR

A **non-exhaustive** list of studies by INAR members and collaborators that used FLEXPART
or FLEXPART-WRF:

- Bianchi, F., Junninen, H., Bigi, A., et al. (2021): *Biogenic particles formed in the
  Himalaya as an important source of free tropospheric aerosols*, Nat. Geosci., **14**,
  4–9. <https://doi.org/10.1038/s41561-020-00661-5>
- Aliaga, D., Sinclair, V. A., Andrade, M., et al. (2021): *Identifying source regions of
  air masses sampled at the tropical high-altitude site of Chacaltaya using WRF-FLEXPART
  and cluster analysis*, Atmos. Chem. Phys., **21**, 16453–16477.
  <https://doi.org/10.5194/acp-21-16453-2021>
- Hakala, S., Vakkari, V., Bianchi, F., et al. (2022): *Observed coupling between air mass
  history, secondary growth of nucleation mode particles and aerosol pollution levels in
  Beijing*, Environ. Sci.: Atmos., **2**, 146–164.
  <https://doi.org/10.1039/D1EA00089F>
- Xavier, C., Baykara, M., Wollesen de Jonge, R., et al. (2022): *Secondary aerosol
  formation in marine Arctic environments: a model measurement comparison at Ny-Ålesund*,
  Atmos. Chem. Phys., **22**, 10023–10043.
  <https://doi.org/10.5194/acp-22-10023-2022>
- Boyer, M., Aliaga, D., Quéléver, L. L. J., et al. (2024): *The annual cycle and sources
  of relevant aerosol precursor vapors in the central Arctic during the MOSAiC
  expedition*, Atmos. Chem. Phys., **24**, 12595–12621.
  <https://doi.org/10.5194/acp-24-12595-2024>
- Bettineschi, M., Vitali, B., Cholakian, A., et al. (2025): *Across land, sea, and
  mountains: sulphate aerosol sources and transport dynamics over the northern
  Apennines*, Environ. Sci.: Atmos., **5**, 1023–1034.
  <https://doi.org/10.1039/D5EA00035A>
- Foreback, B., Clusius, P., Baykara, M., et al. (2025): *A Lagrangian view on severe haze
  in Beijing: local and long-range sources of trace gases and primary and secondary
  aerosols*, Atmos. Environ., **363**, 121602.
  <https://doi.org/10.1016/j.atmosenv.2025.121602>
- Clusius, P., Baykara, M., Xavier, C., et al. (2026): *Modelling the impact of
  anthropogenic aerosols on CCN concentrations over a rural boreal forest environment*,
  Atmos. Chem. Phys., **26**, 1967–1992.
  <https://doi.org/10.5194/acp-26-1967-2026>
- Agrò, M., Bettineschi, M., Melina, S., et al. (2026): *Ventilation and low pollution
  enhancing new particle formation in Milan, Italy*, Atmos. Chem. Phys., **26**,
  6521–6539. <https://doi.org/10.5194/acp-26-6521-2026>

---

## 4. Official resources

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

## 5. License

**GNU General Public License v3 or later** — see [`LICENSE`](LICENSE) for the full text.

`FLEXPART_v11/` is FLEXPART v11, copyright the FLEXPART developers as named in the file
headers (`SPDX-FileCopyrightText: FLEXPART 1998-2019`), released under the GPLv3 or later
(`FLEXPART_v11/LICENSE`). This repository redistributes it under the same terms.

`WRF-FLEXPART/` is FLEXPART-WRF v3.3.2, copyright J. Brioude, D. Arnold, A. Stohl
and the other FLEXPART authors named in the file headers, released under the GPLv3.
This repository redistributes it under the same terms.

`FLEX_EXTRACT/` is a different licence: © 2014–2020 Anne Philipp, Leopold Haimberger and
Petra Seibert under **CC-BY-4.0** (`FLEX_EXTRACT/LICENSE.md`), except the Fortran sources
under `FLEX_EXTRACT/Source/Fortran/`, which are GPL-2.0.

The Roihu-specific build, setup, run and analysis scripts written for this repository are released under **CC0 1.0 Universal (CC0-1.0)**. To the extent permitted by law, they may be copied, modified, distributed and used for any purpose without permission or attribution.

---

## 6. Contacts

For questions, suggestions or requests: manuel.bettineschi@helsinki.fi
