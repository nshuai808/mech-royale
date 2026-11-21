"""aimcore.py - reference math for H-AIM / H-MOV (protocol mechfight/1). Python stdlib only.

Pure functions, no I/O, no globals except DEFAULT_KNOBS. Every tunable lives in the knob dict
(params.json "aim" section). Geometry comes from hello.config / obs.self.stats at runtime;
the CFG dict below mirrors the kit's recorded hello so tests can run offline.
Frames: x east, y north, z up, meters, seconds, radians (protocol section 5).
"""
import math
import random

PI = math.pi

# ---- numbers from the kit's recorded hello (read them from hello.config at runtime!) ----
CFG = {
    "mech": dict(radius=2.5, height=9.0, muzzle_height=7.0, walk_speed=11.7, boost_speed=19.5,
                 ground_accel=58.5, turn_rate=4.0, pitch_rate=3.0, min_pitch=-0.7, max_pitch=1.3,
                 rear_mult=1.5, front_arc_deg=180.0),
    "gun": dict(damage=45.0, cooldown=0.24, speed=252.0, range=230.0, spread_deg=0.6, mag=12, reload=2.4),
    "mortar": dict(damage=200.0, splash=160.0, splash_radius=7.0, splash_edge=0.3, cooldown=2.6,
                   speed=72.0, gravity=22.0, ttl=7.0, knock=16.0, knock_up=9.0, drain=45.0),
    "laser": dict(damage=315.0, charge=0.75, min_charge=0.15, min_frac=0.35, hold_s=2.0,
                  cooldown=1.65, range=280.0, cookoff=0.6),
    "projectile": dict(gun_radius=0.3),
    "size_per_cube": 0.05,
}

DEFAULT_KNOBS = {
    # timing model (calibrate in sim: see spec section 12)
    "dt": 0.05,                    # one sim tick
    "fire_delay_s": 0.05,          # decision -> first tick at which a shot can leave
    "laser_release_delay_s": 0.05,
    # lead
    "lead_order": 1,               # 0 none, 1 linear, 2 linear+damped accel
    "accel_gain": 0.0,             # only used when lead_order == 2
    "accel_tau_s": 0.4,
    # maneuver uncertainty of the target: (horizon s, RMS perpendicular error m). From recorded house-bot track, L1.
    "man_sigma_table": [[0.0, 0.0], [0.1, 0.27], [0.2, 0.75], [0.3, 1.39], [0.4, 2.16], [0.6, 4.05], [0.8, 6.18],
                        [1.0, 8.28], [1.2, 10.25], [1.5, 12.67], [2.0, 17.22], [3.0, 30.74]],
    "man_sigma_scale": 1.0,
    # gun fire gate
    "gun_p_min": 0.30,
    "gun_max_range_m": 160.0,
    "reload_idle_ammo_frac": 0.5,
    # mortar
    "mortar_arc": "low",
    "mortar_min_range_m": 14.0,
    "mortar_min_exp_dmg": 90.0,
    "mortar_edmg_table": [[0.1, 356], [0.2, 349], [0.3, 318], [0.5, 238], [0.7, 157], [1.0, 84], [1.4, 40], [1.8, 16],
                          [2.2, 10], [3.0, 5]],
    "mortar_direct_extra_m": 0.3,
    "mortar_splash_surface": 0.0,  # metres subtracted from blast->target distance (0 = measured to centre)
    # laser
    "laser_release_p": 0.80,
    "laser_hold_full": True,
    # strafing / dodging
    "hold_min_dec": 4, "hold_max_dec": 10,   # strafe hold in decisions (0.1 s each)
    "flip_prob": 1.0,
    "strafe_speed_frac": 1.0,
    "range_lo_m": 60.0, "range_hi_m": 140.0,
    "dodge_enable": True,
    "dodge_margin_m": 0.8,
    "dodge_horizon_s": 0.9,
    "dodge_step_s": 0.04,
    "dodge_cands": 16,
    "dodge_w_nav": 0.35,
    "dodge_latency_s": 0.0,
    "laser_line_margin_m": 1.0,
}


def knobs(overrides=None):
    k = dict(DEFAULT_KNOBS)
    if overrides:
        k.update(overrides)
    return k


# ---------------------------------------------------------------- basic geometry
def wrap_pi(a):
    return (a + PI) % (2 * PI) - PI


