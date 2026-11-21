"""Tests for engage.py (H-ENG / H-REG). Run from the repo root:  python3 test_engage.py   (or: python3 -m unittest test_engage -v)"""
import copy
import gzip
import json
import math
import os
import time
import unittest

import engage as E

KIT = os.environ.get("KIT", os.path.join(os.path.dirname(os.path.abspath(__file__)), "kit"))


def load_stream():
    with gzip.open(os.path.join(KIT, "check", "stream.jsonl.gz"), "rt") as f:
        return [json.loads(l) for l in f]


STREAM = load_stream()
HELLO = STREAM[0]
OBS = [m for m in STREAM if m.get("type") == "obs"]


def make_obs(hp=1400, max_hp=1400, weapons=None, cubes=0, enemies=(), t=30.0, alive=8, pos=(0.0, 0.0, 0.0), aim=0.0,
            events=(), in_zone=True, energy=100):
    """Synthetic obs on top of a real recorded one so every field exists."""
    o = copy.deepcopy(OBS[0])
    me = o["self"]
    me.update(pos=list(pos), hp=hp, max_hp=max_hp, cubes=cubes, aim=[aim, 0.0], energy=energy, in_zone=in_zone)
    gun = {"kind": "gun", "cooldown": 0.0, "ammo": 12, "reload": 0.0, "stats": dict(HELLO["config"]["weapons"]["gun"])}
    ws = [gun, None]
    for kind in (weapons or []):
        c = dict(HELLO["config"]["weapons"][kind])
        ws[1] = {"kind": kind, "cooldown": 0.0, "stats": c}
        if kind == "laser":
            ws[1]["charge"] = 0.0
    me["weapons"] = ws
    o.update(t=t, alive=alive, events=list(events), projectiles=[], sounds=[], beams=[], crates=[], cubes=[], pickups=[])
    o["zone"] = {"center": [0, 0], "radius": 560, "next_center": [0, 0], "next_radius": 380, "shrink_start": 60,
                 "shrink_end": 110, "dps": 20}
    o["mechs"] = list(enemies)
    return o


def enemy(eid=5, dist=60.0, bear=0.0, hp=1400, max_hp=1400, cubes=0, weapons=("gun",), face_me=True, pos0=(0.0, 0.0, 0.0)):
    x = pos0[0] + dist * math.cos(bear)
    y = pos0[1] + dist * math.sin(bear)
    aim = bear + math.pi if face_me else bear  # facing me, or facing away from me
    return {"id": eid, "kind": "mech", "pos": [x, y, 0.0], "vel": [0, 0, 0], "aim": [aim, 0.0], "hp": hp, "max_hp": max_hp,
            "cubes": cubes, "weapons": list(weapons), "charging": False}


def ratio(obs, eng=None, target_idx=0):
    eng = eng or E.Engagement(HELLO)
    tgt = obs["mechs"][target_idx]
    res, _ = eng.evaluate(obs, tgt, obs["mechs"])
    return res


