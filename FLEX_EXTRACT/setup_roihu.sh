#!/bin/bash
#=====================================================================================
# setup_roihu.sh — install flex_extract 7.1.3 on Roihu (CSC)
#
#   ./setup_roihu.sh                # install in place: build calc_etadot, check python
#   ./setup_roihu.sh --clean        # remove the previous build first
#   ./setup_roihu.sh --check        # only report the environment, install nothing
#
# This is the Roihu equivalent of the upstream setup_local_*.sh scripts, which name a
# makefile with hard-coded Puhti/Mahti library paths (and, in the case of
# makefile_local_gfortran, a hand-built emoslib under /projappl/project_2015087 that
# does not exist here). It sources roihu_env.sh, checks the python side, and then
# calls the same Source/Python/install.py the upstream scripts call — with
# --target=local and --makefile=makefile_roihu.
#
# "local" is the right target on Roihu: the retrieval runs HERE and pulls ERA5 from
# the Copernicus CDS over the network. The 'ecs'/'hpc' targets install flex_extract
# INSIDE ECMWF and need a member-state account and an ecaccess gateway; see README
# section 5 if you have MARS access and want that instead.
#
# Off Roihu (to test the logic on a laptop with gfortran + libeccodes-dev):
#   FE_SKIP_MODULES=1 ./setup_roihu.sh
#=====================================================================================
set -o pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MAKEFILE="makefile_roihu"
CONTROLFILE="${FE_CONTROLFILE:-CONTROL_EA5}"

DO_CLEAN=0
CHECK_ONLY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --clean)   DO_CLEAN=1; shift ;;
    --check)   CHECK_ONLY=1; shift ;;
    -h|--help) sed -n '2,24p' "${BASH_SOURCE[0]}" | sed 's/^#//'; exit 0 ;;
    *)         echo "Unknown argument: $1  (try --help)" >&2; exit 2 ;;
  esac
done

# ---- environment ---------------------------------------------------------------------
# shellcheck source=roihu_env.sh
source "$ROOT/roihu_env.sh" || { echo "ERROR: roihu_env.sh failed — install aborted." >&2; exit 1; }

# ---- python side ------------------------------------------------------------------------
# flex_extract fails deep inside a retrieval if one of these is missing, often after
# the MARS/CDS request has already been queued. Check up front.
MISSING=""
for m in eccodes cdsapi ecmwfapi genshi numpy; do
  python3 -c "import $m" 2>/dev/null || MISSING="$MISSING $m"
done
if [ -n "$MISSING" ]; then
  echo
  echo "ERROR: missing python module(s):$MISSING" >&2
  echo "       Create the virtual environment once (see README.md section 2):" >&2
  echo "         python3 -m venv \$HOME/flex_extract_venv" >&2
  echo "         source \$HOME/flex_extract_venv/bin/activate" >&2
  echo "         pip install cdsapi ecmwf-api-client genshi numpy eccodes" >&2
  echo "       then re-run this script." >&2
  [ "$CHECK_ONLY" -eq 1 ] || exit 1
fi

# ---- API credentials ---------------------------------------------------------------------
# Not fatal: you can install now and sort the keys out before the first retrieval.
[ -f "$HOME/.cdsapirc" ]  || echo "WARNING: no ~/.cdsapirc — ERA5 from the CDS will not work yet (README section 2)." >&2
[ -f "$HOME/.ecmwfapirc" ] || echo "note: no ~/.ecmwfapirc — only needed for MARS/member-state access." >&2

if [ "$CHECK_ONLY" -eq 1 ]; then
  echo
  echo "--check: environment reported above, nothing installed."
  exit 0
fi

# ---- build ---------------------------------------------------------------------------------
cd "$ROOT" || exit 1
[ -f "Source/Python/install.py" ] || { echo "ERROR: Source/Python/install.py not found — wrong directory?" >&2; exit 1; }
[ -f "Source/Fortran/$MAKEFILE" ] || { echo "ERROR: Source/Fortran/$MAKEFILE not found." >&2; exit 1; }

if [ "$DO_CLEAN" -eq 1 ]; then
  echo "cleaning the previous build ..."
  ( cd Source/Fortran && make -f "$MAKEFILE" clean )
fi

echo
echo "=============================================================================="
echo " Installing flex_extract (target=local, makefile=$MAKEFILE)"
echo "=============================================================================="

python3 Source/Python/install.py \
    --target=local \
    --makefile="$MAKEFILE" \
    --controlfile="$CONTROLFILE"
rc=$?

# ---- summary ---------------------------------------------------------------------------------
EXE="$ROOT/Source/Fortran/calc_etadot"
echo
echo "=============================================================================="
echo " INSTALL SUMMARY"
echo "=============================================================================="
if [ "$rc" -eq 0 ] && [ -x "$EXE" ]; then
  echo " calc_etadot : OK   $EXE -> $(readlink -f "$EXE" 2>/dev/null || echo "$EXE")"
  if ldd "$EXE" 2>/dev/null | grep -q "not found"; then
    echo " WARNING: unresolved libraries:"
    ldd "$EXE" | grep "not found"
    echo " -> source roihu_env.sh before running a retrieval."
    rc=1
  fi
  echo
  echo " Next: edit Run/Control/<your CONTROL file>, then"
  echo "         cd Run && sbatch --account=project_XXXXXXX run_flex_extract.slurm"
  echo "       or, for a long period, bash submit_chain.sh (see README section 4)."
else
  rc=${rc:-1}; [ "$rc" -eq 0 ] && rc=1
  echo " calc_etadot : FAILED — see the make output above."
  echo " Most likely ECCODES_INCLUDE_DIR / ECCODES_LIB_DIR are wrong; they came from"
  echo "   $ECCODES_PREFIX"
fi
echo "=============================================================================="
exit "$rc"