def dir_yp(yaw, pitch):
    c = math.cos(pitch)
    return (c * math.cos(yaw), c * math.sin(yaw), math.sin(pitch))


def yp_of(d):
    return (math.atan2(d[1], d[0]), math.atan2(d[2], math.hypot(d[0], d[1])))


def unit3(v):
    n = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]) or 1.0
    return (v[0] / n, v[1] / n, v[2] / n)


def dist3(a, b):
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2)


def clamp(x, lo, hi):
    return lo if x < lo else hi if x > hi else x


def size_scale(cubes, cfg=CFG):
    return 1.0 + cfg["size_per_cube"] * cubes


# ---------------------------------------------------------------- torso slew
def slew_aim(aim, cmd, dt, turn_rate, pitch_rate, pmin, pmax):
    """Actual torso aim after dt seconds when commanding cmd. Per-axis rate limit (verified for yaw on the
    recorded stream: max step is exactly turn_rate*0.1 per decision; pitch per-axis is an assumption)."""
    step = turn_rate * dt
    yaw = aim[0] + clamp(wrap_pi(cmd[0] - aim[0]), -step, step)
    pstep = pitch_rate * dt
    pit = aim[1] + clamp(clamp(cmd[1], pmin, pmax) - aim[1], -pstep, pstep)
    return (wrap_pi(yaw), pit)


def slew_time(aim, cmd, turn_rate, pitch_rate):
    return max(abs(wrap_pi(cmd[0] - aim[0])) / turn_rate, abs(cmd[1] - aim[1]) / pitch_rate)


# ---------------------------------------------------------------- probability helpers
def p_within(mu, sigma, r):
    """P(|N(mu, sigma)| < r)."""
    if sigma < 1e-9:
        return 1.0 if abs(mu) < r else 0.0
    s = sigma * math.sqrt(2.0)
    return 0.5 * (math.erf((r - mu) / s) + math.erf((r + mu) / s))


def man_sigma(h, k):
    """Interpolated RMS perpendicular error of linear lead at horizon h seconds."""
    tab = k["man_sigma_table"]
    s = tab[-1][1]
    if h <= tab[0][0]:
        s = tab[0][1]
    else:
        for (h0, s0), (h1, s1) in zip(tab, tab[1:]):
            if h <= h1:
                s = s0 + (s1 - s0) * (h - h0) / (h1 - h0)
                break
    if h > tab[-1][0]:                      # beyond the table: keep the last slope
        (h0, s0), (h1, s1) = tab[-2], tab[-1]
        s = s1 + (s1 - s0) * (h - h1) / (h1 - h0)
    return s * k["man_sigma_scale"]


# ---------------------------------------------------------------- target prediction
def predict_pos(tgt, h, k):
    """Predicted FEET position of target h seconds from the observation."""
    p, v = tgt["pos"], tgt["vel"]
    if k["lead_order"] == 0 or h <= 0:
        return (p[0], p[1], p[2])
    x, y, z = p[0] + v[0] * h, p[1] + v[1] * h, p[2] + v[2] * h
    a = tgt.get("acc")
    if k["lead_order"] >= 2 and a:
        g, tau = k["accel_gain"], k["accel_tau_s"]
        t1 = min(h, tau)
        x += g * (0.5 * a[0] * t1 * t1 + a[0] * t1 * (h - t1))
        y += g * (0.5 * a[1] * t1 * t1 + a[1] * t1 * (h - t1))
    return (x, y, z)


def target_dims(tgt, cfg=CFG):
    s = size_scale(tgt.get("cubes", 0), cfg)
    return cfg["mech"]["radius"] * s, cfg["mech"]["height"] * s


# ---------------------------------------------------------------- gun
def fire_ticks(cooldown, dt):
    """Which tick of the 2-tick action a ready gun fires on: 1, 2, or None (not ready within this action)."""
    if cooldown <= dt + 1e-9:
        return 1
    if cooldown <= 2 * dt + 1e-9:
        return 2
    return None


