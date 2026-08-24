#!/bin/bash
#=====================================================================================
# flex_extract 7.1.3 — install & run environment for Roihu (CSC)
#
# SOURCE it, do NOT execute it:
#       source ./roihu_env.sh
#
# It is sourced by setup_roihu.sh and by Run/run_flex_extract.slurm, so the ecCodes
# that compiles calc_etadot is the same one the python bindings use at run time —
# which is exactly the mismatch that produces "ImportError: libeccodes.so" halfway
# through a retrieval.
#
# It needs a python virtual environment with the flex_extract dependencies; see
# README section 2. Point it somewhere else with:
#       FE_VENV=/path/to/venv source ./roihu_env.sh
#
# Escape hatch for testing off Roihu:
#       FE_SKIP_MODULES=1 source ./roihu_env.sh
#=====================================================================================

# --- Roihu module stack (x86_64 CPU side) ---------------------------------------------
# Same gcc as FLEXPART v11, so calc_etadot and FLEXPART agree about GRIB. ecCodes is
# left unversioned; pin it with FE_ECCODES if you need a specific one.
FE_GCC=${FE_GCC:-gcc/15.2.0}
FE_ECCODES=${FE_ECCODES:-eccodes}
FE_PYTHON=${FE_PYTHON:-python-data}
FE_VENV=${FE_VENV:-$HOME/flex_extract_venv}

if [ -z "${FE_SKIP_MODULES:-}" ]; then

  if ! command -v module >/dev/null 2>&1; then
    echo "ERROR: no 'module' command — are you on Roihu?" >&2
    echo "       To work elsewhere: FE_SKIP_MODULES=1 source ./roihu_env.sh" >&2
    return 1 2>/dev/null || exit 1
  fi

  module purge
  module load $FE_GCC $FE_ECCODES || {
    echo "ERROR: 'module load $FE_GCC $FE_ECCODES' failed." >&2
    echo "       Check with: module spider eccodes" >&2
    return 1 2>/dev/null || exit 1
  }
  # python-data carries numpy and friends; harmless if the venv shadows it.
  module load $FE_PYTHON 2>/dev/null || \
    echo "note: module '$FE_PYTHON' not available; relying on the venv alone." >&2
fi

# --- ecCodes prefix, for makefile_roihu -----------------------------------------------
# ecCodes ships no *-config script, so take whatever the module exports and fall back
# to the location of codes_info.
_ecp="${ECCODES_DIR:-${ECCODES_ROOT:-${ECCODES_INSTALL_ROOT:-}}}"
if [ -z "$_ecp" ] && command -v codes_info >/dev/null 2>&1; then
  _ecp="$(cd "$(dirname "$(command -v codes_info)")/.." && pwd)"
fi
if [ -n "$_ecp" ] && [ -d "$_ecp" ]; then
  export ECCODES_PREFIX="$_ecp"
  export ECCODES_INCLUDE_DIR="$_ecp/include"
  if [ -d "$_ecp/lib64" ]; then export ECCODES_LIB_DIR="$_ecp/lib64"
  else                          export ECCODES_LIB_DIR="$_ecp/lib"; fi
else
  echo "ERROR: cannot locate ecCodes (no ECCODES_DIR/ECCODES_ROOT and no codes_info" >&2
  echo "       on PATH). calc_etadot cannot be built without it." >&2
  return 1 2>/dev/null || exit 1
fi
unset _ecp

# --- python virtual environment --------------------------------------------------------
if [ -f "$FE_VENV/bin/activate" ]; then
  # shellcheck disable=SC1090
  source "$FE_VENV/bin/activate"
else
  echo "WARNING: no virtual environment at $FE_VENV." >&2
  echo "         flex_extract needs cdsapi, ecmwf-api-client, genshi, numpy and the" >&2
  echo "         eccodes python bindings — see README.md section 2. Continuing with" >&2
  echo "         whatever python is on PATH." >&2
fi

# --- report (ends up in every install and job log) ---------------------------------------
echo "---------------------------------------------------------------- roihu_env.sh"
echo " host / arch  : $(hostname) / $(uname -m)"
echo " gfortran     : $(command -v gfortran || echo MISSING)  [$(gfortran -dumpversion 2>/dev/null)]"
echo " python       : $(command -v python3 || echo MISSING)  [$(python3 -V 2>&1)]"
echo " ecCodes      : $ECCODES_PREFIX"
echo " venv         : ${VIRTUAL_ENV:-none}"
for _m in eccodes cdsapi ecmwfapi genshi numpy; do
  if python3 -c "import $_m" 2>/dev/null; then _s="ok"; else _s="MISSING"; fi
  printf " %-12s : %s\n" "py:$_m" "$_s"
done
unset _m _s
echo "------------------------------------------------------------------------------"