class TestEstimator(unittest.TestCase):
    def test_symmetric_gun_duel_is_near_even(self):
        r = ratio(make_obs(enemies=[enemy(dist=60)])).ratio
        self.assertTrue(0.7 < r < 1.3, r)

    def test_ratio_monotone_in_enemy_hp(self):
        lo = ratio(make_obs(enemies=[enemy(hp=400)])).ratio
        hi = ratio(make_obs(enemies=[enemy(hp=1400)])).ratio
        self.assertGreater(lo, hi)

    def test_ratio_monotone_in_my_hp(self):
        a = ratio(make_obs(hp=500, enemies=[enemy()])).ratio
        b = ratio(make_obs(hp=1400, enemies=[enemy()])).ratio
        self.assertGreater(b, a)

    def test_enemy_cubes_hurt(self):
        a = ratio(make_obs(enemies=[enemy(cubes=0)])).ratio
        b = ratio(make_obs(enemies=[enemy(cubes=10)])).ratio
        self.assertGreater(a, b)

    def test_rear_armor_window_helps(self):
        away = ratio(make_obs(enemies=[enemy(face_me=False)]))
        toward = ratio(make_obs(enemies=[enemy(face_me=True)]))
        self.assertGreater(away.ratio, toward.ratio)
        self.assertLessEqual(away.ttk_target, toward.ttk_target)

    def test_rear_window_math(self):
        # attacker directly behind defender: gap=pi, half arc=pi/2 -> (pi/2)/4 rad/s + reaction
        w = E.rear_window((-10, 0), (0, 0), 0.0, 4.0, 180.0, 0.25)
        self.assertAlmostEqual(w, 0.25 + (math.pi / 2) / 4.0, places=6)
        self.assertEqual(E.rear_window((10, 0), (0, 0), 0.0, 4.0, 180.0, 0.25), 0.0)

    def test_lightning_shorts_laser(self):
        e = enemy(dist=30, weapons=("gun", "laser"))
        base = ratio(make_obs(enemies=[e])).ratio
        with_l = ratio(make_obs(weapons=["lightning"], enemies=[e])).ratio
        self.assertGreater(with_l, base)

    def test_laser_cooks_off_mortar_holder(self):
        e_m = enemy(dist=80, weapons=("gun", "mortar"))
        e_g = enemy(dist=80, weapons=("gun",))
        self.assertGreater(ratio(make_obs(weapons=["laser"], enemies=[e_m])).ratio * 0 + 1, 0)  # smoke
        r_m = ratio(make_obs(weapons=["laser"], enemies=[e_m])).ttk_target
        r_g = ratio(make_obs(weapons=["laser"], enemies=[e_g])).ttk_target
        self.assertLess(r_m, r_g)  # laser kills a mortar holder faster (x1.6)

    def test_mortar_loses_to_laser_up_close(self):
        e = enemy(dist=30, weapons=("gun", "laser"))
        mortar = ratio(make_obs(weapons=["mortar"], enemies=[e])).ratio
        laser = ratio(make_obs(weapons=["laser"], enemies=[e])).ratio
        self.assertLess(mortar, laser)

    def test_out_of_zone_adds_cost(self):
        a = ratio(make_obs(enemies=[enemy()], in_zone=True)).ratio
        b = ratio(make_obs(enemies=[enemy()], in_zone=False)).ratio
        self.assertGreater(a, b)

    def test_joiners_lower_ratio(self):
        one = ratio(make_obs(enemies=[enemy(5, 60)])).ratio
        two = ratio(make_obs(enemies=[enemy(5, 60), enemy(6, 80, bear=1.0)])).ratio
        self.assertLess(two, one)

    def test_armor_stat_counts(self):
        o = make_obs(enemies=[enemy()])
        a = ratio(o).ratio
        o["self"]["stats"]["armor"] = 0.24
        self.assertGreater(ratio(o).ratio, a)

    def test_unkillable_target_is_not_a_fight(self):
        o = make_obs(enemies=[enemy(dist=60)])
        o["self"]["weapons"][0]["stats"]["damage"] = 0.01
        self.assertLess(ratio(o).ratio, 0.1)


class StubOcc:
    """Wall along x=30 for |y|<500: LOS is blocked across it. Ground flat, everything walkable except the wall."""
    def los(self, a, b):
        return not ((a[0] - 30.0) * (b[0] - 30.0) < 0)
    def ground(self, x, y):
        return 0.0
    def walkable(self, x, y):
        return abs(x - 30.0) > 1.0


