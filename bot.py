"""Mech Royale bot v1: survival first.

Every decision (10/s, 50 ms budget on 1 CPU):
  1. Read the world: threats (visible mechs, recent damage, near weapon sounds), zone timing, loot.
  2. Pick a mode, in priority order:
       zone    outside the live circle, late for the next one, or zone.py says CRITICAL: run in, facing threats
       evade   outnumbered or hurt: go to a spot the threats can't see (cover search), shooting back
       fight   a fight we should take: strafe, keep weapon range, shoot
       (capture: standing in a supply-drop ring we hold outranks evade/fight: 4 s alone = 3 cubes + full HP)
       drop    a supply drop worth it and nobody near us (drops.py): approach, wait off the ring, capture
       loot    a weapon / cube nearby: take it; shoot nearby crates early
       heal    hurt and safe: stand still (silent) and regenerate
       move    get inside the next circle (with margin)
       hold    stand still, scan
  3. Aim: always face the main threat (rear hits deal x1.5). Weapons fire when the actual torso aim
     is on target: gun with lead, laser charge-and-release, lightning in its cone, mortar ballistic.

Read protocol.md for the rules; numbers come from hello.config.
"""
import json
import math
import os
import random
import time
import traceback

import botlog
import drops
import late
import mechfight as mf
import roof
import zone
from nav import AStar, Map

TAU = 2 * math.pi
UPGRADE_PREF = ["plating", "armor", "nanites", "laser_damage", "laser_charge", "lightning_efficiency",
                "gun_damage", "gun_rate", "servos", "sensors", "gyros", "jets", "capacitor", "reactor",
                "gun_mag", "gun_velocity", "lightning_range", "mortar_reload", "lightning_chain",
                "mortar_velocity", "mortar_splash", "laser_pierce"]
WEAPON_RANK = {"lightning": 3, "laser": 2, "mortar": 1, "gun": 0}   # lightning: 240 dps, can't miss inside 45 m
SPECIAL = ("laser", "lightning")
BEATS = {"laser": "mortar", "mortar": "lightning", "lightning": "laser"}   # protocol weapon triangle
# context-aware upgrade pick (params.json "upgrade_ctx"): base score per upgrade, then bumps for the weapon
# we hold and the weapons we have seen on enemy mechs (counter triangle: laser > mortar > lightning > laser)
UPG_BASE = {"plating": 10.0, "armor": 9.5, "nanites": 8.6,
            "servos": 4.0, "sensors": 3.5, "gyros": 3.5, "jets": 3.0, "capacitor": 3.0, "reactor": 3.0}
UPG_WEAPON = {   # score when this weapon is our primary (best held); a secondary held weapon gets 3 less
    "lightning": {"lightning_efficiency": 8.5, "lightning_range": 7.5, "lightning_chain": 4.0},
    "laser": {"laser_damage": 8.5, "laser_charge": 7.5, "laser_pierce": 3.0},
    "mortar": {"mortar_reload": 7.5, "mortar_velocity": 5.0, "mortar_splash": 4.5},
    "gun": {"gun_damage": 7.5, "gun_rate": 7.0, "gun_mag": 5.0, "gun_velocity": 4.5},
}
BUDGET_S = 0.028  # our own soft deadline per decision; the server's is 50 ms


def wrap(a):
    return (a + math.pi) % TAU - math.pi


def norm(x, y):
    d = math.hypot(x, y)
    return (x / d, y / d) if d > 1e-9 else (0.0, 0.0)


def load_params():
    """params.json next to this file (zone / drops knobs). A missing or bad file means the defaults."""
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "params.json")) as f:
            return json.load(f)
    except Exception:
        return {}


