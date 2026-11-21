"""Calibrate R (engage.py's damage-budget ratio) against stochastic 1v1 duels.

The estimator is an expected-value model; real fights are lumpy (a 315-dmg laser either lands or not).
This script draws random duels, computes R with the real estimator, then plays the SAME weapon schedules with
per-shot Bernoulli hits many times and reports P(win | R bin). Use it to choose engage_ratio / disengage_ratio.

It validates the variance structure, NOT the hit-rate assumptions (those are shared on both sides). Real hit rates
come from the AIM component's measurements or from H-SIM.

    python3 tools/engage_calibrate.py [n_duels] [mc_per_duel]
"""
import math
import random
import sys
import os
import gzip
import json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import engage as E          # noqa: E402
import test_engage as T     # noqa: E402


def raw_events(weapon, start, horizon, rng):
    """Yield (time, damage) with Bernoulli hits for one weapon."""
    out = []
    it = weapon.schedule(start)
    while True:
        t, expected = next(it)
        if t > horizon:
            break
        k = weapon.kind
        if k == "gun":
            dm = weapon.dmg if rng.random() < weapon.hit else 0.0
        elif k == "laser":
            dm = weapon.dmg * weapon.cookoff if rng.random() < weapon.hit else 0.0
        elif k == "lightning":
            dm = weapon.dmg * weapon.factor if rng.random() < weapon.hit else 0.0
        elif k == "mortar":
            if rng.random() < weapon.p_direct:
                dm = (weapon.direct + weapon.splash) * weapon.factor
            elif rng.random() < weapon.p_splash:
                dm = weapon.splash * weapon.factor
            else:
                dm = 0.0
        else:
            dm = expected
        out.append((t, dm))
    return out


def duel_outcome(my_ehp, my_ws, my_starts, side, rear_mult, horizon, rng):
    mine = []
    for w, s in zip(my_ws, my_starts):
        for t, d in raw_events(w, s, horizon, rng):
            mult = rear_mult if t < side.rear_window else 1.0
            mine.append((t, d * mult, "me"))
    theirs = []
    for w, s in zip(side.weapons, side.start):
        for t, d in raw_events(w, s, horizon, rng):
            mult = rear_mult if t < side.rear_on_me else 1.0
            theirs.append((t, d * mult, "them"))
    evs = sorted(mine + theirs)
    hp_me, hp_them = my_ehp, side.hp
    for t, d, who in evs:
        if who == "me":
            hp_them -= d
            if hp_them <= 0:
                return True, hp_me
        else:
            hp_me -= d
            if hp_me <= 0:
                return False, 0.0
    return False, hp_me  # unfinished = not a win


def random_duel(rng):
    kinds = ["lightning", "laser", "mortar", None, None]
    mine = rng.choice(kinds)
    theirs = ["gun"] + ([rng.choice(["lightning", "laser", "mortar"])] if rng.random() < 0.6 else [])
    my_cubes = rng.randint(0, 6)
    en_cubes = rng.randint(0, 6)
    dist = rng.choice([20, 35, 50, 80, 120])
    my_hp = rng.uniform(0.25, 1.0) * 1400 * (1 + 0.04 * my_cubes)
    en_hp = rng.uniform(0.25, 1.0) * 1400 * (1 + 0.04 * en_cubes)
    face = rng.random() < 0.8
    o = T.make_obs(hp=my_hp, max_hp=1400 * (1 + 0.04 * my_cubes), weapons=[mine] if mine else [], cubes=my_cubes,
                   enemies=[T.enemy(dist=dist, hp=en_hp, max_hp=1400 * (1 + 0.04 * en_cubes), cubes=en_cubes,
                                    weapons=tuple(theirs), face_me=face)], alive=1)
    return o


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 1500
    mc = int(sys.argv[2]) if len(sys.argv) > 2 else 40
    rng = random.Random(12345)
    eng = E.Engagement(T.HELLO)
    k = eng.k
    rows = []
    for _ in range(n):
        o = random_duel(rng)
        m = o["mechs"][0]
        res, _ = eng.evaluate(o, m, o["mechs"])
        me = o["self"]
        tw = m["weapons"]
        ws, st = eng._my_weapons(me, E.dist2(m["pos"], me["pos"]), tw, eng.cfg["weapons"])
        side = eng._enemy_side(m, me, o["t"], 1.0, True)
        wins = 0
        hp_left = 0.0
        for _ in range(mc):
            w, h = duel_outcome(eng._my_ehp(me), ws, st, side, eng.cfg["mech"]["rear_mult"], k["horizon_s"], rng)
            wins += w
            hp_left += h if w else 0.0
        rows.append((res.ratio, wins / mc, hp_left / max(wins, 1)))
    bins = [0, 0.3, 0.6, 0.8, 1.0, 1.2, 1.4, 1.7, 2.0, 3.0, 5.0, 99.1]
    print(f"{n} random duels x {mc} stochastic replays; estimator params: hit_gun={k['hit_gun']} hit_laser={k['hit_laser']}")
    print(f"{'R bin':>12} {'n':>5} {'P(win)':>7} {'avg HP left | win':>18}")
    pts = []
    for lo, hi in zip(bins[:-1], bins[1:]):
        b = [r for r in rows if lo <= r[0] < hi]
        if not b:
            continue
        pw = sum(r[1] for r in b) / len(b)
        hl = sum(r[2] for r in b) / len(b)
        pts.append(((lo + min(hi, 6)) / 2, pw))
        print(f"{lo:>5.1f}-{min(hi, 99):<5.1f} {len(b):>5} {pw:>7.2f} {hl:>18.0f}")
    # logistic fit: logit(p) = a + b ln R  (least squares on clipped bins)
    xs, ys = [], []
    for r, p, _ in rows:
        if r <= 0.05 or r >= 98:
            continue
        p = min(0.99, max(0.01, p))
        xs.append(math.log(r))
        ys.append(math.log(p / (1 - p)))
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
    a = my - b * mx
    print(f"\nlogit P(win) = {a:.2f} + {b:.2f} * ln R")
    for pw in (0.5, 0.6, 0.7, 0.8, 0.9):
        R = math.exp((math.log(pw / (1 - pw)) - a) / b)
        print(f"  P(win)={pw:.0%} needs R >= {R:.2f}")


if __name__ == "__main__":
    main()
