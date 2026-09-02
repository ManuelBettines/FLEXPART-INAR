#!/bin/bash
#=====================================================================================
# Run one analysis_scripts tool on Roihu (CSC) as a batch job.
#
# The post-processing reads whole footprint fields into memory and, for the raw
# flxout files, sums hundreds of output steps — that is a compute-node job, not
# something to run on the login node.
#
#   sbatch --account=project_XXXXXXX run_analysis.slurm <tool> [arguments...]
#
# <tool> picks the script; everything after it is passed to that script unchanged,
# so every flag in README.md works exactly as documented:
#
#   sbatch --account=project_XXXXXXX run_analysis.slurm \
#          reduce flxout_d02_20220626_230000.nc -o footprints_d02.nc --chunk 100
#
#   sbatch --account=project_XXXXXXX run_analysis.slurm \
#          footprint footprints_d01.nc --start 2022-05-28 --end 2022-05-29
#
#   sbatch --account=project_XXXXXXX --time=12:00:00 --mem=64G run_analysis.slurm \
#          ame flxout_d01_20230430_230000.nc --emis EMISSION_MILAN.nc --var MONOT NOx \
#          --hours 72 -o AME_Milan.csv
#
#   tool          script                what it does
#   ----------    -------------------   -----------------------------------------
#   reduce        reduce_output.py      sum the output steps into one footprint per
#                                       release — do this first
#   footprint     plot_footprint.py     mean source-receptor map over a time window
#   source-map    plot_source_map.py    map of where a measured concentration came from
#   time-over     time_over.py          residence time over a static surface field
#   ame           ame_timeseries.py     exposure to a time-varying emission field
#   som           som_regimes.py        transport regimes from a self-organising map
#
# Relative paths are resolved from the directory you submit in, so submit from the
# directory holding flxout/header (usually somewhere on /scratch) and point AS_ROOT
# at this repository's analysis_scripts directory. Output files land beside you.
#
#=====================================================================================
#SBATCH --job-name=fpanalysis
#SBATCH --partition=small
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=0
#SBATCH --time=72:00:00
#SBATCH --output=fpanalysis_%j.out
#SBATCH --error=fpanalysis_%j.err

#--------------------------------- CONFIGURATION -------------------------------------
# Where the python scripts live. The scripts are in the repository (/projappl or
# $HOME) while the data is on /scratch, so there is no sensible relative default:
# either submit from analysis_scripts/, or export AS_ROOT before submitting.
#
# Note that Slurm stages this file into a spool directory before running it, so the
# script cannot work out its own location — this variable is how it is told.
AS_ROOT="${AS_ROOT:-${SLURM_SUBMIT_DIR:-$PWD}}"

# Python. python-data carries numpy, xarray, netCDF4, dask, pandas, matplotlib and
# cartopy. minisom (for som_regimes.py) is not in it — install it into a venv and
# point AS_VENV at that, or:  pip install --user minisom
AS_PYTHON_MODULE="${AS_PYTHON_MODULE:-python-data}"
AS_VENV="${AS_VENV:-}"

# Cartopy downloads Natural Earth coastlines on first use and caches them here. Fill
# the cache once on the login node (see the warning this script prints) if the
# compute nodes cannot reach the internet.
export CARTOPY_DATA_DIR="${CARTOPY_DATA_DIR:-$HOME/.local/share/cartopy}"
#-------------------------------------------------------------------------------------

set -o pipefail
cd "${SLURM_SUBMIT_DIR:-$PWD}"

usage() {
  awk 'NR>2 && /^#={10,}/ {exit} NR>2 {sub(/^# ?/, ""); print}' "$0"
  echo
  echo "Run any tool's own --help for its full flag list, e.g.:"
  echo "    AS_ROOT=. bash run_analysis.slurm footprint --help"
}

# --- pick the tool --------------------------------------------------------------------
TOOL="${1:-}"
case "$TOOL" in
  -h|--help|help) usage; exit 0 ;;
  "")             usage >&2; exit 1 ;;
esac
shift

case "$TOOL" in
  reduce|reduce_output|reduce_output.py)          SCRIPT=reduce_output.py  ; NEEDS="" ;;
  footprint|plot_footprint|plot_footprint.py)     SCRIPT=plot_footprint.py ; NEEDS="cartopy" ;;
  source-map|sourcemap|plot_source_map|plot_source_map.py)
                                                  SCRIPT=plot_source_map.py; NEEDS="cartopy" ;;
  time-over|time_over|time_over.py)               SCRIPT=time_over.py      ; NEEDS="" ;;
  ame|ame_timeseries|ame_timeseries.py)           SCRIPT=ame_timeseries.py ; NEEDS="" ;;
  som|som_regimes|som_regimes.py)                 SCRIPT=som_regimes.py    ; NEEDS="cartopy minisom sklearn" ;;
  *)
    echo "ERROR: unknown tool '$TOOL'." >&2
    echo >&2
    usage >&2
    exit 1 ;;
esac

if [ "$#" -eq 0 ]; then
  echo "ERROR: '$TOOL' needs at least an input file — nothing was passed to $SCRIPT." >&2
  echo "       sbatch --account=project_XXXXXXX $(basename "$0") $TOOL <input.nc> [flags...]" >&2
  exit 1
fi

# --- environment ------------------------------------------------------------------------
# Unlike the model components there is nothing compiled here, so the modules are loaded
# inline rather than from a roihu_env.sh: one python module, optionally a venv on top.
if command -v module >/dev/null 2>&1; then
  module purge 2>/dev/null
  module load "$AS_PYTHON_MODULE" || {
    echo "ERROR: 'module load $AS_PYTHON_MODULE' failed." >&2
    echo "       Check what exists with:  module spider python-data" >&2
    echo "       and override with AS_PYTHON_MODULE=<name>, or set AS_VENV to a venv" >&2
    echo "       that already has numpy, xarray, netCDF4, dask, pandas, matplotlib" >&2
    echo "       and cartopy." >&2
    exit 1
  }
