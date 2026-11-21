"""loot.py: pickup priority + weapon counter-pick policy (H-LOO, H-WPN). Standard library only.

Owns: which weapon pickup to walk to, when to `take` (and which slot to `drop`), and when to drop a
liability weapon. Does NOT own: pathing (inject `path_cost`), aiming/firing, zone choice.

Usage inside a bot:

    planner = loot.LootPlanner(hello["config"], loot.LootParams.from_dict(params.get("loot", {})))
    ...
    d = planner.step(obs, threats=perception_threats_or_None, path_cost=nav.path_cost_or_None)
    if d.take is not None:
        action["take"] = d.take
        if d.drop is not None: action["drop"] = d.drop
    elif d.drop is not None:              # liability drop, no pickup
        action["drop"] = d.drop
    elif d.goal is not None:
        nav.set_goal(d.goal, priority="loot")   # navigation module routes there

Weapon slots are NOT fixed: use `loot.slot_of(obs["self"]["weapons"], "laser")` to find which
`fire[i]` to press. Never hard-code fire=[gun, special].

Every number a test might want to move is in LootParams (-> params.json["loot"]).
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field, fields
from typing import Callable, Dict, FrozenSet, Iterable, List, Optional, Tuple

SPECIALS = ("mortar", "laser", "lightning")

# Prior value of owning a special when nothing is known about opponents (None = empty slot = 0).
# Reasoning in the proposal doc: lightning needs no aim and has the best dps; laser is hitscan but
# dodgeable and 1.65 s to equip; mortar is hard to land on movers, 2.6 s to equip, and is the only
# weapon that is a liability just by being held (laser cook-off, +60%).
DEFAULT_BASE = {"lightning": 1.0, "laser": 0.9, "mortar": 0.55}

# COUNTER[mine][theirs] = (delta, tau_m): value of holding `mine` against an opponent holding `theirs`,
# scaled by exp(-dist/tau_m) where tau_m is the range at which that matchup actually bites.
DEFAULT_COUNTER = {
    "laser": {"mortar": (0.5, 200.0),      # cook-off +60% and outranges the shell
              "lightning": (-0.3, 50.0),   # shorted, but only inside its 45 m arc
              "laser": (0.0, 1.0)},
    "mortar": {"lightning": (0.4, 50.0),   # concussion throws it out of arc range, drains energy
               "laser": (-0.8, 200.0),     # a held mortar eats +60% from any laser within 280 m
               "mortar": (0.0, 1.0)},
    "lightning": {"laser": (0.5, 50.0),    # short: charge lost, no laser for 2 s (inside 45 m)
                  "mortar": (-0.4, 120.0),  # concussed out of range, energy drained
                  "lightning": (0.0, 1.0)},
}

SOUND_KIND = {"laser": "laser", "laser_charge": "laser", "lightning": "lightning",
              "mortar": "mortar", "explosion": "mortar"}
SOUND_DIST_M = {"near": 30.0, "mid": 110.0, "far": 220.0}


@dataclass
class LootParams:
    enabled: bool = True
    # --- value model (H-WPN) ---
    base: Dict[str, float] = field(default_factory=lambda: dict(DEFAULT_BASE))
    counter: Dict[str, Dict[str, Tuple[float, float]]] = field(default_factory=lambda: {k: dict(v) for k, v in DEFAULT_COUNTER.items()})
    counter_strength: float = 1.0      # 0 = fixed pick by `base` only (the H-WPN control arm)
    counter_cap: float = 1.5           # clamp on the summed counter term
    threat_half_life_s: float = 20.0   # a remembered loadout loses half its weight every this many s
    kind_memory_s: float = 60.0        # forget an enemy's loadout after this long unseen
    sound_weight: float = 0.5          # heard-but-unseen weapon counts this much of a seen one
    # --- where to go (H-LOO) ---
    dist_cost_per_100m: float = 0.35   # utility lost per 100 m of path
    detour_early_m: float = 150.0      # empty slot, t < early_until_s
    detour_mid_m: float = 60.0         # empty slot, t < mid_until_s (first shrink)
    detour_late_m: float = 25.0        # empty slot, after
    swap_detour_m: float = 40.0        # slot full: only walk this far to upgrade
    early_until_s: float = 60.0
    mid_until_s: float = 110.0
    min_utility: float = 0.05
    exposure_weight: float = 0.5       # x exposure in [0,1] from nav
    enemy_near_pickup_m: float = 40.0  # visible enemy mech this close to the pickup
    enemy_near_pickup_pen: float = 1.0
    roof_dz_m: float = 4.0             # pickup this much above our feet = roof
    roof_max_dz_m: float = 40.0
    roof_pen_per_10m: float = 0.1
    zone_margin_m: float = 25.0        # pickup must be this far inside the (next) circle
    # --- swaps ---
    swap_margin: float = 0.25          # hysteresis: new weapon must beat the held one by this
    swap_cooldown_s: float = 6.0       # no swap within this of the last one
    equip_cost_per_s: float = 0.05     # x equip delay x (1 + 2 if in a fight)
    fight_dist_m: float = 60.0         # enemy mech this close = in a fight
    fight_pickup_radius_m: float = 12.0  # in a fight only grab pickups this close
    # --- liability drop ---
    drop_liability: bool = True
    drop_below: float = 0.10           # drop a held special whose value (vs who is around) is below this
    drop_blacklist_s: float = 30.0     # do not re-take what we just dropped
    blacklist_s: float = 5.0           # after take_failed
    take_margin_m: float = 0.5         # send `take` when within pickup_radius - this

    @classmethod
    def from_dict(cls, d: Optional[dict]) -> "LootParams":
        """Build from params.json["loot"]: unknown keys ignored, partial overrides allowed."""
        p = cls()
        names = {f.name for f in fields(cls)}
        for k, v in (d or {}).items():
            if k not in names:
                continue
            if k == "base":
                p.base.update(v)
            elif k == "counter":
                for mine, row in v.items():
                    for theirs, pair in row.items():
                        p.counter.setdefault(mine, {})[theirs] = (float(pair[0]), float(pair[1]))
            else:
                setattr(p, k, v)
        return p


@dataclass
class Threat:
    id: Optional[int]
    dist: float
    kinds: FrozenSet[str]
    weight: float          # 0..1 confidence (age and sound discount); distance is applied per matchup in value()


@dataclass
class Decision:
    take: Optional[int] = None
    drop: Optional[int] = None
    goal: Optional[Tuple[float, float, float]] = None
    pickup_id: Optional[int] = None
    kind: Optional[str] = None
    utility: float = 0.0
    reason: str = ""


# ----------------------------------------------------------------------------------------- helpers
def slot_of(weapons: List[Optional[dict]], kind: str) -> Optional[int]:
    """Slot index holding `kind`, else None. Use for `fire[i]`."""
    for i, w in enumerate(weapons):
        if w and w.get("kind") == kind:
            return i
    return None


def preferred_range(kind: str, cfg: dict) -> Tuple[float, float, float]:
    """(min, ideal, max) engagement range in metres for Engage/Movement. Derived from config."""
    w = cfg["weapons"]
    if kind == "lightning":
        r = w["lightning"]["range"]
        return (0.0, 0.6 * r, r)
    if kind == "laser":
        r = w["laser"]["range"]
        return (45.0, 0.5 * r, r)         # stay outside lightning arc range; telegraphed, so not point blank
    if kind == "mortar":
        m = w["mortar"]
        reach = m["speed"] ** 2 / m["gravity"]
        return (2.5 * m["splash_radius"], 0.4 * reach, reach)   # own splash hurts at 50%
    g = w["gun"]
    return (0.0, 0.5 * g["range"], g["range"])


def _d2(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _default_path_cost(src, dst):
    return (_d2(src, dst) * 1.25, 0.0)


# ------------------------------------------------------------------------------------------ planner
class LootPlanner:
    def __init__(self, cfg: dict, params: Optional[LootParams] = None):
        self.cfg = cfg
        self.p = params or LootParams()
        self.pickup_radius = float(cfg["loot"]["pickup_radius"])
        self.equip_s = float(cfg["loot"]["equip_s"])
        self.mem: Dict[int, dict] = {}            # pickup id -> {kind,pos,miss}
        self.blacklist: Dict[int, float] = {}     # pickup id -> until
        self.enemy_kinds: Dict[int, dict] = {}    # mech id -> {kinds,t,pos}
        self.last_swap_t = -1e9
        self.last_damage_t = -1e9

    # -- knowledge ----------------------------------------------------------------------------
    def equip_delay(self, kind: str) -> float:
        cd = self.cfg["weapons"].get(kind, {}).get("cooldown", 0.0)
        return max(self.equip_s, cd)

    def _ingest(self, obs: dict) -> None:
        t = obs["t"]
        me = obs["self"]
        for ev in obs.get("events", []):
            typ = ev.get("type")
            if typ == "took":
                self.mem.pop(ev["id"], None)
                self.last_swap_t = t
            elif typ == "dropped":
                # the weapon now lies at our feet as pickup `ev["id"]`
                self.mem[ev["id"]] = {"kind": ev["kind"], "pos": tuple(me["pos"]), "miss": 0}
                self.blacklist[ev["id"]] = t + self.p.drop_blacklist_s
            elif typ == "take_failed":
                if ev.get("reason") == "gone":
                    self.mem.pop(ev["id"], None)
                else:
                    self.blacklist[ev["id"]] = t + self.p.blacklist_s
            elif typ == "damaged":
                self.last_damage_t = t
        seen = set()
        for pk in obs.get("pickups", []):
            seen.add(pk["id"])
            self.mem[pk["id"]] = {"kind": pk["kind"], "pos": tuple(pk["pos"]), "miss": 0}
        # Pickups never despawn, so an entry only disappears if someone took it. If we are close and it
        # is not listed for 3 observations in a row, it is gone (proximity sensors are blocked by buildings,
        # hence the streak rather than a single miss).
        for pid in list(self.mem):
            if pid in seen:
                continue
            if _d2(me["pos"], self.mem[pid]["pos"]) < 25.0:
                self.mem[pid]["miss"] += 1
                if self.mem[pid]["miss"] >= 3:
                    del self.mem[pid]
        for pid in [k for k, u in self.blacklist.items() if u < t]:
            del self.blacklist[pid]

    def threats_from_obs(self, obs: dict) -> List[Threat]:
        """Fallback threat list. Prefer Perception's tracked list if it exists (same dataclass)."""
        p, t, me = self.p, obs["t"], obs["self"]
        out: List[Threat] = []
        seen_now = set()
        for m in obs.get("mechs", []):
            if m.get("kind") != "mech":
                continue
            seen_now.add(m["id"])
            kinds = frozenset(k for k in m.get("weapons", []) if k in SPECIALS)
            self.enemy_kinds[m["id"]] = {"kinds": kinds, "t": t, "pos": tuple(m["pos"])}
            d = _d2(me["pos"], m["pos"])
            out.append(Threat(m["id"], d, kinds, 1.0))
        for mid, rec in list(self.enemy_kinds.items()):
            if mid in seen_now:
                continue
            age = t - rec["t"]
            if age > p.kind_memory_s:
                del self.enemy_kinds[mid]
                continue
            d = _d2(me["pos"], rec["pos"])
            out.append(Threat(mid, d, rec["kinds"], 0.5 ** (age / p.threat_half_life_s)))
        for s in obs.get("sounds", []):
            k = SOUND_KIND.get(s.get("kind"))
            if not k:
                continue
            d = SOUND_DIST_M.get(s.get("dist"), 110.0)
            w = p.sound_weight * 0.5 ** (s.get("age", 0.0) / p.threat_half_life_s)
            out.append(Threat(None, d, frozenset([k]), w))
        return out

    # -- value model --------------------------------------------------------------------------
    def value(self, kind: str, threats: Iterable[Threat]) -> float:
        p = self.p
        adj = 0.0
        row = p.counter.get(kind, {})
        for th in threats:
            for k in th.kinds:
                delta, tau = row.get(k, (0.0, 1.0))
                adj += th.weight * math.exp(-th.dist / tau) * delta
        adj = max(-p.counter_cap, min(p.counter_cap, adj))
        return p.base.get(kind, 0.0) + p.counter_strength * adj

    # -- decision -----------------------------------------------------------------------------
    def _budget(self, t: float, swapping: bool) -> float:
        p = self.p
        phase = p.detour_early_m if t < p.early_until_s else p.detour_mid_m if t < p.mid_until_s else p.detour_late_m
        return min(phase, p.swap_detour_m) if swapping else phase

    def _zone_ok(self, obs: dict, pos, t: float) -> bool:
        z = obs.get("zone")
        if not z:
            return True
        use_next = t >= z.get("shrink_start", 1e9) - 10.0
        c = z["next_center"] if use_next else z["center"]
        r = z["next_radius"] if use_next else z["radius"]
        return _d2(pos, c) <= r - self.p.zone_margin_m

    def step(self, obs: dict, threats: Optional[List[Threat]] = None,
             path_cost: Optional[Callable] = None) -> Decision:
        p = self.p
        self._ingest(obs)
        if not p.enabled:
            return Decision(reason="disabled")
        me, t = obs["self"], obs["t"]
        mypos = tuple(me["pos"])
        if threats is None:
            threats = self.threats_from_obs(obs)
        path_cost = path_cost or _default_path_cost
        weapons = me.get("weapons", [])

        enemies = [m for m in obs.get("mechs", []) if m.get("kind") == "mech"]
        in_fight = (any(_d2(mypos, m["pos"]) < p.fight_dist_m for m in enemies)
                    or t - self.last_damage_t < 2.0)

        # Which slot would a new weapon go to?
        def busy(i):
            w = weapons[i]
            return bool(w and w.get("kind") == "laser" and w.get("charge", 0) > 0)
        empty = [i for i, w in enumerate(weapons) if w is None]
        swappable = [i for i, w in enumerate(weapons)
                     if w is not None and not busy(i) and w["kind"] != "gun"]
        held = {w["kind"] for w in weapons if w}
        cur_v = {i: self.value(weapons[i]["kind"], threats) for i in swappable if weapons[i]["kind"] in SPECIALS}

        # 1) Liability drop: a held special that is worse than nothing against who is around.
        if p.drop_liability and cur_v and not in_fight:
            slot = min(cur_v, key=cur_v.get)
            if cur_v[slot] < p.drop_below:
                return Decision(drop=slot, kind=weapons[slot]["kind"], utility=cur_v[slot],
                                reason="liability drop")

        if not me.get("in_zone", True):
            return Decision(reason="outside zone: zone module has priority")

        if empty:
            target_slot, swapping, v_cur = empty[0], False, 0.0
        elif cur_v and t - self.last_swap_t >= p.swap_cooldown_s:
            target_slot = min(cur_v, key=cur_v.get)
            swapping, v_cur = True, cur_v[target_slot]
        else:
            return Decision(reason="slots full, swap on cooldown or nothing swappable")

        budget = self._budget(t, swapping)
        best: Optional[Tuple[float, int, dict, float]] = None
        for pid, e in self.mem.items():
            k = e["kind"]
            if k not in SPECIALS or k in held or pid in self.blacklist:
                continue
            pos = e["pos"]
            length, exposure = path_cost(mypos, pos)
            if length is None or length > budget:
                continue
            if in_fight and _d2(mypos, pos) > p.fight_pickup_radius_m:
                continue
            if not self._zone_ok(obs, pos, t):
                continue
            dz = pos[2] - mypos[2]
            roof_pen = 0.0
            if dz > p.roof_dz_m:
                need = self.cfg["mech"]["jet_drain"] * dz / self.cfg["mech"]["max_rise_speed"]
                if dz > p.roof_max_dz_m or need > me.get("energy", 0) - 15:
                    continue
                roof_pen = p.roof_pen_per_10m * dz / 10.0
            gain = self.value(k, threats) - v_cur
            if swapping:
                gain -= p.swap_margin + p.equip_cost_per_s * self.equip_delay(k) * (3.0 if in_fight else 1.0)
            # veto only enemies that would reach the pickup before we do
            mine_d = _d2(pos, mypos)
            near_enemy = any(_d2(pos, m["pos"]) < min(p.enemy_near_pickup_m, mine_d) for m in enemies)
            u = (gain - p.dist_cost_per_100m * length / 100.0 - p.exposure_weight * exposure
                 - roof_pen - (p.enemy_near_pickup_pen if near_enemy else 0.0))
            if best is None or u > best[0]:
                best = (u, pid, e, length)
        if best is None or best[0] < p.min_utility:
            return Decision(reason="nothing worth it")
        u, pid, e, length = best
        pos = e["pos"]
        reach = self.pickup_radius - p.take_margin_m
        if _d2(mypos, pos) <= reach and abs(pos[2] - mypos[2]) <= 3.5:
            return Decision(take=pid, drop=target_slot if swapping else None, goal=pos, pickup_id=pid,
                            kind=e["kind"], utility=u, reason="swap" if swapping else "take")
        return Decision(goal=pos, pickup_id=pid, kind=e["kind"], utility=u,
                        reason="walk to upgrade" if swapping else "walk to loot")