def solve_gun(me, tgt, k, cfg=CFG, cooldown=0.0):
    """Intercept solution for a constant-speed straight bullet.
    me: pos(feet), vel, aim, radius, muzzle_h, turn_rate, pitch_rate.  tgt: pos(feet), vel, [acc], cubes.
    Returns dict(cmd=(yaw,pitch), T, tf, dist, point, t_fire, ticks)."""
    g = cfg["gun"]
    dt = k["dt"]
    ticks = fire_ticks(cooldown, dt)
    t_fire = k["fire_delay_s"] + ((ticks or 2) - 1) * dt
    tr, th = target_dims(tgt, cfg)
    off = me["radius"] + 0.5
    mx = me["pos"][0] + me["vel"][0] * t_fire
    my = me["pos"][1] + me["vel"][1] * t_fire
    mz = me["pos"][2] + me["muzzle_h"]
    p0 = predict_pos(tgt, 0.0, k)
    d = unit3((p0[0] - mx, p0[1] - my, p0[2] + 0.5 * th - mz))
    T = t_fire
    c = (p0[0], p0[1], p0[2] + 0.5 * th)
    dist = 0.0
    for _ in range(3):                      # shot origin depends on aim direction
        o = (mx + off * d[0], my + off * d[1], mz + off * d[2])
        T = t_fire + dist3(c, o) / g["speed"]
        for _ in range(5):                  # contraction factor ~ v_target / bullet_speed <= 0.08
            pp = predict_pos(tgt, T, k)
            c = (pp[0], pp[1], pp[2] + 0.5 * th)
            dist = dist3(c, o)
            T = t_fire + dist / g["speed"]
        d = unit3((c[0] - o[0], c[1] - o[1], c[2] - o[2]))
    yaw, pit = yp_of(d)
    pit = clamp(pit, cfg["mech"]["min_pitch"], cfg["mech"]["max_pitch"])
    return dict(cmd=(yaw, pit), T=T, tf=T - t_fire, dist=dist, point=c, t_fire=t_fire, ticks=ticks, origin=o)


def gun_hit_prob(sol, me, tgt, k, cfg=CFG, aim_cmd=None):
    """Probability the bullet fired on this action passes inside the target cylinder.
    aim_cmd: the aim actually commanded this decision (defaults to the ideal gun aim; differs when the laser owns the torso)."""
    g = cfg["gun"]
    aim_f = slew_aim(me["aim"], aim_cmd if aim_cmd is not None else sol["cmd"], sol["t_fire"], me["turn_rate"], me["pitch_rate"],
                     cfg["mech"]["min_pitch"], cfg["mech"]["max_pitch"])
    dist = sol["dist"]
    mu_h = wrap_pi(aim_f[0] - sol["cmd"][0]) * math.cos(sol["cmd"][1]) * dist
    mu_v = (aim_f[1] - sol["cmd"][1]) * dist
    sig_s = dist * math.tan(math.radians(g["spread_deg"]))
    sig_m = man_sigma(sol["T"], k)
    tr, th = target_dims(tgt, cfg)
    rb = cfg["projectile"]["gun_radius"]
    ph = p_within(mu_h, math.hypot(sig_s, sig_m), tr + rb)
    pv = p_within(mu_v, math.hypot(sig_s, 0.3 * sig_m), 0.5 * th + rb)
    return ph * pv


def gun_decision(me, tgt, gun_state, k, cfg=CFG, engage=True, los_clear=True, aim_cmd=None):
    """-> dict(aim, fire, p_hit, sol). gun_state: ammo, cooldown, reload."""
    sol = solve_gun(me, tgt, k, cfg, gun_state["cooldown"])
    p = gun_hit_prob(sol, me, tgt, k, cfg, aim_cmd)
    ok = (engage and los_clear and gun_state["ammo"] > 0 and gun_state["reload"] <= 0 and sol["ticks"] is not None
          and sol["dist"] <= min(cfg["gun"]["range"], k["gun_max_range_m"]) and p >= k["gun_p_min"])
    return dict(aim=sol["cmd"], fire=ok, p_hit=p, sol=sol)


# ---------------------------------------------------------------- mortar
def ballistic(d, h, v, g, arc="low"):
    """Pitch and flight time to cover horizontal distance d and height change h at launch speed v."""
    if d < 1e-6:
        return None
    disc = v ** 4 - g * (g * d * d + 2 * h * v * v)
    if disc < 0:
        return None
    s = math.sqrt(disc)
    t = (v * v - s) / (g * d) if arc == "low" else (v * v + s) / (g * d)
    th = math.atan(t)
    return th, d / (v * math.cos(th))


