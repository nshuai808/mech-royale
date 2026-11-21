"""Ablation evaluation of H-PER on the synthetic harness.  python3 tools/per_eval.py [seeds] [duration] [fire_rate] [variants,comma] [open|hunt|late|late_hunt]"""
import gzip
import json
import math
import os
import statistics as st
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from geom import Geom
from percept import Perception, load_params
from per_sim import Scenario

KIT = os.path.join(ROOT, "kit")
HELLO = json.loads(gzip.open(KIT + "/check/stream.jsonl.gz", "rt").readline())
GEOM = Geom(KIT + "/arena")

VARIANTS = {
    "full": {},
    "no_sound": {"use_sound": False},
    "no_carve": {"use_carve": False},
    "no_events": {"use_events": False},
    "dead_reckon": {"use_sound": False, "use_carve": False, "use_events": False},
    "sigma_x0.5": {"bearing_sigma_scale": 0.5},
    "sigma_x2": {"bearing_sigma_scale": 2.0},
    "slow_vel": {"vel_tau_s": 8.0},
    "fast_vel": {"vel_tau_s": 0.8},
    "walk_2": {"walk_sigma": 2.0},
    "walk_6": {"walk_sigma": 6.0},
    "no_hunt": {"hunt_auto": False},
    "hunt_fix4": {"hunt_auto": False, "hunt_fixed_mps": 4.0},
    "hunt_fix8": {"hunt_auto": False, "hunt_fixed_mps": 8.0},
}
BUCKETS = [(0, 2), (2, 5), (5, 10), (10, 20), (20, 60), (60, 999)]


SCEN = {"open": {}, "hunt": {"hunt_frac": 1.0}, "late": {"zone_r": 170.0, "sep": 25.0}, "late_hunt": {"zone_r": 170.0, "sep": 25.0, "hunt_frac": 1.0}}


