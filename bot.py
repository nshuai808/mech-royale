"""mech-royale v2: kit example bot + loot/weapon planner (H-LOO, H-WPN). See loot.py and params.json."""
import json
import math
import os

import botlog
import loot
import mechfight as mf
import percept


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
        self.per, self.world, self.per_errors = None, None, 0
        pp = self.params.get("perception") or {}
        if pp.get("enabled", True):
            try:
                self.per = percept.Perception(hello, params=percept.load_params(overrides=pp))
            except Exception as e:  # no perception = v2 behaviour
                botlog.trace(0, mode="per_error", err=repr(e))

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
            return self.planner.step(obs, threats=threats)
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

        d = self._loot(obs, self._perceive(obs))
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
                     per=None if self.world is None else [len(self.per.tracks), round(self.per.cloud.mass, 1),
                                                          len(self.world.hot), round(self.per.times[-1], 1)])
        return act


mf.run(Bot)
