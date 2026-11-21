"""H-PER: perception and world model for mechfight/1 (stdlib only, ~5-10 ms per tick).

What it keeps
  * identified tracks (one per enemy id ever seen): exact state while visible, a particle cloud while hidden
  * one "unseen" intensity cloud (PHD style): the expected positions of enemies never seen yet,
    total mass = alive - 1 - identified tracks
  * projectile tracks -> incoming-hit predictions, mortar impact points, back-traced shooter fixes
  * laser telegraph lines, lightning reach, a threat grid, and hot spots (clusters of unseen mass)

What it fuses (each source is a knob toggle so every claim can be ablated)
  sounds    bearing (sigma 7 deg * hearing) + sharp near/mid/far bins + sound kind     [use_sound]
  events    damaged.by + bearing (gun/laser/lightning), hit.target along our aim        [use_events]
  beams     laser/lightning path[0] is the shooter's muzzle: a direct position fix       [use_beams]
  shots     bullet back-ray, mortar ballistic launch-point solve                         [use_proj]
  negative  hidden mass inside our current line-of-sight volume is penalised             [use_carve]
  zone      hidden mass outside the zone is pulled in                                    [zone_pull_mps]

Usage:
    per = Perception(hello, map_dir="/arena")          # in __init__, inside the 20 s ready window
    w = per.update(obs)                                # every decision; returns the World snapshot
"""
import bisect
import json
import math
import os
import random
import sys
import time
from collections import deque

from geom import Geom

TWO_PI = 2 * math.pi
PI = math.pi

DEFAULTS = {
    "enabled": True,
    "time_budget_ms": 8.0,       # self-imposed share of the 50 ms decision (merge contract: <10 ms worst case)
    # --- hidden motion model
    "n_hidden": 32,              # particles per identified hidden track
    "n_cloud": 480,              # particles in the unseen cloud
    "walk_sigma": 3.5,           # m/s, stationary per-axis speed spread of a hidden enemy
    "vel_tau_s": 2.5,            # velocity memory: last seen velocity decays to the spread with this time constant
    "hunt_auto": True,           # learn mean closing speed of visible enemies and drift hidden mass toward us
    "hunt_rate": 0.2,           # integral gain of the drift learner (per re-acquisition)
    "hunt_max_mps": 6.0,
    "hunt_leak_s": 45.0,         # learned drift decays toward 0 unless re-confirmed
    "hunt_fixed_mps": 0.0,       # used when hunt_auto is false
    "resample_ess": 0.5,
    "resample_jitter_m": 2.0,
    "zone_pull_mps": 8.0,        # hidden mass outside the zone drifts toward the center
    "zone_slack_m": 15.0,
    # --- sound fusion
    "use_sound": True,
    "bearing_sigma_scale": 1.0,  # multiplies the 7 deg noise (also scaled by self.stats.hearing)
    "bearing_floor_deg": 2.0,
    "bin_slack_m": 6.0,          # soft edge on the near/mid/far thresholds
    "sound_floor": 0.02,         # outlier floor inside each sound likelihood
    "sound_bg": 0.05,            # prior weight of "source not in my model"
    "max_sounds_per_tick": 8,
    "compat_missing_weapon": 0.15,
    # --- events / beams / projectiles
    "use_events": True,
    "use_beams": True,
    "use_proj": True,
    "event_sigma_deg": 2.0,
    "hit_sigma_deg": 3.0,
    "proj_sigma_m": 4.0,
    "mortar_sigma_m": 5.0,
    "proj_max_per_tick": 6,
    # --- negative information
    "use_carve": False,          # H-PER-3 not supported in harness (neutral); enable only after a leaderboard A/B
    "carve_pen": 0.15,           # weight multiplier for hidden mass inside our current view
    "carve_margin_m": 6.0,
    "carve_grace_s": 0.7,        # do not carve a track that just left view
    "los_rays": 96,
    "los_step_m": 4.0,
    "trees_occlude": True,
    # --- unseen cloud
    "use_cloud": True,
    "promote_sigma_m": 15.0,     # how local the removal of one unit of cloud mass is when an id is first seen
    "hot_cell_m": 30.0,
    "hot_min_mass": 0.35,
    "hot_max": 6,
    # --- outputs
    "dodge_horizon_s": 0.8,
    "tg_cell_m": 20.0,
    "unknown_threat": 0.8,
}

SPECIALS = ("mortar", "laser", "lightning")
HEARD_TO_KIND = {"laser": "laser", "laser_charge": "laser", "lightning": "lightning", "mortar": "mortar"}

MECH_SOUNDS = {"gun": "gun", "mortar": "mortar", "laser": "laser", "laser_charge": "laser",
               "lightning": "lightning", "step": None, "boost": None, "jet": None, "reload": "gun"}
SOUND_PRIORITY = {"laser": 0, "laser_charge": 0, "mortar": 1, "lightning": 1, "reload": 2, "boost": 2, "jet": 2,
                  "step": 3, "gun": 4}


def load_params(path=None, overrides=None):
    p = dict(DEFAULTS)
    if path and os.path.exists(path):
        with open(path) as f:
            p.update(json.load(f).get("per", {}))
    if overrides:
        p.update(overrides)
    return p


def wrap(a):
    return (a + PI) % TWO_PI - PI


def _bin_edges(dist, kind, cfg):
    snd = cfg["sound"]
    rng = snd["range"].get(kind, 300.0)
    if dist == "near":
        return 0.0, min(snd["near"], rng)
    if dist == "mid":
        return snd["near"], min(snd["mid"], max(rng, snd["near"] + 1))
    return snd["mid"], max(rng, snd["mid"] + 1)


class Track:
    __slots__ = ("id", "pos", "vel", "aim", "hp", "max_hp", "cubes", "weapons", "charging", "vis", "t_seen",
                 "t_lost", "first_t", "px", "py", "vx", "vy", "w", "heard", "last_pos", "ever_vis")

    def __init__(self, tid, t):
        self.id = tid
        self.pos = [0.0, 0.0, 0.0]
        self.vel = [0.0, 0.0, 0.0]
        self.aim = [0.0, 0.0]
        self.hp = None
        self.max_hp = 1400.0
        self.cubes = 0
        self.weapons = {"gun"}
        self.charging = False
        self.vis = False
        self.t_seen = t
        self.t_lost = None
        self.first_t = t
        self.px = self.py = self.vx = self.vy = self.w = None
        self.heard = {}
        self.last_pos = None
        self.ever_vis = False


class Cloud:
    """Intensity of enemies never seen: particles whose weights sum to `mass` (expected count)."""
    __slots__ = ("px", "py", "vx", "vy", "w", "mass")

    def __init__(self):
        self.px, self.py, self.vx, self.vy, self.w = [], [], [], [], []
        self.mass = 0.0


class Contact:
    """What consumers read. `src` is seen | recent | sound | unseen."""
    __slots__ = ("id", "pos", "vel", "sigma", "age", "conf", "hp", "max_hp", "cubes", "weapons", "charging",
                 "aim", "vis", "src", "threat", "heard", "mass")

    def __repr__(self):
        return "Contact(id=%s %s %.0f,%.0f sig=%.0f age=%.1f)" % (self.id, self.src, self.pos[0], self.pos[1],
                                                                   self.sigma, self.age)


