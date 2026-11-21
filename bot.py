"""mech-royale v2 (integrated): loot (H-LOO/H-WPN) + upgrades (H-UPG) + perception (H-PER) + navigation/stealth
(H-NAV/H-STL) + fight-or-flee/regen (H-ENG/H-REG) + aiming/fight movement (H-AIM/H-MOV).

bot.py is the only place the components meet (docs/V2_MERGE.md). Every component call is wrapped: a failure means that
component has no opinion and the bot falls back toward v1 behaviour. Not covered yet: zone shaping and supply drops
(H-ZON/H-DRP): the default goal is still the centre of the next circle.

Goal priority (highest first): engage retreat/regen > fight movement (aim) > loot goal > zone walk.
Action-field owners: take/drop = loot; pick = upgrades; aim/fire/reload = aim (engage may hold fire / set the resting
aim / ask for a reload); move = arbiter (engage retreat, aim strafe, else nav toward the goal); boost/jump = arbiter.
"""
import json
import math
import os
import time

import aim
import botlog
import engage
import loot
import mechfight as mf
import nav
import percept
import upgrades

SLOW_MS = 35.0      # a decision slower than this makes us skip the optional heavy components for a while
SLOW_SKIP_TICKS = 10


def load_params():
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "params.json")) as f:
            return json.load(f)
    except Exception as e:  # a bad params file must never stop the bot
        botlog.trace(0, mode="params_error", err=str(e))
        return {}


