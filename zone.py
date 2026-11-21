"""zone.py: zone detection and safety planning (H-ZON). Standard library only.

Owns: where the circle is and will be, whether we are (or will be) outside it, and a zone-safe goal
with an urgency level. Does NOT own: pathing (the goal is a straight-line target; nav routes it),
supply-drop capture (only the `drop_is_safe` helper exists, not wired), move/boost/jump (the arbiter in
bot.py decides), take/drop (loot).

Usage inside a bot:

    tracker = zone.ZoneTracker(hello, params.get("zone"))
    plan = tracker.update(obs)               # ZonePlan or None; never raises
    if plan and plan.goal and plan.urgency >= zone_cutoff:
        goal, boost = plan.goal, plan.boost   # hand to the arbiter

Every number is in ZoneParams (-> params.json["zone"]).

What it gives the bot each tick (see `ZonePlan`):
  * exact current circle and where it will be at any future time (linear shrink)
  * margin to the edge (+ inside, - outside) with an online-calibrated edge bias
  * time until the edge reaches us if we stand still
  * a simulated escape: damage taken if we walk / boost to a safe point
  * a goal point and an urgency level so combat/loot code knows when to yield

Authority order for "am I outside": zone damage event > obs.self.in_zone > geometry.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, fields
from typing import List, Optional, Sequence, Tuple

Vec2 = Tuple[float, float]

# urgency levels
FREE, SOON, GO, CRITICAL = 0, 1, 2, 3
URGENCY_NAMES = ("free", "soon", "go", "critical")

INF = float("inf")


@dataclass
class ZoneParams:
    enabled: bool = True
    base_margin_m: float = 6.0          # safety inset on top of the mech's own radius (H-ZON arrival margin)
    safe_min_frac: float = 0.5          # safe disc is never smaller than this fraction of the next circle
    comfort_frac: float = 0.6           # idle point radius as a fraction of the next circle
    bias_limit_m: float = 6.0           # clamp on the learned edge offset
    critical_hp_frac: float = 0.6       # escape costing this fraction of HP (or more) is CRITICAL
    go_slack_s: float = 6.0             # slack below this (time_to_exit - travel time) -> GO
    soon_slack_s: float = 20.0          # slack below this -> SOON
    soon_before_shrink_s: float = 15.0  # a shrink this close counts as SOON even with lots of slack
    boost_penalty_s: float = 0.5        # prefer walking unless boosting saves at least this long
    sim_dt_s: float = 0.25
    sim_horizon_s: float = 90.0
    override_loot_urgency: int = 2      # bot.py: zone goal beats the loot goal at or above this (2 = GO)
    idle_goal: str = "center"           # bot.py when FREE and no loot goal: "center" (v1 walk) or "comfort"

    @classmethod
    def from_dict(cls, d: Optional[dict]) -> "ZoneParams":
        """Build from params.json["zone"]: unknown keys ignored, partial overrides allowed, bad types ignored."""
        p = cls()
        for f in fields(cls):
            if isinstance(d, dict) and f.name in d:
                v = d[f.name]
                cur = getattr(p, f.name)
                try:
                    setattr(p, f.name, type(cur)(v) if not isinstance(cur, bool) else bool(v))
                except Exception:
                    pass
        return p


def _finite(*xs: float) -> bool:
    return all(isinstance(x, (int, float)) and math.isfinite(x) for x in xs)


@dataclass(frozen=True)
class Circle:
    cx: float
    cy: float
    r: float

    def dist_to_center(self, p: Sequence[float]) -> float:
        return math.hypot(p[0] - self.cx, p[1] - self.cy)

    def margin(self, p: Sequence[float]) -> float:
        """Positive inside, negative outside (distance to the edge)."""
        return self.r - self.dist_to_center(p)


@dataclass
class ZonePlan:
    now: float
    circle: Circle                 # circle right now
    next_circle: Circle            # circle it is shrinking to
    shrinking: bool
    phase: int                     # index of the phase whose circle we are heading to (best effort)
    dps: float
    margin: float                  # to current edge, bias-corrected (+ inside)
    inside: bool                   # best belief: no zone damage right now
    time_to_exit: float            # standing still; 0 if already outside, INF if never this phase
    goal: Optional[Vec2]           # where to go to be safe (None if already safe)
    comfort_goal: Vec2             # where to drift when idle late in a phase
    est_damage: float              # HP lost following the plan from here
    stay_damage: float             # HP lost if we stand still until the next circle is reached
    boost: bool                    # recommend boosting toward goal
    urgency: int
    reason: str = ""

    @property
    def urgency_name(self) -> str:
        return URGENCY_NAMES[self.urgency]


@dataclass
class _Schedule:
    """Phase timeline from hello.config.zone (used when the obs has no future info)."""
    start: Circle
    radii: List[float] = field(default_factory=list)
    dps: List[float] = field(default_factory=list)
    shrink_start: List[float] = field(default_factory=list)
    shrink_end: List[float] = field(default_factory=list)

    @classmethod
    def from_config(cls, zcfg: Optional[dict]) -> "_Schedule":
        sch = cls(Circle(0.0, 0.0, 560.0))
        if not isinstance(zcfg, dict):
            return sch
        try:
            c = zcfg.get("start_center") or [0.0, 0.0]
            sch.start = Circle(float(c[0]), float(c[1]), float(zcfg.get("start_radius", 560.0)))
            t = 0.0
            for ph in zcfg.get("phases") or []:
                hold, shrink = float(ph["hold_s"]), float(ph["shrink_s"])
                sch.shrink_start.append(t + hold)
                sch.shrink_end.append(t + hold + shrink)
                sch.radii.append(float(ph["radius"]))
                sch.dps.append(float(ph["dps"]))
                t += hold + shrink
        except Exception:
            pass
        return sch

    def phase_at(self, t: float) -> int:
        """Index of the phase active at t (hold or shrink); len(phases) after the end."""
        for i, e in enumerate(self.shrink_end):
            if t < e:
                return i
        return len(self.shrink_end)

    def dps_at(self, t: float, fallback: float) -> float:
        i = self.phase_at(t)
        if 0 <= i < len(self.dps):
            return self.dps[i]
        return self.dps[-1] if self.dps else fallback


class ZoneTracker:
    """Feed it every hello/obs. Call `update(obs)` -> ZonePlan (or None if the obs has no zone)."""

    def __init__(self, hello: Optional[dict] = None, params: Optional[dict] = None):
        self.p = ZoneParams.from_dict(params)
        cfg = (hello or {}).get("config", {}) if isinstance(hello, dict) else {}
        mech = cfg.get("mech", {}) or {}
        self.schedule = _Schedule.from_config(cfg.get("zone"))
        self.mech_radius = float(mech.get("radius", 2.5))
        self.walk_speed = float(mech.get("walk_speed", 11.7))
        self.boost_speed = float(mech.get("boost_speed", 19.5))
        self.boost_drain = float(mech.get("boost_drain", 17.0))
        self.edge_bias = 0.0           # learned: true_edge = geometric_edge + bias (clamped)
        # state
        self._prev_margin: Optional[float] = None
        self._prev_inside: Optional[bool] = None
        self._last_plan: Optional[ZonePlan] = None
        self._zone_hit_t = -INF        # last time we saw zone damage
        self._flips = 0
        self.mismatches = 0            # times in_zone disagreed with geometry (for tuning)
        self.errors = 0

    # ---------------------------------------------------------------- circles
    @staticmethod
    def parse(z: dict) -> Tuple[Circle, Circle, float, float, float]:
        c, n = z["center"], z["next_center"]
        cur = Circle(float(c[0]), float(c[1]), max(0.0, float(z["radius"])))
        nxt = Circle(float(n[0]), float(n[1]), max(0.0, float(z["next_radius"])))
        return cur, nxt, float(z["shrink_start"]), float(z["shrink_end"]), float(z.get("dps", 0.0))

    @staticmethod
    def circle_at(cur: Circle, nxt: Circle, s0: float, s1: float, t: float) -> Circle:
        """Exact circle at match time t, given the obs' current/next circle and shrink window."""
        if t <= s0 or s1 <= s0:
            return cur if t <= s0 else nxt
        if t >= s1:
            return nxt
        f = (t - s0) / (s1 - s0)
        return Circle(cur.cx + (nxt.cx - cur.cx) * f,
                      cur.cy + (nxt.cy - cur.cy) * f,
                      cur.r + (nxt.r - cur.r) * f)

    @staticmethod
    def first_exit(p: Vec2, cur: Circle, nxt: Circle, s0: float, s1: float, t0: float,
                   inset: float = 0.0) -> float:
        """Earliest time >= t0 when a point standing at p is outside (radius reduced by `inset`).
        Exact: inside the shrink window the test |p-c(s)|^2 > (r(s)-inset)^2 is a quadratic in s.
        Returns t0 if already outside, INF if the point stays inside through the next circle."""
        def outside_at(t: float) -> bool:
            c = ZoneTracker.circle_at(cur, nxt, s0, s1, t)
            return c.dist_to_center(p) > c.r - inset

        if outside_at(t0):
            return t0
        if t0 < s0 and outside_at(s0):          # hold phase never moves, so this only guards bad data
            return s0
        # Solve in the shrink window [max(t0,s0), s1].
        a_t = max(t0, s0)
        if s1 <= s0 or a_t >= s1:
            return INF if not outside_at(s1) else s1
        dx0, dy0 = p[0] - cur.cx, p[1] - cur.cy
        ddx, ddy = -(nxt.cx - cur.cx), -(nxt.cy - cur.cy)    # p - c(s) = d0 + dd*s
        r0, dr = cur.r - inset, nxt.r - cur.r
        # g(s) = |d0 + dd s|^2 - (r0 + dr s)^2 = A s^2 + B s + C ; outside when g > 0
        A = ddx * ddx + ddy * ddy - dr * dr
        B = 2 * (dx0 * ddx + dy0 * ddy) - 2 * r0 * dr
        C = dx0 * dx0 + dy0 * dy0 - r0 * r0
        s_lo = (a_t - s0) / (s1 - s0)
        # g(s_lo) <= 0 here. Find the smallest root in (s_lo, 1].
        roots: List[float] = []
        if abs(A) < 1e-12:
            if abs(B) > 1e-12:
                roots.append(-C / B)
        else:
            disc = B * B - 4 * A * C
            if disc >= 0:
                sq = math.sqrt(disc)
                roots += [(-B - sq) / (2 * A), (-B + sq) / (2 * A)]
        # Radius can only be negative past r==0; ignore roots that are not real crossings.
        hits = sorted(r for r in roots if s_lo - 1e-9 <= r <= 1.0 + 1e-9)
        for r in hits:
            probe = min(1.0, r + 1e-4)
            g = (dx0 + ddx * probe) ** 2 + (dy0 + ddy * probe) ** 2 - (r0 + dr * probe) ** 2
            if g > 0:
                return s0 + max(r, s_lo) * (s1 - s0)
        return INF if not outside_at(s1) else s1

    # ------------------------------------------------------------ simulation
    def _simulate(self, p: Vec2, goal: Vec2, t0: float, cur: Circle, nxt: Circle, s0: float, s1: float,
                  energy: float, boost: bool, dps_fn, inset: float, vmult: float = 1.0,
                  horizon: float = 90.0, dt: float = 0.25) -> Tuple[float, float]:
        """Walk straight to goal (then stand). Returns (damage, arrival_time_offset)."""
        x, y = p
        gx, gy = goal
        t = t0
        dmg = 0.0
        energy_left = energy if boost else 0.0
        arrived = None
        steps = int(horizon / dt)
        for _ in range(steps):
            d = math.hypot(gx - x, gy - y)
            if d > 0.5:
                if energy_left > 0:
                    v = self.boost_speed * vmult
                    energy_left -= self.boost_drain * dt
                else:
                    v = self.walk_speed * vmult
                step = min(d, v * dt)
                x += (gx - x) / d * step
                y += (gy - y) / d * step
            elif arrived is None:
                arrived = t - t0
            c = self.circle_at(cur, nxt, s0, s1, t)
            if math.hypot(x - c.cx, y - c.cy) > c.r - inset:
                dmg += dps_fn(t) * dt
            t += dt
            if t > s1 + 1.0 and arrived is not None:
                break
        return dmg, (arrived if arrived is not None else horizon)

    # --------------------------------------------------------------- updating
    def update(self, obs: dict) -> Optional[ZonePlan]:
        try:
            plan = self._update(obs)
        except Exception:
            self.errors += 1
            return self._last_plan if self._last_plan is not None else None
        self._last_plan = plan
        return plan

    def _note_events(self, obs: dict) -> None:
        t = float(obs.get("t", 0.0))
        for ev in obs.get("events") or []:
            if ev.get("type") == "damaged" and ev.get("weapon") == "zone":
                self._zone_hit_t = t

    def _calibrate(self, margin_raw: float, inside_obs: Optional[bool]) -> None:
        """When in_zone flips between ticks the true edge lies between the two margins."""
        if inside_obs is None:
            return
        if self._prev_inside is not None and inside_obs != self._prev_inside and self._prev_margin is not None:
            lo, hi = sorted((self._prev_margin, margin_raw))
            if hi - lo < 8.0:       # ignore flips from big jumps (knockback, teleports)
                est = -(lo + hi) / 2.0  # true edge at raw margin == -bias  => bias = -mid
                a = 1.0 if self._flips == 0 else 0.5   # first observation is the best info we have
                self._flips += 1
                self.edge_bias = max(-self.p.bias_limit_m, min(self.p.bias_limit_m, (1 - a) * self.edge_bias + a * est))
        geo_inside = margin_raw >= 0
        if geo_inside != inside_obs:
            self.mismatches += 1
        self._prev_inside, self._prev_margin = inside_obs, margin_raw

    def _update(self, obs: dict) -> Optional[ZonePlan]:
        z = obs.get("zone")
        me = obs.get("self") or {}
        if not z or "pos" not in me:
            return None
        now = float(obs.get("t", 0.0))
        pos = (float(me["pos"][0]), float(me["pos"][1]))
        vel = me.get("vel") or [0.0, 0.0, 0.0]
        if not _finite(now, pos[0], pos[1]):
            return None
        self._note_events(obs)

        cur, nxt, s0, s1, dps = self.parse(z)
        if not _finite(cur.cx, cur.cy, cur.r, nxt.cx, nxt.cy, nxt.r, s0, s1):
            return None
        # Repair malformed data: next circle must be inside the current one.
        if nxt.r > cur.r:
            nxt = Circle(nxt.cx, nxt.cy, cur.r)
        shrinking = s0 <= now < s1

        # ---- where am I relative to the edge
        raw_margin = cur.margin(pos)
        inside_obs = me.get("in_zone")
        inside_obs = bool(inside_obs) if inside_obs is not None else None
        self._calibrate(raw_margin, inside_obs)
        margin = raw_margin + self.edge_bias
        if inside_obs is None:
            inside = margin >= 0
        else:
            inside = inside_obs
            # in_zone says outside but geometry says inside (or the reverse): trust in_zone, but make the
            # margin sign agree so downstream code can't get confused.
            if inside and margin < 0:
                margin = 0.0
            elif not inside and margin >= 0:
                margin = -0.01
        if now - self._zone_hit_t < 0.25:       # took zone damage this tick: definitely outside
            inside = False
            margin = min(margin, -0.01)

        cubes = float(me.get("cubes", 0) or 0)
        scale = 1.0 + 0.05 * cubes
        inset = self.mech_radius * scale + self.p.base_margin_m
        vmult = 1.0
        st = me.get("stats") or {}
        if _finite(st.get("walk_speed", math.nan)) and self.walk_speed > 0:
            vmult = float(st["walk_speed"]) / self.walk_speed
        energy = float(me.get("energy", 0.0) or 0.0)

        def dps_fn(t: float) -> float:
            # current dps applies through the current shrink; after that use the schedule
            return dps if t < s1 else self.schedule.dps_at(t, dps)

        # ---- phase index (best effort) from radii
        phase = self._phase_index(cur, nxt, now)

        # ---- time until the edge reaches me if I stand still
        t_exit = self.first_exit(pos, cur, nxt, s0, s1, now, inset=0.0) if inside else now
        time_to_exit = max(0.0, t_exit - now) if t_exit != INF else INF

        # ---- safe disc = next circle inset by margin (never smaller than half the circle)
        safe_r = max(nxt.r - inset, nxt.r * self.p.safe_min_frac)
        safe_center = (nxt.cx, nxt.cy)
        d_next = math.hypot(pos[0] - nxt.cx, pos[1] - nxt.cy)
        # standing still is fine iff we stay inside until the next circle is final
        if inside and time_to_exit == INF:
            stay_dmg = 0.0          # exact test says the edge never reaches us: skip the simulation
        else:
            stay_dmg, _ = self._simulate(pos, pos, now, cur, nxt, s0, s1, 0.0, False, dps_fn, inset=0.0,
                                         vmult=vmult, horizon=max(5.0, min(120.0, s1 - now + 2.0)),
                                         dt=self.p.sim_dt_s)
        comfort = self._comfort_goal(pos, nxt)

        if d_next <= safe_r and inside and stay_dmg <= 0.0:
            plan = ZonePlan(now, cur, nxt, shrinking, phase, dps, margin, inside, time_to_exit,
                            None, comfort, 0.0, 0.0, False, FREE, "inside next circle")
            plan.urgency = self._free_or_soon(plan, s0, now)
            return plan

        # ---- candidate goals; pick the one with least predicted damage, then shortest walk
        cands = self._candidates(pos, nxt, safe_r)
        best = None
        for use_boost in (False, True):
            for g in cands:
                dmg, tarr = self._simulate(pos, g, now, cur, nxt, s0, s1, energy, use_boost, dps_fn,
                                           inset=0.0, vmult=vmult, horizon=self.p.sim_horizon_s, dt=self.p.sim_dt_s)
                # boosting costs energy we may want for jumping/jetting: small penalty
                key = (round(dmg, 1), tarr + (self.p.boost_penalty_s if use_boost else 0.0))
                if best is None or key < best[0]:
                    best = (key, g, dmg, use_boost, tarr)
        _, goal, dmg, use_boost, tarr = best

        hp = float(me.get("hp", 1400.0) or 1400.0)
        urgency, reason = self._classify(inside, time_to_exit, dmg, hp, tarr, now, s0, shrinking, stay_dmg)
        # Only recommend boost when it is actually needed (it burns energy that jets/jumps need).
        boost = bool(use_boost and urgency >= GO)
        return ZonePlan(now, cur, nxt, shrinking, phase, dps, margin, inside, time_to_exit, goal,
                        comfort, dmg, stay_dmg, boost, urgency, reason)

    # ----------------------------------------------------------------- helpers
    def _phase_index(self, cur: Circle, nxt: Circle, now: float) -> int:
        sch = self.schedule
        for i, r in enumerate(sch.radii):
            if abs(r - nxt.r) < 0.5:
                return i
        return sch.phase_at(now)

    @staticmethod
    def _toward(p: Vec2, c: Vec2, dist_from_center: float) -> Vec2:
        """Point at `dist_from_center` from c on the ray c->p."""
        d = math.hypot(p[0] - c[0], p[1] - c[1])
        if d < 1e-6:
            return (c[0] + dist_from_center, c[1])
        k = dist_from_center / d
        return (c[0] + (p[0] - c[0]) * k, c[1] + (p[1] - c[1]) * k)

    def _candidates(self, pos: Vec2, nxt: Circle, safe_r: float) -> List[Vec2]:
        c = (nxt.cx, nxt.cy)
        d = math.hypot(pos[0] - c[0], pos[1] - c[1])
        out = [self._toward(pos, c, min(d, safe_r)),            # nearest point of the safe disc
               self._toward(pos, c, min(d, safe_r * self.p.comfort_frac)),      # a bit deeper
               c]                                                # dead centre
        # De-duplicate near-identical points.
        uniq: List[Vec2] = []
        for g in out:
            if all(math.hypot(g[0] - u[0], g[1] - u[1]) > 1.0 for u in uniq):
                uniq.append(g)
        return uniq

    def _comfort_goal(self, pos: Vec2, nxt: Circle) -> Vec2:
        """Where to idle: well inside the next circle (60% radius), on our side of it."""
        c = (nxt.cx, nxt.cy)
        d = math.hypot(pos[0] - c[0], pos[1] - c[1])
        return self._toward(pos, c, min(d, nxt.r * self.p.comfort_frac)) if d > 1e-6 else c

    def _free_or_soon(self, plan: ZonePlan, s0: float, now: float) -> int:
        # Inside the next circle already: SOON only matters as a hint that a shrink is imminent.
        if now < s0 and s0 - now < self.p.soon_before_shrink_s:
            return SOON
        return FREE

    def _classify(self, inside: bool, time_to_exit: float, dmg: float, hp: float, tarr: float,
                  now: float, s0: float, shrinking: bool, stay_dmg: float) -> Tuple[int, str]:
        if not inside:
            if dmg >= self.p.critical_hp_frac * hp:
                return CRITICAL, "outside, escape costs a lot of hp"
            return GO, "outside the zone"
        if dmg >= self.p.critical_hp_frac * hp:
            return CRITICAL, "will be caught; escape costs a lot of hp"
        if dmg > 0:
            return GO, "edge will reach us; leave now"
        # No damage even on the best plan, but standing still would hurt: leave with slack.
        slack = time_to_exit - tarr
        if slack < self.p.go_slack_s:
            return GO, f"slack {slack:.1f}s"
        if slack < self.p.soon_slack_s or (not shrinking and s0 - now < self.p.soon_before_shrink_s):
            return SOON, f"slack {slack:.1f}s"
        return FREE, f"slack {slack:.1f}s"

    # ------------------------------------------------------------ convenience
    def drop_is_safe(self, drop: dict, plan: ZonePlan, pos: Vec2, speed: Optional[float] = None) -> bool:
        """Is a supply drop worth heading for: lands inside the circle we are heading to, and we can
        reach it before the edge gets there."""
        try:
            dp = drop["pos"]
            d_next = math.hypot(dp[0] - plan.next_circle.cx, dp[1] - plan.next_circle.cy)
            if d_next > plan.next_circle.r - drop.get("radius", 8.0) * 0.5:
                return False
            v = speed or self.walk_speed
            eta = math.hypot(dp[0] - pos[0], dp[1] - pos[1]) / v
            return eta <= max(drop.get("lands_in", 0.0), 0.0) + 25.0 or plan.urgency == FREE
        except Exception:
            return False
