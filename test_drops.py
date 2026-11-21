"""Unit tests for drops.py (H-DRP) plus a bot.py integration check. python3 test_drops.py"""
import math
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from drops import DropPlanner, DropParams  # noqa: E402
import test_zone  # noqa: E402  (reuses its bot-over-the-protocol runner)

HELLO = {"slot": 3, "config": {"mech": {"walk_speed": 11.7},
                               "drops": {"times": [70, 140, 210], "fall_s": 25, "radius": 8, "capture_s": 4, "cubes": 3}}}
ZONE = {"center": [0, 0], "radius": 380, "next_center": [0, 0], "next_radius": 240,
        "shrink_start": 155, "shrink_end": 195, "dps": 35}


def obs(t=150.0, pos=(100.0, 0.0), hp=1400, drops=(), mechs=(), events=(), zone=None):
    return {"t": t, "tick": int(t * 20),
            "self": {"id": 3, "pos": [pos[0], pos[1], 0.0], "hp": hp, "max_hp": 1400, "stats": {"walk_speed": 11.7}},
            "drops": list(drops), "mechs": list(mechs), "events": list(events), "zone": zone or dict(ZONE)}


def drop(pos=(0.0, 0.0), lands_in=0.0, holder=None, progress=0.0, did=20001):
    return {"id": did, "pos": [pos[0], pos[1], 0.0], "radius": 8, "lands_in": lands_in, "capture_s": 4,
            "progress": progress, "holder": holder}


def enemy(pos, mid=5):
    return {"id": mid, "kind": "mech", "pos": [pos[0], pos[1], 0.0], "vel": [0, 0, 0], "hp": 1400, "max_hp": 1400}


def test_no_drops():
    d = DropPlanner(HELLO).step(obs())
    assert d.goal is None and d.reason == "no drops"


def test_landed_reachable_drop_is_approached():
    d = DropPlanner(HELLO).step(obs(drops=[drop()]))
    assert d.phase == "approach" and d.goal[:2] == (0.0, 0.0), d


def test_too_early_waits_at_standoff_on_our_side():
    d = DropPlanner(HELLO).step(obs(pos=(60.0, 0.0), drops=[drop(lands_in=20.0)]))
    assert d.phase == "wait" and d.hold
    assert abs(math.hypot(*d.goal[:2]) - DropParams().standoff_m) < 1 and d.goal[0] > 0, d


def test_leave_in_time_to_arrive_at_landing():
    # 117 m away = 10 s walk, lands in 12 s: start walking now
    d = DropPlanner(HELLO).step(obs(pos=(117.0, 0.0), drops=[drop(lands_in=12.0)]))
    assert d.phase == "approach", d


def test_capture_holds_inside_ring_and_steps_back_in():
    p = DropPlanner(HELLO)
    d = p.step(obs(pos=(1.0, 0.0), drops=[drop(holder=3, progress=1.0)]))
    assert d.phase == "capture" and d.move == (0.0, 0.0)
    d = p.step(obs(t=150.1, pos=(6.0, 0.0), drops=[drop(holder=3, progress=1.1)]))
    assert d.phase == "capture" and d.move[0] < 0, d     # near the ring edge: step back toward the centre


def test_stalled_capture_gives_up():
    p = DropPlanner(HELLO)
    reasons = []
    for k in range(40):  # 4 s in the ring, clock frozen (someone else in it)
        d = p.step(obs(t=150.0 + k * 0.1, pos=(1.0, 0.0), drops=[drop(holder=None, progress=0.0)]))
        reasons.append(d.reason)
    assert "stalled" in reasons and 28 <= reasons.index("stalled") <= 33 and d.goal is None, reasons
    d = p.step(obs(t=155.0, pos=(1.0, 0.0), drops=[drop()]))
    assert d.goal is None  # ignored for retry_s


def test_enemies_at_the_ring_make_it_not_worth_it():
    d = DropPlanner(HELLO).step(obs(drops=[drop()], mechs=[enemy((5, 5)), enemy((-10, 3), 6)]))
    assert d.goal is None, d


def test_low_hp_raises_utility():
    a = DropPlanner(HELLO).step(obs(hp=1400, drops=[drop()]))
    b = DropPlanner(HELLO).step(obs(hp=300, drops=[drop()]))
    assert b.utility > a.utility + 0.5


