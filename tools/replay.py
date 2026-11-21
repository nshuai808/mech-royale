#!/usr/bin/env python3
"""Feed recorded observations to a bot, one decision at a time, and record what it does. Stdlib only.

    python3 tools/replay.py -- python3 -u bot.py                       # the kit's 300-observation stream
    python3 tools/replay.py replays/rec-....jsonl.gz -- python3 -u bot.py   # any replay file or raw stream
    python3 tools/replay.py --repeat 3 -- docker run --rm -i --network none --cpus 1 --memory 512m \
        --read-only --tmpfs /tmp:rw,size=64m --user 65534:65534 -e MECH_TRACE=1 \
        -v "$PWD/kit/arena:/arena:ro" mech-royale                       # timing inside the match sandbox
        (add --map-dir /arena for docker so hello points at the mounted map)

Like the server, it sends one observation, waits for the answer, then sends the next. Unlike the
server it never skips: a late answer is waited for (up to 1 s) and counted as late, so every
decision gets logged. The observations are recorded and do not react to the bot, so this tests
timing, crashes and what the bot *decides* given real situations, not how well it plays.

Writes a replay file (tools/replaylog.py format) per pass and prints answer-time percentiles.
Compare two bot versions on the same stream with:  python3 tools/analyze.py --diff A.jsonl.gz B.jsonl.gz
"""
import argparse
import json
import os
import queue
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import replaylog as rl  # noqa: E402


def one_pass(cmd, msgs, out, budget_ms, warn_ms, map_dir, quiet, source):
    hello = dict(msgs[0])
    if hello.get("type") != "hello":
        sys.exit("the stream doesn't start with a hello")
    hello["map"] = dict(hello.get("map", {}), dir=map_dir)
    obs = [m for m in msgs if m.get("type") == "obs"]
    end = next((m for m in reversed(msgs) if m.get("type") == "end"), {"type": "end", "place": 0, "kills": 0})

    log = rl.Writer(out)
    log.write("meta", {"tool": "replay", "source": source, "cmd": cmd})
    env = dict(os.environ, MECH_TRACE="1", PYTHONUNBUFFERED="1")
    child = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    q = queue.Queue()
    errs = []

    def pump_out():
        for raw in child.stdout:
            q.put((log.now(), raw))
        q.put((log.now(), None))

    def pump_err():
        for raw in child.stderr:
            line = raw.decode("utf-8", "replace").rstrip("\n")
            tr = rl.parse_trace(line)
            if tr is not None:
                log.write("trace", tr)
            else:
                log.write("err", raw=line)
                errs.append(line)
                if not quiet:
                    sys.stderr.write(f"[bot] {line}\n")

    for f in (pump_out, pump_err):
        threading.Thread(target=f, daemon=True).start()

    def send(m):
        child.stdin.write((json.dumps(m, separators=(",", ":")) + "\n").encode())
        child.stdin.flush()
        log.write("in", m)

    def next_msg(deadline):
        """(wall, parsed or raw str) or None on timeout; ('eof', None) if the bot exited."""
        try:
            at, raw = q.get(timeout=max(0.0, deadline - log.now()))
        except queue.Empty:
            return None
        if raw is None:
            return ("eof", None)
        try:
            return (at, json.loads(raw))
        except ValueError:
            return (at, raw.decode("utf-8", "replace").rstrip("\n"))

    times, late, missing, crashed = [], 0, 0, None
    t0 = log.now()
    send(hello)
    got = next_msg(t0 + 20)
    if got is None or got[0] == "eof":
        crashed = "no ready within 20 s" if got is None else "exited before ready"
    else:
        log.write("out", got[1] if isinstance(got[1], dict) else None, raw=None if isinstance(got[1], dict) else got[1])
        if not quiet:
            print(f"ready in {(got[0] - t0) * 1000:.0f} ms")

    for o in ([] if crashed else obs):
        sent = log.now()
        send(o)
        while True:
            got = next_msg(sent + budget_ms / 1000 + 1.0)
            if got is None:
                missing += 1
                break
            if got[0] == "eof":
                crashed = f"bot exited at tick {o['tick']}"
                break
            at, m = got
            if not isinstance(m, dict):
                log.write("out", raw=m)
                continue
            lat = round((at - sent) * 1000, 2)
            log.write("out", m, lat_ms=lat)
            if m.get("tick") == o["tick"]:
                times.append(lat)
                late += lat > budget_ms
                break
        if crashed:
            break

    if not crashed:
        try:
            send(end)
            child.stdin.close()
            child.wait(timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            child.kill()
    else:
        child.kill()
    time.sleep(0.05)
    log.close()

    times.sort()
    pct = lambda p: times[min(len(times) - 1, int(p * len(times)))] if times else 0.0
    warn = sum(t > warn_ms for t in times)
    print(f"observations: {len(obs)}  answered: {len(times)}  late (>{budget_ms:.0f} ms): {late}  "
          f"over {warn_ms:.0f} ms: {warn}  no answer: {missing}")
    print(f"answer ms: p50 {pct(0.5):.1f}  p90 {pct(0.9):.1f}  p99 {pct(0.99):.1f}  max {pct(1.0):.1f}")
    if crashed:
        print(f"CRASH: {crashed}. Last stderr lines:")
        for line in errs[-12:]:
            print(f"  {line}")
    print(f"wrote {out}")
    return 1 if crashed or late else 0


def main():
    argv = sys.argv[1:]
    if "--" not in argv:
        sys.exit("usage: replay.py [STREAM] [--out FILE] [--repeat N] [--map-dir DIR] -- BOT COMMAND...")
    i = argv.index("--")
    ap = argparse.ArgumentParser()
    ap.add_argument("stream", nargs="?", default=rl.KIT_STREAM, help="replay file or raw server stream (default: the kit's)")
    ap.add_argument("--out", help="replay file to write (default: replays/replay-<time>.jsonl.gz)")
    ap.add_argument("--repeat", type=int, default=1, help="passes with a fresh bot each (timing varies run to run)")
    ap.add_argument("--map-dir", default=rl.KIT_ARENA, help="hello.map.dir to send (use /arena for docker)")
    ap.add_argument("--budget-ms", type=float, default=50)
    ap.add_argument("--warn-ms", type=float, default=35, help="flag answers slower than this (leave margin under 50)")
    ap.add_argument("-q", "--quiet", action="store_true", help="don't echo the bot's stderr")
    a = ap.parse_args(argv[:i])
    cmd = argv[i + 1 :]
    msgs = rl.server_messages(a.stream)
    worst = 0
    for n in range(a.repeat):
        out = a.out or rl.default_out("replay")
        if a.repeat > 1:
            print(f"--- pass {n + 1} of {a.repeat}")
            if a.out:
                root, ext = out.split(".jsonl", 1) if ".jsonl" in out else (out, "")
                out = f"{root}-{n + 1}.jsonl{ext}"
            else:
                time.sleep(1.01)  # distinct timestamped names
        worst = max(worst, one_pass(cmd, msgs, out, a.budget_ms, a.warn_ms, a.map_dir, a.quiet, os.path.relpath(a.stream, rl.ROOT)))
    sys.exit(worst)


if __name__ == "__main__":
    main()
