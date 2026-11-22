#!/usr/bin/env python3
"""Death anatomy from giddy traces (MECH_TRACE_FILE=prefix -> prefix-<pid>.jsonl, one file per match).

    python tools/death_anatomy.py DIR [DIR ...]

Per match: death time, kills by 150 / 300 s, cubes, upgrades. Fights = stretches with damage taken or dealt, split by
5+ quiet seconds. For each fight: start time, HP at start, peak attackers, damage taken/dealt, outcome. Then pooled:
how the fatal fight looks (attackers, start HP, modes, retreat share, rear-hit share, damage dealt), and how fights
in 150-300 s compare with fights before 150 s.
"""
import glob
import json
import os
import statistics as st
import sys
from collections import Counter


def load(path):
    rows = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return rows


def fights(rows, quiet=5.0):
    out, cur, last = [], None, -1e9
    for i, r in enumerate(rows):
        active = r["dmg"] > 0 or r["dealt"] > 0
        if active:
            if cur is None or r["t"] - last > quiet:
                if cur:
                    out.append(cur)
                prev = rows[max(0, i - 1)]
                cur = {"start": r["t"], "hp0": prev["hp"] / max(1, prev["max_hp"]), "rows": []}
            last = r["t"]
        if cur is not None and r["t"] - last <= quiet:
            cur["rows"].append(r)
    if cur:
        out.append(cur)
    for fi in out:
        rs = fi["rows"]
        fi["end"] = rs[-1]["t"]
        fi["taken"] = sum(r["dmg"] for r in rs)
        fi["rear"] = sum(r["rear_dmg"] for r in rs)
        fi["dealt"] = sum(r["dealt"] for r in rs)
        fi["peak_hitters"] = max(r["hitters6"] for r in rs)
        fi["peak_los"] = max(r["los160"] for r in rs)
        fi["kills"] = rs[-1]["kills"] - rs[0]["kills"] + (1 if rs[0]["kills"] > (rs[0]["kills"]) else 0)
        fi["modes"] = Counter(r["mode"].split(":")[0] for r in rs)
        fi["retreat"] = sum(r["retreat"] for r in rs) / len(rs)
        fi["hp_end"] = rs[-1]["hp"] / max(1, rs[-1]["max_hp"])
    return out


def main():
    files = []
    for d in sys.argv[1:]:
        files += sorted(glob.glob(os.path.join(d, "*.jsonl")))
    matches = []
    for p in files:
        rows = load(p)
        if len(rows) < 20:
            continue
        matches.append((p, rows))
    print(f"matches {len(matches)}")
    deaths, early, mid = [], [], []
    k150, k300, ktot, dtimes, cubes = [], [], [], [], []
    for p, rows in matches:
        T = rows[-1]["t"]
        died = T < 470
        kat = lambda t: max([r["kills"] for r in rows if r["t"] <= t] or [0])
        k150.append(kat(150)); k300.append(kat(300)); ktot.append(rows[-1]["kills"])
        cubes.append(rows[-1]["cubes"])
        if died:
            dtimes.append(T)
        fs = fights(rows)
        for f in fs:
            k_before = max([r["kills"] for r in rows if r["t"] < f["start"]] or [0])
            f["kills"] = f["rows"][-1]["kills"] - k_before
            (early if f["start"] < 150 else mid if f["start"] < 300 else []).append(f)
        if died and fs:
            deaths.append((p, T, fs[-1], rows))
    n = len(matches)
    print(f"kills by 150 s {st.mean(k150):.2f}  by 300 s {st.mean(k300):.2f}  total {st.mean(ktot):.2f}  "
          f"(real giddy: 4.58 / 5.73 / 5.73)")
    print(f"died {len(dtimes)}/{n}  death time median {st.median(dtimes):.0f} s  "
          f"before 150 s {sum(t < 150 for t in dtimes)}  150-300 s {sum(150 <= t < 300 for t in dtimes)}  "
          f"after {sum(t >= 300 for t in dtimes)}   cubes at end mean {st.mean(cubes):.1f}")
    ups = Counter(u for _, rows in matches for u in (rows[-1].get("upgrades") or []))
    wpn = Counter(tuple(rows[-1].get("weapons") or []) for _, rows in matches)
    print(f"upgrades taken (all matches): {dict(ups)}")
    print(f"loadout at end: {dict(wpn)}")

    def summ(label, fs):
        if not fs:
            print(f"{label}: none")
            return
        won = [f for f in fs if f["kills"] > 0]
        print(f"{label}: {len(fs)} fights, {len(won)} with a kill; start HP median {st.median(f['hp0'] for f in fs):.2f}; "
              f"peak attackers mean {st.mean(f['peak_hitters'] for f in fs):.2f} (>=2 in {sum(f['peak_hitters'] >= 2 for f in fs)}); "
              f"taken/dealt {sum(f['taken'] for f in fs):.0f}/{sum(f['dealt'] for f in fs):.0f}; "
              f"rear share {sum(f['rear'] for f in fs) / max(1, sum(f['taken'] for f in fs)):.2f}; "
              f"retreat share {st.mean(f['retreat'] for f in fs):.2f}")

    summ("fights starting < 150 s", early)
    summ("fights starting 150-300 s", mid)

    print("\nFATAL fights:")
    ff = [d[2] for d in deaths]
    summ("fatal", ff)
    modes = Counter()
    for f in ff:
        modes.update(f["modes"])
    tot = sum(modes.values()) or 1
    print("fatal fight time by mode:", {k: round(v / tot, 2) for k, v in modes.most_common()})
    last_modes = Counter()
    for _, T, f, rows in deaths:
        last = [r for r in rows if r["t"] >= T - 3]
        last_modes.update(r["mode"].split(":")[0] for r in last)
    tot = sum(last_modes.values()) or 1
    print("last 3 s by mode:", {k: round(v / tot, 2) for k, v in last_modes.most_common()})
    print("\nper death: t, fight start, HP at start, peak attackers, peak LOS<160, taken, dealt, kills in fight, rear share, retreat share")
    for p, T, f, rows in sorted(deaths, key=lambda d: d[1]):
        print(f"  {T:6.1f}  {f['start']:6.1f}  {f['hp0']:.2f}  {f['peak_hitters']}  {f['peak_los']}  {f['taken']:6.0f}  "
              f"{f['dealt']:6.0f}  {f['kills']}  {f['rear'] / max(1, f['taken']):.2f}  {f['retreat']:.2f}  {os.path.basename(p)}")


if __name__ == "__main__":
    main()
