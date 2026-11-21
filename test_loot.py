"""Unit tests for loot.py. Run: python3 test_loot.py   (stdlib unittest, no sim needed)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import loot  # noqa: E402

CFG = {
    "loot": {"pickup_radius": 4, "equip_s": 1},
    "mech": {"jet_drain": 15, "max_rise_speed": 10},
    "weapons": {
        "gun": {"range": 230},
        "mortar": {"cooldown": 2.6, "speed": 72, "gravity": 22, "splash_radius": 7},
        "laser": {"cooldown": 1.65, "range": 280},
        "lightning": {"cooldown": 0.25, "range": 45},
    },
}
GUN = {"kind": "gun", "cooldown": 0, "ammo": 12, "reload": 0}


def obs(t=10.0, pos=(0, 0, 0), weapons=None, pickups=(), mechs=(), sounds=(), events=(), energy=100, zone=None,
        in_zone=True):
    return {
        "tick": int(t * 10), "t": t,
        "self": {"id": 0, "pos": list(pos), "hp": 1400, "energy": energy, "in_zone": in_zone,
                 "weapons": weapons if weapons is not None else [dict(GUN), None]},
        "mechs": list(mechs), "pickups": list(pickups), "sounds": list(sounds), "events": list(events),
        "zone": zone,
    }


def pk(i, kind, x, y, z=0.0):
    return {"id": i, "kind": kind, "pos": [x, y, z]}


def enemy(i, x, y, *weapons):
    return {"id": i, "kind": "mech", "pos": [x, y, 0.0], "weapons": ["gun", *weapons], "hp": 1400}


def held(kind, **kw):
    d = {"kind": kind, "cooldown": 0}
    d.update(kw)
    return d


class TestLoot(unittest.TestCase):
    def planner(self, **kw):
        return loot.LootPlanner(CFG, loot.LootParams(**kw))

    # --- pickup priority -----------------------------------------------------------------
    def test_empty_slot_prefers_lightning_over_laser_over_mortar_at_equal_distance(self):
        d = self.planner().step(obs(pickups=[pk(1, "mortar", 30, 0), pk(2, "laser", 0, 30), pk(3, "lightning", -30, 0)]))
        self.assertEqual(d.kind, "lightning")
        d = self.planner().step(obs(pickups=[pk(1, "mortar", 30, 0), pk(2, "laser", 0, 30)]))
        self.assertEqual(d.kind, "laser")

    def test_closer_weaker_weapon_beats_far_stronger_one(self):
        pl = self.planner()
        d = pl.step(obs(pickups=[pk(1, "mortar", 10, 0), pk(2, "lightning", 0, 120)]))
        self.assertEqual(d.kind, "mortar")

    def test_far_mortar_is_not_worth_it_but_far_lightning_is(self):
        pl = self.planner()
        self.assertIsNone(pl.step(obs(pickups=[pk(1, "mortar", 120, 0)])).goal)
        pl = self.planner()
        self.assertIsNotNone(pl.step(obs(pickups=[pk(1, "lightning", 120, 0)])).goal)

    def test_gun_pickups_and_duplicate_kinds_are_ignored(self):
        pl = self.planner()
        self.assertIsNone(pl.step(obs(pickups=[pk(1, "gun", 5, 0)])).goal)
        w = [dict(GUN), held("laser")]
        pl = self.planner()
        self.assertEqual(pl.step(obs(weapons=w, pickups=[pk(1, "laser", 5, 0)])).reason,
                         "nothing worth it")

    def test_take_when_in_reach_else_walk(self):
        pl = self.planner()
        d = pl.step(obs(pickups=[pk(7, "laser", 3.0, 0)]))
        self.assertEqual((d.take, d.drop), (7, None))
        pl = self.planner()
        d = pl.step(obs(pickups=[pk(7, "laser", 20.0, 0)]))
        self.assertIsNone(d.take)
        self.assertEqual(d.goal, (20.0, 0, 0.0))

    # --- phase budgets -------------------------------------------------------------------
    def test_detour_budget_shrinks_with_time(self):
        far = [pk(1, "lightning", 100, 0)]   # path 125 m with the default 1.25 factor
        self.assertIsNotNone(self.planner().step(obs(t=20, pickups=far)).goal)
        self.assertIsNone(self.planner().step(obs(t=80, pickups=far)).goal)
        self.assertIsNone(self.planner().step(obs(t=150, pickups=[pk(1, "lightning", 30, 0)])).goal)   # 37 m > 25
        self.assertIsNotNone(self.planner().step(obs(t=150, pickups=[pk(1, "lightning", 15, 0)])).goal)

    def test_zone_gate(self):
        z = {"center": [0, 0], "radius": 500, "next_center": [300, 0], "next_radius": 100, "shrink_start": 60}
        d = self.planner().step(obs(t=55, pickups=[pk(1, "lightning", -40, 0)], zone=z))
        self.assertIsNone(d.goal)    # t >= shrink_start-10 so the next circle applies; pickup is outside it
        d = self.planner().step(obs(t=20, pickups=[pk(1, "lightning", -40, 0)], zone=z))
        self.assertIsNotNone(d.goal)

    def test_roof_needs_energy_and_height_cap(self):
        roof = [pk(1, "lightning", 10, 0, z=30.0)]
        self.assertIsNotNone(self.planner().step(obs(pickups=roof, energy=100)).goal)
        self.assertIsNone(self.planner().step(obs(pickups=roof, energy=40)).goal)
        self.assertIsNone(self.planner().step(obs(pickups=[pk(1, "lightning", 10, 0, z=60.0)])).goal)

    def test_enemy_next_to_pickup_vetoes_it(self):
        d = self.planner().step(obs(pickups=[pk(1, "lightning", 30, 0)], mechs=[enemy(9, 40, 0)]))
        self.assertIsNone(d.goal)

    def test_outside_zone_defers_to_zone_module(self):
        d = self.planner().step(obs(pickups=[pk(1, "lightning", 5, 0)], in_zone=False))
        self.assertIsNone(d.take)
        self.assertIsNone(d.goal)

    # --- counter-pick / swaps ------------------------------------------------------------
    def test_laser_threat_makes_mortar_a_liability_and_triggers_drop(self):
        w = [dict(GUN), held("mortar")]
        pl = self.planner()
        d = pl.step(obs(weapons=w, mechs=[enemy(9, 90, 0, "laser")]))
        self.assertEqual((d.drop, d.take, d.kind), (1, None, "mortar"))
        d = self.planner().step(obs(weapons=w, mechs=[enemy(9, 260, 0, "laser")]))   # far: keep it
        self.assertIsNone(d.drop)

    def test_no_liability_drop_without_threat(self):
        w = [dict(GUN), held("mortar")]
        d = self.planner().step(obs(weapons=w))
        self.assertIsNone(d.drop)

    def test_dropped_weapon_is_not_picked_back_up(self):
        pl = self.planner()
        pl.step(obs(t=10, weapons=[dict(GUN), None], events=[{"type": "dropped", "id": 50, "kind": "mortar", "slot": 1}]))
        d = pl.step(obs(t=12, pickups=[pk(50, "mortar", 1, 0)]))
        self.assertIsNone(d.take)

    def test_counter_pick_swaps_laser_for_lightning_against_laser_holder(self):
        w = [dict(GUN), held("laser")]
        pl = self.planner()
        # laser holder 10 m away: lightning shorts it, so lightning clears the swap margin even mid-fight
        d = pl.step(obs(weapons=w, mechs=[enemy(9, -10, 0, "laser")], pickups=[pk(1, "lightning", 6, 0)]))
        self.assertEqual((d.kind, d.reason), ("lightning", "walk to upgrade"))
        pl = self.planner()
        d = pl.step(obs(weapons=w, mechs=[enemy(9, -10, 0, "laser")], pickups=[pk(1, "lightning", 2, 0)]))
        self.assertEqual((d.take, d.drop), (1, 1))

    def test_mortar_swaps_up_to_lightning_when_a_laser_holder_is_around(self):
        w = [dict(GUN), held("mortar")]
        d = self.planner().step(obs(weapons=w, mechs=[enemy(9, 130, 0, "laser")], pickups=[pk(1, "lightning", 2, 0)]))
        self.assertEqual((d.take, d.drop), (1, 1))

    def test_lightning_holder_far_away_barely_matters_to_a_laser_carrier(self):
        pl = self.planner()
        far = pl.value("laser", [loot.Threat(9, 120.0, frozenset(["lightning"]), 1.0)])
        near = pl.value("laser", [loot.Threat(9, 20.0, frozenset(["lightning"]), 1.0)])
        self.assertGreater(far, 0.85)       # arc is 45 m: a laser outranges it
        self.assertLess(near, 0.75)

    def test_params_from_dict_partial_override(self):
        p = loot.LootParams.from_dict({"detour_early_m": 90, "base": {"mortar": 0.2},
                                       "counter": {"laser": {"mortar": [0.9, 100]}}, "nonsense": 1})
        self.assertEqual(p.detour_early_m, 90)
        self.assertEqual(p.base["mortar"], 0.2)
        self.assertEqual(p.base["laser"], loot.DEFAULT_BASE["laser"])
        self.assertEqual(p.counter["laser"]["mortar"], (0.9, 100.0))
        self.assertEqual(p.counter["laser"]["lightning"], loot.DEFAULT_COUNTER["laser"]["lightning"])

    def test_hysteresis_no_swap_for_marginal_gain(self):
        w = [dict(GUN), held("laser")]    # 0.9 vs lightning 1.0, margin 0.25
        d = self.planner().step(obs(weapons=w, pickups=[pk(1, "lightning", 2, 0)]))
        self.assertIsNone(d.take)

    def test_never_swap_out_a_charging_laser(self):
        w = [dict(GUN), held("laser", charge=0.4)]
        d = self.planner().step(obs(weapons=w, mechs=[enemy(9, 100, 0, "laser")], pickups=[pk(1, "lightning", 2, 0)]))
        self.assertIsNone(d.take)
        self.assertIsNone(d.drop)

    def test_swap_cooldown(self):
        pl = self.planner()
        pl.step(obs(t=10, events=[{"type": "took", "id": 3, "kind": "laser", "slot": 1}]))
        w = [dict(GUN), held("mortar")]
        # a lightning is lying at our feet and a laser-holder is near: worth swapping, but not 2 s after a swap
        args = dict(weapons=w, mechs=[enemy(9, 130, 0, "laser")], pickups=[pk(1, "lightning", 2, 0)])
        self.assertIsNone(pl.step(obs(t=12, **args)).take)
        self.assertEqual(pl.step(obs(t=17, **args)).take, 1)

    def test_in_a_fight_only_adjacent_pickups(self):
        m = [enemy(9, 50, 0)]
        self.assertIsNone(self.planner().step(obs(mechs=m, pickups=[pk(1, "lightning", -25, 0)])).goal)
        self.assertEqual(self.planner().step(obs(mechs=m, pickups=[pk(1, "lightning", -8, 0)])).take, None)  # walk
        self.assertEqual(self.planner().step(obs(mechs=m, pickups=[pk(1, "lightning", -2, 0)])).take, 1)

    def test_counter_strength_zero_is_fixed_pick(self):
        w = [dict(GUN), held("mortar")]
        pl = self.planner(counter_strength=0.0)
        d = pl.step(obs(weapons=w, mechs=[enemy(9, 90, 0, "laser")]))
        self.assertIsNone(d.drop)

    def test_sound_ghost_counts_less_than_a_seen_enemy(self):
        pl = self.planner()
        seen = pl.value("mortar", pl.threats_from_obs(obs(mechs=[enemy(9, 30, 0, "laser")])))
        pl2 = self.planner()
        heard = pl2.value("mortar", pl2.threats_from_obs(obs(sounds=[{"kind": "laser_charge", "dist": "near", "age": 0.1}])))
        self.assertLess(seen, heard)
        self.assertLess(heard, pl.p.base["mortar"])

    def test_enemy_loadout_is_remembered_after_it_leaves_view(self):
        pl = self.planner()
        pl.step(obs(t=10, mechs=[enemy(9, 60, 0, "laser")]))
        th = pl.threats_from_obs(obs(t=18))
        self.assertTrue(th and "laser" in th[0].kinds)
        self.assertEqual(pl.threats_from_obs(obs(t=200)), [])

    # --- memory -----------------------------------------------------------------------------
    def test_memory_persists_then_prunes_when_gone_up_close(self):
        pl = self.planner()
        pl.step(obs(t=1, pos=(0, 0, 0), pickups=[pk(1, "lightning", 100, 0)]))
        pl.step(obs(t=2, pos=(0, 0, 0)))
        self.assertIn(1, pl.mem)
        for k in range(3):
            pl.step(obs(t=3 + k, pos=(95, 0, 0)))
        self.assertNotIn(1, pl.mem)

    def test_take_failed_gone_removes_and_range_blacklists(self):
        pl = self.planner()
        pl.step(obs(pickups=[pk(1, "lightning", 2, 0), pk(2, "laser", 2, 1)]))
        pl.step(obs(t=10.1, events=[{"type": "take_failed", "id": 1, "reason": "gone"},
                                    {"type": "take_failed", "id": 2, "reason": "range"}]))
        self.assertNotIn(1, pl.mem)
        self.assertIn(2, pl.blacklist)

    def test_slot_of_and_preferred_range(self):
        self.assertEqual(loot.slot_of([dict(GUN), held("laser")], "laser"), 1)
        self.assertIsNone(loot.slot_of([dict(GUN), None], "laser"))
        lo, ideal, hi = loot.preferred_range("mortar", CFG)
        self.assertAlmostEqual(hi, 72 ** 2 / 22)
        self.assertGreater(lo, 7)


if __name__ == "__main__":
    unittest.main(verbosity=1)
