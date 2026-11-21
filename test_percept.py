"""Unit tests for percept.py (H-PER). python3 test_percept.py   (stdlib only; harness lives in tools/per_sim.py)"""
import copy
import gzip
import json
import math
import os
import random
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
from geom import Geom
from percept import Perception, load_params
from per_sim import Scenario
import loot

KIT = os.path.join(ROOT, "kit")
STREAM = [json.loads(l) for l in gzip.open(KIT + "/check/stream.jsonl.gz", "rt")]
HELLO = STREAM[0]
OBS = [m for m in STREAM if m["type"] == "obs"]
GEOM = Geom(KIT + "/arena")
G = 22.0
TESTS = []


def test(f):
    TESTS.append(f)
    return f


def mk(**over):
    return Perception(HELLO, params=load_params(overrides=over), geom=GEOM)


def first_obs(seed=1):
    sc = Scenario(HELLO, GEOM, seed)
    sc.step()
    return sc.hello_obs()


@test
def mortar_launch_solve_is_exact():
    r = random.Random(5)
    per = mk()
    per.update(first_obs())
    for _ in range(300):
        x0, y0 = r.uniform(-200, 200), r.uniform(-200, 200)
        z0 = GEOM.ground(x0, y0) + 9.5
        yaw, pitch = r.uniform(-math.pi, math.pi), r.uniform(-0.2, 1.2)
        vh, vz0 = 72 * math.cos(pitch), 72 * math.sin(pitch)
        t = r.uniform(0.2, 0.8) * (2 * vz0 / G if vz0 > 0 else 1.0)
        p = {"pos": [x0 + vh * math.cos(yaw) * t, y0 + vh * math.sin(yaw) * t, z0 + vz0 * t - 0.5 * G * t * t],
             "vel": [vh * math.cos(yaw), vh * math.sin(yaw), vz0 - G * t]}
        fix = per.mortar_launch(p)
        assert fix and math.hypot(fix[0] - x0, fix[1] - y0) < 1.0, (fix, x0, y0)


@test
def incoming_bullet_hit_vs_miss():
    per = mk()
    o = first_obs()
    me = o["self"]["pos"]
    o["self"]["vel"] = [0, 0, 0]
    for off, expect in ((0.0, True), (1.5, True), (6.0, False)):
        o2 = dict(o)
        o2["projectiles"] = [{"id": 1, "kind": "gun", "pos": [me[0] + 100, me[1] + off, me[2] + 5], "vel": [-252, 0, 0]}]
        w = per.update(o2)
        hit = bool(w.incoming) and w.incoming[0].hit and w.incoming[0].t_hit < 0.5
        assert hit == expect, (off, hit)


@test
def laser_line_and_dodge_direction():
    o = first_obs()
    me = o["self"]["pos"]
    o["mechs"] = [{"id": 2, "kind": "mech", "pos": [me[0] + 80, me[1] + 1, me[2]], "vel": [0, 0, 0], "aim": [math.pi, 0],
                   "hp": 1400, "max_hp": 1400, "cubes": 0, "weapons": ["gun", "laser"], "charging": True}]
    w = mk().update(o)
    assert w.laser_lines and w.laser_lines[0]["hit"]
    assert w.laser_lines[0]["dodge"][1] < -0.9      # shooter's line is at +1 m north of us: dodge south


@test
def mass_accounting_over_scenarios():
    for seed in (3, 4):
        sc = Scenario(HELLO, GEOM, seed, duration=60, fire_rate=0.2)
        per = mk()
        while sc.t < 60:
            sc.step()
            o = sc.hello_obs()
            per.update(o)
            assert abs(len(per.tracks) + per.cloud.mass - (o["alive"] - 1)) < 0.6, (sc.t, len(per.tracks), per.cloud.mass, o["alive"])


@test
def malformed_and_sparse_observations_do_not_raise():
    r = random.Random(9)
    per = mk()
    for o in OBS[:150]:
        o = copy.deepcopy(o)
        for k in ("sounds", "events", "beams", "projectiles"):
            if r.random() < 0.3:
                o[k] = []
        if o["sounds"] and r.random() < 0.3:
            o["sounds"][0]["age"] = 0.0
        if r.random() < 0.2:
            o["events"] = [{"type": "damaged", "amount": 10, "weapon": "zone", "bearing": None, "by": None}]
        if r.random() < 0.2:
            o["events"] = [{"type": "damaged", "amount": 10, "weapon": "gun", "bearing": 1.0, "by": 7}]
        if r.random() < 0.1:
            o["mechs"] = o["mechs"] + [{"id": 100, "kind": "npc", "pos": [0, 0, 0], "vel": [0, 0, 0], "aim": [0, 0]}]
        per.update(o)