class TestStateMachine(unittest.TestCase):
    def mk(self, **kw):
        return E.Engagement(HELLO, occluder=StubOcc(), **kw)

    def test_neutral_to_engage_when_favourable(self):
        eng = self.mk()
        d = eng.update(make_obs(enemies=[enemy(hp=300, dist=60)], alive=4))
        self.assertEqual(d.mode, "engage", d.diag)

    def test_no_engage_when_even(self):
        eng = self.mk()
        d = eng.update(make_obs(enemies=[enemy(dist=60)], alive=4))
        self.assertEqual(d.mode, "neutral", d.diag)

    def test_early_game_bar_is_higher(self):
        # same fight, engage late-game but not at alive=16
        e = enemy(hp=700, dist=60)
        late = self.mk().update(make_obs(enemies=[e], alive=4)).diag["thr"]
        early = self.mk().update(make_obs(enemies=[e], alive=16)).diag["thr"]
        self.assertGreater(early, late)

    def test_hysteresis(self):
        eng = self.mk()
        # find an enemy hp where R sits between disengage (1.0) and engage (~1.4)
        lo, hi = 200, 1400
        for _ in range(30):
            mid = (lo + hi) // 2
            R = eng.update(make_obs(enemies=[enemy(hp=mid)], alive=4, t=1.0)).diag.get("R")
            eng = self.mk()
            if R is None:
                break
            if R > 1.2:
                lo = mid
            else:
                hi = mid
        e = enemy(hp=hi)
        eng = self.mk()
        # not engaged: needs engage bar
        d0 = eng.update(make_obs(enemies=[e], alive=4, t=1.0))
        self.assertTrue(1.0 < d0.diag["R"] < 1.4, d0.diag)
        self.assertEqual(d0.mode, "neutral")
        # once engaged by force, it stays while R > disengage bar
        eng.mode, eng.mode_since, eng.target = "engage", 0.0, e["id"]
        d1 = eng.update(make_obs(enemies=[e], alive=4, t=3.0))
        self.assertEqual(d1.mode, "engage", d1.diag)

    def test_low_hp_retreats_then_regens(self):
        eng = self.mk()
        eng.mode, eng.mode_since, eng.target = "engage", 0.0, 5
        e = enemy(dist=40, bear=0.0)   # east of us, wall at x=30 is between us and the *far* side only
        e["pos"][0] = -40.0            # put enemy WEST so fleeing east crosses the wall
        d = eng.update(make_obs(hp=300, enemies=[e], t=5.0, alive=6))
        self.assertEqual(d.mode, "retreat", d.diag)
        self.assertTrue(d.hold_fire)
        self.assertIsNotNone(d.goal)
        self.assertGreater(d.move[0], 0.0)  # away from the enemy (east)
        # walk the sim: teleport behind the wall, enemy out of view -> regen
        for step in range(40):
            o = make_obs(hp=300, enemies=[], pos=(d.goal[0] if d.goal else 60, d.goal[1] if d.goal else 0, 0), t=6.0 + step * 0.1)
            o["events"] = []
            dd = eng.update(o)
            if dd.mode == "regen":
                break
        self.assertEqual(eng.mode, "regen", dd.diag)
        self.assertEqual(dd.speed, 0.0)
        self.assertTrue(dd.hold_fire)

    def test_regen_resumes_at_threshold(self):
        eng = self.mk()
        eng.mode, eng.regen_start_t = "regen", 0.0
        d = eng.update(make_obs(hp=1300, t=30.0))
        self.assertEqual(d.mode, "neutral")
        eng.mode = "regen"
        d = eng.update(make_obs(hp=600, t=30.0))
        self.assertEqual(d.mode, "regen")

    def test_regen_interrupted_by_hopeless_fight_retreats_again(self):
        eng = self.mk()
        eng.mode, eng.regen_start_t = "regen", 0.0
        d = eng.update(make_obs(hp=500, enemies=[enemy(dist=50)], t=20.0))
        self.assertEqual(d.mode, "retreat", d.diag)

    def test_finishing_blow_overrides_low_hp(self):
        eng = self.mk()
        eng.mode, eng.mode_since, eng.target = "engage", 0.0, 5
        d = eng.update(make_obs(hp=380, enemies=[enemy(hp=60, dist=50)], t=10.0, alive=5))
        # hp_frac 0.27 < retreat floor, but one burst finishes it
        self.assertEqual(d.mode, "engage", d.diag)

    def test_lockout_blocks_reengage(self):
        eng = self.mk()
        eng.lockout[5] = 100.0
        d = eng.update(make_obs(enemies=[enemy(hp=100)], t=10.0, alive=4))
        self.assertEqual(d.mode, "neutral")

    def test_phantom_triggers_retreat(self):
        eng = self.mk()
        ev = [{"type": "damaged", "amount": 90, "weapon": "gun", "bearing": math.pi, "by": 9, "rear": False}]
        d = eng.update(make_obs(enemies=[], events=ev, t=12.0))
        self.assertEqual(d.mode, "retreat", d.diag)
        self.assertGreater(d.move[0], 0.0)

    def test_zone_damage_does_not_make_phantom(self):
        eng = self.mk()
        ev = [{"type": "damaged", "amount": 20, "weapon": "zone", "bearing": None, "by": None}]
        d = eng.update(make_obs(enemies=[], events=ev, t=12.0))
        self.assertEqual(d.mode, "neutral")

    def test_regen_eta(self):
        eng = self.mk()
        eng.last_combat_t = 10.0
        o = make_obs(hp=700, t=12.0)
        # 3 s of delay left + (0.85*1400 - 700)/45
        self.assertAlmostEqual(eng.regen_eta(o, 0.85), 3.0 + (0.85 * 1400 - 700) / 45.0, places=6)

    def test_nanites_stats_flow_into_eta(self):
        eng = self.mk()
        eng.last_combat_t = 0.0
        o = make_obs(hp=700, t=10.0)
        o["self"]["stats"]["regen_per_s"] = 72.0
        o["self"]["stats"]["regen_delay"] = 3.5
        self.assertAlmostEqual(eng.regen_eta(o, 0.85), (0.85 * 1400 - 700) / 72.0, places=6)

    def test_predicted_enemy_regen(self):
        eng = self.mk()
        eng.last_seen[5] = {"t": 10.0, "hp": 500, "max_hp": 1400}
        self.assertEqual(eng.predicted_enemy_hp(5, 14.0), 500)           # still inside the 5 s delay
        self.assertEqual(eng.predicted_enemy_hp(5, 25.0), 500 + 10 * 45)  # 15 s - 5 s delay
        self.assertEqual(eng.predicted_enemy_hp(5, 200.0), 1400)

    def test_decision_apply_merges_only_owned_fields(self):
        eng = self.mk()
        eng.mode = "regen"
        d = eng.update(make_obs(hp=500, t=40.0))
        act = d.apply({"tick": 1, "move": [1, 0], "fire": [True, True], "aim": [0.0, 0.0]})
        self.assertEqual(act["move"], [0.0, 0.0])
        self.assertEqual(act["fire"], [False, False])


