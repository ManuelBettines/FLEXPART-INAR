#!/bin/bash
#=====================================================================================
# Run FLEXPART v11 on Roihu (CSC) — one node, OpenMP.
#
#   1. copy this script into your case directory, next to 'pathnames'
#   2. edit the CONFIGURATION block below (and the #SBATCH lines)
#   3. submit, giving your CSC project:
#          sbatch --account=project_XXXXXXX run_flexpart.slurm
#
# --account is deliberately NOT hard-coded, so this file works for everyone at INAR.
# If you get tired of typing it, add   #SBATCH --account=project_XXXXXXX   below, or
# set SBATCH_ACCOUNT=project_XXXXXXX in your ~/.bashrc.
#=====================================================================================
#SBATCH --job-name=flexpart11
#SBATCH --partition=small
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=32
#SBATCH --mem=0
#SBATCH --time=72:00:00
#SBATCH --output=flexpart_%j.out
#SBATCH --error=flexpart_%j.err

#--------------------------------- CONFIGURATION -------------------------------------
# EDIT THIS. Your case directory lives on /scratch and the code lives in /projappl, so
# there is no sensible relative default: point FP_ROOT at the repository's
# FLEXPART_v11 directory (or export FP_ROOT before submitting).
FP_ROOT="${FP_ROOT:-/projappl/project_XXXXXXX/$USER/FLEXPART/FLEXPART_v11}"

# FLEXPART_ETA is the eta-coordinate, netCDF build — the one you want for ECMWF data.
FP_BIN="${FP_BIN:-$FP_ROOT/bin/FLEXPART_ETA}"
FP_ENV="${FP_ENV:-$FP_ROOT/roihu_env.sh}"

# Read from the directory you submit in.
FP_PATHNAMES="${FP_PATHNAMES:-pathnames}"
#-------------------------------------------------------------------------------------

set -o pipefail
cd "$SLURM_SUBMIT_DIR"

# Load exactly the modules the binary was built with — ecCodes included. This is why
# the 300-character LD_LIBRARY_PATH of the old Puhti launch script is not needed.
[ -f "$FP_ENV" ] || {
  echo "ERROR: $FP_ENV not found. Edit FP_ROOT at the top of this script (or export" >&2
  echo "       FP_ROOT) so it points at the repository's FLEXPART_v11 directory." >&2
  exit 1
}
source "$FP_ENV" || { echo "ERROR: cannot source $FP_ENV" >&2; exit 1; }

export OMP_NUM_THREADS="${SLURM_CPUS_PER_TASK:-1}"
export OMP_STACKSIZE=512M     # the per-thread private arrays are large
export OMP_PLACES=cores
export OMP_PROC_BIND=true
ulimit -s unlimited

echo "=============================================================================="
echo " FLEXPART v11 (OpenMP)   job ${SLURM_JOB_ID:-interactive} on $(hostname)"
echo " start           : $(date)"
echo " workdir         : $PWD"
echo " repo            : $FP_ROOT"
echo " binary          : $FP_BIN"
echo " pathnames       : $FP_PATHNAMES"
echo " OMP_NUM_THREADS : $OMP_NUM_THREADS"
echo "=============================================================================="

[ -x "$FP_BIN" ]       || { echo "ERROR: $FP_BIN not found — check FP_ROOT, and run compile_roihu.sh eta." >&2; exit 1; }
[ -f "$FP_PATHNAMES" ] || { echo "ERROR: $FP_PATHNAMES not found (FLEXPART reads it from the working directory)." >&2; exit 1; }

# pathnames, line by line:  1 options dir, 2 output dir, 3 met data dir, 4 AVAILABLE.
OPTDIR="$(sed -n '1p' "$FP_PATHNAMES" | tr -d '[:space:]')"
OUTDIR="$(sed -n '2p' "$FP_PATHNAMES" | tr -d '[:space:]')"
METDIR="$(sed -n '3p' "$FP_PATHNAMES" | tr -d '[:space:]')"
AVAIL="$(sed -n  '4p' "$FP_PATHNAMES" | tr -d '[:space:]')"

# FLEXPART does not create its output directory, and fails late and confusingly if it
# is missing. The other three must already exist.
mkdir -p "$OUTDIR" || { echo "ERROR: cannot create output dir '$OUTDIR' (line 2 of $FP_PATHNAMES)." >&2; exit 1; }
for d in "$OPTDIR" "$METDIR"; do
  [ -d "$d" ] || { echo "ERROR: '$d' from $FP_PATHNAMES is not a directory." >&2; exit 1; }
done
[ -f "$AVAIL" ] || { echo "ERROR: AVAILABLE file '$AVAIL' (line 4 of $FP_PATHNAMES) does not exist." >&2; exit 1; }

srun "$FP_BIN" "$FP_PATHNAMES"
rc=$?

echo "=============================================================================="
echo " end: $(date)   exit code: $rc"
echo " output in: $OUTDIR"
echo "=============================================================================="
exit $rc
