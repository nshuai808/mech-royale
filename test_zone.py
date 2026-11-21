import math, random, sys, time
import gzip, json, os, subprocess
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from zone import ZoneTracker, ZoneParams, Circle, FREE, SOON, GO, CRITICAL, INF

CFG = {"config": {"mech": {"radius": 2.5, "walk_speed": 11.7, "boost_speed": 19.5, "boost_drain": 17},
       "zone": {"start_center": [41.3, -72.8], "start_radius": 560, "phases": [
           {"hold_s": 60, "shrink_s": 50, "radius": 380, "dps": 20},
           {"hold_s": 45, "shrink_s": 40, "radius": 240, "dps": 35},
           {"hold_s": 35, "shrink_s": 35, "radius": 140, "dps": 60},
           {"hold_s": 30, "shrink_s": 30, "radius": 70, "dps": 100},
           {"hold_s": 25, "shrink_s": 25, "radius": 25, "dps": 160},
           {"hold_s": 15, "shrink_s": 25, "radius": 0, "dps": 260}]}}}

def obs(t, pos, cur, nxt, s0, s1, dps=20, in_zone=None, events=(), cubes=0, hp=1400, energy=100):
    if in_zone is None:
        in_zone = math.hypot(pos[0]-cur[0], pos[1]-cur[1]) <= cur[2]
    return {"t": t, "self": {"pos": [pos[0], pos[1], 0], "vel": [0,0,0], "in_zone": in_zone, "cubes": cubes,
            "hp": hp, "energy": energy},
            "zone": {"center": cur[:2], "radius": cur[2], "next_center": nxt[:2], "next_radius": nxt[2],
                     "shrink_start": s0, "shrink_end": s1, "dps": dps}, "events": list(events)}

def brute_exit(p, cur, nxt, s0, s1, t0, inset=0.0, dt=0.001):
    t = t0
    while t <= s1 + 1:
        c = ZoneTracker.circle_at(Circle(*cur), Circle(*nxt), s0, s1, t)
        if math.hypot(p[0]-c.cx, p[1]-c.cy) > c.r - inset:
            return t
        t += dt
    return INF

def test_circle_at():
    cur, nxt = Circle(0, 0, 100), Circle(20, -10, 40)
    assert ZoneTracker.circle_at(cur, nxt, 10, 20, 5) == cur
    assert ZoneTracker.circle_at(cur, nxt, 10, 20, 25) == nxt
    c = ZoneTracker.circle_at(cur, nxt, 10, 20, 15)
    assert (c.cx, c.cy, c.r) == (10, -5, 70)
    # degenerate window
    assert ZoneTracker.circle_at(cur, nxt, 10, 10, 10) == cur
    assert ZoneTracker.circle_at(cur, nxt, 10, 10, 11) == nxt

def test_first_exit_matches_bruteforce():
    rnd = random.Random(1)
    for _ in range(300):
        cur = (rnd.uniform(-50, 50), rnd.uniform(-50, 50), rnd.uniform(100, 500))
        nr = rnd.uniform(0, cur[2] * 0.8)
        ang, off = rnd.uniform(0, 6.28), rnd.uniform(0, cur[2] - nr)
        nxt = (cur[0] + off*math.cos(ang), cur[1] + off*math.sin(ang), nr)
        s0 = rnd.uniform(0, 50); s1 = s0 + rnd.uniform(10, 60)
        ang2, d = rnd.uniform(0, 6.28), rnd.uniform(0, cur[2] * 0.99)
        p = (cur[0] + d*math.cos(ang2), cur[1] + d*math.sin(ang2))
        t0 = rnd.uniform(0, s1)
        inset = rnd.choice([0, 8.5])
        want = brute_exit(p, cur, nxt, s0, s1, t0, inset)
        got = ZoneTracker.first_exit(p, Circle(*cur), Circle(*nxt), s0, s1, t0, inset)
        if want == INF:
            assert got == INF or got >= s1 - 1e-6, (p, cur, nxt, s0, s1, t0, got)
        else:
            assert abs(got - want) < 0.01, (got, want, p, cur, nxt, s0, s1, t0, inset)

def test_phase_and_free():
    tr = ZoneTracker(CFG)
    cur, nxt = (41.3, -72.8, 560), (-42.1, 7.1, 380)
    p = tr.update(obs(10, (-40, 5), cur, nxt, 60, 110))
    assert p.urgency == FREE and p.goal is None and p.inside, p
    assert p.phase == 0

def test_edge_position_must_leave():
    tr = ZoneTracker(CFG)
    cur, nxt = (0, 0, 560), (0, 0, 380)
    p = tr.update(obs(55, (540, 0), cur, nxt, 60, 110))     # 20 m inside the edge, shrink in 5 s
    assert p.urgency >= GO and p.goal is not None
    assert p.goal[0] < 380, p.goal
    assert math.isfinite(p.est_damage)

