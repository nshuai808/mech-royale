"""Unit tests for the counter-aware weapon rank (params.json "weapon_ctx"). Run: python test_weapon_ctx.py"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bot as B

PU = 3.5   # pickup radius in the kit config


def make(ctx=True, t=10.0):
    b = B.Bot.__new__(B.Bot)          # skip the map build: loot choice only needs me, pos, foe memory
    b.upg_ctx, b.wpn_ctx, b.foe_kit = False, ctx, {}
    b.wpn_k, b.wpn_n0, b.wpn_margin, b.wpn_mortar_gun = 1.0, 3.0, 0.5, 1.6
    b._rank_t, b._rank = None, dict(B.WEAPON_RANK)
    b.x = b.y = b.z = 0.0
    b.t, b.pickup_r = t, PU
    b.in_safe = lambda x, y: True
    return b


def setup(b, weapons, foes=()):
    b.me = {"weapons": [{"kind": k} if k else None for k in weapons], "hp": 1400, "max_hp": 1400}
    b._note_foes({"mechs": [{"kind": "mech", "id": i, "weapons": list(k)} for i, k in enumerate(foes)]})
    b._rank_t = None


def pk(i, kind, d):
    return {"id": i, "kind": kind, "pos": [d, 0.0, 0.0]}


def take(b, kind):
    return b._take({"pickups": [pk(7, kind, 1.0)]})


def goal(b, pickups):
    g = b._loot_goal({"pickups": pickups, "cubes": [], "crates": []})
    return g and g[2]


def test_ranks_triangle():
    b = make()
    setup(b, ("gun", None), [("gun", "mortar")] * 12)
    R = b._ranks()
    assert R["laser"] > R["lightning"] > R["mortar"], R      # laser beats mortar, lightning loses to it
    setup(b, ("gun", None), [("gun", "laser")] * 12)
    R = b._ranks()
    assert R["lightning"] > 3 and R["mortar"] < 1 and R["laser"] == 2, R
    setup(make(), ("gun", None))
    assert make()._ranks() == B.WEAPON_RANK                  # no foes seen: unchanged


def test_shrink_few_foes():
    b = make()
    setup(b, ("gun", None), [("gun", "mortar")])
    R = b._ranks()
    assert abs(R["laser"] - 2.25) < 1e-9 and R["lightning"] > R["laser"]   # one sighting doesn't flip lightning


def test_loot_goal_prefers_counter():
    # gun only, laser and lightning equally far; mortar-heavy enemies -> go for the laser
    b = make()
    setup(b, ("gun", None), [("gun", "mortar")] * 12)
    assert goal(b, [pk(1, "lightning", 60), pk(2, "laser", 60)]) == "get laser"
    b = make()
    setup(b, ("gun", None))
    assert goal(b, [pk(1, "lightning", 60), pk(2, "laser", 60)]) == "get lightning"


def test_mortar_replaces_gun_vs_lightning():
    b = make()
    setup(b, ("gun", "laser"), [("gun", "lightning")] * 12)
    assert take(b, "mortar") == {"take": 7, "drop": 0}       # keep the laser, the mortar takes the gun's slot
    b = make()
    setup(b, ("gun", "laser"))
    assert take(b, "mortar") is None                         # no lightning seen: as main


def test_no_swap_inside_margin():
    # gun+laser vs mostly mortar foes, a little lightning: laser and lightning close in rank -> both kept via gun swap
    b = make()
    setup(b, ("gun", "laser"), [("gun", "mortar")] * 8)
    assert take(b, "lightning") == {"take": 7, "drop": 0}


def test_flag_off_matches_fixed_rank():
    for weapons in (("gun", None), ("gun", "laser"), ("gun", "mortar"), ("gun", "lightning"), ("laser", "mortar")):
        for kind in ("laser", "lightning", "mortar"):
            for foes in ((), [("gun", "lightning")] * 12, [("gun", "mortar")] * 12):
                b = make(ctx=False)
                setup(b, weapons, foes)
                b2 = make(ctx=True)
                setup(b2, weapons)          # ctx on but no foes seen == fixed ranks
                assert take(b, kind) == take(b2, kind), (weapons, kind, foes)
                ps = [pk(1, kind, 50), pk(2, "laser", 80)]
                assert goal(b, ps) == goal(b2, ps)


def test_robust_bad_foe_data():
    b = make()
    setup(b, ("gun", "laser"))
    b._note_foes({"mechs": [{"kind": "mech", "id": 1, "weapons": None}, {"kind": "mech", "id": 2, "weapons": [None, 5, "mortar"]}]})
    b._rank_t = None
    R = b._ranks()
    assert set(R) == set(B.WEAPON_RANK)
    take(b, "lightning"); goal(b, [pk(1, "mortar", 30)])


if __name__ == "__main__":
    n = 0
    for k, v in list(globals().items()):
        if k.startswith("test_"):
            v(); n += 1
    print(f"{n} tests OK")