class TestParams(unittest.TestCase):
    def test_partial_override_and_junk_ignored(self):
        p = E.params_from_dict({"engage_ratio": 1.9, "refuge_rings": [10, 20], "nope": 1, "_note": "x",
                                "hit_gun": "bad", "auto_regen": 0})
        self.assertEqual(p["engage_ratio"], 1.9)
        self.assertEqual(p["refuge_rings"], (10.0, 20.0))
        self.assertEqual(p["hit_gun"], E.PARAMS["hit_gun"])
        self.assertFalse(p["auto_regen"])
        self.assertNotIn("nope", p)
        self.assertEqual(E.params_from_dict(None)["engage_ratio"], E.PARAMS["engage_ratio"])
        self.assertEqual(E.params_from_dict({"engage_ratio": True})["engage_ratio"], E.PARAMS["engage_ratio"])


class TestSeenIsGroundTruth(unittest.TestCase):
    def test_visible_enemy_blocks_regen_and_marks_bad_spot(self):
        eng = E.Engagement(HELLO, occluder=StubOcc())
        d = eng.update(make_obs(hp=300, enemies=[enemy(dist=40, bear=math.pi)], t=5.0, alive=6))
        self.assertEqual(d.mode, "retreat")
        at = (d.goal[0], d.goal[1], 0.0)
        # model says hidden (behind the stub wall) but the enemy is still in obs.mechs: not hidden
        e = enemy(dist=40, bear=math.pi, pos0=at)
        d2 = eng.update(make_obs(hp=300, enemies=[e], t=6.0, pos=at, alive=6))
        self.assertEqual(d2.mode, "retreat")
        self.assertTrue(d2.diag.get("bad_spot"))
        self.assertEqual(len(eng.bad_spots), 1)

    def test_no_flapping_between_retreat_and_regen(self):
        eng = E.Engagement(HELLO, occluder=StubOcc())
        d = eng.update(make_obs(hp=300, enemies=[enemy(dist=40, bear=math.pi)], t=5.0, alive=6))
        pos = (d.goal[0], d.goal[1], 0.0)
        flips = 0
        prev = d.mode
        for i in range(60):          # enemy permanently visible from the refuge: no regen at all
            e = enemy(dist=40, bear=math.pi, pos0=pos)
            dd = eng.update(make_obs(hp=300, enemies=[e], t=6.0 + 0.1 * i, pos=pos, alive=6))
            flips += dd.mode != prev
            prev = dd.mode
            if dd.goal:
                pos = (dd.goal[0], dd.goal[1], 0.0)
        self.assertEqual(flips, 0)
        self.assertEqual(prev, "retreat")


