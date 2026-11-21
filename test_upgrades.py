"""Tests for the H-UPG policy.  Run:  python3 test_upgrades.py [STREAM.jsonl.gz]   (default stream: kit/check/stream.jsonl.gz)
(the recorded stream only supplies hello.config; it contains no offers, so check.py never exercises pick()).
"""
import copy
import gzip
import itertools
import json
import os
import sys
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from upgrades import DEFAULTS, UpgradePolicy, load_params  # noqa: E402

STREAM = os.path.join(HERE, "kit", "check", "stream.jsonl.gz")
if len(sys.argv) > 1 and os.path.exists(sys.argv[1]):
    STREAM = sys.argv.pop(1)


def load_stream():
    hello, obs = None, []
    with gzip.open(STREAM, "rt") as f:
        for line in f:
            m = json.loads(line)
            if m.get("type") == "hello":
                hello = m
            elif m.get("type") == "obs":
                obs.append(m)
    return hello, obs


HELLO, OBS = load_stream()
CFG = HELLO["config"]


def mk_obs(choices, held=("gun",), stacks=(), cubes=3, t=140.0, alive=11, zdps=20.0, oid=1):
    weapons = [{"kind": k} for k in held] + [None] * (2 - len(held))
    return {"type": "obs", "tick": 1, "t": t, "alive": alive,
            "self": {"cubes": cubes, "upgrades": list(stacks), "weapons": weapons},
            "zone": {"dps": zdps},
            "offer": {"id": oid, "expires": t + 5, "choices": [{"id": c, "name": c, "desc": ""} for c in choices]}}


