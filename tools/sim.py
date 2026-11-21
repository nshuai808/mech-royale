#!/usr/bin/env python3
"""A crude local Mech Royale simulator, to compare bot versions offline. Standard library only.

    python3 tools/sim.py --matches 8 -- python3 -u bot.py
    python3 tools/sim.py --matches 8 --seed 5 --record -- python3 -u bot.py   # + replay files for analyze.py

Your bot runs as a real subprocess over mechfight/1 (hello, obs, action, end) against 15 in-process house
bots that act like the practice squad: they never fight each other and hunt you, the weakest first, more
of them as you thin them out, all of them late. Score = mean of 16 - place, like the real one.

What it models: the real map grid (walls, sight blockers; nav.py), the zone schedule from config,
acceleration, wall sliding, aim slew, gun bullets that travel (spread, range, walls, rear x1.5), magazine
and reload, HP regen, zone damage, vision (45 m around + 120 deg wedge, buildings block, 5 s memory),
gun/step sounds, placement. What it doesn't: climbing and jets (walls are impassable), terrain height
in shots, trees, loot/crates/cubes/NPCs/upgrades, mortar/laser/lightning. Supply drops ARE modelled
(called at drops.times, land fall_s later in the next circle, alone in the ring capture_s -> full HP, energy,
+cubes as +hp_per_cube max HP); --drop-rivals P sends the nearest idle house bot to a drop with probability P. So it tests movement,
zone play, cover and gunfights. It is NOT the real game: use it for relative comparisons and sanity
checks, and confirm with practice submissions.
"""
import argparse
import json
import math
import os
import queue
import random
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
import replaylog as rl  # noqa: E402
from nav import AStar, Map  # noqa: E402

TAU = 2 * math.pi
SKILL = {"easy": 0.07, "medium": 0.045, "hard": 0.028, "expert": 0.018}  # aim noise (rad)
ROSTER = ["easy"] * 4 + ["medium"] * 4 + ["hard"] * 4 + ["expert"] * 3


def wrap(a):
    return (a + math.pi) % TAU - math.pi


def norm(x, y):
    d = math.hypot(x, y)
    return (x / d, y / d) if d > 1e-9 else (0.0, 0.0)


class Mech:
    def __init__(self, mid, x, y, cfg, skill=None):
        m = cfg["mech"]
        self.id, self.skill = mid, skill
        self.x, self.y, self.z = x, y, 0.0
        self.vx = self.vy = 0.0
        self.yaw, self.pitch = random.uniform(-math.pi, math.pi), 0.0
        self.cmd_yaw, self.cmd_pitch = self.yaw, 0.0
        self.move, self.boost, self.fire = (0.0, 0.0), False, False
        self.hp = self.max_hp = m["hp"]
        self.energy = m["energy"]
        self.last_spend = -9.0
        g = cfg["weapons"]["gun"]
        self.ammo, self.gun_cd, self.reload = g["mag"], 0.0, 0.0
        self.last_combat = -99.0
        self.alive, self.place, self.kills = True, None, 0
        self.cubes, self.base_hp, self.drop_target = 0, m["hp"], None
        self.events = []
        self.seen = {}          # id -> last time seen (for 5 s memory)
        self.last_step = -9.0
        # house-bot brain
        self.path, self.path_t, self.strafe, self.strafe_t = None, -9.0, 1, 0.0


