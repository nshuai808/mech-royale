"""mech-royale v2: kit example bot + loot/weapon planner (H-LOO, H-WPN). See loot.py and params.json."""
import json
import math
import os

import botlog
import engage
import loot
import mechfight as mf


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
        self.engage = self._make_engage(hello)

    def _make_engage(self, hello):
        """H-ENG/H-REG (engage.py). Built in the ready window; any failure means no engage, i.e. v2 behaviour."""
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

    def _engage(self, obs):
        try:
            return self.engage.update(obs) if self.engage is not None else engage.Decision()
        except Exception as e:
            botlog.trace(obs["tick"], mode="engage_error", err=repr(e))
            return engage.Decision()

    def _loot(self, obs):
        """Loot decision; any failure falls back to v1 behaviour (no loot) instead of crashing."""
        try:
            return self.planner.step(obs)
        except Exception as e:
            botlog.trace(obs["tick"], mode="loot_error", err=repr(e))
            return loot.Decision(reason="error")

    def _fire(self, me, dist):
        """fire[i] per slot: the gun always; the special only inside its range. Mortar stays off until
        there is a ballistic aim solver (v2 aims flat). Slots are looked up, never assumed."""
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

    def act(self, obs: mf.Observation) -> mf.Action:
        me = obs["self"]
        x, y, z = me["pos"]
        zone_goal = obs["zone"]["next_center"]
        act: mf.Action = {"tick": obs["tick"]}
        if obs["offer"]:
            act["pick"] = 0

        d = self._loot(obs)
        e = self._engage(obs)
        quiet = e.mode in ("retreat", "regen")   # retreat/regen outrank fight, loot and the zone walk (V2_MERGE goal priority)
        if d.take is not None:
            act["take"] = d.take
            if d.drop is not None:
                act["drop"] = d.drop
        elif d.drop is not None:
            act["drop"] = d.drop

        enemies = sorted((m for m in obs["mechs"] if m["kind"] == "mech"), key=lambda m: math.dist(m["pos"], me["pos"]))
        goal = d.goal if d.goal is not None else zone_goal
        if e.mode == "retreat":
            if e.goal is not None:
                goal = e.goal
            elif e.move is not None:
                goal = (x + 50 * e.move[0], y + 50 * e.move[1], z)
        yaw = math.atan2(goal[1] - y, goal[0] - x)
        climbing = not quiet and d.goal is not None and d.goal[2] - z > self.planner.p.roof_dz_m
        move = [math.cos(yaw), math.sin(yaw)]
        if quiet:   # regen: stand still (silent); retreat: e.speed < 1 once clear and unseen (walking under 5 m/s is silent)
            move = [0.0, 0.0] if e.mode == "regen" else [move[0] * e.speed, move[1] * e.speed]
        act.update(move=move, aim=[yaw, 0.0],
                   boost=(not me["in_zone"]) or (climbing and not me["grounded"]) or e.boost,
                   jump=(climbing or obs["tick"] % 40 == 0) and not quiet)
        dist = None
        if enemies:
            t = enemies[0]["pos"]
            dist = math.dist(t[:2], (x, y))
            aim = [math.atan2(t[1] - y, t[0] - x), math.atan2(t[2] - z - 2.5, dist)]
            act.update(aim=aim, fire=self._fire(me, dist))
            mf.draw.line([x, y, z + 7], [t[0], t[1], t[2] + 4.5], "#ff5040")
        if not enemies and e.aim_yaw is not None:
            act["aim"] = [e.aim_yaw, 0.0]       # regen: face the last-known threat so a returning attacker meets our front arc
        if e.hold_fire:
            act["fire"] = [False, False]        # retreat/regen: no shots (sound, and it resets our regen timer)
        if e.reload:
            act["reload"] = True
        mf.draw.point([goal[0], goal[1], z], "#40ff90" if quiet else ("#ffd060" if d.goal is not None else "#40c0ff"), 6)
        mf.draw.label(f"hp {me['hp']:.0f} · {len(enemies)} in sight" + (f" · {d.reason} {d.kind}" if d.kind else "")
                      + (f" · {e.mode}" if e.mode != "neutral" else ""))
        mode = e.mode if quiet else ("fight" if enemies else ("loot" if d.goal is not None else "to_zone"))
        botlog.trace(obs["tick"], mode=mode, target=enemies[0]["id"] if enemies else None, in_zone=me["in_zone"],
                     loot=d.reason, loot_kind=d.kind, loot_u=round(d.utility, 2),
                     weapons=[w["kind"] if w else None for w in me["weapons"]],
                     engage=f"{e.mode}|R={e.diag.get('R')}|{e.reason}")
        return act


mf.run(Bot)
