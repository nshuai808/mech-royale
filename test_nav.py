"""Unit tests for nav.py. Run: python3 test_nav.py   (stdlib unittest; uses kit/arena and navmap.bin)."""
import gzip
import json
import math
import os
import random
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import nav  # noqa: E402

ARENA = os.path.join(HERE, "kit", "arena")
STREAM = os.path.join(HERE, "kit", "check", "stream.jsonl.gz")


def read_stream():
    hello, obs = None, []
    with gzip.open(STREAM, "rt") as f:
        for line in f:
            m = json.loads(line)
            if m["type"] == "hello" and hello is None:
                hello = m
            elif m["type"] == "obs":
                obs.append(m)
    return hello, obs


HELLO, OBS = read_stream()
CFG = HELLO["config"]
HELLO_ARENA = dict(HELLO, map={"dir": ARENA, "files": ["v2/world.json", "v2/terrain.i16"]})
GUN = {"kind": "gun", "cooldown": 0, "ammo": 12, "reload": 0}


def fake_obs(t, pos, in_zone=True, mechs=(), sounds=(), grounded=True, weapons=None):
    return {"tick": int(t * 10), "t": t, "self": {"id": 0, "pos": list(pos), "in_zone": in_zone, "grounded": grounded,
            "weapons": weapons if weapons is not None else [dict(GUN), None]},
            "mechs": list(mechs), "sounds": list(sounds)}


def make_nav(stealth_mode="hide_only", **nav_kw):
    nv = nav.Navigator.create(HELLO_ARENA, nav.NavParams.from_dict(nav_kw), nav.StealthParams(mode=stealth_mode), here=HERE)
    assert nv is not None
    return nv


NV = make_nav()
NM = NV.nm


def main_component_cells():
    cnt = {}
    for k in range(len(NM.blocked)):
        c = NM.comp[k]
        if c:
            cnt[c] = cnt.get(c, 0) + 1
    big = max(cnt, key=cnt.get)
    return [k for k in range(len(NM.blocked)) if NM.comp[k] == big], cnt[big], sum(cnt.values())


MAIN, MAIN_N, FREE_N = main_component_cells()


def pair(rng, lo=100, hi=400):
    while True:
        a, b = rng.choice(MAIN), rng.choice(MAIN)
        ax, ay = NM.center(a)
        bx, by = NM.center(b)
        if lo <= math.hypot(ax - bx, ay - by) <= hi:
            return a, b


def run_trip(nv, a, b, max_ticks=900, move_ok=True, dt=0.1):
    """Kinematic mover: pos += move * walk * dt, stopping when the cell it would enter is blocked."""
    x, y = NM.center(a)
    gx, gy = NM.center(b)
    blocked_samples = 0
    ticks = 0
    worst_ms = 0.0
    for n in range(max_ticks):
        t = n * dt
        z = NM.ground_z(NM.idx(x, y)) if NM.idx(x, y) >= 0 else 0.0
        t0 = time.perf_counter()
        d = nv.step(fake_obs(t, (x, y, z)), (gx, gy, z))
        worst_ms = max(worst_ms, 1000 * (time.perf_counter() - t0))
        ticks += 1
        if math.hypot(gx - x, gy - y) < 6.0:
            return True, ticks, blocked_samples, worst_ms
        mv = d.move if d.move is not None else (gx - x, gy - y)
        L = math.hypot(*mv)
        if L > 1e-6:
            mv = (mv[0] / L * min(1.0, L), mv[1] / L * min(1.0, L))
        nx, ny = x + mv[0] * nv.walk * dt, y + mv[1] * nv.walk * dt
        k = NM.idx(nx, ny)
        if k < 0 or (NM.blocked[k] and move_ok):
            blocked_samples += 1
            if k < 0 or NM.blocked[k]:
                continue                      # wall: do not move
        x, y = nx, ny
    return False, ticks, blocked_samples, worst_ms