def test_drop_outside_future_zone_is_refused():
    z = dict(ZONE, next_center=[0, 0], next_radius=50)
    d = DropPlanner(HELLO).step(obs(drops=[drop(pos=(48.0, 0.0))], zone=z))
    assert d.goal is None, d


def test_too_far_or_too_late_is_refused():
    assert DropPlanner(HELLO).step(obs(pos=(0.0, 0.0), drops=[drop(pos=(230.0, 0.0), lands_in=0.0)],
                                       zone=dict(ZONE, radius=560, next_radius=560))).goal is not None
    p = DropParams(max_dist_m=100)
    pl = DropPlanner(HELLO, {"max_dist_m": 100})
    assert pl.p.max_dist_m == 100 and pl.step(obs(pos=(150.0, 0.0), drops=[drop()])).goal is None


def test_captured_event_forgets_the_drop():
    p = DropPlanner(HELLO)
    p.step(obs(drops=[drop()], events=[{"type": "drop", "id": 20001, "cubes": 3}]))
    assert p.step(obs(drops=[drop()])).goal is None


def test_contested_far_drop_is_skipped_close_one_is_not():
    far = DropPlanner(HELLO).step(obs(pos=(150.0, 0.0), drops=[drop(holder=7, progress=2.0)]))
    near = DropPlanner(HELLO).step(obs(pos=(30.0, 0.0), drops=[drop(holder=7, progress=2.0)]))
    assert far.goal is None and near.goal is not None and near.boost


def test_enemy_near_us_blocks_new_run_but_not_capture():
    assert DropPlanner(HELLO).step(obs(drops=[drop()], mechs=[enemy((150, 60))])).goal is None
    d = DropPlanner(HELLO).step(obs(pos=(1.0, 0.0), drops=[drop(holder=3, progress=2.0)], mechs=[enemy((90, 0))]))
    assert d.phase == "capture", d


def test_zone_critical_overrides():
    class Z:
        urgency = 3
    assert DropPlanner(HELLO).step(obs(drops=[drop()]), zone_plan=Z()).goal is None


def test_path_cost_unreachable_and_garbage():
    p = DropPlanner(HELLO)
    assert p.step(obs(drops=[drop()]), path_cost=lambda a, b: (None, 0.0)).goal is None
    bad = obs(drops=[{"id": 1, "pos": None}])
    assert p.step(bad).reason.startswith("error")
    assert DropPlanner(HELLO, {"enabled": False}).step(obs(drops=[drop()])).reason == "off"


def test_fast():
    p = DropPlanner(HELLO)
    o = obs(drops=[drop(did=20000 + i, pos=(i * 20.0, 0.0)) for i in range(3)], mechs=[enemy((50, 50))])
    t0 = time.perf_counter()
    for _ in range(500):
        p.step(o)
    assert (time.perf_counter() - t0) / 500 < 0.002


# ---- bot.py integration (real subprocess over the protocol)
def _at_drop_setup(o, lands_in=0.0, me=(40.0, 0.0), holder=None):
    o["self"]["pos"] = [me[0], me[1], 0.0]; o["self"]["in_zone"] = True; o["self"]["id"] = 3
    o["pickups"] = []; o["mechs"] = []; o["cubes"] = []; o["crates"] = []; o["events"] = []
    o["zone"] = dict(ZONE); o["t"] = 150.0
    o["drops"] = [drop(lands_in=lands_in, holder=holder)]


def test_bot_walks_to_landed_drop():
    (a,) = test_zone._run_bot([_at_drop_setup])
    assert a["move"][0] < -0.7, a


def test_bot_stands_in_ring_while_capturing():
    (a,) = test_zone._run_bot([lambda o: _at_drop_setup(o, me=(1.0, 0.5), holder=3)])
    assert math.hypot(*a["move"]) < 0.4, a


if __name__ == "__main__":
    fails = 0
    for n, f in list(globals().items()):
        if n.startswith("test_") and callable(f) and f.__module__ == __name__:
            try:
                f(); print("ok  ", n)
            except Exception:
                import traceback; traceback.print_exc(); print("FAIL", n); fails += 1
    sys.exit(1 if fails else 0)