def solve_mortar(me, tgt, k, cfg=CFG, arc=None, cooldown=0.0):
    m = cfg["mortar"]
    v, grav = m["speed"], m["gravity"]
    arc = arc or k["mortar_arc"]
    t_fire = k["fire_delay_s"]
    tr, th_t = target_dims(tgt, cfg)
    tube_z = me["pos"][2] + me["height"] + 0.5
    tx = me["pos"][0] + me["vel"][0] * t_fire
    ty = me["pos"][1] + me["vel"][1] * t_fire
    off = me["radius"] + 0.5
    pitch, Tf = 0.2, 1.0
    c = predict_pos(tgt, t_fire + Tf, k)
    for _ in range(10):
        c = predict_pos(tgt, t_fire + Tf, k)
        cx, cy, cz = c[0], c[1], c[2] + 0.5 * th_t
        yaw = math.atan2(cy - ty, cx - tx)
        ox = tx + off * math.cos(pitch) * math.cos(yaw)
        oy = ty + off * math.cos(pitch) * math.sin(yaw)
        oz = tube_z + off * math.sin(pitch)
        d = math.hypot(cx - ox, cy - oy)
        sol = ballistic(d, cz - oz, v, grav, arc)
        if sol is None:
            return None
        pitch, Tf = sol
    lo, hi = cfg["mech"]["min_pitch"], cfg["mech"]["max_pitch"]
    if not (lo <= pitch <= hi) or Tf > m["ttl"]:
        return None
    return dict(cmd=(yaw, pitch), tf=Tf, T=t_fire + Tf, dist=d, point=(cx, cy, cz), origin=(ox, oy, oz),
                t_fire=t_fire, arc=arc)


def mortar_damage_at(miss, k, cfg=CFG, tgt_r=2.5):
    """Damage to a target whose axis is `miss` metres (horizontal) from the blast point."""
    m = cfg["mortar"]
    mm = max(0.0, miss - k["mortar_splash_surface"])
    splash = m["splash"] * (1 - (1 - m["splash_edge"]) * mm / m["splash_radius"]) if mm <= m["splash_radius"] else 0.0
    direct = m["damage"] if miss <= tgt_r + k["mortar_direct_extra_m"] else 0.0
    return direct + splash


def expected_mortar_damage(err_samples, k, cfg=CFG, tgt_r=2.5):
    """Mean damage over empirical horizontal error magnitudes (metres) of the aim point vs the target."""
    if not err_samples:
        return 0.0
    return sum(mortar_damage_at(e, k, cfg, tgt_r) for e in err_samples) / len(err_samples)


def expected_mortar_damage_table(T, k):
    """Runtime estimate of damage per shell at flight time T against a MANEUVERING target (linear-lead aim point).
    Table = empirical E[dmg] from the recorded house-bot track (lead_eval.py); one enemy, n~100-160 per point."""
    tab = k["mortar_edmg_table"]
    if T <= tab[0][0]:
        return tab[0][1]
    for (t0, e0), (t1, e1) in zip(tab, tab[1:]):
        if T <= t1:
            return e0 + (e1 - e0) * (T - t0) / (t1 - t0)
    return tab[-1][1]


def shell_pos(origin, cmd, t, cfg=CFG):
    m = cfg["mortar"]
    d = dir_yp(*cmd)
    return (origin[0] + m["speed"] * d[0] * t, origin[1] + m["speed"] * d[1] * t,
            origin[2] + m["speed"] * d[2] * t - 0.5 * m["gravity"] * t * t)


# ---------------------------------------------------------------- laser
def laser_damage(charge, cfg=CFG):
    l = cfg["laser"]
    return l["damage"] * (l["min_frac"] + (1 - l["min_frac"]) * min(1.0, charge / l["charge"]))


