"""engage.py: H-ENG (fight-or-flee) and H-REG (retreat-and-regen) for the Mech Royale bot.

Pure standard library. Owns ONE decision: should we shoot at the thing in front of us,
or break contact and heal. It does not aim, strafe, path-find or pick loot; it returns a
`Decision` that the integrator merges with the other components' output.

Pieces
------
* `simulate_fight`   expected-value fight sim (0.1 s steps) with the weapon triangle,
                     rear-armor windows, reloads/charges, joiners and third-party hazard.
* `Engagement`       per-tick state machine: NEUTRAL -> ENGAGE -> RETREAT -> REGEN.
* `Occluder`         optional 2-D prism + terrain line-of-sight, for finding cover.
* `PARAMS`           every threshold, with a one-line doc. Override via params.json["engage"].

Integration
-----------
    eng = Engagement(hello, params=load_params("params.json"), occluder=Occluder("/arena"))
    d = eng.update(obs)           # once per observation, < ~8 ms typical
    # d.mode, d.target, d.goal, d.move, d.speed, d.boost, d.aim_yaw, d.hold_fire, d.reload, d.diag
"""
from __future__ import annotations

import array
import json
import math
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

# --------------------------------------------------------------------------------------
# Knobs. Everything tunable lives here; params.json["engage"] overrides by key.
# --------------------------------------------------------------------------------------
PARAMS: Dict[str, Any] = {
    # ---- estimator: hit rates (fraction of nominal shots that land on a moving mech) ----
    "hit_gun": 0.50,            # my gun accuracy vs a strafing mech (AIM chat should replace with measured)
    "hit_laser": 0.55,          # laser is hitscan but charge line is visible/dodgeable
    "hit_mortar_direct": 0.15,  # direct hit on a moving mech is rare
    "hit_mortar_splash": 0.55,  # near-miss splash (landing within splash_radius)
    "hit_lightning": 0.90,      # instant, cone 30 deg, only needs range + LOS
    "enemy_skill": 1.0,         # multiplies every enemy hit rate. PRACTICE: house bots may be >1; FINAL: peers ~1
    "enemy_pad_per_offer": 0.04,  # unseen upgrades: +4% enemy HP and +4% enemy damage per upgrade offer implied by their cubes
    "reaction_s": 0.25,         # enemy time-to-react before it starts hitting us once it can
    "distracted_after_s": 0.6,  # enemy has had its back to us this long without turning -> it is locked on something else
    "distracted_bonus_s": 2.0,  # ...then assume x1.5 rear hits for this much longer (H-ENG rear-armor opportunity)
    "mortar_vs_lightning": 0.5,  # concussion makes lightning ~half as effective in either direction
    "mortar_min_range": 10.0,   # inside this, mortar self-splash/knock makes it ~useless
    "self_stats_include_cube": False,  # do self.weapons[i].stats already include cube damage? (UNVERIFIED, see ENGAGE.md)
    # ---- estimator: fight context ----
    "threat_radius": 200.0,     # enemies farther than this are ignored by the estimator
    "join_radius": 110.0,       # other mechs inside this may join a fight on `target`
    "join_weight": 0.5,         # their damage is scaled by this (they may not engage)
    "third_party_dps": 14.0,    # extra incoming HP/s from unseen arrivals at alive==16, scales with (alive-1)/15
    "horizon_s": 60.0,          # fight sim horizon (a 50%-accurate gun-only duel takes ~25-30 s); unfinished fights are extrapolated
    "dt": 0.2,                  # sim step; shots are event-scheduled so dt only quantises death detection
    "npc_hit": 0.5,
    "target_max": 3,            # candidate targets evaluated per tick (nearest + lowest-HP)
    # ---- fight-or-flee thresholds ----
    "engage_ratio": 1.40,       # R = my_effective_HP / damage_taken_to_kill_everyone. Start fight at >= this
    "disengage_ratio": 1.00,    # leave a fight when R drops below this (hysteresis gap vs engage_ratio)
    "early_alive": 11,          # while alive >= this, fights are net-negative (attract third parties): raise bar
    "early_ratio_add": 0.30,
    "late_alive": 3,            # with this few mechs left, avoiding the fight only delays it (zone is closing)
    "late_ratio_mult": 0.80,    # ...so scale the engage bar by this
    "kill_value_per_cube": 0.05,  # a kill drops (cubes+2) and weapons: lower the bar by this per dropped cube
    "kill_value_cap": 0.25,
    "min_engage_hp_frac": 0.50,  # never START a fight below this HP fraction
    "retreat_hp_frac": 0.30,     # hard floor: below this HP fraction, flee unless finishing
    "escape_margin": 0.60,       # retreat early enough to survive the escape: hp <= cost*(1+margin)+reserve
    "escape_reserve_hp": 120.0,
    "default_escape_s": 3.0,     # time to break LOS if no map info
    "finish_ttk_s": 1.2,         # if I kill the target within this and survive, ignore the retreat trigger
    "finish_survive_frac": 0.8,  # ...and expected damage taken < this * my HP
    "min_fight_s": 1.0,          # anti-thrash: stay in ENGAGE at least this long (unless HP floor)
    "retreat_lockout_s": 4.0,    # after retreating, do not re-engage that target for this long
    "cornered_ratio": 0.55,      # pursued and still R >= this -> turn and fight instead of running forever
    "pursuit_giveup_s": 6.0,     # running this long with the nearest threat not receding -> "pursued"
    "phantom_dist": 90.0,        # unseen shooter assumed this far along `damaged.bearing`
    "phantom_ttl": 6.0,
    "phantom_retreat": True,    # shot by something unseen with no visible target: break LOS (False: leave to Perception/Move)
    "avoid_ratio": 0.60,        # neutral + a visible mech this close with R below this: break contact before it starts
    "avoid_dist": 100.0,        # ...only if that mech is within this many metres (0 or avoid_ratio 0 disables)
    "auto_regen": True,         # neutral, nothing in view, HP < heal_before_roam_frac: hide (or hold still) and heal
    "cover_memory_s": 30.0,     # last-known threat position is used to pick a hiding spot for this long
    "cover_walk_max_s": 6.0,
    "regen_unseen_s": 0.6,      # must have been out of every enemy's sight this long before standing still to heal
    "bad_spot_ttl_s": 20.0,     # a refuge that turned out visible is avoided for this long
    "bad_spot_radius": 15.0,
    "w_bad": 3.0,               # cost: refuge near a spot that failed    # walk to a refuge at most this long when no threat is in view
    # ---- regen / retreat ----
    "regen_resume_frac": 0.85,   # leave REGEN at this HP fraction
    "regen_max_wait_s": 45.0,
    "heal_before_roam_frac": 0.60,  # neutral + no threats + below this: ask integrator to hide-and-heal
    "refuge_headings": 12,
    "refuge_rings": (12.0, 24.0, 40.0),
    "refuge_budget_ms": 6.0,     # hard cap on cover search time per replan (best-so-far is used)
    "replan_s": 0.5,
    "commit_s": 1.5,             # keep a refuge goal at least this long unless it stops being hidden
    "w_hidden": 3.0,             # reward: fraction of threats with no LOS to the refuge
    "w_gain": 1.0,               # reward: distance gained from threats (normalised by ring radius)
    "w_travel": 0.8,             # cost: travel seconds
    "w_path": 1.0,               # cost: refuge path midpoint visible to a threat
    "w_zone": 2.0,               # cost: refuge outside next zone circle (per 100 m excess)
    "zone_margin": 12.0,
    "clear_dist": 45.0,          # beyond this (> step sound range 40 m) from all last-known threats: walk, don't boost
    "boost_min_energy": 22.0,
    "slip_speed": 4.4,           # m/s once clear (< sound.step_speed 5 m/s = silent)
    "reload_safe_dist": 80.0,    # reload in REGEN only if last-known threat is farther than this (reload sound 60 m)
    "retreat_face_threat": True,  # aim at nearest threat while backing off (legs are independent): keeps front armor to them
    "retreat_cover_fire": False,  # fire while retreating? (resets my regen timer, so default off)
    "ambush_range": 0.0,         # REGEN: if >0, a lone enemy walking into this range in front arc may be shot (re-runs estimator)
    "zone_leave_margin_s": 8.0,  # leave REGEN this early before our spot leaves the next circle
}

