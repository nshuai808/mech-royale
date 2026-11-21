"""Aiming and fight movement (H-AIM, H-MOV) for mech-royale v2. Stdlib only. Math lives in aimcore.py; knobs in params.json.

    ctl = aim.AimController(hello["config"], params.get("aim"), params.get("move"), seed=hello.get("seed", 0))
    d = ctl.step(obs, suppress_move=False, engage=True)   # AimDecision

Owns: aim, fire, reload, and a fight-movement SUGGESTION (d.move). It never sets take/drop/pick/jump/boost.
Weapon slots are looked up with loot.slot_of, never assumed. The caller (bot.py arbiter) decides whether to use d.move.
Any exception propagates; bot.py wraps the call and falls back to v2 behaviour.
"""
import math
from dataclasses import dataclass, fields
from typing import List, Optional, Tuple

import aimcore as A
from loot import slot_of


@dataclass
class AimParams:
    enabled: bool = True
    # target and weapon gates
    laser_max_range_frac: float = 0.9      # start a laser charge only inside this fraction of its range
    laser_extra_hold_s: float = 0.3        # release if held this long past full charge without a good alignment
    lightning_range_frac: float = 0.9
    lightning_aim_tol_deg: float = 12.0    # safe under either reading of cone_deg
    mortar_enabled: bool = False           # needs a trajectory-clear check from NAV; off until then
    mortar_max_target_speed: float = 1.5
    mortar_align_rad: float = 0.01
    # reload and facing
    reload_idle_s: float = 1.0
    turn_on_hit: bool = True
    hit_turn_s: float = 1.5
    # fight movement (the "move" section)
    strafe_enabled: bool = True
    strafe_min_range_m: float = 50.0       # inside this nothing dodges a gun; follow the goal instead
    zone_margin_m: float = 30.0            # no strafing within this distance of the zone edge
    max_bullets: int = 12

    @classmethod
    def split(cls, *sections):
        """Merge dict sections; return (AimParams, aimcore knob dict). Unknown keys ignored, bad types ignored."""
        p = cls()
        names = {f.name: f for f in fields(cls)}
        kn = {}
        for sec in sections:
            for key, v in (sec or {}).items():
                if key.startswith("_"):
                    continue
                if key in names:
                    cur = getattr(p, key)
                    if isinstance(cur, bool) and isinstance(v, bool):
                        setattr(p, key, v)
                    elif isinstance(cur, (int, float)) and not isinstance(cur, bool) and isinstance(v, (int, float)) and not isinstance(v, bool):
                        setattr(p, key, type(cur)(v))
                elif key in A.DEFAULT_KNOBS:
                    cur = A.DEFAULT_KNOBS[key]
                    if isinstance(cur, bool):
                        ok = isinstance(v, bool)
                    elif isinstance(cur, (int, float)):
                        ok = isinstance(v, (int, float)) and not isinstance(v, bool)
                    elif isinstance(cur, str):
                        ok = isinstance(v, str)
                    else:
                        ok = isinstance(v, list)
                    if ok:
                        kn[key] = v
        return p, kn


@dataclass
class AimDecision:
    aim: Optional[Tuple[float, float]] = None     # None = leave the caller's aim
    fire: Optional[List[bool]] = None             # None = leave the caller's fire
    reload: bool = False
    move: Optional[Tuple[float, float]] = None    # fight-movement suggestion (unit vector) or None
    reason: str = ""
    p_hit: Optional[float] = None
    target: Optional[int] = None


