"""Self-checks for aimcore: every solver is verified against an independent forward simulation."""
import math
import random
import aimcore as A

K = A.knobs()
CFG = A.CFG
M = CFG["mech"]
rng = random.Random(7)
fails = 0


def check(name, ok, extra=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + (("  " + extra) if extra else ""))
    if not ok:
        fails += 1


def mk_me(pos=(0, 0, 0), vel=(0, 0, 0), aim=(0, 0)):
    return dict(pos=pos, vel=vel, aim=aim, radius=2.5, height=9.0, muzzle_h=7.0, turn_rate=4.0, pitch_rate=3.0)


# ---- 1. gun intercept vs forward sim (constant-velocity target; aim already on the commanded line) ----
worst = 0.0
for trial in range(400):
    R = rng.uniform(20, 200)
    bearing = rng.uniform(-math.pi, math.pi)
    sp = rng.uniform(0, 19.5)
    heading = rng.uniform(-math.pi, math.pi)
    tgt = dict(pos=(R * math.cos(bearing), R * math.sin(bearing), rng.uniform(-3, 3)),
               vel=(sp * math.cos(heading), sp * math.sin(heading), 0.0), cubes=rng.randint(0, 6))
    me = mk_me(vel=(rng.uniform(-6, 6), rng.uniform(-6, 6), 0))
    cd = rng.choice([0.0, 0.08])
    sol = A.solve_gun(me, tgt, K, CFG, cooldown=cd)
    d = A.dir_yp(*sol["cmd"])
    t_fire = sol["t_fire"]
    mz = (me["pos"][0] + me["vel"][0] * t_fire, me["pos"][1] + me["vel"][1] * t_fire, me["pos"][2] + 7.0)
    org = tuple(mz[i] + 3.0 * d[i] for i in range(3))     # radius+0.5 out along aim
    _, th = A.target_dims(tgt)
    # exact closest approach of two constant-velocity points (independent of the solver's iteration)
    r0 = [org[j] - (tgt["pos"][j] + (0.5 * th if j == 2 else 0.0)) - tgt["vel"][j] * t_fire for j in range(3)]
    w = [252.0 * d[j] - tgt["vel"][j] for j in range(3)]
    ts = max(0.0, -sum(r0[j] * w[j] for j in range(3)) / sum(x * x for x in w))
    best = math.sqrt(sum((r0[j] + w[j] * ts) ** 2 for j in range(3)))
    worst = max(worst, best)
check("gun intercept: bullet passes within 0.05 m of predicted centre (400 random cases)", worst < 0.05, f"worst={worst:.4f} m")

# lead_order 0 sanity: 11.7 m/s lateral target at 100 m must miss by metres
k0 = A.knobs({"lead_order": 0})
tgt = dict(pos=(100, 0, 0), vel=(0, 11.7, 0), cubes=0)
sol0 = A.solve_gun(mk_me(), tgt, k0, CFG)
sol1 = A.solve_gun(mk_me(), tgt, K, CFG)
d0, d1 = A.dir_yp(*sol0["cmd"]), A.dir_yp(*sol1["cmd"])
lat_err = abs(math.tan(sol1["cmd"][0] - sol0["cmd"][0])) * 100
check("lead matters: zero-lead aim is >3 m off a 11.7 m/s strafer at 100 m", lat_err > 3.0, f"{lat_err:.2f} m")

# ---- 2. slew ----
a = A.slew_aim((0.0, 0.0), (3.0, 0.0), 0.1, 4.0, 3.0, -0.7, 1.3)
check("yaw slew caps at turn_rate*dt (0.4 rad per decision)", abs(a[0] - 0.4) < 1e-9, f"{a[0]:.3f}")
a = A.slew_aim((3.0, 0.0), (-3.0, 0.0), 0.1, 4.0, 3.0, -0.7, 1.3)
check("yaw slew takes the short way across +-pi", a[0] > 3.0 or a[0] < -3.0 + 1e-9 and abs(A.wrap_pi(a[0] - 3.0)) - 0.4 < 1e-9)
check("180 degree turn takes pi/4 s", abs(A.slew_time((0, 0), (math.pi, 0), 4.0, 3.0) - math.pi / 4) < 1e-9)
a = A.slew_aim((0, 0), (0, 5.0), 1.0, 4.0, 3.0, -0.7, 1.3)
check("pitch command clamped to max_pitch", abs(a[1] - 1.3) < 1e-9)