class Bot:
    name = "mech-royale"

    def __init__(self, hello):
        self.cfg = cfg = hello["config"]
        self.rng = random.Random(hello.get("seed", 0))
        self.slot = hello.get("slot")
        m = cfg["mech"]
        self.map = None
        try:
            self.map = Map(hello["map"]["dir"], m["height"], m["step_up"], m["max_slope_deg"], m["eye_height"])
        except Exception:
            mf.log("map load failed, steering without it:\n" + traceback.format_exc())
        self.w = cfg["weapons"]
        self.pickup_r = cfg["loot"]["pickup_radius"]
        self.cube_r = cfg["cubes"]["pickup_radius"]
        # memory
        self.zone_key = None
        self.phase_start = None          # (cx, cy, r) of the current circle when this phase began
        self.attackers = {}              # id -> (t, bearing)
        self.last_hurt_t = -99.0
        self.last_dealt_t = -99.0
        self.hurt_bearing = None
        self.heard = None                # (t, bearing, dist)
        self.short_until = -1.0
        self.hist = []                   # (t, x, y)
        self.escape_until, self.escape_dir = -1.0, (0.0, 0.0)
        self.strafe_sign, self.strafe_until = 1, 0.0
        self.cover, self.cover_t = None, -99.0
        self.job, self.job_goal, self.path, self.path_t = None, None, None, -99.0
        self.mode = "hold"
        self.target_id = None
        self.known = {}                  # enemy id -> (t_seen, x, y)
        self.zone_commit = False         # once a zone run starts, finish it (no flip-flopping)
        self.stuck_at, self.side_sign, self.escape_climb = [], 1, True
        self.roam, self.roam_t = None, -1.0
        # roam_fix: roam only to points with free ground nearby, and don't restart a failed A* for the same goal at once
        self.roam_fix = bool((load_params().get("roam_fix") or {}).get("enabled", False))
        self.fail_goal, self.fail_t = None, -99.0
        # rooftop camping (roof.py): from roof.start_s, hold a climbable roof inside the circle, out of ground sight
        self.aggro = bool((load_params().get("aggro") or {}).get("enabled", False))
        # docs/stuck_pocket.md: escalating unstick (climb toward the goal, slide one side, then a long jet climb)
        self.unstick_v2 = bool((load_params().get("unstick") or {}).get("v2", False))
        self.upg_ctx = bool((load_params().get("upgrade_ctx") or {}).get("enabled", False))
        self.foe_kit = {}                # enemy id -> tuple of weapon kinds last seen on it
        # counter-aware weapon rank (params.json "weapon_ctx"): WEAPON_RANK shifted by the weapons enemies carry
        wp = load_params().get("weapon_ctx") or {}
        self.wpn_ctx = bool(wp.get("enabled", False))
        self.wpn_k = float(wp.get("counter", 1.0))          # rank shift at 100% of foes beaten / beating us
        self.wpn_n0 = float(wp.get("shrink_n", 3))          # shares shrink by n / (n + shrink_n) for n foes seen
        self.wpn_margin = float(wp.get("swap_margin", 0.5)) # a pickup must out-rank what it replaces by this much
        self.wpn_mortar_gun = float(wp.get("mortar_gun_swap", 1.6))   # mortar replaces the gun at this rank
        self._rank_t, self._rank = None, dict(WEAPON_RANK)
        # special guard (params.json "special_guard"): no weapon swap that drops a held weapon while in a fight;
        # the new weapon can't fire for 1-1.65 s and the dropped one may go to the enemy we're fighting
        gp = load_params().get("special_guard") or {}
        self.guard = bool(gp.get("enabled", False))
        self.guard_r = float(gp.get("enemy_r", 150))       # a visible enemy mech this close = in a fight
        self.guard_s = float(gp.get("quiet_s", 2.5))       # ...or we took weapon damage this recently
        # mortar lead (params.json "mortar_lead"): aim the shell where the target will be when it lands
        mp = load_params().get("mortar_lead") or {}
        self.mortar_lead = bool(mp.get("enabled", False))
        self.mlead_k = float(mp.get("lead_frac", 0.8))     # share of the straight-line prediction (targets strafe)
        self.mlead_max = float(mp.get("max_lead_m", 40))   # cap on the lead offset
        ee = load_params().get("early_evade") or {}
        self.early_evade = {"enabled": bool(ee.get("enabled", True)), "attackers": int(ee.get("attackers", 2)),
                            "hp_frac": float(ee.get("hp_frac", 0.8)), "window_s": float(ee.get("window_s", 2.0))}
        uh = load_params().get("unseen_hit") or {}
        self.unseen_p = {"enabled": bool(uh.get("enabled", False)), "cover": bool(uh.get("cover", True)),
                         "face": bool(uh.get("face", True)), "window_s": float(uh.get("window_s", 1.5)),
                         "finish_s": float(uh.get("finish_s", 1.5)), "hp_frac": float(uh.get("hp_frac", 1.01))}
        ef = load_params().get("evade_fix") or {}
        self.evade_fix = {"enabled": bool(ef.get("enabled", False)), "commit_s": float(ef.get("commit_s", 2.5)),
                          "radii": tuple(ef.get("radii", (8, 16, 26, 40, 55, 70)))}
        self.evade_until = -1.0          # evade_fix: once evade starts, keep at it until then (no fight/evade dithering)
        self.unseen = []                 # [(t, bearing)] of hits in the last window_s by mechs we can't see, newest first
        rp = load_params().get("roof") or {}
        self.roof_start = float(rp.get("start_s", 100))
        self.rp, self.roof, self.roof_key, self.climb_until, self.roof_app = None, None, None, -1.0, None
        if rp.get("enabled", True) and self.map is not None:
            try:
                self.rp = roof.RoofPlanner(hello["map"]["dir"], self.map.ground)
            except Exception:
                mf.log("roof planner init failed:\n" + traceback.format_exc())   # recent stuck spots (t, x, y); sidestep side
        # zone tracker (H-ZON) and supply-drop planner (H-DRP): any failure = that component has no opinion
        params = load_params()
        self.zt = self.dp = None
        self.zp, self.dd = None, drops.DropDecision(reason="off")
        try:
            if (params.get("zone") or {}).get("enabled", True):
                self.zt = zone.ZoneTracker(hello, params.get("zone"))
        except Exception:
            mf.log("zone tracker init failed:\n" + traceback.format_exc())
        try:
            if (params.get("drops") or {}).get("enabled", True):
                self.dp = drops.DropPlanner(hello, params.get("drops"))
        except Exception:
            mf.log("drop planner init failed:\n" + traceback.format_exc())
        # late-game placement (late.py): from the 4th circle on, hold a concealed spot inside the next circle
        self.lp = None
        try:
            if (params.get("late") or {}).get("enabled", False) and self.map is not None:
                self.lp = late.LatePlanner(self.map, params.get("late"))
        except Exception:
            mf.log("late planner init failed:\n" + traceback.format_exc())
        # Step 1 (research: potential-field dodging): sidestep incoming bullets and mortar shells; learn shooter
        # positions from beams. Hitscan lasers can't be strafed (the shot goes where we are when it is released).
        dp_ = params.get("dodge") or {}
        on = dp_.get("enabled", True)
        self.dodge_on = bool(on) and bool(dp_.get("bullets", True) or dp_.get("mortars", True))
        self.dodge_bullets, self.dodge_mortars = bool(dp_.get("bullets", True)), bool(dp_.get("mortars", True))
        self.beams_on = bool(on) and bool(dp_.get("beams", True))
        self.dodge_weight = float(dp_.get("weight", 1.5))
        self.dodge_flip = 1

    # ================================================================== main
    def act(self, obs):
        t0 = time.perf_counter()
        self.deadline = t0 + BUDGET_S
        me = obs["self"]
        self.me, self.t = me, obs["t"]
        x, y, z = me["pos"]
        self.x, self.y, self.z = x, y, z
        self.stats = me.get("stats", {})
        self._remember(obs)
        self._zone(obs)
        self.zp = None
        if self.zt is not None:
            try:
                self.zp = self.zt.update(obs)
            except Exception:
                self.zp = None
        self.dd = drops.DropDecision(reason="off")
        if self.dp is not None:
            self.dd = self.dp.step(obs, zone_plan=self.zp)   # never raises

        act = {"tick": obs["tick"]}
        if self.upg_ctx or self.wpn_ctx:
            self._note_foes(obs)
        if obs.get("offer"):
            act["pick"] = self._pick_upgrade(obs["offer"])

        enemies = [m for m in obs["mechs"] if m["kind"] == "mech"]
        npcs = [m for m in obs["mechs"] if m["kind"] == "npc"]
        for e in enemies + npcs:
            e["_d"] = math.dist(e["pos"][:2], (x, y))
        enemies.sort(key=lambda e: e["_d"])
        for e in enemies:
            self.known[e["id"]] = (self.t, e["pos"][0], e["pos"][1])
        if self.beams_on:      # a beam or arc starts at its shooter's muzzle: that is a known position even if we can't see it
            seen_ids = {e["id"] for e in enemies}
            for b in obs.get("beams", ()):
                if b.get("by") not in seen_ids and b.get("path"):
                    self.known[b["by"]] = (self.t - b.get("age", 0.0), b["path"][0][0], b["path"][0][1])
        self.known = {k: v for k, v in self.known.items() if self.t - v[0] < 12}
        hp_frac = me["hp"] / max(1.0, me["max_hp"])
        recently_hurt = self.t - self.last_hurt_t < 2.5

        if not hasattr(self, "heal_gate_hp"):
            heal_gate = load_params().get("heal_gate") or {}
            self.heal_gate_hp = heal_gate.get("hp_frac", 0.7) if heal_gate.get("enabled") else 0.0
        healing = hp_frac < self.heal_gate_hp
        target = self._choose_target(enemies, npcs, healing)
        # everyone we know about nearby, including ones that just ducked out of view
        threats = [(kx, ky) for (_, kx, ky) in self.known.values() if math.hypot(kx - x, ky - y) < 220]
        up = self.unseen_p
        self.unseen = []
        if up["enabled"]:
            seen_ids = {e["id"] for e in enemies}
            self.unseen = sorted(((at, b) for i, (at, b) in self.attackers.items()
                                  if i < 100 and i not in seen_ids and b is not None and self.t - at < up["window_s"]),
                                 reverse=True)
            # cover must also block whoever is shooting us from out of sight (sim: most spawn deaths are rear hits from them)
            threats += [(x + 80 * math.cos(b), y + 80 * math.sin(b)) for _, b in self.unseen[:2]]
        if recently_hurt and self.hurt_bearing is not None and not any(
                self.attackers.get(e["id"], (-99,))[0] > self.t - 2.5 for e in enemies):
            threats.append((x + 80 * math.cos(self.hurt_bearing), y + 80 * math.sin(self.hurt_bearing)))
        m = self.map
        exposed = [e for e in enemies if e["_d"] < 200 and (m is None or m.los(x, y, e["pos"][0], e["pos"][1]))]

        move, boost, why = None, False, ""
        need_zone, hurry = self._zone_need()
        zp = self.zp
        zone_crit = zp is not None and zp.goal is not None and zp.urgency >= zone.CRITICAL
        if zone_crit:                    # the escape would cost a lot of HP: go now (H-ZON)
            need_zone = hurry = True
        if not need_zone:
            self.zone_commit = False
        elif hurry or not me["in_zone"]:
            self.zone_commit = True
        hurry = hurry or self.zone_commit
        close = [e for e in enemies if e["_d"] < 150]
        on_roof, roof_go = self._roof_state()
        dd = self.dd
        capturing = dd.goal is not None and dd.phase == "capture"
        late_on = self.lp is not None and self.lp.active(self.zn)

        # ---------------------------------------------------------- modes
        if not me["in_zone"] or hurry:
            self.mode, why = "zone", "outside" if not me["in_zone"] else ("critical" if zone_crit else "late")
            move = self._go_circle(self.gx, self.gy, self.gr)
            boost = me["energy"] > 20 and (not me["in_zone"] or hurry)
        elif on_roof:
            # up high: stand back from the edges (ground bots can't see us there), shoot whatever we can see
            sx, sy = self.roof.stand
            self.mode, why = "roof", f"top {self.roof.top:.0f}"
            move = None if math.hypot(sx - x, sy - y) < 2.5 else norm(sx - x, sy - y)
        elif roof_go and self.t < self.climb_until:
            self.mode, why = "climb", f"to {self.roof.top:.0f}"
            move = norm(self.roof.stand[0] - x, self.roof.stand[1] - y)
        elif capturing:
            # inside a ring we hold: 4 s alone = 3 cubes + full HP. Stay (and keep shooting) unless it stalls.
            self.mode, why = "drop", dd.reason
            move = dd.move if dd.move and (dd.move[0] or dd.move[1]) else None
        elif threats and ((not self.aggro and (self._third_party(target, enemies, exposed)
                                                or self._should_evade(close, hp_frac, recently_hurt, target)))
                          or (self.aggro and hp_frac < 0.25 and len(exposed) >= 2)
                          or self._multi_hit(hp_frac)
                          or self._unseen_cover(target, hp_frac)
                          or (self.t < self.evade_until and not self._finishing(target))):
            if self.mode != "evade" and self.evade_fix["enabled"]:
                self.evade_until = self.t + self.evade_fix["commit_s"]
            self.mode = "evade"
            move, why = self._evade(threats)
            boost = me["energy"] > 25 and (hp_frac < 0.6 or len(exposed) >= 2)
        elif healing:
            self.mode, why = "heal_gate", "hold for regen"
            if need_zone:
                move, why = self._go_circle(self.gx, self.gy, self.gr), "into next circle"
            else:
                visible_threats = [(tx, ty) for tx, ty in threats if m is None or m.los(x, y, tx, ty)]
                if visible_threats:
                    move, why = self._evade(visible_threats)
        elif target is not None:
            self.mode, why = "fight", f"#{target['id']}"
            move = self._fight_move(target)
            lt_held = any(w and w["kind"] == "lightning" for w in me["weapons"])
            if (lt_held and target["kind"] == "mech" and target["_d"] > 40 and hp_frac > 0.5
                    and len(exposed) <= 1 and me["energy"] > 35):
                why += " close in"
                move = self._go_point(target["pos"][0], target["pos"][1], 30.0)
                boost = target["_d"] > 60
        elif roof_go:
            move, why = self._roof_travel()
        elif self.aggro and self.known and hp_frac > 0.4 and not (late_on and self.lp.p.no_hunt):
            # nobody in sight but we know where they are: go get them (the practice bots are weak)
            kid, (kt, kx, ky) = min(self.known.items(), key=lambda kv: math.hypot(kv[1][1] - x, kv[1][2] - y))
            self.mode, why = "hunt", f"#{kid}"
            move = self._go_point(kx, ky, 20.0)
        elif any(e["_d"] < 150 for e in exposed) or (threats and self.t - self.last_hurt_t < 6):
            self.mode = "hide"
            move, why = self._evade(threats)
        else:
            drop = dd.goal is not None
            loot = None if drop else self._loot_goal(obs)
            if late_on and loot and loot[2] == "get cube" and me.get("cubes", 0) >= self.lp.p.cube_cap:
                loot = None          # past the stat cap a cube only makes us bigger
            if drop:
                self.mode, why = "drop", f"{dd.drop_id} {dd.phase} {dd.reason}"
                gx, gy = dd.goal[0], dd.goal[1]
                move = None if math.hypot(gx - x, gy - y) < 2.0 else self._go_point(gx, gy)
                boost = dd.boost and me["energy"] > 30
            elif loot:
                self.mode, why = "loot", loot[2]
                move = self._go_point(loot[0], loot[1])
            elif late_on:
                spot = None
                try:
                    spot = self.lp.update(x, y, self.gx, self.gy, self.gr,
                                          min(self.deadline - 0.010, time.perf_counter() + 0.006))
                except Exception:
                    mf.log("late planner failed:\n" + traceback.format_exc())
                    self.lp = None
                if spot is None:
                    self.mode, why = "late", "search"
                    move = self._go_circle(self.gx, self.gy, self.gr)
                elif math.hypot(spot[0] - x, spot[1] - y) > 2.5:
                    self.mode, why = "late", f"to spot hp {hp_frac:.0%}"
                    move = self._go_point(spot[0], spot[1], 2.0)
                else:
                    self.mode, why = "late", f"hold hp {hp_frac:.0%}"
                    move = None
            elif hp_frac < 0.92 and self.t - max(self.last_hurt_t, self.last_dealt_t) < 30:
                self.mode, why = "heal", f"hp {hp_frac:.0%}"
                move = None if not need_zone else self._go_circle(self.gx, self.gy, self.gr)
            elif need_zone:
                self.mode, why = "move", "into next circle"
                move = self._go_circle(self.gx, self.gy, self.gr)
            elif self.t < 180 and hp_frac > 0.8:
                # nothing to do early: roam the safe zone to find crates, NPCs and weapons (cubes = HP + damage)
                roam_failed = (self.roam_fix and self.roam is not None and self.fail_goal is not None
                               and self.fail_goal == self._goal_key(self.roam[0], self.roam[1], 6.0))
                if (self.roam is None or self.t > self.roam_t or roam_failed
                        or math.hypot(self.roam[0] - x, self.roam[1] - y) < 8):
                    for _ in range(6 if self.roam_fix else 1):
                        a = self.rng.uniform(0, TAU)
                        r = self.rng.uniform(40, 110)
                        px, py = x + r * math.cos(a), y + r * math.sin(a)
                        if not self.in_safe(px, py, ahead=30):
                            px, py = self.gx + (px - self.gx) * 0.3, self.gy + (py - self.gy) * 0.3
                        if not self.roam_fix or self.map is None or self.map.nearest_free(px, py, max_r=2) >= 0:
                            break
                    self.roam, self.roam_t = (px, py), self.t + 20
                self.mode, why = "roam", ""
                move = self._go_point(self.roam[0], self.roam[1], 6.0)
            else:
                self.mode, why = "hold", ""
                move = None

        # ---------------------------------------------------------- legs
        if self.mode == "drop" and capturing:
            mv, jump, boost2 = (move if move is not None else (0.0, 0.0)), False, False   # small in-ring steps, no jets
        elif self.mode == "roof":
            mv, jump, boost2 = (move if move is not None else (0.0, 0.0)), False, False
        elif self.mode == "climb":
            # jump, then jet while airborne until the feet clear the roof edge, pressing toward the stand point
            mv = move
            jump = me["grounded"]
            boost2 = (not me["grounded"]) and z < self.roof.top + 1.5
            boost = False
        else:
            mv = self._steer(move) if move is not None else (0.0, 0.0)
            if self.unstick_v2:
                mv, jump, boost2 = self._unstick_v2(mv, move)
            else:
                mv, jump, boost2 = self._unstick(mv, move is not None)
            if self.dodge_on and self.t >= self.escape_until:
                dv, dwhy = self._dodge(obs)
                if dv is not None:
                    w = self.dodge_weight
                    mv = self._steer(norm(mv[0] + dv[0] * w, mv[1] + dv[1] * w))
                    why = (why + " " if why else "") + "dodge " + dwhy
                    mf.draw.line([x, y, z + 2], [x + dv[0] * 12, y + dv[1] * 12, z + 2], "#ffffff")
        if move is not None and self.mode in ("move", "loot", "heal", "drop") and not boost and not boost2:
            pass  # walking at full speed: faster than sneaking, and the squad hunts us anyway
        act["move"] = [round(mv[0], 3), round(mv[1], 3)]
        act["boost"] = bool(boost or boost2)
        if jump:
            act["jump"] = True

        # ---------------------------------------------------------- torso and weapons
        self._aim_and_fire(act, obs, target, mv)
        loot_take = self._take(obs)
        if loot_take:
            act.update(loot_take)

        botlog.trace(obs["tick"], mode=self.mode, why=why, target=None if target is None else target["id"],
                     hp=round(me["hp"]), zone=zp.urgency_name if zp else None,
                     drop=f"{dd.drop_id}|{dd.phase}" if dd.goal is not None else dd.reason, ms=round((time.perf_counter() - t0) * 1000, 2))
        mf.draw.label(f"{self.mode} {why} hp {me['hp']:.0f}")
        return act

    # ================================================================== dodge
    def _dodge(self, obs):
        """(unit dodge direction, why) for enemy bullets that will hit us within ~0.6 s and mortar shells landing within
        splash range; (None, "") when nothing is coming. Gun bullets fly straight, so we step sideways off their line."""
        me = self.me
        projs = obs.get("projectiles") or ()
        if not projs:
            return None, ""
        st = self.stats
        rad = st.get("radius", 2.5) + 1.0                       # cylinder radius plus a margin
        half_h = st.get("height", 9.0) / 2 + 1.0
        cx, cy, cz = self.x, self.y, self.z + st.get("height", 9.0) / 2
        mvx, mvy, mvz = me["vel"]
        g = self.w["mortar"].get("gravity", 22.0)
        splash = self.w["mortar"].get("splash_radius", 7.0)
        dx_sum = dy_sum = 0.0
        n_b = n_m = 0
        for p in projs:
            kind = p.get("kind")
            px, py, pz = p["pos"]
            vx, vy, vz = p["vel"]
            if kind in ("gun", "npc") and self.dodge_bullets:
                rvx, rvy, rvz = vx - mvx, vy - mvy, vz - mvz
                s2 = rvx * rvx + rvy * rvy + rvz * rvz
                if s2 < 1e-6:
                    continue
                rx, ry, rz = px - cx, py - cy, pz - cz
                ts = -(rx * rvx + ry * rvy + rz * rvz) / s2     # time of closest approach
                if ts < 0.0 or ts > 0.6:
                    continue
                hx, hy, hz = rx + rvx * ts, ry + rvy * ts, rz + rvz * ts
                if math.hypot(hx, hy) > rad or abs(hz) > half_h:
                    continue                                    # it passes us
                sp = math.hypot(vx, vy)
                if sp < 1e-6:
                    continue
                perp = (-vy / sp, vx / sp)
                lat = hx * perp[0] + hy * perp[1]               # which side of its line we are on
                sgn = (1.0 if lat > 0 else -1.0) if abs(lat) > 0.3 else self.dodge_flip
                self.dodge_flip = sgn
                wgt = 1.0 / (0.15 + ts)
                dx_sum += perp[0] * sgn * wgt
                dy_sum += perp[1] * sgn * wgt
                n_b += 1
            elif kind == "mortar" and self.dodge_mortars:
                dz = pz - self.z
                disc = vz * vz + 2 * g * dz
                if disc < 0:
                    continue
                tl = (vz + math.sqrt(disc)) / g                 # time until it reaches our ground level
                if tl < 0.1 or tl > 2.0:
                    continue
                lx, ly = px + vx * tl, py + vy * tl
                dl = math.hypot(lx - self.x, ly - self.y)
                if dl > splash + 3.0:
                    continue
                if dl < 1.0:
                    ux, uy = -vy, vx                            # dead centre: leave sideways
                else:
                    ux, uy = self.x - lx, self.y - ly
                ux, uy = norm(ux, uy)
                wgt = 2.0
                dx_sum += ux * wgt
                dy_sum += uy * wgt
                n_m += 1
        if not (n_b or n_m):
            return None, ""
        d = norm(dx_sum, dy_sum)
        if d == (0.0, 0.0):
            return None, ""
        return d, (f"{n_b}b" if n_b else "") + (f"{n_m}m" if n_m else "")

    # ================================================================== memory
    def _remember(self, obs):
        t = self.t
        for e in obs.get("events", []):
            k = e.get("type")
            if k == "damaged":
                if e.get("weapon") != "zone":
                    self.last_hurt_t = t
                    if e.get("bearing") is not None:
                        self.hurt_bearing = e["bearing"]
                    if e.get("by") is not None:
                        self.attackers[e["by"]] = (t, e.get("bearing"))
            elif k == "hit":
                self.last_dealt_t = t
            elif k == "effect" and e.get("effect") == "short":
                self.short_until = t + self.w["lightning"].get("short_s", 2)
        for s in obs.get("sounds", []):
            if s["kind"] in ("gun", "laser", "laser_charge", "lightning", "mortar") and s["dist"] in ("near", "mid"):
                self.heard = (t - s.get("age", 0), s["bearing"], s["dist"])
        self.hist.append((t, self.x, self.y))
        if len(self.hist) > 30:
            del self.hist[:-30]

    # ================================================================== zone
    def _zone(self, obs):
        zn = obs["zone"]
        key = (round(zn["next_center"][0], 1), round(zn["next_center"][1], 1), round(zn["next_radius"], 1))
        if key != self.zone_key:
            self.zone_key = key
            self.phase_start = (zn["center"][0], zn["center"][1], zn["radius"])
            self.job = None
        self.zn = zn
        nr = zn["next_radius"]
        margin = min(40.0, max(6.0, nr * 0.25))
        self.gx, self.gy = zn["next_center"]
        self.gr = max(3.0, nr - margin)

    def circle_at(self, t):
        zn, (cx, cy, r) = self.zn, self.phase_start
        ss, se = zn["shrink_start"], zn["shrink_end"]
        if t <= ss:
            return cx, cy, r
        nx, ny = zn["next_center"]
        if t >= se or se <= ss:
            return nx, ny, zn["next_radius"]
        f = (t - ss) / (se - ss)
        return cx + (nx - cx) * f, cy + (ny - cy) * f, r + (zn["next_radius"] - r) * f

    def _zone_need(self):
        """(want to move into the next circle, must hurry)."""
        d = math.hypot(self.x - self.gx, self.y - self.gy)
        if d <= self.gr:
            return False, False
        speed = self.stats.get("walk_speed", 11.7)
        travel = (d - self.gr) / speed * 1.35 + 3
        left = self.zn["shrink_end"] - self.t
        # hurry if the shrinking edge would catch us before we get in
        cx, cy, r = self.circle_at(self.t + travel)
        caught = math.hypot(self.x - cx, self.y - cy) > r - 5
        return True, caught or travel > left

    def in_safe(self, px, py, ahead=8.0):
        cx, cy, r = self.circle_at(self.t + ahead)
        return math.hypot(px - cx, py - cy) < r - 4

    # ================================================================== targeting
    def _choose_target(self, enemies, npcs, healing=False):
        best, best_s = None, -1e9
        now = self.t
        laser = any(w and w["kind"] == "laser" for w in self.me["weapons"])
        far = 250 if laser else 130          # laser: hitscan 315 dmg to 280 m, snipe the hunter on its way in
        for e in enemies:
            hit = self.attackers.get(e["id"])
            shooting_us = hit and now - hit[0] < 4
            if healing and not shooting_us:
                continue
            if e["_d"] > max(230, far) or (e["_d"] > far and not shooting_us and not self.aggro):
                continue  # don't start long-range fights: they only draw the squad in
            s = -e["_d"] * 0.05
            if shooting_us:
                s += 6
            if "hp" in e and e.get("max_hp"):
                s += (1 - e["hp"] / e["max_hp"]) * 5
            if e["id"] == self.target_id:
                s += 2  # stickiness
            if s > best_s:
                best, best_s = e, s
        if best is None:
            for n in npcs:
                hit = self.attackers.get(n["id"])
                attacking = hit and now - hit[0] < 4
                hp_ok = self.me["hp"] > 0.5 * self.me["max_hp"]
                if attacking or (not healing and hp_ok and self.t < 240 and n["_d"] < 150):  # 350 HP, 2 cubes each
                    if best is None or n["_d"] < best["_d"]:
                        best = n
        self.target_id = best["id"] if best else None
        return best

    def _roof_state(self):
        """(on our roof, want to go to it). Picks / drops the roof as the zone moves."""
        if self.rp is None or self.t < self.roof_start:
            return False, False
        safe = lambda px, py: self.in_safe(px, py, ahead=40)
        if self.roof is not None and (self.zone_key != self.roof_key or not safe(*self.roof.stand)):
            if not safe(*self.roof.stand):
                self.roof = None
            self.roof_key = self.zone_key
        if self.roof is None:
            self.roof = self.rp.choose(self.x, self.y, safe, self.zn["next_center"], self.zn["next_radius"])
            self.roof_key = self.zone_key
            if self.roof is None:
                return False, False
        on = self.z > self.roof.top - 1.5 and self.roof.contains(self.x, self.y)
        return on, not on

    def _roof_travel(self):
        """Walk to the wall, wait for enough energy to clear it, then start the climb."""
        r = self.roof
        if self.roof_app is None or self.roof_app[0] is not r:
            # fixed approach point per roof (a moving goal restarts A* every tick), snapped to free ground
            ax, ay = self.rp.approach(r, self.x, self.y)
            k = self.map.nearest_free(ax, ay, max_r=6)
            if k >= 0:
                ax, ay = self.map.center(k)
            self.roof_app = (r, ax, ay)
        _, ax, ay = self.roof_app
        d = math.hypot(ax - self.x, ay - self.y)
        if d > 4.0:
            self.mode = "to_roof"
            return self._go_point(ax, ay, 3.0), f"{d:.0f} m"
        need = min(100.0, (r.top - self.z) / 60.0 * 100.0 + 8.0)
        if self.me["energy"] < need:
            self.mode = "roof_wait"
            return None, f"energy {self.me['energy']:.0f}/{need:.0f}"
        self.mode = "climb"
        self.climb_until = self.t + 7.0
        return norm(r.stand[0] - self.x, r.stand[1] - self.y), "go"

    def _ttk(self, target):
        """Seconds to kill the target with the gun at its range (reload and accuracy included); None if unknown."""
        if target is None or target["kind"] != "mech" or target.get("hp") is None:
            return None
        g = self.w["gun"]
        mag, cd, rl = g.get("mag", 12), g.get("cooldown", 0.24), g.get("reload", 2.4)
        d = target["_d"]
        acc = 0.66 if d < 80 else (0.5 if d < 150 else 0.3)
        kinds = {w["kind"] for w in self.me["weapons"] if w}
        dps = g.get("damage", 45) / cd * (mag * cd) / (mag * cd + rl) * acc if "gun" in kinds else 0.0
        lt, la = self.w["lightning"], self.w["laser"]
        if "lightning" in kinds and d < lt.get("range", 45):
            dps = max(dps, lt["damage"] / lt["cooldown"] * 0.9)
        if "laser" in kinds and d < la.get("range", 280):
            dps = max(dps, la["damage"] / (la["charge"] + la["cooldown"]) * (0.85 if d < 150 else 0.6))
        return target["hp"] / max(dps, 1.0)

    def _third_party(self, target, enemies, exposed):
        """Back off when someone else can start shooting us before we finish the target (time to kill + 1 s),
        or something we can't see is hitting us; stay if the target dies within 1.2 s."""
        ttk = self._ttk(target)
        if ttk is None:
            return len(exposed) >= 2                        # no fight to finish: v2's rule
        if ttk < 1.2:
            return False
        t, m = self.t, self.map
        seen = {e["id"] for e in enemies}
        if any(i not in seen and i < 100 and at > t - 2.0 for i, (at, _) in self.attackers.items()):   # mech ids 0-15
            return True                                     # an unseen enemy is hitting us
        for e in enemies:
            if e is target:
                continue
            d = e["_d"]
            los = m is None or m.los(self.x, self.y, e["pos"][0], e["pos"][1])
            if self.attackers.get(e["id"], (-99,))[0] > t - 2.0 or (los and d < 150):
                tts = 0.0
            else:
                tts = max(0.0, d - 150) / 12.0 + (0.0 if los else 2.0)
            if tts < ttk + 1.0:
                return True
        return False

    def _multi_hit(self, hp_frac):
        """Step 2: two or more different mechs hit us within window_s while we are below hp_frac: we are being flanked
        (sim: most spawn-time deaths are 12-16 s duels where a second and third shooter join and hit our back). Break
        off to cover now instead of at 25% HP."""
        ep = self.early_evade
        if not ep["enabled"] or hp_frac >= ep["hp_frac"]:
            return False
        recent = {i for i, (at, _) in self.attackers.items() if i < 100 and self.t - at < ep["window_s"]}
        return len(recent) >= ep["attackers"]

    def _finishing(self, target):
        ttk = self._ttk(target)
        return ttk is not None and ttk < self.unseen_p["finish_s"]

    def _unseen_cover(self, target, hp_frac):
        """unseen_hit: a mech we can't see hit us within window_s: get out of its line (and the target's) unless
        the target dies first. Sim: in 6 of 8 deaths before 25 s most damage came from such a shooter, in our back."""
        up = self.unseen_p
        return bool(up["enabled"] and up["cover"] and self.unseen and hp_frac < up["hp_frac"]
                    and not self._finishing(target))

    def _should_evade(self, close, hp_frac, recently_hurt, target):
        if len(close) >= 3:
            return True
        if target is not None and target["kind"] == "mech" and "hp" in target and target.get("max_hp"):
            their = target["hp"] / target["max_hp"]
            if hp_frac < 0.4 and their > hp_frac + 0.1:
                return True
            return False
        if target is None and recently_hurt:
            return hp_frac < 0.7  # shot by something we can't see
        return hp_frac < 0.3 and target is not None

    # ================================================================== movement goals
    def _evade(self, threats):
        m = self.map
        if m is not None and (self.cover is None or self.t - self.cover_t > 0.6):
            ok = lambda px, py: self.in_safe(px, py)
            self.cover = m.find_cover(self.x, self.y, threats[:4], ok, radii=self.evade_fix["radii"] if self.evade_fix["enabled"] else (8, 16, 26, 40), dirs=16,
                                      deadline=self.deadline - 0.006)
            self.cover_t = self.t
        if self.cover:
            cx, cy, _ = self.cover
            if math.hypot(cx - self.x, cy - self.y) < 2.5:
                return None, "in cover"
            return norm(cx - self.x, cy - self.y), "to cover"
        # no cover: away from the threats, pulled toward the zone center
        ax = sum(self.x - tx for tx, _ in threats)
        ay = sum(self.y - ty for _, ty in threats)
        ux, uy = norm(ax, ay)
        zx, zy = norm(self.gx - self.x, self.gy - self.y)
        return norm(ux + zx * 0.6, uy + zy * 0.6), "away"

    def _fight_move(self, tgt):
        tx, ty = tgt["pos"][0], tgt["pos"][1]
        d = tgt["_d"]
        ux, uy = norm(tx - self.x, ty - self.y)
        if self.t > self.strafe_until:
            self.strafe_sign = self.rng.choice((-1, 1))
            self.strafe_until = self.t + self.rng.uniform(0.8, 2.0)
        px, py = -uy * self.strafe_sign, ux * self.strafe_sign
        lo, hi = self._range_band()
        radial = 0.0
        if d < lo:
            radial = -0.8
        elif d > hi:
            radial = 0.8
        vx, vy = px + ux * radial, py + uy * radial
        if not self.in_safe(self.x + vx * 10, self.y + vy * 10):
            zx, zy = norm(self.gx - self.x, self.gy - self.y)
            vx, vy = vx + zx * 1.5, vy + zy * 1.5
        return norm(vx, vy)

    def _range_band(self):
        kinds = {w["kind"] for w in self.me["weapons"] if w}
        if "lightning" in kinds:
            return 15, 38
        if "laser" in kinds:
            return 50, 150
        if "mortar" in kinds:
            return 60, 170
        return 35, 110

    def _loot_goal(self, obs):
        me, x, y = self.me, self.x, self.y
        slots = me["weapons"]
        have = {w["kind"] for w in slots if w}
        R = self._ranks()
        worst = min((R[w["kind"]] for w in slots[1:] if w), default=-1)
        margin = self.wpn_margin if self.wpn_ctx else 1e-9
        best, best_s = None, -1e9
        for p in obs.get("pickups", []):
            if p["kind"] in have or abs(p["pos"][2] - self.z) > 3.5:
                continue
            gain = R[p["kind"]] - worst
            if gain < margin and not self._gun_swap(p["kind"]):
                continue
            gain = max(gain, 1)
            d = math.dist(p["pos"][:2], (x, y))
            reach = (250 if self.t < 120 else 150) if not (have & set(SPECIAL)) else 90
            if d < reach and self.in_safe(p["pos"][0], p["pos"][1]):
                s = gain * 30 - d
                if s > best_s:
                    best, best_s = (p["pos"][0], p["pos"][1], f"get {p['kind']}"), s
        if best:
            return best
        for c in obs.get("cubes", []):
            d = math.dist(c["pos"][:2], (x, y))
            if d < 120 and abs(c["pos"][2] - self.z) < 3.5 and self.in_safe(c["pos"][0], c["pos"][1]):
                return (c["pos"][0], c["pos"][1], "get cube")
        cr = self._crate(obs, 200 if self.t < 120 and not (have & set(SPECIAL)) else 150)
        if cr is not None:
            d = math.dist(cr["pos"][:2], (x, y))
            if d > 35:
                return (cr["pos"][0], cr["pos"][1], "crate")
        return None

    def _crate(self, obs, max_d):
        """Nearest crate on our level, inside the safe zone, worth breaking (cube + 50% weapon); None if none."""
        if self.t > 300 or self.me["hp"] < 0.7 * self.me["max_hp"]:
            return None
        best, best_d = None, max_d
        for c in obs.get("crates", []):
            if abs(c["pos"][2] - self.z) > 3.5 or not self.in_safe(c["pos"][0], c["pos"][1]):
                continue
            d = math.dist(c["pos"][:2], (self.x, self.y))
            if d < best_d:
                best, best_d = c, d
        return best

    def _in_fight(self, obs):
        t = self.t
        if t - self.last_hurt_t < self.guard_s:   # (not last_dealt_t: shooting a crate isn't a fight)
            return True
        return any(m.get("kind") == "mech" and math.dist(m["pos"][:2], (self.x, self.y)) < self.guard_r
                   for m in obs.get("mechs", []))

    def _gun_swap(self, kind):
        """True if a pickup of this kind should replace the gun in slot 0 (we already hold another special)."""
        slots = self.me["weapons"]
        g, s1 = slots[0], slots[1] if len(slots) > 1 else None
        ok = kind in SPECIAL or (self.wpn_ctx and kind == "mortar" and self._ranks()["mortar"] >= self.wpn_mortar_gun)
        return (ok and g is not None and g["kind"] == "gun" and s1 is not None
                and s1["kind"] != kind and s1["kind"] in SPECIAL + ("mortar",))

    def _take(self, obs):
        slots = self.me["weapons"]
        have = {w["kind"] for w in slots if w}
        for p in obs.get("pickups", []):
            if p["kind"] in have:
                continue
            if math.dist(p["pos"][:2], (self.x, self.y)) > self.pickup_r - 0.3 or abs(p["pos"][2] - self.z) > 3.8:
                continue
            if slots[1] is None:
                return {"take": p["id"]}
            if self.guard and self._in_fight(obs):
                return None              # every remaining case drops a weapon: wait until the fight is over
            R = self._ranks()
            margin = self.wpn_margin if self.wpn_ctx else 1e-9
            if R[p["kind"]] - R[slots[1]["kind"]] >= margin and not slots[1].get("charge"):
                # a better special: if the gun can go instead, keep both specials
                if self._gun_swap(p["kind"]) and slots[1]["kind"] in SPECIAL:
                    return {"take": p["id"], "drop": 0}
                return {"take": p["id"], "drop": 1}
            if self._gun_swap(p["kind"]):
                return {"take": p["id"], "drop": 0}
        return None

    def _ranks(self):
        """WEAPON_RANK, shifted (flag weapon_ctx) by the share of seen enemies each weapon beats minus the share
        that beats it. Shares shrink toward 0 while few enemies have been seen. Cached per decision."""
        if not self.wpn_ctx:
            return WEAPON_RANK
        t = getattr(self, "t", None)
        if t is not None and t == self._rank_t:
            return self._rank
        r = dict(WEAPON_RANK)
        try:
            n = len(self.foe_kit)
            if n:
                sh = self._foe_share()
                f = self.wpn_k * n / (n + self.wpn_n0)
                for k, prey in BEATS.items():
                    hunter = next(h for h, v in BEATS.items() if v == k)
                    r[k] += f * (sh.get(prey, 0.0) - sh.get(hunter, 0.0))
        except Exception:
            r = dict(WEAPON_RANK)
        self._rank_t, self._rank = t, r
        return r

    def _note_foes(self, obs):
        for m in obs.get("mechs", []):
            if m.get("kind") == "mech" and isinstance(m.get("weapons"), list):
                self.foe_kit[m.get("id")] = tuple(w for w in m["weapons"] if isinstance(w, str))

    def _foe_share(self):
        """Share of the enemy mechs we have seen that carry each special (0..1), from their last-seen loadout."""
        n = len(self.foe_kit)
        if not n:
            return {}
        return {k: sum(k in kit for kit in self.foe_kit.values()) / n for k in ("laser", "mortar", "lightning")}

    def _upgrade_scores(self, ids):
        held = [w["kind"] for w in self.me["weapons"] if w and w.get("kind") in WEAPON_RANK]
        primary = max(held, key=lambda k: WEAPON_RANK[k], default="gun")
        foe = self._foe_share()
        lz, mo, li = foe.get("laser", 0.0), foe.get("mortar", 0.0), foe.get("lightning", 0.0)
        sc = {}
        for u in ids:
            v = UPG_BASE.get(u)
            for k in held:
                w = UPG_WEAPON.get(k, {}).get(u)
                if w is not None:
                    v = max(v if v is not None else -1e9, w if k == primary else w - 3.0)
            if v is None:
                v = 0.0
            # what we hold vs what they hold
            if u == "lightning_range":
                v += 1.5 * (lz + mo)            # they outrange the arc: reach them sooner
            elif u == "laser_charge":
                v += 1.5 * li                   # beat the short / fire before the arc closes in
            elif u in ("capacitor", "reactor"):
                v += (2.5 if primary == "lightning" else 0.0) + 1.5 * mo   # arcs cost energy, shells drain it
            elif u == "jets":
                v += 1.0 * mo                   # recover from the knock-back
            elif u == "servos":
                v += (2.0 * li if primary != "lightning" else 0.0)   # kite out of the 45 m arc
            elif u == "gyros" and primary == "lightning":
                v += 1.0                        # keep a close strafer in the 30 deg cone
            elif u == "armor":
                v += 0.5 * lz                   # 315-damage bursts: flat reduction
            sc[u] = v
        return sc

    def _pick_upgrade(self, offer):
        ids = [c["id"] for c in offer["choices"]]
        if self.upg_ctx:
            try:
                sc = self._upgrade_scores(ids)
                return max(range(len(ids)), key=lambda i: (sc[ids[i]], -i))
            except Exception:
                pass
        kinds = [w["kind"] for w in self.me["weapons"] if w]
        mine = [u for u in ids if any(u.startswith(k + "_") for k in kinds)]
        pref = UPGRADE_PREF[:3] + sorted(mine, key=lambda u: UPGRADE_PREF.index(u) if u in UPGRADE_PREF else 99) + UPGRADE_PREF[3:]
        for u in pref:
            if u in ids:
                return ids.index(u)
        return 0

    # ================================================================== navigation
    def _go_circle(self, gx, gy, gr):
        d = math.hypot(gx - self.x, gy - self.y)
        if d <= gr:
            return None
        return self._go_point(gx, gy, gr)

    @staticmethod
    def _goal_key(gx, gy, gr):
        return (round(gx / 4), round(gy / 4), round(gr / 4))

    def _go_point(self, gx, gy, gr=1.5):
        m = self.map
        dx, dy = gx - self.x, gy - self.y
        d = math.hypot(dx, dy)
        if m is None or d < 3:
            return norm(dx, dy)
        look = min(d, 60.0)
        ux, uy = dx / d, dy / d
        if m.blocked(self.x, self.y) or m.ray_free(self.x, self.y, self.x + ux * look, self.y + uy * look, m.nav):
            self.path = None
            return (ux, uy)
        goal = self._goal_key(gx, gy, gr)
        replan = self.job_goal != goal or self.path is None and self.job is None or self.t - self.path_t > 5
        if self.roam_fix and goal == self.fail_goal and self.t - self.fail_t < 3.0:
            replan = False   # this goal just failed (unreachable / too far): walk straight, retry in a few s
            if self.job_goal != goal:   # drop a search / path for some other goal so we don't follow it here
                self.job, self.path, self.job_goal = None, None, goal
        if replan and (self.job is None or self.job_goal != goal):
            self.job, self.job_goal = AStar(m, self.x, self.y, gx, gy, gr), goal
        if self.job is not None:
            self.job.step(max(0.001, self.deadline - time.perf_counter() - 0.008))
            if self.job.done:
                self.path, self.path_t, self.job = self.job.path, self.t, None
                if self.path is None:
                    self.fail_goal, self.fail_t = goal, self.t
        if self.path:
            # drop reached waypoints, aim at the furthest visible one
            while len(self.path) > 1 and math.hypot(self.path[0][0] - self.x, self.path[0][1] - self.y) < 4:
                self.path.pop(0)
            for wp in reversed(self.path[:5]):
                if m.ray_free(self.x, self.y, wp[0], wp[1], m.wall):
                    return norm(wp[0] - self.x, wp[1] - self.y)
            if self.t - self.path_t > 1.5:
                self.path = None  # we drifted off it: replan
        return (ux, uy)

    def _steer(self, want):
        """Turn a desired direction into one that doesn't run into a wall in the next few meters."""
        ux, uy = want
        m = self.map
        if m is None or (ux == 0 and uy == 0) or m.blocked(self.x, self.y):
            return (ux, uy)
        if m.ray_len(self.x, self.y, ux, uy, 7.0) >= 6.0:
            return (ux, uy)
        best, best_s = (ux, uy), -1e9
        base = math.atan2(uy, ux)
        for k in range(1, 12):
            for sgn in (1, -1):
                a = base + sgn * k * (math.pi / 12)
                cx, cy = math.cos(a), math.sin(a)
                free = m.ray_len(self.x, self.y, cx, cy, 10.0)
                if free < 3:
                    continue
                s = (cx * ux + cy * uy) + 0.5 * free / 10.0
                if s > best_s:
                    best, best_s = (cx, cy), s
        return best

    def _unstick(self, mv, moving):
        """If we commanded movement for 1.5 s and barely moved, jump-jet over or slide around."""
        t = self.t
        if t < self.escape_until:
            if not self.escape_climb:
                return self.escape_dir, False, False
            jet = self.me["energy"] > 15
            return self.escape_dir, self.me["grounded"], jet and not self.me["grounded"]
        if moving and len(self.hist) >= 16 and (mv[0] or mv[1]):
            t_old, x_old, y_old = self.hist[-16]
            if t - t_old >= 1.4 and math.hypot(self.x - x_old, self.y - y_old) < 2.0:
                again = any(t - st < 10.0 and math.hypot(self.x - sx, self.y - sy) < 6.0 for st, sx, sy in self.stuck_at)
                self.stuck_at = [(st, sx, sy) for st, sx, sy in self.stuck_at if t - st < 10.0] + [(t, self.x, self.y)]
                if again:
                    # the climb failed here before: sidestep along the wall, alternating sides
                    self.side_sign = -self.side_sign
                    self.escape_dir = (-mv[1] * self.side_sign, mv[0] * self.side_sign)
                elif self.me["energy"] > 40:
                    self.escape_dir = mv  # climb over it
                else:
                    a = math.atan2(mv[1], mv[0]) + self.rng.choice((-1, 1)) * self.rng.uniform(1.2, 2.0)
                    self.escape_dir = (math.cos(a), math.sin(a))
                self.escape_climb = not again
                self.escape_until = t + 1.2
                self.path, self.job = None, None
                self.hist.clear()
                return self.escape_dir, not again, False
        return mv, False, False

    def _unstick_v2(self, mv, want):
        """Like _unstick, but escalates when we keep getting stuck at the same spot (docs/stuck_pocket.md):
        even-numbered attempts there climb (jump + jets) toward where we actually want to go (unsteered),
        each one longer, up to the energy we have; odd-numbered ones slide along the wall, the same side twice
        in a row, so the slide covers ground instead of undoing the last one."""
        t, me = self.t, self.me
        if t < self.escape_until:
            if not self.escape_climb:
                return self.escape_dir, False, False
            return self.escape_dir, me["grounded"], (not me["grounded"]) and me["energy"] > 8
        if want is not None and len(self.hist) >= 16 and (mv[0] or mv[1]):
            t_old, x_old, y_old = self.hist[-16]
            if t - t_old >= 1.4 and math.hypot(self.x - x_old, self.y - y_old) < 2.0:
                here = [(st, sx, sy) for st, sx, sy in self.stuck_at
                        if t - st < 20.0 and math.hypot(self.x - sx, self.y - sy) < 6.0]
                n = len(here)
                self.stuck_at = [(st, sx, sy) for st, sx, sy in self.stuck_at if t - st < 20.0] + [(t, self.x, self.y)]
                wx, wy = norm(want[0], want[1])
                if not (wx or wy):
                    wx, wy = mv
                energy = me["energy"]
                if n % 2 == 0 and energy > 35:
                    self.escape_dir, self.escape_climb = (wx, wy), True
                    dur = 1.2 if n == 0 else min(4.5, 0.6 + energy / 15.0)   # jets drain 15/s: use most of it
                else:
                    side = self.side_sign * (1 if (n // 4) % 2 == 0 else -1)   # n = 1, 3: one side; 5, 7: the other
                    self.escape_dir, self.escape_climb = (-wy * side, wx * side), False
                    dur = 2.0
                self.escape_until = t + dur
                self.path, self.job = None, None
                self.hist.clear()
                return self.escape_dir, self.escape_climb, False
        return mv, False, False

    # ================================================================== aim and weapons
    def _aim_and_fire(self, act, obs, target, mv):
        me = self.me
        slots = me["weapons"]
        fire = [False, False]
        aim = None
        if target is not None:
            aim, fire = self._engage(target, slots)
        if aim is None and target is None and self.mode in ("loot", "hold", "move", "roam"):
            cr = self._crate(obs, 60)
            if cr is not None and (self.map is None or self.map.los(self.x, self.y, cr["pos"][0], cr["pos"][1])):
                fake = {"kind": "crate", "pos": cr["pos"], "vel": (0, 0, 0)}
                aim, fire = self._engage(fake, slots)
        up = self.unseen_p
        if (up["face"] and self.unseen and self.mode in ("fight", "evade", "hide", "hunt")
                and not (self.mode == "fight" and self._finishing(target))):
            # unseen_hit: turn to whoever shoots us from out of sight: they enter the 200 m wedge, rear hits become front
            aim, fire = (self.unseen[0][1], 0.0), [False, False]
        if aim is None and self.mode in ("evade", "hide"):
            aim = self._threat_aim()     # rear hits do x1.5: keep our front to whoever we are running from
        if aim is None:
            aim = self._idle_aim(mv)
        act["aim"] = [round(aim[0], 4), round(aim[1], 4)]
        if any(fire):
            act["fire"] = fire
        g = slots[0]
        if g and g["kind"] == "gun" and target is None and g.get("ammo", 99) < g["stats"].get("mag", 12) * 0.5 and not g.get("reload"):
            act["reload"] = True

    def _engage(self, tgt, slots):
        me = self.me
        mx, my = self.x, self.y
        mz = self.z + self.stats.get("muzzle_height", 7.0)
        tx, ty, tz = tgt["pos"]
        tvx, tvy, tvz = tgt.get("vel", (0, 0, 0))
        tz += 4.5 if tgt["kind"] == "mech" else 1.75
        d = math.hypot(tx - mx, ty - my)
        ay, ap = me["aim"]

        def err(yaw, pitch):
            return abs(wrap(yaw - ay)) + abs(pitch - ap) * 0.7

        direct = (math.atan2(ty - my, tx - mx), math.atan2(tz - mz, max(d, 0.1)))
        idx = {w["kind"]: i for i, w in enumerate(slots) if w}
        fire = [False, False]
        primary = None

        lt = slots[idx["lightning"]] if "lightning" in idx else None
        la = slots[idx["laser"]] if "laser" in idx else None
        mo = slots[idx["mortar"]] if "mortar" in idx else None
        gun = slots[idx["gun"]] if "gun" in idx else None

        if lt and d <= lt["stats"].get("range", 45) * 0.92 and me["energy"] >= 6:
            primary = direct
            cone = math.radians(lt["stats"].get("cone_deg", 30)) / 2
            if abs(wrap(direct[0] - ay)) < cone * 0.8 and lt["cooldown"] <= 0:
                fire[idx["lightning"]] = True
        if la and primary is None and d <= la["stats"].get("range", 280) * 0.95 and self.t >= self.short_until:
            charge = la.get("charge", 0) or 0
            full = la["stats"].get("charge", 0.75)
            if charge > 0 or la["cooldown"] <= 0:
                primary = direct
                if charge < full * 0.97 or err(*direct) > 0.03:
                    fire[idx["laser"]] = True  # keep holding (charging), release when full and on target
        if mo and primary is None and mo["cooldown"] <= 0:
            mdz = tz - 4.5 - (self.z + self.stats.get("height", 9) + 0.5)
            px, py, pd = tx, ty, d
            if self.mortar_lead:
                px, py, pd = self._mortar_lead(tx, ty, tvx, tvy, d, mdz, mo["stats"])
            if 25 < pd < 225:
                sol = self._mortar_pitch(pd, mdz, mo["stats"])
                if sol is not None:
                    primary = (math.atan2(py - my, px - mx) if self.mortar_lead else direct[0], sol)
                    if err(*primary) < 0.025:
                        fire[idx["mortar"]] = True
        if gun:
            spd = gun["stats"].get("speed", 252)
            lx, ly, lz = tx, ty, tz
            for _ in range(2):
                tt = math.dist((lx, ly, lz), (mx, my, mz)) / spd
                lx, ly, lz = tx + tvx * tt, ty + tvy * tt, tz + tvz * tt
            lead = (math.atan2(ly - my, lx - mx), math.atan2(lz - mz, max(math.hypot(lx - mx, ly - my), 0.1)))
            if primary is None:
                primary = lead
            tol = 0.035 + 2.5 / max(d, 1)
            if d <= gun["stats"].get("range", 230) and err(*lead) < tol and gun.get("ammo", 1) > 0 and not gun.get("reload"):
                fire[idx["gun"]] = True
        return primary, fire

    def _mortar_lead(self, tx, ty, tvx, tvy, d, dz, st):
        """Aim point (x, y, horizontal distance) for a shell: the target's position after the flight time of the
        low arc, times lead_frac, offset capped at max_lead_m. Falls back to the target itself without a solution."""
        v = st.get("speed", 72)
        px, py, pd = tx, ty, d
        for _ in range(3):
            sol = self._mortar_pitch(pd, dz, st)
            if sol is None:
                return tx, ty, d
            ft = pd / max(1e-6, v * math.cos(sol)) * self.mlead_k
            ox, oy = tvx * ft, tvy * ft
            o = math.hypot(ox, oy)
            if o > self.mlead_max:
                ox, oy = ox * self.mlead_max / o, oy * self.mlead_max / o
            px, py = tx + ox, ty + oy
            pd = math.hypot(px - self.x, py - self.y)
        return px, py, pd

    def _mortar_pitch(self, d, dz, st):
        v, g = st.get("speed", 72), st.get("gravity", 22)
        # solve d*tan - g d^2 / (2 v^2 cos^2) = dz for the low arc
        a = g * d * d / (2 * v * v)
        disc = d * d - 4 * a * (a + dz)
        if disc < 0:
            return None
        tan_p = (d - math.sqrt(disc)) / (2 * a)
        return math.atan(tan_p)

    def _threat_aim(self):
        """Aim at the nearest known enemy within 220 m, else where we were hit from in the last 6 s; None if neither."""
        best, best_d = None, 220.0
        for (_, kx, ky) in self.known.values():
            d = math.hypot(kx - self.x, ky - self.y)
            if d < best_d:
                best, best_d = (kx, ky), d
        if best is not None:
            return (math.atan2(best[1] - self.y, best[0] - self.x), 0.0)
        if self.hurt_bearing is not None and self.t - self.last_hurt_t < 6.0:
            return (self.hurt_bearing, 0.0)
        return None

    def _idle_aim(self, mv):
        t = self.t
        if self.heard and t - self.heard[0] < 2.0:
            return (self.heard[1], 0.0)
        if self.hurt_bearing is not None and t - self.last_hurt_t < 3.0:
            return (self.hurt_bearing, 0.0)
        # sweep: around the movement direction when moving, all the way round when standing
        if mv[0] or mv[1]:
            base = math.atan2(mv[1], mv[0])
            return (wrap(base + 1.1 * math.sin(t * 1.3)), 0.0)
        return (wrap(t * 1.6), 0.0)


mf.run(Bot)
