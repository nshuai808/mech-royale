"""Fight breakdown of sim replays (stdlib only): python tools/fights.py replays/sim-*.jsonl.gz
kills, how many enemies hit us, how it ended. Answers: do we die entering fights damaged, or losing at full HP?"""
import gzip, json, sys, collections

allf = []
for p in sys.argv[1:]:
    fights, cur, last_ev = [], None, -99
    hp = mx = None; t = 0; place = None; kills_seen = 0
    for l in gzip.open(p, "rt"):
        r = json.loads(l)
        if r["d"] != "in":
            continue
        m = r["m"]
        if m.get("type") == "end":
            place = m.get("place")
            continue
        if m.get("type") != "obs":
            continue
        t = m["t"]; s = m["self"]; hp, mx = s["hp"], s["max_hp"]
        evs = [e for e in m.get("events", []) if e.get("type") in ("damaged", "hit", "kill", "killed") and e.get("weapon") != "zone"]
        if evs:
            if cur is None or t - last_ev > 5:
                if cur:
                    cur["end_hp"] = cur["last_hp"]; fights.append(cur)
                cur = {"t0": t, "hp0": hp / mx, "attackers": set(), "dmg_in": 0, "kills": 0, "last_hp": hp / mx}
            last_ev = t
            for e in evs:
                if e["type"] == "damaged":
                    cur["dmg_in"] += e.get("amount", 0)
                    if e.get("by") is not None:
                        cur["attackers"].add(e["by"])
                if e["type"] == "kill":
                    cur["kills"] += 1
            cur["last_hp"] = hp / mx
    if cur:
        cur["end_hp"] = cur["last_hp"]; cur["died"] = True; fights.append(cur)
    for f in fights:
        f.setdefault("died", False)
    allf.append((p, t, fights))

n_f = sum(len(f) for _, _, f in allf)
deaths = [f[-1] for _, _, f in allf if f]
print(f"matches {len(allf)}  fights {n_f}  ({n_f / len(allf):.1f}/match)")
won = [f for _, _, fs in allf for f in fs if not f["died"]]
print(f"fights survived: {len(won)}  kills in them {sum(f['kills'] for f in won)}  mean HP start {sum(f['hp0'] for f in won) / max(1, len(won)):.0%}  end {sum(f['end_hp'] for f in won) / max(1, len(won)):.0%}")
print(f"fatal fights: {len(deaths)}  mean HP at start {sum(f['hp0'] for f in deaths) / len(deaths):.0%}")
b = collections.Counter("full (>=90%)" if f["hp0"] >= 0.9 else "partial (50-90%)" if f["hp0"] >= 0.5 else "low (<50%)" for f in deaths)
print("  fatal fight started at HP:", dict(b))
a = collections.Counter(min(len(f["attackers"]), 3) for f in deaths)
print("  attackers in fatal fight (3 = 3+):", dict(sorted(a.items())))
a2 = collections.Counter(min(len(f["attackers"]), 3) for f in won)
print("  attackers in survived fights   :", dict(sorted(a2.items())))
gaps = []
for _, _, fs in allf:
    for x, y in zip(fs, fs[1:]):
        gaps.append(y["t0"] - x["t0"])
if gaps:
    gaps.sort()
    print(f"  time between fight starts: median {gaps[len(gaps) // 2]:.0f} s")