# ---- 3. mortar vs forward sim ----
def mortar_miss(me, tgt):
    sol = A.solve_mortar(me, tgt, K, CFG)
    if sol is None:
        return None, None
    # forward-simulate the real parabola from the real origin rule and compare at flight time with predicted point
    d = A.dir_yp(*sol["cmd"])
    tube = (me["pos"][0] + me["vel"][0] * sol["t_fire"], me["pos"][1] + me["vel"][1] * sol["t_fire"], me["pos"][2] + 9.5)
    org = tuple(tube[i] + 3.0 * d[i] for i in range(3))
    sp = A.shell_pos(org, sol["cmd"], sol["tf"], CFG)
    tp = A.predict_pos(tgt, sol["T"], K)
    th = 9.0 * A.size_scale(tgt.get("cubes", 0))
    return math.hypot(sp[0] - tp[0], sp[1] - tp[1]), abs(sp[2] - (tp[2] + 0.5 * th)), sol


worst_xy = worst_z = 0.0
n_ok = 0
for trial in range(300):
    R = rng.uniform(25, 220)
    br = rng.uniform(-math.pi, math.pi)
    sp = rng.uniform(0, 12)
    hd = rng.uniform(-math.pi, math.pi)
    tgt = dict(pos=(R * math.cos(br), R * math.sin(br), rng.uniform(-6, 6)), vel=(sp * math.cos(hd), sp * math.sin(hd), 0), cubes=0)
    out = mortar_miss(mk_me(), tgt)
    if out[0] is None:
        continue
    n_ok += 1
    worst_xy = max(worst_xy, out[0])
    worst_z = max(worst_z, out[1])
check("mortar solver: shell reaches predicted point (xy and z) in forward sim", worst_xy < 0.05 and worst_z < 0.05 and n_ok > 150,
      f"solved={n_ok}/300 worst xy={worst_xy:.4f} z={worst_z:.4f}")
sol = A.solve_mortar(mk_me(), dict(pos=(100, 0, 5.0), vel=(0, 0, 0)), K, CFG)   # centre at tube height: h~0, textbook case
check("mortar 100 m level low arc: pitch ~12.5 deg, flight ~1.4 s", sol and abs(math.degrees(sol["cmd"][1]) - 12.5) < 1.0 and 1.3 < sol["tf"] < 1.6,
      f"pitch={math.degrees(sol['cmd'][1]):.2f} tf={sol['tf']:.2f}")
check("mortar beyond max range returns None", A.solve_mortar(mk_me(), dict(pos=(260, 0, 0), vel=(0, 0, 0)), K, CFG) is None)
sol_h = A.solve_mortar(mk_me(), dict(pos=(150, 0, 5.0), vel=(0, 0, 0)), K, CFG, arc="high")
check("mortar high arc at 150 m is a ~6 s lob, inside ttl 7 s", sol_h and 5.5 < sol_h["tf"] < 7.0, f"tf={sol_h['tf']:.2f}" if sol_h else "None")
check("mortar high arc at 100 m is NOT available (needs pitch > max_pitch 1.3 rad)", A.solve_mortar(mk_me(), dict(pos=(100, 0, 5.0), vel=(0, 0, 0)), K, CFG, arc="high") is None)
mn = min(R for R in range(40, 240, 2) if A.solve_mortar(mk_me(), dict(pos=(R, 0, 5.0), vel=(0, 0, 0)), K, CFG, arc="high"))
print("INFO shortest level range the high (lob) arc can reach:", mn, "m")
t_by_range = {R: A.solve_mortar(mk_me(), dict(pos=(R, 0, 0), vel=(0, 0, 0)), K, CFG)["tf"] for R in (50, 100, 150, 200)}
print("INFO mortar low-arc flight time by range:", {r: round(t, 2) for r, t in t_by_range.items()})
check("mortar damage model: centre=360, edge of 7 m=48, outside=0",
      abs(A.mortar_damage_at(0, K) - 360) < 1e-6 and abs(A.mortar_damage_at(7, K) - 48) < 1e-6 and A.mortar_damage_at(7.1, K) == 0)

# runtime mortar expectation table: monotone decreasing in flight time, 360 ceiling
vals = [A.expected_mortar_damage_table(T, K) for T in (0.1, 0.5, 1.0, 1.4, 2.2, 3.0, 5.0)]
check("mortar E[dmg] table decreases with flight time and stays below the 360 stationary value", all(x >= y for x, y in zip(vals, vals[1:])) and vals[0] <= 360,
      str([round(v) for v in vals]))
check("man_sigma monotone and extrapolates", A.man_sigma(0.5, K) < A.man_sigma(1.0, K) < A.man_sigma(3.0, K) < A.man_sigma(4.0, K))

