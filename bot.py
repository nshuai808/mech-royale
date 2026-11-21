"""mech-royale v2: kit example bot + loot/weapon planner (H-LOO, H-WPN). See loot.py and params.json."""
import json
import math
import os

import botlog
import loot
import mechfight as mf
import upgrades


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
        self.upg = None
        try:
            if self.params.get("upgrades", {}).get("enabled", True):
                self.upg = upgrades.UpgradePolicy(cfg, self.params.get("upgrades"))
        except Exception as e:  # no policy = v1 behaviour (pick 0)
            botlog.trace(0, mode="upgrades_error", err=repr(e))

    def _loot(self, obs):
        """Loot decision; any failure falls back to v1 behaviour (no loot) instead of crashing."""
        try:
            return self.planner.step(obs)
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
        pick = self._pick(obs)
        if pick is not None:
            act["pick"] = pick

        d = self._loot(obs)
        if d.take is not None:
            act["take"] = d.take
            if d.drop is not None:
                act["drop"] = d.drop
        elif d.drop is not None:
            act["drop"] = d.drop

        enemies = sorted((m for m in obs["mechs"] if m["kind"] == "mech"), key=lambda m: math.dist(m["pos"], me["pos"]))
        goal = d.goal if d.goal is not None else zone_goal
        yaw = math.atan2(goal[1] - y, goal[0] - x)
        climbing = d.goal is not None and d.goal[2] - z > self.planner.p.roof_dz_m
        act.update(move=[math.cos(yaw), math.sin(yaw)], aim=[yaw, 0.0],
                   boost=(not me["in_zone"]) or (climbing and not me["grounded"]),
                   jump=climbing or obs["tick"] % 40 == 0)
        dist = None
        if enemies:
            t = enemies[0]["pos"]
            dist = math.dist(t[:2], (x, y))
            aim = [math.atan2(t[1] - y, t[0] - x), math.atan2(t[2] - z - 2.5, dist)]
            act.update(aim=aim, fire=self._fire(me, dist))
            mf.draw.line([x, y, z + 7], [t[0], t[1], t[2] + 4.5], "#ff5040")
        mf.draw.point([goal[0], goal[1], z], "#ffd060" if d.goal is not None else "#40c0ff", 6)
        mf.draw.label(f"hp {me['hp']:.0f} · {len(enemies)} in sight" + (f" · {d.reason} {d.kind}" if d.kind else ""))
        mode = "fight" if enemies else ("loot" if d.goal is not None else "to_zone")
        botlog.trace(obs["tick"], mode=mode, target=enemies[0]["id"] if enemies else None, in_zone=me["in_zone"],
                     loot=d.reason, loot_kind=d.kind, loot_u=round(d.utility, 2),
                     weapons=[w["kind"] if w else None for w in me["weapons"]],
                     upg=self.upg.debug_label() if self.upg is not None else "")
        return act


mf.run(Bot)