@test
def loot_threats_adapter():
    o = first_obs()
    me = o["self"]["pos"]
    o["mechs"] = [{"id": 2, "kind": "mech", "pos": [me[0] + 30, me[1], me[2]], "vel": [0, 0, 0], "aim": [0, 0],
                   "hp": 1400, "max_hp": 1400, "cubes": 0, "weapons": ["gun", "laser"], "charging": False}]
    per = mk()
    per.update(o)
    th = per.loot_threats(loot.Threat)
    assert th and th[0].id == 2 and "laser" in th[0].kinds and th[0].weight == 1.0 and abs(th[0].dist - 30) < 1
    # lost from view: still reported, discounted by age and confidence
    o2 = dict(o)
    o2["mechs"] = []
    o2["t"] = o["t"] + 0.1
    per.update(o2)
    th2 = per.loot_threats(loot.Threat)
    assert th2 and th2[0].id == 2 and 0.3 < th2[0].weight <= 1.0


@test
def params_override_and_disable_switches():
    p = load_params(overrides={"use_sound": False, "n_cloud": 100})
    assert p["use_sound"] is False and p["n_cloud"] == 100 and p["use_events"] is True
    per = mk(use_sound=False)
    per.update(first_obs())      # runs with sound fusion off
    p2 = Perception(HELLO, params=load_params(overrides={"enabled": False}), geom=GEOM)
    w = p2.update(first_obs())
    assert w.contacts == [] or all(c.src == "seen" for c in w.contacts)


@test
def timing_stress_under_budget():
    sc = Scenario(HELLO, GEOM, 7, duration=60, fire_rate=0.6)
    per = mk()
    ms = []
    while sc.t < 60:
        sc.step()
        o = sc.hello_obs()
        for _ in range(3):
            o["sounds"] = o["sounds"] + [dict(s) for s in o["sounds"]]
        t0 = time.perf_counter()
        per.update(o)
        ms.append((time.perf_counter() - t0) * 1000)
    ms.sort()
    p99 = ms[int(len(ms) * 0.99)]
    print("   stress p50 %.2f p99 %.2f max %.2f ms" % (ms[len(ms) // 2], p99, ms[-1]))
    assert p99 < 10.0 and ms[-1] < 20.0


@test
def recorded_stream_runs_and_is_fast():
    per = Perception(HELLO, params=load_params(), geom=GEOM)
    ms = []
    for o in OBS:
        t0 = time.perf_counter()
        per.update(o)
        ms.append((time.perf_counter() - t0) * 1000)
    ms.sort()
    print("   stream p50 %.2f p99 %.2f max %.2f ms" % (ms[len(ms) // 2], ms[int(len(ms) * 0.99)], ms[-1]))
    assert ms[int(len(ms) * 0.99)] < 10.0
    assert abs(len(per.tracks) + per.cloud.mass - (OBS[-1]["alive"] - 1)) < 0.6


@test
def hidden_track_beats_last_seen_on_real_stream():
    wins = 0
    n = 0
    for start in (110, 160, 380, 420):
        per = Perception(HELLO, params=load_params(), geom=GEOM)
        hide = range(start, start + 60, 2)
        for o in OBS:
            if o["tick"] in hide:
                truth = next((m for m in o["mechs"] if m["id"] == 10), None)
                o = dict(o)
                o["mechs"] = [m for m in o["mechs"] if m["id"] != 10]
                per.update(o)
                tr = per.tracks.get(10)
                if truth and tr and tr.px and o["tick"] == start + 58:
                    mx, my, _ = per._mean_xy(tr)
                    e1 = math.hypot(mx - truth["pos"][0], my - truth["pos"][1])
                    e0 = math.hypot(tr.last_pos[0] - truth["pos"][0], tr.last_pos[1] - truth["pos"][1])
                    n += 1
                    wins += e1 < e0
            else:
                per.update(o)
    print("   hold-out windows won %d/%d" % (wins, n))
    assert n >= 3 and wins >= n // 2 + 1


if __name__ == "__main__":
    bad = 0
    for f in TESTS:
        try:
            f()
            print("ok   ", f.__name__)
        except Exception as e:
            bad += 1
            import traceback
            traceback.print_exc()
            print("FAIL ", f.__name__, repr(e))
    print("%d/%d passed" % (len(TESTS) - bad, len(TESTS)))
    sys.exit(1 if bad else 0)
