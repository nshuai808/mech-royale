#!/usr/bin/env python3
"""Record everything a bot hears and says, without changing it. Standard library only.

    python3 tools/record.py [--out replays/NAME.jsonl.gz] -- python3 -u bot.py

It runs the bot command as a child process and sits between it and whatever is driving it (check.py,
a simulator, a live server): every line is passed through untouched and also written to a replay file
(format in tools/replaylog.py), with the bot's answer time for every observation. It sets MECH_TRACE=1
so botlog.trace() lines are captured too. Other stderr lines are captured and passed through.

Typical use: record the kit's conformance stream while checking it:

    python3 kit/check/check.py -- python3 tools/record.py -- python3 -u bot.py

Then read the result:  python3 tools/analyze.py replays/<newest>.jsonl.gz
Don't put this in the Dockerfile: it's for local runs only (tools/ is in .dockerignore).
"""
import argparse
import json
import os
import subprocess
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import replaylog as rl  # noqa: E402


def main():
    argv = sys.argv[1:]
    if "--" not in argv:
        sys.exit("usage: record.py [--out FILE] -- BOT COMMAND...")
    i = argv.index("--")
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", help="replay file to write (default: replays/rec-<time>.jsonl.gz)")
    a = ap.parse_args(argv[:i])
    cmd = argv[i + 1 :]
    out = a.out or rl.default_out("rec")
    log = rl.Writer(out)
    log.write("meta", {"tool": "record", "cmd": cmd})
    env = dict(os.environ, MECH_TRACE="1", PYTHONUNBUFFERED="1")
    child = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    sent_at = {}  # tick -> wall time we handed that obs to the bot

    def pump_in():
        # Forward input in the chunks it arrives in, so observations sent together (a bot that fell
        # behind) still reach the bot together and its newest-observation logic behaves as unwrapped.
        fd, buf = sys.stdin.fileno(), b""
        try:
            while True:
                chunk = os.read(fd, 1 << 20)
                if not chunk:
                    break
                try:
                    child.stdin.write(chunk)
                    child.stdin.flush()
                except (BrokenPipeError, OSError):
                    break
                now = log.now()
                buf += chunk
                *lines, buf = buf.split(b"\n")
                for raw in lines:
                    if not raw.strip():
                        continue
                    try:
                        msg = json.loads(raw)
                    except ValueError:
                        log.write("in", raw=raw.decode("utf-8", "replace"))
                        continue
                    if isinstance(msg, dict) and msg.get("type") == "obs":
                        sent_at[msg.get("tick")] = now
                    log.write("in", msg)
        finally:
            try:
                child.stdin.close()
            except OSError:
                pass

    def pump_out():
        for raw in child.stdout:
            sys.stdout.buffer.write(raw)
            sys.stdout.buffer.flush()
            try:
                msg = json.loads(raw)
            except ValueError:
                log.write("out", raw=raw.decode("utf-8", "replace").rstrip("\n"))
                continue
            extra = {}
            if isinstance(msg, dict) and msg.get("tick") in sent_at:
                extra["lat_ms"] = round((log.now() - sent_at.pop(msg["tick"])) * 1000, 2)
            log.write("out", msg, **extra)

    def pump_err():
        for raw in child.stderr:
            line = raw.decode("utf-8", "replace").rstrip("\n")
            tr = rl.parse_trace(line)
            if tr is not None:
                log.write("trace", tr)
            else:
                log.write("err", raw=line)
                sys.stderr.write(line + "\n")
                sys.stderr.flush()

    threads = [threading.Thread(target=f, daemon=True) for f in (pump_in, pump_out, pump_err)]
    for t in threads:
        t.start()
    code = child.wait()
    threads[1].join(timeout=2)
    threads[2].join(timeout=2)
    log.close()
    sys.stderr.write(f"[record] wrote {out}\n")
    sys.exit(code)


if __name__ == "__main__":
    main()
