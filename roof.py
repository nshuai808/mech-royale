"""roof.py: pick a climbable roof inside the zone and get onto it (protocol section 6: jet ~60 m on 100 energy).

Standard library only. The bot asks `RoofPlanner.choose(...)` for a roof that stays inside the next circle, walks to
its `approach` point next to the wall, waits for energy, then climbs (move toward `stand`, jump, jet while airborne).
On the roof it stands at `stand`, back from the edges, so ground bots can't see it.
"""
import json
import math
import os


def _inside(px, py, ring):
    """Point in polygon (flat [x0, y0, x1, y1, ...]), even-odd."""
    n = len(ring) // 2
    c = False
    j = n - 1
    for i in range(n):
        xi, yi, xj, yj = ring[2 * i], ring[2 * i + 1], ring[2 * j], ring[2 * j + 1]
        if (yi > py) != (yj > py) and px < (xj - xi) * (py - yi) / ((yj - yi) or 1e-9) + xi:
            c = not c
        j = i
    return c


def _edge_dist(px, py, ring):
    """Distance from a point to the polygon outline, and the closest outline point."""
    n = len(ring) // 2
    best, bp = 1e9, (px, py)
    for i in range(n):
        ax, ay = ring[2 * i], ring[2 * i + 1]
        bx, by = ring[2 * ((i + 1) % n)], ring[2 * ((i + 1) % n) + 1]
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        f = 0.0 if L2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
        cx, cy = ax + dx * f, ay + dy * f
        d = math.hypot(px - cx, py - cy)
        if d < best:
            best, bp = d, (cx, cy)
    return best, bp


class Roof:
    __slots__ = ("ring", "top", "stand", "inner", "area")

    def __init__(self, ring, top, stand, inner, area):
        self.ring, self.top, self.stand, self.inner, self.area = ring, top, stand, inner, area

    def contains(self, x, y):
        return _inside(x, y, self.ring)


class RoofPlanner:
    def __init__(self, map_dir, ground, min_h=8.0, max_h=50.0, min_area=600.0, min_inner=7.0):
        self.roofs = []
        with open(os.path.join(map_dir, "v2", "world.json")) as f:
            w = json.load(f)
        for p in w.get("prisms", []):
            if p.get("kind") != "building" or p.get("holes"):
                continue
            ring = p["ring"]
            xs, ys = ring[0::2], ring[1::2]
            n = len(xs)
            area = abs(sum(xs[i] * ys[(i + 1) % n] - xs[(i + 1) % n] * ys[i] for i in range(n))) / 2
            if area < min_area:
                continue
            # stand point: the interior grid point farthest from the edges (out of sight from the ground)
            best, best_d = None, 0.0
            x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
            step = max(2.0, min(x1 - x0, y1 - y0) / 12)
            yy = y0 + step / 2
            while yy < y1:
                xx = x0 + step / 2
                while xx < x1:
                    if _inside(xx, yy, ring):
                        d, _ = _edge_dist(xx, yy, ring)
                        if d > best_d:
                            best, best_d = (xx, yy), d
                    xx += step
                yy += step
            if best is None or best_d < min_inner:
                continue
            h = p["top"] - ground(best[0], best[1])
            if not (min_h <= h <= max_h):
                continue
            # a roof with another prism above it at the stand point (towers, stacked blocks) is skipped
            self.roofs.append(Roof(ring, p["top"], best, best_d, area))
        # drop roofs covered by a taller prism at their stand point
        keep = []
        for r in self.roofs:
            if any(o is not r and o.top > r.top + 1 and o.contains(*r.stand) for o in self.roofs):
                continue
            keep.append(r)
        self.roofs = keep

    def choose(self, x, y, safe, nc, nr):
        """Best roof whose stand point passes `safe(px, py)`; prefers near us and near the next centre."""
        best, best_s = None, 1e18
        for r in self.roofs:
            sx, sy = r.stand
            dc = math.hypot(sx - nc[0], sy - nc[1])
            if dc > nr - 8 or not safe(sx, sy):
                continue
            s = math.hypot(sx - x, sy - y) + 0.7 * dc - 2.0 * min(r.inner, 20)
            if s < best_s:
                best, best_s = r, s
        return best

    @staticmethod
    def approach(r, x, y):
        """Point on the ground just outside the wall nearest to us."""
        _, (cx, cy) = _edge_dist(x, y, r.ring)
        sx, sy = r.stand
        ux, uy = cx - sx, cy - sy
        d = math.hypot(ux, uy) or 1.0
        return cx + ux / d * 3.5, cy + uy / d * 3.5
