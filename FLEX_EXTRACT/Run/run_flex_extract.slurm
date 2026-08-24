#!/bin/bash
#=====================================================================================
# Run one flex_extract retrieval on Roihu (CSC).
#
#   sbatch --account=project_XXXXXXX run_flex_extract.slurm
#   sbatch --account=project_XXXXXXX run_flex_extract.slurm CONTROL_EA5.VolcanoSA
#
# $1 (optional) is the BASENAME of a CONTROL file in Run/Control/. submit.py resolves
# it relative to Control/, so pass the basename, not a path. Without it, whatever
# run_local.sh has in CONTROLFILE is used.
#
# The work itself is not parallel: flex_extract spends most of its time waiting for
# ECMWF to serve the request and then running calc_etadot once per time step. One task
# on one node is right; the wall time is what matters. A CDS request for a couple of
# weeks of hourly ERA5 on 137 levels can sit in the queue for hours, so submit_chain.sh
# exists to split a long period into jobs that each finish inside the wall-time limit.
#
# --account is deliberately NOT hard-coded, so this file works for everyone at INAR.
#=====================================================================================
#SBATCH --job-name=flex_extract
#SBATCH --partition=small
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=36:00:00
#SBATCH --output=flex_extract_%j.out
#SBATCH --error=flex_extract_%j.err

#--------------------------------- CONFIGURATION -------------------------------------
# Where roihu_env.sh lives (the repo's FLEX_EXTRACT directory).
FE_ENV="${FE_ENV:-../roihu_env.sh}"
#-------------------------------------------------------------------------------------

set -o pipefail
cd "$SLURM_SUBMIT_DIR"

# Exactly the modules and the virtual environment calc_etadot was built with, so the
# ecCodes the python bindings load is the one it is linked against.
source "$FE_ENV" || { echo "ERROR: cannot source $FE_ENV" >&2; exit 1; }

# run_local.sh reads this:  CONTROLFILE="${FE_CONTROLFILE:-CONTROL_EA5.VolcanoSA}"
if [ -n "${1:-}" ]; then
  export FE_CONTROLFILE="$1"
fi
CTRL="${FE_CONTROLFILE:-$(awk -F'"' '/^CONTROLFILE=/{print $2; exit}' run_local.sh)}"

echo "=============================================================================="
echo " flex_extract   job ${SLURM_JOB_ID:-interactive} on $(hostname)"
echo " start        : $(date)"
echo " workdir      : $PWD"
echo " CONTROL file : ${CTRL:-<the default in run_local.sh>}"
echo "=============================================================================="

[ -f "run_local.sh" ] || { echo "ERROR: run_local.sh not found — submit from the Run/ directory." >&2; exit 1; }
if [ -n "${FE_CONTROLFILE:-}" ] && [ ! -f "Control/$FE_CONTROLFILE" ]; then
  echo "ERROR: Control/$FE_CONTROLFILE does not exist." >&2
  exit 1
fi

# INPUTDIR/OUTPUTDIR are set inside run_local.sh; flex_extract does not create them.
for var in INPUTDIR OUTPUTDIR; do
  d=$(awk -F"'" -v v="$var" '$0 ~ "^"v"=" {print $2; exit}' run_local.sh)
  [ -n "$d" ] && [ "$d" != "None" ] && mkdir -p "$d"
done

bash run_local.sh
rc=$?

echo "=============================================================================="
echo " end: $(date)   exit code: $rc"
echo "=============================================================================="
exit $rc
