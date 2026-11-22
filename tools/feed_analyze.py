#!/usr/bin/env python3
"""Per-bot report over recorded spectator-feed matches (tools/feed_record.py). Standard library only.

    python3 tools/feed_analyze.py replays/feed/*.jsonl.gz            # one row per bot name, all matches pooled
    python3 tools/feed_analyze.py --per-match replays/feed/*.jsonl.gz
    python3 tools/feed_analyze.py --csv out.csv replays/feed/*.jsonl.gz  # one row per (match, mech)

Reads the "mechreplay/1" files: header (bot names, slots), frames (`m` rows: id x y z aim_yaw aim_pitch hp energy
flags cubes max_hp slot0 slot1), events (`ev`) and the final "result" line (place, kills, damage, cubes_max,
upgrades, loadout, first_weapon_t, death_t, killed_with, ...). Points = 16 - place, as on the practice board.

Columns: n matches, pts, kills, dmg dealt/taken, cubes max, cubes at 60/150 s, max HP at the end, first weapon
time, died < 60 s (share), death time, roof % (feet > 4 m above the terrain), air % (not grounded), drops taken.
Also prints points by final loadout, and the correlation of points with cubes, kills and damage.
"""
import argparse
import csv
import gzip
import json
import math
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)


def ground_fn():
    try:
        from nav import Map
        mp = Map(os.path.join(ROOT, "kit", "arena"), 9, 1.2, 50, 8)
        return mp.ground
    except Exception:
        return None


def load(path, ground):
    op = gzip.open if path.endswith(".gz") else open
    with op(path, "rt") as f:
        lines = [json.loads(l) for l in f if l.strip()]
    if not lines or lines[0].get("type") != "header":
        return None
    h = lines[0]
    res = next((o for o in lines if o.get("type") == "result"), None)
    if res is None:
        return None
    hz = h.get("tick_hz", 20)
    names = {m["id"]: (m.get("name") or "?") for m in h["mechs"]}
    st = {i: {"frames": 0, "roof": 0, "air": 0, "c60": 0, "c150": 0, "maxhp_end": 0} for i in names}
    for o in lines[1:]:
        if "m" not in o or "t" not in o:
            continue
        t = o["t"] / hz
        for row in o["m"]:
            i, x, y, z, _, _, hp, en, fl, cu, mh = row[:11]
            s = st.get(i)
            if s is None:
                continue
            s["frames"] += 1
            if not (fl & 1):
                s["air"] += 1
            if ground is not None and z - ground(x, y) > 4.0:
                s["roof"] += 1
            if t <= 60:
                s["c60"] = cu
            if t <= 150:
                s["c150"] = cu
            s["maxhp_end"] = mh
    out = []
    for m in res["mechs"]:
        i = m["id"]
        s = st.get(i, {})
        fr = max(1, s.get("frames", 0))
        out.append({
            "file": os.path.basename(path), "seed": h.get("seed"), "id": i, "name": names.get(i, m.get("name")),
            "pts": 16 - m["place"], "place": m["place"], "kills": m.get("kills", 0),
            "dealt": m.get("damage_dealt", 0), "taken": m.get("damage_taken", 0),
            "cubes": m.get("cubes_max", 0), "c60": s.get("c60", 0), "c150": s.get("c150", 0),
            "maxhp": s.get("maxhp_end", 0), "first_wep": m.get("first_weapon_t"),
            "death": m.get("death_t"), "killed_with": m.get("killed_with"),
            "loadout": "+".join(k for k in (m.get("loadout") or []) if k) or "-",
            "upgrades": ",".join(m.get("upgrades") or []), "drops": m.get("drops_taken", 0),
            "roof": 100.0 * s.get("roof", 0) / fr, "air": 100.0 * s.get("air", 0) / fr,
            "rear": (m.get("effects") or {}).get("rear", 0),
        })
    return out


def corr(xs, ys):
    n = len(xs)
    if n < 3:
        return float("nan")
    mx, my = sum(xs) / n, sum(ys) / n
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy) if sx and sy else float("nan")


def mean(v):
    v = [x for x in v if x is not None]
    return sum(v) / len(v) if v else float("nan")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--csv")
    ap.add_argument("--per-match", action="store_true")
    a = ap.parse_args()
    ground = ground_fn()
    rows, used = [], 0
    for p in a.files:
        r = load(p, ground)
        if r:
            rows += r
            used += 1
            if a.per_match:
                print(f"{os.path.basename(p)}: " + ", ".join(f"{x['name']} {x['place']}" for x in sorted(r, key=lambda x: x["place"])))
    print(f"{used} complete match(es), {len(rows)} mech-matches")
    if not rows:
        return
    if a.csv:
        with open(a.csv, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    by = defaultdict(list)
    for r in rows:
        by[r["name"]].append(r)
    hdr = (f"{'bot':22} {'n':>3} {'pts':>5} {'kills':>5} {'dealt':>6} {'taken':>6} {'cubes':>5} {'c60':>4} {'c150':>4} "
           f"{'maxHP':>5} {'1stwep':>6} {'d<60':>5} {'death':>5} {'roof%':>5} {'air%':>4} {'drops':>5}")
    print(hdr)
    for name, rs in sorted(by.items(), key=lambda kv: -mean([r["pts"] for r in kv[1]])):
        early = sum(1 for r in rs if r["death"] is not None and r["death"] < 60) / len(rs)
        print(f"{name[:22]:22} {len(rs):>3} {mean([r['pts'] for r in rs]):5.2f} {mean([r['kills'] for r in rs]):5.2f} "
              f"{mean([r['dealt'] for r in rs]):6.0f} {mean([r['taken'] for r in rs]):6.0f} {mean([r['cubes'] for r in rs]):5.1f} "
              f"{mean([r['c60'] for r in rs]):4.1f} {mean([r['c150'] for r in rs]):4.1f} {mean([r['maxhp'] for r in rs]):5.0f} "
              f"{mean([r['first_wep'] for r in rs]):6.1f} {early:5.0%} {mean([r['death'] for r in rs]):5.0f} "
              f"{mean([r['roof'] for r in rs]):5.1f} {mean([r['air'] for r in rs]):4.0f} {mean([r['drops'] for r in rs]):5.2f}")
    lo = defaultdict(list)
    for r in rows:
        lo[r["loadout"]].append(r["pts"])
    print("\npoints by final loadout: " + ", ".join(f"{k} {mean(v):.2f} (n={len(v)})" for k, v in sorted(lo.items(), key=lambda kv: -mean(kv[1]))))
    pts = [r["pts"] for r in rows]
    print("correlation with points: " + ", ".join(f"{k} {corr([r[k] for r in rows], pts):+.2f}" for k in ("cubes", "kills", "dealt", "taken", "roof", "air")))
    up = defaultdict(lambda: defaultdict(int))
    for r in rows:
        if r["upgrades"]:
            up[r["name"]][r["upgrades"].split(",")[0]] += 1
    print("first upgrade by bot: " + "; ".join(f"{n}: " + ", ".join(f"{u} {c}" for u, c in sorted(d.items(), key=lambda kv: -kv[1])) for n, d in sorted(up.items())))


if __name__ == "__main__":
    main()
