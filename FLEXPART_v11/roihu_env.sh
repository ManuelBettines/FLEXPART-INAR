#!/bin/bash
#=====================================================================================
# FLEXPART v11 — build & run environment for Roihu (CSC)
#
# SOURCE it, do NOT execute it:
#       source ./roihu_env.sh
#
# It is sourced by compile_roihu.sh and by the Slurm scripts in run/, so the modules
# used at run time are guaranteed identical to the ones used at build time. That is
# why no LD_LIBRARY_PATH has to be hard-coded anywhere (the old Puhti launch script
# in local_reference/ needed a 300-character one; this replaces it).
#
# Escape hatch for testing off Roihu (e.g. on a laptop with a system gfortran,
# libeccodes-dev and libnetcdff-dev):
#       FP11_SKIP_MODULES=1 source ./roihu_env.sh
#=====================================================================================

# --- Roihu module stack (x86_64 CPU side, Spack v2026_03) ----------------------------
# Roihu is architecturally split: the CPU login node and the CPU partitions (test,
# interactive, small, medium, large, longrun, hugemem) are x86_64 with a gcc/15.2.0
# stack; the GPU side is aarch64 (Grace) with gcc/14.3.0. Binaries do not run across
# the two ("Exec format error"). This is the same stack WRF-FLEXPART uses, plus
# ecCodes, which FLEXPART v11 needs for GRIB input and FLEXPART-WRF does not.
#
# openmpi is loaded even though FLEXPART v11 has NO MPI code (see README section 3):
# Roihu's netcdf-c/hdf5 are built against it, so it has to be in the stack to link.
#
# ecCodes is deliberately left unversioned — pin it with FP11_ECCODES if a specific
# version is needed, and check what exists with:  module spider eccodes
FP11_GCC=${FP11_GCC:-gcc/15.2.0}
FP11_ECCODES=${FP11_ECCODES:-eccodes}
FP11_MODULES=${FP11_MODULES:-"openmpi/5.0.10 hdf5/1.14.6 netcdf-c/4.9.3 netcdf-fortran/4.6.2"}

if [ -z "${FP11_SKIP_MODULES:-}" ]; then

  if [ "$(uname -m)" != "x86_64" ]; then
    echo "ERROR: this is a $(uname -m) node ($(hostname))." >&2
    echo "       FLEXPART v11 here is built for the x86_64 CPU side of Roihu." >&2
    echo "       Log in to roihu-cpu.csc.fi and build there, or override the stack" >&2
    echo "       with FP11_GCC=gcc/14.3.0 before sourcing this file." >&2
    return 1 2>/dev/null || exit 1
  fi

  if ! command -v module >/dev/null 2>&1; then
    echo "ERROR: no 'module' command — are you on Roihu?" >&2
    echo "       To build elsewhere: FP11_SKIP_MODULES=1 source ./roihu_env.sh" >&2
    return 1 2>/dev/null || exit 1
  fi

  module purge
  module load $FP11_GCC $FP11_MODULES $FP11_ECCODES || {
    echo "ERROR: 'module load $FP11_GCC $FP11_MODULES $FP11_ECCODES' failed." >&2
    echo "       Check the available versions with:" >&2
    echo "           module spider netcdf-fortran" >&2
    echo "           module spider eccodes" >&2
    echo "       and override with FP11_ECCODES=eccodes/<version>." >&2
    return 1 2>/dev/null || exit 1
  }
fi

# --- big static arrays and OpenMP thread stacks ---------------------------------------
# FLEXPART v11 allocates most things on the heap, but the per-thread private arrays in
# the turbulence/interpolation loops still overflow a default 8 MB thread stack.
ulimit -s unlimited 2>/dev/null
export OMP_STACKSIZE="${OMP_STACKSIZE:-512M}"
# The makefile also exports this; FLEXPART's own OpenMP regions are not nested.
export OMP_NESTED=FALSE

# --- netCDF flags ---------------------------------------------------------------------
# Roihu ships netcdf-c and netcdf-fortran as SEPARATE Spack prefixes, so the upstream
# makefile assumption of one prefix (or of CPATH/LIBRARY_PATH being set for you) does
# not hold. nf-config knows about both: --flibs emits -lnetcdff AND -lnetcdf with the
# right -L.
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

# --- ecCodes flags ---------------------------------------------------------------------
# ecCodes ships no *-config script, so the prefix is taken from whichever of these the
# module happens to set, and from codes_info as a last resort. -leccodes_f90 is the
# Fortran interface; -leccodes is the C library underneath it. Both are needed.
_ecp="${ECCODES_DIR:-${ECCODES_ROOT:-${ECCODES_INSTALL_ROOT:-}}}"
if [ -z "$_ecp" ] && command -v codes_info >/dev/null 2>&1; then
  _ecp="$(cd "$(dirname "$(command -v codes_info)")/.." && pwd)"
fi
if [ -n "$_ecp" ] && [ -d "$_ecp" ]; then
  _eclib="$_ecp/lib"; [ -d "$_ecp/lib64" ] && _eclib="$_ecp/lib64"
  export EC_FFLAGS="-I$_ecp/include"
  export EC_FLIBS="-L$_eclib -Wl,-rpath=$_eclib -leccodes_f90 -leccodes"
else
  echo "ERROR: cannot locate ecCodes (no ECCODES_DIR/ECCODES_ROOT and no codes_info" >&2
  echo "       on PATH). FLEXPART v11 cannot read GRIB without it." >&2
  echo "       Load it by hand and re-source, or set ECCODES_DIR=/path/to/eccodes." >&2
  return 1 2>/dev/null || exit 1
fi
unset _ecp _eclib _ncp _nclib

# --- report (ends up in every build and job log) ---------------------------------------
echo "---------------------------------------------------------------- roihu_env.sh"
echo " host / arch : $(hostname) / $(uname -m)"
echo " gfortran    : $(command -v gfortran || echo MISSING)  [$(gfortran -dumpversion 2>/dev/null)]"
echo " codes_info  : $(command -v codes_info || echo MISSING)"
echo " NC_FFLAGS   : $NC_FFLAGS"
echo " NC_FLIBS    : $NC_FLIBS"
echo " EC_FFLAGS   : $EC_FFLAGS"
echo " EC_FLIBS    : $EC_FLIBS"
echo "------------------------------------------------------------------------------"
