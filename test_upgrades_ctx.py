"""Unit tests for the context-aware upgrade pick (params.json "upgrade_ctx"). Run: python test_upgrades_ctx.py"""
import gzip, json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bot as B

with gzip.open(os.path.join(HERE, "kit", "check", "stream.jsonl.gz"), "rt") as f:
    HELLO = json.loads(f.readline())
HELLO["map"]["dir"] = os.path.join(HERE, "kit", "arena")


def make(ctx=True):
    b = B.Bot.__new__(B.Bot)          # skip the map build: the pick only needs me + foe memory
    b.upg_ctx, b.foe_kit = ctx, {}
    b.dmg_build_on = False
    return b


def W(*kinds):
    return [{"kind": k} if k else None for k in kinds]


def pick(b, weapons, choices, foes=()):
    b.me = {"weapons": W(*weapons)}
    obs = {"mechs": [{"kind": "mech", "id": i, "weapons": list(k)} for i, k in enumerate(foes)]}
    b._note_foes(obs)
    return choices[b._pick_upgrade({"choices": [{"id": c} for c in choices]})]


def test_generic_first():
    b = make()
    assert pick(b, ("gun", "laser"), ["laser_damage", "plating", "servos"]) == "plating"
    assert pick(make(), ("gun", None), ["gun_rate", "armor", "sensors"]) == "armor"


def test_primary_weapon_over_secondary():
    # laser is primary: its upgrade beats the gun's
    assert pick(make(), ("gun", "laser"), ["gun_damage", "laser_charge", "sensors"]) == "laser_charge"
    # only a gun: gun upgrades rank above utility
    assert pick(make(), ("gun", None), ["sensors", "gun_damage", "servos"]) == "gun_damage"


def test_lightning_energy():
    # holding lightning, energy beats sensors/gyros-free utility
    assert pick(make(), ("gun", "lightning"), ["sensors", "capacitor", "servos"]) == "capacitor"


def test_counter_bumps():
    # laser held, enemies carry lightning (they short us): faster charge beats more damage
    foes = [("gun", "lightning")] * 4
    assert pick(make(), ("gun", "laser"), ["laser_damage", "laser_charge", "gyros"], foes) == "laser_charge"
    # no lightning seen: damage first
    assert pick(make(), ("gun", "laser"), ["laser_damage", "laser_charge", "gyros"], [("gun", "mortar")]) == "laser_damage"
    # lightning held, enemies are ranged (laser/mortar): range beats efficiency
    foes = [("gun", "laser")] * 3 + [("gun", "mortar")] * 2
    assert pick(make(), ("gun", "lightning"), ["lightning_efficiency", "lightning_range", "jets"], foes) == "lightning_range"
    # gun only vs lightning users: servos (kite) over sensors
    assert pick(make(), ("gun", None), ["sensors", "servos", "gyros"], [("gun", "lightning")] * 3) == "servos"


def test_flag_off_is_main():
    b = make(ctx=False)
    b.me = {"weapons": W("gun", "laser")}
    for ch in (["laser_damage", "plating", "servos"], ["sensors", "gyros", "jets"], ["gun_damage", "laser_charge", "x"]):
        got = b._pick_upgrade({"choices": [{"id": c} for c in ch]})
        ids = ch
        kinds = ["gun", "laser"]
        mine = [u for u in ids if any(u.startswith(k + "_") for k in kinds)]
        pref = B.UPGRADE_PREF[:3] + sorted(mine, key=lambda u: B.UPGRADE_PREF.index(u) if u in B.UPGRADE_PREF else 99) + B.UPGRADE_PREF[3:]
        want = next((ids.index(u) for u in pref if u in ids), 0)
        assert got == want, (ch, got, want)


def test_every_config_upgrade_scored_and_robust():
    ids = [u["id"] for u in HELLO["config"]["upgrades"]]
    b = make()
    for weapons in (("gun", None), ("gun", "laser"), ("gun", "lightning"), ("gun", "mortar"), ("laser", "lightning"), (None, None)):
        b.me = {"weapons": W(*weapons)}
        for i in range(0, len(ids), 3):
            ch = ids[i:i + 3]
            r = b._pick_upgrade({"choices": [{"id": c} for c in ch]})
            assert 0 <= r < len(ch)
    # malformed enemy weapons field and unknown ids never raise
    b._note_foes({"mechs": [{"kind": "mech", "id": 9, "weapons": None}, {"kind": "mech", "id": 8, "weapons": ["gun", None]}]})
    b.me = {"weapons": [None, {"kind": "weird"}]}
    assert b._pick_upgrade({"choices": [{"id": "zzz"}, {"id": "plating"}]}) == 1


def test_full_bot_flag_from_params():
    b = B.Bot(HELLO)
    p = (B.load_params().get("upgrade_ctx") or {}).get("enabled", False)
    assert b.upg_ctx == bool(p)


if __name__ == "__main__":
    n = 0
    for k, v in list(globals().items()):
        if k.startswith("test_"):
            v(); n += 1
    print(f"{n} tests OK")
