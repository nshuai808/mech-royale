"""H-UPG: upgrade policy for the Mech Royale bot. Standard library only.

Idea: an offer is 3 upgrades we cannot choose, only rank. We rank them by their
marginal gain in a closed-form "combat power" model, built *from hello.config.upgrades*
(so it stays correct when balance changes), with a handful of state-dependent knobs.

    ln P = w_ehp * ln(D) + w_dps * ln(DPS) + utility terms

    D   = (max_hp + C * recovered_hp_per_disengage) / (1 - armor)    effective durability
    DPS = sum over held weapons of uptime * hit_rate * sustained_dps  (slots fire independently)
    utility = elasticity * ln(stat ratio) for speed, turn rate, sensors, hearing, energy

Bot integration (3 lines):
    self.upg = UpgradePolicy(hello["config"], params.get("upgrades"))          # __init__
    p = self.upg.pick(obs)                                                     # every obs
    if p is not None: act["pick"] = p

pick() is idempotent per offer id, never raises, and falls back to index 0 (the server default).
"""
import copy
import json
import math
import os

DEFAULTS = {
    # --- combat-power model ---
    "w_ehp": 1.0,              # weight on ln(durability)
    "w_dps": 0.8,              # weight on ln(damage output); placement rewards surviving more than killing
    "uptime":  {"gun": 0.85, "mortar": 0.6, "laser": 0.7, "lightning": 0.25},   # fraction of a fight the weapon is usable
    "p_hit":   {"gun": 0.35, "lightning": 0.9},                                  # hit probability vs a strafing mech
    # laser is telegraphed (charging=true is visible): a shorter charge leaves less time to dodge
    "laser_hit_nododge": 0.75, "laser_dodge_p": 0.4, "laser_react_s": 0.25, "laser_need_s": 0.5,
    "k_gun_speed": 0.25,        # hit rate ~ (bullet speed / base)^k  (shorter flight time, smaller lead error)
    "mortar_sigma_m": 9.0,     # shell landing error (1 sigma, m) at base shell speed
    "mortar_target_r": 3.0,    # effective direct-hit radius (m)
    "mortar_splash_mean": 0.65,  # mean fraction of splash damage inside the radius
    "lightning_chain_bonus": 0.08,   # damage bonus per chain jump above the base (needs a 2nd target)
    "lightning_range_exp": 0.8,      # in-range time ~ (range/base)^exp
    "lightning_cone_exp": 0.5,
    "laser_pierce_bonus": 0.03,
    # --- survival / regen ---
    "regen_cycles": 0.25,      # C: heal cycles that convert into survival. Sim (fresh full-HP peers, open field) supports ~0.1-0.3;
                               # raise only if H-REG really retreats and heals. Measured lulls add to it at runtime (below).
    "regen_gap_s": 12.0,       # typical seconds of peace between fights (replaced by the measured median lull when we have one)
    "lull_min_s": 6.0,         # a lull counts as a heal opportunity if combat events stop for at least this long
    "lull_window_s": 150.0,    # ...within this many recent seconds
    "regen_cycles_per_lull": 0.05,  # extra C per measured heal-sized lull (small: sim shows lulls alone do not convert into survival)
    "lull_cap": 4,
    "regen_missing_frac": 0.5, # typical fraction of max HP missing when peace starts
    # --- utility elasticities (d ln P / d ln stat); priors, not measurements ---
    "e_speed": 0.10, "e_turn": 0.15, "e_near": 0.15, "e_vision": 0.10, "e_hear": 0.08,
    "e_energy": 0.12, "e_energy_regen": 0.08, "e_energy_drain": 0.08,
    # --- weapon-upgrade handling ---
    "swap_discount": 0.25,     # weapon-2 upgrades go dormant if H-WPN swaps that weapon away
    "bias": {},                # additive per-upgrade nudges, in ln-power units (e.g. {"sensors": 0.02})
    # --- state-dependent multipliers on the knobs above (name -> knob -> multiplier) ---
    "state_scale": {
        "early":          {"w_dps": 0.75, "regen_cycles": 1.3},                       # t<120 s and >=10 alive: avoid, heal
        "finals":         {"w_dps": 1.25, "regen_cycles": 0.5, "e_near": 0.7, "e_vision": 0.7},   # <=4 alive: duels decide it
        "late_zone":      {"regen_cycles": 0.3, "e_energy": 1.5, "e_energy_drain": 1.5},           # zone dps>=60: no regen, run
        "lightning_held": {"e_energy": 1.4, "e_energy_regen": 1.4},
        "big":            {"e_speed": 0.7, "e_turn": 0.8},                                          # >=10 cubes: 1.5x hitbox, dodging weaker
    },
    "thresholds": {"finals_alive": 4, "early_t": 120.0, "early_alive": 10, "late_zone_dps": 60.0, "big_cubes": 10},
}