PROFILES = {
    # LOCAL SIM ONLY (env MECH_PROFILE or profile=). The submitted image is one config for practice AND final, so the
    # defaults above must be the robust choice; this table only lets H-SIM replay the practice structure
    # (15 hunters converge on us) to see how far the knobs move. See ENGAGE.md "Practice vs final".
    "practice": {"third_party_dps": 22.0, "join_weight": 0.8, "early_alive": 99},
    "final": {},
}


def params_from_dict(d: Optional[Dict[str, Any]] = None, profile: Optional[str] = None) -> Dict[str, Any]:
    """Defaults + partial override from params.json["engage"]. Unknown keys and wrong-typed values are ignored."""
    p = dict(PARAMS)
    prof = profile or os.environ.get("MECH_PROFILE")
    if prof in PROFILES:
        p.update(PROFILES[prof])
    for key, val in (d or {}).items():
        if key not in PARAMS or key.startswith("_"):
            continue
        dflt = PARAMS[key]
        try:
            if isinstance(dflt, bool):
                p[key] = bool(val)
            elif isinstance(dflt, tuple):
                p[key] = tuple(float(x) for x in val)
            elif isinstance(dflt, (int, float)):
                p[key] = type(dflt)(val) if not isinstance(val, bool) else dflt
        except (TypeError, ValueError):
            pass
    return p


def load_params(path: Optional[str] = None, profile: Optional[str] = None) -> Dict[str, Any]:
    p = dict(PARAMS)
    prof = profile or os.environ.get("MECH_PROFILE")
    if prof in PROFILES:
        p.update(PROFILES[prof])
    if path and os.path.exists(path):
        try:
            with open(path) as f:
                blob = json.load(f)
            p.update(blob.get("engage", {}))
        except Exception:
            pass
    return p


# --------------------------------------------------------------------------------------
# Small math helpers
# --------------------------------------------------------------------------------------
def wrap(a: float) -> float:
    while a > math.pi:
        a -= 2 * math.pi
    while a < -math.pi:
        a += 2 * math.pi
    return a


