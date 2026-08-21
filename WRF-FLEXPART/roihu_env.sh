#!/bin/bash
#=====================================================================================
# FLEXPART-WRF v3.3.2 — build & run environment for Roihu (CSC)
#
# SOURCE it, do NOT execute it:
#       source ./roihu_env.sh
#
# It is sourced by compile_roihu.sh and by the Slurm scripts in run/, so the modules
# used at run time are guaranteed identical to the ones used at build time. That is
# why no LD_LIBRARY_PATH has to be hard-coded anywhere.
#
# Escape hatch for testing off Roihu (e.g. on a laptop with a system gfortran):
#       FLEXWRF_SKIP_MODULES=1 source ./roihu_env.sh
#=====================================================================================

# --- Roihu module stack (x86_64 CPU side, Spack v2026_03) ----------------------------
# Roihu is architecturally split. The CPU login node and the CPU partitions (test,
# interactive, small, medium, large, longrun, hugemem) are x86_64 and their stack is
# built against gcc/15.2.0. The GPU login node and gpu* partitions are aarch64 (Grace)
# and use gcc/14.3.0. Binaries do NOT run across the two ("Exec format error"), and
# loading the wrong gcc makes the modules below unloadable (no mpif90).
FLEXWRF_GCC=${FLEXWRF_GCC:-gcc/15.2.0}
FLEXWRF_MODULES=${FLEXWRF_MODULES:-"openmpi/5.0.10 hdf5/1.14.6 netcdf-c/4.9.3 netcdf-fortran/4.6.2"}

if [ -z "${FLEXWRF_SKIP_MODULES:-}" ]; then

  if [ "$(uname -m)" != "x86_64" ]; then
    echo "ERROR: this is a $(uname -m) node ($(hostname))." >&2
    echo "       FLEXPART-WRF here is built for the x86_64 CPU side of Roihu." >&2
    echo "       Log in to roihu-cpu.csc.fi and build there, or override the stack with" >&2
    echo "       FLEXWRF_GCC=gcc/14.3.0 before sourcing this file." >&2
    return 1 2>/dev/null || exit 1
  fi

  if ! command -v module >/dev/null 2>&1; then
    echo "ERROR: no 'module' command — are you on Roihu?" >&2
    echo "       To build elsewhere: FLEXWRF_SKIP_MODULES=1 source ./roihu_env.sh" >&2
    return 1 2>/dev/null || exit 1
  fi

  module purge
  module load $FLEXWRF_GCC $FLEXWRF_MODULES || {
    echo "ERROR: 'module load $FLEXWRF_GCC $FLEXWRF_MODULES' failed." >&2
    echo "       Check versions with: module spider netcdf-fortran" >&2
    return 1 2>/dev/null || exit 1
  }
fi

# --- big static arrays: FLEXPART-WRF needs an unlimited stack -------------------------
ulimit -s unlimited 2>/dev/null

# --- netCDF flags ---------------------------------------------------------------------
# Roihu ships netcdf-c and netcdf-fortran as SEPARATE Spack prefixes, so the upstream
# makefile.mom assumption of one $NETCDF prefix holding both is wrong here. nf-config
# knows about both: --flibs already emits -lnetcdff AND -lnetcdf with the right -L.
if command -v nf-config >/dev/null 2>&1; then
  export NC_FFLAGS="$(nf-config --fflags)"
  export NC_FLIBS="$(nf-config --flibs)"
elif command -v nc-config >/dev/null 2>&1; then
  _ncp="$(nc-config --prefix)"
  _nclib="$_ncp/lib"; [ -d "$_ncp/lib64" ] && _nclib="$_ncp/lib64"
  export NC_FFLAGS="-I$_ncp/include"
  export NC_FLIBS="-L$_nclib -lnetcdff -lnetcdf"
  echo "WARNING: nf-config not found, guessed netCDF flags from nc-config." >&2
else
  echo "ERROR: neither nf-config nor nc-config on PATH — netcdf-fortran not loaded?" >&2
  return 1 2>/dev/null || exit 1
fi

# --- report (ends up in every build and job log) ---------------------------------------
echo "---------------------------------------------------------------- roihu_env.sh"
echo " host / arch : $(hostname) / $(uname -m)"
echo " gfortran    : $(command -v gfortran || echo MISSING)  [$(gfortran -dumpversion 2>/dev/null)]"
echo " mpif90      : $(command -v mpif90 || echo MISSING)"
echo " NC_FFLAGS   : $NC_FFLAGS"
echo " NC_FLIBS    : $NC_FLIBS"
echo "------------------------------------------------------------------------------"
