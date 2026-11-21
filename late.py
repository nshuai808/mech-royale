"""late.py: late-game placement (Session E). Standard library only.

From the circle that shrinks to `start_next_r` on, when nothing else claims the bot (no fight, evade, drop or
loot), go to a concealed spot inside the next circle and hold it there at full HP, instead of roaming or
standing in the open. A spot is scored by how few long sight lines it has (buildings close on many sides),
how far we must walk to it, and (optionally) how close it is to the circle edge.

The search is incremental: it scores candidates until the tick's deadline and resumes next tick, so it
never costs more than the time left. The spot is recomputed when the next circle changes.

Knobs (params.json["late"]):
  enabled         master switch; false = the bot behaves exactly like main
  start_next_r    activate once the next circle's radius is at or below this (m)
  no_hunt         in late mode, don't walk to the last known enemy (aggro "hunt") when none is visible
  cube_cap        in late mode, ignore loose cubes once we hold this many (stat cap 10; size keeps growing)
  edge_pref       -1..1: >0 prefers spots near the circle edge (back to the wall), <0 near the center
  travel_w        score penalty per meter we must walk to the spot
  ray_m           sight-line length that counts as fully open (m)
"""
import math
import time
from dataclasses import dataclass, fields

CELL = 2.0


@dataclass
class LateParams:
    enabled: bool = False
    start_next_r: float = 140.0
    no_hunt: bool = True
    cube_cap: int = 10
    edge_pref: float = 0.0
    travel_w: float = 0.15
    ray_m: float = 70.0

    @classmethod
    def from_dict(cls, d):
        p = cls()
        if isinstance(d, dict):
            for f in fields(cls):
                if f.name in d:
                    cur = getattr(p, f.name)
                    try:
                        setattr(p, f.name, bool(d[f.name]) if isinstance(cur, bool) else type(cur)(d[f.name]))
                    except Exception:
                        pass
        return p


class LatePlanner:
    def __init__(self, m, params=None):
        self.m = m
        self.p = LateParams.from_dict(params)
        self.key = None
        self.spot = None          # (x, y) best so far for the current circle
        self.best_s = 1e18
        self.todo = []            # candidates left to score
        self.dirs = [(math.cos(2 * math.pi * a / 16), math.sin(2 * math.pi * a / 16)) for a in range(16)]

    def active(self, zn):
        return self.p.enabled and zn["next_radius"] <= self.p.start_next_r

    def _openness(self, x, y):
        """Mean free sight distance over 16 directions, as a fraction of ray_m (0 = boxed in, 1 = open)."""
        m = self.m
        g, minx, miny, nx, ny = m.sight, m.minx, m.miny, m.nx, m.ny
        lim = self.p.ray_m
        tot = 0.0
        for ux, uy in self.dirs:
            d = CELL
            while d <= lim:
                i = int((x + ux * d - minx) / CELL)
                j = int((y + uy * d - miny) / CELL)
                if i < 0 or j < 0 or i >= nx or j >= ny or g[j * nx + i]:
                    break
                d += CELL
            tot += min(d, lim)
        return tot / (16 * lim)

    def update(self, x, y, gx, gy, gr, deadline):
        """Spot (x, y) inside the disc (gx, gy, gr), or None until the first candidate is scored."""
        m = self.m
        if m is None:
            return None
        key = (round(gx, 1), round(gy, 1), round(gr, 1))
        if key != self.key:
            self.key, self.spot, self.best_s = key, None, 1e18
            cands = [(gx, gy, 0.0)]
            if math.hypot(x - gx, y - gy) < gr:
                cands.append((x, y, math.hypot(x - gx, y - gy) / max(gr, 1.0)))
            for f, n in ((0.3, 8), (0.55, 12), (0.8, 16), (0.95, 16)):
                for a in range(n):
                    ang = 2 * math.pi * (a + 0.5 * (f > 0.5)) / n
                    cands.append((gx + f * gr * math.cos(ang), gy + f * gr * math.sin(ang), f))
            # nearest first: if time runs short we still have a reasonable spot
            cands.sort(key=lambda c: math.hypot(c[0] - x, c[1] - y))
            self.todo = cands
        p = self.p
        while self.todo and time.perf_counter() < deadline:
            cx, cy, f = self.todo.pop(0)
            k = m.nearest_free(cx, cy, max_r=3)
            if k < 0:
                continue
            px, py = m.center(k)
            if math.hypot(px - gx, py - gy) > gr:
                continue
            s = (self._openness(px, py) * 100.0 + p.travel_w * math.hypot(px - x, py - y)
                 - p.edge_pref * 20.0 * f)
            if s < self.best_s:
                self.best_s, self.spot = s, (px, py)
        if self.spot is None and not self.todo:
            self.spot = (gx, gy)
        return self.spot
