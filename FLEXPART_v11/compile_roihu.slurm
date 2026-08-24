#!/bin/bash
#=====================================================================================
# Optional batch wrapper around compile_roihu.sh.
#
# Building on the Roihu login node is fine (a few minutes, a handful of cores), so
# this is only for when you would rather not tie up a login shell, or when a login
# node is busy.
#
#   sbatch --account=project_XXXXXXX compile_roihu.slurm
#   sbatch --account=project_XXXXXXX compile_roihu.slurm eta     # one flavour only
#=====================================================================================
#SBATCH --job-name=flexpart11_build
#SBATCH --partition=small
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=16G
#SBATCH --time=01:00:00
#SBATCH --output=compile_%j.log

cd "$SLURM_SUBMIT_DIR"

# Pass through whatever flavours were given to sbatch; default to the script's own
# default (eta + meter) when none were. Note "${@:-eta meter}" would NOT work here:
# with an empty $@ it expands to the single word "eta meter", which the script
# rejects as an unknown argument.
if [ $# -gt 0 ]; then
  ./compile_roihu.sh "$@" -j "${SLURM_CPUS_PER_TASK:-8}"
else
  ./compile_roihu.sh -j "${SLURM_CPUS_PER_TASK:-8}"
fi
