"""Map geometry for perception (stdlib only).

Built once in the 20 s `ready` window (about 1-2 s of CPU). Provides:
  - ground(x, y)          bilinear terrain height
  - gblocked(x, y)        True where a ground mech cannot stand (buildings, steep slope, off map)
  - horizon(...)          per-direction line-of-sight distance from an eye point (lazy, cached by the caller)
  - los(a, b)             one segment LOS test (used by the test harness and by consumers)

Cells are `cell` metres square. Sight blockers are stored as a height interval per cell
([lo, hi] of the buildings/bridges covering it) and a second interval for tree crowns.
"""
import json
import math
import os
import sys
from array import array

INF = float("inf")


class Geom:
    def __init__(self, map_dir, cell=3.0, load_trees=True, slope_block=True):
        with open(os.path.join(map_dir, "v2", "world.json")) as f:
            world = json.load(f)
        tm = world["terrain"]
        self.t_minx, self.t_miny = tm["minX"], tm["minY"]
        self.t_step, self.t_nx, self.t_ny = tm["step"], tm["nx"], tm["ny"]
        raw = array("h")
        with open(os.path.join(map_dir, "v2", tm["file"]), "rb") as f:
            raw.frombytes(f.read())
        if sys.byteorder == "big":
            raw.byteswap()
        self.terrain = raw
        b = world["bounds"]
        self.minx, self.miny, self.maxx, self.maxy = b["minX"], b["minY"], b["maxX"], b["maxY"]
        self.cell = c = float(cell)
        self.nx = int((self.maxx - self.minx) / c) + 2
        self.ny = int((self.maxy - self.miny) / c) + 2
        n = self.nx * self.ny
        self.lo = [INF] * n          # sight blocker interval (buildings, bridges, stadium)
        self.hi = [-INF] * n
        self.tlo = [INF] * n         # tree crowns
        self.thi = [-INF] * n
        self.gb = bytearray(n)       # ground-blocked mask
        self._raster_prisms(world["prisms"])
        if load_trees:
            self._raster_trees(world["trees"])
        if slope_block:
            self._slope_mask()
        self._tables = {}

    # ---- terrain -------------------------------------------------------------------------
    def ground(self, x, y):
        fx = (x - self.t_minx) / self.t_step
        fy = (y - self.t_miny) / self.t_step
        i = int(fx)
        j = int(fy)
        if i < 0:
            i = 0
        elif i > self.t_nx - 2:
            i = self.t_nx - 2
        if j < 0:
            j = 0
        elif j > self.t_ny - 2:
            j = self.t_ny - 2
        ax = min(1.0, max(0.0, fx - i))
        ay = min(1.0, max(0.0, fy - j))
        t = self.terrain
        k = j * self.t_nx + i
        h00 = t[k]
        h10 = t[k + 1]
        h01 = t[k + self.t_nx]
        h11 = t[k + self.t_nx + 1]
        return 0.01 * (h00 * (1 - ax) * (1 - ay) + h10 * ax * (1 - ay) + h01 * (1 - ax) * ay + h11 * ax * ay)

    # ---- raster --------------------------------------------------------------------------
    def idx(self, x, y):
        i = int((x - self.minx) / self.cell)
        j = int((y - self.miny) / self.cell)
        if i < 0 or j < 0 or i >= self.nx or j >= self.ny:
            return -1
        return j * self.nx + i

    def gblocked(self, x, y):
        k = self.idx(x, y)
        return k < 0 or self.gb[k] != 0

    def _fill(self, rings, fn):
        """Even-odd scanline fill of `rings` (flat coordinate lists); calls fn(idx) per covered cell."""
        c = self.cell
        ys = [v for r in rings for v in r[1::2]]
        j0 = max(0, int((min(ys) - self.miny) / c))
        j1 = min(self.ny - 1, int((max(ys) - self.miny) / c) + 1)
        edges = []
        for r in rings:
            m = len(r) // 2
            for a in range(m):
                x1, y1 = r[2 * a], r[2 * a + 1]
                x2, y2 = r[2 * ((a + 1) % m)], r[2 * ((a + 1) % m) + 1]
                if y1 != y2:
                    edges.append((x1, y1, x2, y2))
        for j in range(j0, j1 + 1):
            y = self.miny + (j + 0.5) * c
            xs = []
            for x1, y1, x2, y2 in edges:
                if (y1 <= y < y2) or (y2 <= y < y1):
                    xs.append(x1 + (y - y1) * (x2 - x1) / (y2 - y1))
            xs.sort()
            for a in range(0, len(xs) - 1, 2):
                i0 = max(0, int(math.ceil((xs[a] - self.minx) / c - 0.5)))
                i1 = min(self.nx - 1, int(math.floor((xs[a + 1] - self.minx) / c - 0.5)))
                base = j * self.nx
                for i in range(i0, i1 + 1):
                    fn(base + i)

    def _raster_prisms(self, prisms):
        lo, hi, gb = self.lo, self.hi, self.gb
        for p in prisms:
            rings = [p["ring"]] + list(p.get("holes") or [])
            base, top = p["base"], p["top"]
            solid = p["kind"] != "bridge"

            def fn(k, base=base, top=top, solid=solid):
                if base < lo[k]:
                    lo[k] = base
                if top > hi[k]:
                    hi[k] = top
                if solid:
                    gb[k] = 1
            try:
                self._fill(rings, fn)
            except ValueError:
                continue

    def _raster_trees(self, trees):
        f = trees["fields"]
        d = trees["data"]
        n = len(f)
        ix, iy, iz = f.index("x"), f.index("y"), f.index("z")
        ih, ir, ib = f.index("height"), f.index("crownR"), f.index("crownBase")
        icx = f.index("crownX") if "crownX" in f else None
        icy = f.index("crownY") if "crownY" in f else None
        c = self.cell
        for t in range(len(d) // n):
            r = d[t * n:(t + 1) * n]
            cx = r[icx] if icx is not None else r[ix]
            cy = r[icy] if icy is not None else r[iy]
            z0 = r[iz]
            clo, chi, rad = z0 + r[ib], z0 + r[ih], max(r[ir], 1.0)
            for j in range(int((cy - rad - self.miny) / c), int((cy + rad - self.miny) / c) + 1):
                if j < 0 or j >= self.ny:
                    continue
                for i in range(int((cx - rad - self.minx) / c), int((cx + rad - self.minx) / c) + 1):
                    if i < 0 or i >= self.nx:
                        continue
                    k = j * self.nx + i
                    if clo < self.tlo[k]:
                        self.tlo[k] = clo
                    if chi > self.thi[k]:
                        self.thi[k] = chi

    def _slope_mask(self, max_deg=50.0):
        lim = math.tan(math.radians(max_deg))
        c = self.cell
        for j in range(self.ny):
            y = self.miny + (j + 0.5) * c
            for i in range(self.nx):
                k = j * self.nx + i
                if self.gb[k]:
                    continue
                x = self.minx + (i + 0.5) * c
                gx = (self.ground(x + c, y) - self.ground(x - c, y)) / (2 * c)
                gy = (self.ground(x, y + c) - self.ground(x, y - c)) / (2 * c)
                if gx * gx + gy * gy > lim * lim:
                    self.gb[k] = 1

    # ---- line of sight -------------------------------------------------------------------
    def _dirs(self, K):
        t = self._tables.get(K)
        if t is None:
            cs = [math.cos(-math.pi + (k + 0.5) * 2 * math.pi / K) for k in range(K)]
            sn = [math.sin(-math.pi + (k + 0.5) * 2 * math.pi / K) for k in range(K)]
            t = self._tables[K] = (cs, sn)
        return t

    def ray(self, ex, ey, ez, cs, sn, limit, step, trees=True):
        """Distance along (cs, sn) from the eye to the first sight blocker, capped at `limit`."""
        lo, hi, tlo, thi = self.lo, self.hi, self.tlo, self.thi
        nx, ny, minx, miny, inv = self.nx, self.ny, self.minx, self.miny, 1.0 / self.cell
        d = step
        while d < limit:
            i = int((ex + cs * d - minx) * inv)
            j = int((ey + sn * d - miny) * inv)
            if i < 0 or j < 0 or i >= nx or j >= ny:
                return d
            k = j * nx + i
            if lo[k] <= ez <= hi[k]:
                return d
            if trees and tlo[k] <= ez <= thi[k]:
                return d
            d += step
        return limit

    def los(self, a, b, step=2.0, trees=False):
        """True if the segment a->b (3D points) is not blocked by a building/bridge (or crown if trees)."""
        dx, dy, dz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
        dist = math.sqrt(dx * dx + dy * dy)
        if dist < 1e-6:
            return True
        n = max(1, int(dist / step))
        lo, hi, tlo, thi = self.lo, self.hi, self.tlo, self.thi
        for s in range(1, n):
            f = s / n
            k = self.idx(a[0] + dx * f, a[1] + dy * f)
            if k < 0:
                return False
            z = a[2] + dz * f
            if lo[k] <= z <= hi[k]:
                return False
            if trees and tlo[k] <= z <= thi[k]:
                return False
        return True
