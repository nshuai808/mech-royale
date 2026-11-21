#!/usr/bin/env python3
"""Fuzz bot.Bot.act with generated observations (every weapon, loot, offers, drops, effects, the final zone).
Catches exceptions and slow decisions in code paths the recorded stream and the sim never reach.
    python3 tools/fuzz.py
"""
import copy
import gzip
import json
import math
import os
import random
import sys
import time
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
import mechfight as mf  # noqa: E402
mf.run = lambda *a, **k: None          # import bot.py without starting the loop
import bot as B  # noqa: E402
L = [json.loads(l) for l in gzip.open('kit/check/stream.jsonl.gz', 'rt')]
hello, obs = L[0], [m for m in L if m.get('type') == 'obs']
hello['map']['dir'] = 'kit/arena'
cfg = hello['config']; W = cfg['weapons']
rng = random.Random(7)
def wobs(kind):
    w = {"kind": kind, "cooldown": rng.choice([0, 0, 0.5]), "stats": dict(W[kind])}
    if kind == 'gun': w.update(ammo=rng.randint(0, 12), reload=rng.choice([0, 0, 1.2]))
    if kind == 'laser': w['charge'] = rng.choice([0, 0, 0.3, 0.74, 0.8])
    return w
errors, worst, n = 0, 0.0, 0
for trial in range(4):
    bot = B.Bot(copy.deepcopy(hello))
    for o in obs:
        o = copy.deepcopy(o)
        s = o['self']
        s['weapons'] = [wobs('gun'), rng.choice([None, wobs('laser'), wobs('lightning'), wobs('mortar')])]
        s['energy'] = rng.uniform(0, 100); s['in_zone'] = rng.random() > 0.2; s['grounded'] = rng.random() > 0.2
        s['hp'] = rng.uniform(5, 1400)
        x, y, z = s['pos']
        for _ in range(rng.randint(0, 4)):
            a, d = rng.uniform(0, 6.28), rng.uniform(2, 220)
            o['mechs'].append({"id": rng.randint(0, 15), "kind": "mech", "pos": [x + d*math.cos(a), y + d*math.sin(a), z + rng.uniform(-3, 20)],
                               "vel": [rng.uniform(-15, 15), rng.uniform(-15, 15), 0], "aim": [0, 0], "hp": rng.uniform(1, 1400), "max_hp": 1400,
                               "weapons": ["gun"], "charging": rng.random() < 0.2})
        if rng.random() < 0.3:
            o['mechs'].append({"id": 100 + rng.randint(0, 11), "kind": "npc", "pos": [x + rng.uniform(-60, 60), y + rng.uniform(-60, 60), z], "vel": [0, 0, 0], "aim": [0, 0], "hp": 350, "max_hp": 350})
        o['pickups'] = [{"id": 8000 + i, "kind": rng.choice(["mortar", "laser", "lightning"]), "pos": [x + rng.uniform(-6, 6), y + rng.uniform(-6, 6), z]} for i in range(rng.randint(0, 3))]
        o['cubes'] = [{"id": 5000 + i, "pos": [x + rng.uniform(-40, 40), y + rng.uniform(-40, 40), z]} for i in range(rng.randint(0, 2))]
        if rng.random() < 0.1:
            o['offer'] = {"id": 1, "expires": o['t'] + 5, "choices": [{"id": u['id'], "name": "", "desc": ""} for u in rng.sample(cfg['upgrades'], 3)]}
        if rng.random() < 0.2:
            o['drops'] = [{"id": 20000, "pos": [x + rng.uniform(-100, 100), y + rng.uniform(-100, 100), z], "radius": 8, "lands_in": rng.choice([0, 10]), "capture_s": 4, "progress": 0, "holder": rng.choice([None, s['id'], 5])}]
        ev = []
        if rng.random() < 0.3: ev.append({"type": "damaged", "amount": 45, "weapon": rng.choice(["gun", "laser", "zone", "npc"]), "bearing": rng.choice([None, 1.0]), "by": rng.choice([None, 4, 104]), "rear": True})
        if rng.random() < 0.1: ev.append({"type": "effect", "effect": rng.choice(["short", "cookoff", "concuss"]), "by": 3})
        if rng.random() < 0.1: ev.append({"type": "hit", "target": 4, "amount": 45, "weapon": "gun"})
        o['events'] = ev
        if rng.random() < 0.05:  # the zone at its end: radius 0
            o['zone'].update(next_radius=0, radius=25, shrink_start=o['t'] - 1, shrink_end=o['t'] + 20)
        t0 = time.perf_counter()
        try:
            a = bot.act(o)
            json.dumps(a)
            assert all(math.isfinite(v) for v in a.get('move', []) + a.get('aim', [])), a
            if 'pick' in a: assert 0 <= a['pick'] < 3
        except Exception:
            errors += 1
            if errors <= 3: traceback.print_exc()
        worst = max(worst, (time.perf_counter() - t0) * 1000); n += 1
print(f"decisions {n}  exceptions {errors}  worst {worst:.1f} ms")
