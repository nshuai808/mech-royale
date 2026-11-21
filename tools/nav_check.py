#!/usr/bin/env python3
"""Offline nav validation (stdlib only): follow random trips with the real Navigator on the real map and
measure the TRUE distance to wall edges along the way (exact prism geometry, not the 4 m grid).

The simulated mech moves freely (no collision), so a clearance under the 2.5 m radius means the path
would have clipped a wall on the server. This does not model the server's collision or slide.

    python3 tools/nav_check.py [--trips 60] [--seed 1] [--margin 0.5]
"""
import argparse
import gzip
import json
import math
import os
import random
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import nav  # noqa: E402


def load():
    with gzip.open(os.path.join(ROOT, "kit", "check", "stream.jsonl.gz"), "rt") as f:
        hello = json.loads(f.readline())
    arena = os.path.join(ROOT, "kit", "arena")
    return dict(hello, map={"dir": arena}), arena


class Walls:
    def __init__(self, arena, step_up, height):
        w = json.load(open(os.path.join(arena, "v2/world.json")))
        tr = w["terrain"]
        self.NX, self.NY, self.minx, self.miny = tr["nx"], tr["ny"], tr["minX"], tr["minY"]
        import array
        self.ter = array.array("h")
        with open(os.path.join(arena, "v2/terrain.i16"), "rb") as f:
            self.ter.frombytes(f.read())
        self.step_up, self.height = step_up, height
        self.pr = []
        for p in w["prisms"]:
            xs, ys = p["ring"][0::2], p["ring"][1::2]
            self.pr.append((min(xs), max(xs), min(ys), max(ys), p))

    def ground(self, x, y):
        i = min(self.NX - 2, max(0, int(x - self.minx)))
        j = min(self.NY - 2, max(0, int(y - self.miny)))
        return self.ter[j * self.NX + i] * 0.01

    def clearance(self, x, y):
        z = self.ground(x, y)
        best = 1e9
        for x0, x1, y0, y1, p in self.pr:
            if x < x0 - 8 or x > x1 + 8 or y < y0 - 8 or y > y1 + 8:
                continue
            if not (p["top"] > z + self.step_up and p["base"] < z + self.height):
                continue
            if nav._pip(x, y, p["ring"]) and not any(nav._pip(x, y, h) for h in (p.get("holes") or []) if h):
                return -1.0
            for r in [p["ring"]] + [h for h in (p.get("holes") or []) if h]:
                n = len(r) // 2
                for k in range(n):
                    a = (k - 1) % n
                    ax, ay, bx, by = r[2 * a], r[2 * a + 1], r[2 * k], r[2 * k + 1]
                    dx, dy = bx - ax, by - ay
                    L = dx * dx + dy * dy
                    t = 0.0 if L == 0 else max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / L))
                    d = math.hypot(x - ax - t * dx, y - ay - t * dy)
                    if d < best:
                        best = d
        return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trips", type=int, default=60)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--margin", type=float, default=nav.NavParams().clearance_margin_m)
    a = ap.parse_args()
    hello, arena = load()
    m = hello["config"]["mech"]
    nv = nav.Navigator.create(hello, nav.NavParams(clearance_margin_m=a.margin), nav.StealthParams(mode="off"), here=ROOT)
    nm = nv.nm
    walls = Walls(arena, m["step_up"], m["height"])
    main_comp = {}
    for k in range(len(nm.blocked)):
        if nm.comp[k]:
            main_comp[nm.comp[k]] = main_comp.get(nm.comp[k], 0) + 1
    big = max(main_comp, key=main_comp.get)
    cells = [k for k in range(len(nm.blocked)) if nm.comp[k] == big]
    rng = random.Random(a.seed)
    clear, arrived, ticks_tot = [], 0, 0
    for _ in range(a.trips):
        while True:
            s, g = rng.choice(cells), rng.choice(cells)
            if 100 <= math.dist(nm.center(s), nm.center(g)) <= 450:
                break
        nv2 = nav.Navigator(nm, hello["config"], nv.p, nv.sp)
        x, y = nm.center(s)
        gx, gy = nm.center(g)
        for n in range(900):
            z = nm.ground_z(nm.idx(x, y))
            d = nv2.step({"t": n * 0.1, "tick": n, "self": {"pos": [x, y, z], "in_zone": True, "grounded": True, "weapons": []},
                          "mechs": [], "sounds": []}, (gx, gy, z))
            ticks_tot += 1
            if math.hypot(gx - x, gy - y) < 6.0:
                arrived += 1
                break
            mv = d.move if d.move is not None else (gx - x, gy - y)
            L = math.hypot(*mv)
            if L > 1:
                mv = (mv[0] / L, mv[1] / L)
            x, y = x + mv[0] * m["walk_speed"] * 0.1, y + mv[1] * m["walk_speed"] * 0.1
            if n % 2 == 0:
                clear.append(walls.clearance(x, y))
    clear.sort()
    pc = lambda q: clear[int(q * (len(clear) - 1))]
    bad = sum(1 for c in clear if c < m["radius"])
    print(f"margin {a.margin}: trips arrived {arrived}/{a.trips}; samples {len(clear)}; true clearance m: "
          f"min {clear[0]:.2f} p1 {pc(.01):.2f} p5 {pc(.05):.2f} med {pc(.5):.2f}; "
          f"under radius {m['radius']}: {bad} ({100 * bad / len(clear):.2f}%)")


if __name__ == "__main__":
    main()