class Incoming:
    __slots__ = ("id", "kind", "t_hit", "miss", "hit_pos", "dodge", "shooter", "radius", "pos", "vel", "hit")


class World:
    """Per-tick snapshot. Plain attributes, no behaviour beyond a few queries."""

    def __init__(self):
        self.t = 0.0
        self.tick = 0
        self.me = None
        self.contacts = []         # identified enemies (visible and hidden) + unseen hot spots
        self.hot = []              # hot spots only
        self.incoming = []         # bullets/shells predicted to reach us, soonest first
        self.laser_lines = []      # charging enemy lasers: dicts with id, perp, dodge, along
        self.lightning_risk = []   # enemies with lightning inside reach
        self.npcs = {}
        self.n_unseen = 0.0
        self._per = None

    def visible(self):
        return [c for c in self.contacts if c.src == "seen"]

    def nearest(self, k=3):
        me = self.me["pos"]
        cs = [c for c in self.contacts if c.src != "unseen"]
        cs.sort(key=lambda c: (c.pos[0] - me[0]) ** 2 + (c.pos[1] - me[1]) ** 2)
        return cs[:k]

    def threat_grid(self):
        return self._per.threat_grid()

    def threat_at(self, x, y, radius=40.0):
        return self._per.mass_near(x, y, radius)