def laser_decision(me, tgt, charge, k, cfg=CFG, engage=True, los_clear=True):
    """Hold-to-charge, release when aligned. Hitscan: no flight lead, only decision latency + slew."""
    l = cfg["laser"]
    t_rel = k["laser_release_delay_s"]
    tr, th = target_dims(tgt, cfg)
    pp = predict_pos(tgt, t_rel, k)
    c = (pp[0], pp[1], pp[2] + 0.5 * th)
    mz = me["pos"][2] + me["muzzle_h"]
    o = (me["pos"][0] + me["vel"][0] * t_rel, me["pos"][1] + me["vel"][1] * t_rel, mz)
    d = unit3((c[0] - o[0], c[1] - o[1], c[2] - o[2]))
    cmd = yp_of(d)
    dist = dist3(c, o)
    aim_f = slew_aim(me["aim"], cmd, t_rel, me["turn_rate"], me["pitch_rate"],
                     cfg["mech"]["min_pitch"], cfg["mech"]["max_pitch"])
    mu_h = wrap_pi(aim_f[0] - cmd[0]) * math.cos(cmd[1]) * dist
    mu_v = (aim_f[1] - cmd[1]) * dist
    sig = man_sigma(t_rel, k)
    p = p_within(mu_h, sig, tr) * p_within(mu_v, 0.3 * sig, 0.5 * th)
    full = charge >= l["charge"] - 1e-9
    ready_to_release = charge >= l["min_charge"] and p >= k["laser_release_p"] and (full or not k["laser_hold_full"])
    return dict(aim=cmd, hold=engage and los_clear and not ready_to_release, release=engage and ready_to_release,
                p_hit=p, dmg=laser_damage(charge, cfg), dist=dist)


def beam_line_offset(me_pos, me_cubes, enemy, cfg=CFG):
    """Perpendicular distance from my centre of mass to the enemy's aim ray, and distance along it."""
    yaw, pit = enemy["aim"]
    d = dir_yp(yaw, pit)
    mu = (enemy["pos"][0], enemy["pos"][1], enemy["pos"][2] + cfg["mech"]["muzzle_height"])
    my_h = cfg["mech"]["height"] * size_scale(me_cubes, cfg)
    r = (me_pos[0] - mu[0], me_pos[1] - mu[1], me_pos[2] + 0.5 * my_h - mu[2])
    along = r[0] * d[0] + r[1] * d[1] + r[2] * d[2]
    perp = math.sqrt(max(0.0, r[0] ** 2 + r[1] ** 2 + r[2] ** 2 - along * along))
    return perp, along


def laser_line_on_me(me_pos, me_cubes, enemy, k, cfg=CFG):
    perp, along = beam_line_offset(me_pos, me_cubes, enemy, cfg)
    rr = cfg["mech"]["radius"] * size_scale(me_cubes, cfg)
    return enemy.get("charging", False) and along > 0 and perp <= rr + k["laser_line_margin_m"]


# ---------------------------------------------------------------- lightning
def lightning_target(me_pos, aim_yaw, entities, cfg_l=None, los=None, cone_half_deg=30.0, rng_m=45.0):
    """Entity the arc would hit: nearest (3-D) within range and within cone_half_deg of aim YAW, with line of sight.
    entities: dicts with pos and kind in {mech, npc, crate}. cone_deg=30 may mean +-30 or +-15; aim within +-12 is safe either way."""
    best = None
    for e in entities:
        d = dist3(me_pos, e["pos"])
        if d > rng_m:
            continue
        bearing = math.atan2(e["pos"][1] - me_pos[1], e["pos"][0] - me_pos[0])
        if abs(wrap_pi(bearing - aim_yaw)) > math.radians(cone_half_deg):
            continue
        if los is not None and not los(me_pos, e["pos"]):
            continue
        if best is None or d < best[0]:
            best = (d, e)
    return best[1] if best else None


# ---------------------------------------------------------------- combat movement
def my_traj(p0, v0, u_vel, A, t):
    """Horizontal position after t s moving at accel-limited A toward commanded velocity u_vel."""
    dvx, dvy = u_vel[0] - v0[0], u_vel[1] - v0[1]
    dn = math.hypot(dvx, dvy)
    if dn < 1e-9:
        return (p0[0] + v0[0] * t, p0[1] + v0[1] * t)
    tc = dn / A
    ex, ey = dvx / dn, dvy / dn
    if t <= tc:
        s = 0.5 * A * t * t
        return (p0[0] + v0[0] * t + ex * s, p0[1] + v0[1] * t + ey * s)
    s = 0.5 * A * tc * tc
    return (p0[0] + v0[0] * tc + ex * s + u_vel[0] * (t - tc), p0[1] + v0[1] * tc + ey * s + u_vel[1] * (t - tc))


