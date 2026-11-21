"""Unit tests for aim.py (controller wiring). Run: python3 test_aim.py   (math tests: python3 test_aimcore.py)"""
import copy
import gzip
import json
import math
import os
import time

import aim
import aimcore as A

HERE = os.path.dirname(os.path.abspath(__file__))
with gzip.open(os.path.join(HERE, "kit", "check", "stream.jsonl.gz"), "rt") as f:
    _rows = [json.loads(l) for l in f]
HELLO = _rows[0]
CFG = HELLO["config"]
REAL_OBS = [r for r in _rows if r.get("type") == "obs"]
fails = 0


def check(name, ok, extra=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + ((" " + extra) if extra else ""))
    if not ok:
        fails += 1


def gun(ammo=12, cooldown=0.0, reload=0.0):
    return {"kind": "gun", "cooldown": cooldown, "ammo": ammo, "reload": reload, "stats": dict(CFG["weapons"]["gun"])}


def special(kind, cooldown=0.0, charge=0.0):
    w = {"kind": kind, "cooldown": cooldown, "stats": dict(CFG["weapons"][kind])}
    if kind == "laser":
        w["charge"] = charge
    return w


def mk_obs(tick=100, weapons=None, enemies=(), bullets=(), events=(), pos=(0, 0, 0), vel=(0, 0, 0), aim=(0.0, 0.0), in_zone=True,
           zone=None, energy=100):
    return {"type": "obs", "tick": tick, "t": tick / 20.0, "alive": 10,
            "self": {"id": 1, "pos": list(pos), "vel": list(vel), "aim": list(aim), "hp": 1400, "max_hp": 1400, "energy": energy,
                     "grounded": True, "cubes": 0, "in_zone": in_zone, "weapons": weapons if weapons is not None else [gun(), None],
                     "stats": dict(CFG["mech"])},
            "mechs": list(enemies), "projectiles": list(bullets), "crates": [], "cubes": [], "pickups": [], "sounds": [], "beams": [],
            "events": list(events), "drops": [],
            "zone": zone or {"center": [0, 0], "radius": 500, "next_center": [0, 0], "next_radius": 300, "shrink_start": 60, "shrink_end": 110, "dps": 20},
            "offer": None}


def enemy(x, y, vx=0.0, vy=0.0, id=5, cubes=0):
    return {"id": id, "kind": "mech", "pos": [x, y, 0.0], "vel": [vx, vy, 0.0], "aim": [0.0, 0.0], "hp": 1400, "max_hp": 1400,
            "cubes": cubes, "weapons": ["gun"], "charging": False}


def ctl(aim_p=None, move_p=None, seed=3):
    return aim.AimController(CFG, aim_p, move_p, seed=seed)


# ---- params ----
p, kn = aim.AimParams.split({"enabled": False, "strafe_min_range_m": 70, "bogus": 1, "gun_p_min": 0.5}, {"hold_min_dec": 3, "flip_prob": "x"})
check("params: partial override, knobs routed to aimcore, bad type and unknown keys ignored",
      p.enabled is False and p.strafe_min_range_m == 70 and kn == {"gun_p_min": 0.5, "hold_min_dec": 3})
check("params: None sections give defaults", aim.AimParams.split(None, None)[0].enabled is True)
check("disabled controller returns an inert decision", ctl({"enabled": False}).step(mk_obs(enemies=[enemy(100, 0)])).fire is None)