class Perception:
    def __init__(self, hello, map_dir=None, params=None, geom=None):
        self.cfg = hello["config"]
        self.P = params if params is not None else dict(DEFAULTS)
        self.slot = hello.get("slot", 0)
        self.rng = random.Random(hello.get("seed", 1))
        t0 = time.perf_counter()
        if geom is not None:
            self.geom = geom
        else:
            md = map_dir or hello.get("map", {}).get("dir", "/arena")
            self.geom = Geom(md)
        self.build_ms = (time.perf_counter() - t0) * 1000
        self.tracks = {}                    # id -> Track
        self.cloud = Cloud()
        self.cloud_init = False
        self.npcs = {}
        self.seen_proj = set()
        self.recent_sounds = deque(maxlen=48)
        self.death_sounds = deque(maxlen=8)
        self.hist = deque(maxlen=40)        # (t, x, y, aim_yaw)
        self.prev_obs_t = None
        self.prev_aim = None
        self.prev_alive = None
        self.world = World()
        self.world._per = self
        self.scale = 1.0
        self.hunt = 0.0
        self.hunt_n = 0
        self.times = deque(maxlen=400)
        self.stats = {"n": 0, "reacq": [], "first_seen": [], "remembered_listed": 0, "listed": 0, "over_budget": 0}
        self._tg = None
        self._tg_tick = -1
        self._horizon = None
        w = self.cfg["weapons"]
        self.dps = {"gun": w["gun"]["damage"] / w["gun"]["cooldown"],
                    "mortar": (w["mortar"]["damage"] + w["mortar"]["splash"] * 0.5) / w["mortar"]["cooldown"],
                    "laser": w["laser"]["damage"] / (w["laser"]["charge"] + w["laser"]["cooldown"]),
                    "lightning": w["lightning"]["damage"] / w["lightning"]["cooldown"]}
        self.wrange = {"gun": w["gun"]["range"], "laser": w["laser"]["range"], "lightning": w["lightning"]["range"],
                       "mortar": 235.0}

    # =========================================================================================
    # public
    # =========================================================================================
    def update(self, obs):
        t_start = time.perf_counter()
        P = self.P
        self.me = me = obs["self"]
        t = obs["t"]
        dt = 0.1 if self.prev_obs_t is None else max(0.0, min(1.0, t - self.prev_obs_t))
        self.t = t
        self.dt = dt
        self.obs = obs
        ex, ey = me["pos"][0], me["pos"][1]
        self.hist.append((t, ex, ey, me["aim"][0]))
        self.hearing = me.get("stats", {}).get("hearing", 1.0)
        budget = P["time_budget_ms"] * self.scale
        deadline = t_start + P["time_budget_ms"] / 1000.0
        if P["hunt_auto"] and self.hunt > 0:
            self.hunt *= math.exp(-dt / P["hunt_leak_s"])
        if not P["enabled"]:
            self._passthrough(obs)
            self.prev_obs_t = t
            return self.world

        if not self.cloud_init:
            self._init_cloud(obs)
        self._ingest_visible(obs)
        self._predict(dt)
        t_after_pred = time.perf_counter()

        sounds = self._pick_sounds(obs.get("sounds", []))
        events = obs.get("events", [])
        beams = obs.get("beams", [])
        if P["use_beams"]:
            for b in beams:
                self._on_beam(b)
        if P["use_events"]:
            for e in events:
                self._on_event(e)
        if P["use_proj"]:
            self._on_projectiles(obs.get("projectiles", []), deadline)
        if P["use_sound"]:
            for s in sounds:
                if time.perf_counter() > deadline:
                    break
                self._on_sound(s)
        self._death_accounting(obs, events)
        if P["use_carve"] and time.perf_counter() < deadline - 0.002:
            self._carve(obs)
        self._maybe_resample()
        self._build_outputs(obs)
        self.prev_obs_t = t
        self.prev_aim = list(me["aim"])
        self.prev_alive = obs.get("alive")
        # timing control: AIMD on particle budget
        ms = (time.perf_counter() - t_start) * 1000
        self.times.append(ms)
        self.stats["n"] += 1
        if ms > P["time_budget_ms"]:
            self.stats["over_budget"] += 1
            self.scale = max(0.25, self.scale * 0.7)
        elif ms < 0.6 * P["time_budget_ms"]:
            self.scale = min(1.0, self.scale + 0.05)
        return self.world

    def telemetry_line(self):
        ts = sorted(self.times) or [0.0]
        s = self.stats
        re = s["reacq"]
        med = sorted(r[1] for r in re)[len(re) // 2] if re else -1
        return ("per t=%.0f n=%d ms p50=%.1f p99=%.1f max=%.1f scale=%.2f over=%d reacq=%d med_err=%.0f "
                "firstseen=%d unseen_mass=%.1f listed_remembered=%d/%d" % (
                    self.t, s["n"], ts[len(ts) // 2], ts[int(len(ts) * 0.99) - 1 if len(ts) > 1 else 0], ts[-1],
                    self.scale, s["over_budget"], len(re), med, len(s["first_seen"]), self.cloud.mass,
                    s["remembered_listed"], s["listed"]))

    # =========================================================================================
    # ingest
    # =========================================================================================
    def _passthrough(self, obs):
        w = self.world
        w.t, w.tick, w.me = obs["t"], obs["tick"], obs["self"]
        w.contacts = []
        for m in obs.get("mechs", []):
            if m["kind"] != "mech":
                continue
            c = Contact()
            c.id, c.pos, c.vel, c.sigma, c.age, c.conf = m["id"], m["pos"], m["vel"], 0.0, 0.0, 1.0
            c.hp, c.max_hp, c.cubes = m.get("hp"), m.get("max_hp"), m.get("cubes", 0)
            c.weapons, c.charging, c.aim, c.vis, c.src = set(m.get("weapons", [])), m.get("charging", False), m["aim"], True, "seen"
            c.threat, c.heard, c.mass = 1.0, {}, 1.0
            w.contacts.append(c)

    def _vision_params(self):
        v = self.cfg["vision"]
        st = self.me.get("stats", {})
        return (v["range"] + st.get("vision_bonus", 0.0), v["near_range"] + st.get("near_range_bonus", 0.0),
                math.radians(v["fov_deg"]))

    def _init_cloud(self, obs):
        P = self.P
        c = self.cloud
        zc = self.cfg["zone"]["start_center"]
        zr = self.cfg["zone"]["start_radius"] * self.cfg["match"].get("spawn_zone_fraction", 0.8)
        sep = self.cfg["match"].get("spawn_min_separation", 130.0)
        me = obs["self"]["pos"]
        g = self.geom
        n = P["n_cloud"]
        tries = 0
        while len(c.px) < n and tries < n * 40:
            tries += 1
            r = zr * math.sqrt(self.rng.random())
            a = self.rng.random() * TWO_PI
            x, y = zc[0] + r * math.cos(a), zc[1] + r * math.sin(a)
            if g.gblocked(x, y):
                continue
            if (x - me[0]) ** 2 + (y - me[1]) ** 2 < sep * sep:
                continue
            c.px.append(x)
            c.py.append(y)
            c.vx.append(self.rng.gauss(0, P["walk_sigma"]))
            c.vy.append(self.rng.gauss(0, P["walk_sigma"]))
            c.w.append(1.0)
        alive = obs.get("alive", 16)
        c.mass = float(max(0, alive - 1))
        self._renorm(c, c.mass)
        self.cloud_init = True

    @staticmethod
    def _renorm(c, mass):
        s = sum(c.w)
        if s <= 1e-12:
            n = len(c.w)
            if n:
                c.w = [mass / n] * n
            c.mass = mass
            return
        k = mass / s
        c.w = [x * k for x in c.w]
        c.mass = mass

    def _ingest_visible(self, obs):
        P = self.P
        t = self.t
        seen_ids = set()
        vis_r, near_r, fov = self._vision_params()
        ex, ey, yaw = self.me["pos"][0], self.me["pos"][1], self.me["aim"][0]
        for m in obs.get("mechs", []):
            if m["kind"] == "npc":
                self.npcs[m["id"]] = {"pos": m["pos"], "vel": m["vel"], "hp": m.get("hp"), "t": t}
                continue
            tid = m["id"]
            seen_ids.add(tid)
            # detector: a listed mech outside our sensing envelope would be a server memory entry
            dx, dy = m["pos"][0] - ex, m["pos"][1] - ey
            d = math.hypot(dx, dy)
            self.stats["listed"] += 1
            if d > near_r + 1 and abs(wrap(math.atan2(dy, dx) - yaw)) > fov / 2 + 0.05:
                self.stats["remembered_listed"] += 1
            tr = self.tracks.get(tid)
            if tr is None:
                tr = Track(tid, t)
                self._take_from_cloud(m["pos"][0], m["pos"][1], P["promote_sigma_m"])
                self.tracks[tid] = tr
                self.stats["first_seen"].append((t, tid))
            elif not tr.vis and tr.px is not None:
                self._log_reacq(tr, m["pos"])
            tr.pos = list(m["pos"])
            tr.vel = list(m["vel"])
            tr.aim = list(m["aim"])
            tr.hp = m.get("hp", tr.hp)
            tr.max_hp = m.get("max_hp", tr.max_hp)
            tr.cubes = m.get("cubes", tr.cubes)
            ws = m.get("weapons")
            if ws:
                tr.weapons = set(ws)
            tr.charging = bool(m.get("charging"))
            tr.vis = True
            tr.ever_vis = True
            tr.t_seen = t
            tr.t_lost = None
            tr.px = tr.py = tr.vx = tr.vy = tr.w = None
        for tid, tr in self.tracks.items():
            if tr.vis and tid not in seen_ids:
                tr.vis = False
                tr.t_lost = t
                tr.last_pos = list(tr.pos)
                self._seed_particles(tr, tr.pos[0], tr.pos[1], tr.vel[0], tr.vel[1], 2.0)
        for k in [k for k, v in self.npcs.items() if t - v["t"] > 30.0]:
            del self.npcs[k]

    def _log_reacq(self, tr, pos):
        mx, my, sig = self._mean_xy(tr)
        err = math.hypot(mx - pos[0], my - pos[1])
        lx, ly = tr.last_pos[0], tr.last_pos[1]
        base = math.hypot(lx - pos[0], ly - pos[1])
        age = self.t - (tr.t_lost or self.t)
        if age > 0.3:
            self.stats["reacq"].append((age, err, base, sig))
        if self.P["hunt_auto"] and 1.5 <= age <= 25.0:
            ex, ey = self.me["pos"][0], self.me["pos"][1]
            ux, uy = ex - mx, ey - my
            ud = math.hypot(ux, uy)
            if ud > 25.0:
                sample = ((pos[0] - mx) * ux + (pos[1] - my) * uy) / ud / age
                self.hunt = max(0.0, min(self.P["hunt_max_mps"], self.hunt + self.P["hunt_rate"] * max(-10.0, min(10.0, sample))))
                self.hunt_n += 1

    def _seed_particles(self, tr, x, y, vx, vy, spread):
        n = max(8, int(self.P["n_hidden"] * self.scale))
        r = self.rng
        tr.px = [x + r.gauss(0, spread) for _ in range(n)]
        tr.py = [y + r.gauss(0, spread) for _ in range(n)]
        s = self.P["walk_sigma"] * 0.3
        tr.vx = [vx + r.gauss(0, s) for _ in range(n)]
        tr.vy = [vy + r.gauss(0, s) for _ in range(n)]
        tr.w = [1.0 / n] * n

    def _mean_xy(self, tr):
        if tr.px is None:
            return tr.pos[0], tr.pos[1], 0.0
        w = tr.w
        s = sum(w) or 1.0
        mx = sum(a * b for a, b in zip(tr.px, w)) / s
        my = sum(a * b for a, b in zip(tr.py, w)) / s
        v = sum(b * ((a - mx) ** 2 + (c - my) ** 2) for a, c, b in zip(tr.px, tr.py, w)) / s
        return mx, my, math.sqrt(v / 2.0)

    # =========================================================================================
    # cloud <-> identified bookkeeping
    # =========================================================================================
    def _take_from_cloud(self, x, y, sigma):
        """An enemy was located at (x, y): remove one unit of unseen mass, weighted by locality."""
        c = self.cloud
        if c.mass < 0.5 or not c.px:
            c.mass = max(0.0, c.mass - 1.0)
            return
        inv = -0.5 / (sigma * sigma)
        k = [math.exp(((a - x) ** 2 + (b - y) ** 2) * inv) for a, b in zip(c.px, c.py)]
        c.w = [w * (1.0 - 0.9 * kk) for w, kk in zip(c.w, k)]
        self._renorm(c, max(0.0, c.mass - 1.0))

    def _spawn_from_cloud(self, tr, ell, n):
        """Create hidden particles for a newly identified, never-seen enemy from cloud mass weighted by ell."""
        c = self.cloud
        r = self.rng
        wl = [w * ell(a, b) for w, a, b in zip(c.w, c.px, c.py)]
        s = sum(wl)
        if s <= 1e-9 or not c.px:
            return False
        cum, acc = [], 0.0
        for v in wl:
            acc += v
            cum.append(acc)
        tr.px, tr.py, tr.vx, tr.vy = [], [], [], []
        for _ in range(n):
            i = bisect.bisect_left(cum, r.random() * acc)
            i = min(i, len(cum) - 1)
            tr.px.append(c.px[i] + r.gauss(0, 1.5))
            tr.py.append(c.py[i] + r.gauss(0, 1.5))
            tr.vx.append(c.vx[i])
            tr.vy.append(c.vy[i])
        tr.w = [1.0 / n] * n
        # remove one unit from the cloud in proportion to ell
        c.w = [w * (1.0 - 0.9 * min(1.0, ell(a, b))) for w, a, b in zip(c.w, c.px, c.py)]
        self._renorm(c, max(0.0, c.mass - 1.0))
        return True

    def _hidden_tracks(self):
        return [tr for tr in self.tracks.values() if not tr.vis and tr.px is not None]

    # =========================================================================================
    # motion
    # =========================================================================================
    def _predict(self, dt):
        if dt <= 0:
            return
        P = self.P
        steps = 1 if dt <= 0.25 else 2
        h = dt / steps
        zone = self.obs["zone"]
        for tr in self._hidden_tracks():
            self._move(tr, h, steps, zone, keep=True)
        if self.cloud.px:
            self._move(self.cloud, h, steps, zone, keep=False)

    def hunt_bias(self):
        P = self.P
        if P["hunt_auto"]:
            return max(0.0, min(P["hunt_max_mps"], self.hunt))
        return P["hunt_fixed_mps"]

    def _move(self, o, h, steps, zone, keep):
        P = self.P
        g = self.geom
        bias = self.hunt_bias()
        hx, hy = self.me["pos"][0], self.me["pos"][1]
        gauss = self.rng.gauss
        a = math.exp(-h / P["vel_tau_s"])
        b = P["walk_sigma"] * math.sqrt(max(0.0, 1.0 - a * a))
        vmax = self.cfg["mech"]["boost_speed"] * 1.3
        px, py, vx, vy = o.px, o.py, o.vx, o.vy
        n = len(px)
        zx, zy = zone["center"]
        zr = zone["radius"] + P["zone_slack_m"]
        pull = P["zone_pull_mps"]
        gb, gidx = g.gb, g.idx
        minx, maxx, miny, maxy = g.minx + 3, g.maxx - 3, g.miny + 3, g.maxy - 3
        for _ in range(steps):
            for i in range(n):
                x, y = px[i], py[i]
                u = vx[i] * a + b * gauss(0, 1)
                v = vy[i] * a + b * gauss(0, 1)
                if bias > 0.0:
                    qx, qy = hx - x, hy - y
                    qd = math.sqrt(qx * qx + qy * qy) + 1e-6
                    if qd > 25.0:
                        k = (1.0 - a) * bias / qd
                        u += k * qx
                        v += k * qy
                dx, dy = x - zx, y - zy
                d2 = dx * dx + dy * dy
                if d2 > zr * zr:
                    d = math.sqrt(d2)
                    u -= pull * dx / d * h * 3
                    v -= pull * dy / d * h * 3
                sp2 = u * u + v * v
                if sp2 > vmax * vmax:
                    k = vmax / math.sqrt(sp2)
                    u *= k
                    v *= k
                nx_, ny_ = x + u * h, y + v * h
                if nx_ < minx or nx_ > maxx or ny_ < miny or ny_ > maxy:
                    u = -u
                    v = -v
                    nx_, ny_ = x, y
                else:
                    k = gidx(nx_, ny_)
                    if k < 0 or gb[k]:
                        u, v = -0.5 * v, 0.5 * u
                        nx_, ny_ = x, y
                px[i], py[i], vx[i], vy[i] = nx_, ny_, u, v

    # =========================================================================================
    # likelihood helpers
    # =========================================================================================
    def _ell_ray(self, ox, oy, th, sig, lo, hi, slack, floor):
        inv = -0.5 / (sig * sig)
        sl2 = -0.5 / (slack * slack)
        atan2, exp, sqrt = math.atan2, math.exp, math.sqrt

        def ell(x, y):
            dx, dy = x - ox, y - oy
            d = sqrt(dx * dx + dy * dy)
            da = atan2(dy, dx) - th
            da = (da + PI) % TWO_PI - PI
            a = exp(da * da * inv)
            if d < lo:
                a *= exp((lo - d) ** 2 * sl2)
            elif d > hi:
                a *= exp((d - hi) ** 2 * sl2)
            return floor + (1.0 - floor) * a
        return ell

    def _ell_point(self, x0, y0, sig):
        inv = -0.5 / (sig * sig)
        exp = math.exp

        def ell(x, y):
            return exp(((x - x0) ** 2 + (y - y0) ** 2) * inv)
        return ell

    def _own_pos_at(self, age):
        t = self.t - age
        h = self.hist
        if len(h) == 1 or t >= h[-1][0]:
            return h[-1][1], h[-1][2]
        for i in range(len(h) - 1, 0, -1):
            if h[i - 1][0] <= t <= h[i][0]:
                f = (t - h[i - 1][0]) / max(1e-6, h[i][0] - h[i - 1][0])
                return h[i - 1][1] + f * (h[i][1] - h[i - 1][1]), h[i - 1][2] + f * (h[i][2] - h[i - 1][2])
        return h[0][1], h[0][2]

    def _compat(self, tr, need):
        if need is None or need in tr.weapons:
            return 1.0
        if tr.heard.get(need) is not None:
            return 1.0
        return self.P["compat_missing_weapon"]

    # =========================================================================================
    # data association + update (sound, projectile shot fix)
    # =========================================================================================
    def _associate_update(self, ell, need, kind_label, shift_ok=True):
        """One anonymous detection with likelihood field `ell`: soft-associate across visible tracks,
        hidden tracks and the unseen cloud, then apply the mass-preserving mixture update to each hidden object."""
        P = self.P
        cands = []   # (key, L, compat, ells)
        for tr in self.tracks.values():
            c = self._compat(tr, need)
            if tr.vis:
                L = ell(tr.pos[0] - tr.vel[0] * 0.05, tr.pos[1] - tr.vel[1] * 0.05)
                cands.append((tr, L * c, None, None))
            elif tr.px is not None:
                ls = [ell(a, b) for a, b in zip(tr.px, tr.py)]
                s = sum(tr.w) or 1.0
                L = sum(w * l for w, l in zip(tr.w, ls)) / s
                cands.append((tr, L * c, ls, s))
        cl = self.cloud
        Lu, lu = 0.0, None
        if P["use_cloud"] and cl.mass > 0.05 and cl.px:
            lu = [ell(a, b) for a, b in zip(cl.px, cl.py)]
            Lu = sum(w * l for w, l in zip(cl.w, lu))     # mass-scaled: expected number of enemies consistent with it
        tot = P["sound_bg"] + Lu + sum(c[1] for c in cands)
        if tot <= 1e-12:
            return None
        best = None
        for tr, Lc, ls, s in cands:
            r = Lc / tot
            if r > 0.4:
                tr.heard[kind_label] = self.t
            if ls is None or r < 1e-3:
                continue
            L = Lc / max(1e-9, self._compat(tr, need))
            if L <= 1e-12:
                continue
            tr.w = [w * ((1.0 - r) + r * l / L) for w, l in zip(tr.w, ls)]
            ssum = sum(tr.w)
            if ssum > 0:
                tr.w = [w / ssum * s for w in tr.w]
        if lu is not None and Lu > 1e-9:
            ru = Lu / tot
            k = ru / max(cl.mass, 1e-9)
            cl.w = [w * (1.0 - k) + ru * w * l / Lu for w, l in zip(cl.w, lu)]
            self._renorm(cl, cl.mass)
        return tot

    def _pick_sounds(self, sounds):
        out = []
        for s in sounds:
            k = s.get("kind")
            if k == "death":
                ox, oy = self._own_pos_at(s.get("age", 0.0))
                self.death_sounds.append((self.t, ox, oy, s["bearing"], s["dist"]))
            if k in MECH_SOUNDS:
                out.append(s)
        out.sort(key=lambda s: SOUND_PRIORITY.get(s["kind"], 5))
        return out[: self.P["max_sounds_per_tick"]]

    def _on_sound(self, s):
        P = self.P
        kind = s["kind"]
        ox, oy = self._own_pos_at(s.get("age", 0.0))
        lo, hi = _bin_edges(s["dist"], kind, self.cfg)
        sig = max(math.radians(P["bearing_floor_deg"]),
                  math.radians(self.cfg["sound"]["bearing_noise_deg"]) * self.hearing * P["bearing_sigma_scale"])
        ell = self._ell_ray(ox, oy, s["bearing"], sig, lo, hi, P["bin_slack_m"], P["sound_floor"])
        self.recent_sounds.append((self.t, ox, oy, s["bearing"], lo, hi, kind))
        self._associate_update(ell, MECH_SOUNDS[kind], kind)

    # =========================================================================================
    # events / beams
    # =========================================================================================
    def _track_for_id(self, tid, ell, rng_ok=True):
        """Return the hidden track for an enemy id, creating it from the cloud if never seen. None if visible."""
        if not isinstance(tid, (int, float)) or tid >= 100 or tid == self.slot:
            return None
        tid = int(tid)
        tr = self.tracks.get(tid)
        if tr is None:
            tr = Track(tid, self.t)
            tr.vis = False
            tr.t_lost = self.t
            n = max(8, int(self.P["n_hidden"] * self.scale))
            if not self._spawn_from_cloud(tr, ell, n):
                return None
            tr.pos = [sum(tr.px) / n, sum(tr.py) / n, 0.0]
            tr.last_pos = list(tr.pos)
            self.tracks[tid] = tr
        return tr

    def _apply_ell(self, tr, ell):
        if tr is None or tr.vis or tr.px is None:
            return
        tr.w = [w * ell(a, b) for w, a, b in zip(tr.w, tr.px, tr.py)]
        if sum(tr.w) < 1e-12:       # inconsistent: reseed along the field
            return
        s = sum(tr.w)
        tr.w = [w / s for w in tr.w]

    def _on_event(self, e):
        P = self.P
        ty = e.get("type")
        me = self.me["pos"]
        if ty == "damaged":
            w, by, br = e.get("weapon"), e.get("by"), e.get("bearing")
            if br is None or by is None or w not in ("gun", "laser", "lightning"):
                return
            ell = self._ell_ray(me[0], me[1], br, math.radians(P["event_sigma_deg"]), 0.0, self.wrange[w] * 1.15,
                                P["bin_slack_m"], P["sound_floor"])
            tr = self._track_for_id(by, ell)
            if tr is not None:
                tr.weapons.add(w)
                tr.heard[w] = self.t
                self._apply_ell(tr, ell)
        elif ty == "hit":
            tgt, w = e.get("target"), e.get("weapon")
            if tgt is None or tgt >= 100 or w not in ("gun", "laser", "lightning") or self.prev_aim is None:
                return
            yaw = 0.5 * (self.prev_aim[0] + self.me["aim"][0]) if abs(self.prev_aim[0] - self.me["aim"][0]) < 0.5 else self.me["aim"][0]
            ell = self._ell_ray(me[0], me[1], yaw, math.radians(P["hit_sigma_deg"]), 0.0, self.wrange[w] * 1.1,
                                P["bin_slack_m"], P["sound_floor"])
            tr = self._track_for_id(tgt, ell)
            self._apply_ell(tr, ell)
        elif ty == "kill":
            tid = e.get("target")
            if tid in self.tracks:
                del self.tracks[tid]

    def _on_beam(self, b):
        by = b.get("by")
        path = b.get("path") or []
        if not path or by is None or by >= 100 or by == self.slot:
            return
        x, y = path[0][0], path[0][1]
        ell = self._ell_point(x, y, 8.0)
        tr = self.tracks.get(int(by))
        if tr is None:
            tr = self._track_for_id(by, ell)
            if tr is None:
                return
        if tr.vis:
            tr.weapons.add(b["kind"])
            return
        tr.weapons.add(b["kind"])
        tr.heard[b["kind"]] = self.t
        n = len(tr.px)
        r = self.rng
        tr.px = [x + r.gauss(0, 1.5) for _ in range(n)]
        tr.py = [y + r.gauss(0, 1.5) for _ in range(n)]
        tr.vx = [r.gauss(0, 1.0) for _ in range(n)]
        tr.vy = [r.gauss(0, 1.0) for _ in range(n)]
        tr.w = [1.0 / n] * n

    # =========================================================================================
    # projectiles
    # =========================================================================================
    def _on_projectiles(self, projs, deadline):
        P = self.P
        w = self.world
        new = 0
        for p in projs:
            pid = p["id"]
            if p["kind"] == "npc" or pid in self.seen_proj:
                continue
            if new >= P["proj_max_per_tick"] or time.perf_counter() > deadline:
                break
            self.seen_proj.add(pid)
            new += 1
            if p["kind"] == "gun":
                self._gun_fix(p)
            elif p["kind"] == "mortar":
                self._mortar_fix(p)
        if len(self.seen_proj) > 4000:
            self.seen_proj = set(list(self.seen_proj)[-1000:])

    def _gun_fix(self, p):
        x, y, z = p["pos"]
        vx, vy = p["vel"][0], p["vel"][1]
        sp = math.hypot(vx, vy)
        if sp < 1.0:
            return
        ux, uy = vx / sp, vy / sp
        rng = self.cfg["weapons"]["gun"]["range"] * 1.25 + 10
        sig = self.P["proj_sigma_m"]
        inv = -0.5 / (sig * sig)
        exp = math.exp

        def ell(a, b):
            rx, ry = a - x, b - y
            along = -(rx * ux + ry * uy)            # distance behind the bullet
            perp = rx * (-uy) + ry * ux
            if along < -5.0 or along > rng:
                return 0.02
            return 0.02 + 0.98 * exp(perp * perp * inv)
        self._associate_update(ell, "gun", "gun")

    def _mortar_fix(self, p):
        fix = self.mortar_launch(p)
        if fix is None:
            return
        ell = self._ell_point(fix[0], fix[1], self.P["mortar_sigma_m"])
        self._associate_update(ell, "mortar", "mortar")

    def mortar_launch(self, p):
        """Back-trace a shell to its launch point using constant |v0| and gravity. Returns (x, y, z, t_flight) or None."""
        cfg = self.cfg["weapons"]["mortar"]
        g = cfg["gravity"]
        x, y, z = p["pos"]
        vx, vy, vz = p["vel"]
        vh2 = vx * vx + vy * vy
        best = None
        for mult in (1.0, 1.2, 1.44):
            v0 = cfg["speed"] * mult
            q = v0 * v0 - vh2
            if q < 0:
                continue
            s = math.sqrt(q)
            for vz0 in (s, -s):
                tt = (vz0 - vz) / g
                if tt < -0.05 or tt > cfg.get("ttl", 7.0) + 0.2:
                    continue
                tt = max(tt, 0.0)
                x0 = x - vx * tt
                y0 = y - vy * tt
                z0 = z - vz0 * tt + 0.5 * g * tt * tt
                err = abs(z0 - (self.geom.ground(x0, y0) + 9.5))
                if best is None or err < best[0]:
                    best = (err, x0, y0, z0, tt)
        if best is None or best[0] > 7.0:
            return None
        return best[1], best[2], best[3], best[4]

    # =========================================================================================
    # death accounting
    # =========================================================================================
    def _death_accounting(self, obs, events):
        alive = obs.get("alive")
        if alive is None:
            return
        target = alive - 1
        cur = len(self.tracks) + self.cloud.mass
        guard = 0
        while cur > target + 0.5 and guard < 16:
            guard += 1
            self._remove_victim()
            cur = len(self.tracks) + self.cloud.mass
        if self.cloud.mass < 0:
            self.cloud.mass = 0.0

    def _remove_victim(self):
        """Someone died: pick the most likely candidate using the recent death sound and last-known hp."""
        t = self.t
        ds = [d for d in self.death_sounds if t - d[0] < 1.5]
        sig = math.radians(self.cfg["sound"]["bearing_noise_deg"]) * self.hearing
        cand = []
        if ds:
            _, ox, oy, br, dist = ds[-1]
            lo, hi = _bin_edges(dist, "death", self.cfg)
            ell = self._ell_ray(ox, oy, br, sig, lo, hi, self.P["bin_slack_m"], 0.05)
        else:
            ell = None
        for tr in self.tracks.values():
            if tr.vis:
                L = 0.0
            elif tr.px is None:
                L = 0.05
            else:
                s = sum(tr.w) or 1.0
                L = sum(w * (ell(a, b) if ell else 1.0) for w, a, b in zip(tr.w, tr.px, tr.py)) / s
            # a track that vanished from a fully visible spot with low hp is the likeliest victim
            if tr.t_lost is not None and abs(tr.t_lost - t) < 0.15 and tr.hp is not None and tr.hp < 0.35 * tr.max_hp:
                L = max(L, 1.5)
            cand.append((L, "t", tr))
        cl = self.cloud
        if cl.mass > 0.5 and cl.px:
            Lu = sum(w * (ell(a, b) if ell else 1.0) for w, a, b in zip(cl.w, cl.px, cl.py))
            cand.append((Lu, "c", None))
        if not cand:
            return
        cand.sort(key=lambda c: -c[0])
        _, kind, tr = cand[0]
        if kind == "t":
            del self.tracks[tr.id]
        else:
            if ell is not None:
                cl.w = [w * (1.0 - 0.9 * ell(a, b)) for w, a, b in zip(cl.w, cl.px, cl.py)]
            self._renorm(cl, max(0.0, cl.mass - 1.0))

    # =========================================================================================
    # negative information
    # =========================================================================================
    def _carve(self, obs):
        P = self.P
        g = self.geom
        vis_r, near_r, fov = self._vision_params()
        ex, ey = self.me["pos"][0], self.me["pos"][1]
        ez = self.me["pos"][2] + self.me.get("stats", {}).get("eye_height", 8.0)
        yaw = self.me["aim"][0]
        K = P["los_rays"]
        cs, sn = g._dirs(K)
        step = P["los_step_m"]
        hz = [None] * K
        margin = P["carve_margin_m"]
        pen = P["carve_pen"]
        half = fov / 2 + 2 * PI / K
        trees = P["trees_occlude"]
        atan2 = math.atan2
        kscale = K / TWO_PI

        def process(px, py, w):
            n = len(px)
            changed = False
            for i in range(n):
                dx, dy = px[i] - ex, py[i] - ey
                d2 = dx * dx + dy * dy
                if d2 > vis_r * vis_r or d2 < 4.0:
                    continue
                a = atan2(dy, dx)
                f = (a + PI) * kscale
                k = int(f) % K
                k2 = (k - 1) % K if f - int(f) < 0.5 else (k + 1) % K
                d = math.sqrt(d2)
                vk = 0.0
                for kk in (k, k2):
                    h = hz[kk]
                    if h is None:
                        th = -PI + (kk + 0.5) * TWO_PI / K
                        lim = vis_r if abs(wrap(th - yaw)) <= half else near_r
                        h = hz[kk] = g.ray(ex, ey, ez, cs[kk], sn[kk], lim, step, trees)
                    vk = h if kk == k else min(vk, h)
                if d + margin < vk:
                    w[i] *= pen
                    changed = True
            return changed

        grace = P["carve_grace_s"]
        for tr in self._hidden_tracks():
            if self.t - (tr.t_lost or 0.0) < grace:
                continue
            if process(tr.px, tr.py, tr.w):
                s = sum(tr.w)
                if s > 1e-12:
                    tr.w = [w / s for w in tr.w]
                else:
                    tr.w = [1.0 / len(tr.w)] * len(tr.w)
        cl = self.cloud
        if cl.px and cl.mass > 0.05 and P["use_cloud"]:
            before = cl.mass
            if process(cl.px, cl.py, cl.w):
                self._renorm(cl, before)

    # =========================================================================================
    # resampling
    # =========================================================================================
    def _maybe_resample(self):
        P = self.P
        thr = P["resample_ess"]
        for tr in self._hidden_tracks():
            n = max(8, int(P["n_hidden"] * self.scale))
            self._resample(tr, n, 1.0, thr)
        cl = self.cloud
        if cl.px:
            n = max(120, int(P["n_cloud"] * self.scale))
            self._resample(cl, n, cl.mass if cl.mass > 0 else 1.0, thr)

    def _resample(self, o, n_out, total, thr):
        w = o.w
        n = len(w)
        s = sum(w)
        if s <= 1e-12:
            return
        s2 = sum(x * x for x in w)
        ess = s * s / s2
        if ess > thr * n and n == n_out:
            return
        r = self.rng
        step = s / n_out
        u = r.random() * step
        cum = 0.0
        i = 0
        px, py, vx, vy = o.px, o.py, o.vx, o.vy
        npx, npy, nvx, nvy = [], [], [], []
        jit = self.P["resample_jitter_m"]
        gb, gidx = self.geom.gb, self.geom.idx
        for kk in range(n_out):
            target = u + kk * step
            while cum + w[i] < target and i < n - 1:
                cum += w[i]
                i += 1
            x = px[i] + r.gauss(0, jit)
            y = py[i] + r.gauss(0, jit)
            k = gidx(x, y)
            if k < 0 or gb[k]:
                x, y = px[i], py[i]
            npx.append(x)
            npy.append(y)
            nvx.append(vx[i] + r.gauss(0, 0.4))
            nvy.append(vy[i] + r.gauss(0, 0.4))
        o.px, o.py, o.vx, o.vy = npx, npy, nvx, nvy
        o.w = [total / n_out] * n_out

    # =========================================================================================
    # outputs
    # =========================================================================================
    def _threat_of(self, tr):
        ws = tr.weapons or {"gun"}
        base = max(self.dps[w] for w in ws if w in self.dps)
        sz = 1.0 + 0.04 * tr.cubes
        hp = 1.0 if tr.hp is None else max(0.2, tr.hp / tr.max_hp)
        return base * sz * (0.5 + 0.5 * hp) / self.dps["gun"]

    def _build_outputs(self, obs):
        P = self.P
        w = self.world
        w.t, w.tick, w.me = self.t, obs["tick"], self.me
        w.npcs = self.npcs
        w.n_unseen = self.cloud.mass
        cs = []
        for tr in self.tracks.values():
            c = Contact()
            c.id = tr.id
            c.hp, c.max_hp, c.cubes = tr.hp, tr.max_hp, tr.cubes
            c.weapons = set(tr.weapons)
            c.charging = tr.charging and tr.vis
            c.aim = tr.aim
            c.vis = tr.vis
            c.heard = dict(tr.heard)
            c.mass = 1.0
            c.threat = self._threat_of(tr)
            if tr.vis:
                c.pos, c.vel, c.sigma, c.age, c.conf, c.src = list(tr.pos), list(tr.vel), 0.0, 0.0, 1.0, "seen"
            else:
                mx, my, sg = self._mean_xy(tr)
                age = self.t - (tr.t_lost or self.t)
                c.pos = [mx, my, self.geom.ground(mx, my)]
                c.vel = [sum(a * b for a, b in zip(tr.vx, tr.w)) / (sum(tr.w) or 1.0),
                         sum(a * b for a, b in zip(tr.vy, tr.w)) / (sum(tr.w) or 1.0), 0.0]
                c.sigma, c.age = sg, age
                c.conf = self._mass_within(tr, mx, my, 25.0)
                c.src = "recent" if age < 5.0 else "sound" if tr.heard and self.t - max(tr.heard.values()) < 5.0 else "recent"
            cs.append(c)
        w.hot = self._hot_spots()
        w.contacts = cs + w.hot
        self._incoming(obs)
        self._telegraphs()
        self._tg = None

    @staticmethod
    def _mass_within(tr, x, y, r):
        s = sum(tr.w) or 1.0
        return sum(wt for a, b, wt in zip(tr.px, tr.py, tr.w) if (a - x) ** 2 + (b - y) ** 2 < r * r) / s

    def mass_near(self, x, y, radius):
        """Expected number of enemies (identified-hidden + unseen) within radius of (x, y), plus visible ones."""
        r2 = radius * radius
        tot = 0.0
        for tr in self.tracks.values():
            if tr.vis:
                if (tr.pos[0] - x) ** 2 + (tr.pos[1] - y) ** 2 < r2:
                    tot += 1.0
            elif tr.px is not None:
                s = sum(tr.w) or 1.0
                tot += sum(w for a, b, w in zip(tr.px, tr.py, tr.w) if (a - x) ** 2 + (b - y) ** 2 < r2) / s
        cl = self.cloud
        tot += sum(w for a, b, w in zip(cl.px, cl.py, cl.w) if (a - x) ** 2 + (b - y) ** 2 < r2)
        return tot

    def _hot_spots(self):
        P = self.P
        cl = self.cloud
        if not cl.px or cl.mass < 0.05:
            return []
        cell = P["hot_cell_m"]
        acc = {}
        for a, b, wt in zip(cl.px, cl.py, cl.w):
            key = (int(a // cell), int(b // cell))
            e = acc.get(key)
            if e is None:
                acc[key] = [wt, a * wt, b * wt]
            else:
                e[0] += wt
                e[1] += a * wt
                e[2] += b * wt
        # merge 3x3 neighbourhood mass for ranking
        out = []
        used = set()
        keys = sorted(acc, key=lambda k: -acc[k][0])
        for k in keys:
            if k in used:
                continue
            m = x = y = 0.0
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    kk = (k[0] + dx, k[1] + dy)
                    e = acc.get(kk)
                    if e is not None and kk not in used:
                        m += e[0]
                        x += e[1]
                        y += e[2]
                        used.add(kk)
            if m < P["hot_min_mass"]:
                break
            x, y = x / m, y / m
            c = Contact()
            c.id, c.pos, c.vel = None, [x, y, self.geom.ground(x, y)], [0.0, 0.0, 0.0]
            c.sigma, c.age, c.conf, c.hp, c.max_hp, c.cubes = cell, 0.0, min(1.0, m), None, None, 0
            c.weapons, c.charging, c.aim, c.vis, c.src = set(), False, [0, 0], False, "unseen"
            c.mass = m
            c.threat = m * P["unknown_threat"]
            c.heard = self._heard_near(x, y, cell * 1.5)
            out.append(c)
            if len(out) >= P["hot_max"]:
                break
        return out

    def _heard_near(self, x, y, rad):
        res = {}
        for (t, ox, oy, br, lo, hi, kind) in self.recent_sounds:
            if self.t - t > 8.0:
                continue
            d = math.hypot(x - ox, y - oy)
            if lo - rad <= d <= hi + rad and abs(wrap(math.atan2(y - oy, x - ox) - br)) < math.radians(18):
                res[kind] = res.get(kind, 0) + 1
        return res

    # ---- threat grid ------------------------------------------------------------------------
    def threat_grid(self):
        if self._tg is not None and self._tg_tick == self.world.tick:
            return self._tg
        P = self.P
        g = self.geom
        cell = P["tg_cell_m"]
        nx = int((g.maxx - g.minx) / cell) + 1
        ny = int((g.maxy - g.miny) / cell) + 1
        data = [0.0] * (nx * ny)

        def add(x, y, v):
            i = int((x - g.minx) / cell)
            j = int((y - g.miny) / cell)
            if 0 <= i < nx and 0 <= j < ny:
                data[j * nx + i] += v
        for tr in self.tracks.values():
            th = self._threat_of(tr)
            if tr.vis:
                add(tr.pos[0], tr.pos[1], th)
            elif tr.px is not None:
                s = sum(tr.w) or 1.0
                for a, b, w in zip(tr.px, tr.py, tr.w):
                    add(a, b, th * w / s)
        cl = self.cloud
        u = P["unknown_threat"]
        for a, b, w in zip(cl.px, cl.py, cl.w):
            add(a, b, u * w)
        self._tg = {"cell": cell, "minx": g.minx, "miny": g.miny, "nx": nx, "ny": ny, "data": data}
        self._tg_tick = self.world.tick
        return self._tg

    # ---- projectiles / telegraphs ---------------------------------------------------------------
    def _incoming(self, obs):
        P = self.P
        me = self.me
        mx, my, mz = me["pos"]
        mvx, mvy = me["vel"][0], me["vel"][1]
        size = 1.0 + self.cfg["cubes"].get("size_per_cube", 0.05) * me.get("cubes", 0)
        R = self.cfg["mech"]["radius"] * size + self.cfg["projectile"]["gun_radius"] + 0.6
        H = self.cfg["mech"]["height"] * size
        res = []
        horizon = 1.2
        mort = self.cfg["weapons"]["mortar"]
        for p in obs.get("projectiles", []):
            if p["kind"] == "mortar":
                inc = self._mortar_incoming(p, mx, my, mz)
                if inc is not None:
                    res.append(inc)
                continue
            x, y, z = p["pos"]
            vx, vy, vz = p["vel"]
            rx, ry = x - mx, y - my
            wx, wy = vx - mvx, vy - mvy
            a = wx * wx + wy * wy
            if a < 1e-6:
                continue
            tcpa = -(rx * wx + ry * wy) / a
            cx, cy = rx + wx * tcpa, ry + wy * tcpa
            miss = math.hypot(cx, cy)
            if tcpa < -0.05 or tcpa > horizon or miss > R + 3.0:
                continue
            # first time the bullet is inside radius R
            if miss < R:
                dt_in = math.sqrt(max(0.0, R * R - miss * miss) / a)
                t_hit = max(0.0, tcpa - dt_in)
            else:
                t_hit = tcpa
            zc = z + vz * t_hit
            if not (mz - 0.5 <= zc <= mz + H + 0.5):
                continue
            inc = Incoming()
            inc.id, inc.kind, inc.t_hit, inc.miss = p["id"], p["kind"], t_hit, miss
            inc.pos, inc.vel = p["pos"], p["vel"]
            inc.hit_pos = [x + vx * t_hit, y + vy * t_hit, zc]
            wn = math.sqrt(a)
            inc.dodge = self._dodge_dir(cx, cy, -wy / wn, wx / wn)
            inc.radius = R
            inc.hit = miss < R
            sp = math.hypot(vx, vy)
            inc.shooter = [x - vx / max(sp, 1e-6) * 60.0, y - vy / max(sp, 1e-6) * 60.0] if p["kind"] == "gun" else None
            res.append(inc)
        res.sort(key=lambda i: i.t_hit)
        self.world.incoming = res

    @staticmethod
    def _dodge_dir(cx, cy, nx_, ny_):
        # (cx, cy) is where the bullet passes relative to us; step to the opposite side of the path
        s = -1.0 if (cx * nx_ + cy * ny_) > 0 else 1.0
        return [s * nx_, s * ny_]

    def _mortar_incoming(self, p, mx, my, mz):
        cfg = self.cfg["weapons"]["mortar"]
        g = cfg["gravity"]
        x, y, z = p["pos"]
        vx, vy, vz = p["vel"]
        g_ = self.geom
        t = 0.0
        dt = 0.05
        while t < 7.0:
            t += dt
            xx, yy = x + vx * t, y + vy * t
            zz = z + vz * t - 0.5 * g * t * t
            if zz <= g_.ground(xx, yy):
                break
            if g_.idx(xx, yy) < 0:
                return None
        else:
            return None
        d = math.hypot(xx - mx, yy - my)
        rad = cfg["splash_radius"] * 1.3
        if d > rad + 12.0:
            return None
        inc = Incoming()
        inc.id, inc.kind, inc.t_hit, inc.miss = p["id"], "mortar", t, d
        inc.hit_pos, inc.radius, inc.pos, inc.vel = [xx, yy, zz], rad, p["pos"], p["vel"]
        inc.hit = d < rad
        dd = max(d, 1e-6)
        inc.dodge = [(mx - xx) / dd, (my - yy) / dd]
        fix = self.mortar_launch(p)
        inc.shooter = [fix[0], fix[1]] if fix else None
        return inc

    def _telegraphs(self):
        w = self.world
        me = self.me
        mx, my = me["pos"][0], me["pos"][1]
        size = 1.0 + 0.05 * me.get("cubes", 0)
        R = self.cfg["mech"]["radius"] * size + 0.5
        lines, lt = [], []
        lcfg = self.cfg["weapons"]["lightning"]
        for tr in self.tracks.values():
            if not tr.vis:
                continue
            x, y = tr.pos[0], tr.pos[1]
            yaw = tr.aim[0]
            if tr.charging:
                ux, uy = math.cos(yaw), math.sin(yaw)
                rx, ry = mx - x, my - y
                along = rx * ux + ry * uy
                perp = rx * (-uy) + ry * ux
                if along > 0 and abs(perp) < R + 6.0 and along < self.cfg["weapons"]["laser"]["range"]:
                    sgn = 1.0 if perp >= 0 else -1.0
                    lines.append({"id": tr.id, "perp": abs(perp), "along": along,
                                  "dodge": [sgn * -uy, sgn * ux], "hit": abs(perp) < R})
            if "lightning" in tr.weapons:
                d = math.hypot(mx - x, my - y)
                if d < lcfg["range"] * 1.1:
                    cone = abs(wrap(math.atan2(my - y, mx - x) - yaw))
                    if cone < math.radians(lcfg["cone_deg"] + 10):
                        lt.append({"id": tr.id, "dist": d, "cone": cone})
        w.laser_lines = lines
        w.lightning_risk = lt

    # ---- adapters ---------------------------------------------------------------------------
    def loot_threats(self, threat_cls, half_life_s=20.0, sound_weight=0.5):
        """Contacts as loot.Threat(id, dist, kinds, weight) for LootPlanner.step(threats=...).
        Seen enemies weigh 1; hidden ones weigh conf x 0.5^(age/half_life); unseen hot spots count only
        for the weapon kinds heard from them (x sound_weight x mass)."""
        mx, my = self.me["pos"][0], self.me["pos"][1]
        out = []
        for c in self.world.contacts:
            kinds = set(k for k in c.weapons if k in SPECIALS)
            for k in c.heard:
                if k in HEARD_TO_KIND:
                    kinds.add(HEARD_TO_KIND[k])
            if not kinds:
                continue
            d = math.hypot(c.pos[0] - mx, c.pos[1] - my)
            if c.src == "seen":
                w = 1.0
            elif c.src == "unseen":
                w = min(1.0, c.mass) * sound_weight
            else:
                w = c.conf * 0.5 ** (c.age / half_life_s)
            if w >= 0.02:
                out.append(threat_cls(c.id, d, frozenset(kinds), w))
        return out

    # ---- debug --------------------------------------------------------------------------------
    def draw(self, draw):
        w = self.world
        me = self.me["pos"]
        for c in w.contacts:
            if c.src == "seen":
                draw.point([c.pos[0], c.pos[1], c.pos[2] + 4], "#ff5040", 5)
            elif c.src == "unseen":
                draw.point([c.pos[0], c.pos[1], c.pos[2] + 2], "#ffaa00", 8)
                draw.text("m%.1f" % c.mass, [c.pos[0], c.pos[1], c.pos[2] + 3], "#ffaa00")
            else:
                draw.point([c.pos[0], c.pos[1], c.pos[2] + 2], "#c060ff", 5)
                draw.text("%s s%.0f a%.0f" % (c.id, c.sigma, c.age), [c.pos[0], c.pos[1], c.pos[2] + 3], "#c060ff")
        for i in w.incoming[:6]:
            draw.line(i.pos, i.hit_pos, "#ffff40")