# ---- 4. laser ----
check("laser damage curve 110/151/315", abs(A.laser_damage(0) - 110.25) < 1e-6 and abs(A.laser_damage(0.15) - 151.2) < 0.1 and abs(A.laser_damage(0.75) - 315) < 1e-6)
tgt = dict(pos=(100, 0, 0), vel=(0, 11.7, 0), cubes=0)
me_aligned = mk_me(aim=A.yp_of(A.unit3((100, 0.585, 4.5 - 7))))
dec = A.laser_decision(me_aligned, tgt, 0.75, K, CFG)
check("laser: aligned + full charge -> release", dec["release"] and dec["p_hit"] > 0.9, f"p={dec['p_hit']:.3f}")
dec = A.laser_decision(mk_me(aim=(1.0, 0.0)), tgt, 0.75, K, CFG)
check("laser: 57 deg off target -> do not release, keep slewing", (not dec["release"]) and dec["p_hit"] < 0.01)
dec = A.laser_decision(me_aligned, tgt, 0.4, K, CFG)
check("laser: hold_full keeps charging at 0.4 s", dec["hold"] and not dec["release"])
enemy = dict(pos=(0, 0, 0), aim=A.yp_of(A.unit3((150, 1.0, 4.5 - 7))), charging=True)
perp, along = A.beam_line_offset((150, 1.0, 0), 0, enemy)
check("beam_line_offset: ray through my centre -> ~0 m", perp < 1e-6 and abs(along - 150) < 0.1, f"perp={perp:.2e} along={along:.1f}")
check("laser_line_on_me true when aimed at me and false when 20 m wide", A.laser_line_on_me((150, 1.0, 0), 0, enemy, K) and
      not A.laser_line_on_me((150, 21.0, 0), 0, enemy, K))

# ---- lightning ----
ents = [dict(id=1, kind="crate", pos=(20, 5, 0)), dict(id=2, kind="mech", pos=(30, 0, 0)), dict(id=3, kind="mech", pos=(10, 40, 0))]
check("lightning picks the NEAREST thing in the cone (a crate steals the arc from the mech behind it)",
      A.lightning_target((0, 0, 0), 0.0, ents)["id"] == 1)
check("lightning ignores targets outside the cone and beyond 45 m", A.lightning_target((0, 0, 0), math.pi, ents) is None)
check("lightning respects line of sight", A.lightning_target((0, 0, 0), 0.0, ents, los=lambda a, b: b[0] > 25)["id"] == 2)

# ---- 5. dodge scorer ----
def bullet_toward(me_pos, dist, offset_lat, vz=0.0):
    # bullet flying in +x aimed to pass offset_lat metres north of my centre, starting dist metres west
    return dict(pos=(me_pos[0] - dist, me_pos[1] + offset_lat, me_pos[2] + 4.5), vel=(252.0, 0.0, vz))

me = dict(pos=(0, 0, 0), vel=(0, 0, 0), radius=2.5, height=9.0)
b = [bullet_toward((0, 0, 0), 100.0, 0.5)]      # arrives in 0.40 s, would hit
stay = A.bullet_pen((0, 0), me, b, K)
(vel, cost) = A.choose_move(me, b, None, 11.7, K)
check("dodge: head-on bullet with 0.4 s to impact is dodgeable sideways", stay > 0.6 and cost < 0.05 and abs(vel[1]) > 5,
      f"stay_pen={stay:.2f} best_cost={cost:.3f} vel={vel[0]:.1f},{vel[1]:.1f}")
b = [bullet_toward((0, 0, 0), 20.0, 0.5)]       # 0.08 s to impact: physics says no
(vel, cost) = A.choose_move(me, b, None, 11.7, K)
check("dodge: bullet 20 m out (0.08 s) cannot be dodged - cost stays high", cost > 0.5, f"best_cost={cost:.2f}")
b = [bullet_toward((0, 0, 0), 100.0, -7.0)]     # already missing by 7 m (south side), nav wants north
(vel, cost) = A.choose_move(me, b, (0.0, 1.0), 11.7, K)
check("dodge: bullet missing anyway -> follow nav direction", cost < 1e-6 and vel[1] > 11.0, f"vel={vel}")
b = [bullet_toward((0, 0, 0), 100.0, 0.5, vz=0.0)]
b[0]["pos"] = (b[0]["pos"][0], b[0]["pos"][1], 20.0)  # flying 20 m up: over a 9 m mech
check("dodge: bullet passing above the 9 m cylinder is ignored", A.bullet_pen((0, 0), me, b, K) == 0.0)

# ---- 6. strafer ----
st = A.Strafer(3, K)
holds, last, run = [], None, 0
for i in range(2000):
    d = st.step((1.0, 0.0), 100.0)
    s = 1 if d[1] > 0 else -1
    if last is None or s == last:
        run += 1
    else:
        holds.append(run)
        run = 1
    last = s
check("strafer: holds within [min,max] decisions and flips every time", min(holds[1:]) >= K["hold_min_dec"] and max(holds[1:]) <= K["hold_max_dec"],
      f"min={min(holds[1:])} max={max(holds[1:])} n={len(holds)}")
d = st.step((1.0, 0.0), 30.0)
check("strafer: too close adds a retreat component, too far adds an advance", d[0] < -0.3 and st.step((1.0, 0.0), 200.0)[0] > 0.3)

print("\nFAILS:", fails)
raise SystemExit(1 if fails else 0)