def test_outside_is_go_or_worse_and_goal_inside_next():
    tr = ZoneTracker(CFG)
    cur, nxt = (0, 0, 560), (-100, 0, 380)
    p = tr.update(obs(30, (600, 0), cur, nxt, 60, 110))
    assert not p.inside and p.urgency >= GO
    assert math.hypot(p.goal[0] + 100, p.goal[1]) <= 380

def test_critical_when_far_and_low_hp():
    tr = ZoneTracker(CFG)
    cur, nxt = (0, 0, 70), (0, 0, 25)
    p = tr.update(obs(250, (150, 0), cur, nxt, 245, 270, dps=100, hp=300, in_zone=False))
    assert p.urgency == CRITICAL

def test_final_circle_zero():
    tr = ZoneTracker(CFG)
    cur, nxt = (10, 10, 25), (12, 9, 0)
    p = tr.update(obs(380, (14, 14), cur, nxt, 395, 420, dps=260))
    assert p.goal == (12, 9) or math.hypot(p.goal[0]-12, p.goal[1]-9) < 1.0

def test_in_zone_authority_and_calibration():
    tr = ZoneTracker(CFG)
    cur, nxt = (0, 0, 560), (0, 0, 380)
    # server says edge is 3 m further out than geometry: flip at raw margin -3
    for i, x in enumerate([550, 556, 558, 560, 562, 563.5, 565]):
        inside = x <= 563
        p = tr.update(obs(10 + i*0.1, (x, 0), cur, nxt, 60, 110, in_zone=inside))
        assert p.inside == inside
    assert 1.0 < abs(tr.edge_bias) <= 6.0 and tr.edge_bias > 0   # raw margin was negative when still inside
    assert tr.mismatches >= 1

def test_zone_damage_event_forces_outside():
    tr = ZoneTracker(CFG)
    cur, nxt = (0, 0, 560), (0, 0, 380)
    p = tr.update(obs(20, (500, 0), cur, nxt, 60, 110, in_zone=True,
                      events=[{"type": "damaged", "weapon": "zone", "by": None, "amount": 20}]))
    assert not p.inside and p.margin < 0

def test_garbage_never_raises():
    tr = ZoneTracker(CFG)
    assert tr.update({}) is None
    assert tr.update({"zone": None, "self": {}}) is None
    assert tr.update({"t": float("nan"), "self": {"pos": [0, 0, 0]},
                      "zone": {"center": [0, 0], "radius": 1, "next_center": [0, 0], "next_radius": 0,
                               "shrink_start": 0, "shrink_end": 1}}) is None
    # next bigger than current, missing in_zone, zero-length shrink
    p = tr.update({"t": 5, "self": {"pos": [3, 3, 0]},
                   "zone": {"center": [0, 0], "radius": 50, "next_center": [0, 0], "next_radius": 80,
                            "shrink_start": 5, "shrink_end": 5}})
    assert p is not None
    # hello missing entirely
    ZoneTracker(None).update(obs(1, (0, 0), (0, 0, 100), (0, 0, 50), 10, 20))
    ZoneTracker({}).update(obs(1, (0, 0), (0, 0, 100), (0, 0, 50), 10, 20))

def test_full_match_simulation_survives_with_plan():
    """Follow the plan through all 6 shrinks with random nested centers; zone damage should stay small."""
    rnd = random.Random(7)
    tr = ZoneTracker(CFG)
    phases = CFG["config"]["zone"]["phases"]
    cur = (41.3, -72.8, 560.0)
    pos = [rnd.uniform(-300, 400), rnd.uniform(-300, 200)]
    t, dt, total, t0 = 0.0, 0.1, 0.0, 0.0
    worst_calls = 0.0
    for ph in phases:
        nr = ph["radius"]
        ang, off = rnd.uniform(0, 6.28), rnd.uniform(0, (cur[2]-nr)*0.95)
        nxt = (cur[0] + off*math.cos(ang), cur[1] + off*math.sin(ang), nr)
        s0, s1 = t0 + ph["hold_s"], t0 + ph["hold_s"] + ph["shrink_s"]
        while t < s1:
            c = ZoneTracker.circle_at(Circle(*cur), Circle(*nxt), s0, s1, t)
            inside = math.hypot(pos[0]-c.cx, pos[1]-c.cy) <= c.r
            dps = ph["dps"]
            if not inside:
                total += dps * dt
            a = time.perf_counter()
            plan = tr.update(obs(t, pos, cur, nxt, s0, s1, dps=dps, in_zone=inside, energy=100))
            worst_calls = max(worst_calls, time.perf_counter() - a)
            if plan.goal:
                d = math.hypot(plan.goal[0]-pos[0], plan.goal[1]-pos[1])
                v = (19.5 if plan.boost else 11.7) * dt
                if d > 0.1:
                    k = min(1, v/d); pos[0] += (plan.goal[0]-pos[0])*k; pos[1] += (plan.goal[1]-pos[1])*k
            t += dt
        cur, t0 = nxt, s1
        t = s1
    print(f"total zone damage {total:.0f}, worst update {worst_calls*1000:.2f} ms, errors {tr.errors}")
    assert tr.errors == 0
    assert worst_calls < 0.010, worst_calls      # leave >=40 ms of the 50 ms budget to the rest of the bot
    assert total < 400, total