class Params(unittest.TestCase):
    def test_partial_and_unknown_keys(self):
        p = nav.NavParams.from_dict({"open_weight": 1.5, "nope": 3})
        self.assertEqual(p.open_weight, 1.5)
        self.assertEqual(p.slice_ms, nav.NavParams().slice_ms)
        s = nav.StealthParams.from_dict({"mode": "off", "quiet_kinds": ["step"]})
        self.assertEqual(s.mode, "off")
        self.assertEqual(s.quiet_kinds, ("step",))
        self.assertEqual(nav.NavParams.from_dict(None).enabled, True)

    def test_disabled_returns_none(self):
        self.assertIsNone(nav.Navigator.create(HELLO_ARENA, nav.NavParams(enabled=False), here=HERE))


class MapTests(unittest.TestCase):
    def test_bake_matches_runtime_build(self):
        m = CFG["mech"]
        built = nav.build_map(ARENA, m["radius"], 0.5, m["step_up"], m["height"])
        self.assertEqual(built.key, NM.key)
        self.assertEqual(bytes(built.blocked), bytes(NM.blocked))
        self.assertEqual(bytes(built.edge), bytes(NM.edge))

    def test_roundtrip(self):
        nm2 = nav.NavMap.loads(NM.dumps())
        self.assertEqual((nm2.W, nm2.H, nm2.key), (NM.W, NM.H, NM.key))
        self.assertEqual(bytes(nm2.blocked), bytes(NM.blocked))
        self.assertEqual(list(nm2.comp[:500]), list(NM.comp[:500]))

    def test_stale_bake_is_rebuilt_not_trusted(self):
        m = CFG["mech"]
        with tempfile.TemporaryDirectory() as d:
            bad = nav.NavMap.loads(NM.dumps())
            bad.key = "0" * 40
            path = os.path.join(d, "navmap.bin")
            with open(path, "wb") as f:
                f.write(bad.dumps())
            nm = nav.load_or_build(ARENA, path, m["radius"], 0.5, m["step_up"], m["height"], 30.0)
            self.assertEqual(nm.key, NM.key)

    def test_missing_files_and_garbage_bake_give_none_not_a_crash(self):
        m = CFG["mech"]
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "navmap.bin"), "wb") as f:
                f.write(b"garbage")
            self.assertIsNone(nav.load_or_build(None, os.path.join(d, "navmap.bin"), m["radius"], 0.5, m["step_up"], m["height"], 5.0))
            self.assertIsNone(nav.load_or_build(d, os.path.join(d, "nope.bin"), m["radius"], 0.5, m["step_up"], m["height"], 5.0))

    def test_build_deadline(self):
        m = CFG["mech"]
        with self.assertRaises(nav.BuildTimeout):
            nav.build_map(ARENA, m["radius"], 0.5, m["step_up"], m["height"], deadline=time.perf_counter() - 1)

    def test_recorded_positions_are_standable(self):
        """Real mechs from the recorded match: almost all stand in cells we call free, and every one snaps to a free cell."""
        pts = []
        for o in OBS:
            pts.append(o["self"]["pos"])
            pts += [m["pos"] for m in o["mechs"] if m["kind"] == "mech"]
        blocked = 0
        for p in pts:
            k = NM.idx(p[0], p[1])
            self.assertGreaterEqual(NM.snap(p[0], p[1], 2), 0)
            if k >= 0 and NM.blocked[k]:
                blocked += 1
        print(f"\n  recorded positions: {len(pts)}, in a blocked 4 m cell: {blocked} ({100 * blocked / len(pts):.1f}%)")
        self.assertLess(blocked / len(pts), 0.06)

    def test_connectivity(self):
        print(f"\n  free cells {FREE_N}, main component {MAIN_N} ({100 * MAIN_N / FREE_N:.1f}%)")
        self.assertGreater(MAIN_N / FREE_N, 0.9)

    def test_ledges_are_directional(self):
        """Some edge must allow a step down but not the step back up (a ledge higher than step_up)."""
        found = 0
        for k in range(len(NM.blocked)):
            if NM.blocked[k]:
                continue
            i, j = k % NM.W, k // NM.W
            if i + 1 < NM.W and not NM.blocked[k + 1]:
                a, b = NM.edge[k] & nav.E, NM.edge[k + 1] & nav.W_
                if bool(a) != bool(b):
                    found += 1
        self.assertGreater(found, 0)