else
  echo "note: no 'module' command — using whatever python3 is on PATH." >&2
fi

if [ -n "$AS_VENV" ]; then
  [ -f "$AS_VENV/bin/activate" ] || {
    echo "ERROR: no virtual environment at $AS_VENV (bin/activate not found)." >&2; exit 1; }
  # shellcheck disable=SC1090
  source "$AS_VENV/bin/activate" || { echo "ERROR: cannot activate $AS_VENV" >&2; exit 1; }
fi

# The plotting scripts already force the Agg backend; this covers anything matplotlib
# does before they get the chance, on a node with no display.
export MPLBACKEND="${MPLBACKEND:-Agg}"
export MPLCONFIGDIR="${MPLCONFIGDIR:-$HOME/.cache/matplotlib}"
mkdir -p "$MPLCONFIGDIR"

# numpy/dask otherwise start one thread per core on the whole node, not per allocated
# core, and the oversubscription makes these jobs slower, not faster.
NTHREADS="${SLURM_CPUS_PER_TASK:-1}"
export OMP_NUM_THREADS="$NTHREADS"
export OPENBLAS_NUM_THREADS="$NTHREADS"
export MKL_NUM_THREADS="$NTHREADS"
export NUMEXPR_NUM_THREADS="$NTHREADS"

TOOLPATH="$AS_ROOT/$SCRIPT"

echo "=============================================================================="
echo " analysis_scripts   job ${SLURM_JOB_ID:-interactive} on $(hostname)"
echo " start        : $(date)"
echo " workdir      : $PWD"
echo " tool         : $TOOL  ->  $TOOLPATH"
echo " arguments    : $*"
echo " python       : $(command -v python3 || echo MISSING)  [$(python3 -V 2>&1)]"
echo " venv         : ${VIRTUAL_ENV:-none}"
echo " threads      : $NTHREADS"
echo "=============================================================================="

# --- checks that are cheap now and confusing an hour in ---------------------------------
[ -f "$TOOLPATH" ] || {
  echo "ERROR: $TOOLPATH not found." >&2
  echo "       AS_ROOT must point at the repository's analysis_scripts directory." >&2
  echo "       Either submit from there, or:" >&2
  echo "           sbatch --account=project_XXXXXXX --export=ALL,AS_ROOT=/path/to/analysis_scripts \\" >&2
  echo "                  /path/to/analysis_scripts/$(basename "$0") $TOOL ..." >&2
  exit 1
}

command -v python3 >/dev/null 2>&1 || { echo "ERROR: no python3 on PATH." >&2; exit 1; }

missing=""
for m in numpy xarray netCDF4 dask pandas matplotlib $NEEDS; do
  python3 -c "import $m" 2>/dev/null || missing="$missing $m"
done
if [ -n "$missing" ]; then
  echo "ERROR: python cannot import:$missing" >&2
  echo "       Install them into a venv and pass it with AS_VENV, e.g." >&2
  echo "           python3 -m venv --system-site-packages \$HOME/fp_analysis_venv" >&2
  echo "           source \$HOME/fp_analysis_venv/bin/activate" >&2
  echo "           pip install$(echo "$missing" | sed 's/sklearn/scikit-learn/')" >&2
  echo "       (som_regimes.py needs minisom and scikit-learn; the map plots need cartopy.)" >&2
  exit 1
fi

# Cartopy fetches its coastlines over the network the first time it draws them, which
# fails on a compute node with no route out — and only after the analysis is finished.
case "$NEEDS" in
  *cartopy*)
    ne="$CARTOPY_DATA_DIR/shapefiles/natural_earth"
    absent=""
    for f in physical/ne_50m_coastline.shp physical/ne_50m_land.shp \
             physical/ne_50m_ocean.shp physical/ne_10m_coastline.shp \
             cultural/ne_50m_admin_0_boundary_lines_land.shp \
             cultural/ne_10m_admin_0_boundary_lines_land.shp; do
      [ -f "$ne/$f" ] || absent="$absent $(basename "$f")"
    done
    if [ -n "$absent" ]; then
      echo "WARNING: $CARTOPY_DATA_DIR is missing:$absent" >&2
      echo "         The maps use the 10m shapes for domains narrower than 15 degrees" >&2
      echo "         and the 50m ones otherwise. If this job dies while plotting, fill" >&2
      echo "         the cache once from the login node, which has the network, and" >&2
      echo "         resubmit:" >&2
      echo "             module load $AS_PYTHON_MODULE" >&2
      echo "             export CARTOPY_DATA_DIR=$CARTOPY_DATA_DIR" >&2
      echo "             python3 -c \"from cartopy.io import shapereader as s; [s.natural_earth(resolution=r, category=c, name=n) for r in ('10m','50m') for c, n in (('physical','coastline'), ('physical','land'), ('physical','ocean'), ('cultural','admin_0_boundary_lines_land'))]\"" >&2
    fi ;;
esac

# --- run ----------------------------------------------------------------------------------
# srun inside the allocation, so the job step is accounted and bound to the cores it
# was given; plain python if this file is being run by hand outside Slurm.
if [ -n "${SLURM_JOB_ID:-}" ] && command -v srun >/dev/null 2>&1; then
  srun python3 "$TOOLPATH" "$@"
else
  python3 "$TOOLPATH" "$@"
fi
rc=$?

echo "=============================================================================="
echo " end: $(date)   exit code: $rc"
echo " output in: $PWD"
echo "=============================================================================="
exit $rc
