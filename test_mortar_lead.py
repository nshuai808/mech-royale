"""Unit tests for mortar lead (params.json "mortar_lead"): fly the shell with the protocol's ballistics and
check where it lands against a moving target. Run: python test_mortar_lead.py"""
import math, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bot as B

MO = {"kind": "mortar", "cooldown": 0, "stats": {"speed": 72, "gravity": 22, "splash_radius": 7}}
H = 9.0


def make(lead=True, k=1.0):
    b = B.Bot.__new__(B.Bot)
    b.mortar_lead, b.mlead_k, b.mlead_max = lead, k, 40.0
    b.x = b.y = b.z = 0.0
    b.t, b.short_until = 10.0, -1.0
    b.stats = {"height": H, "muzzle_height": 7.0}
    b.me = {"aim": [0.0, 0.0], "energy": 100, "weapons": [None, MO]}
    return b


def land(yaw, pitch, v=72.0, g=22.0, z0=H + 0.5):
    """Where a shell fired from (0, 0, z0) comes down to z = 0, and when."""
    vh, vz = v * math.cos(pitch), v * math.sin(pitch)
    t = (vz + math.sqrt(vz * vz + 2 * g * z0)) / g
    return vh * t * math.cos(yaw), vh * t * math.sin(yaw), t


def miss(b, pos, vel):
    tgt = {"kind": "mech", "pos": list(pos), "vel": list(vel)}
    aim, _ = b._engage(tgt, b.me["weapons"])
    lx, ly, t = land(*aim)
    return math.hypot(lx - (pos[0] + vel[0] * t), ly - (pos[1] + vel[1] * t))


def test_still_target_same_as_off():
    for p in ((80, 0, 0), (150, 60, 0), (40, -30, 0)):
        assert abs(miss(make(True), p, (0, 0, 0)) - miss(make(False), p, (0, 0, 0))) < 1e-6
        assert miss(make(True), p, (0, 0, 0)) < 1.0           # the low-arc solver itself lands on the target


def test_moving_target_inside_splash():
    for p, v in (((100, 0, 0), (0, 11.7, 0)), ((150, 40, 0), (-11.7, 0, 0)), ((70, -50, 0), (8, 8, 0))):
        on, off = miss(make(True), p, v), miss(make(False), p, v)
        assert on < 2.5, (p, v, on)                           # full lead: inside the 7 m splash
        assert off > 10, (p, v, off)                          # no lead: outside it
        assert miss(make(True, k=0.8), p, v) < off            # partial lead still helps


def test_lead_capped_and_range_gate():
    b = make(True)
    tgt = {"kind": "mech", "pos": [100, 0, 0], "vel": [0, 200, 0]}   # absurd speed: offset capped at 40 m
    aim, _ = b._engage(tgt, b.me["weapons"])
    lx, ly, _ = land(*aim)
    assert abs(math.hypot(lx - 100, ly) - 40) < 3
    # a target at 215 m running away leads out of shell range: fall back to the unled aim (as main)
    t = {"kind": "mech", "pos": [215, 0, 0], "vel": [11.7, 0, 0]}
    assert make(True)._engage(dict(t), [None, MO])[0] == make(False)._engage(dict(t), [None, MO])[0]


if __name__ == "__main__":
    n = 0
    for k, v in list(globals().items()):
        if k.startswith("test_"):
            v(); n += 1
    print(f"{n} tests OK")
