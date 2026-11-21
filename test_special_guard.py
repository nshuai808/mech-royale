"""Unit tests for the in-fight swap guard (params.json "special_guard"). Run: python test_special_guard.py"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bot as B


def make(guard=True, t=50.0):
    b = B.Bot.__new__(B.Bot)
    b.upg_ctx = b.wpn_ctx = False
    b.foe_kit, b._rank_t, b._rank = {}, None, dict(B.WEAPON_RANK)
    b.wpn_margin, b.wpn_mortar_gun = 0.5, 1.6
    b.guard, b.guard_r, b.guard_s = guard, 150.0, 2.5
    b.x = b.y = b.z = 0.0
    b.t, b.pickup_r = t, 4.0
    b.last_hurt_t = b.last_dealt_t = -99.0
    return b


def obs(kind, enemy_d=None):
    o = {"pickups": [{"id": 8001, "kind": kind, "pos": [1.0, 0.0, 0.0]}], "mechs": []}
    if enemy_d is not None:
        o["mechs"].append({"kind": "mech", "id": 3, "pos": [enemy_d, 0.0, 0.0], "weapons": ["gun"]})
    return o


def held(b, *kinds):
    b.me = {"weapons": [{"kind": k} if k else None for k in kinds]}


def test_empty_slot_always_taken():
    b = make(); held(b, "gun", None); b.last_hurt_t = b.t
    assert b._take(obs("laser", enemy_d=40)) == {"take": 8001}


def test_swap_waits_in_fight():
    b = make(); held(b, "gun", "mortar")
    assert b._take(obs("laser", enemy_d=100)) is None            # enemy in sight
    b = make(); held(b, "gun", "laser"); b.last_hurt_t = b.t - 1.0
    assert b._take(obs("lightning")) is None                     # just hit
    b = make(); held(b, "gun", "mortar"); b.last_dealt_t = b.t   # shooting a crate is not a fight
    assert b._take(obs("laser")) == {"take": 8001, "drop": 1}


def test_swap_after_fight():
    b = make(); held(b, "gun", "mortar"); b.last_hurt_t = b.t - 3.0
    assert b._take(obs("laser", enemy_d=200)) == {"take": 8001, "drop": 1}
    b = make(); held(b, "gun", "laser")
    assert b._take(obs("lightning")) == {"take": 8001, "drop": 0}


def test_flag_off_is_main():
    for k in (("gun", None), ("gun", "mortar"), ("gun", "laser"), ("gun", "lightning")):
        for kind in ("mortar", "laser", "lightning"):
            for ed, hurt in ((None, False), (60, True), (100, False)):
                a, c = make(guard=False), make(guard=True)
                held(a, *k); held(c, *k)
                if hurt:
                    a.last_hurt_t = a.t
                want = a._take(obs(kind, ed))
                assert want == c._take(obs(kind)), (k, kind, ed)   # guard on, no fight == guard off


if __name__ == "__main__":
    n = 0
    for k, v in list(globals().items()):
        if k.startswith("test_"):
            v(); n += 1
    print(f"{n} tests OK")