# ---- gun lead + slot-aware fire ----
c = ctl()
d = c.step(mk_obs(enemies=[enemy(100, 0, 0, 11.7)], aim=(0.0, 0.0)))
direct = math.atan2(0.0, 100.0)
check("gun: aim leads a crossing target (yaw ahead of the direct bearing)", d.aim[0] > direct + 0.03, f"yaw={d.aim[0]:.3f}")
check("gun: aligned torso, crossing target at 100 m -> fire gun slot", d.fire == [True, False] and d.p_hit > 0.3, f"p={d.p_hit:.2f}")
d = ctl().step(mk_obs(enemies=[enemy(100, 0)], aim=(2.0, 0.0)))
check("gun: torso 115 deg off target -> hold fire (slew-aware gate) but still command the aim", d.fire == [False, False] and abs(d.aim[0]) < 0.2)
d = ctl().step(mk_obs(weapons=[None, gun()], enemies=[enemy(100, 0)]))
check("slots: gun in slot 1 -> fire[1] only", d.fire == [False, True])
d = ctl().step(mk_obs(weapons=[gun(), special("lightning")], enemies=[enemy(30, 0)]))
check("slots: gun+lightning, target at 30 m -> both fire", d.fire == [True, True])
d = ctl().step(mk_obs(weapons=[special("lightning"), gun()], enemies=[enemy(30, 0)]))
check("slots: lightning in slot 0, gun in slot 1 -> indices follow the weapons", d.fire == [True, True])
d = ctl().step(mk_obs(weapons=[gun(), special("lightning")], enemies=[enemy(80, 0)]))
check("lightning: out of arc range (80 m > 45 m) -> not fired", d.fire == [True, False])
d = ctl().step(mk_obs(weapons=[gun(), special("lightning")], enemies=[enemy(30, 0)], energy=1))
check("lightning: not enough energy -> not fired", d.fire[1] is False)
d = ctl().step(mk_obs(weapons=[gun(ammo=0), None], enemies=[enemy(100, 0)]))
check("gun: empty magazine -> no fire", d.fire == [False, False])
d = ctl().step(mk_obs(weapons=[gun(reload=1.0), None], enemies=[enemy(100, 0)]))
check("gun: reloading -> no fire", d.fire == [False, False])
d = ctl().step(mk_obs(enemies=[enemy(190, 0)]))
check("gun: beyond gun_max_range (190 m > 160 m) -> no fire", d.fire == [False, False])
d = ctl().step(mk_obs(enemies=[enemy(100, 0)]), engage=False)
check("engage=False -> hold fire, no aim override", d.fire is None and d.aim is None)
d = ctl({"gun_p_min": 0.0}).step(mk_obs(enemies=[enemy(190, 0)]))
check("knob: gun_p_min=0 still respects the hard range cap", d.fire == [False, False])

# upgrades change live stats: faster bullets must shorten the lead
fast = mk_obs(enemies=[enemy(150, 0, 0, 11.7)])
slow_d = ctl().step(fast)
fast["self"]["weapons"][0]["stats"]["speed"] = 252 * 1.25 * 4
fast_d = ctl().step(fast)
check("live stats: a faster bullet needs less lead", fast_d.aim[0] < slow_d.aim[0])

# ---- laser ----
d = ctl().step(mk_obs(weapons=[gun(), special("laser")], enemies=[enemy(120, 0)]))
check("laser: ready, target at 120 m -> start charging (fire[laser] held)", d.fire[1] is True and d.reason == "laser_charge")
d = ctl().step(mk_obs(weapons=[gun(), special("laser", cooldown=1.2)], enemies=[enemy(120, 0)]))
check("laser: on cooldown -> not started", d.fire[1] is False)
d = ctl().step(mk_obs(weapons=[gun(), special("laser")], enemies=[enemy(270, 0)]))
check("laser: beyond 90% of range -> not started", d.fire[1] is False)
aimed = A.yp_of(A.unit3((120.0, 0.0, 4.5 - 7.0)))
d = ctl().step(mk_obs(weapons=[gun(), special("laser", charge=0.4)], enemies=[enemy(120, 0)], aim=aimed))
check("laser: charging, not full -> keep holding", d.fire[1] is True and d.reason == "laser_charge")
d = ctl().step(mk_obs(weapons=[gun(), special("laser", charge=0.75)], enemies=[enemy(120, 0)], aim=aimed))
check("laser: full charge and aligned -> release (fire False)", d.fire[1] is False and d.reason == "laser_release", f"p={d.p_hit:.2f}")
c = ctl({"laser_extra_hold_s": 0.3})
outs = [c.step(mk_obs(tick=100 + 2 * i, weapons=[gun(), special("laser", charge=0.75)], enemies=[enemy(120, 0)], aim=(1.0, 0.0))).fire[1]
        for i in range(6)]
