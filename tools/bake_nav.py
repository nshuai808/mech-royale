#!/usr/bin/env python3
"""Bake the navigation grid into navmap.bin (stdlib only). Run from the repo root after the map or
mech numbers change; commit the result. The bot checks a hash of world.json + terrain.i16 and rebuilds
at runtime if it does not match, so a stale bake is safe but slower to start.

    python3 tools/bake_nav.py                 # uses kit/arena and the hello in kit/check/stream.jsonl.gz
    python3 tools/bake_nav.py --margin 0.5 --out navmap.bin
"""
import argparse
import gzip
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import nav  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arena", default=os.path.join(ROOT, "kit", "arena"))
    ap.add_argument("--stream", default=os.path.join(ROOT, "kit", "check", "stream.jsonl.gz"))
    ap.add_argument("--margin", type=float, default=nav.NavParams().clearance_margin_m)
    ap.add_argument("--out", default=os.path.join(ROOT, nav.NavParams().baked_file))
    a = ap.parse_args()
    with gzip.open(a.stream, "rt") as f:
        hello = json.loads(f.readline())
    m = hello["config"]["mech"]
    t = time.perf_counter()
    nm = nav.build_map(a.arena, m["radius"], a.margin, m["step_up"], m["height"])
    dt = time.perf_counter() - t
    data = nm.dumps()
    with open(a.out, "wb") as f:
        f.write(data)
    free = sum(1 for b in nm.blocked if not b)
    print(f"built {nm.W}x{nm.H} cells in {dt:.1f}s; free {free}/{len(nm.blocked)}; components "
          f"{len(set(nm.comp)) - 1}; wrote {a.out} ({len(data) / 1024:.0f} KB); key {nm.key[:12]}")


if __name__ == "__main__":
    main()
