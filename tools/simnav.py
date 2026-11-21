"""Map model for the bot: a 2 m grid of walls and sight blockers, ground height, rays, line of sight,
cover search and an incremental A* that never blows the 50 ms budget. Standard library only.

Built once at hello from hello.map (v2/world.json + v2/terrain.i16, protocol.md section 11).
"""
import heapq
import json
import math
import os
import sys
import time
from array import array

CELL = 2.0


class Map:
    def __init__(self, map_dir, mech_height=9.0, step_up=1.2, max_slope_deg=50.0, eye=8.0):
        with open(os.path.join(map_dir, "v2", "world.json")) as f:
            w = json.load(f)
        b = w["bounds"]
        self.minx, self.miny = b["minX"], b["minY"]
        self.maxx, self.maxy = b["maxX"], b["maxY"]
        self.nx = int(math.ceil((self.maxx - self.minx) / CELL))
        self.ny = int(math.ceil((self.maxy - self.miny) / CELL))
        self._load_terrain(map_dir, w["terrain"])
        n = self.nx * self.ny
        # ground height at each cell center
        g = array("f", bytes(4 * n))
        for j in range(self.ny):
            y = self.miny + (j + 0.5) * CELL
            row = j * self.nx
            for i in range(self.nx):
                g[row + i] = self.ground(self.minx + (i + 0.5) * CELL, y)
        self.g = g
        wall = bytearray(n)   # can't walk through (building, stadium, too-steep terrain, map edge)
        sight = bytearray(n)  # blocks eye-level line of sight (tall solids)
        for p in w["prisms"]:
            if p["kind"] == "bridge":
                continue  # walkable deck / passable underneath; terrain slope handles the banks
            self._fill(p, wall, sight, mech_height, step_up, eye)
        # steep terrain
        lim = CELL * math.tan(math.radians(max_slope_deg))
        nx = self.nx
        for j in range(self.ny):
            row = j * nx
            for i in range(nx):
                k = row + i
                h = g[k]
                if (i + 1 < nx and abs(g[k + 1] - h) > lim) or (j + 1 < self.ny and abs(g[k + nx] - h) > lim):
                    wall[k] = 1
                    if i + 1 < nx and abs(g[k + 1] - h) > lim:
                        wall[k + 1] = 1
                    if j + 1 < self.ny and abs(g[k + nx] - h) > lim:
                        wall[k + nx] = 1
        for i in range(nx):  # map edge
            wall[i] = wall[(self.ny - 1) * nx + i] = 1
        for j in range(self.ny):
            wall[j * nx] = wall[j * nx + nx - 1] = 1
        self.wall, self.sight = wall, sight
        # navigation grid: walls grown by one cell so paths keep clear of the 2.5 m mech radius
        nav = bytearray(wall)
        for k in range(n):
            if wall[k]:
                i, j = k % nx, k // nx
                for dj in (-1, 0, 1):
                    jj = j + dj
                    if 0 <= jj < self.ny:
                        base = jj * nx
                        for di in (-1, 0, 1):
                            ii = i + di
                            if 0 <= ii < nx:
                                nav[base + ii] = 1
        self.nav = nav

    # ------------------------------------------------------------------ loading
    def _load_terrain(self, map_dir, t):
        self.tminx, self.tminy, self.tstep = t["minX"], t["minY"], t["step"]
        self.tnx, self.tny, self.tscale = t["nx"], t["ny"], t.get("scale", 0.01)
        a = array("h")
        with open(os.path.join(map_dir, "v2", t.get("file", "terrain.i16")), "rb") as f:
            a.frombytes(f.read())
        if sys.byteorder != "little":
            a.byteswap()
        self.terrain = a

    def ground(self, x, y):
        """Bilinear ground height (m)."""
        fx = (x - self.tminx) / self.tstep
        fy = (y - self.tminy) / self.tstep
        i, j = int(fx), int(fy)
        if i < 0:
            i, fx = 0, 0.0
        if j < 0:
            j, fy = 0, 0.0
        if i >= self.tnx - 1:
            i, fx = self.tnx - 2, float(self.tnx - 1)
        if j >= self.tny - 1:
            j, fy = self.tny - 2, float(self.tny - 1)
        u, v = fx - i, fy - j
        a, nx = self.terrain, self.tnx
        k = j * nx + i
        h = (a[k] * (1 - u) + a[k + 1] * u) * (1 - v) + (a[k + nx] * (1 - u) + a[k + nx + 1] * u) * v
        return h * self.tscale

    def _fill(self, p, wall, sight, mech_height, step_up, eye):
        """Scanline-fill a prism's footprint (ring minus holes, even-odd) into the grids."""
        polys = [p["ring"]] + list(p.get("holes") or [])
        edges = []
        ys = []
        for r in polys:
            m = len(r) // 2
            for a in range(m):
                x0, y0 = r[2 * a], r[2 * a + 1]
                x1, y1 = r[2 * ((a + 1) % m)], r[2 * ((a + 1) % m) + 1]
                if y0 != y1:
                    edges.append((x0, y0, x1, y1))
                ys.append(y0)
        if not edges:
            return
        j0 = max(0, int((min(ys) - self.miny) / CELL))
        j1 = min(self.ny - 1, int((max(ys) - self.miny) / CELL))
        base, top = p["base"], p["top"]
        nx = self.nx
        for j in range(j0, j1 + 1):
            yc = self.miny + (j + 0.5) * CELL
            xs = []
            for x0, y0, x1, y1 in edges:
                if (y0 <= yc < y1) or (y1 <= yc < y0):
                    xs.append(x0 + (yc - y0) * (x1 - x0) / (y1 - y0))
            if len(xs) < 2:
                continue
            xs.sort()
            for a in range(0, len(xs) - 1, 2):
                i0 = max(0, int(math.ceil((xs[a] - self.minx) / CELL - 0.5)))
                i1 = min(nx - 1, int(math.floor((xs[a + 1] - self.minx) / CELL - 0.5)))
                for i in range(i0, i1 + 1):
                    k = j * nx + i
                    gk = self.g[k]
                    if top > gk + step_up and base < gk + mech_height:
                        wall[k] = 1
                    if top > gk + eye and base < gk + eye:
                        sight[k] = 1

    # ------------------------------------------------------------------ cells
    def cell(self, x, y):
        i = int((x - self.minx) / CELL)
        j = int((y - self.miny) / CELL)
        if i < 0 or j < 0 or i >= self.nx or j >= self.ny:
            return -1
        return j * self.nx + i

    def center(self, k):
        return self.minx + (k % self.nx + 0.5) * CELL, self.miny + (k // self.nx + 0.5) * CELL

    def blocked(self, x, y, grid=None):
        k = self.cell(x, y)
        return True if k < 0 else bool((grid or self.wall)[k])

    def ray_free(self, x0, y0, x1, y1, grid=None, step=1.0):
        """True if no blocked cell lies on the segment (sampled every `step` m)."""
        g = grid if grid is not None else self.wall
        dx, dy = x1 - x0, y1 - y0
        d = math.hypot(dx, dy)
        n = int(d / step) + 1
        minx, miny, nx, ny = self.minx, self.miny, self.nx, self.ny
        last = -2
        for s in range(1, n + 1):
            f = s / n
            i = int((x0 + dx * f - minx) / CELL)
            j = int((y0 + dy * f - miny) / CELL)
            if i < 0 or j < 0 or i >= nx or j >= ny:
                return False
            k = j * nx + i
            if k != last:
                if g[k]:
                    return False
                last = k
        return True

    def ray_len(self, x, y, ux, uy, max_d, grid=None):
        """Free distance along a unit direction, up to max_d."""
        g = grid if grid is not None else self.wall
        minx, miny, nx, ny = self.minx, self.miny, self.nx, self.ny
        d = 1.0
        while d <= max_d:
            i = int((x + ux * d - minx) / CELL)
            j = int((y + uy * d - miny) / CELL)
            if i < 0 or j < 0 or i >= nx or j >= ny or g[j * nx + i]:
                return d - 1.0
            d += 1.0
        return max_d

    def los(self, ax, ay, bx, by):
        """Eye-level line of sight between two ground points (buildings only; trees ignored)."""
        return self.ray_free(ax, ay, bx, by, self.sight, step=1.5)

    # ------------------------------------------------------------------ search
    def find_cover(self, x, y, threats, ok, radii=(8, 16, 26), dirs=16, deadline=None):
        """A nearby reachable point hidden from every threat (list of (x, y)). `ok(px, py)` filters
        points (e.g. must stay in the zone). Returns (px, py, hidden_count) or None."""
        best, best_s = None, -1e9
        for r in radii:
            for a in range(dirs):
                if deadline and time.perf_counter() > deadline:
                    return best
                ang = 2 * math.pi * a / dirs
                px, py = x + r * math.cos(ang), y + r * math.sin(ang)
                k = self.cell(px, py)
                if k < 0 or self.nav[k] or not ok(px, py):
                    continue
                if not self.ray_free(x, y, px, py, self.wall):
                    continue
                hidden = sum(1 for tx, ty in threats if not self.los(tx, ty, px, py))
                if hidden == 0:
                    continue
                dmin = min((math.hypot(px - tx, py - ty) for tx, ty in threats), default=0)
                s = hidden * 100 + min(dmin, 120) * 0.3 - r * 0.8
                if s > best_s:
                    best, best_s = (px, py, hidden), s
            if best and best[2] == len(threats):
                return best
        return best

    def nearest_free(self, x, y, grid=None, max_r=6):
        g = grid if grid is not None else self.nav
        k = self.cell(x, y)
        if k >= 0 and not g[k]:
            return k
        i0, j0 = int((x - self.minx) / CELL), int((y - self.miny) / CELL)
        for r in range(1, max_r + 1):
            for dj in range(-r, r + 1):
                for di in (-r, r) if abs(dj) != r else range(-r, r + 1):
                    i, j = i0 + di, j0 + dj
                    if 0 <= i < self.nx and 0 <= j < self.ny and not g[j * self.nx + i]:
                        return j * self.nx + i
        return -1


class AStar:
    """Incremental A* on the nav grid from a start to any cell inside a goal circle. Call step(budget_s)
    each tick until .done; then .path is a list of (x, y) waypoints (string-pulled), or None."""

    def __init__(self, m, sx, sy, gx, gy, gr, weight=1.6, max_expand=60000):
        self.m, self.gx, self.gy, self.gr = m, gx, gy, max(gr, CELL)
        self.weight, self.max_expand = weight, max_expand
        self.done, self.path, self.expanded = False, None, 0
        s = m.nearest_free(sx, sy)
        if s < 0:
            self.done = True
            return
        self.start = s
        self.came = {s: -1}
        self.cost = {s: 0.0}
        self.open = [(self._h(s), s)]

    def _h(self, k):
        x, y = self.m.center(k)
        return max(0.0, math.hypot(x - self.gx, y - self.gy) - self.gr) * self.weight

    def step(self, budget_s):
        if self.done:
            return
        m, nav, nx, ny = self.m, self.m.nav, self.m.nx, self.m.ny
        end = time.perf_counter() + budget_s
        came, cost, open_ = self.came, self.cost, self.open
        gx, gy, gr2 = self.gx, self.gy, self.gr * self.gr
        minx, miny = m.minx, m.miny
        while open_:
            if (self.expanded & 63) == 0 and time.perf_counter() > end:
                return
            _, k = heapq.heappop(open_)
            self.expanded += 1
            i, j = k % nx, k // nx
            cx, cy = minx + (i + 0.5) * CELL, miny + (j + 0.5) * CELL
            if (cx - gx) ** 2 + (cy - gy) ** 2 <= gr2:
                self._finish(k)
                return
            if self.expanded > self.max_expand:
                break
            ck = cost[k]
            for di, dj, c in ((1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0),
                              (1, 1, 1.414), (1, -1, 1.414), (-1, 1, 1.414), (-1, -1, 1.414)):
                ii, jj = i + di, j + dj
                if ii < 0 or jj < 0 or ii >= nx or jj >= ny:
                    continue
                n = jj * nx + ii
                if nav[n]:
                    continue
                if di and dj and (nav[j * nx + ii] or nav[jj * nx + i]):
                    continue  # no corner cutting
                nc = ck + c
                if nc < cost.get(n, 1e18):
                    cost[n] = nc
                    came[n] = k
                    x, y = minx + (ii + 0.5) * CELL, miny + (jj + 0.5) * CELL
                    h = max(0.0, math.hypot(x - gx, y - gy) - self.gr) * self.weight
                    heapq.heappush(open_, (nc + h, n))
        self.done = True  # unreachable or too far: no path

    def _finish(self, k):
        cells = []
        while k != -1:
            cells.append(k)
            k = self.came[k]
        cells.reverse()
        pts = [self.m.center(c) for c in cells]
        # string pulling: keep only the waypoints needed for clear straight segments
        out, a = [pts[0]], 0
        while a < len(pts) - 1:
            b = min(len(pts) - 1, a + 40)
            while b > a + 1 and not self.m.ray_free(pts[a][0], pts[a][1], pts[b][0], pts[b][1], self.m.nav):
                b -= 1
            out.append(pts[b])
            a = b
        self.path = out
        self.done = True
        self.came = self.cost = self.open = None