check("laser: full charge but never aligned -> released after laser_extra_hold_s (no 2.75 s half-speed trap)", outs[0] is True and outs[-1] is False, str(outs))
d = ctl().step(mk_obs(weapons=[special("laser", charge=0.75), gun()], enemies=[enemy(120, 0)], aim=aimed))
check("laser: slot order respected (laser in slot 0)", d.fire[0] is False and d.reason == "laser_release")

# ---- mortar ----
d = ctl().step(mk_obs(weapons=[gun(), special("mortar")], enemies=[enemy(100, 0)]))
check("mortar: disabled by default -> slot never fired", d.fire[1] is False)
c = ctl({"mortar_enabled": True})
sol = A.solve_mortar(c._me(mk_obs()["self"], c._live(mk_obs()["self"])), dict(pos=(100, 0, 0), vel=(0, 0, 0)), c.k, c._live(mk_obs()["self"]))
d = c.step(mk_obs(weapons=[gun(), special("mortar")], enemies=[enemy(100, 0)], aim=sol["cmd"]))
check("mortar: enabled, stationary target, torso on the solution -> fire", d.fire[1] is True and d.reason == "mortar")
d = c.step(mk_obs(weapons=[gun(), special("mortar")], enemies=[enemy(100, 0, 0, 8)], aim=sol["cmd"]))
check("mortar: moving target -> not fired", d.fire[1] is False)
d = c.step(mk_obs(weapons=[gun(), special("mortar")], enemies=[enemy(100, 0)], aim=sol["cmd"]), traj_clear=lambda s: False)
check("mortar: blocked trajectory -> not fired", d.fire[1] is False)

# ---- idle: reload and facing ----
c = ctl()
d = c.step(mk_obs(tick=400, weapons=[gun(ammo=3), None]))
check("idle: low ammo, no enemy for >= reload_idle_s -> tactical reload", d.reload is True)
d = c.step(mk_obs(tick=402, weapons=[gun(ammo=3, reload=1.5), None]))
check("idle: already reloading -> no second reload", d.reload is False)
c = ctl()
c.step(mk_obs(tick=10, weapons=[gun(ammo=3), None], enemies=[enemy(100, 0)]))
d = c.step(mk_obs(tick=14, weapons=[gun(ammo=3), None]))
check("idle: enemy seen 0.2 s ago -> no reload yet", d.reload is False)
d = ctl().step(mk_obs(tick=100, events=[{"type": "damaged", "amount": 90, "weapon": "gun", "bearing": 2.5, "by": 5, "rear": True}]))
check("idle: damaged from behind -> turn toward the damage bearing", d.aim is not None and abs(d.aim[0] - 2.5) < 1e-9 and d.reason == "face_hit")
c = ctl()
c.step(mk_obs(tick=100, events=[{"type": "damaged", "amount": 90, "weapon": "gun", "bearing": 2.5, "by": 5, "rear": True}]))
check("idle: bearing expires after hit_turn_s", c.step(mk_obs(tick=200)).aim is None)
check("idle: nothing to do -> leaves the caller's aim and fire alone", ctl().step(mk_obs()).fire is None and ctl().step(mk_obs()).aim is None)

# ---- fight movement suggestion ----
c = ctl()
d = c.step(mk_obs(enemies=[enemy(100, 0)], aim=(0.0, 0.0)))
check("move: target at 100 m -> strafe is perpendicular to the line of sight", d.move is not None and abs(d.move[1]) > 0.8 and abs(d.move[0]) < 0.5, str(d.move))
check("move: inside strafe_min_range (30 m) -> no override", ctl().step(mk_obs(enemies=[enemy(30, 0)])).move is None)
check("move: out of zone -> no override (zone safety wins)", ctl().step(mk_obs(enemies=[enemy(100, 0)], in_zone=False)).move is None)
edge = {"center": [0, 0], "radius": 20, "next_center": [0, 0], "next_radius": 10, "shrink_start": 60, "shrink_end": 110, "dps": 20}
check("move: within zone_margin of the edge -> no override", ctl().step(mk_obs(enemies=[enemy(100, 0)], zone=edge)).move is None)
check("move: suppress_move (e.g. loot roof climb) -> no override", ctl().step(mk_obs(enemies=[enemy(100, 0)]), suppress_move=True).move is None)
check("move: strafe_enabled=false -> no override", ctl({}, {"strafe_enabled": False}).step(mk_obs(enemies=[enemy(100, 0)])).move is None)
d = ctl().step(mk_obs(enemies=[enemy(55, 0)]))
check("move: target at 55 m (inside range_lo 60) -> strafe plus a retreat component", d.move[0] < -0.3, str(d.move))
d = ctl().step(mk_obs(enemies=[enemy(200, 0)]))
check("move: target at 200 m (beyond range_hi 140) -> strafe plus an advance component", d.move[0] > 0.3, str(d.move))
c = ctl()
signs = []
for i in range(120):
    m = c.step(mk_obs(tick=100 + 2 * i, enemies=[enemy(100, 0)])).move
    signs.append(1 if m[1] > 0 else -1)