def load_params(path_or_dict=None):
    """Merge user params over DEFAULTS (one level deep for dict-valued knobs)."""
    p = copy.deepcopy(DEFAULTS)
    src = path_or_dict
    if isinstance(src, str):
        with open(src) as f:
            src = json.load(f)
    if isinstance(src, dict):
        for k, v in src.items():
            if isinstance(v, dict) and isinstance(p.get(k), dict):
                for k2, v2 in v.items():
                    if isinstance(v2, dict) and isinstance(p[k].get(k2), dict):
                        p[k][k2].update(v2)
                    else:
                        p[k][k2] = v2
            else:
                p[k] = v
    return p


def _get(d, path, default=None):
    for part in path.split("."):
        if not isinstance(d, dict) or part not in d:
            return default
        d = d[part]
    return d


class UpgradePolicy:
    def __init__(self, config, params=None):
        self.p = load_params(params)
        self.defs = {u["id"]: u for u in config.get("upgrades", [])}
        self.base = {"mech": dict(config.get("mech", {})),
                     "weapons": {k: dict(v) for k, v in config.get("weapons", {}).items()}}
        vis = config.get("vision", {})
        self.near0 = float(vis.get("near_range", 45.0))
        self.vis0 = float(vis.get("range", 200.0))
        self.cube_cfg = config.get("cubes", {})
        self._cache = {}      # offer id -> chosen index
        self.last_explain = []
        self._last_combat = None     # sim time of the last damaged/hit/kill event
        self._lulls = []             # (end_time, length_s) of peaceful gaps between combat events

    # ---------- stat application ----------
    def apply(self, stacks):
        """Return {'mech':{...}, 'weapons':{kind:{...}}} after applying `stacks` ({upgrade_id: n})."""
        st = copy.deepcopy(self.base)
        for uid, n in stacks.items():
            d = self.defs.get(uid)
            if not d:
                continue
            for _ in range(int(n)):
                for e in d.get("effects", []):
                    parts = e["path"].split(".")
                    tgt = st
                    ok = True
                    for part in parts[:-1]:
                        if part not in tgt or not isinstance(tgt[part], dict):
                            ok = False
                            break
                        tgt = tgt[part]
                    if not ok:
                        continue
                    key = parts[-1]
                    if "mul" in e:
                        if key in tgt:
                            tgt[key] = tgt[key] * e["mul"]
                    if "add" in e:
                        tgt[key] = tgt.get(key, 0.0) + e["add"]
        return st

    # ---------- state -> knob scaling ----------
    def knobs(self, state):
        p = self.p
        th = p["thresholds"]
        active = []
        if state.get("alive", 16) <= th["finals_alive"]:
            active.append("finals")
        if state.get("t", 0.0) < th["early_t"] and state.get("alive", 16) >= th["early_alive"]:
            active.append("early")
        if state.get("zone_dps", 0.0) >= th["late_zone_dps"]:
            active.append("late_zone")
        if "lightning" in state.get("held", ()):
            active.append("lightning_held")
        if state.get("cubes", 0) >= th["big_cubes"]:
            active.append("big")
        k = {n: p[n] for n in ("w_ehp", "w_dps", "regen_cycles", "regen_gap_s", "regen_missing_frac",
                               "e_speed", "e_turn", "e_near", "e_vision", "e_hear",
                               "e_energy", "e_energy_regen", "e_energy_drain")}
        n_l = state.get("n_lulls", 0)
        if n_l:
            k["regen_cycles"] += p["regen_cycles_per_lull"] * min(n_l, p["lull_cap"])
            if state.get("lull_gap"):
                k["regen_gap_s"] = min(max(state["lull_gap"], p["lull_min_s"]), 25.0)
        for name in active:
            for knob, mult in p["state_scale"].get(name, {}).items():
                k[knob] = k[knob] * mult
        k["_active"] = active
        return k

    # ---------- the model ----------
    def _gun_dps(self, g, g0):
        p = self.p
        sustained = g["mag"] * g["damage"] / (g["mag"] * g["cooldown"] + g["reload"])
        hit = p["p_hit"]["gun"] * (g["speed"] / g0["speed"]) ** p["k_gun_speed"]
        return p["uptime"]["gun"] * min(hit, 0.95) * sustained

    def _mortar_dps(self, w, w0):
        p = self.p
        sigma = p["mortar_sigma_m"] * (w0["speed"] / w["speed"])   # lead error comes from target velocity change during flight: ~ flight time ~ 1/speed
        pd = 1 - math.exp(-p["mortar_target_r"] ** 2 / (2 * sigma ** 2))
        ps = 1 - math.exp(-w["splash_radius"] ** 2 / (2 * sigma ** 2))
        e = pd * (w["damage"] + w["splash"]) + max(ps - pd, 0.0) * w["splash"] * p["mortar_splash_mean"]
        return p["uptime"]["mortar"] * e / w["cooldown"]

    def _laser_dps(self, w):
        p = self.p
        dmg = w["damage"] * (1 + p["laser_pierce_bonus"] * w.get("pierce", 0))
        window = max(0.0, w["charge"] - p["laser_react_s"])               # time left after the target reacts
        dodge = p["laser_dodge_p"] * min(1.0, window / p["laser_need_s"])
        hit = p["laser_hit_nododge"] * (1.0 - dodge)
        return p["uptime"]["laser"] * hit * dmg / (w["charge"] + w["cooldown"])

    def _lightning_dps(self, w, w0):
        p = self.p
        rng = (w["range"] / w0["range"]) ** p["lightning_range_exp"] * (w["cone_deg"] / w0["cone_deg"]) ** p["lightning_cone_exp"]
        chain = 1 + p["lightning_chain_bonus"] * (w["chain"] - w0["chain"])
        return p["uptime"]["lightning"] * min(rng, 2.0) * p["p_hit"]["lightning"] * w["damage"] * chain / w["cooldown"]

    def ln_power(self, stacks, held, k):
        st = self.apply(stacks)
        b = self.base
        m, m0 = st["mech"], b["mech"]
        W, W0 = st["weapons"], b["weapons"]
        armor = min(max(m.get("armor", 0.0), 0.0), 0.9)
        hp = m["hp"]
        rec = min(k["regen_missing_frac"] * hp, m["regen_per_s"] * max(0.0, k["regen_gap_s"] - m["regen_delay"]))
        dur = (hp + k["regen_cycles"] * rec) / (1 - armor)
        dps = 0.0
        if "gun" in held:
            dps += self._gun_dps(W["gun"], W0["gun"])
        if "mortar" in held:
            dps += self._mortar_dps(W["mortar"], W0["mortar"])
        if "laser" in held:
            dps += self._laser_dps(W["laser"])
        if "lightning" in held:
            dps += self._lightning_dps(W["lightning"], W0["lightning"])
        lp = k["w_ehp"] * math.log(dur) + k["w_dps"] * math.log(max(dps, 1e-6))
        # utility
        lp += k["e_speed"] * math.log(m["walk_speed"] / m0["walk_speed"])
        lp += k["e_turn"] * math.log(m["turn_rate"] / m0["turn_rate"])
        near = self.near0 + m.get("near_range_bonus", 0.0)
        vis = self.vis0 + m.get("vision_bonus", 0.0)
        lp += k["e_near"] * math.log(near / self.near0) + k["e_vision"] * math.log(vis / self.vis0)
        lp += k["e_hear"] * (1.0 - m.get("hearing", 1.0))
        lp += k["e_energy"] * math.log(m["energy"] / m0["energy"])
        lp += k["e_energy_regen"] * math.log(m["energy_regen"] / m0["energy_regen"])
        lp += k["e_energy_drain"] * math.log(m0["boost_drain"] / m["boost_drain"])
        return lp

    def score(self, uid, stacks, held, k, secondary):
        d = self.defs.get(uid)
        if d is None:
            return -1.0   # unknown to this config: below any real upgrade
        before = self.ln_power(stacks, held, k)
        after_stacks = dict(stacks)
        after_stacks[uid] = after_stacks.get(uid, 0) + 1
        g = self.ln_power(after_stacks, held, k) - before
        req = d.get("requires")
        if req and req in secondary:
            g *= 1.0 - self.p["swap_discount"]
        return g + self.p["bias"].get(uid, 0.0)

    # ---------- measured peace (state for nanites) ----------
    def observe(self, obs):
        """Call every observation. Records how long the bot actually goes without combat events."""
        try:
            t = float(obs.get("t", 0.0))
            ev = [e for e in (obs.get("events") or []) if e.get("type") in ("damaged", "hit", "kill")]
            if ev:
                if self._last_combat is not None and t - self._last_combat >= 1.0:
                    self._lulls.append((t, t - self._last_combat))
                self._last_combat = t
            win = self.p["lull_window_s"]
            self._lulls = [(te, ln) for te, ln in self._lulls if t - te <= win]
        except Exception:
            pass

    def lull_state(self, t):
        """(# heal-sized lulls in the window, median length of those) -- including a lull still in progress."""
        p = self.p
        good = [ln for te, ln in self._lulls if ln >= p["lull_min_s"] and t - te <= p["lull_window_s"]]
        if self._last_combat is not None and t - self._last_combat >= p["lull_min_s"]:
            good.append(t - self._last_combat)
        if not good:
            return 0, None
        good.sort()
        return len(good), good[len(good) // 2]

    # ---------- observation glue ----------
    def state_from_obs(self, obs):
        me = obs["self"]
        stacks = {}
        for uid in me.get("upgrades", []) or []:
            stacks[uid] = stacks.get(uid, 0) + 1
        held = [w["kind"] for w in me.get("weapons", []) if w]
        secondary = [w["kind"] for w in me.get("weapons", [])[1:] if w]
        zone = obs.get("zone") or {}
        t = obs.get("t", 0.0)
        n_l, gap = self.lull_state(t)
        return {"stacks": stacks, "held": held, "secondary": secondary, "cubes": me.get("cubes", 0),
                "t": t, "alive": obs.get("alive", 16), "zone_dps": zone.get("dps", 0.0),
                "n_lulls": n_l, "lull_gap": gap}

    def rank(self, choices, state):
        k = self.knobs(state)
        out = []
        for i, c in enumerate(choices):
            uid = c["id"] if isinstance(c, dict) else c
            out.append((self.score(uid, state["stacks"], state["held"], k, state["secondary"]), i, uid))
        out.sort(key=lambda r: (-r[0], r[1]))
        return out

    def pick(self, obs):
        """Index into offer.choices, or None when there is no offer. Never raises."""
        self.observe(obs)
        try:
            offer = obs.get("offer")
            if not offer:
                return None
            oid = offer.get("id")
            if oid in self._cache:
                return self._cache[oid]
            choices = offer.get("choices") or []
            if not choices:
                return None
            ranked = self.rank(choices, self.state_from_obs(obs))
            self.last_explain = ranked
            idx = ranked[0][1]
            self._cache[oid] = idx
            return idx
        except Exception:
            return 0

    def debug_label(self):
        if not self.last_explain:
            return ""
        s, _, uid = self.last_explain[0]
        return f"upg {uid} {s * 1000:+.0f}"


# ---------- CLI: print the weight table ----------
CANNED_STATES = {
    # name: (held weapons, cubes, t, alive, zone_dps, stacks, extra state)
    "gun only, offer 1":        (["gun"], 1, 70, 14, 20, {}, {}),
    "gun+lightning, offer 2":   (["gun", "lightning"], 3, 140, 11, 20, {}, {}),
    "gun+laser, offer 2":       (["gun", "laser"], 3, 140, 11, 20, {}, {}),
    "gun+mortar, offer 2":      (["gun", "mortar"], 3, 140, 11, 20, {}, {}),
    "gun+laser, offer 2, calm": (["gun", "laser"], 3, 140, 11, 20, {}, {"n_lulls": 3, "lull_gap": 12.0}),
    "gun+laser, finals":        (["gun", "laser"], 10, 300, 3, 100, {"plating": 1, "armor": 1}, {}),
}


def table(policy):
    rows = {}
    for name, (held, cubes, t, alive, zdps, stacks, extra) in CANNED_STATES.items():
        state = {"stacks": stacks, "held": held, "secondary": [h for h in held if h != "gun"],
                 "cubes": cubes, "t": t, "alive": alive, "zone_dps": zdps}
        state.update(extra)
        k = policy.knobs(state)
        for uid, d in policy.defs.items():
            req = d.get("requires")
            if req and req not in held:
                continue
            if stacks.get(uid, 0) >= d.get("max", 1):
                continue
            rows.setdefault(uid, {})[name] = policy.score(uid, stacks, held, k, state["secondary"]) * 1000
    return rows


if __name__ == "__main__":
    import gzip
    import sys
    path = sys.argv[1]
    cfg = None
    with gzip.open(path, "rt") as f:
        for line in f:
            m = json.loads(line)
            if m.get("type") == "hello":
                cfg = m["config"]
                break
    pol = UpgradePolicy(cfg)
    rows = table(pol)
    cols = list(CANNED_STATES)
    print("milli-ln-power gain of the NEXT stack (higher = pick first); '-' = not offerable")
    print(f"{'upgrade':22s}" + "".join(f"{c[:18]:>20s}" for c in cols))
    order = sorted(rows, key=lambda u: -max(rows[u].values()))
    for u in order:
        print(f"{u:22s}" + "".join(f"{rows[u][c]:20.0f}" if c in rows[u] else f"{'-':>20s}" for c in cols))