class Sim:
    def __init__(self, cfg, mp, seed, bot_cmd, out=None, verbose=False, drop_rivals=0.5):
        self.cfg, self.map, self.rng = cfg, mp, random.Random(seed)
        random.seed(seed)
        self.bot_cmd, self.out, self.verbose = bot_cmd, out, verbose
        mc = cfg["match"]
        self.dt = 1.0 / mc["tick_hz"]
        self.decide = mc["decide_every"]
        self.t, self.tick = 0.0, 0
        self.bullets = []
        self.sounds = []        # (t, x, y, kind, by)
        self.drops, self.drop_rivals = [], drop_rivals
        self.drop_cfg = cfg.get("drops") or {}
        self.drop_times = list(self.drop_cfg.get("times") or [])
        self._zone_init()
        self._spawn()

    # ------------------------------------------------------------------ setup
    def _free_point(self, cx, cy, r):
        for _ in range(500):
            a, d = self.rng.uniform(0, TAU), r * math.sqrt(self.rng.random())
            x, y = cx + d * math.cos(a), cy + d * math.sin(a)
            k = self.map.cell(x, y)
            if k >= 0 and not self.map.nav[k]:
                return x, y
        return cx, cy

    def _spawn(self):
        z = self.cfg["zone"]
        cx, cy = z["start_center"]
        r = z["start_radius"] * self.cfg["match"].get("spawn_zone_fraction", 0.8)
        sep = self.cfg["match"].get("spawn_min_separation", 130)
        pts = []
        for i in range(16):
            for tries in range(400):
                x, y = self._free_point(cx, cy, r)
                if all(math.hypot(x - a, y - b) >= sep * (1 - tries / 400) for a, b in pts):
                    break
            pts.append((x, y))
        self.me_slot = self.rng.randrange(16)
        roster = ROSTER[:]
        self.mechs = []
        for i, (x, y) in enumerate(pts):
            skill = None if i == self.me_slot else roster.pop(0)
            self.mechs.append(Mech(i, x, y, self.cfg, skill))
        self.me = self.mechs[self.me_slot]
        for m in self.mechs:
            m.z = self.map.ground(m.x, m.y)

    def _zone_init(self):
        z = self.cfg["zone"]
        self.phases = z["phases"]
        self.phase = 0
        self.zc, self.zr = list(z["start_center"]), z["start_radius"]
        self.phase_t0 = 0.0
        self._next_circle()

    def _next_circle(self):
        ph = self.phases[self.phase]
        nr = ph["radius"]
        spread = self.cfg.get("drops", {}).get("spread", 0.7)
        a, d = self.rng.uniform(0, TAU), (self.zr - nr) * spread * math.sqrt(self.rng.random())
        nc = [self.zc[0] + d * math.cos(a), self.zc[1] + d * math.sin(a)]
        # keep it on the map
        m = self.map
        nc[0] = min(max(nc[0], m.minx + nr + 20), m.maxx - nr - 20) if nr < (m.maxx - m.minx) / 2 - 20 else nc[0]
        nc[1] = min(max(nc[1], m.miny + nr + 20), m.maxy - nr - 20) if nr < (m.maxy - m.miny) / 2 - 20 else nc[1]
        self.nc, self.nr = nc, nr
        self.ss = self.phase_t0 + ph["hold_s"]
        self.se = self.ss + ph["shrink_s"]
        self.dps = ph["dps"]
        self.start_c, self.start_r = list(self.zc), self.zr

    def _zone_tick(self):
        t = self.t
        if self.ss < t < self.se:
            f = (t - self.ss) / (self.se - self.ss)
            self.zc = [self.start_c[0] + (self.nc[0] - self.start_c[0]) * f, self.start_c[1] + (self.nc[1] - self.start_c[1]) * f]
            self.zr = self.start_r + (self.nr - self.start_r) * f
        elif t >= self.se:
            self.zc, self.zr = list(self.nc), self.nr
            if self.phase + 1 < len(self.phases):
                self.phase += 1
                self.phase_t0 = self.se
                self._next_circle()
            else:
                self.ss = self.se = 1e9

    def in_zone(self, m):
        return math.hypot(m.x - self.zc[0], m.y - self.zc[1]) <= self.zr

    # ------------------------------------------------------------------ physics
    def _blocked(self, x, y):
        g = self.map.wall
        for ox, oy in ((0, 0), (2.2, 0), (-2.2, 0), (0, 2.2), (0, -2.2)):
            k = self.map.cell(x + ox, y + oy)
            if k < 0 or g[k]:
                return True
        return False

    def _move(self, m):
        mc = self.cfg["mech"]
        mx, my = m.move
        L = math.hypot(mx, my)
        if L > 1:
            mx, my = mx / L, my / L
        speed = mc["walk_speed"]
        if m.boost and (mx or my) and m.energy > 0:
            speed = mc["boost_speed"]
            m.energy = max(0.0, m.energy - mc["boost_drain"] * self.dt)
            m.last_spend = self.t
        elif self.t - m.last_spend > mc["energy_regen_delay"]:
            m.energy = min(mc["energy"], m.energy + mc["energy_regen"] * self.dt)
        tvx, tvy = mx * speed, my * speed
        a = mc["ground_accel"] * self.dt
        dvx, dvy = tvx - m.vx, tvy - m.vy
        dv = math.hypot(dvx, dvy)
        if dv > a:
            dvx, dvy = dvx / dv * a, dvy / dv * a
        m.vx += dvx
        m.vy += dvy
        nx, ny = m.x + m.vx * self.dt, m.y + m.vy * self.dt
        if not self._blocked(nx, ny):
            m.x, m.y = nx, ny
        elif not self._blocked(nx, m.y):
            m.x, m.vy = nx, 0.0
        elif not self._blocked(m.x, ny):
            m.y, m.vx = ny, 0.0
        else:
            m.vx = m.vy = 0.0
        m.z = self.map.ground(m.x, m.y)
        # aim slew
        tr, pr = mc["turn_rate"] * self.dt, mc["pitch_rate"] * self.dt
        d = wrap(m.cmd_yaw - m.yaw)
        m.yaw = wrap(m.yaw + max(-tr, min(tr, d)))
        p = max(mc["min_pitch"], min(mc["max_pitch"], m.cmd_pitch))
        m.pitch += max(-pr, min(pr, p - m.pitch))
        # steps
        if math.hypot(m.vx, m.vy) > self.cfg["sound"]["step_speed"] and self.t - m.last_step > self.cfg["sound"]["step_every"]:
            m.last_step = self.t
            self.sounds.append((self.t, m.x, m.y, "boost" if m.boost else "step", m.id))

    def _guns(self, m):
        g = self.cfg["weapons"]["gun"]
        m.gun_cd = max(0.0, m.gun_cd - self.dt)
        if m.reload > 0:
            m.reload -= self.dt
            if m.reload <= 0:
                m.reload, m.ammo = 0.0, g["mag"]
        if m.fire and m.gun_cd <= 0 and m.ammo > 0 and m.reload <= 0:
            sp = math.radians(g["spread_deg"])
            yaw, pitch = m.yaw + self.rng.gauss(0, sp), m.pitch + self.rng.gauss(0, sp)
            dx, dy, dz = math.cos(pitch) * math.cos(yaw), math.cos(pitch) * math.sin(yaw), math.sin(pitch)
            ox, oy, oz = m.x + dx * 3, m.y + dy * 3, m.z + self.cfg["mech"]["muzzle_height"] + dz * 3
            self.bullets.append([ox, oy, oz, dx * g["speed"], dy * g["speed"], dz * g["speed"], g["range"], m.id])
            m.ammo -= 1
            m.gun_cd = g["cooldown"]
            if m.ammo == 0:
                m.reload = g["reload"]
            self.sounds.append((self.t, m.x, m.y, "gun", m.id))

    def _bullets(self):
        g = self.cfg["weapons"]["gun"]
        mc = self.cfg["mech"]
        keep = []
        for b in self.bullets:
            x, y, z, vx, vy, vz, left, by = b
            step = math.hypot(vx, vy, vz) * self.dt
            nx, ny, nz = x + vx * self.dt, y + vy * self.dt, z + vz * self.dt
            hit = None
            for m in self.mechs:
                if not m.alive or m.id == by:
                    continue
                # closest approach of the segment to the mech axis (2D)
                sx, sy = nx - x, ny - y
                L2 = sx * sx + sy * sy
                f = max(0.0, min(1.0, ((m.x - x) * sx + (m.y - y) * sy) / L2)) if L2 else 0.0
                cx, cy, cz = x + sx * f, y + sy * f, z + (nz - z) * f
                if (cx - m.x) ** 2 + (cy - m.y) ** 2 <= (mc["radius"] + 0.3) ** 2 and m.z <= cz <= m.z + mc["height"]:
                    hit = m
                    break
            if hit:
                self._damage(hit, g["damage"], "gun", self.mechs[by], math.atan2(-vy, -vx))
                continue
            if not self.map.ray_free(x, y, nx, ny, self.map.sight, step=2.0) and nz < self.map.ground(nx, ny) + 12:
                continue
            left -= step
            if left > 0:
                keep.append([nx, ny, nz, vx, vy, vz, left, by])
        self.bullets = keep

    def _damage(self, victim, amount, weapon, src, bearing):
        rear = False
        if src is not None:
            if abs(wrap(bearing - victim.yaw)) > math.radians(self.cfg["mech"]["front_arc_deg"]) / 2:
                amount *= self.cfg["mech"]["rear_mult"]
                rear = True
            src.last_combat = self.t
            src.events.append({"type": "hit", "target": victim.id, "amount": amount, "weapon": weapon, **({"rear": True} if rear else {})})
        victim.hp -= amount
        victim.last_combat = self.t
        ev = {"type": "damaged", "amount": round(amount, 1), "weapon": weapon,
              "bearing": None if src is None else round(bearing, 3), "by": None if src is None else src.id}
        if rear:
            ev["rear"] = True
        victim.events.append(ev)
        if victim.hp <= 0 and victim.alive:
            victim.dead_tick = self.tick
            victim.dead_t = self.t
            victim.alive = False
            victim.killer = src
            if src is not None:
                src.kills += 1
                src.events.append({"type": "kill", "target": victim.id})

    def _upkeep(self, m):
        mc = self.cfg["mech"]
        if not self.in_zone(m):
            self._damage(m, self.dps * self.dt, "zone", None, 0.0)
        elif self.t - m.last_combat > mc["regen_delay"] and m.hp < m.max_hp:
            m.hp = min(m.max_hp, m.hp + mc["regen_per_s"] * self.dt)

    # ------------------------------------------------------------------ supply drops
    def _drops_tick(self):
        dc = self.drop_cfg
        while self.drop_times and self.t >= self.drop_times[0]:
            self.drop_times.pop(0)
            x, y = self._free_point(self.nc[0], self.nc[1], max(5.0, self.nr * 0.8))
            d = {"id": 20000 + len(self.drops), "x": x, "y": y, "z": self.map.ground(x, y), "land": self.t + dc.get("fall_s", 25),
                 "holder": None, "progress": 0.0, "taken": False}
            self.drops.append(d)
            if self.rng.random() < self.drop_rivals:   # a rival house bot goes for it (not one of the hunters)
                hunters = self._hunters()
                idle = [m for m in self.mechs if m.alive and m is not self.me and m.id not in hunters and m.drop_target is None]
                if idle:
                    min(idle, key=lambda m: math.hypot(m.x - x, m.y - y)).drop_target = d["id"]
        rad, cap = dc.get("radius", 8), dc.get("capture_s", 4)
        for d in self.drops:
            if d["taken"] or self.t < d["land"]:
                continue
            inside = [m for m in self.mechs if m.alive and math.hypot(m.x - d["x"], m.y - d["y"]) <= rad]
            if len(inside) == 1:
                m = inside[0]
                if d["holder"] != m.id:
                    d["holder"], d["progress"] = m.id, 0.0
                d["progress"] += self.dt
                if d["progress"] >= cap:
                    d["taken"] = True
                    cc = self.cfg["cubes"]
                    m.cubes += dc.get("cubes", 3)
                    m.max_hp = m.base_hp * (1 + cc["hp_per_cube"] * min(m.cubes, cc["stat_cap"]))
                    m.hp, m.energy = m.max_hp, self.cfg["mech"]["energy"]
                    m.events.append({"type": "drop", "id": d["id"], "cubes": m.cubes})
                    if m is self.me:
                        self.me_drops = getattr(self, "me_drops", 0) + 1
            elif not inside:
                d["holder"], d["progress"] = None, 0.0
        for m in self.mechs:
            if m.drop_target is not None:
                d = next(dd for dd in self.drops if dd["id"] == m.drop_target)
                if d["taken"]:
                    m.drop_target = None

    # ------------------------------------------------------------------ perception
    def sees(self, a, b):
        d = math.hypot(b.x - a.x, b.y - a.y)
        v = self.cfg["vision"]
        if d > v["range"]:
            return False
        if d > v["near_range"] and abs(wrap(math.atan2(b.y - a.y, b.x - a.x) - a.yaw)) > math.radians(v["fov_deg"]) / 2:
            return False
        return self.map.los(a.x, a.y, b.x, b.y)

    def observe(self, me):
        others = []
        for m in self.mechs:
            if m is me or not m.alive:
                continue
            if self.sees(me, m):
                me.seen[m.id] = self.t
            if self.t - me.seen.get(m.id, -99) <= self.cfg["vision"].get("memory_s", 5):
                others.append({"id": m.id, "kind": "mech", "pos": [round(m.x, 2), round(m.y, 2), round(m.z, 2)],
                               "vel": [round(m.vx, 2), round(m.vy, 2), 0], "aim": [round(m.yaw, 3), round(m.pitch, 3)],
                               "hp": round(m.hp), "max_hp": round(m.max_hp), "cubes": m.cubes, "weapons": ["gun"], "charging": False})
        sounds = []
        rng_ = self.cfg["sound"]["range"]
        noise = math.radians(self.cfg["sound"]["bearing_noise_deg"])
        for (st, sx, sy, kind, by) in self.sounds:
            if by == me.id or self.t - st > 0.1 + 1e-9:
                continue
            d = math.hypot(sx - me.x, sy - me.y)
            if d <= rng_.get(kind, 0):
                sounds.append({"kind": kind, "bearing": round(math.atan2(sy - me.y, sx - me.x) + self.rng.gauss(0, noise), 3),
                               "dist": "near" if d < 60 else "mid" if d < 160 else "far", "age": round(self.t - st, 2)})
        g = self.cfg["weapons"]["gun"]
        mc = self.cfg["mech"]
        obs = {
            "type": "obs", "tick": self.tick, "t": round(self.t, 2), "alive": sum(m.alive for m in self.mechs),
            "self": {"id": me.id, "pos": [round(me.x, 2), round(me.y, 2), round(me.z, 2)], "vel": [round(me.vx, 2), round(me.vy, 2), 0],
                     "aim": [round(me.yaw, 3), round(me.pitch, 3)], "hp": round(me.hp, 1), "max_hp": round(me.max_hp, 1),
                     "energy": round(me.energy, 1), "max_energy": mc["energy"], "grounded": True, "cubes": me.cubes, "upgrades": [],
                     "weapons": [{"kind": "gun", "cooldown": round(me.gun_cd, 2), "ammo": me.ammo, "reload": round(max(0, me.reload), 2),
                                  "stats": dict(g)}, None],
                     "in_zone": self.in_zone(me), "stats": dict(mc)},
            "mechs": others, "projectiles": [], "crates": [], "cubes": [], "pickups": [], "sounds": sounds, "beams": [],
            "events": me.events, "offer": None,
            "drops": [{"id": d["id"], "pos": [round(d["x"], 2), round(d["y"], 2), round(d["z"], 2)], "radius": self.drop_cfg.get("radius", 8),
                       "lands_in": round(max(0.0, d["land"] - self.t), 2), "capture_s": self.drop_cfg.get("capture_s", 4),
                       "progress": round(d["progress"], 2), "holder": d["holder"]} for d in self.drops if not d["taken"]],
            "zone": {"center": [round(self.start_c[0], 2), round(self.start_c[1], 2)] if self.t < self.ss else [round(self.zc[0], 2), round(self.zc[1], 2)],
                     "radius": round(self.start_r if self.t < self.ss else self.zr, 2),
                     "next_center": [round(self.nc[0], 2), round(self.nc[1], 2)], "next_radius": self.nr,
                     "shrink_start": round(self.ss, 2), "shrink_end": round(self.se, 2), "dps": self.dps},
        }
        me.events = []
        return obs

    # ------------------------------------------------------------------ house squad
    def _hunters(self):
        house = [m for m in self.mechs if m is not self.me]
        dead = sum(1 for m in house if not m.alive)
        n = len(house) if self.t > 300 else 1 + dead
        order = sorted(house, key=lambda m: list(SKILL).index(m.skill))
        return {m.id for m in order if m.alive}.intersection({m.id for m in order[: n + dead]})

    def _house(self, m, hunters, squad_sees_me):
        me = self.me
        mx, my = m.x, m.y
        sees = me.alive and self.sees(m, me)
        d = math.hypot(me.x - mx, me.y - my)
        want = None
        # zone first
        cd = math.hypot(mx - self.nc[0], my - self.nc[1])
        margin = max(5.0, self.nr * 0.3)
        hunting = m.id in hunters and me.alive
        if not self.in_zone(m) or (cd > self.nr - margin and (self.t > self.ss - 15 or not hunting)):
            want = self._house_path(m, self.nc[0], self.nc[1], max(3.0, self.nr - margin))
        elif m.drop_target is not None and not (hunting and sees):
            dd = next(q for q in self.drops if q["id"] == m.drop_target)
            want = self._house_path(m, dd["x"], dd["y"], 2.0)
        elif hunting:
            if sees and d < 90:
                if self.t > m.strafe_t:
                    m.strafe, m.strafe_t = self.rng.choice((-1, 1)), self.t + self.rng.uniform(1, 2.5)
                ux, uy = norm(me.x - mx, me.y - my)
                rad = 0.6 if d > 70 else (-0.6 if d < 35 else 0.0)
                want = norm(-uy * m.strafe + ux * rad, ux * m.strafe + uy * rad)
            else:
                want = self._house_path(m, me.x, me.y, 30.0)
        m.move = want or (0.0, 0.0)
        m.boost = False
        m.fire = False
        if me.alive and (sees or (hunting and squad_sees_me and d < 120 and self.map.los(mx, my, me.x, me.y))):
            g = self.cfg["weapons"]["gun"]
            mz = m.z + self.cfg["mech"]["muzzle_height"]
            tt = d / g["speed"]
            lx, ly = me.x + me.vx * tt, me.y + me.vy * tt
            noise = SKILL[m.skill]
            if self.tick % 10 == 0:
                m.aim_noise = (self.rng.gauss(0, noise), self.rng.gauss(0, noise * 0.5))
            nz = getattr(m, "aim_noise", (0.0, 0.0))
            m.cmd_yaw = math.atan2(ly - my, lx - mx) + nz[0]
            m.cmd_pitch = math.atan2(me.z + 4.5 - mz, max(d, 1)) + nz[1]
            if d < g["range"] and abs(wrap(m.cmd_yaw - m.yaw)) < 0.1:
                m.fire = True
        elif want:
            m.cmd_yaw = math.atan2(want[1], want[0])

    def _house_path(self, m, gx, gy, gr):
        if math.hypot(gx - m.x, gy - m.y) <= gr:
            return None
        mp = self.map
        if mp.ray_free(m.x, m.y, gx, gy, mp.nav) or mp.blocked(m.x, m.y, mp.nav):
            return norm(gx - m.x, gy - m.y)
        if m.path is None or self.t - m.path_t > 3:
            a = AStar(mp, m.x, m.y, gx, gy, gr, max_expand=20000)
            a.step(1.0)
            m.path, m.path_t = a.path, self.t
        if m.path:
            while len(m.path) > 1 and math.hypot(m.path[0][0] - m.x, m.path[0][1] - m.y) < 4:
                m.path.pop(0)
            wx, wy = m.path[0]
            return norm(wx - m.x, wy - m.y)
        return norm(gx - m.x, gy - m.y)

    # ------------------------------------------------------------------ bot process
    def _start_bot(self):
        env = dict(os.environ, MECH_TRACE="1", PYTHONUNBUFFERED="1")
        self.proc = subprocess.Popen(self.bot_cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=ROOT)
        self.q = queue.Queue()
        self.errs = []

        def out():
            for raw in self.proc.stdout:
                self.q.put(raw)
            self.q.put(None)

        def err():
            for raw in self.proc.stderr:
                line = raw.decode("utf-8", "replace").rstrip("\n")
                tr = rl.parse_trace(line)
                if self.log:
                    self.log.write("trace" if tr is not None else "err", tr, raw=None if tr is not None else line)
                if tr is None:
                    self.errs.append(line)

        threading.Thread(target=out, daemon=True).start()
        threading.Thread(target=err, daemon=True).start()

    def _send(self, msg):
        if self.log:
            self.log.write("in", msg)
        try:
            self.proc.stdin.write((json.dumps(msg, separators=(",", ":")) + "\n").encode())
            self.proc.stdin.flush()
            return True
        except (BrokenPipeError, OSError):
            return False

    def _recv(self, tick, timeout):
        end = time.perf_counter() + timeout
        while True:
            left = end - time.perf_counter()
            if left <= 0:
                return None, None
            try:
                raw = self.q.get(timeout=left)
            except queue.Empty:
                return None, None
            if raw is None:
                return None, "eof"
            try:
                m = json.loads(raw)
            except ValueError:
                continue
            if tick is None or m.get("tick") == tick:
                return m, None

    # ------------------------------------------------------------------ run
    def run(self, budget_ms=50.0):
        self.log = rl.Writer(self.out) if self.out else None
        if self.log:
            self.log.write("meta", {"tool": "sim", "cmd": self.bot_cmd})
        self._start_bot()
        hello = {"type": "hello", "protocol": "mechfight/1", "slot": self.me_slot, "seed": self.rng.randrange(2 ** 31),
                 "map": {"dir": os.path.join(ROOT, "kit", "arena"), "files": ["v2/world.json", "v2/terrain.i16"]}, "config": self.cfg}
        self._send(hello)
        ready, _ = self._recv(None, 20)
        if self.log and ready:
            self.log.write("out", ready)
        last_cmd, last_ok_t = {}, 0.0
        late = 0
        dur = self.cfg["match"]["duration_s"]
        while self.t < dur and sum(m.alive for m in self.mechs) > 1 and (self.me.alive or self.me.place is None):
            if self.tick % self.decide == 0:
                hunters = self._hunters()
                squad_sees = any(self.sees(h, self.me) for h in self.mechs if h is not self.me and h.alive)
                for m in self.mechs:
                    if m.alive and m is not self.me:
                        self._house(m, hunters, squad_sees)
                if self.me.alive:
                    o = self.observe(self.me)
                    sent = time.perf_counter()
                    self._send(o)
                    a, why = self._recv(o["tick"], budget_ms / 1000)
                    lat = (time.perf_counter() - sent) * 1000
                    if a is None:
                        late += 1
                        if why == "eof" or self.t - last_ok_t > self.cfg["bot"]["coast_s"]:
                            last_cmd = {}
                        a = {k: last_cmd[k] for k in ("move", "aim", "boost") if k in last_cmd}
                    else:
                        if self.log:
                            self.log.write("out", a, lat_ms=round(lat, 2))
                        last_ok_t = self.t
                        last_cmd = a
                    me = self.me
                    mv = a.get("move") or [0, 0]
                    me.move = (float(mv[0]), float(mv[1]))
                    me.boost = bool(a.get("boost"))
                    if "aim" in a:
                        me.cmd_yaw, me.cmd_pitch = float(a["aim"][0]), float(a["aim"][1])
                    f = a.get("fire") or [False, False]
                    me.fire = bool(f[0]) if f else False
            for m in self.mechs:
                if m.alive:
                    self._move(m)
                    self._guns(m)
            self._bullets()
            for m in self.mechs:
                if m.alive:
                    self._upkeep(m)
            self._zone_tick()
            self._drops_tick()
            self.sounds = [s for s in self.sounds if self.t - s[0] < 0.2]
            # placements: everyone who died this tick shares the place
            died = [m for m in self.mechs if not m.alive and m.place is None]
            if died:
                alive_after = sum(m.alive for m in self.mechs)
                for m in died:
                    m.place = alive_after + 1
            self.t += self.dt
            self.tick += 1
        alive = [m for m in self.mechs if m.alive]
        if not self.me.alive:
            pass  # our place was set the tick we died; the rest doesn't matter
        elif len(alive) == 1:
            alive[0].place = 1
        else:  # clock ran out: rank by HP
            for i, m in enumerate(sorted(alive, key=lambda m: -m.hp)):
                m.place = i + 1
        me = self.me
        end = {"type": "end", "place": me.place, "kills": me.kills}
        self._send(end)
        try:
            self.proc.stdin.close()
            self.proc.wait(timeout=3)
        except Exception:
            self.proc.kill()
        if self.log:
            time.sleep(0.05)
            self.log.close()
        cause = "survived" if me.alive else ("zone" if getattr(me, "killer", None) is None else f"#{me.killer.id} ({me.killer.skill})")
        return {"place": me.place, "kills": me.kills, "drops": getattr(self, "me_drops", 0), "t": round(getattr(me, "dead_t", self.t), 1), "cause": cause, "late": late, "errs": self.errs[-5:]}


