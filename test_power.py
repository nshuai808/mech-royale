"""t11-power: rush_build upgrade order, cube_cap, lt_chain aim. Run: python test_power.py"""
import math, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bot as B


def bare():
    b = B.Bot.__new__(B.Bot)
    b.x = b.y = b.z = 0.0
    b.map = None
    b.stats = {"muzzle_height": 7.0}
    return b


# lt_chain: lone near enemy vs a pack of three further away -> aim at the pack
b = bare()
def mech(i, x, y):
    return {"id": i, "kind": "mech", "pos": [x, y, 0.0], "_d": math.hypot(x, y)}
b._enemies = [mech(1, 10, 0), mech(2, 0, 30), mech(3, 5, 33), mech(4, -5, 33)]
yaw, _ = b._chain_aim({"range": 45, "chain_range": 14}, (0.0, 0.0))
assert abs(yaw - math.atan2(30, 0)) < 0.2, yaw
# no pack -> keep the original aim
b._enemies = [mech(1, 10, 0), mech(2, 0, 40)]
assert b._chain_aim({"range": 45, "chain_range": 14}, (0.123, 0.0)) == (0.123, 0.0)

# rush_build: armor beats nanites and gun upgrades; lightning_chain beats laser_damage
b = bare()
b.rush_build, b.upg_ctx = True, False
b.me = {"weapons": [{"kind": "gun"}, {"kind": "lightning"}]}
offer = lambda *ids: {"choices": [{"id": i} for i in ids]}
assert b._pick_upgrade(offer("gun_damage", "nanites", "armor")) == 2
assert b._pick_upgrade(offer("laser_damage", "lightning_chain", "servos")) == 1

# cube_cap: at the cap, loose cubes are ignored
b = bare()
b.cube_cap, b.t = 10, 50.0
b.me = {"weapons": [{"kind": "gun"}, {"kind": "lightning"}], "cubes": 10}
b._ranks = lambda: dict(B.WEAPON_RANK)
b.wpn_ctx, b.wpn_margin = False, 0.5
b.in_safe = lambda px, py: True
b._crate = lambda obs, r: None
obs = {"pickups": [], "cubes": [{"pos": [5.0, 0.0, 0.0]}], "crates": []}
assert b._loot_goal(obs) is None
b.me["cubes"] = 9
assert b._loot_goal(obs)[2] == "get cube"
print("test_power ok")
