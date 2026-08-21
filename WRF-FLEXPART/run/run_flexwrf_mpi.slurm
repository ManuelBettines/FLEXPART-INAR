#!/bin/bash
#=====================================================================================
# Run FLEXPART-WRF on Roihu (CSC) — multi-node, hybrid MPI + OpenMP.
#
# Only use this when a single node is not enough. FLEXPART-WRF's MPI layer distributes
# particles over ranks and gathers the concentration fields on rank 0, so it scales
# well with particle count but NOT with grid size — a bigger output grid makes rank 0
# the bottleneck. If in doubt, start with run_flexwrf_omp.slurm.
#
#   sbatch --account=project_XXXXXXX run_flexwrf_mpi.slurm
#
# Total threads = nodes x ntasks-per-node x cpus-per-task. Keep that at or below the
# cores you actually requested, or the ranks will fight over the same cores.
#=====================================================================================
#SBATCH --job-name=flexwrf_mpi
#SBATCH --partition=medium
#SBATCH --nodes=2
#SBATCH --ntasks-per-node=4
#SBATCH --cpus-per-task=8
#SBATCH --mem=0
#SBATCH --time=36:00:00
#SBATCH --output=flexwrf_mpi_%j.out
#SBATCH --error=flexwrf_mpi_%j.err

#--------------------------------- CONFIGURATION -------------------------------------
FLEXWRF_BIN="${FLEXWRF_BIN:-../bin/flexwrf33_gnu_mpi}"
FLEXWRF_INPUT="${FLEXWRF_INPUT:-flexwrf.input}"
FLEXWRF_ENV="${FLEXWRF_ENV:-../roihu_env.sh}"
#-------------------------------------------------------------------------------------

set -o pipefail
cd "$SLURM_SUBMIT_DIR"

source "$FLEXWRF_ENV" || { echo "ERROR: cannot source $FLEXWRF_ENV" >&2; exit 1; }

export OMP_NUM_THREADS="${SLURM_CPUS_PER_TASK:-1}"
export OMP_STACKSIZE=512M
ulimit -s unlimited

echo "=============================================================================="
echo " FLEXPART-WRF (MPI+OpenMP)   job ${SLURM_JOB_ID:-interactive}"
echo " start           : $(date)"
echo " nodes           : ${SLURM_JOB_NUM_NODES:-?}  (${SLURM_JOB_NODELIST:-?})"
echo " ranks           : ${SLURM_NTASKS:-?}"
echo " OMP_NUM_THREADS : $OMP_NUM_THREADS  -> ${SLURM_NTASKS:-?} x $OMP_NUM_THREADS threads total"
echo " binary          : $FLEXWRF_BIN"
echo " input           : $FLEXWRF_INPUT"
echo "=============================================================================="

[ -x "$FLEXWRF_BIN" ]   || { echo "ERROR: $FLEXWRF_BIN not found — run compile_roihu.sh mpi first." >&2; exit 1; }
[ -f "$FLEXWRF_INPUT" ] || { echo "ERROR: input file $FLEXWRF_INPUT not found." >&2; exit 1; }

OUTDIR="$(sed -n '2p' "$FLEXWRF_INPUT" | tr -d '[:space:]')"
mkdir -p "$OUTDIR" || { echo "ERROR: cannot create output dir '$OUTDIR' (line 2 of $FLEXWRF_INPUT)." >&2; exit 1; }

srun "$FLEXWRF_BIN" "$FLEXWRF_INPUT"
rc=$?

echo "=============================================================================="
echo " end: $(date)   exit code: $rc"
echo " output in: $OUTDIR"
echo "=============================================================================="
exit $rc
