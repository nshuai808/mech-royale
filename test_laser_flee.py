"""laser_flee: in evade/hide/zone the laser trigger is never held (charging halves speed); other weapons unaffected.
Run: python test_laser_flee.py"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bot as B


def make(mode, flee=True):
    b = B.Bot.__new__(B.Bot)
    b.laser_flee, b.mode = flee, mode
    b.unseen_p, b.unseen = {"face": False}, []
    b.me = {"weapons": [{"kind": "gun", "ammo": 12, "stats": {"mag": 12}}, {"kind": "laser", "charge": 0.3, "stats": {}}]}
    b._engage = lambda tgt, slots: ((0.0, 0.0), [True, True])
    b._idle_aim = lambda mv: (0.0, 0.0)
    return b


def fire_of(b):
    act = {}
    b._aim_and_fire(act, {}, {"kind": "mech"}, (0, 0))
    return act.get("fire", [False, False])


for mode in ("evade", "hide", "zone"):
    assert fire_of(make(mode)) == [True, False], mode          # gun keeps firing, laser released
assert fire_of(make("fight")) == [True, True]                   # fighting: unchanged
assert fire_of(make("evade", flee=False)) == [True, True]       # flag off: unchanged
print("test_laser_flee ok")
