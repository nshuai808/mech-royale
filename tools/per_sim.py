"""Perception test harness (tools/per_eval.py runs ablations on it): a deliberately small world with ground truth.

Not the H-SIM simulator. It has only what perception needs to be tested honestly:
  * 15 scripted enemies (campers, walkers, boosters) on the real map, with weapon loadouts
  * the protocol's vision rule (120 deg wedge to 200 m, 45 m all round, building LOS, crowns block)
    evaluated with a *finer* ray march than the module uses, so the module's coarse horizon is tested for error
  * the protocol's sound rule (carry ranges, 7 deg bearing noise, sharp near/mid/far bins, step/boost cadence)
  * damaged events (id + exact bearing) when enemies shoot at us, and occasional deaths
"""
import math
import random
import sys

import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PI = math.pi


def wrap(a):
    return (a + PI) % (2 * PI) - PI


class Enemy:
    pass


class Scenario:
    def __init__(self, hello, geom, seed, duration=90.0, fire_rate=0.1, deaths=2, zone_r=None, sep=130.0, hunt_frac=0.0):
        self.cfg = hello["config"]
        self.g = geom
        self.r = random.Random(seed)
        self.t = 0.0
        self.dur = duration
        self.fire_rate = fire_rate
        self.zc = self.cfg["zone"]["start_center"]
        self.zr = zone_r or self.cfg["zone"]["start_radius"]
        self.tick = 0
        r = self.r
        # our mech
        self.me = {"pos": self._free(0.8), "vel": [0, 0, 0], "aim": [r.uniform(-PI, PI), 0.0]}
        self.me_wp = self._free(0.5)
        self.enemies = []
        for i in range(15):
            e = Enemy()
            e.id = i + (1 if i >= hello["slot"] else 0)
            while True:
                p = self._free(0.8)
                if math.hypot(p[0] - self.me["pos"][0], p[1] - self.me["pos"][1]) < sep:
                    continue
                if any(math.hypot(p[0] - o.pos[0], p[1] - o.pos[1]) < sep for o in self.enemies):
                    continue
                break
            e.pos = p
            e.vel = [0.0, 0.0]
            e.wp = self._free(0.7)
            e.speed = r.choice([0.0, 0.0, 4.0, 8.0, 11.7, 11.7, 19.5])
            e.hunt = r.random() < hunt_frac
            if e.hunt:
                e.speed = r.choice([8.0, 11.7, 11.7, 19.5])
            e.retarget = 0.0
            e.weapons = ["gun"] + ([r.choice(["mortar", "laser", "lightning"])] if r.random() < 0.6 else [])
            e.alive = True
            e.burst = 0
            e.burst_w = "gun"
            e.next_snd = 0.0
            e.next_step = r.random() * 0.6
            e.cubes = 0
            e.hp = 1400.0
            self.enemies.append(e)
        self.death_times = sorted(r.uniform(20, duration - 5) for _ in range(deaths))
        self.pending = []      # sound events generated this step: (kind, x, y, t)
        self.events = []

    def _free(self, frac):
        while True:
            a = self.r.random() * 2 * PI
            d = self.zr * frac * math.sqrt(self.r.random())
            x, y = self.zc[0] + d * math.cos(a), self.zc[1] + d * math.sin(a)
            if not self.g.gblocked(x, y):
                return [x, y, self.g.ground(x, y)]

    # ------------------------------------------------------------------------------------
    def step(self, dt=0.1):
        r, g = self.r, self.g
        self.t += dt
        self.tick += 2
        self.pending = []
        self.events = []
        me = self.me
        # our movement: waypoint walker, scanning aim
        dx, dy = self.me_wp[0] - me["pos"][0], self.me_wp[1] - me["pos"][1]
        d = math.hypot(dx, dy)
        if d < 8:
            self.me_wp = self._free(0.5)
        else:
            sp = 7.0
            nx, ny = me["pos"][0] + dx / d * sp * dt, me["pos"][1] + dy / d * sp * dt
            if g.gblocked(nx, ny):
                self.me_wp = self._free(0.5)
                me["vel"] = [0, 0, 0]
            else:
                me["pos"][0], me["pos"][1] = nx, ny
                me["pos"][2] = g.ground(nx, ny)
                me["vel"] = [dx / d * sp, dy / d * sp, 0]
        base = math.atan2(dy, dx)
        me["aim"][0] = wrap(base + 1.1 * math.sin(0.9 * self.t))
        # enemies
        for e in self.enemies:
            if not e.alive:
                continue
            if e.hunt:
                e.retarget -= dt
                if e.retarget <= 0:
                    e.retarget = 3.0
                    e.wp = [me["pos"][0] + r.gauss(0, 25), me["pos"][1] + r.gauss(0, 25), 0.0]
            ex, ey = e.wp[0] - e.pos[0], e.wp[1] - e.pos[1]
            dd = math.hypot(ex, ey)
            if dd < 6 or e.speed == 0:
                if e.speed > 0 and not e.hunt:
                    e.wp = self._free(0.7)
                e.vel = [0.0, 0.0]
            else:
                nx, ny = e.pos[0] + ex / dd * e.speed * dt, e.pos[1] + ey / dd * e.speed * dt
                if g.gblocked(nx, ny):
                    if not e.hunt:
                        e.wp = self._free(0.7)
                    e.vel = [0.0, 0.0]
                else:
                    e.pos[0], e.pos[1], e.pos[2] = nx, ny, g.ground(nx, ny)
                    e.vel = [ex / dd * e.speed, ey / dd * e.speed]
            sp = math.hypot(*e.vel)
            e.next_step -= dt
            if sp > 5.0 and e.next_step <= 0:
                e.next_step = 0.6
                self.pending.append(("boost" if sp > 15 else "step", e.pos[0], e.pos[1], e))
            # firing
            if e.burst <= 0 and r.random() < self.fire_rate * dt:
                e.burst = r.randint(8, 25)
                e.burst_w = r.choice(e.weapons)
            if e.burst > 0:
                e.burst -= 1
                e.next_snd -= dt
                w = e.burst_w
                cd = {"gun": 0.24, "mortar": 2.6, "laser": 2.4, "lightning": 0.25}[w]
                if e.next_snd <= 0:
                    e.next_snd = cd
                    if w == "laser":
                        self.pending.append(("laser_charge", e.pos[0], e.pos[1], e))
                    self.pending.append((w, e.pos[0], e.pos[1], e))
                    # shots that find us
                    dme = math.hypot(e.pos[0] - me["pos"][0], e.pos[1] - me["pos"][1])
                    rng = {"gun": 150, "laser": 150, "lightning": 40}.get(w, 0)
                    if rng and dme < rng and self.visible_pair(e) and r.random() < 0.3:
                        br = math.atan2(me["pos"][1] - e.pos[1], me["pos"][0] - e.pos[0]) + PI
                        self.events.append({"type": "damaged", "amount": 45, "weapon": w, "bearing": wrap(br),
                                            "by": e.id, "rear": False})
        # deaths
        if self.death_times and self.t >= self.death_times[0]:
            self.death_times.pop(0)
            cand = [e for e in self.enemies if e.alive and not self.is_visible(e)]
            if cand:
                e = r.choice(cand)
                e.alive = False
                self.pending.append(("death", e.pos[0], e.pos[1], e))

    # ------------------------------------------------------------------------------------
    def eye(self):
        return [self.me["pos"][0], self.me["pos"][1], self.me["pos"][2] + 8.0]

    def is_visible(self, e):
        me = self.me["pos"]
        dx, dy = e.pos[0] - me[0], e.pos[1] - me[1]
        d = math.hypot(dx, dy)
        v = self.cfg["vision"]
        if d > v["range"]:
            return False
        if d > v["near_range"] and abs(wrap(math.atan2(dy, dx) - self.me["aim"][0])) > math.radians(v["fov_deg"]) / 2:
            return False
        return self.g.los(self.eye(), [e.pos[0], e.pos[1], e.pos[2] + 5.0], step=1.5, trees=True)

    def visible_pair(self, e):
        return self.g.los([e.pos[0], e.pos[1], e.pos[2] + 7.0], self.eye(), step=2.0, trees=False)

    def hello_obs(self):
        r = self.r
        cfg = self.cfg
        mechs = []
        for e in self.enemies:
            if e.alive and self.is_visible(e):
                mechs.append({"id": e.id, "kind": "mech", "pos": [e.pos[0], e.pos[1], e.pos[2]],
                              "vel": [e.vel[0], e.vel[1], 0.0], "aim": [0.0, 0.0], "hp": e.hp, "max_hp": 1400,
                              "cubes": 0, "weapons": list(e.weapons), "charging": False})
        sounds = []
        me = self.me["pos"]
        for kind, x, y, e in self.pending:
            d = math.hypot(x - me[0], y - me[1])
            if d > cfg["sound"]["range"][kind]:
                continue
            br = math.atan2(y - me[1], x - me[0]) + math.radians(r.gauss(0, cfg["sound"]["bearing_noise_deg"]))
            dist = "near" if d < 60 else "mid" if d < 160 else "far"
            sounds.append({"kind": kind, "bearing": wrap(br), "dist": dist, "age": r.choice([0.05, 0.1])})
        alive = 1 + sum(1 for e in self.enemies if e.alive)
        return {"type": "obs", "tick": self.tick, "t": round(self.t, 3), "alive": alive,
                "self": {"id": 99, "pos": list(me), "vel": list(self.me["vel"]), "aim": list(self.me["aim"]),
                         "hp": 1400, "max_hp": 1400, "energy": 100, "max_energy": 100, "grounded": True, "cubes": 0,
                         "upgrades": [], "in_zone": True, "weapons": [None, None], "stats": dict(cfg["mech"])},
                "mechs": mechs, "projectiles": [], "crates": [], "cubes": [], "pickups": [], "sounds": sounds,
                "beams": [], "events": self.events, "drops": [],
                "zone": {"center": self.zc, "radius": self.zr, "next_center": self.zc, "next_radius": self.zr,
                         "shrink_start": 9999, "shrink_end": 9999, "dps": 20}, "offer": None}
