#!/usr/bin/env python3
"""Read a wrfout file's horizontal grid and convert lat/lon <-> FLEXPART grid metres.

FLEXPART-WRF expresses release boxes and the output grid either in degrees
(RELEASE_COORD / OUTGRID_COORD = 1) or in "grid metres" (= 0). Grid metres are

    x = xmet0 + dx * i ,  y = ymet0 + dy * j          (map_proj_wrf.f90:606)

with `xmet0 = ymet0 = 0` (gridcheck.f90:145) and `i, j` the ZERO-based index on the
**mother** domain's mass grid. So x = 0 is the centre of the south-west corner cell of
d01, and the domain spans 0 .. (nx-1)*dx.

Rather than reimplementing WRF's four map projections, this inverts the grid using the
XLONG/XLAT fields stored in the wrfout file itself: nearest grid point, then one Newton
step with the local Jacobian, which lands well inside a metre for the usual smooth
projections. The round-trip error is reported so you can see it.

Used by generate_releases.py; also runnable for a quick look at a file's grid:

    ./wrfgrid.py /scratch/.../wrfout_d01_2022-03-21_00:00:00 --ll 28.309 -16.499
"""
import math
import os
import re
import sys

NAME_RE = re.compile(r"_d(?P<domain>\d+)_")


def _need_netcdf4():
    try:
        import netCDF4  # noqa: F401
    except ImportError:
        raise SystemExit(
            "converting lat/lon to grid metres needs the python netCDF4 module "
            "(the XLONG/XLAT fields are read from the wrfout file).\n"
            "On CSC: module load python-data, or give the coordinates in grid "
            "metres instead.")
    return __import__("netCDF4")


def find_wrfout(path, pattern="wrfout_d*"):
    """Accept a wrfout file or a directory; from a directory take the lowest domain."""
    if os.path.isfile(path):
        return path
    if not os.path.isdir(path):
        raise SystemExit(f"no such file or directory: {path}")
    import glob
    files = sorted(glob.glob(os.path.join(path, pattern)))
    if not files:
        raise SystemExit(f"no files matching {pattern!r} in {path}")

    def domain(f):
        m = NAME_RE.search(os.path.basename(f))
        return int(m.group("domain")) if m else 99

    return min(files, key=lambda f: (domain(f), f))