def dist2(a: Sequence[float], b: Sequence[float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def bearing(a: Sequence[float], b: Sequence[float]) -> float:
    return math.atan2(b[1] - a[1], b[0] - a[0])


# --------------------------------------------------------------------------------------
# Occluder: LOS against building/bridge/stadium prisms and terrain
# --------------------------------------------------------------------------------------
class Occluder:
    """2-D polygon + height line-of-sight. Load once in the ready window (~30 ms for 259 prisms)."""

    CELL = 40.0

    def __init__(self, map_dir: str):
        wpath = os.path.join(map_dir, "v2", "world.json")
        with open(wpath) as f:
            w = json.load(f)
        self.prisms: List[Tuple[float, float, float, float, List[Tuple[float, float]], List[List[Tuple[float, float]]], float, float]] = []
        for p in w["prisms"]:
            ring = [(p["ring"][i], p["ring"][i + 1]) for i in range(0, len(p["ring"]), 2)]
            holes = []
            for h in p.get("holes") or []:
                holes.append([(h[i], h[i + 1]) for i in range(0, len(h), 2)])
            xs = [q[0] for q in ring]
            ys = [q[1] for q in ring]
            self.prisms.append((min(xs), min(ys), max(xs), max(ys), ring, holes, float(p["base"]), float(p["top"])))
        self.grid: Dict[Tuple[int, int], List[int]] = {}
        for i, pr in enumerate(self.prisms):
            for cx in range(int(pr[0] // self.CELL), int(pr[2] // self.CELL) + 1):
                for cy in range(int(pr[1] // self.CELL), int(pr[3] // self.CELL) + 1):
                    self.grid.setdefault((cx, cy), []).append(i)
        t = w["terrain"]
        self.tminx, self.tminy, self.tstep, self.tnx, self.tny = t["minX"], t["minY"], t["step"], t["nx"], t["ny"]
        self.terrain: Optional[array.array] = None
        tpath = os.path.join(map_dir, "v2", t.get("file", "terrain.i16"))
        try:
            arr = array.array("h")
            with open(tpath, "rb") as f:
                arr.fromfile(f, self.tnx * self.tny)
            self.terrain = arr
        except Exception:
            self.terrain = None

    # ground height (nearest vertex; fine for LOS and refuge z)
    def ground(self, x: float, y: float) -> float:
        if self.terrain is None:
            return 0.0
        i = int(round((x - self.tminx) / self.tstep))
        j = int(round((y - self.tminy) / self.tstep))
        if i < 0 or j < 0 or i >= self.tnx or j >= self.tny:
            return 0.0
        return self.terrain[j * self.tnx + i] * 0.01

    def walkable(self, x: float, y: float) -> bool:
        """Cheap: inside map and not inside a prism footprint at ground level."""
        if self.terrain is not None:
            i = int(round((x - self.tminx) / self.tstep))
            j = int(round((y - self.tminy) / self.tstep))
            if i < 1 or j < 1 or i >= self.tnx - 1 or j >= self.tny - 1:
                return False
        g = self.ground(x, y)
        for idx in self.grid.get((int(x // self.CELL), int(y // self.CELL)), ()):
            pr = self.prisms[idx]
            if pr[6] <= g + 1.2 and pr[7] > g + 1.2 and _in_prism_xy(pr, x, y):
                return False
        return True

    def los(self, a: Sequence[float], b: Sequence[float]) -> bool:
        """True if the segment a->b (x,y,z) is not blocked by a prism or terrain."""
        ax, ay, az = a[0], a[1], a[2]
        bx, by, bz = b[0], b[1], b[2]
        length = math.hypot(bx - ax, by - ay)
        if length < 1e-6:
            return True
        # candidate prisms from cells along the segment
        cand = set()
        n = max(1, int(length / (self.CELL * 0.5)))
        for k in range(n + 1):
            t = k / n
            x = ax + (bx - ax) * t
            y = ay + (by - ay) * t
            cand.update(self.grid.get((int(x // self.CELL), int(y // self.CELL)), ()))
        for idx in cand:
            pr = self.prisms[idx]
            if max(ax, bx) < pr[0] or min(ax, bx) > pr[2] or max(ay, by) < pr[1] or min(ay, by) > pr[3]:
                continue
            if _segment_blocked(pr, ax, ay, az, bx, by, bz):
                return False
        if self.terrain is not None:
            steps = max(2, int(length / 4.0))
            for k in range(1, steps):
                t = k / steps
                x = ax + (bx - ax) * t
                y = ay + (by - ay) * t
                if az + (bz - az) * t < self.ground(x, y) + 0.3:
                    return False
        return True


def _in_poly(poly: List[Tuple[float, float]], x: float, y: float) -> bool:
    inside = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi:
            inside = not inside
        j = i
    return inside


def _in_prism_xy(pr, x: float, y: float) -> bool:
    if x < pr[0] or x > pr[2] or y < pr[1] or y > pr[3]:
        return False
    if not _in_poly(pr[4], x, y):
        return False
    for h in pr[5]:
        if _in_poly(h, x, y):
            return False
    return True


def _seg_edge_ts(poly, ax, ay, bx, by, out: List[float]) -> None:
    dx, dy = bx - ax, by - ay
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        ex, ey = x2 - x1, y2 - y1
        den = dx * ey - dy * ex
        if abs(den) < 1e-12:
            continue
        t = ((x1 - ax) * ey - (y1 - ay) * ex) / den
        u = ((x1 - ax) * dy - (y1 - ay) * dx) / den
        if 0.0 <= t <= 1.0 and 0.0 <= u <= 1.0:
            out.append(t)


def _segment_blocked(pr, ax, ay, az, bx, by, bz) -> bool:
    ts = [0.0, 1.0]
    _seg_edge_ts(pr[4], ax, ay, bx, by, ts)
    for h in pr[5]:
        _seg_edge_ts(h, ax, ay, bx, by, ts)
    ts.sort()
    for k in range(len(ts) - 1):
        if ts[k + 1] - ts[k] < 1e-9:
            continue
        tm = 0.5 * (ts[k] + ts[k + 1])
        x = ax + (bx - ax) * tm
        y = ay + (by - ay) * tm
        if _in_prism_xy(pr, x, y):
            z = az + (bz - az) * tm
            if pr[6] <= z <= pr[7]:
                return True
    return False


# --------------------------------------------------------------------------------------
# Fight simulation (expected value, 0.1 s steps)
# --------------------------------------------------------------------------------------
@dataclass
class Gun:
    dmg: float
    cd: float
    mag: int
    reload: float
    hit: float
    ammo: Optional[int] = None
    reload_left: float = 0.0
    kind: str = "gun"

    def schedule(self, start: float):
        # returns generator of (time, damage-before-mult) shot events
        t = start + self.reload_left
        ammo = self.mag if self.ammo is None else self.ammo
        if ammo <= 0:
            ammo = self.mag
            t = start + max(self.reload_left, self.reload)
        while True:
            yield t, self.dmg * self.hit
            ammo -= 1
            t += self.cd
            if ammo <= 0:
                ammo = self.mag
                t += self.reload


@dataclass
class Laser:
    dmg: float
    charge: float
    cd: float
    hit: float
    cookoff: float = 1.0
    kind: str = "laser"

    def schedule(self, start: float):
        t = start + self.charge
        while True:
            yield t, self.dmg * self.hit * self.cookoff
            t += self.charge + self.cd


@dataclass
class Lightning:
    dmg: float
    cd: float
    hit: float
    factor: float = 1.0
    kind: str = "lightning"

    def schedule(self, start: float):
        t = start
        while True:
            yield t, self.dmg * self.hit * self.factor
            t += self.cd


@dataclass
class Mortar:
    direct: float
    splash: float
    cd: float
    p_direct: float
    p_splash: float
    factor: float = 1.0
    kind: str = "mortar"

    def schedule(self, start: float):
        t = start
        while True:
            yield t, (self.direct * self.p_direct + self.splash * self.p_splash) * self.factor
            t += self.cd


@dataclass
class NpcGun:
    dmg: float
    cd: float
    hit: float
    kind: str = "npc"

    def schedule(self, start: float):
        t = start
        while True:
            yield t, self.dmg * self.hit
            t += self.cd


@dataclass
class Side:
    """One combatant in the sim. `weapons` fire at the opposing side."""
    id: Any
    hp: float                    # effective HP in raw-damage units
    weapons: List[Any]
    start: List[float]           # per-weapon first-fire time
    rear_window: float = 0.0     # seconds during which MY hits on THIS side are x rear_mult
    rear_on_me: float = 0.0      # seconds during which THIS side's hits on ME are x rear_mult
    weight: float = 1.0          # scales damage dealt by this side (joiners)
    is_target: bool = False


@dataclass
class FightResult:
    ttk_target: float            # time to kill the focus target (inf if never)
    ttk_all: float               # time to kill everyone in the fight (inf if never)
    damage_taken: float          # raw damage taken until everyone dead (or horizon), as if immortal
    my_hp_left: float            # my effective HP after that (may be negative = I'd have died)
    died_at: float               # time I'd die (inf if never)
    ratio: float                 # R = my_ehp / damage_taken (capped)
    taken_at_target: float = 0.0  # damage taken by the moment the focus target dies
    curve: List[Tuple[float, float]] = field(default_factory=list)  # (t, my ehp) coarse, for debug


def simulate_fight(my_ehp: float, my_weapons: List[Any], my_start: List[float], enemies: List[Side],
                   rear_mult: float, extra_dps: float, horizon: float,
                   dt: float = 0.1, focus_order: Optional[List[int]] = None, ratio_cap: float = 99.0) -> FightResult:
    """Expected-value duel/skirmish. I focus enemies in `focus_order` (indices into `enemies`)."""
    n = len(enemies)
    order = focus_order if focus_order is not None else list(range(n))
    hp = [e.hp for e in enemies]
    hp0 = sum(hp)
    alive = [True] * n
    my_iters = [w.schedule(s) for w, s in zip(my_weapons, my_start)]
    my_next = [next(it) for it in my_iters]
    en_iters: List[List[Any]] = []
    en_next: List[List[Any]] = []
    for e in enemies:
        its = [w.schedule(s) for w, s in zip(e.weapons, e.start)]
        en_iters.append(its)
        en_next.append([next(it) for it in its])
    taken = 0.0
    taken_at_target: Optional[float] = None
    died_at = math.inf
    ttk_target = math.inf
    ttk_all = math.inf
    t = 0.0
    curve: List[Tuple[float, float]] = []
    steps = int(horizon / dt)
    for step in range(steps):
        t1 = t + dt
        # me -> focus enemy
        focus = next((i for i in order if alive[i]), None)
        if focus is None:
            ttk_all = t
            break
        for k in range(len(my_weapons)):
            while my_next[k][0] < t1:
                te, dm = my_next[k]
                if focus is not None and alive[focus]:
                    mult = rear_mult if te < enemies[focus].rear_window else 1.0
                    hp[focus] -= dm * mult
                    if hp[focus] <= 0:
                        alive[focus] = False
                        if enemies[focus].is_target and ttk_target == math.inf:
                            ttk_target = te
                        focus = next((i for i in order if alive[i]), None)
                        if focus is None:
                            break
                my_next[k] = next(my_iters[k])
            if focus is None:
                break
        if focus is None and all(not a for a in alive):
            ttk_all = t1
        # enemies -> me
        for i, e in enumerate(enemies):
            if not alive[i]:
                continue
            for k in range(len(e.weapons)):
                while en_next[i][k][0] < t1:
                    te, dm = en_next[i][k]
                    mult = rear_mult if te < e.rear_on_me else 1.0
                    taken += dm * mult * e.weight
                    en_next[i][k] = next(en_iters[i][k])
        taken += extra_dps * dt * (1.0 if any(alive) else 0.0)
        if ttk_target != math.inf and taken_at_target is None:
            taken_at_target = taken
        t = t1
        if died_at == math.inf and taken >= my_ehp:
            died_at = t
        if step % 5 == 0:
            curve.append((round(t, 2), my_ehp - taken))
        if ttk_all != math.inf:
            break
    my_left = my_ehp - taken
    ratio = ratio_cap if taken < 1.0 else min(ratio_cap, my_ehp / taken)
    if ttk_all == math.inf:
        # not finished inside the horizon: extrapolate damage-per-HP-removed so R still orders fights sensibly
        progress = 1.0 - max(0.0, sum(max(0.0, h) for h in hp)) / max(hp0, 1.0)
        ratio = 0.05 if progress < 0.05 else min(ratio, my_ehp * progress / max(taken, 1.0), 0.95)
    return FightResult(ttk_target, ttk_all, taken, my_left, died_at, ratio,
                       taken_at_target if taken_at_target is not None else taken, curve)


# --------------------------------------------------------------------------------------
# Building Sides from observations
# --------------------------------------------------------------------------------------
def _cube_mult(cfg: Dict[str, Any], cubes: float) -> float:
    c = cfg["cubes"]
    return 1.0 + c["damage_per_cube"] * min(cubes, c["stat_cap"])


def _offers(cfg: Dict[str, Any], cubes: int) -> int:
    return sum(1 for th in cfg["cubes"]["upgrade_thresholds"] if cubes >= th)


def _angle_gap(aim_yaw: float, from_pos: Sequence[float], to_pos: Sequence[float]) -> float:
    """Absolute angle between a torso aim and the bearing to a point."""
    return abs(wrap(bearing(from_pos, to_pos) - aim_yaw))


def rear_window(attacker_pos, defender_pos, defender_aim_yaw: float, defender_turn_rate: float,
                front_arc_deg: float, reaction_s: float) -> float:
    """Seconds for which the defender's back/side stays toward the attacker.

    Defender's front arc is +-front_arc/2 around its aim yaw. If the attacker is outside it, the defender
    needs (gap - half_arc)/turn_rate to bring the attacker back inside, plus reaction time.
    """
    gap = _angle_gap(defender_aim_yaw, defender_pos, attacker_pos)
    half = math.radians(front_arc_deg) / 2.0
    if gap <= half:
        return 0.0
    return reaction_s + (gap - half) / max(defender_turn_rate, 1e-3)


class Engagement:
    """Fight-or-flee + retreat-and-regen state machine."""

    def __init__(self, hello: Dict[str, Any], params: Optional[Dict[str, Any]] = None,
                 occluder: Optional[Occluder] = None, profile: Optional[str] = None):
        self.cfg = hello["config"]
        self.k = dict(params) if params else load_params(None, profile)
        self.occ = occluder
        self.mode = "neutral"
        self.mode_since = 0.0
        self.target: Optional[int] = None
        self.lockout: Dict[int, float] = {}      # enemy id -> t until which we won't re-engage
        self.last_seen: Dict[int, Dict[str, Any]] = {}  # id -> {t, pos, hp, max_hp, aim}
        self.last_threat_pos: Optional[List[float]] = None
        self.last_threat_t = -1e9
        self.last_combat_t = -1e9                # last time we dealt or took damage
        self.phantoms: List[Dict[str, Any]] = []  # unseen shooters from damaged events
        self.away_since: Dict[int, float] = {}   # enemy id -> t since which its back has been toward us
        self.goal: Optional[List[float]] = None
        self.goal_t = -1e9
        self.goal_score = -1e9
        self.goal_hidden = False
        self.unseen_since: Optional[float] = None
        self.bad_spots: List[Tuple[float, float, float]] = []   # (x, y, t) refuges that did not hide us
        self.retreat_start_t = 0.0
        self.retreat_min_dist = math.inf
        self.escape_s = self.k["default_escape_s"]
        self.regen_start_t = 0.0
        self.cornered = False
        self.stats = {"engage": 0, "retreat": 0, "regen": 0, "cornered": 0, "refuge_ms_max": 0.0}

    # ---------------------------------------------------------------- environment hooks
    def _los(self, a, b) -> bool:
        return self.occ.los(a, b) if self.occ else True

    def _ground(self, x, y, default) -> float:
        return self.occ.ground(x, y) if self.occ else default

    def _walkable(self, x, y) -> bool:
        return self.occ.walkable(x, y) if self.occ else True

    # ---------------------------------------------------------------- stats extraction
    def _my_ehp(self, me) -> float:
        armor = me["stats"].get("armor", 0.0)
        return me["hp"] / max(0.2, 1.0 - armor)

    def _my_weapons(self, me, dist: float, target_weapons: Sequence[str], cfgw) -> Tuple[List[Any], List[float]]:
        k = self.k
        ws: List[Any] = []
        starts: List[float] = []
        cm = 1.0 if self.k["self_stats_include_cube"] else _cube_mult(self.cfg, me["cubes"])
        held = {w["kind"] for w in me["weapons"] if w}
        t_has_laser = "laser" in target_weapons
        t_has_mortar = "mortar" in target_weapons
        t_has_light = "lightning" in target_weapons
        walk = me["stats"].get("walk_speed", 11.7)
        for w in me["weapons"]:
            if not w:
                continue
            st = w["stats"]
            kind = w["kind"]
            cd0 = max(0.0, w.get("cooldown", 0.0))
            rng = st.get("range", 1e9)
            approach = max(0.0, dist - rng * 0.95) / walk
            if kind == "gun":
                g = Gun(st["damage"] * cm, st["cooldown"], int(st["mag"]), st["reload"], k["hit_gun"],
                        ammo=w.get("ammo"), reload_left=w.get("reload", 0.0))
                ws.append(g)
                starts.append(max(cd0, approach))
            elif kind == "laser":
                if t_has_light and dist <= self.cfg["weapons"]["lightning"]["range"] * 1.5:
                    continue  # their lightning shorts my laser as long as it is in arc range
                ck = 1.0 + self.cfg["weapons"]["laser"]["cookoff"] if t_has_mortar else 1.0
                ws.append(Laser(st["damage"] * cm, st["charge"], st["cooldown"], k["hit_laser"], ck))
                starts.append(max(cd0, approach))
            elif kind == "lightning":
                f = k["mortar_vs_lightning"] if t_has_mortar else 1.0
                ws.append(Lightning(st["damage"] * cm, st["cooldown"], k["hit_lightning"], f))
                starts.append(max(cd0, approach))
            elif kind == "mortar":
                if dist < k["mortar_min_range"]:
                    continue
                f = k["mortar_vs_lightning"] if t_has_light else 1.0
                ws.append(Mortar(st["damage"] * cm, st["splash"] * cm, st["cooldown"], k["hit_mortar_direct"],
                                 k["hit_mortar_splash"], f))
                starts.append(max(cd0, approach))
        return ws, starts

    def _enemy_side(self, m, me, t_now: float, weight: float, is_target: bool) -> Side:
        k = self.k
        cfgw = self.cfg["weapons"]
        pad = 1.0 + k["enemy_pad_per_offer"] * _offers(self.cfg, int(m.get("cubes", 0)))
        cm = _cube_mult(self.cfg, m.get("cubes", 0)) * pad
        skill = k["enemy_skill"]
        d = dist2(m["pos"], me["pos"])
        max_hp = m.get("max_hp", self.cfg["mech"]["hp"])
        hp = m.get("hp")
        if hp is None:
            hp = max_hp
        ehp = hp * pad
        if m["kind"] == "npc":
            npc = self.cfg["npc"]
            return Side(m["id"], ehp, [NpcGun(npc["damage"], npc["cooldown"], k["npc_hit"])], [0.0],
                        weight=weight, is_target=is_target)  # NPC torso aim is ignored: no rear windows
        kinds = [w for w in m.get("weapons", ["gun"])]
        my_kinds = {w["kind"] for w in me["weapons"] if w}
        ws: List[Any] = []
        st: List[float] = []
        walk = self.cfg["mech"]["walk_speed"]
        # can they bear on us? they have to turn if we are outside their aim
        gap = _angle_gap(m["aim"][0], m["pos"], me["pos"])
        bear_delay = k["reaction_s"] + gap / max(self.cfg["mech"]["turn_rate"], 1e-3)
        if gap < math.radians(20):
            bear_delay = 0.0
        charging = bool(m.get("charging"))
        for kind in kinds:
            c = cfgw.get(kind)
            if kind == "gun":
                ws.append(Gun(c["damage"] * cm, c["cooldown"], c["mag"], c["reload"], min(0.95, k["hit_gun"] * skill)))
                st.append(bear_delay + max(0.0, d - c["range"] * 0.95) / walk)
            elif kind == "laser":
                if "lightning" in my_kinds and d <= cfgw["lightning"]["range"] * 1.5:
                    continue  # my lightning shorts them
                ck = 1.0 + cfgw["laser"]["cookoff"] if "mortar" in my_kinds else 1.0
                ws.append(Laser(c["damage"] * cm, 0.0 if charging else c["charge"], c["cooldown"],
                                min(0.95, k["hit_laser"] * skill), ck))
                st.append(bear_delay)
            elif kind == "lightning":
                f = k["mortar_vs_lightning"] if "mortar" in my_kinds else 1.0
                ws.append(Lightning(c["damage"] * cm, c["cooldown"], min(0.95, k["hit_lightning"] * skill), f))
                st.append(bear_delay + max(0.0, d - c["range"] * 0.95) / walk)
            elif kind == "mortar":
                if d < k["mortar_min_range"]:
                    continue
                f = k["mortar_vs_lightning"] if "lightning" in my_kinds else 1.0
                ws.append(Mortar(c["damage"] * cm, c["splash"] * cm, c["cooldown"],
                                 min(0.9, k["hit_mortar_direct"] * skill), min(0.9, k["hit_mortar_splash"] * skill), f))
                st.append(bear_delay)
        # rear-armor window: how long THEIR back is toward me (my x1.5 bonus)
        rw = rear_window(me["pos"], m["pos"], m["aim"][0], self.cfg["mech"]["turn_rate"],
                         self.cfg["mech"]["front_arc_deg"], k["reaction_s"])
        since = self.away_since.get(m["id"])
        if since is not None and rw > 0.0 and (t_now - since) >= k["distracted_after_s"]:
            rw += k["distracted_bonus_s"]
        rom = rear_window(m["pos"], me["pos"], me["aim"][0], me["stats"].get("turn_rate", 4.0),
                          self.cfg["mech"]["front_arc_deg"], 0.0)
        return Side(m["id"], ehp, ws, st, rear_window=rw, rear_on_me=rom, weight=weight, is_target=is_target)

    # ---------------------------------------------------------------- evaluation
    def evaluate(self, obs: Dict[str, Any], target: Dict[str, Any], others: List[Dict[str, Any]]) -> Tuple[FightResult, Dict[str, Any]]:
        k = self.k
        me = obs["self"]
        t_now = obs["t"]
        sides: List[Side] = []
        tgt_side = self._enemy_side(target, me, t_now, 1.0, True)
        sides.append(tgt_side)
        for o in others:
            if o["id"] == target["id"]:
                continue
            d = dist2(o["pos"], me["pos"])
            if d <= k["join_radius"]:
                sides.append(self._enemy_side(o, me, t_now, k["join_weight"], False))
        # my weapons configured against the target's kit
        dist = dist2(target["pos"], me["pos"])
        tw = target.get("weapons", ["gun"])
        ws, starts = self._my_weapons(me, dist, tw, self.cfg["weapons"])
        # focus: target first, then joiners by ascending HP
        order = [0] + sorted(range(1, len(sides)), key=lambda i: sides[i].hp)
        extra = 0.0
        if not me.get("in_zone", True):
            extra += obs["zone"]["dps"]
        extra += k["third_party_dps"] * max(0.0, (obs["alive"] - 1) / 15.0)
        # rear multiplier applies at the rear_window time scale per side; sim uses `rear_mult`
        res = simulate_fight(self._my_ehp(me), ws, starts, sides, self.cfg["mech"]["rear_mult"], extra,
                             k["horizon_s"], k["dt"], order, 99.0)
        info = {"n_sides": len(sides), "my_dps_kinds": [w.kind for w in ws], "rear_window_them": round(tgt_side.rear_window, 2),
                "rear_on_me": round(tgt_side.rear_on_me, 2), "extra_dps": round(extra, 1)}
        return res, info

    def _threshold(self, obs: Dict[str, Any], target: Dict[str, Any]) -> float:
        k = self.k
        thr = k["engage_ratio"]
        if obs["alive"] >= k["early_alive"]:
            thr += k["early_ratio_add"]
        if obs["alive"] <= k["late_alive"]:
            thr *= k["late_ratio_mult"]
        if target["kind"] == "mech":
            bonus = min(k["kill_value_cap"], k["kill_value_per_cube"] * (target.get("cubes", 0) + 2))
            thr *= (1.0 - bonus)
        else:
            thr *= (1.0 - min(k["kill_value_cap"], k["kill_value_per_cube"] * 2))
        return thr

    # ---------------------------------------------------------------- refuge search
    def _refuge(self, obs: Dict[str, Any], threats: List[List[float]]) -> Optional[Tuple[List[float], float, bool]]:
        """Pick a nearby hidden point away from `threats`. Returns (goal_xy, score, hidden)."""
        k = self.k
        me = obs["self"]
        px, py, pz = me["pos"]
        zone = obs["zone"]
        zc, zr = zone["next_center"], zone["next_radius"]
        eye_z = 8.0
        body_z = 4.5
        threats = sorted(threats, key=lambda p: dist2(p, me["pos"]))[:2]
        if not threats:
            return None
        t0 = time.perf_counter()
        t_now = obs["t"]
        best: Optional[Tuple[List[float], float, bool]] = None
        speed = me["stats"].get("boost_speed", 19.5) if me["energy"] > k["boost_min_energy"] else me["stats"].get("walk_speed", 11.7)
        base_far = {i: dist2(th, me["pos"]) for i, th in enumerate(threats)}
        n = int(k["refuge_headings"])
        # bias headings: directly away from the nearest threat first
        away = bearing(threats[0], me["pos"])
        for ring in k["refuge_rings"]:
            for h in range(n):
                if (time.perf_counter() - t0) * 1000.0 > k["refuge_budget_ms"]:
                    return best
                ang = away + (h - n / 2.0 + 0.5) * (2 * math.pi / n)
                x = px + ring * math.cos(ang)
                y = py + ring * math.sin(ang)
                if not self._walkable(x, y):
                    continue
                gz = self._ground(x, y, pz)
                hidden = 0
                gain = 0.0
                path_vis = 0
                for ti, th in enumerate(threats):
                    thz = th[2] if len(th) > 2 else pz
                    a = (th[0], th[1], thz + eye_z)
                    seen = self._los(a, (x, y, gz + body_z)) or self._los(a, (x, y, gz + 9.0))
                    if not seen:
                        hidden += 1
                    gain += (dist2(th, (x, y)) - base_far[ti]) / ring
                    mx, my = (px + x) * 0.5, (py + y) * 0.5
                    if self._los(a, (mx, my, self._ground(mx, my, pz) + body_z)):
                        path_vis += 1
                hf = hidden / len(threats)
                gain /= len(threats)
                excess = max(0.0, dist2((x, y), zc) - (zr - k["zone_margin"]))
                bad = any(t_now - b[2] < k["bad_spot_ttl_s"] and math.hypot(x - b[0], y - b[1]) < k["bad_spot_radius"]
                          for b in self.bad_spots)
                score = (k["w_hidden"] * hf + k["w_gain"] * max(-1.0, min(1.0, gain))
                         - k["w_travel"] * (ring / speed) - k["w_path"] * (path_vis / len(threats))
                         - k["w_zone"] * excess / 100.0 - (k["w_bad"] if bad else 0.0))
                if best is None or score > best[1]:
                    best = ([x, y, gz], score, hf >= 0.999)
        ms = (time.perf_counter() - t0) * 1000.0
        self.stats["refuge_ms_max"] = max(self.stats["refuge_ms_max"], ms)
        return best

    def _escape_time(self, obs, threats) -> float:
        """Estimated seconds to break LOS from the current position (cached via last refuge)."""
        if self.goal is None or not threats:
            return self.k["default_escape_s"]
        me = obs["self"]
        speed = me["stats"].get("boost_speed", 19.5) if me["energy"] > self.k["boost_min_energy"] else me["stats"].get("walk_speed", 11.7)
        return max(1.0, dist2(self.goal, me["pos"]) / speed)

    # ---------------------------------------------------------------- bookkeeping
    def _ingest(self, obs: Dict[str, Any]) -> None:
        t = obs["t"]
        for m in obs["mechs"]:
            self.last_seen[m["id"]] = {"t": t, "pos": m["pos"], "hp": m.get("hp"), "max_hp": m.get("max_hp"),
                                       "aim": m["aim"], "kind": m["kind"], "cubes": m.get("cubes", 0),
                                       "weapons": m.get("weapons", [])}
        half = math.radians(self.cfg["mech"]["front_arc_deg"]) / 2.0
        mp = obs["self"]["pos"]
        live = set()
        for m in obs["mechs"]:
            if m["kind"] != "mech":
                continue
            live.add(m["id"])
            if _angle_gap(m["aim"][0], m["pos"], mp) > half:
                self.away_since.setdefault(m["id"], t)
            else:
                self.away_since.pop(m["id"], None)
        for eid in list(self.away_since):
            if eid not in live:
                del self.away_since[eid]
        self.phantoms = [p for p in self.phantoms if t - p["t"] <= self.k["phantom_ttl"]]
        visible_ids = {m["id"] for m in obs["mechs"]}
        for e in obs["events"]:
            ty = e.get("type")
            if ty in ("damaged", "hit"):
                if not (ty == "damaged" and e.get("weapon") == "zone"):
                    self.last_combat_t = t
            if ty == "damaged" and e.get("by") is not None and e["by"] not in visible_ids and e.get("bearing") is not None:
                me = obs["self"]["pos"]
                b = e["bearing"]
                self.phantoms.append({"t": t, "id": e["by"], "pos": [me[0] + self.k["phantom_dist"] * math.cos(b),
                                                                      me[1] + self.k["phantom_dist"] * math.sin(b), me[2]]})
        for m in obs["mechs"]:
            if m["kind"] == "mech" and dist2(m["pos"], obs["self"]["pos"]) < self.k["threat_radius"]:
                self.last_threat_pos = list(m["pos"])
                self.last_threat_t = t
        if self.phantoms and not any(m["kind"] == "mech" for m in obs["mechs"]):
            self.last_threat_pos = list(self.phantoms[-1]["pos"])
            self.last_threat_t = t

    def _set_mode(self, mode: str, t: float) -> None:
        if mode != self.mode:
            self.mode = mode
            self.mode_since = t
            if mode in self.stats:
                self.stats[mode] += 1

    def regen_eta(self, obs: Dict[str, Any], frac: float) -> float:
        me = obs["self"]
        st = me["stats"]
        delay_left = max(0.0, st.get("regen_delay", 5.0) - (obs["t"] - self.last_combat_t))
        need = max(0.0, frac * me["max_hp"] - me["hp"])
        return delay_left + need / max(st.get("regen_per_s", 45.0), 1e-3)

    def predicted_enemy_hp(self, eid: int, t: float) -> Optional[float]:
        """Enemies regen too (symmetric). Predict a remembered enemy's HP after we lost sight of it."""
        s = self.last_seen.get(eid)
        if not s or s.get("hp") is None:
            return None
        dt = max(0.0, t - s["t"] - self.cfg["mech"]["regen_delay"])
        return min(s.get("max_hp") or self.cfg["mech"]["hp"], s["hp"] + dt * self.cfg["mech"]["regen_per_s"])

    # ---------------------------------------------------------------- main entry
    def update(self, obs: Dict[str, Any]) -> "Decision":
        k = self.k
        t = obs["t"]
        me = obs["self"]
        self._ingest(obs)
        hp_frac = me["hp"] / max(1.0, me["max_hp"])
        mechs = [m for m in obs["mechs"] if m["kind"] == "mech" and dist2(m["pos"], me["pos"]) <= k["threat_radius"]]
        npcs = [m for m in obs["mechs"] if m["kind"] == "npc" and dist2(m["pos"], me["pos"]) <= 60.0]
        # phantoms behave like unseen mechs for retreat purposes (not for the estimator)
        threat_pos = [m["pos"] for m in mechs] + [p["pos"] for p in self.phantoms]
        diag: Dict[str, Any] = {"hp_frac": round(hp_frac, 3), "mode_in": self.mode, "n_mech": len(mechs), "n_phantom": len(self.phantoms)}

        # ---- candidate evaluation (only if there is something to fight)
        best = None
        pool = mechs if mechs else []
        cand = sorted(pool, key=lambda m: dist2(m["pos"], me["pos"]))[: k["target_max"]]
        low = min(pool, key=lambda m: (m.get("hp") or 1e9), default=None)
        if low is not None and low not in cand:
            cand.append(low)
        if not cand and npcs and not self.phantoms and self.mode in ("neutral", "engage"):
            cand = npcs[:1]
        for m in cand:
            if self.lockout.get(m["id"], -1) > t and m["kind"] == "mech":
                continue
            res, info = self.evaluate(obs, m, pool or npcs)
            thr = self._threshold(obs, m)
            score = res.ratio / thr
            if best is None or score > best[0]:
                best = (score, m, res, info, thr)

        # ---- transitions
        mode = self.mode
        decision_reason = ""
        if mode in ("neutral", "engage"):
            if best is not None:
                score, tgt, res, info, thr = best
                diag.update(R=round(res.ratio, 2), thr=round(thr, 2), ttk_me=round(res.ttk_target, 2) if res.ttk_target != math.inf else None,
                            dmg_taken=round(res.damage_taken), target=tgt["id"], **info)
                # hysteresis: use the lower disengage_ratio once fighting
                bar = k["disengage_ratio"] if mode == "engage" else thr
                finishing = (res.ttk_target <= k["finish_ttk_s"] and res.taken_at_target < k["finish_survive_frac"] * self._my_ehp(me))
                if mode == "engage" and hp_frac < 0.75:
                    self._replan(obs, threat_pos)   # keep a fresh refuge so escape_time is real
                esc = self._escape_time(obs, threat_pos)
                enemy_dps = res.damage_taken / max(res.ttk_all if res.ttk_all != math.inf else k["horizon_s"], 0.5)
                esc_cost = enemy_dps * esc
                must_flee = (hp_frac < k["retreat_hp_frac"] or
                             self._my_ehp(me) <= esc_cost * (1.0 + k["escape_margin"]) + k["escape_reserve_hp"])
                diag.update(esc_s=round(esc, 1), esc_cost=round(esc_cost), must_flee=must_flee, finishing=finishing)
                if mode == "neutral":
                    if res.ratio >= bar and hp_frac >= k["min_engage_hp_frac"] and not must_flee:
                        self._set_mode("engage", t)
                        self.target = tgt["id"]
                        decision_reason = "R>=thr"
                    elif (tgt["kind"] == "mech" and k["avoid_ratio"] > 0 and res.ratio < k["avoid_ratio"]
                          and dist2(tgt["pos"], me["pos"]) <= k["avoid_dist"]):
                        self._begin_retreat(obs, tgt["id"], threat_pos)   # hopeless matchup: leave before it starts
                        decision_reason = "avoid"
                else:  # engage
                    self.target = tgt["id"] if self.target is None or self.target not in [m["id"] for m in pool] else self.target
                    held = (t - self.mode_since) >= k["min_fight_s"]
                    if finishing and not (hp_frac < 0.12):
                        decision_reason = "finishing"
                    elif (res.ratio < bar and held) or must_flee:
                        self._begin_retreat(obs, tgt["id"], threat_pos)
                        decision_reason = "R<bar" if res.ratio < bar else "must_flee"
            else:
                diag["R"] = None
                if mode == "engage":
                    # target gone from view: stop engaging; hold position if hurt, otherwise neutral
                    self._set_mode("neutral", t)
                    self.target = None
            if k["phantom_retreat"] and self.phantoms and mode == "neutral" and best is None and self.mode == "neutral":
                # being shot by something unseen: do not stand in the open
                self._begin_retreat(obs, None, threat_pos)
                decision_reason = "phantom"
            if (self.mode == "neutral" and k["auto_regen"] and not threat_pos and hp_frac < k["heal_before_roam_frac"]
                    and self._inside_next_circle(obs)):
                if self.last_threat_pos is not None and t - self.last_threat_t < k["cover_memory_s"]:
                    self._begin_retreat(obs, None, [self.last_threat_pos])   # hide from where the last threat was
                else:
                    self._set_mode("regen", t)
                    self.regen_start_t = t
                decision_reason = "auto_regen"
        elif mode == "retreat":
            self._tick_retreat(obs, threat_pos, mechs, best, diag)
        elif mode == "regen":
            self._tick_regen(obs, threat_pos, mechs, best, diag)

        # ---- build the decision
        dec = Decision(mode=self.mode, target=self.target if self.mode == "engage" else None, diag=diag)
        dec.reason = decision_reason
        if self.mode == "engage":
            tgt_m = next((m for m in mechs + npcs if m["id"] == self.target), None)
            if tgt_m is not None:
                dec.standoff = self.standoff(me, tgt_m)
        elif self.mode == "retreat":
            self._fill_retreat(obs, dec, mechs, threat_pos)
        elif self.mode == "regen":
            self._fill_regen(obs, dec)
        else:
            dec.wants_regen = hp_frac < k["heal_before_roam_frac"] and not threat_pos
            if dec.wants_regen:
                diag["regen_eta_s"] = round(self.regen_eta(obs, k["regen_resume_frac"]), 1)
        diag["mode_out"] = self.mode
        return dec

    # ---------------------------------------------------------------- retreat / regen internals
    def _begin_retreat(self, obs, target_id: Optional[int], threat_pos) -> None:
        t = obs["t"]
        self._set_mode("retreat", t)
        self.retreat_start_t = t
        self.retreat_min_dist = min([dist2(p, obs["self"]["pos"]) for p in threat_pos], default=math.inf)
        self.cornered = False
        self.unseen_since = None
        if self.goal is not None and t - self.goal_t > 1.0:
            self.goal = None
        self._replan(obs, self._cover_threats(obs, threat_pos) or threat_pos, force=self.goal is None)
        if target_id is not None:
            self.lockout[target_id] = t + self.k["retreat_lockout_s"]
        self.target = None

    def _replan(self, obs, threat_pos, force=False) -> None:
        t = obs["t"]
        if not force and self.goal is not None and (t - self.goal_t) < self.k["replan_s"]:
            return
        # hysteresis: keep the committed goal while it is still hidden and we have not arrived
        r = self._refuge(obs, threat_pos)
        if r is None:
            return
        g, sc, hidden = r
        if self.goal is not None and (t - self.goal_t) < self.k["commit_s"] and self.goal_score >= sc - 0.5:
            return
        self.goal, self.goal_score, self.goal_t = g, sc, t
        self.goal_hidden = hidden

    def _inside_next_circle(self, obs) -> bool:
        z = obs["zone"]
        return obs["self"].get("in_zone", True) and dist2(obs["self"]["pos"], z["next_center"]) <= z["next_radius"] - self.k["zone_margin"]

    def _cover_threats(self, obs, threat_pos):
        """Live threats, else the last-known position (recent), as the thing to hide from."""
        if threat_pos:
            return threat_pos
        if self.last_threat_pos is not None and obs["t"] - self.last_threat_t < self.k["cover_memory_s"]:
            return [self.last_threat_pos]
        return []

    def _any_los(self, obs, threats) -> bool:
        me = obs["self"]
        p = (me["pos"][0], me["pos"][1], me["pos"][2] + 4.5)
        for th in threats:
            thz = th[2] if len(th) > 2 else me["pos"][2]
            if dist2(th, me["pos"]) <= 200.0 and self._los((th[0], th[1], thz + 8.0), p):
                return True
        return False

    def _tick_retreat(self, obs, threat_pos, mechs, best, diag) -> None:
        k = self.k
        t = obs["t"]
        me = obs["self"]
        near = min([dist2(p, me["pos"]) for p in threat_pos], default=math.inf)
        self.retreat_min_dist = min(self.retreat_min_dist, near) if t - self.retreat_start_t < 1.0 else self.retreat_min_dist
        # The observation is ground truth: a mech in obs["mechs"] has line of sight to us (vision is symmetric
        # except for its 120 deg wedge). The map model only covers unseen shooters (phantoms) and planning.
        see_live = any(dist2(m["pos"], me["pos"]) <= 200.0 for m in mechs)
        phantom_pos = [p for p in threat_pos if not any(p is m["pos"] for m in mechs)]
        see = see_live or (bool(phantom_pos) and self._any_los(obs, phantom_pos))
        if see:
            self.unseen_since = None
        elif self.unseen_since is None:
            self.unseen_since = t
        unseen_for = 0.0 if self.unseen_since is None else t - self.unseen_since
        diag.update(retreat_s=round(t - self.retreat_start_t, 1), near=round(near, 1) if near != math.inf else None,
                    seen=see, unseen_s=round(unseen_for, 1))
        arrived = self.goal is not None and dist2(self.goal, me["pos"]) < 4.0
        if arrived and see:       # the "hidden" refuge was not: remember it and plan somewhere else
            self.bad_spots = [b for b in self.bad_spots if t - b[2] < k["bad_spot_ttl_s"]] + [(self.goal[0], self.goal[1], t)]
            self.goal, self.goal_t, self.goal_score = None, -1e9, -1e9
            diag["bad_spot"] = True
        if arrived and not see:   # decide before replanning, or we would jitter between refuges
            if unseen_for >= k["regen_unseen_s"]:
                self._set_mode("regen", t)
                self.regen_start_t = t
            return                # else: stay put until the unseen timer matures
        self._replan(obs, self._cover_threats(obs, threat_pos))
        # pursued and cornered? turn and fight if the odds are not hopeless
        if (t - self.retreat_start_t) > k["pursuit_giveup_s"] and mechs and near <= self.retreat_min_dist + 5.0 and see:
            if best is not None and best[2].ratio >= k["cornered_ratio"]:
                self.cornered = True
                self._set_mode("engage", t)
                self.target = best[1]["id"]
                self.stats["cornered"] += 1
                diag["cornered"] = True
                return
        if threat_pos:
            clear = near > k["clear_dist"] and not see
        else:  # nothing in view: walk to the refuge first, but not for long
            clear = self.goal is None or (t - self.retreat_start_t) > k["cover_walk_max_s"]
        if clear and (t - self.retreat_start_t) > 1.0 and unseen_for >= k["regen_unseen_s"]:
            self._set_mode("regen", t)
            self.regen_start_t = t
        # zone safety: if we are outside the zone there is no regen; keep moving to the circle
        if not me.get("in_zone", True):
            diag["out_of_zone"] = True

    def _fill_retreat(self, obs, dec, mechs, threat_pos) -> None:
        k = self.k
        me = obs["self"]
        dec.goal = self.goal
        if self.goal is not None:
            ang = bearing(me["pos"], self.goal)
            dec.move = (math.cos(ang), math.sin(ang))
        elif threat_pos:
            nearest = min(threat_pos, key=lambda p: dist2(p, me["pos"]))
            ang = bearing(nearest, me["pos"])
            dec.move = (math.cos(ang), math.sin(ang))
        near = min([dist2(p, me["pos"]) for p in threat_pos], default=math.inf)
        seen = dec.diag.get("seen", False)
        dec.boost = bool(seen and me["energy"] >= k["boost_min_energy"] and near < 200.0)
        dec.speed = 1.0
        if not seen and near > k["clear_dist"]:
            dec.speed = k["slip_speed"] / me["stats"].get("walk_speed", 11.7)  # silent once out of sight and clear
            dec.boost = False
        if k["retreat_face_threat"] and threat_pos:
            nearest = min(threat_pos, key=lambda p: dist2(p, me["pos"]))
            dec.aim_yaw = bearing(me["pos"], nearest)
        dec.hold_fire = not k["retreat_cover_fire"]

    def _tick_regen(self, obs, threat_pos, mechs, best, diag) -> None:
        k = self.k
        t = obs["t"]
        me = obs["self"]
        hp_frac = me["hp"] / max(1.0, me["max_hp"])
        diag["regen_eta_s"] = round(self.regen_eta(obs, k["regen_resume_frac"]), 1)
        # exit conditions
        if hp_frac >= k["regen_resume_frac"] or (t - self.regen_start_t) > k["regen_max_wait_s"]:
            self._set_mode("neutral", t)
            diag["regen_done"] = True
            return
        # a threat appeared
        if mechs or (self.phantoms and any(p["t"] > obs["t"] - 1.0 for p in self.phantoms)):
            if best is not None and best[2].ratio >= max(best[4], k["engage_ratio"]) and hp_frac >= k["min_engage_hp_frac"]:
                self._set_mode("engage", t)
                self.target = best[1]["id"]
                diag["ambush"] = True
            else:
                self._begin_retreat(obs, None, threat_pos)
            return
        # zone about to leave us outside? (no regen outside; also leave before the squeeze)
        zone = obs["zone"]
        if dist2(me["pos"], zone["next_center"]) > zone["next_radius"] - k["zone_margin"]:
            time_to_shrink = zone["shrink_start"] - t
            excess = dist2(me["pos"], zone["next_center"]) - (zone["next_radius"] - k["zone_margin"])
            travel = excess / me["stats"].get("walk_speed", 11.7)
            if time_to_shrink <= travel + k["zone_leave_margin_s"] or not me.get("in_zone", True):
                self._set_mode("neutral", t)
                diag["leave_regen_zone"] = True

    def _fill_regen(self, obs, dec) -> None:
        k = self.k
        me = obs["self"]
        dec.move = (0.0, 0.0)
        dec.speed = 0.0
        dec.hold_fire = True
        if self.last_threat_pos is not None:
            dec.aim_yaw = bearing(me["pos"], self.last_threat_pos)
        if self.last_threat_pos is None or dist2(self.last_threat_pos, me["pos"]) > k["reload_safe_dist"]:
            g = next((w for w in me["weapons"] if w and w.get("kind") == "gun"), None)
            if g and g.get("ammo", g["stats"]["mag"]) < g["stats"]["mag"] and g.get("reload", 0) == 0:
                dec.reload = True

    # ---------------------------------------------------------------- advisory standoff band
    def standoff(self, me, tgt) -> Tuple[float, float, str]:
        """(min_range, max_range, why) a Movement component can use. Derived from the weapon triangle."""
        mine = {w["kind"] for w in me["weapons"] if w}
        theirs = set(tgt.get("weapons", ["gun"]))
        lr = self.cfg["weapons"]["lightning"]["range"]
        if "lightning" in mine and "laser" in theirs and "lightning" not in theirs:
            return (0.0, lr * 0.9, "close in: lightning shorts laser")
        if "lightning" in theirs and "lightning" not in mine:
            if "mortar" in mine:
                return (lr * 1.3, 200.0, "mortar from beyond lightning range")
            return (lr * 1.3, 140.0, "stay outside lightning range")
        if "laser" in mine and "mortar" in theirs:
            return (50.0, 250.0, "laser outranges mortar and cooks it off")
        if "mortar" in mine and "laser" in theirs and "lightning" not in mine:
            return (0.0, 60.0, "bad matchup: close fast or leave")
        return (35.0, 140.0, "default band")


@dataclass
class Decision:
    mode: str = "neutral"
    target: Optional[int] = None
    goal: Optional[List[float]] = None
    move: Optional[Tuple[float, float]] = None     # None = integrator's navigation decides
    speed: float = 1.0                              # scale for `move` length (stealth/slip)
    boost: bool = False
    aim_yaw: Optional[float] = None                 # None = aiming component decides
    hold_fire: bool = False
    reload: bool = False
    wants_regen: bool = False
    standoff: Optional[Tuple[float, float, str]] = None
    reason: str = ""
    diag: Dict[str, Any] = field(default_factory=dict)

    def apply(self, act: Dict[str, Any]) -> Dict[str, Any]:
        """Merge into an action dict. Only overrides what this mode owns."""
        if self.mode in ("retreat", "regen") and self.move is not None:
            mx, my = self.move
            act["move"] = [mx * self.speed, my * self.speed]
            act["boost"] = self.boost
        if self.aim_yaw is not None:
            act["aim"] = [self.aim_yaw, 0.0]
        if self.hold_fire:
            act["fire"] = [False, False]
        if self.reload:
            act["reload"] = True
        return act


if __name__ == "__main__":
    import sys
    if "--dump-params" in sys.argv:
        print(json.dumps({"engage": {k: (list(v) if isinstance(v, tuple) else v) for k, v in PARAMS.items()}}, indent=2))
