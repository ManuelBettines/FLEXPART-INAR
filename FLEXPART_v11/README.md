# FLEXPART v11 on Roihu (CSC)

> **Status: not set up yet.** The Roihu compile and run instructions for FLEXPART v11
> are being written; this folder is a placeholder so the repository structure is
> complete. Until then, use [`../WRF-FLEXPART/`](../WRF-FLEXPART/) for WRF-driven runs.

**FLEXPART v11** is the current release of the standard (global) Lagrangian particle
dispersion model, driven by ECMWF meteorology — ERA5 or the operational analysis —
rather than by your own WRF output. It is a substantial rewrite of v10: restructured
particle handling, improved wet deposition and turbulence, and a netCDF output path.

Its input files are produced by **flex_extract**, so set that up first:
[`../FLEX_EXTRACT/`](../FLEX_EXTRACT/).

## Official resources

- FLEXPART home page — <https://www.flexpart.eu/>
- Source and issues (GitLab) — <https://www.flexpart.eu/gitlab/flexpart>
- Documentation and release notes — <https://www.flexpart.eu/wiki/FpRoadmap>

## Cite

Pisso, I., et al. (2019): *The Lagrangian particle dispersion model FLEXPART version
10.4*, Geosci. Model Dev., **12**, 4955–4997.
<https://doi.org/10.5194/gmd-12-4955-2019> — plus the v11 reference once published.

## What will go here

- `roihu_env.sh` — the Roihu module stack (gcc, OpenMPI, netCDF, ecCodes)
- `compile_roihu.sh` — one-command build, matching the WRF-FLEXPART one
- `README.md` — step-by-step compile and run guide
- `run/` — `COMMAND` / `RELEASES` / `OUTGRID` / `SPECIES` templates and Slurm scripts

Note that FLEXPART v11 needs **ecCodes** for GRIB input, which FLEXPART-WRF does not.