class PathTests(unittest.TestCase):
    def test_random_trips_arrive_without_stuck(self):
        rng = random.Random(7)
        ok, ticks, blocked, worst = 0, [], 0, 0.0
        n = 40
        for _ in range(n):
            nv = make_nav()
            a, b = pair(rng)
            r = run_trip(nv, a, b)
            ok += r[0]
            ticks.append(r[1])
            blocked += r[2]
            worst = max(worst, r[3])
        print(f"\n  trips ok {ok}/{n}, mean ticks {sum(ticks) / n:.0f}, steps into blocked (clearance) cells {blocked}, worst step {worst:.1f} ms")
        self.assertGreaterEqual(ok, int(0.95 * n))
        self.assertLess(worst, 15.0)

    def test_path_length_close_to_straight_line(self):
        rng = random.Random(3)
        ratios = []
        for _ in range(25):
            a, b = pair(rng, 150, 400)
            s = nav._Search(NM, a, b, NV.mult, {})
            s.run(time.perf_counter() + 5.0)
            self.assertTrue(s.found)
            path = s.path()
            ax, ay = NM.center(a)
            bx, by = NM.center(b)
            length = sum(math.dist(NM.center(path[i]), NM.center(path[i + 1])) for i in range(len(path) - 1))
            ratios.append(length / math.hypot(ax - bx, ay - by))
        print(f"\n  path/euclid mean {sum(ratios) / len(ratios):.2f}, max {max(ratios):.2f}  (nav.detour default {nav.NavParams().detour})")
        self.assertLess(sum(ratios) / len(ratios), 1.6)

    def test_search_is_time_sliced_and_resumable(self):
        rng = random.Random(11)
        a, b = pair(rng, 350, 600)
        s = nav._Search(NM, a, b, NV.mult, {})
        slices = 0
        while not s.run(time.perf_counter() + 0.001):
            slices += 1
            self.assertLess(slices, 5000)
        self.assertTrue(s.found)
        s2 = nav._Search(NM, a, b, NV.mult, {})
        s2.run(time.perf_counter() + 30)
        self.assertAlmostEqual(s.g[a], s2.g[a], places=3)       # slicing does not change the answer
        print(f"\n  1 ms slices needed for a {math.dist(NM.center(a), NM.center(b)):.0f} m trip: {slices}")

    def test_exposure_weight_changes_cost_not_validity(self):
        rng = random.Random(5)
        a, b = pair(rng, 200, 400)
        lens = {}
        for w in (0.0, 8.0):
            nv = make_nav(open_weight=w)
            s = nav._Search(NM, a, b, nv.mult, {})
            s.run(time.perf_counter() + 5)
            lens[w] = len(s.path())
            self.assertTrue(s.found)
        self.assertGreaterEqual(lens[8.0], lens[0.0] - 1)       # never shorter by cheating the grid

    def test_threat_pushes_path_away(self):
        rng = random.Random(21)
        for _ in range(40):
            a, b = pair(rng, 250, 450)
            nv = make_nav(open_weight=0.0)
            s = nav._Search(NM, a, b, nv.mult, {})
            s.run(time.perf_counter() + 5)
            p0 = s.path()
            mid = NM.center(p0[len(p0) // 2])
            extra = nv._threat_extra([(mid[0], mid[1], 1.0)], 0.0)
            s2 = nav._Search(NM, a, b, nv.mult, extra)
            s2.run(time.perf_counter() + 5)
            p1 = s2.path()
            d0 = min(math.dist(NM.center(k), mid) for k in p0)
            d1 = min(math.dist(NM.center(k), mid) for k in p1)
            if d1 > d0 + 4:
                return
        self.fail("a threat in the way never moved the path in 40 tries")

    def test_unreachable_goal_gives_no_opinion(self):
        other = next(k for k in range(len(NM.blocked)) if NM.comp[k] and NM.comp[k] != NM.comp[MAIN[0]])
        ox, oy = NM.center(other)
        sx, sy = NM.center(MAIN[0])
        d = make_nav().step(fake_obs(0.0, (sx, sy, 0)), (ox, oy, 0))
        self.assertIsNone(d.move)
        self.assertEqual(d.reason, "goal_unreachable")

    def test_elevated_goal_hands_off_near_the_foot(self):
        sx, sy = NM.center(MAIN[0])
        nv = make_nav()
        d = nv.step(fake_obs(0.0, (sx, sy, 0)), (sx + 8, sy, 20.0))
        self.assertEqual(d.reason, "handoff")
        self.assertGreater(d.move[0], 0.9)

    def test_off_grid_start_falls_back(self):
        d = make_nav().step(fake_obs(0.0, (-5000, 0, 0)), (0, 0, 0))
        self.assertIsNone(d.move)

    def test_garbage_obs_never_raises(self):
        d = make_nav().step({"t": 0}, (0, 0, 0))
        self.assertIsNone(d.move)
        self.assertTrue(d.reason.startswith("nav_error"))


class StealthTests(unittest.TestCase):
    def setUp(self):
        self.x, self.y = NM.center(MAIN[len(MAIN) // 2])

    def goal_near(self, d=5.0):
        return (self.x + d, self.y, 0.0)

    def test_hold_at_default_goal(self):
        d = make_nav("hide_only").step(fake_obs(0.0, (self.x, self.y, 0)), self.goal_near(), default_goal=True)
        self.assertTrue(d.hold)
        self.assertEqual(d.move, (0.0, 0.0))
        self.assertFalse(d.boost_ok)

    def test_no_hold_for_loot_goal_or_when_off_or_outside_zone_or_enemy_visible(self):
        o = fake_obs(0.0, (self.x, self.y, 0))
        self.assertFalse(make_nav("hide_only").step(o, self.goal_near(), default_goal=False).hold)
        self.assertFalse(make_nav("off").step(o, self.goal_near(), default_goal=True).hold)
        o2 = fake_obs(0.0, (self.x, self.y, 0), in_zone=False)
        self.assertFalse(make_nav("hide_only").step(o2, self.goal_near(), default_goal=True).hold)
        o3 = fake_obs(0.0, (self.x, self.y, 0), mechs=[{"kind": "mech", "id": 4, "pos": [self.x + 30, self.y, 0]}])
        self.assertFalse(make_nav("hide_only").step(o3, self.goal_near(), default_goal=True).hold)

    def test_hold_radius_boundary(self):
        o = fake_obs(0.0, (self.x, self.y, 0))
        self.assertTrue(make_nav("hide_only").step(o, self.goal_near(14.9), default_goal=True).hold)
        self.assertFalse(make_nav("hide_only").step(o, self.goal_near(15.5), default_goal=True).hold)

    def test_always_creeps_under_the_step_threshold(self):
        k = MAIN[len(MAIN) // 3]
        x, y = NM.center(k)
        far = None
        for k2 in MAIN:
            if 120 < math.dist(NM.center(k2), (x, y)) < 200:
                far = k2
                break
        gx, gy = NM.center(far)
        nv = make_nav("always")
        d = None
        for n in range(80):                      # let the search finish
            d = nv.step(fake_obs(n * 0.1, (x, y, 0)), (gx, gy, 0))
            if d.move is not None:
                break
        self.assertIsNotNone(d.move)
        speed = math.hypot(*d.move) * CFG["mech"]["walk_speed"]
        self.assertLess(speed, 5.0)
        self.assertGreater(speed, 4.0)
        self.assertFalse(d.boost_ok)

    def test_near_threat_creeps_only_on_a_near_quiet_sound(self):
        k = MAIN[len(MAIN) // 3]
        x, y = NM.center(k)
        far = next(k2 for k2 in MAIN if 120 < math.dist(NM.center(k2), (x, y)) < 200)
        gx, gy = NM.center(far)
        for sounds, creeps in (([], False), ([{"kind": "step", "dist": "near", "age": 0.5, "bearing": 0}], True),
                               ([{"kind": "step", "dist": "far", "age": 0.5, "bearing": 0}], False),
                               ([{"kind": "step", "dist": "near", "age": 9.0, "bearing": 0}], False),
                               ([{"kind": "gun", "dist": "near", "age": 0.1, "bearing": 0}], False)):
            nv = make_nav("near_threat")
            d = None
            for n in range(80):
                d = nv.step(fake_obs(n * 0.1, (x, y, 0), sounds=sounds), (gx, gy, 0))
                if d.move is not None:
                    break
            self.assertEqual(d.boost_ok, not creeps, sounds)


class StuckTests(unittest.TestCase):
    def test_stuck_recovery_cycles_jump_jet_side(self):
        rng = random.Random(2)
        a, b = pair(rng, 150, 300)
        x, y = NM.center(a)
        gx, gy = NM.center(b)
        nv = make_nav()
        kinds = []
        for n in range(200):                      # the mech never moves
            d = nv.step(fake_obs(n * 0.1, (x, y, 0)), (gx, gy, 0))
            if d.reason.startswith("unstick_") and (not kinds or kinds[-1] != d.reason):
                kinds.append(d.reason)
        self.assertGreaterEqual(len(kinds), 3, kinds)
        self.assertEqual(kinds[:3], ["unstick_jump", "unstick_jet", "unstick_side"])

    def test_no_false_stuck_when_walking_or_charging_laser(self):
        rng = random.Random(9)
        a, b = pair(rng, 250, 400)
        nv = make_nav()
        r = run_trip(nv, a, b)
        self.assertTrue(r[0])
        self.assertEqual(nv.stat["stuck"], 0)

    def test_idle_by_choice_is_not_stuck(self):
        x, y = NM.center(MAIN[10])
        nv = make_nav("hide_only")
        for n in range(60):
            d = nv.step(fake_obs(n * 0.1, (x, y, 0)), (x + 3, y, 0), default_goal=True)
        self.assertTrue(d.hold)
        self.assertEqual(nv.stat["stuck"], 0)


class PathCostTests(unittest.TestCase):
    def test_same_component_is_euclid_times_detour(self):
        a, b = MAIN[100], MAIN[900]
        (ax, ay), (bx, by) = NM.center(a), NM.center(b)
        length, expo = NV.path_cost((ax, ay, NM.ground_z(a)), (bx, by, NM.ground_z(b)))
        self.assertAlmostEqual(length, math.hypot(ax - bx, ay - by) * NV.p.detour, places=3)
        self.assertTrue(0.0 <= expo <= 1.0)

    def test_other_component_is_none(self):
        other = next(k for k in range(len(NM.blocked)) if NM.comp[k] and NM.comp[k] != NM.comp[MAIN[0]])
        (ax, ay), (bx, by) = NM.center(MAIN[0]), NM.center(other)
        self.assertEqual(NV.path_cost((ax, ay, NM.ground_z(MAIN[0])), (bx, by, NM.ground_z(other)))[0], None)

    def test_roof_pickup_is_not_called_unreachable(self):
        # a point inside a building footprint, high above the ground
        k = next(k for k in range(len(NM.blocked)) if NM.blocked[k] and k % NM.W > 5 and (k // NM.W) > 5)
        x, y = NM.center(k)
        length, _ = NV.path_cost(NM.center(MAIN[0]) + (0.0,), (x, y, NM.ground_z(k) + 20.0))
        self.assertIsNotNone(length)

    def test_garbage_does_not_raise(self):
        self.assertIsNotNone(NV.path_cost((0, 0), (1e9, 1e9))[0])


class Timing(unittest.TestCase):
    def test_replayed_observations_step_time(self):
        nv = make_nav()
        times = []
        for o in OBS:
            me = o["self"]
            gx, gy = o["zone"]["next_center"]
            t0 = time.perf_counter()
            nv.step(o, (gx, gy, 0.0), default_goal=True)
            times.append(1000 * (time.perf_counter() - t0))
        times.sort()
        print(f"\n  recorded stream, {len(times)} steps: p50 {times[len(times) // 2]:.2f} ms, p99 {times[int(len(times) * .99)]:.2f} ms, max {times[-1]:.2f} ms")
        self.assertLess(times[-1], 15.0)

    def test_create_never_raises(self):
        self.assertIsNone(nav.Navigator.create({}, nav.NavParams()))
        self.assertIsNone(nav.Navigator.create({"config": {}}, nav.NavParams()))


if __name__ == "__main__":
    unittest.main(verbosity=1)
