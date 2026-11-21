"""Shared replay-file format for tools/record.py, tools/replay.py and tools/analyze.py. Standard library only.

A replay file is gzipped JSON lines, one per message, in the order they happened:

    {"w": 12.3456, "d": "in",    "m": {...server message: hello / obs / end...}}
    {"w": 12.3581, "d": "out",   "m": {...bot message: ready / action...}, "lat_ms": 12.5}
    {"w": 12.3570, "d": "trace", "m": {"tick": 508, "mode": "to_zone", ...}}   # botlog.trace()
    {"w": 12.3600, "d": "err",   "s": "a stderr line from the bot"}

`w` is wall-clock seconds since the recording started. `lat_ms` is the bot's answer time for that
observation (from handing it the obs to reading its action), measured outside the bot.
"""
import gzip
import json
import os
import threading
import time
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPLAYS = os.path.join(ROOT, "replays")
KIT_STREAM = os.path.join(ROOT, "kit", "check", "stream.jsonl.gz")
KIT_ARENA = os.path.join(ROOT, "kit", "arena")


def default_out(prefix):
    os.makedirs(REPLAYS, exist_ok=True)
    return os.path.join(REPLAYS, f"{prefix}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.jsonl.gz")


class Writer:
    """Thread-safe replay-file writer."""

    def __init__(self, path):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.path = path
        self.t0 = time.perf_counter()
        self.f = gzip.open(path, "wt", compresslevel=3)
        self.lock = threading.Lock()

    def now(self):
        return time.perf_counter() - self.t0

    def write(self, d, msg=None, raw=None, **extra):
        rec = {"w": round(self.now(), 4), "d": d}
        if msg is not None:
            rec["m"] = msg
        if raw is not None:
            rec["s"] = raw
        rec.update(extra)
        line = json.dumps(rec, separators=(",", ":")) + "\n"
        with self.lock:
            self.f.write(line)

    def close(self):
        with self.lock:
            self.f.close()


def read(path):
    """Yield records from a replay file. A raw server stream (like kit/check/stream.jsonl.gz, one server
    message per line) is accepted too and comes back as "in" records."""
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if "d" in rec and ("m" in rec or "s" in rec):
                yield rec
            else:
                yield {"w": None, "d": "in", "m": rec}


def server_messages(path):
    """Just the server -> bot messages (hello, obs..., end) of a replay file or raw stream."""
    return [r["m"] for r in read(path) if r["d"] == "in" and isinstance(r.get("m"), dict)]


def parse_trace(line):
    """A botlog TRACE line -> dict, or None."""
    if line.startswith("TRACE "):
        try:
            return json.loads(line[6:])
        except ValueError:
            return None
    return None
