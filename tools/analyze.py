#!/usr/bin/env python3
"""Turn a replay file into a readable report. Standard library only.

    python3 tools/analyze.py replays/x.jsonl.gz              # report
    python3 tools/analyze.py replays/x.jsonl.gz --csv x.csv  # plus one row per decision (spreadsheet / plots)
    python3 tools/analyze.py --diff A.jsonl.gz B.jsonl.gz    # where two bot versions decided differently
    python3 tools/analyze.py kit/check/stream.jsonl.gz       # raw server streams work too (no actions)

Report sections: result, answer times, survival (HP, zone, damage taken by weapon/attacker, rear hits),
offense, loot and upgrades, behavior (botlog.trace modes), the last seconds before death, a timeline,
and the bot's stderr errors.
"""
import argparse
import csv
import math
import os
import signal
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import replaylog as rl  # noqa: E402


def load(path):
    hello, end, ready, meta = None, None, None, {}
    obs, acts, lats, traces, errs = [], {}, {}, {}, []
    for r in rl.read(path):
        d, m = r["d"], r.get("m")
        if d == "meta" and isinstance(m, dict):
            meta = m
        elif d == "in" and isinstance(m, dict):
            t = m.get("type")
            if t == "hello":
                hello = m
            elif t == "obs":
                obs.append(m)  # deduped by tick below (check.py re-sends recent ones in bursts)
            elif t == "end":
                end = m
        elif d == "out" and isinstance(m, dict):
            if m.get("type") == "ready":
                ready = m
            elif "tick" in m:
                acts[m["tick"]] = m
                if "lat_ms" in r:
                    lats[m["tick"]] = r["lat_ms"]
        elif d == "trace" and isinstance(m, dict) and "tick" in m:
            traces[m["tick"]] = m
        elif d == "err":
            errs.append(r.get("s", ""))
    seen = {}
    for o in obs:
        seen[o["tick"]] = o
    obs = [seen[t] for t in sorted(seen)]
    return hello, ready, obs, acts, lats, traces, errs, end, meta


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(p * len(xs)))] if xs else 0.0


def zone_edge(o):
    """Meters inside the current circle (negative = outside), and inside the next circle."""
    x, y = o["self"]["pos"][:2]
    z = o["zone"]
    cur = z["radius"] - math.dist((x, y), z["center"])
    nxt = z["next_radius"] - math.dist((x, y), z["next_center"])
    return cur, nxt


def enemies(o):
    return [m for m in o.get("mechs", []) if m.get("kind") == "mech"]


