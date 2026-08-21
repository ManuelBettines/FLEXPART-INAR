#!/bin/bash
#=====================================================================================
# Optional batch wrapper around compile_roihu.sh.
#
# Building on the Roihu login node is fine (a few minutes, a handful of cores), so
# this is only for when you would rather not tie up a login shell, or when a login
# node is busy.
#
#   sbatch --account=project_XXXXXXX compile_roihu.slurm
#   sbatch --account=project_XXXXXXX compile_roihu.slurm omp     # one flavour only
#=====================================================================================
#SBATCH --job-name=flexwrf_build
#SBATCH --partition=small
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=16G
#SBATCH --time=01:00:00
#SBATCH --output=compile_%j.log

cd "$SLURM_SUBMIT_DIR"
./compile_roihu.sh "${@:-all}" -j "${SLURM_CPUS_PER_TASK:-8}"
