"""Tests for late.py (late-game spot planner) on the real map.  python test_late.py"""
import math
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import late  # noqa: E402
from nav import Map  # noqa: E402

m = Map(os.path.join(HERE, "kit", "arena"), 9.0, 1.2, 50.0, 8.0)
fails = 0


def check(ok, what):
    global fails
    print(("ok   " if ok else "FAIL ") + what)
    fails += not ok


# flag and activation
p = late.LatePlanner(m, {})
check(not p.active({"next_radius": 70}), "default params: off")
p = late.LatePlanner(m, {"enabled": True, "start_next_r": 140})
check(not p.active({"next_radius": 240}) and p.active({"next_radius": 140}) and p.active({"next_radius": 0}),
      "active from next radius <= 140")
bad = late.LateParams.from_dict({"enabled": "yes", "start_next_r": "x", "cube_cap": 7})
check(bad.enabled is True and bad.start_next_r == 140.0 and bad.cube_cap == 7, "bad values ignored, good kept")

# spots for random circles across the map: inside the disc, no more open than the center, time-bounded
import random  # noqa: E402
rng = random.Random(3)
worst_ms, better, comparable, n = 0.0, 0, 0, 0
for trial in range(30):
    gx, gy = rng.uniform(-250, 250), rng.uniform(-250, 250)
    gr = rng.choice([3.0, 17.5, 52.5, 105.0])
    x, y = gx + rng.uniform(-200, 200), gy + rng.uniform(-200, 200)
    lp = late.LatePlanner(m, {"enabled": True, "travel_w": 0.0})   # rank by openness alone
    spot, ticks = None, 0
    while ticks < 200:
        t0 = time.perf_counter()
        spot = lp.update(x, y, gx, gy, gr, t0 + 0.012)
        worst_ms = max(worst_ms, (time.perf_counter() - t0) * 1000)
        ticks += 1
        if not lp.todo:
            break
    n += 1
    if spot is None or math.hypot(spot[0] - gx, spot[1] - gy) > gr + 1e-6:
        check(False, f"spot inside disc ({gx:.0f},{gy:.0f},{gr})")
        continue
    k = m.nearest_free(gx, gy, max_r=3)
    if k >= 0:
        cx, cy = m.center(k)
        if math.hypot(cx - gx, cy - gy) <= gr:          # the center was a valid candidate: we must beat it
            comparable += 1
            better += lp._openness(*spot) <= lp._openness(cx, cy) + 1e-9
check(n == 30, "30 circles planned")
check(comparable >= 10 and better == comparable, f"spot no more open than the center in {better}/{comparable}")
check(worst_ms < 16, f"worst update {worst_ms:.1f} ms with a 12 ms deadline")

# same circle: spot is stable (no flip-flop) once the search is done
lp = late.LatePlanner(m, {"enabled": True})
for _ in range(100):
    s1 = lp.update(0, 0, 20, -40, 52.5, time.perf_counter() + 0.01)
s2 = lp.update(5, 5, 20, -40, 52.5, time.perf_counter() + 0.01)
check(s1 == s2, "spot stable within a phase")
print("PASS" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