class AimController:
    def __init__(self, cfg, aim_params=None, move_params=None, seed=0):
        self.p, kn = AimParams.split(aim_params, move_params)
        self.k = A.knobs(kn)
        self.base = {
            "mech": dict(cfg["mech"]),
            "gun": dict(cfg["weapons"]["gun"]),
            "mortar": dict(cfg["weapons"]["mortar"]),
            "laser": dict(cfg["weapons"]["laser"]),
            "lightning": dict(cfg["weapons"]["lightning"]),
            "projectile": dict(cfg["projectile"]),
            "size_per_cube": cfg["cubes"]["size_per_cube"],
        }
        self.strafer = A.Strafer(int(seed) & 0x7FFFFFFF, self.k)
        self.t_enemy = -1e9          # last time an enemy was visible
        self.hit_bearing = None
        self.t_hit = -1e9
        self.full_hold = 0           # decisions the laser has been held at full charge

    # ------------------------------------------------------------------ live config (upgrades change stats at runtime)
    def _live(self, me):
        c = dict(self.base)
        st = me.get("stats") or {}
        c["mech"] = dict(c["mech"], **{k: v for k, v in st.items() if k in c["mech"]})
        for w in me["weapons"]:
            if w and w.get("stats") and w["kind"] in c:
                c[w["kind"]] = dict(c[w["kind"]], **w["stats"])
        return c

    @staticmethod
    def _me(me, cfg):
        st = me.get("stats") or {}
        m = cfg["mech"]
        return dict(pos=tuple(me["pos"]), vel=tuple(me["vel"]), aim=tuple(me["aim"]),
                    radius=st.get("radius", m["radius"]), height=st.get("height", m["height"]),
                    muzzle_h=st.get("muzzle_height", m["muzzle_height"]),
                    turn_rate=m["turn_rate"], pitch_rate=m["pitch_rate"])

    # ------------------------------------------------------------------ main entry
    def step(self, obs, suppress_move=False, engage=True, primary_id=None, traj_clear=None):
        if not self.p.enabled:
            return AimDecision(reason="off")
        t = obs["tick"] / 20.0
        me = obs["self"]
        cfg = self._live(me)
        meD = self._me(me, cfg)
        for e in obs.get("events", ()):
            if e.get("type") == "damaged" and e.get("bearing") is not None:
                self.hit_bearing, self.t_hit = e["bearing"], t
        enemies = [m for m in obs["mechs"] if m.get("kind") == "mech"]
        if not enemies:
            return self._idle(obs, me, t)
        self.t_enemy = t
        px, py, pz = me["pos"]
        enemies.sort(key=lambda m: A.dist3(m["pos"], me["pos"]))
        prim = next((m for m in enemies if m["id"] == primary_id), enemies[0])
        tgt = dict(pos=tuple(prim["pos"]), vel=tuple(prim["vel"]), cubes=prim.get("cubes", 0))
        dist = A.dist3(prim["pos"], me["pos"])
        dec = AimDecision(target=prim["id"])
        if not engage:
            dec.reason = "hold_fire"
            return dec

        weapons = me["weapons"]
        gi, li, ni, mi = (slot_of(weapons, k) for k in ("gun", "laser", "lightning", "mortar"))
        fire = [False, False]
        cmd = None
        reason = "gun"

        # laser: hold to charge, release when aligned; it owns the torso while charging
        if li is not None:
            lw = weapons[li]
            charge = lw.get("charge", 0.0) or 0.0
            lcfg = cfg["laser"]
            charging = charge > 0
            can_start = lw["cooldown"] <= 2 * self.k["dt"] + 1e-9 and dist <= self.p.laser_max_range_frac * lcfg["range"]
            if charging or can_start:
                ld = A.laser_decision(meD, tgt, charge, self.k, cfg, engage=True)
                cmd = ld["aim"]
                full = charge >= lcfg["charge"] - 1e-9
                self.full_hold = self.full_hold + 1 if (charging and full) else 0
                forced = self.full_hold * 0.1 >= self.p.laser_extra_hold_s
                fire[li] = bool(not (charging and (ld["release"] or forced)))
                reason = "laser_charge" if fire[li] else "laser_release"
                dec.p_hit = ld["p_hit"]
        else:
            self.full_hold = 0

        # mortar (off by default): only at stationary targets with a clear trajectory
        if cmd is None and mi is not None and self.p.mortar_enabled:
            mw = weapons[mi]
            spd = math.hypot(tgt["vel"][0], tgt["vel"][1])
            if mw["cooldown"] <= 2 * self.k["dt"] + 1e-9 and spd <= self.p.mortar_max_target_speed and dist >= self.k["mortar_min_range_m"]:
                sol = A.solve_mortar(meD, tgt, self.k, cfg)
                if sol and (traj_clear is None or traj_clear(sol)) and 360.0 >= self.k["mortar_min_exp_dmg"]:
                    cmd = sol["cmd"]
                    af = A.slew_aim(meD["aim"], cmd, sol["t_fire"], meD["turn_rate"], meD["pitch_rate"], cfg["mech"]["min_pitch"], cfg["mech"]["max_pitch"])
                    if abs(A.wrap_pi(af[0] - cmd[0])) <= self.p.mortar_align_rad and abs(af[1] - cmd[1]) <= self.p.mortar_align_rad:
                        fire[mi] = True
                    reason = "mortar"

        # gun: lead + slew-aware hit probability gate
        if gi is not None:
            gw = weapons[gi]
            gd = A.gun_decision(meD, tgt, gw, self.k, cfg, engage=True, aim_cmd=cmd)
            if cmd is None:
                cmd = gd["aim"]
            fire[gi] = bool(gd["fire"])
            if dec.p_hit is None:
                dec.p_hit = gd["p_hit"]

        # lightning: direct, only inside range and when the slewed aim keeps the target well inside the cone
        if ni is not None:
            nw = weapons[ni]
            lr = self.p.lightning_range_frac * cfg["lightning"]["range"]
            if cmd is None:
                cmd = A.yp_of(A.unit3((tgt["pos"][0] - px, tgt["pos"][1] - py, tgt["pos"][2] + 4.5 - pz - meD["muzzle_h"])))
            af = A.slew_aim(meD["aim"], cmd, self.k["dt"], meD["turn_rate"], meD["pitch_rate"], cfg["mech"]["min_pitch"], cfg["mech"]["max_pitch"])
            bearing = math.atan2(tgt["pos"][1] - py, tgt["pos"][0] - px)
            ok_dir = abs(A.wrap_pi(af[0] - bearing)) <= math.radians(self.p.lightning_aim_tol_deg)
            cost = (nw.get("stats") or {}).get("energy", cfg["lightning"]["energy"])
            fire[ni] = bool(dist <= lr and ok_dir and me.get("energy", 0) >= cost)

        if cmd is None:
            cmd = A.yp_of(A.unit3((tgt["pos"][0] - px, tgt["pos"][1] - py, tgt["pos"][2] + 4.5 - pz - meD["muzzle_h"])))
        dec.aim = (cmd[0], cmd[1])
        dec.fire = fire
        dec.reason = reason
        dec.move = self._move(obs, me, meD, cfg, tgt, suppress_move)
        return dec

    # ------------------------------------------------------------------ no enemy visible
    def _idle(self, obs, me, t):
        dec = AimDecision(reason="idle")
        gi = slot_of(me["weapons"], "gun")
        if gi is not None:
            gw = me["weapons"][gi]
            mag = (gw.get("stats") or {}).get("mag", self.base["gun"]["mag"])
            if gw["reload"] <= 0 and gw["ammo"] < self.k["reload_idle_ammo_frac"] * mag and t - self.t_enemy >= self.p.reload_idle_s:
                dec.reload = True
        if self.p.turn_on_hit and self.hit_bearing is not None and t - self.t_hit <= self.p.hit_turn_s:
            dec.aim = (self.hit_bearing, 0.0)       # face whoever shot us (rear hits do x1.5)
            dec.reason = "face_hit"
        return dec

    # ------------------------------------------------------------------ fight movement suggestion
    def _move(self, obs, me, meD, cfg, tgt, suppress):
        p = self.p
        if suppress or not p.strafe_enabled or not me.get("grounded", True) or not me.get("in_zone", True):
            return None
        if math.hypot(tgt["pos"][0] - meD["pos"][0], tgt["pos"][1] - meD["pos"][1]) < p.strafe_min_range_m:
            return None
        z = obs.get("zone")
        if z:
            if z["radius"] - math.hypot(meD["pos"][0] - z["center"][0], meD["pos"][1] - z["center"][1]) < p.zone_margin_m:
                return None
        dx, dy = tgt["pos"][0] - meD["pos"][0], tgt["pos"][1] - meD["pos"][1]
        n = math.hypot(dx, dy) or 1.0
        sd = self.strafer.step((dx / n, dy / n), n)
        want = sd
        speed = cfg["mech"]["walk_speed"]
        if self.k["dodge_enable"]:
            bl = [dict(pos=b["pos"], vel=b["vel"]) for b in obs.get("projectiles", ()) if b.get("kind") in ("gun", "npc")]
            if bl:
                bl.sort(key=lambda b: A.dist3(b["pos"], meD["pos"]))
                v, _cost = A.choose_move(meD, bl[:p.max_bullets], want, speed, self.k, cfg)
                vn = math.hypot(v[0], v[1])
                return (v[0] / vn, v[1] / vn) if vn > 1e-6 else (0.0, 0.0)
        return want