def main():
    argv = sys.argv[1:]
    if "--" not in argv:
        sys.exit("usage: sim.py [--matches N] [--seed S] [--record] -- BOT COMMAND...")
    i = argv.index("--")
    ap = argparse.ArgumentParser()
    ap.add_argument("--matches", type=int, default=8)
    ap.add_argument("--first", type=int, default=0, help="start at match index N (seed*1000+N), to rerun one match")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--record", action="store_true", help="write a replay file per match into replays/")
    ap.add_argument("--budget-ms", type=float, default=50.0)
    ap.add_argument("--drop-rivals", type=float, default=0.5, help="chance a house bot goes for each supply drop")
    a = ap.parse_args(argv[:i])
    cmd = argv[i + 1:]
    import gzip
    with gzip.open(rl.KIT_STREAM, "rt") as f:
        cfg = json.loads(f.readline())["config"]
    mp = Map(os.path.join(ROOT, "kit", "arena"), cfg["mech"]["height"], cfg["mech"]["step_up"], cfg["mech"]["max_slope_deg"], cfg["mech"]["eye_height"])
    pts, t0 = [], time.time()
    for n in range(a.first, a.first + a.matches):
        seed = a.seed * 1000 + n
        out = os.path.join(rl.REPLAYS, f"sim-s{seed}.jsonl.gz") if a.record else None
        r = Sim(cfg, mp, seed, cmd, out, drop_rivals=a.drop_rivals).run(a.budget_ms)
        pts.append(16 - r["place"])
        print(f"match {n + 1:2} seed {seed}: place {r['place']:2} ({16 - r['place']:2} pts)  died {r['cause']:16} at {r['t']:5.1f}s  kills {r['kills']}  drops {r['drops']}"
              + (f"  late {r['late']}" if r["late"] else "") + (f"  stderr: {r['errs'][-1]}" if r["errs"] else ""), flush=True)
    mean = sum(pts) / len(pts)
    sd = (sum((p - mean) ** 2 for p in pts) / max(1, len(pts) - 1)) ** 0.5
    print(f"SCORE {mean:.2f}  (+-{sd / max(1, len(pts)) ** 0.5:.2f} s.e., {len(pts)} matches, {time.time() - t0:.0f} s)")


if __name__ == "__main__":
    main()