class Bot:
    name = "mech-royale-v2"

    def __init__(self, hello: mf.Hello):
        cfg = hello["config"]
        self.cfg = cfg
        self.params = load_params()
        self.reach = cfg["loot"]["pickup_radius"]
        self.planner = loot.LootPlanner(cfg, loot.LootParams.from_dict(self.params.get("loot")))
        self.special_margin = self.params.get("fire", {}).get("special_margin", 0.9)
        self.slow_until = -1

        self.upg = None
        try:
            if self.params.get("upgrades", {}).get("enabled", True):
                self.upg = upgrades.UpgradePolicy(cfg, self.params.get("upgrades"))
        except Exception as e:  # no policy = v1 behaviour (pick 0)
            botlog.trace(0, mode="upgrades_error", err=repr(e))

        self.per, self.world, self.per_errors = None, None, 0
        pp = self.params.get("perception") or {}
        if pp.get("enabled", True):
            try:
                self.per = percept.Perception(hello, params=percept.load_params(overrides=pp))
            except Exception as e:  # no perception = loot builds its own threats
                botlog.trace(0, mode="per_error", err=repr(e))

        self.nav = self._build_nav(hello)
        self.engage = self._make_engage(hello)
        self.aimer = None
        try:
            if (self.params.get("aim") or {}).get("enabled", True):
                self.aimer = aim.AimController(cfg, self.params.get("aim"), self.params.get("move"),
                                               seed=hello.get("seed", 0))
        except Exception as e:  # no aim controller = the flat v2 aim and fire below
            botlog.trace(0, mode="aim_init_error", err=repr(e))

    # ---- component wrappers (each one: any failure = no opinion) ----
    def _build_nav(self, hello):
        try:
            if (self.params.get("nav") or {}).get("enabled", True) is False:
                return None
            return nav.Navigator.create(hello, nav.NavParams.from_dict(self.params.get("nav")),
                                        nav.StealthParams.from_dict(self.params.get("stealth")))
        except Exception as e:
            botlog.trace(0, mode="nav_error", err=repr(e))
            return None

    def _make_engage(self, hello):
        try:
            sec = self.params.get("engage") or {}
            if sec.get("enabled", True) is False:
                return None
            occ = None
            try:
                occ = engage.Occluder(hello["map"]["dir"])
            except Exception as e:
                botlog.trace(0, mode="engage_map_error", err=repr(e))
            return engage.Engagement(hello, params=engage.params_from_dict(sec), occluder=occ)
        except Exception as e:
            botlog.trace(0, mode="engage_init_error", err=repr(e))
            return None

    def _perceive(self, obs):
        """World model update (H-PER). Returns loot threats, or None to let loot use its own fallback."""
        if self.per is None:
            return None
        try:
            self.world = self.per.update(obs)
            self.per_errors = 0
            return self.per.loot_threats(loot.Threat) or None
        except Exception as e:
            self.world = None
            self.per_errors += 1
            botlog.trace(obs["tick"], mode="per_error", err=repr(e))
            if self.per_errors >= 20:
                self.per = None
            return None

    def _loot(self, obs, threats=None):
        """Loot decision; any failure falls back to v1 behaviour (no loot) instead of crashing."""
        try:
            return self.planner.step(obs, threats=threats, path_cost=self.nav.path_cost if self.nav else None)
        except Exception as e:
            botlog.trace(obs["tick"], mode="loot_error", err=repr(e))
            return loot.Decision(reason="error")

    def _pick(self, obs):
        """Upgrade pick (H-UPG). Runs every tick (it tracks combat lulls); any failure means the v1 default, pick 0."""
        try:
            if self.upg is not None:
                return self.upg.pick(obs)
        except Exception as e:
            botlog.trace(obs["tick"], mode="upgrades_error", err=repr(e))
        return 0 if obs.get("offer") else None

    def _engage(self, obs):
        try:
            return self.engage.update(obs) if self.engage is not None else engage.Decision()
        except Exception as e:
            botlog.trace(obs["tick"], mode="engage_error", err=repr(e))
            return engage.Decision()

    def _aim(self, obs, suppress_move):
        """Aim/fire/reload (aim.py) and a fight-movement suggestion; None = use the flat v2 aim and fire."""
        if self.aimer is None:
            return None
        try:
            return self.aimer.step(obs, suppress_move=suppress_move)
        except Exception as e:
            botlog.trace(obs["tick"], mode="aim_error", err=repr(e))
            return None

    def _nav(self, obs, goal, default_goal):
        if self.nav is None:
            return None
        try:
            return self.nav.step(obs, goal, default_goal)
        except Exception as e:
            botlog.trace(obs["tick"], mode="nav_error", err=repr(e))
            return None

    def _fire(self, me, dist):
        """Flat fallback fire[i] per slot: the gun always; the special only inside its range. Slots are looked up."""
        fire = [False, False]
        for i, w in enumerate(me["weapons"]):
            if not w:
                continue
            kind = w["kind"]
            if kind == "gun":
                fire[i] = True
            elif kind in ("laser", "lightning"):
                fire[i] = dist <= self.special_margin * self.cfg["weapons"][kind]["range"]
        return fire

    # ---- the decision ----
    def act(self, obs: mf.Observation) -> mf.Action:
        t0 = time.perf_counter()
        tick = obs["tick"]
        me = obs["self"]
        x, y, z = me["pos"]
        act: mf.Action = {"tick": tick}
        slow = tick < self.slow_until

        pick = self._pick(obs)
        if pick is not None:
            act["pick"] = pick

        threats = None if slow else self._perceive(obs)
        d = self._loot(obs, threats)
        if d.take is not None:
            act["take"] = d.take
            if d.drop is not None:
                act["drop"] = d.drop
        elif d.drop is not None:
            act["drop"] = d.drop

        e = self._engage(obs)
        quiet = e.mode in ("retreat", "regen")   # retreat/regen outrank fight, loot and the zone walk

        # goal: retreat > loot > zone centre
        default_goal = False
        if e.mode == "retreat" and e.goal is not None:
            goal = e.goal
        elif e.mode == "retreat" and e.move is not None:
            goal = (x + 50 * e.move[0], y + 50 * e.move[1], z)
        elif d.goal is not None:
            goal = d.goal
        else:
            goal = obs["zone"]["next_center"]
            default_goal = True
        climbing = (not quiet) and d.goal is not None and d.goal[2] - z > self.planner.p.roof_dz_m

        enemies = sorted((m for m in obs["mechs"] if m["kind"] == "mech"),
                         key=lambda m: math.dist(m["pos"], me["pos"]))

        # base action: walk straight at the goal, face the way we walk (v1 behaviour)
        yaw = math.atan2(goal[1] - y, goal[0] - x)
        act.update(move=[math.cos(yaw), math.sin(yaw)], aim=[yaw, 0.0],
                   boost=(not me["in_zone"]) or (climbing and not me["grounded"]) or e.boost,
                   jump=(climbing or tick % 40 == 0) and not quiet)

        # aiming + fight movement (aim owns aim/fire/reload)
        a = self._aim(obs, quiet or climbing)
        if a is not None:
            if a.aim is not None:
                act["aim"] = list(a.aim)
            if a.fire is not None:
                act["fire"] = a.fire
            if a.reload:
                act["reload"] = True
        elif enemies:
            t = enemies[0]["pos"]
            dist = math.dist(t[:2], (x, y))
            act.update(aim=[math.atan2(t[1] - y, t[0] - x), math.atan2(t[2] - z - 2.5, dist)],
                       fire=self._fire(me, dist))
            mf.draw.line([x, y, z + 7], [t[0], t[1], t[2] + 4.5], "#ff5040")

        # movement arbiter
        strafing = (not quiet) and a is not None and a.move is not None
        nd = None
        if e.mode == "regen":
            act["move"] = [0.0, 0.0]                 # regen: stand still (silent), face the last-known threat
        elif strafing:
            act["move"] = list(a.move)               # fight movement outranks loot and the zone walk
        else:
            nd = None if slow else self._nav(obs, goal, default_goal)
            if nd is not None:
                if nd.move is not None:
                    act["move"] = [nd.move[0], nd.move[1]]
                if ((not nd.boost_ok and not climbing) or nd.hold) and not e.boost:
                    act["boost"] = False
                if nd.hold:
                    act["jump"] = False
                if nd.jump:
                    act["jump"] = True
                if nd.boost:
                    act["boost"] = True
            if e.mode == "retreat":                  # slip away quietly once clear and unseen (e.speed < 1)
                act["move"] = [act["move"][0] * e.speed, act["move"][1] * e.speed]

        # engage's say over the shot: hold fire, resting aim, early reload
        if not enemies and e.aim_yaw is not None:
            act["aim"] = [e.aim_yaw, 0.0]            # face the last-known threat so a returning attacker meets our front arc
        if e.hold_fire:
            act["fire"] = [False, False]             # retreat/regen: no shots (sound, and it resets our regen timer)
        if e.reload:
            act["reload"] = True

        mf.draw.point([goal[0], goal[1], z], "#40ff90" if quiet else ("#ffd060" if d.goal is not None else "#40c0ff"), 6)
        mf.draw.label(f"hp {me['hp']:.0f} · {len(enemies)} in sight" + (f" · {d.reason} {d.kind}" if d.kind else "")
                      + (f" · {e.mode}" if e.mode != "neutral" else ""))
        mode = e.mode if quiet else ("fight" if enemies else ("loot" if d.goal is not None else "to_zone"))
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        if elapsed_ms > SLOW_MS:
            self.slow_until = tick + SLOW_SKIP_TICKS
        botlog.trace(tick, mode=mode, target=enemies[0]["id"] if enemies else None, in_zone=me["in_zone"],
                     loot=d.reason, loot_kind=d.kind, loot_u=round(d.utility, 2),
                     weapons=[w["kind"] if w else None for w in me["weapons"]],
                     upg=self.upg.debug_label() if self.upg is not None else "",
                     aim=a.reason if a else None, nav=nd.reason if nd else None,
                     engage=f"{e.mode}|R={e.diag.get('R')}|{e.reason}",
                     per=None if self.world is None else [len(self.per.tracks), round(self.per.cloud.mass, 1),
                                                          len(self.world.hot), round(self.per.times[-1], 1)],
                     ms=round(elapsed_ms, 1))
        return act


mf.run(Bot)