flips = sum(1 for a, b in zip(signs, signs[1:]) if a != b)
check("move: strafe reverses at random intervals (12 s, expect 12 to 30 flips)", 12 <= flips <= 30, f"flips={flips}")
# dodge: bullet on a collision course from the west, 100 m out, aimed at the centre
b = {"id": 1, "kind": "gun", "pos": [-100.0, 0.3, 4.5], "vel": [252.0, 0.0, 0.0]}
d = ctl({}, {"flip_prob": 1.0}).step(mk_obs(enemies=[enemy(0, 150)], bullets=[b]))
c0 = ctl({}, {"flip_prob": 1.0})
cfg0, me0 = c0._live(mk_obs()["self"]), c0._me(mk_obs()["self"], c0._live(mk_obs()["self"]))
pen_stay = A.bullet_pen((0.0, 0.0), me0, [dict(pos=b["pos"], vel=b["vel"])], c0.k, cfg0)
pen_move = A.bullet_pen((d.move[0] * 11.7, d.move[1] * 11.7), me0, [dict(pos=b["pos"], vel=b["vel"])], c0.k, cfg0)
check("dodge: head-on bullet -> suggested move has ~0 predicted hit penalty (standing still would not)", pen_stay > 0.5 and pen_move < 0.05,
      f"stay={pen_stay:.2f} move={pen_move:.3f} dir={d.move}")
npc = {"id": 2, "kind": "mortar", "pos": [-100.0, 0.3, 4.5], "vel": [252.0, 0.0, 0.0]}
check("dodge: mortar shells are not treated as bullets", ctl().step(mk_obs(enemies=[enemy(0, 150)], bullets=[npc])).move is not None)

# ---- robustness and budget ----
c = ctl()
ok = True
for o in REAL_OBS:
    try:
        c.step(o)
    except Exception as e:  # noqa
        ok = False
        print("   exception:", repr(e))
        break
check("replay: controller survives all 300 recorded kit observations", ok)
many = mk_obs(weapons=[gun(), special("laser", charge=0.3)], enemies=[enemy(60 + 15 * i, 20 * i - 40, 5, -3, id=3 + i, cubes=i) for i in range(6)],
              bullets=[{"id": 10 + i, "kind": "gun", "pos": [-80.0 - 6 * i, 0.5 * i, 4.5], "vel": [252.0, 0.0, 0.0]} for i in range(12)],
              aim=(0.2, 0.0))
ts = []
c = ctl()
for _ in range(200):
    t0 = time.perf_counter()
    c.step(many)
    ts.append((time.perf_counter() - t0) * 1000)
ts.sort()
check("budget: 6 enemies + laser + 12 bullets, median < 5 ms and worst < 10 ms", ts[100] < 5.0 and ts[-1] < 10.0, f"median={ts[100]:.2f} p99={ts[197]:.2f} worst={ts[-1]:.2f} ms")
ts = []
for o in REAL_OBS:
    t0 = time.perf_counter()
    c.step(o)
    ts.append((time.perf_counter() - t0) * 1000)
ts.sort()
print(f"INFO real observations: median={ts[150]:.3f} ms p99={ts[296]:.3f} ms max={ts[-1]:.3f} ms")

print("\nFAILS:", fails)
raise SystemExit(1 if fails else 0)
