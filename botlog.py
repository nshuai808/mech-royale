"""Per-decision trace for the local tools. Off unless MECH_TRACE=1, so it costs nothing in real matches.

    import botlog
    botlog.trace(obs["tick"], mode="to_zone", target=None, why="outside next circle")

Each call writes one `TRACE {json}` line to stderr. tools/record.py and tools/replay.py set MECH_TRACE=1,
capture these lines into the replay file, and tools/analyze.py summarizes them (e.g. time spent per mode).
Keep fields small and JSON-friendly: numbers, short strings, ids.
"""
import json
import os
import sys

ON = os.environ.get("MECH_TRACE") == "1"


def trace(tick, **fields):
    if ON:
        sys.stderr.write("TRACE " + json.dumps({"tick": tick, **fields}, separators=(",", ":"), default=str) + "\n")
        sys.stderr.flush()