def report(path, csv_path=None, every=10.0, death_s=6.0):
    hello, ready, obs, acts, lats, traces, errs, end, meta = load(path)
    p = print
    p(f"== {os.path.basename(path)}")
    if not obs:
        p("no observations in this file")
        return
    cfg = (hello or {}).get("config", {})
    budget = cfg.get("bot", {}).get("tick_budget_ms", 50)
    name = (ready or {}).get("name", "?")
    p(f"bot {name!r}  slot {(hello or {}).get('slot', '?')}  decisions {len(obs)}  "
      f"match time {obs[0]['t']:.1f}-{obs[-1]['t']:.1f} s")
    last = obs[-1]
    if end:
        p(f"RESULT  place {end.get('place')}  ->  {16 - end.get('place', 16)} points   kills {end.get('kills')}")
    else:
        p(f"RESULT  no `end` message (last seen alive={last['alive']}, would place {last['alive']} if dead now)")
    if meta.get("tool") == "replay" or not acts:
        p(f"NOTE    replayed observations ({meta.get('source', 'raw stream')}): HP, damage, zone, result and death below")
        p("        are the ORIGINAL recording's. Only answer times, actions (fire/take/pick) and modes are this bot's.")
    p()

    # ---- timing
    if lats:
        L = list(lats.values())
        p("-- answer time")
        p(f"answered {len(L)}/{len(obs)}   p50 {pct(L, .5):.1f}  p90 {pct(L, .9):.1f}  p99 {pct(L, .99):.1f}  "
          f"max {max(L):.1f} ms   over 35 ms: {sum(x > 35 for x in L)}   late (>{budget} ms): {sum(x > budget for x in L)}")
        slow = sorted(lats.items(), key=lambda kv: -kv[1])[:3]
        p("slowest ticks: " + ", ".join(f"{t} ({ms:.1f} ms)" for t, ms in slow))

    # ---- survival
    dmg_w, dmg_by, rear, rear_n = Counter(), Counter(), 0.0, 0
    hit_w, kills, took, failed, upgrades, effects = Counter(), [], [], Counter(), [], Counter()
    for o in obs:
        for e in o.get("events", []):
            t = e.get("type")
            if t == "damaged":
                dmg_w[e.get("weapon")] += e.get("amount", 0)
                if e.get("by") is not None:
                    dmg_by[e["by"]] += e.get("amount", 0)
                if e.get("rear"):
                    rear += e.get("amount", 0)
                    rear_n += 1
            elif t == "hit":
                hit_w[e.get("weapon")] += e.get("amount", 0)
            elif t == "kill":
                kills.append((o["t"], e.get("target")))
            elif t == "took":
                took.append((o["t"], e.get("kind"), e.get("slot")))
            elif t == "take_failed":
                failed[e.get("reason")] += 1
            elif t == "upgrade":
                upgrades.append((o["t"], e.get("id")))
            elif t == "effect":
                effects[e.get("effect")] += 1
    hp = [o["self"]["hp"] for o in obs]
    out_zone = sum(1 for o in obs if not o["self"]["in_zone"])
    dt = 1.0 / (cfg.get("match", {}).get("tick_hz", 20) / cfg.get("match", {}).get("decide_every", 2))
    total = sum(dmg_w.values())
    p("-- survival")
    p(f"hp start {hp[0]:.0f}  min {min(hp):.0f}  end {hp[-1]:.0f}   outside zone {out_zone * dt:.1f} s   "
      f"damage taken {total:.0f}")
    if total:
        p("taken by weapon: " + ", ".join(f"{w} {v:.0f} ({v / total:.0%})" for w, v in dmg_w.most_common()))
        p("taken by attacker: " + ", ".join(f"#{k} {v:.0f}" for k, v in dmg_by.most_common(5)))
        p(f"from behind: {rear_n} hits, {rear:.0f} dmg ({rear / total:.0%} of all)  <- face your attacker: rear hits x1.5")
    if effects:
        p("effects on you: " + ", ".join(f"{k} x{v}" for k, v in effects.items()))

    # ---- offense / loot
    p("-- offense and loot")
    p(f"damage dealt: {sum(hit_w.values()):.0f}" + (" (" + ", ".join(f"{w} {v:.0f}" for w, v in hit_w.most_common()) + ")" if hit_w else "")
      + f"   kills: {len(kills)}" + (" " + str([f"#{k}@{t:.0f}s" for t, k in kills]) if kills else ""))
    p(f"cubes end {last['self']['cubes']:.0f}   weapons end {[w['kind'] if w else None for w in last['self']['weapons']]}")
    if took:
        p("took: " + ", ".join(f"{k}->slot{s:.0f}@{t:.0f}s" for t, k, s in took))
    if failed:
        p("take failed: " + ", ".join(f"{r} x{n}" for r, n in failed.items()))
    offers = [o for o in obs if o.get("offer")]
    if offers:
        picked = sum(1 for o in offers if "pick" in acts.get(o["tick"], {}))
        p(f"offers seen on {len(offers)} decisions, picked on {picked}; upgrades: {[u for _, u in upgrades]}")

    # ---- behavior from traces
    if traces:
        modes = Counter(tr.get("mode", "?") for tr in traces.values())
        n = sum(modes.values())
        p("-- behavior (botlog.trace)")
        p("modes: " + ", ".join(f"{m} {c / n:.0%}" for m, c in modes.most_common()))
        switches = sum(1 for a, b in zip(sorted(traces), sorted(traces)[1:]) if traces[a].get("mode") != traces[b].get("mode"))
        p(f"mode switches: {switches} ({switches / max(1, n) * 10:.2f}/s)  <- many per second = dithering")

    # ---- last seconds
    p(f"-- last {death_s:.0f} s" + (" before death" if end and end.get("place", 1) > 1 else ""))
    t_end = last["t"]
    for o in obs:
        if o["t"] < t_end - death_s:
            continue
        ev = [e for e in o.get("events", []) if e.get("type") == "damaged"]
        a = acts.get(o["tick"], {})
        cur, nxt = zone_edge(o)
        tr = traces.get(o["tick"], {})
        if ev or o is last or int(o["t"] * 10) % 10 == 0:
            dmg = ", ".join(f"-{e['amount']:.0f} {e['weapon']}" + (f" #{e['by']}" if e.get('by') is not None else "") + (" REAR" if e.get("rear") else "") for e in ev)
            p(f"  t={o['t']:6.1f} hp {o['self']['hp']:5.0f} en {o['self']['energy']:3.0f} "
              f"{'IN ' if o['self']['in_zone'] else 'OUT'} edge {cur:+5.0f}m  see {len(enemies(o))}  alive {o['alive']:2}  "
              f"{tr.get('mode', '') :10} fire {a.get('fire', '')}  {dmg}")

    # ---- timeline
    p(f"-- timeline (every {every:.0f} s)")
    p("      t     hp   en zone  edge  next  see alive  mode")
    nxt_t = obs[0]["t"]
    for o in obs:
        if o["t"] + 1e-9 < nxt_t and o is not last:
            continue
        nxt_t = o["t"] + every
        cur, nx = zone_edge(o)
        p(f"  {o['t']:5.0f} {o['self']['hp']:6.0f} {o['self']['energy']:4.0f} {'in ' if o['self']['in_zone'] else 'OUT'} "
          f"{cur:+5.0f} {nx:+5.0f} {len(enemies(o)):4} {o['alive']:5}  {traces.get(o['tick'], {}).get('mode', '')}")

    # ---- errors
    real = [e for e in errs if e.strip()]
    if real:
        p(f"-- bot stderr ({len(real)} lines; first 15)")
        for e in real[:15]:
            p("  " + e)

    if csv_path:
        cols = ["tick", "t", "hp", "energy", "x", "y", "z", "in_zone", "zone_edge", "next_edge", "enemies_seen",
                "alive", "dmg_taken", "lat_ms", "move_x", "move_y", "aim_yaw", "aim_pitch", "fire0", "fire1", "boost",
                "jump", "take", "pick", "mode"]
        with open(csv_path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(cols)
            for o in obs:
                s, a = o["self"], acts.get(o["tick"], {})
                cur, nx = zone_edge(o)
                mv, aim, fire = a.get("move") or [None, None], a.get("aim") or [None, None], a.get("fire") or [None, None]
                w.writerow([o["tick"], o["t"], s["hp"], s["energy"], *[round(v, 2) for v in s["pos"]], s["in_zone"],
                            round(cur, 1), round(nx, 1), len(enemies(o)), o["alive"],
                            sum(e.get("amount", 0) for e in o.get("events", []) if e.get("type") == "damaged"),
                            lats.get(o["tick"]), mv[0], mv[1], aim[0], aim[1], fire[0], fire[1] if len(fire) > 1 else None,
                            a.get("boost"), a.get("jump"), a.get("take"), a.get("pick"),
                            traces.get(o["tick"], {}).get("mode")])
        p(f"wrote {csv_path}")


def diff(pa, pb, show=12):
    """Compare the actions two runs took on the same observations."""
    _, ra, oa, aa, la, ta, _, _, _ = load(pa)
    _, rb, ob, ab, lb, tb, _, _, _ = load(pb)
    ticks = sorted(set(aa) & set(ab))
    if not ticks:
        print("no common ticks: were both runs fed the same stream?")
        return

    def near(u, v, tol):
        if u is None or v is None:
            return u == v
        if isinstance(u, list) and isinstance(v, list):
            return len(u) == len(v) and all(near(x, y, tol) for x, y in zip(u, v))
        if isinstance(u, (int, float)) and isinstance(v, (int, float)):
            return abs(u - v) <= tol
        return u == v

    fields = [("move", 0.05), ("aim", 0.05), ("fire", 0), ("boost", 0), ("jump", 0), ("take", 0), ("pick", 0), ("drop", 0)]
    per, rows = Counter(), []
    for t in ticks:
        a, b = aa[t], ab[t]
        dif = [f for f, tol in fields if not near(a.get(f), b.get(f), tol)]
        if ta.get(t, {}).get("mode") != tb.get(t, {}).get("mode"):
            dif.append("mode")
        for f in dif:
            per[f] += 1
        if dif:
            rows.append((t, dif))
    print(f"A {os.path.basename(pa)} ({(ra or {}).get('name')})   B {os.path.basename(pb)} ({(rb or {}).get('name')})")
    print(f"common decisions {len(ticks)}   differing {len(rows)} ({len(rows) / len(ticks):.0%})")
    if per:
        print("by field: " + ", ".join(f"{f} {n}" for f, n in per.most_common()))
    if la and lb:
        print(f"answer p50/p99 ms  A {pct(list(la.values()), .5):.1f}/{pct(list(la.values()), .99):.1f}   "
              f"B {pct(list(lb.values()), .5):.1f}/{pct(list(lb.values()), .99):.1f}")
    for t, dif in rows[:show]:
        sa = {f: aa[t].get(f) for f, _ in fields if f in dif}
        sb = {f: ab[t].get(f) for f, _ in fields if f in dif}
        ma, mb = ta.get(t, {}).get("mode"), tb.get(t, {}).get("mode")
        print(f"  tick {t}: A {sa}{' ' + str(ma) if ma else ''}  |  B {sb}{' ' + str(mb) if mb else ''}")


def main():
    if hasattr(signal, "SIGPIPE"):
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)  # quiet exit when piped into head/less
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+")
    ap.add_argument("--csv", help="write one row per decision to this CSV")
    ap.add_argument("--every", type=float, default=10.0, help="timeline step in seconds")
    ap.add_argument("--death", type=float, default=6.0, help="seconds to show before the end")
    ap.add_argument("--diff", action="store_true", help="compare the decisions of two replay files")
    a = ap.parse_args()
    if a.diff:
        if len(a.files) != 2:
            sys.exit("--diff takes exactly two files")
        diff(*a.files)
        return
    for i, f in enumerate(a.files):
        if i:
            print()
        report(f, a.csv if len(a.files) == 1 else None, a.every, a.death)


if __name__ == "__main__":
    main()