class T(unittest.TestCase):
    def setUp(self):
        self.pol = UpgradePolicy(CFG)

    # ---- plumbing ----
    def test_config_has_22_upgrades(self):
        self.assertEqual(len(self.pol.defs), 22)

    def test_apply_matches_hand_math(self):
        s = self.pol.apply({"plating": 2, "armor": 3, "nanites": 2, "gun_mag": 2, "sensors": 2, "lightning_efficiency": 2})
        self.assertAlmostEqual(s["mech"]["hp"], 1400 * 1.15 ** 2)
        self.assertAlmostEqual(s["mech"]["armor"], 0.24)
        self.assertAlmostEqual(s["mech"]["regen_per_s"], 45 * 1.6 ** 2)
        self.assertAlmostEqual(s["mech"]["regen_delay"], 2.0)
        self.assertEqual(s["weapons"]["gun"]["mag"], 28)
        self.assertAlmostEqual(s["weapons"]["gun"]["reload"], 2.4 * 0.64)
        self.assertAlmostEqual(s["mech"]["hearing"], 0.25)
        self.assertAlmostEqual(s["weapons"]["lightning"]["energy"], 3 * 0.65 ** 2)

    def test_apply_does_not_mutate_base(self):
        before = json.dumps(self.pol.base, sort_keys=True)
        self.pol.apply({"plating": 3, "gun_mag": 2})
        self.assertEqual(before, json.dumps(self.pol.base, sort_keys=True))

    def test_params_json_section_is_valid_partial_override(self):
        with open(os.path.join(HERE, "params.json")) as f:
            sec = json.load(f)["upgrades"]
        p = load_params(sec)
        for k, v in sec.items():
            if k.startswith("_") or k == "enabled":
                continue
            self.assertIn(k, DEFAULTS, f"unknown knob {k} in params.json upgrades section")
            self.assertEqual(p[k], v)
        UpgradePolicy(CFG, sec)      # constructs

    def test_load_params_partial_override(self):
        p = load_params({"w_dps": 1.0, "uptime": {"gun": 0.5}, "state_scale": {"early": {"w_dps": 0.1}}})
        self.assertEqual(p["w_dps"], 1.0)
        self.assertEqual(p["uptime"]["gun"], 0.5)
        self.assertEqual(p["uptime"]["laser"], DEFAULTS["uptime"]["laser"])   # untouched sibling
        self.assertEqual(p["state_scale"]["early"]["w_dps"], 0.1)
        self.assertEqual(p["state_scale"]["early"]["regen_cycles"], DEFAULTS["state_scale"]["early"]["regen_cycles"])

    # ---- protocol behaviour ----
    def test_none_without_offer_on_recorded_stream(self):
        for o in OBS:
            self.assertIsNone(self.pol.pick(o))

    def test_pick_is_valid_index_for_all_offers(self):
        ids = sorted(self.pol.defs)
        for held in (["gun"], ["gun", "mortar"], ["gun", "laser"], ["gun", "lightning"]):
            elig = [u for u in ids if not self.pol.defs[u].get("requires") or self.pol.defs[u]["requires"] in held]
            for trio in itertools.combinations(elig, 3):
                p = UpgradePolicy(CFG)
                i = p.pick(mk_obs(trio, held=held))
                self.assertIn(i, (0, 1, 2))

    def test_idempotent_per_offer_id(self):
        o = mk_obs(["armor", "plating", "servos"], oid=7)
        first = self.pol.pick(o)
        o2 = mk_obs(["armor", "plating", "servos"], oid=7, cubes=12, alive=2, zdps=200)   # state changed, same offer
        self.assertEqual(self.pol.pick(o2), first)
        o3 = mk_obs(["servos", "armor", "plating"], oid=8)                                # next offer is re-evaluated
        self.assertIn(self.pol.pick(o3), (0, 1, 2))

    def test_never_raises_on_garbage(self):
        bad = [
            {"offer": {"id": 1, "choices": []}},
            {"offer": {"id": 2, "choices": [{"id": "nope"}, {"id": "nada"}, {"id": "zip"}]}, "self": {}},
            {"offer": {"id": 3, "choices": [{"id": "armor"}]}, "self": {"upgrades": None, "weapons": [None, None]}},
            {"offer": "weird"}, {"offer": {"id": 4}}, {},
        ]
        for o in bad:
            r = self.pol.pick(o)
            self.assertTrue(r is None or r == 0 or isinstance(r, int))

    def test_unknown_ids_rank_below_real_upgrades(self):
        o = mk_obs(["zzz_unknown", "armor", "yyy_unknown"], oid=11)
        self.assertEqual(self.pol.pick(o), 1)

    def test_latency(self):
        o = mk_obs(["nanites", "gun_mag", "sensors"])
        t0 = time.perf_counter()
        n = 300
        for i in range(n):
            o["offer"]["id"] = 1000 + i       # defeat the cache: worst case
            self.pol.pick(o)
        per = (time.perf_counter() - t0) / n
        self.assertLess(per, 0.002, f"{per * 1000:.2f} ms per fresh decision")   # budget is 50 ms per tick

    # ---- model properties ----
    def sc(self, uid, held=("gun",), stacks=None, **kw):
        state = {"stacks": stacks or {}, "held": list(held), "secondary": [h for h in held if h != "gun"],
                 "cubes": kw.get("cubes", 3), "t": kw.get("t", 140), "alive": kw.get("alive", 11), "zone_dps": kw.get("zdps", 20)}
        return self.pol.score(uid, state["stacks"], state["held"], self.pol.knobs(state), state["secondary"])

    def test_weapon_upgrade_worthless_if_weapon_not_held(self):
        self.assertAlmostEqual(self.sc("mortar_reload", held=("gun",)), 0.0, places=9)
        self.assertGreater(self.sc("mortar_reload", held=("gun", "mortar")), 0.01)

    def test_diminishing_stacks(self):
        self.assertGreater(self.sc("gun_mag"), self.sc("gun_mag", stacks={"gun_mag": 1}))
        self.assertGreater(self.sc("nanites"), self.sc("nanites", stacks={"nanites": 1}))
        self.assertGreater(self.sc("sensors"), self.sc("sensors", stacks={"sensors": 1}))

    def test_regen_cycles_knob_moves_nanites(self):
        lo = UpgradePolicy(CFG, {"regen_cycles": 0.0})
        hi = UpgradePolicy(CFG, {"regen_cycles": 3.0})
        st = {"stacks": {}, "held": ["gun"], "secondary": [], "cubes": 3, "t": 140, "alive": 11, "zone_dps": 20}
        s_lo = lo.score("nanites", {}, ["gun"], lo.knobs(st), [])
        s_hi = hi.score("nanites", {}, ["gun"], hi.knobs(st), [])
        self.assertLess(s_lo, s_hi)
        self.assertAlmostEqual(s_lo, 0.0, places=9)        # nanites only matter through regen

    def test_state_late_zone_demotes_nanites(self):
        self.assertLess(self.sc("nanites", zdps=100), self.sc("nanites", zdps=20))

    def test_state_finals_promotes_dps(self):
        a = self.sc("gun_damage", alive=3) / self.sc("plating", alive=3)
        b = self.sc("gun_damage", alive=11) / self.sc("plating", alive=11)
        self.assertGreater(a, b)

    def test_state_lightning_held_promotes_energy(self):
        self.assertGreater(self.sc("capacitor", held=("gun", "lightning")), self.sc("capacitor", held=("gun",)))

    def test_swap_discount_applies_only_to_secondary_weapon_upgrades(self):
        hi = UpgradePolicy(CFG, {"swap_discount": 0.5})
        st = {"stacks": {}, "held": ["gun", "laser"], "secondary": ["laser"], "cubes": 3, "t": 140, "alive": 11, "zone_dps": 20}
        k = self.pol.knobs(st)
        self.assertAlmostEqual(hi.score("laser_damage", {}, st["held"], k, ["laser"]) /
                               self.pol.score("laser_damage", {}, st["held"], k, ["laser"]), 0.5 / 0.75, places=6)
        self.assertAlmostEqual(hi.score("gun_damage", {}, st["held"], k, ["laser"]),
                               self.pol.score("gun_damage", {}, st["held"], k, ["laser"]), places=9)

    def _feed(self, pol, times_with_events, t_final, choices=("nanites", "armor", "servos"), oid=900):
        for t in times_with_events:
            pol.observe({"t": t, "events": [{"type": "damaged", "amount": 50}]})
        o = mk_obs(choices, t=t_final, oid=oid)
        st = pol.state_from_obs(o)
        k = pol.knobs(st)
        return pol.score("nanites", st["stacks"], st["held"], k, st["secondary"]), st

    def test_measured_lulls_raise_nanites(self):
        quiet = UpgradePolicy(CFG)
        s0, st0 = self._feed(quiet, [], 60.0)
        self.assertEqual(st0["n_lulls"], 0)
        mid = UpgradePolicy(CFG)
        s1, st1 = self._feed(mid, [5.0, 15.0, 27.0, 40.0, 52.0], 60.0)   # 10-13 s of peace between fights: nanites territory
        self.assertGreaterEqual(st1["n_lulls"], 3)
        self.assertGreater(s1, s0)
        busy = UpgradePolicy(CFG)
        s2, st2 = self._feed(busy, [float(x) for x in range(5, 60, 2)], 60.0)   # a hit every 2 s: no heal-sized peace
        self.assertEqual(st2["n_lulls"], 0)
        self.assertAlmostEqual(s2, s0, places=9)

    def test_nanites_saturate_when_lulls_are_very_long(self):
        # 25 s of peace: stock regen (45/s after 5 s) already refills the typical missing HP, so nanites add little
        mid = UpgradePolicy(CFG)
        s_mid, _ = self._feed(mid, [5.0, 15.0, 27.0, 40.0, 52.0], 60.0)
        long_ = UpgradePolicy(CFG)
        s_long, st = self._feed(long_, [5.0, 30.0, 55.0], 80.0, oid=901)
        self.assertGreaterEqual(st["n_lulls"], 2)
        self.assertLess(s_long, s_mid)

    def test_lull_in_progress_counts_and_old_lulls_expire(self):
        p = UpgradePolicy(CFG)
        p.observe({"t": 10.0, "events": [{"type": "hit"}]})
        n, gap = p.lull_state(30.0)                  # 20 s since last combat event
        self.assertEqual(n, 1)
        self.assertAlmostEqual(gap, 20.0)
        p.observe({"t": 31.0, "events": [{"type": "damaged"}]})
        p.observe({"t": 500.0, "events": []})        # far later: the 21 s lull is outside the 150 s window
        self.assertEqual(p._lulls, [])

    def test_observe_survives_garbage(self):
        p = UpgradePolicy(CFG)
        for o in ({}, {"t": "x"}, {"t": 1.0, "events": None}, {"t": 2.0, "events": [{"type": None}, 5]}):
            p.observe(o)

    def test_default_nanites_is_mid_tier_not_top(self):
        # the sim contradicts "nanites first": without measured peace it must not outrank plating or gun_mag
        self.assertLess(self.sc("nanites"), self.sc("plating"))
        self.assertLess(self.sc("nanites"), self.sc("gun_mag"))

    def test_bias_nudges_choice(self):
        o = mk_obs(["armor", "sensors", "servos"], oid=21)
        base = self.pol.pick(o)
        p = UpgradePolicy(CFG, {"bias": {"servos": 5.0}})
        self.assertEqual(p.pick(mk_obs(["armor", "sensors", "servos"], oid=21)), 2)
        self.assertNotEqual(base, 2)

    def test_config_driven_not_hardcoded(self):
        cfg2 = copy.deepcopy(CFG)
        for u in cfg2["upgrades"]:
            if u["id"] == "armor":
                u["effects"][0]["add"] = 0.30          # balance patch: armor becomes huge
        p2 = UpgradePolicy(cfg2)
        o = mk_obs(["armor", "plating", "gun_damage"], oid=31)
        self.assertEqual(p2.pick(o), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
