#!/bin/bash
#=====================================================================================
# compile_roihu.sh — build FLEXPART v11 on Roihu (CSC)
#
#   ./compile_roihu.sh                 # build the two netCDF flavours (eta, meter)
#   ./compile_roihu.sh eta             # build only FLEXPART_ETA (the usual choice)
#   ./compile_roihu.sh all             # eta, meter, eta_bin, meter_bin
#   ./compile_roihu.sh all -j 16       # choose the number of parallel make jobs
#   ./compile_roihu.sh eta --clean     # wipe that flavour's build dir first
#   ./compile_roihu.sh eta --debug     # -O0 -g -fbacktrace build (binary gets _dbg)
#
# Run it on the Roihu **x86_64 CPU login node** (roihu-cpu.csc.fi). It takes a few
# minutes and is small enough for a login node; if you prefer a batch job use
# `sbatch compile_roihu.slurm`, which just calls this script.
#
# Off Roihu (e.g. to test the build logic on a laptop with a system gfortran,
# libeccodes-dev and libnetcdff-dev):
#   FP11_SKIP_MODULES=1 ./compile_roihu.sh eta
#
# Each flavour is built in its OWN directory under build/. That is not cosmetic: the
# eta and metre-coordinate builds compile the SAME sources with different -D flags,
# so sharing one directory silently links a mixture of the two and the run dies in
# verttransform with nonsense heights.
#=====================================================================================
set -o pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$ROOT/src"
MAKEFILE="$ROOT/makefile.roihu"
BUILD="$ROOT/build"
BIN="$ROOT/bin"

# flavour -> "make variables" and the executable name the makefile produces
flavour_makeargs() {
  case "$1" in
    eta)       echo "eta=yes ncf=yes" ;;
    meter)     echo "eta=no  ncf=yes" ;;
    eta_bin)   echo "eta=yes ncf=no"  ;;
    meter_bin) echo "eta=no  ncf=no"  ;;
  esac
}
flavour_exe() {
  case "$1" in
    eta)       echo "FLEXPART_ETA" ;;
    meter)     echo "FLEXPART" ;;
    eta_bin)   echo "FLEXPART_ETA_BIN" ;;
    meter_bin) echo "FLEXPART_BIN" ;;
  esac
}

# ---- arguments ----------------------------------------------------------------------
FLAVOURS=()
JOBS="${J:-8}"
DO_CLEAN=0
EXTRA_ARGS=()
SUFFIX=""

while [ $# -gt 0 ]; do
  case "$1" in
    eta|meter|eta_bin|meter_bin) FLAVOURS+=("$1"); shift ;;
    all)         FLAVOURS+=(eta meter eta_bin meter_bin); shift ;;
    -j)          JOBS="$2"; shift 2 ;;
    -j*)         JOBS="${1#-j}"; shift ;;
    --clean)     DO_CLEAN=1; shift ;;
    --debug)     EXTRA_ARGS+=(DEBUG=yes); SUFFIX="_dbg"; shift ;;
    --serial)    EXTRA_ARGS+=(SERIAL=yes); SUFFIX="${SUFFIX}_serial"; shift ;;
    --arch)      EXTRA_ARGS+=("arch=$2"); shift 2 ;;
    -h|--help)   sed -n '2,25p' "${BASH_SOURCE[0]}" | sed 's/^#//'; exit 0 ;;
    *)           echo "Unknown argument: $1  (try --help)" >&2; exit 2 ;;
  esac
done
[ ${#FLAVOURS[@]} -eq 0 ] && FLAVOURS=(eta meter)

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
  bdir="$BUILD/$flavour$SUFFIX"
  log="$BUILD/build_${flavour}${SUFFIX}.log"
  exe="$(flavour_exe "$flavour")"
  read -r -a margs <<< "$(flavour_makeargs "$flavour")"

  echo
  echo "=============================================================================="
  echo " Building $exe$SUFFIX   (${margs[*]} ${EXTRA_ARGS[*]}, make -j${JOBS})"
  echo "=============================================================================="

  [ "$DO_CLEAN" -eq 1 ] && rm -rf "$bdir"
  mkdir -p "$BUILD"
  mkdir -p "$bdir"

  # Populate the build dir with symlinks to the sources — no copies to drift, and the
  # source tree stays free of .o/.mod files. (The tree shipped here had 89 stale .o
  # and .mod files from a Puhti build committed into src/; they are gone, and this is
  # how they stay gone.)
  ( cd "$bdir" && find . -maxdepth 1 -type l -delete )
  for f in "$SRC"/*.f90 "$SRC"/*.F90; do
    [ -e "$f" ] && ln -sf "$f" "$bdir/"
  done
  cp -f "$MAKEFILE" "$bdir/makefile.roihu"

  ( cd "$bdir" && make -f makefile.roihu "${margs[@]}" "${EXTRA_ARGS[@]}" -j"$JOBS" ) 2>&1 | tee "$log"
  rc=${PIPESTATUS[0]}

  produced="$bdir/$exe"
  if [ "$rc" -eq 0 ] && [ -x "$produced" ]; then
    cp -f "$produced" "$BIN/$exe$SUFFIX"
    RESULT_BIN+=("$BIN/$exe$SUFFIX")
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
printf " %-10s %-8s %s\n" "FLAVOUR" "STATUS" "BINARY"
for i in "${!RESULT_NAME[@]}"; do
  if [ "${RESULT_CODE[$i]}" -eq 0 ]; then
    printf " %-10s %-8s %s (%s)\n" "${RESULT_NAME[$i]}" "OK" "${RESULT_BIN[$i]}" \
           "$(du -h "${RESULT_BIN[$i]}" 2>/dev/null | cut -f1)"
  else
    printf " %-10s %-8s see %s\n" "${RESULT_NAME[$i]}" "FAILED" \
           "$BUILD/build_${RESULT_NAME[$i]}${SUFFIX}.log"
  fi
done

# Prove the dynamic libraries (ecCodes, netCDF, OpenMP) actually resolve.
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
  echo " Next: see README.md -> 'Preparing a run' and run/run_flexpart.slurm"
else
  echo " At least one flavour FAILED — check the logs above before running anything."
fi
echo "=============================================================================="
exit "$FAILED"