class TestAvoidAndAutoRegen(unittest.TestCase):
    def mk(self, **over):
        return E.Engagement(HELLO, params=E.params_from_dict(over), occluder=StubOcc())

    def hopeless(self, dist=60.0, **kw):
        return make_obs(enemies=[enemy(dist=dist, weapons=("gun", "lightning"), bear=math.pi, pos0=(0, 0, 0))], alive=4, **kw)

    def test_avoid_hopeless_matchup_before_it_starts(self):
        d = self.mk().update(self.hopeless())
        self.assertEqual(d.mode, "retreat", d.diag)
        self.assertEqual(d.reason, "avoid")
        self.assertGreater(d.move[0], 0.0)   # enemy is west, run east

    def test_no_avoid_when_far_or_disabled(self):
        self.assertEqual(self.mk().update(self.hopeless(dist=150.0)).mode, "neutral")
        self.assertEqual(self.mk(avoid_ratio=0.0).update(self.hopeless()).mode, "neutral")

    def test_auto_regen_holds_still_without_memory(self):
        d = self.mk().update(make_obs(hp=600, t=40.0))
        self.assertEqual(d.mode, "regen", d.diag)
        self.assertEqual(d.speed, 0.0)
        self.assertTrue(d.hold_fire)

    def test_auto_regen_hides_from_last_known_threat_then_holds(self):
        eng = self.mk()
        eng.last_threat_pos, eng.last_threat_t = [-60.0, 0.0, 0.0], 38.0
        d = eng.update(make_obs(hp=600, t=40.0))
        self.assertEqual(d.mode, "retreat", d.diag)
        self.assertIsNotNone(d.goal)
        self.assertGreater(d.goal[0], 30.0)  # behind the stub wall at x=30
        at = (d.goal[0], d.goal[1], 0.0)
        d1 = eng.update(make_obs(hp=600, t=41.5, pos=at))
        self.assertEqual(d1.mode, "retreat", d1.diag)           # arrived, but the unseen timer has not matured
        self.assertEqual(d1.goal, d.goal)                       # and it does not wander off to another refuge
        d2 = eng.update(make_obs(hp=600, t=42.2, pos=at))
        self.assertEqual(d2.mode, "regen", d2.diag)

    def test_auto_regen_off_outside_zone_or_when_healthy_or_disabled(self):
        self.assertEqual(self.mk().update(make_obs(hp=600, in_zone=False, t=40.0)).mode, "neutral")
        self.assertEqual(self.mk().update(make_obs(hp=1300, t=40.0)).mode, "neutral")
        self.assertEqual(self.mk(auto_regen=False).update(make_obs(hp=600, t=40.0)).mode, "neutral")

    def test_regen_does_not_flap_back_into_auto_regen(self):
        eng = self.mk()
        eng.update(make_obs(hp=600, t=40.0))
        self.assertEqual(eng.mode, "regen")
        eng.update(make_obs(hp=1250, t=60.0))           # >= 0.85: leaves regen
        self.assertEqual(eng.mode, "neutral")
        eng.update(make_obs(hp=1250, t=60.1))           # above the 0.6 roam bar: stays neutral
        self.assertEqual(eng.mode, "neutral")

    def test_reload_uses_gun_slot_lookup(self):
        eng = self.mk()
        o = make_obs(hp=600, t=40.0)
        gun = o["self"]["weapons"][0]
        gun["ammo"] = 3
        o["self"]["weapons"] = [{"kind": "lightning", "cooldown": 0.0, "stats": dict(HELLO["config"]["weapons"]["lightning"])}, gun]
        d = eng.update(o)
        self.assertEqual(d.mode, "regen")
        self.assertTrue(d.reload)


