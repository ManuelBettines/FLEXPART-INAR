#!/bin/bash
#=====================================================================================
# Run FLEXPART-WRF on Roihu (CSC) — single node, OpenMP.
#
# This is the normal production setup: one task, many threads, one node. Use
# run_flexwrf_mpi.slurm instead only when one node is genuinely not enough.
#
#   1. copy this script next to your flexwrf.input
#   2. edit the CONFIGURATION block below (and #SBATCH lines) to taste
#   3. submit, giving your CSC project:
#          sbatch --account=project_XXXXXXX run_flexwrf_omp.slurm
#
# --account is deliberately NOT hard-coded, so this file works for everyone at INAR.
# If you get tired of typing it, add   #SBATCH --account=project_XXXXXXX   below, or
# set SBATCH_ACCOUNT=project_XXXXXXX in your ~/.bashrc.
#=====================================================================================
#SBATCH --job-name=flexwrf
#SBATCH --partition=small
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=32
#SBATCH --mem=64G
#SBATCH --time=36:00:00
#SBATCH --output=flexwrf_%j.out
#SBATCH --error=flexwrf_%j.err

#--------------------------------- CONFIGURATION -------------------------------------
# Binary and input file. Relative paths are resolved from the directory you submit in.
FLEXWRF_BIN="${FLEXWRF_BIN:-../bin/flexwrf33_gnu_omp}"
FLEXWRF_INPUT="${FLEXWRF_INPUT:-flexwrf.input}"

# Where roihu_env.sh lives (repo's WRF-FLEXPART directory).
FLEXWRF_ENV="${FLEXWRF_ENV:-../roihu_env.sh}"
#-------------------------------------------------------------------------------------

set -uo pipefail
cd "$SLURM_SUBMIT_DIR"

# Load exactly the modules the binary was built with. This is why the old Puhti
# LD_LIBRARY_PATH hack is not needed any more.
source "$FLEXWRF_ENV" || { echo "ERROR: cannot source $FLEXWRF_ENV" >&2; exit 1; }

export OMP_NUM_THREADS="${SLURM_CPUS_PER_TASK:-1}"
export OMP_STACKSIZE=512M     # FLEXPART-WRF gives each thread large private arrays
ulimit -s unlimited

echo "=============================================================================="
echo " FLEXPART-WRF (OpenMP)   job ${SLURM_JOB_ID:-interactive} on $(hostname)"
echo " start           : $(date)"
echo " workdir         : $PWD"
echo " binary          : $FLEXWRF_BIN"
echo " input           : $FLEXWRF_INPUT"
echo " OMP_NUM_THREADS : $OMP_NUM_THREADS"
echo "=============================================================================="

[ -x "$FLEXWRF_BIN" ]   || { echo "ERROR: $FLEXWRF_BIN not found — run compile_roihu.sh omp first." >&2; exit 1; }
[ -f "$FLEXWRF_INPUT" ] || { echo "ERROR: input file $FLEXWRF_INPUT not found." >&2; exit 1; }

# Line 2 of the input file is the output directory, and FLEXPART does not create it.
OUTDIR="$(sed -n '2p' "$FLEXWRF_INPUT" | tr -d '[:space:]')"
mkdir -p "$OUTDIR" || { echo "ERROR: cannot create output dir '$OUTDIR' (line 2 of $FLEXWRF_INPUT)." >&2; exit 1; }

srun "$FLEXWRF_BIN" "$FLEXWRF_INPUT"
rc=$?

echo "=============================================================================="
echo " end: $(date)   exit code: $rc"
echo " output in: $OUTDIR"
echo "=============================================================================="
exit $rc
