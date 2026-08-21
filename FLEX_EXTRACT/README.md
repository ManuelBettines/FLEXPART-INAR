# flex_extract on Roihu (CSC)

> **Status: not set up yet.** The Roihu setup and run instructions for flex_extract are
> being written; this folder is a placeholder so the repository structure is complete.

**flex_extract** retrieves meteorological fields from ECMWF (MARS, or the Copernicus
Climate Data Store for ERA5) and converts them into the `EN*` GRIB files that
**FLEXPART v11** reads. It is a pre-processing step, not a model: run it first, then
point FLEXPART at its output.

## Official resources

- flex_extract documentation — <https://www.flexpart.eu/flex_extract/>
- Source (GitLab) — <https://www.flexpart.eu/gitlab/flex_extract/flex_extract>
- FLEXPART home page — <https://www.flexpart.eu/>

## Before you start

Access to ECMWF data is **not** automatic and takes time to arrange:

- **ERA5 via the CDS** needs a Copernicus account and a `~/.cdsapirc` API key, and each
  dataset licence must be accepted once in the web interface.
- **MARS access** (operational data, faster retrievals) needs an ECMWF account
  associated with a member-state institution — ask the INAR contact for FMI
  sponsorship.

Retrievals are queued at ECMWF and can take hours to days for long periods. Plan for
that rather than treating it as an interactive step.

## What will go here

- `roihu_env.sh` — Roihu modules and the Python environment
- setup and installation notes for the `local` (CDS) and `remote`/`gateway` (MARS) modes
- `run/` — `CONTROL_*` templates for the periods INAR uses, plus Slurm scripts
- guidance on where to stage the output on `/scratch` so FLEXPART v11 can find it

A development checkout already exists at `~/Desktop/flex_extract-dev` on the Helsinki
desktop; it will be cleaned up and moved here.
