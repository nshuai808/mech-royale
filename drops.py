"""drops.py: supply-drop planner (H-DRP). Standard library only.

A supply drop (protocol.md section 7) is called at 70/140/210 s, lands `fall_s` later inside the circle the zone is
closing to, and gives `cubes` power cubes + full HP + full energy to the mech that stands ALONE inside its ring
(`radius` m) for `capture_s` seconds. Two mechs in the ring freeze the clock; the ring emptying or a different
mech becoming the only one in it restarts it. Every mech sees every called drop in `obs.drops`.

Owns: which drop (if any) is worth going for, where to stand while it is still falling, and how to stay inside
the ring while capturing. Does NOT own: pathing (nav routes the goal), fighting (aim/engage), the zone (zone.py; we
only refuse drops the zone will cover), take/drop (loot).

Usage inside a bot:

    planner = drops.DropPlanner(hello, params.get("drops"))
    dd = planner.step(obs, zone_plan=zp, world=self.world, path_cost=nav.path_cost)   # never raises
    if dd.goal is not None: ...                                 # hand to the arbiter (see DropDecision)

Every number is in DropParams (-> params.json["drops"]).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, fields
from typing import Callable, Dict, List, Optional, Sequence, Tuple


@dataclass
class DropParams:
    enabled: bool = True
    max_dist_m: float = 280.0          # ignore drops farther than this (path metres)
    late_s: float = 30.0               # go if we arrive no later than this after it lands (others may take it)
    early_s: float = 4.0               # don't arrive more than this before it lands: wait at the standoff
    standoff_m: float = 22.0           # wait this far from the ring centre while it falls
    ring_inner_frac: float = 0.5       # while capturing, stay within this fraction of the ring radius
    ring_enter_frac: float = 0.8       # we count as "in the ring" inside this fraction (server ring = 1.0)
    min_utility: float = 0.35          # go only if utility is above this
    value_base: float = 0.6            # utility of 3 cubes + refill at full HP
    value_heal: float = 1.2            # + this x missing-HP fraction (a drop is the fastest heal there is)
    time_cost_per_s: float = 0.012     # utility lost per second of travel
    exposure_cost: float = 0.25        # utility lost per unit of nav path exposure (0..1)
    threat_radius_m: float = 55.0      # enemies this close to the ring make it a fight, not a pickup
    self_threat_radius_m: float = 120.0  # main (v1, 2.92): no drop run while a seen enemy is this close to us
                                         # (an ongoing capture is kept; 0 = off)
    threat_cost: float = 0.45          # utility lost per enemy near the ring (seen / recent contacts)
    unseen_cost: float = 0.15          # utility lost per unit of perception's unseen mass near the ring
    contested_cost: float = 0.6        # another mech is the holder (capturing it right now)
    contested_close_m: float = 45.0    # ... unless we are already this close (our entry freezes their clock)
    stall_s: float = 3.0               # inside the ring this long with no progress: someone shares it, give up
    retry_s: float = 10.0              # after giving up on a drop, ignore it this long
    zone_margin_m: float = 4.0         # ring must sit this far inside the circle at arrival and capture end
    preempt_regen: bool = True         # a capturable drop beats standing still to regen
    preempt_retreat_m: float = 30.0    # ... and beats a retreat when the ring is this close and no threat is near it
    boost_late_s: float = 6.0          # boost when arriving later than this after landing
    detour: float = 1.0                # path length / straight line when no path_cost is given

    @classmethod
    def from_dict(cls, d: Optional[dict]) -> "DropParams":
        p = cls()
        for f in fields(cls):
            if isinstance(d, dict) and f.name in d:
                cur = getattr(p, f.name)
                try:
                    setattr(p, f.name, bool(d[f.name]) if isinstance(cur, bool) else type(cur)(d[f.name]))
                except Exception:
                    pass
        return p


@dataclass
class DropDecision:
    goal: Optional[Tuple[float, float, float]] = None   # where to walk (nav routes it); None = no opinion
    drop_id: Optional[int] = None
    phase: str = "none"            # none | approach | wait | capture
    move: Optional[Tuple[float, float]] = None   # capture only: in-ring move that keeps us inside (len <= 1)
    hold: bool = False             # wait/capture: standing still is fine (default_goal for nav)
    boost: bool = False
    utility: float = 0.0
    preempt_regen: bool = False
    preempt_retreat: bool = False
    preempt_fight: bool = False
    reason: str = ""


def _circle_at(z: dict, t: float) -> Tuple[float, float, float]:
    """Zone circle at time t from obs.zone (linear shrink from current to next)."""
    c, r = z["center"], float(z["radius"])
    nc, nr = z.get("next_center") or c, float(z.get("next_radius", r))
    s0, s1 = float(z.get("shrink_start", 1e9)), float(z.get("shrink_end", 1e9))
    if t <= s0 or s1 <= s0:
        return float(c[0]), float(c[1]), r
    f = min(1.0, (t - s0) / (s1 - s0))
    return c[0] + (nc[0] - c[0]) * f, c[1] + (nc[1] - c[1]) * f, r + (nr - r) * f


class DropPlanner:
    def __init__(self, hello: Optional[dict] = None, params: Optional[dict] = None):
        self.p = DropParams.from_dict(params)
        cfg = (hello or {}).get("config") or {}
        self.my_id = (hello or {}).get("slot")
        dc = cfg.get("drops") or {}
        self.capture_s = float(dc.get("capture_s", 4.0))
        self.radius = float(dc.get("radius", 8.0))
        self.walk_speed = float((cfg.get("mech") or {}).get("walk_speed", 11.7))
        self.call_times = tuple(dc.get("times") or (70, 140, 210))
        self.fall_s = float(dc.get("fall_s", 25))
        self.drop_numbers: Dict[int, int] = {}
        self.ignore_until: Dict[int, float] = {}
        self.taken: set = set()
        self.cur_id: Optional[int] = None
        self.in_ring_since: Optional[float] = None
        self.last_progress = 0.0
        self.last_progress_t = 0.0

    # ------------------------------------------------------------------ public
    def step(self, obs: dict, zone_plan=None, world=None,
             path_cost: Optional[Callable] = None, *, push=False, terrain=None) -> DropDecision:
        if not self.p.enabled:
            return DropDecision(reason="off")
        try:
            return self._step(obs, zone_plan, world, path_cost, push, terrain)
        except Exception as e:  # never let drops stall or crash a tick
            return DropDecision(reason="error:" + type(e).__name__)

    def debug_label(self, d: DropDecision) -> str:
        return "" if d.goal is None else f"drop {d.drop_id} {d.phase} u={d.utility:.2f}"

    # ------------------------------------------------------------------ internals
    def _threats_near(self, obs, world, x, y) -> Tuple[int, float]:
        """(enemies near the point, unseen mass near it)."""
        r = self.p.threat_radius_m
        n, mass = 0, 0.0
        if world is not None:
            for c in getattr(world, "contacts", None) or []:
                if getattr(c, "src", "") in ("seen", "recent") and (getattr(c, "conf", 1.0) or 0) > 0.3:
                    if math.hypot(c.pos[0] - x, c.pos[1] - y) < r:
                        n += 1
            try:
                mass = float(world.threat_at(x, y, r) or 0.0)
            except Exception:
                mass = 0.0
            return n, mass
        for m in obs.get("mechs") or []:
            if m.get("kind") == "mech" and math.hypot(m["pos"][0] - x, m["pos"][1] - y) < r:
                n += 1
        return n, 0.0

    def _zone_ok(self, z: Optional[dict], dp, t_arrive: float, t_done: float, ring_r: float) -> bool:
        if not z:
            return True
        for tt in (t_arrive, t_done):
            cx, cy, cr = _circle_at(z, tt)
            if math.hypot(dp[0] - cx, dp[1] - cy) > cr - ring_r * 0.5 - self.p.zone_margin_m:
                return False
        nc = z.get("next_center")
        if nc is not None and math.hypot(dp[0] - nc[0], dp[1] - nc[1]) > float(z.get("next_radius", 1e9)) - self.p.zone_margin_m:
            return False
        return True

    def _push_route(self, me, dp, ring, terrain, nearby, at_ring, holder, eta, cap_left):
        """Allow a covered approach or a short contest against one weaker mech."""
        x, y = me["pos"][:2]
        dist = math.hypot(dp[0] - x, dp[1] - y)
        rivals = {e["id"]: e for e in nearby + at_ring}
        if at_ring or holder is not None:
            rival = next(iter(rivals.values())) if len(rivals) == 1 else None
            hp = me.get("hp", 0)
            favorable = (rival is not None and (holder is None or holder == rival["id"])
                         and rival.get("hp") is not None and hp >= 1.25 * rival["hp"]
                         and hp >= 0.6 * me.get("max_hp", 1))
            can_enter = holder is None or eta - ring / self.walk_speed <= max(0.0, cap_left)
            return False, favorable and can_enter and dist <= 110.0
        if not nearby or terrain is None or dist <= ring:
            return False, False
        scale = min(1.0, 16.0 / dist)
        sx, sy = x + (dp[0] - x) * scale, y + (dp[1] - y) * scale
        covered = (terrain.ray_free(x, y, sx, sy)
                   and all(not terrain.los(*e["pos"][:2], sx, sy)
                           and not terrain.los(*e["pos"][:2], dp[0], dp[1]) for e in nearby))
        return covered, False

    def _step(self, obs, zone_plan, world, path_cost, push, terrain) -> DropDecision:
        p = self.p
        t = float(obs.get("t", 0.0))
        me = obs["self"]
        x, y, z = me["pos"]
        my_id = me.get("id", self.my_id)
        hpf = float(me.get("hp", 1)) / max(float(me.get("max_hp", 1) or 1), 1.0)
        st = me.get("stats") or {}
        speed = float(st.get("walk_speed", self.walk_speed)) or self.walk_speed
        for ev in obs.get("events") or []:
            if ev.get("type") == "drop" and ev.get("id") is not None:
                self.taken.add(ev["id"])
        zone = obs.get("zone")
        available = obs.get("drops") or ()
        if push:
            for dr in available:
                did, lands_in = dr["id"], dr.get("lands_in", 0)
                if did not in self.drop_numbers and lands_in > 0:
                    called = t + lands_in - self.fall_s
                    self.drop_numbers[did] = next(
                        (number for number, call in enumerate(self.call_times, 1) if abs(call - called) < 1), 0)
        # the zone tracker's urgency is the authority: never pull us away when the edge is critical
        if zone_plan is not None and getattr(zone_plan, "urgency", 0) >= 3:
            self._reset()
            return DropDecision(reason="zone critical")

        nearby = []
        if p.self_threat_radius_m > 0:
            for m in obs.get("mechs") or []:
                if m.get("kind") == "mech" and math.hypot(m["pos"][0] - x, m["pos"][1] - y) < p.self_threat_radius_m:
                    nearby.append(m)

        best = None
        for dr in available:
            did = dr.get("id")
            if did in self.taken or self.ignore_until.get(did, -1) > t:
                continue
            dp = dr["pos"]
            ring = float(dr.get("radius", self.radius))
            lands_in = max(0.0, float(dr.get("lands_in", 0.0)))
            euclid = math.hypot(dp[0] - x, dp[1] - y)
            plen, expo = euclid * p.detour, 0.0        # no path cost: assume a typical detour
            if path_cost is not None:
                try:
                    pl, expo = path_cost((x, y, z), (dp[0], dp[1], dp[2]))
                    if pl is None:
                        continue                          # unreachable on foot
                    plen = max(float(pl), euclid)
                    expo = float(expo or 0.0)
                except Exception:
                    plen, expo = euclid * 1.25, 0.0
            number = self.drop_numbers.get(did, 0) if push else 0
            reach_bonus = 90.0 if number == 2 else 145.0 if number == 3 else 0.0
            if plen > p.max_dist_m + reach_bonus:
                continue
            eta = plen / speed
            late = eta - lands_in                       # >0: we arrive after it lands
            if late > p.late_s:
                continue
            cap = float(dr.get("capture_s", self.capture_s))
            prog = float(dr.get("progress", 0.0) or 0.0)
            t_arrive = t + max(eta, lands_in)
            if not self._zone_ok(zone, dp, t_arrive, t_arrive + cap - (prog if dr.get("holder") == my_id else 0.0), ring):
                continue
            n_thr, mass = self._threats_near(obs, world, dp[0], dp[1])
            u = p.value_base + p.value_heal * (1.0 - hpf)
            u -= p.time_cost_per_s * max(eta, lands_in) + p.exposure_cost * expo
            u -= p.threat_cost * n_thr + p.unseen_cost * mass
            holder = dr.get("holder")
            cover_route = contest = False
            if reach_bonus:
                ring_enemies = [e for e in obs.get("mechs", ()) if e["kind"] == "mech"
                                and math.hypot(e["pos"][0] - dp[0], e["pos"][1] - dp[1]) < p.threat_radius_m]
                rival_holder = holder if holder != my_id else None
                cover_route, contest = self._push_route(me, dp, ring, terrain, nearby, ring_enemies,
                                                        rival_holder, eta, cap - prog)
                if contest or (not n_thr and rival_holder is None):
                    u += 0.32 if number == 2 else 0.52
                if contest:
                    u += p.threat_cost * n_thr
            if holder is not None and holder != my_id and euclid > p.contested_close_m and not contest:
                u -= p.contested_cost
            if did == self.cur_id:
                u += 0.1                                 # hysteresis: don't flip between drops
            capturing_this = (dr.get("holder") == my_id and lands_in <= 0.0
                              and euclid < float(dr.get("radius", self.radius)) * p.ring_enter_frac)
            if nearby and not (capturing_this or cover_route or contest):
                continue
            if best is None or u > best[0]:
                best = (u, dr, eta, lands_in, n_thr, euclid, cover_route, contest)

        if best is None or best[0] < p.min_utility:
            self._reset()
            return DropDecision(reason="none worth it" if best else "no drops",
                                utility=best[0] if best else 0.0)

        u, dr, eta, lands_in, n_thr, euclid, cover_route, contest = best
        did, dp = dr["id"], dr["pos"]
        ring = float(dr.get("radius", self.radius))
        if did != self.cur_id:
            self.cur_id, self.in_ring_since = did, None
            self.last_progress, self.last_progress_t = 0.0, t
        dd = DropDecision(drop_id=did, utility=u)
        dd.preempt_fight = cover_route or contest
        dd.preempt_regen = p.preempt_regen
        dd.preempt_retreat = euclid < p.preempt_retreat_m and n_thr == 0

        landed = lands_in <= 0.0
        in_ring = euclid < ring * p.ring_enter_frac
        if landed and in_ring:
            # ---- capture: stay in the ring; give up if the clock is frozen (someone shares the ring)
            prog = float(dr.get("progress", 0.0) or 0.0)
            if self.in_ring_since is None:
                self.in_ring_since = t
                self.last_progress, self.last_progress_t = prog, t   # the clock may have restarted since last time
            if prog > self.last_progress + 1e-6 and dr.get("holder") == my_id:
                self.last_progress_t = t
            self.last_progress = prog                              # a restart (prog drops) re-bases, not a stall
            stall_s = max(p.stall_s, 6.0) if contest else p.stall_s
            if t - self.last_progress_t > stall_s and t - self.in_ring_since > stall_s:
                self.ignore_until[did] = t + p.retry_s
                self._reset()
                return DropDecision(reason="stalled", utility=u)
            dd.phase = "capture"
            dd.goal = (dp[0], dp[1], dp[2])
            dd.hold = True
            inner = ring * p.ring_inner_frac
            if euclid > inner:
                k = min(1.0, (euclid - inner) / max(ring - inner, 0.5) + 0.3)
                dd.move = ((dp[0] - x) / euclid * k, (dp[1] - y) / euclid * k)
            else:
                dd.move = (0.0, 0.0)
            dd.reason = f"capturing {dr.get('progress', 0)}/{dr.get('capture_s', self.capture_s)}"
            return dd

        self.in_ring_since = None
        if not landed and eta < lands_in - p.early_s:
            # ---- wait: too early. Stand off on our side of the ring (inside the zone) instead of in the open centre
            dd.phase = "wait"
            if euclid > p.standoff_m + 2:
                k = p.standoff_m / euclid
                dd.goal = (dp[0] + (x - dp[0]) * k, dp[1] + (y - dp[1]) * k, dp[2])
            else:
                dd.goal = (x, y, z)
            dd.hold = True
            dd.reason = f"wait lands_in={lands_in:.1f}"
            return dd

        dd.phase = "approach"
        dd.goal = (dp[0], dp[1], dp[2])
        dd.boost = (eta - lands_in) > p.boost_late_s or (landed and dr.get("holder") not in (None, my_id))
        dd.reason = f"approach eta={eta:.1f} lands_in={lands_in:.1f}"
        return dd

    def _reset(self):
        self.cur_id, self.in_ring_since = None, None
