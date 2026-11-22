#!/usr/bin/env python3
"""Fuzz any bot binary over the real protocol: hello, then generated observations one at a time (lockstep).
Reports panics (the Go bot prints them to stderr with MECH_DEBUG=1), bad answers, and answer times.

    python tools/fuzz_bin.py [--trials 4] [--seed 7] -- giddy/mechbot

Observations are the kit's 300 recorded ones, mutated: every weapon, empty slots, enemies at all ranges and heights,
NPCs, loot, offers, drops, events, the zone at radius 0, and positions at or past the map edge.
"""
import argparse
import copy
import gzip
import json
import math
import os
import random
import subprocess
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    argv = sys.argv[1:]
    if "--" not in argv:
        sys.exit(__doc__)
    i = argv.index("--")
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=4)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--slow-ms", type=float, default=10.0, help="list decisions slower than this")
    a = ap.parse_args(argv[:i])
    cmd = argv[i + 1:]

    L = [json.loads(l) for l in gzip.open(os.path.join(ROOT, "kit/check/stream.jsonl.gz"), "rt")]
    hello, obs = L[0], [m for m in L if m.get("type") == "obs"]
    hello["map"]["dir"] = os.path.join(ROOT, "kit", "arena")
    cfg = hello["config"]
    W = cfg["weapons"]
    rng = random.Random(a.seed)

    def wobs(kind):
        w = {"kind": kind, "cooldown": rng.choice([0, 0, 0.5]), "stats": dict(W[kind])}
        if kind == "gun":
            w.update(ammo=rng.randint(0, 12), reload=rng.choice([0, 0, 1.2]))
        if kind == "laser":
            w["charge"] = rng.choice([0, 0, 0.3, 0.74, 0.8, 2.0])
        return w

    def mutate(o):
        o = copy.deepcopy(o)
        s = o["self"]
        slot0 = rng.choice([wobs("gun")] * 4 + [None])
        s["weapons"] = [slot0, rng.choice([None, wobs("laser"), wobs("lightning"), wobs("mortar")])]
        s["energy"] = rng.uniform(0, 100)
        s["in_zone"] = rng.random() > 0.2
        s["grounded"] = rng.random() > 0.2
        s["hp"] = rng.uniform(1, 1400)
        s["cubes"] = rng.choice([0, 0, 3, 10, 25])
        if rng.random() < 0.05:  # at or past the map edge, or high in the air
            s["pos"] = [rng.choice([-2000, 2000, 0]), rng.choice([-2000, 2000, 0]), rng.uniform(-5, 80)]
        x, y, z = s["pos"]
        for _ in range(rng.randint(0, 6)):
            ang, d = rng.uniform(0, 6.28), rng.choice([0.0, rng.uniform(0.5, 260)])
            o["mechs"].append({"id": rng.randint(0, 15), "kind": "mech",
                               "pos": [x + d * math.cos(ang), y + d * math.sin(ang), z + rng.uniform(-3, 30)],
                               "vel": [rng.uniform(-15, 15), rng.uniform(-15, 15), rng.uniform(-10, 10)],
                               "aim": [rng.uniform(-4, 4), rng.uniform(-1, 1)], "hp": rng.uniform(0, 2200),
                               "max_hp": 1400, "cubes": rng.choice([0, 5, 30]),
                               "weapons": rng.choice([[], ["gun"], ["gun", "laser"], ["mortar", "lightning"]]),
                               "charging": rng.random() < 0.2})
        if rng.random() < 0.3:
            o["mechs"].append({"id": 100 + rng.randint(0, 11), "kind": "npc",
                               "pos": [x + rng.uniform(-60, 60), y + rng.uniform(-60, 60), z],
                               "vel": [0, 0, 0], "aim": [0, 0], "hp": 350, "max_hp": 350})
        o["pickups"] = [{"id": 8000 + k, "kind": rng.choice(["gun", "mortar", "laser", "lightning"]),
                         "pos": [x + rng.uniform(-6, 6), y + rng.uniform(-6, 6), z]} for k in range(rng.randint(0, 3))]
        o["cubes"] = [{"id": 5000 + k, "pos": [x + rng.uniform(-60, 60), y + rng.uniform(-60, 60), z]}
                      for k in range(rng.randint(0, 4))]
        o["crates"] = [{"id": 6000 + k, "pos": [x + rng.uniform(-120, 120), y + rng.uniform(-120, 120), z], "hp": 100}
                       for k in range(rng.randint(0, 3))]
        o["projectiles"] = [{"id": 9000 + k, "kind": rng.choice(["gun", "mortar"]),
                             "pos": [x + rng.uniform(-30, 30), y + rng.uniform(-30, 30), z + rng.uniform(0, 30)],
                             "vel": [rng.uniform(-200, 200), rng.uniform(-200, 200), rng.uniform(-30, 30)]}
                            for k in range(rng.randint(0, 4))]
        if rng.random() < 0.1:
            o["offer"] = {"id": 1, "expires": o["t"] + 5,
                          "choices": [{"id": u["id"], "name": "", "desc": ""} for u in rng.sample(cfg["upgrades"], 3)]}
        if rng.random() < 0.2:
            o["drops"] = [{"id": 20000, "pos": [x + rng.uniform(-100, 100), y + rng.uniform(-100, 100), z],
                           "radius": 8, "lands_in": rng.choice([0, 10]), "capture_s": 4, "progress": 0,
                           "holder": rng.choice([None, s["id"], 5])}]
        ev = []
        if rng.random() < 0.3:
            ev.append({"type": "damaged", "amount": 45, "weapon": rng.choice(["gun", "laser", "zone", "npc"]),
                       "bearing": rng.choice([None, 1.0]), "by": rng.choice([None, 4, 104]), "rear": True})
        if rng.random() < 0.1:
            ev.append({"type": "kill", "target": rng.randint(0, 15)})
        if rng.random() < 0.1:
            ev.append({"type": "hit", "target": 4, "amount": 45, "weapon": "gun"})
        o["events"] = ev
        if rng.random() < 0.05:
            o["zone"].update(next_radius=0, radius=rng.choice([0, 25]), shrink_start=o["t"] - 1, shrink_end=o["t"] + 20)
        if rng.random() < 0.02:
            o["alive"] = rng.choice([1, 2, 16])
        return o

    env = dict(os.environ, MECH_DEBUG="1")
    panics, bad, times, n = 0, 0, [], 0
    first_panic = None
    slow = []
    for trial in range(a.trials):
        p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             text=True, bufsize=1, env=env)
        err_lines = []
        th = threading.Thread(target=lambda: err_lines.extend(p.stderr), daemon=True)
        th.start()
        p.stdin.write(json.dumps(hello) + "\n")
        p.stdin.flush()
        p.stdout.readline()  # ready
        for o in obs:
            o = mutate(o)
            t0 = time.perf_counter()
            p.stdin.write(json.dumps(o) + "\n")
            p.stdin.flush()
            line = p.stdout.readline()
            ms = (time.perf_counter() - t0) * 1000
            times.append(ms)
            if ms > a.slow_ms:
                sl = o["self"]
                slow.append((round(ms, 1), o["tick"], [round(v) for v in sl["pos"]], len(o["mechs"]), sl["hp"] < 500,
                             [w and w["kind"] for w in sl["weapons"]], o["zone"]["next_radius"]))
            n += 1
            try:
                ans = json.loads(line)
                assert ans.get("tick") == o["tick"], "tick"
                for v in (ans.get("move") or []) + (ans.get("aim") or []):
                    assert isinstance(v, (int, float)) and math.isfinite(v), "non-finite"
                if "pick" in ans and ans["pick"] is not None:
                    assert 0 <= ans["pick"] < 3, "pick"
            except Exception as e:  # noqa: BLE001
                bad += 1
                if bad <= 3:
                    print("bad answer:", e, line[:200])
        p.stdin.close()
        p.wait(timeout=10)
        th.join(timeout=2)
        txt = "".join(err_lines)
        k = txt.count("PANIC tick")
        panics += k
        if k and first_panic is None:
            first_panic = txt[txt.index("PANIC tick"):][:2500]
    times.sort()
    print(f"decisions {n}  panics {panics}  bad answers {bad}  "
          f"p50 {times[len(times) // 2]:.1f} ms  p99 {times[int(len(times) * 0.99)]:.1f} ms  worst {times[-1]:.1f} ms")
    for row in sorted(slow, reverse=True)[:12]:
        print("slow ms/tick/pos/mechs/lowhp/weapons/next_r:", row)
    if first_panic:
        print("first panic:\n" + first_panic)


if __name__ == "__main__":
    main()