def run(variant, seeds, duration, fire_rate, warm=15.0, scen="open"):
    P = load_params(overrides=VARIANTS[variant])
    err = {b: [] for b in BUCKETS}
    base = {b: [] for b in BUCKETS}
    inm = {b: [] for b in BUCKETS}
    m60, hot_prec, hot_rec, acct, ms = [], [], [], [], []
    reacq = []
    evt = []
    for seed in seeds:
        sc = Scenario(HELLO, GEOM, seed, duration=duration, fire_rate=fire_rate, **SCEN[scen])
        per = Perception(HELLO, params=dict(P), geom=GEOM)
        per.rng.seed(seed)
        while sc.t < duration:
            sc.step()
            obs = sc.hello_obs()
            t0 = time.perf_counter()
            w = per.update(obs)
            ms.append((time.perf_counter() - t0) * 1000)
            if sc.t < warm:
                continue
            acct.append(abs(len(per.tracks) + per.cloud.mass - (obs["alive"] - 1)))
            unseen_truth = []
            for e in sc.enemies:
                if not e.alive:
                    continue
                tr = per.tracks.get(e.id)
                if tr is None:
                    unseen_truth.append(e)
                    cl = per.cloud
                    m = sum(wt for a, b, wt in zip(cl.px, cl.py, cl.w) if (a - e.pos[0]) ** 2 + (b - e.pos[1]) ** 2 < 3600)
                    m60.append(min(1.0, m))
                elif not tr.vis and tr.px is not None and not tr.ever_vis:
                    mx, my, sg = per._mean_xy(tr)
                    evt.append((math.hypot(mx - e.pos[0], my - e.pos[1]), per._mass_within(tr, e.pos[0], e.pos[1], 60.0)))
                elif not tr.vis and tr.px is not None:
                    age = sc.t - (tr.t_lost or sc.t)
                    mx, my, sg = per._mean_xy(tr)
                    e1 = math.hypot(mx - e.pos[0], my - e.pos[1])
                    e0 = math.hypot(tr.last_pos[0] - e.pos[0], tr.last_pos[1] - e.pos[1])
                    for b in BUCKETS:
                        if b[0] <= age < b[1]:
                            err[b].append(e1)
                            base[b].append(e0)
                            inm[b].append(per._mass_within(tr, e.pos[0], e.pos[1], 40.0))
            hs = [c for c in w.hot]
            for c in hs:
                hot_prec.append(1.0 if any(math.hypot(c.pos[0] - e.pos[0], c.pos[1] - e.pos[1]) < 60 for e in unseen_truth) else 0.0)
            for e in unseen_truth:
                hot_rec.append(1.0 if any(math.hypot(c.pos[0] - e.pos[0], c.pos[1] - e.pos[1]) < 60 for c in hs) else 0.0)
        reacq += per.stats["reacq"]
    ms.sort()
    out = {"variant": variant,
           "m60": st.mean(m60) if m60 else float("nan"),
           "hot_prec": st.mean(hot_prec) if hot_prec else float("nan"),
           "hot_rec": st.mean(hot_rec) if hot_rec else float("nan"),
           "acct": st.mean(acct),
           "p50": ms[len(ms) // 2], "p99": ms[int(len(ms) * 0.99)], "max": ms[-1],
           "n_reacq": len(reacq),
           "evt_n": len(evt), "evt_err": st.median([x[0] for x in evt]) if evt else float("nan"), "evt_m60": st.mean([x[1] for x in evt]) if evt else float("nan"),
           "reacq_err": st.median([r[1] for r in reacq]) if reacq else float("nan"),
           "reacq_base": st.median([r[2] for r in reacq]) if reacq else float("nan"),
           "buckets": {b: (len(err[b]), st.median(err[b]) if err[b] else None, st.median(base[b]) if base[b] else None,
                           st.mean(inm[b]) if inm[b] else None) for b in BUCKETS}}
    return out


def main():
    ns = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    dur = float(sys.argv[2]) if len(sys.argv) > 2 else 90.0
    fr = float(sys.argv[3]) if len(sys.argv) > 3 else 0.1
    names = sys.argv[4].split(",") if len(sys.argv) > 4 else list(VARIANTS)
    scen = sys.argv[5] if len(sys.argv) > 5 else "open"
    seeds = list(range(100, 100 + ns))
    print("seeds", len(seeds), "duration", dur, "fire_rate", fr, "scenario", scen)
    print("%-12s %6s %8s %8s %6s %6s %6s | reacq n  med_err  med_last" % ("variant", "m60", "hot_prec", "hot_rec", "acct", "p50ms", "p99ms"))
    res = {}
    for v in names:
        r = res[v] = run(v, seeds, dur, fr, scen=scen)
        print("%-12s %6.3f %8.3f %8.3f %6.2f %6.2f %6.2f | %5d %7.1f %9.1f" % (
            v, r["m60"], r["hot_prec"], r["hot_rec"], r["acct"], r["p50"], r["p99"], r["n_reacq"], r["reacq_err"], r["reacq_base"]))
    print("\nevent-identified (never visible) tracks: n / median err m / mass within 60 m")
    for v, r in res.items():
        print("%-12s n=%d err=%.0f m60=%.2f" % (v, r["evt_n"], r["evt_err"], r["evt_m60"]))
    print("\nhidden identified tracks (previously seen): median error m (filter / last-seen), mass within 40 m of truth, n")
    print("%-12s" % "variant" + "".join("%18s" % ("%d-%ds" % b) for b in BUCKETS))
    for v, r in res.items():
        row = ""
        for b in BUCKETS:
            n, e1, e0, im = r["buckets"][b]
            row += "%18s" % ("-" if n == 0 else "%.0f/%.0f %.2f n%d" % (e1, e0, im, n))
        print("%-12s%s" % (v, row))
    json.dump({k: {**v, "buckets": {"%d-%d" % b: x for b, x in v["buckets"].items()}} for k, v in res.items()},
              open("/tmp/per_eval_%s.json" % scen, "w"), indent=1)


if __name__ == "__main__":
    main()