class TestOccluder(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        t0 = time.perf_counter()
        cls.occ = E.Occluder(os.path.join(KIT, "arena"))
        cls.load_s = time.perf_counter() - t0

    def test_load_budget(self):
        self.assertLess(self.load_s, 3.0)  # must fit inside the 20 s ready window with huge margin

    def test_building_blocks_los_through_it_but_not_over_it(self):
        pr = next(p for p in self.occ.prisms if p[7] - p[6] > 12 and p[6] < 1.0)  # a tall building from the ground
        cx = (pr[0] + pr[2]) / 2
        cy = (pr[1] + pr[3]) / 2
        # find a point inside the footprint
        import random
        rnd = random.Random(1)
        inside = None
        for _ in range(2000):
            x, y = rnd.uniform(pr[0], pr[2]), rnd.uniform(pr[1], pr[3])
            if E._in_prism_xy(pr, x, y):
                inside = (x, y)
                break
        self.assertIsNotNone(inside)
        g = self.occ.ground(*inside)
        a = (pr[0] - 15, inside[1], g + 6)
        b = (pr[2] + 15, inside[1], g + 6)
        self.assertFalse(self.occ.los(a, b))
        a2 = (a[0], a[1], pr[7] + 20)
        b2 = (b[0], b[1], pr[7] + 20)
        self.assertTrue(self.occ.los(a2, b2))

    def test_los_symmetric_on_random_pairs(self):
        import random
        rnd = random.Random(7)
        for _ in range(200):
            a = (rnd.uniform(-200, 200), rnd.uniform(-150, 150), 8.0)
            b = (rnd.uniform(-200, 200), rnd.uniform(-150, 150), 8.0)
            self.assertEqual(self.occ.los(a, b), self.occ.los(b, a))

    def test_los_cost(self):
        import random
        rnd = random.Random(3)
        pts = [((rnd.uniform(-200, 200), rnd.uniform(-150, 150), 8.0), (rnd.uniform(-200, 200), rnd.uniform(-150, 150), 8.0)) for _ in range(300)]
        t0 = time.perf_counter()
        for a, b in pts:
            self.occ.los(a, b)
        per = (time.perf_counter() - t0) / len(pts) * 1000
        print(f"\n  LOS avg {per:.3f} ms/query")
        self.assertLess(per, 1.0)


class TestBudget(unittest.TestCase):
    def test_recorded_stream_runs_clean_and_fast(self):
        occ = E.Occluder(os.path.join(KIT, "arena"))
        eng = E.Engagement(HELLO, occluder=occ)
        worst = 0.0
        modes = {}
        for o in OBS:
            t0 = time.perf_counter()
            d = eng.update(o)
            worst = max(worst, (time.perf_counter() - t0) * 1000)
            modes[d.mode] = modes.get(d.mode, 0) + 1
        print(f"\n  recorded stream: worst update {worst:.2f} ms, modes {modes}, stats {eng.stats}")
        self.assertLess(worst, 30.0)

    def test_retreat_replan_under_budget_with_real_map(self):
        occ = E.Occluder(os.path.join(KIT, "arena"))
        eng = E.Engagement(HELLO, occluder=occ)
        o = make_obs(hp=250, pos=(-100.0, -20.0, occ.ground(-100.0, -20.0)),
                     enemies=[enemy(5, 50, 0.3, pos0=(-100.0, -20.0, 0)), enemy(6, 70, 2.0, pos0=(-100.0, -20.0, 0))], t=20.0, alive=5)
        eng.mode, eng.mode_since = "engage", 0.0
        t0 = time.perf_counter()
        d = eng.update(o)
        ms = (time.perf_counter() - t0) * 1000
        print(f"\n  retreat start update {ms:.2f} ms, mode {d.mode}, refuge_ms_max {eng.stats['refuge_ms_max']:.2f}")
        self.assertEqual(d.mode, "retreat")
        self.assertLess(ms, 30.0)



class TestLateGame(unittest.TestCase):
    def test_late_game_lowers_bar(self):
        e = enemy(hp=700)
        mid = E.Engagement(HELLO).update(make_obs(enemies=[e], alive=6)).diag["thr"]
        late = E.Engagement(HELLO).update(make_obs(enemies=[e], alive=3)).diag["thr"]
        self.assertAlmostEqual(late / mid, 0.8, places=2)


class TestDistracted(unittest.TestCase):
    def test_distracted_enemy_widens_rear_window(self):
        eng = E.Engagement(HELLO)
        e = enemy(face_me=False)
        o1 = make_obs(enemies=[e], t=10.0)
        eng.update(o1)  # registers away_since=10.0
        o2 = make_obs(enemies=[e], t=11.0)
        eng._ingest(o2)
        side = eng._enemy_side(o2["mechs"][0], o2["self"], 11.0, 1.0, True)
        fresh = E.Engagement(HELLO)._enemy_side(o2["mechs"][0], o2["self"], 11.0, 1.0, True)
        self.assertAlmostEqual(side.rear_window - fresh.rear_window, 2.0, places=6)


if __name__ == "__main__":
    unittest.main(verbosity=2)
