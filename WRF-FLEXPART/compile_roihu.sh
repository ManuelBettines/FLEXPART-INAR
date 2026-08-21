#!/bin/bash
#=====================================================================================
# compile_roihu.sh — build FLEXPART-WRF v3.3.2 on Roihu (CSC)
#
#   ./compile_roihu.sh                 # build all three flavours (serial, omp, mpi)
#   ./compile_roihu.sh omp             # build only the OpenMP one
#   ./compile_roihu.sh mpi serial      # build a subset
#   ./compile_roihu.sh all -j 16       # choose the number of parallel make jobs
#   ./compile_roihu.sh omp --clean     # wipe that flavour's build dir first
#
# Run it on the Roihu **x86_64 CPU login node** (roihu-cpu.csc.fi). It takes a few
# minutes and is small enough for a login node; if you prefer a batch job use
# `sbatch compile_roihu.slurm`, which just calls this script.
#
# Off Roihu (e.g. to test the build logic on a laptop with a system gfortran):
#   FLEXWRF_SKIP_MODULES=1 ./compile_roihu.sh all
#
# Each flavour is built in its OWN directory under build/. That is not cosmetic:
# the makefile links with `$(FC) *.o`, so serial, omp and mpi objects sharing one
# directory silently produce a mixed, broken binary.
#=====================================================================================
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$ROOT/src"
MAKEFILE="$ROOT/makefile.roihu"
BUILD="$ROOT/build"
BIN="$ROOT/bin"

# ---- arguments ----------------------------------------------------------------------
FLAVOURS=()
JOBS="${J:-8}"
DO_CLEAN=0

while [ $# -gt 0 ]; do
  case "$1" in
    serial|omp|mpi) FLAVOURS+=("$1"); shift ;;
    all)            FLAVOURS+=(serial omp mpi); shift ;;
    -j)             JOBS="$2"; shift 2 ;;
    -j*)            JOBS="${1#-j}"; shift ;;
    --clean)        DO_CLEAN=1; shift ;;
    -h|--help)      sed -n '2,25p' "${BASH_SOURCE[0]}" | sed 's/^#//'; exit 0 ;;
    *)              echo "Unknown argument: $1  (try --help)" >&2; exit 2 ;;
  esac
done
[ ${#FLAVOURS[@]} -eq 0 ] && FLAVOURS=(serial omp mpi)

# ---- environment ---------------------------------------------------------------------
# shellcheck source=roihu_env.sh
source "$ROOT/roihu_env.sh" || { echo "ERROR: roihu_env.sh failed — build aborted." >&2; exit 1; }

[ -d "$SRC" ]      || { echo "ERROR: no source directory at $SRC" >&2; exit 1; }
[ -f "$MAKEFILE" ] || { echo "ERROR: no $MAKEFILE" >&2; exit 1; }

mkdir -p "$BIN"

# ---- build ----------------------------------------------------------------------------
declare -a RESULT_NAME RESULT_CODE RESULT_BIN
FAILED=0

for flavour in "${FLAVOURS[@]}"; do
  bdir="$BUILD/$flavour"
  log="$BUILD/build_${flavour}.log"

  echo
  echo "=============================================================================="
  echo " Building flexwrf33_gnu_${flavour}   (make -j${JOBS})"
  echo "=============================================================================="

  [ "$DO_CLEAN" -eq 1 ] && rm -rf "$bdir"
  mkdir -p "$bdir"

  # Populate the build dir with symlinks to the sources — no copies to drift, and the
  # source tree stays free of .o/.mod files.
  ( cd "$bdir" && find . -maxdepth 1 -type l -delete )
  for f in "$SRC"/*.f90 "$SRC"/*.F90 "$SRC"/*.f; do
    [ -e "$f" ] && ln -sf "$f" "$bdir/"
  done
  cp -f "$MAKEFILE" "$bdir/makefile.roihu"

  ( cd "$bdir" && make -f makefile.roihu "$flavour" -j"$JOBS" ) 2>&1 | tee "$log"
  rc=${PIPESTATUS[0]}

  produced="$bdir/flexwrf33_gnu_${flavour}"
  if [ "$rc" -eq 0 ] && [ -x "$produced" ]; then
    cp -f "$produced" "$BIN/"
    RESULT_BIN+=("$BIN/flexwrf33_gnu_${flavour}")
  else
    rc=${rc:-1}; [ "$rc" -eq 0 ] && rc=1     # make succeeded but no binary -> failure
    FAILED=1
    RESULT_BIN+=("-")
  fi
  RESULT_NAME+=("$flavour")
  RESULT_CODE+=("$rc")
done

# ---- summary ---------------------------------------------------------------------------
echo
echo "=============================================================================="
echo " BUILD SUMMARY"
echo "=============================================================================="
printf " %-8s %-8s %s\n" "FLAVOUR" "STATUS" "BINARY"
for i in "${!RESULT_NAME[@]}"; do
  if [ "${RESULT_CODE[$i]}" -eq 0 ]; then
    printf " %-8s %-8s %s (%s)\n" "${RESULT_NAME[$i]}" "OK" "${RESULT_BIN[$i]}" \
           "$(du -h "${RESULT_BIN[$i]}" 2>/dev/null | cut -f1)"
  else
    printf " %-8s %-8s see %s\n" "${RESULT_NAME[$i]}" "FAILED" \
           "$BUILD/build_${RESULT_NAME[$i]}.log"
  fi
done

# Prove the dynamic libraries (netCDF, MPI, OpenMP) actually resolve.
for b in "${RESULT_BIN[@]}"; do
  [ "$b" = "-" ] && continue
  if ldd "$b" 2>/dev/null | grep -q "not found"; then
    echo
    echo " WARNING: unresolved libraries in $b:"
    ldd "$b" | grep "not found"
    echo " -> load the same modules at run time (the run/ scripts source roihu_env.sh)."
    FAILED=1
  fi
done

echo
if [ "$FAILED" -eq 0 ]; then
  echo " All requested flavours built. Binaries are in $BIN/"
  echo " Next: see README.md -> 'Preparing a run' and run/run_flexwrf_omp.slurm"
else
  echo " At least one flavour FAILED — check the logs above before running anything."
fi
echo "=============================================================================="
exit "$FAILED"