class WrfGrid:
    """The horizontal grid of one wrfout file."""

    def __init__(self, path):
        netCDF4 = _need_netcdf4()
        import numpy as np

        self.path = path
        self.name = os.path.basename(path)
        m = NAME_RE.search(self.name)
        self.domain = int(m.group("domain")) if m else None
        try:
            ds = netCDF4.Dataset(path)
        except OSError as exc:
            raise SystemExit(f"cannot open {path}: {exc}")
        with ds:
            for var in ("XLONG", "XLAT"):
                if var not in ds.variables:
                    raise SystemExit(f"{path} has no {var} field")
            self.lon = np.asarray(ds.variables["XLONG"][0, :, :], dtype=float)
            self.lat = np.asarray(ds.variables["XLAT"][0, :, :], dtype=float)
            self.dx = float(getattr(ds, "DX"))
            self.dy = float(getattr(ds, "DY"))
            self.map_proj = int(getattr(ds, "MAP_PROJ", -1))
            self.parent_id = int(getattr(ds, "PARENT_ID", 0))
            self.grid_id = int(getattr(ds, "GRID_ID", self.domain or 1))
        self.ny, self.nx = self.lon.shape  # south_north, west_east

    # ------------------------------------------------------------------ geometry

    def describe(self):
        return (f"{self.name}: {self.nx} x {self.ny} points, dx = {self.dx:g} m, "
                f"dy = {self.dy:g} m, MAP_PROJ = {self.map_proj}, "
                f"corners {self.lat[0, 0]:.3f}N {self.lon[0, 0]:.3f}E .. "
                f"{self.lat[-1, -1]:.3f}N {self.lon[-1, -1]:.3f}E")

    def is_mother(self):
        return self.grid_id == 1 or self.domain in (None, 1)

    def ll_to_ij(self, lon, lat):
        """Fractional zero-based (i, j) of a lat/lon on this grid."""
        import numpy as np

        dlon = (self.lon - lon + 180.0) % 360.0 - 180.0
        coslat = math.cos(math.radians(lat))
        d2 = (dlon * coslat) ** 2 + (self.lat - lat) ** 2
        j0, i0 = (int(v) for v in np.unravel_index(int(np.argmin(d2)), d2.shape))

        # one Newton step with the local Jacobian, using neighbours inside the grid
        ia, ib = max(i0 - 1, 0), min(i0 + 1, self.nx - 1)
        ja, jb = max(j0 - 1, 0), min(j0 + 1, self.ny - 1)
        if ib == ia or jb == ja:  # 1-point grid in some direction: nothing to refine
            return float(i0), float(j0)
        dlon_di = self._dlon(self.lon[j0, ib], self.lon[j0, ia]) / (ib - ia)
        dlat_di = (self.lat[j0, ib] - self.lat[j0, ia]) / (ib - ia)
        dlon_dj = self._dlon(self.lon[jb, i0], self.lon[ja, i0]) / (jb - ja)
        dlat_dj = (self.lat[jb, i0] - self.lat[ja, i0]) / (jb - ja)
        det = dlon_di * dlat_dj - dlon_dj * dlat_di
        if abs(det) < 1e-12:
            return float(i0), float(j0)
        rlon = self._dlon(lon, self.lon[j0, i0])
        rlat = lat - self.lat[j0, i0]
        di = (rlon * dlat_dj - rlat * dlon_dj) / det
        dj = (rlat * dlon_di - rlon * dlat_di) / det
        return i0 + di, j0 + dj

    @staticmethod
    def _dlon(a, b):
        return (a - b + 180.0) % 360.0 - 180.0

    def ij_to_ll(self, i, j):
        """Bilinear lat/lon of a fractional zero-based (i, j) -- used to check the fit."""
        i = min(max(i, 0.0), self.nx - 1.0)
        j = min(max(j, 0.0), self.ny - 1.0)
        i0, j0 = int(math.floor(i)), int(math.floor(j))
        i1, j1 = min(i0 + 1, self.nx - 1), min(j0 + 1, self.ny - 1)
        fi, fj = i - i0, j - j0
        base = self.lon[j0, i0]

        def blend(field, wrap=False):
            def val(jj, ii):
                v = field[jj, ii]
                return base + self._dlon(v, base) if wrap else v
            return ((1 - fi) * (1 - fj) * val(j0, i0) + fi * (1 - fj) * val(j0, i1)
                    + (1 - fi) * fj * val(j1, i0) + fi * fj * val(j1, i1))

        return blend(self.lon, wrap=True), blend(self.lat)

    def ll_to_xymeter(self, lon, lat):
        """FLEXPART grid metres (x, y) of a lat/lon, plus the round-trip error in m."""
        i, j = self.ll_to_ij(lon, lat)
        blon, blat = self.ij_to_ll(i, j)
        err = math.hypot((self._dlon(blon, lon)) * math.cos(math.radians(lat)),
                         blat - lat) * 111320.0
        return i * self.dx, j * self.dy, err

    def inside(self, i, j, grace=0.0):
        return -grace <= i <= self.nx - 1 + grace and -grace <= j <= self.ny - 1 + grace

    def extent_m(self):
        """(x_max, y_max): the largest grid-metre coordinates FLEXPART accepts."""
        return self.nx * self.dx, self.ny * self.dy


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("wrfout", help="a wrfout file, or a directory holding them")
    ap.add_argument("--ll", nargs=2, type=float, metavar=("LAT", "LON"),
                    help="convert this latitude/longitude to grid metres")
    a = ap.parse_args(argv)

    grid = WrfGrid(find_wrfout(a.wrfout))
    print(grid.describe())
    xmax, ymax = grid.extent_m()
    print(f"grid metres: x 0 .. {xmax:.0f}, y 0 .. {ymax:.0f}")
    if a.ll:
        lat, lon = a.ll
        x, y, err = grid.ll_to_xymeter(lon, lat)
        i, j = x / grid.dx, y / grid.dy
        print(f"{lat} N {lon} E -> x = {x:.1f} m, y = {y:.1f} m "
              f"(i = {i:.2f}, j = {j:.2f}, fit {err:.1f} m)")
        if not grid.inside(i, j):
            print("warning: that point is OUTSIDE this domain", file=sys.stderr)


if __name__ == "__main__":
    main()