def test_params_partial_and_bad_values():
    p = ZoneParams.from_dict({"base_margin_m": "9", "bogus": 1, "go_slack_s": "nope", "enabled": 0, "idle_goal": "comfort"})
    assert p.base_margin_m == 9.0 and p.go_slack_s == 6.0 and p.enabled is False and p.idle_goal == "comfort"
    assert ZoneParams.from_dict(None) == ZoneParams() and ZoneParams.from_dict("x") == ZoneParams()
    # a bigger margin makes a point near the edge more urgent
    cur, nxt = (0, 0, 560), (0, 0, 380)
    a = ZoneTracker(CFG, {"base_margin_m": 0}).update(obs(10, (370, 0), cur, nxt, 60, 110))
    b = ZoneTracker(CFG, {"base_margin_m": 20}).update(obs(10, (370, 0), cur, nxt, 60, 110))
    assert b.goal is not None and (a.goal is None or b.urgency >= a.urgency)

def test_drop_is_safe():
    tr = ZoneTracker(CFG)
    cur, nxt = (0, 0, 560), (0, 0, 380)
    plan = tr.update(obs(75, (100, 0), cur, nxt, 60, 110))
    assert tr.drop_is_safe({"pos": [50, 0, 0], "radius": 8, "lands_in": 20}, plan, (100, 0))
    assert not tr.drop_is_safe({"pos": [400, 0, 0], "radius": 8, "lands_in": 20}, plan, (100, 0))
    assert not tr.drop_is_safe({}, plan, (100, 0))

# ---- bot.py integration: run the real bot over the protocol with synthetic observations
def _run_bot(obs_list, params_override=None):
    stream = os.path.join(HERE, "kit", "check", "stream.jsonl.gz")
    lines = gzip.open(stream, "rt").read().splitlines()
    hello = json.loads(lines[0])
    first = next(json.loads(l) for l in lines[1:] if json.loads(l).get("type") == "obs")
    env = dict(os.environ)
    if params_override is not None:
        import tempfile, shutil
        d = tempfile.mkdtemp()
        for f in os.listdir(HERE):
            if f.endswith(".py") or f == "params.json":
                shutil.copy(os.path.join(HERE, f), d)
        pj = json.load(open(os.path.join(d, "params.json"))); pj["zone"].update(params_override)
        json.dump(pj, open(os.path.join(d, "params.json"), "w"))
        bot_dir = d
    else:
        bot_dir = HERE
    # interactive lockstep (the wrapper drops queued observations, so feed one at a time)
    proc = subprocess.Popen([sys.executable, "-u", os.path.join(bot_dir, "bot.py")], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=bot_dir, env=env)
    acts = []
    try:
        proc.stdin.write(json.dumps(hello) + "\n"); proc.stdin.flush()
        assert json.loads(proc.stdout.readline())["type"] == "ready"
        for i, mut in enumerate(obs_list):
            o = json.loads(json.dumps(first)); o["tick"] = 1000 + i * 2
            mut(o)
            proc.stdin.write(json.dumps(o) + "\n"); proc.stdin.flush()
            line = proc.stdout.readline()
            assert line, proc.stderr.read()
            acts.append(json.loads(line))
        proc.stdin.write(json.dumps({"type": "end", "place": 3, "kills": 0}) + "\n"); proc.stdin.flush()
        proc.wait(timeout=10)
    finally:
        if proc.poll() is None:
            proc.kill()
    return acts

def _outside_zone(o):
    o["self"]["pos"] = [600.0, 0.0, 0.0]; o["self"]["in_zone"] = False; o["pickups"] = []; o["mechs"] = []
    o["zone"] = {"center": [0, 0], "radius": 560, "next_center": [-100, 0], "next_radius": 380,
                 "shrink_start": 60, "shrink_end": 110, "dps": 20}
    o["t"] = 30.0

def test_bot_runs_to_zone_when_outside():
    (a,) = _run_bot([_outside_zone])
    assert a["move"][0] < -0.9 and a["boost"] is True, a

def test_bot_zone_disabled_falls_back():
    (a,) = _run_bot([_outside_zone], {"enabled": False})
    assert a["move"][0] < -0.9          # v1 behaviour: straight to next_center
    # and the zone tracker really is off: no crash with garbage zone either
    def bad(o): _outside_zone(o); o["zone"]["radius"] = float("nan")
    _run_bot([bad], {"enabled": True})

def test_bot_zone_overrides_loot_when_urgent():
    def loot_behind_us(o):
        _outside_zone(o)
        o["pickups"] = [{"id": 8001, "kind": "lightning", "pos": [700.0, 0.0, 0.0]}]   # away from the zone
    (a,) = _run_bot([loot_behind_us])
    assert a["move"][0] < -0.9 and "take" not in a

if __name__ == "__main__":
    fails = 0
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            try:
                f(); print("ok  ", n)
            except Exception as e:
                import traceback; traceback.print_exc(); print("FAIL", n); fails += 1
    sys.exit(1 if fails else 0)
