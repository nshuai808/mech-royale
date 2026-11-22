"""Synthetic upgrade and lightning approach checks."""
import copy
import gzip
import json
from pathlib import Path
from unittest.mock import patch

import mechfight

# Import the bot class without starting its protocol reader on stdin.
with patch.object(mechfight, "run"):
    import bot

ROOT = Path(__file__).resolve().parent
with gzip.open(ROOT / "kit" / "check" / "stream.jsonl.gz", "rt") as stream:
    HELLO = json.loads(next(stream))
    OBS = next(msg for msg in map(json.loads, stream) if msg["type"] == "obs")
UPGRADES = {u["id"]: u for u in HELLO["config"]["upgrades"]}


def pick(kinds, *choices, enabled=True):
    model = bot.Bot.__new__(bot.Bot)
    model.dmg_build_on = enabled
    model.upg_ctx = False
    model.me = {"weapons": [weapon(k) if k else None for k in kinds]}
    offer = {"choices": [UPGRADES[k] for k in choices]}
    return choices[model._pick_upgrade(offer)]


def test_damage_prefers_primary_weapon():
    assert pick(("gun", "lightning"), "plating", "gun_damage", "lightning_chain") == "lightning_chain"
    assert pick(("gun", "lightning"), "lightning_range", "lightning_chain", "lightning_efficiency") == "lightning_efficiency"
    assert pick(("gun", "lightning"), "armor", "lightning_range") == "lightning_range"
    assert pick(("gun", "laser"), "laser_charge", "armor", "laser_damage") == "laser_damage"
    assert pick(("gun", "laser"), "gun_damage", "plating", "laser_charge") == "laser_charge"
    assert pick(("gun", None), "gun_rate", "armor", "gun_damage") == "gun_damage"
    assert pick(("gun", None), "plating", "gun_rate") == "gun_rate"


def test_damage_fallback_and_off():
    assert pick(("gun", "lightning"), "gun_damage", "nanites", "plating") == "plating"
    assert pick(("gun", "lightning"), "nanites", "capacitor", "armor") == "armor"
    assert pick(("gun", "lightning"), "nanites", "capacitor", "servos") == "capacitor"
    assert pick(("gun", None), "servos", "nanites") == "nanites"
    assert pick(("gun", "lightning"), "plating", "lightning_efficiency", enabled=False) == "plating"


def weapon(kind):
    return {"kind": kind, "cooldown": 0, "stats": dict(HELLO["config"]["weapons"][kind])}


def enemy(ident, distance, hp, y=0):
    return {"id": ident, "kind": "mech", "pos": [distance, y, 0], "vel": [0, 0, 0],
            "hp": hp, "max_hp": 1400, "aim": [0, 0], "weapons": ["gun"]}


def approach(enabled=True, *, hp=1000, energy=100, distance=65, target_hp=350,
             second=False, third=False, lightning=True, range_m=None, isolate=False):
    observation = copy.deepcopy(OBS)
    observation.update(t=20, tick=400, events=[], sounds=[], mechs=[enemy(1, distance, target_hp)],
                       crates=[], drops=[], pickups=[], cubes=[], offer=None)
    observation["zone"].update(center=[0, 0], next_center=[0, 0], radius=560, next_radius=380,
                               shrink_start=60, shrink_end=110)
    slots = [weapon("gun"), weapon("lightning") if lightning else None]
    if range_m is not None:
        slots[1]["stats"]["range"] = range_m
    observation["self"].update(pos=[0, 0, 0], hp=hp, max_hp=1400, energy=energy,
                               aim=[0, 0], in_zone=True, weapons=slots)
    if second:
        observation["mechs"].append(enemy(2, 110, 1400, 40))
    if third:
        observation["mechs"].append(enemy(3, 115, 1400, -40))
    with patch.object(bot, "Map", return_value=None):
        bot_instance = bot.Bot(HELLO)
    bot_instance.lt_close_on = enabled
    if isolate:
        # Test the close-in gate after the fight branch has won arbitration.
        bot_instance._third_party = lambda *_: False
    mechfight.draw.clear()
    action = bot_instance.act(observation)
    return bot_instance.mode, action


def test_close_health_energy_and_weapon():
    # Approaching the target replaces the normal lightning strafe.
    assert approach(hp=491)[1]["move"] == [1, 0]
    assert approach(hp=490)[1]["move"] != [1, 0]
    assert approach(False, hp=700)[1]["move"] != [1, 0]
    assert approach(False, hp=701)[1]["move"] == [1, 0]
    assert approach(energy=35)[1]["move"] != [1, 0]
    assert approach(energy=36)[1]["move"] == [1, 0]
    assert approach(distance=40)[1]["move"] != [1, 0]
    assert approach(lightning=False)[1]["move"] != [1, 0]


def test_close_two_exposed_requires_weak_target():
    assert approach(second=True, target_hp=60)[1]["move"] == [1, 0]
    assert approach(False, second=True, target_hp=60)[1]["move"] != [1, 0]
    assert approach(second=True, target_hp=699, isolate=True)[1]["move"] == [1, 0]
    assert approach(second=True, target_hp=700, isolate=True)[1]["move"] != [1, 0]
    # 3 exposed: evade, unless the finisher keeps us in to finish a target that dies within finish_s (60 HP does)
    fin = (bot.load_params().get("finisher") or {}).get("enabled", False)
    assert approach(second=True, third=True, target_hp=60)[0] == ("fight" if fin else "evade")


def test_close_keeps_energy_near_lightning_range():
    assert approach(False, distance=65)[1]["boost"]
    assert not approach(distance=70)[1]["boost"]
    assert approach(distance=71)[1]["boost"]
    assert not approach(distance=78, range_m=54)[1]["boost"]
    assert approach(distance=80, range_m=54)[1]["boost"]


if __name__ == "__main__":
    for test in (
        test_damage_prefers_primary_weapon,
        test_damage_fallback_and_off,
        test_close_health_energy_and_weapon,
        test_close_two_exposed_requires_weak_target,
        test_close_keeps_energy_near_lightning_range,
    ):
        test()
        print("ok", test.__name__)