def bullet_pen(cand_vel, me, bullets, k, cfg=CFG):
    """Sum over visible enemy bullets of a smooth hit penalty in [0,1]^2 for one candidate velocity."""
    A = cfg["mech"]["ground_accel"]
    rr = me["radius"] + cfg["projectile"]["gun_radius"]
    H = me["height"]
    zf = me["pos"][2]
    pen = 0.0
    dts = k["dodge_step_s"]
    n = int(k["dodge_horizon_s"] / dts)
    # my positions at the grid times (my own motion is smooth, so linear between 0.04 s samples is exact enough)
    mine = [my_traj(me["pos"], me["vel"], cand_vel, A, max(0.0, i * dts - k["dodge_latency_s"])) for i in range(n + 1)]
    for b in bullets:
        bx, by, bz0 = b["pos"]
        vx, vy, vz = b["vel"]
        dmin = 1e9
        for i in range(n):
            t0 = i * dts
            # bullets move ~10 m per sample, so take the exact closest approach of the straight segment pair
            r0x, r0y = bx + vx * t0 - mine[i][0], by + vy * t0 - mine[i][1]
            r1x, r1y = bx + vx * (t0 + dts) - mine[i + 1][0], by + vy * (t0 + dts) - mine[i + 1][1]
            ex, ey = r1x - r0x, r1y - r0y
            ee = ex * ex + ey * ey
            s = 0.0 if ee < 1e-12 else clamp(-(r0x * ex + r0y * ey) / ee, 0.0, 1.0)
            bz = bz0 + vz * (t0 + s * dts)
            if bz < zf - 0.3 or bz > zf + H + 0.3:
                continue
            d = math.hypot(r0x + s * ex, r0y + s * ey)
            if d < dmin:
                dmin = d
        lim = rr + k["dodge_margin_m"]
        if dmin < lim:
            pen += ((lim - dmin) / lim) ** 2
    return pen


def choose_move(me, bullets, desired_dir, speed, k, cfg=CFG, blocked=None):
    """Pick the commanded velocity that minimises predicted bullet hits, tie-broken toward desired_dir.
    desired_dir: unit (x,y) or None.  blocked(dir_xy) -> bool is an optional NAV hook (wall within a few metres).
    Returns (velocity (vx,vy), cost)."""
    cands = []
    n = k["dodge_cands"]
    for i in range(n):
        a = 2 * PI * i / n
        cands.append((math.cos(a) * speed, math.sin(a) * speed))
    cands.append((0.0, 0.0))
    if desired_dir:
        cands.append((desired_dir[0] * speed, desired_dir[1] * speed))
    best = None
    for c in cands:
        if blocked and (c[0] or c[1]) and blocked((c[0] / speed, c[1] / speed)):
            continue
        pen = bullet_pen(c, me, bullets, k, cfg) if (k["dodge_enable"] and bullets) else 0.0
        nav = 0.0
        if desired_dir:
            nav = k["dodge_w_nav"] * (1 - (c[0] * desired_dir[0] + c[1] * desired_dir[1]) / speed)
        cost = pen + nav
        if best is None or cost < best[1]:
            best = (c, cost)
    return best if best else ((0.0, 0.0), 0.0)


class Strafer:
    """Perpendicular strafing with random hold times and forced reversals (H-MOV).
    Holds are integer numbers of decisions so reversals land on decision boundaries."""

    def __init__(self, seed, k):
        self.rng = random.Random(seed)
        self.k = k
        self.sign = 1 if self.rng.random() < 0.5 else -1
        self.left = self.rng.randint(k["hold_min_dec"], k["hold_max_dec"])

    def step(self, los_unit_xy, rng_m, blocked=None):
        """los_unit_xy: unit vector from me toward the primary target. Returns unit move direction."""
        k = self.k
        self.left -= 1
        if self.left <= 0:
            if self.rng.random() < k["flip_prob"]:
                self.sign = -self.sign
            self.left = self.rng.randint(k["hold_min_dec"], k["hold_max_dec"])
        tx, ty = -los_unit_xy[1] * self.sign, los_unit_xy[0] * self.sign
        radial = 0.0
        if rng_m < k["range_lo_m"]:
            radial = -0.5
        elif rng_m > k["range_hi_m"]:
            radial = 0.5
        dx, dy = tx + radial * los_unit_xy[0], ty + radial * los_unit_xy[1]
        n = math.hypot(dx, dy) or 1.0
        d = (dx / n, dy / n)
        if blocked and blocked(d):           # wall ahead: flip early instead of grinding into it
            self.sign = -self.sign
            tx, ty = -los_unit_xy[1] * self.sign, los_unit_xy[0] * self.sign
            n = math.hypot(tx, ty) or 1.0
            d = (tx / n, ty / n)
        return d
