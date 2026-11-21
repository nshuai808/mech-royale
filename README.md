# mech-royale

Our bot for the Builders Buildathon **Mech Royale** track: a 16-mech battle royale on a 3D map of the OSU Oval.
Score = mean of `16 - place` over 48 practice matches. **Placement beats kills.** Baseline (kit example bot): 1.15.

Submissions close **Sun 11:00 AM ET**. Max 4 submissions per hour per team.

## Layout

| Path | What |
| --- | --- |
| `Dockerfile` | What the scorer builds. Must stay at the top of the repo. |
| `bot.py` | Our bot (`Bot.act()` runs 10×/s, must answer in < 50 ms). Started from the kit's example. |
| `mechfight.py` | The kit's protocol wrapper (stdlib only). Shouldn't need editing. |
| `kit/protocol.md` | **The full rulebook.** Read it first. |
| `kit/check/check.py` | Conformance check: the scorer runs this before every match. |
| `kit/arena/` | The map (`world.json`, `terrain.i16`); mounted at `/arena` in matches. |
| `kit/mechfight.schema.json` | JSON Schema for every message. |
| `botlog.py` | `trace()` for per-decision logging; off unless `MECH_TRACE=1`, so free in matches. |
| `tools/` | Local logging harness: `record.py`, `replay.py`, `analyze.py` (see below). Not in the image. |
| `CLAUDE.md` | Context and status for Claude Code sessions. |

`kit/` is excluded from the Docker image by `.dockerignore`.

## Runtime limits (what can break a submission)

- No network at runtime. 1 CPU, 512 MB RAM.
- Runs as uid 65534 (not root). Install packages system-wide in the Dockerfile, never `pip install --user`.
- Read-only disk. Only `/tmp` (64 MB) is writable. The map is at `/arena` (read-only).
- 50 ms per observation. A late answer means the mech freezes without firing. Leave a margin.
- A crash leaves the mech as a sitting target.
- Pin any versions you download (the Dockerfile pins the base image by digest).

## Test locally

Quick protocol check (no Docker):

```sh
python kit/check/check.py -- python -u bot.py
```

Full check exactly as the scorer runs it (needs Docker):

```sh
docker build -t mech-royale .
python kit/check/check.py --map-dir /arena -- docker run --rm -i --network none --cpus 1 --memory 512m --read-only --tmpfs /tmp:rw,size=64m --user 65534:65534 -v "$PWD/kit/arena:/arena:ro" mech-royale
```

## Logging harness

Matches show us only the score (no stderr), so we look at the bot locally. All stdlib Python; files land in `replays/` (gitignored).

```sh
# feed the kit's 300 recorded observations to the bot and log every decision + answer time
python3 tools/replay.py -- python3 -u bot.py
# same inside the match sandbox (the real 50 ms test); needs the image built
python3 tools/replay.py --repeat 3 --map-dir /arena -- docker run --rm -i --network none --cpus 1 --memory 512m --read-only --tmpfs /tmp:rw,size=64m --user 65534:65534 -e MECH_TRACE=1 -v "$PWD/kit/arena:/arena:ro" mech-royale
# record any run, e.g. the conformance check
python3 kit/check/check.py -- python3 tools/record.py -- python3 -u bot.py
# read a log, or compare two bot versions on the same stream
python3 tools/analyze.py replays/<file>.jsonl.gz --csv out.csv
python3 tools/analyze.py --diff replays/A.jsonl.gz replays/B.jsonl.gz
```

Local simulator and fuzz test (see CLAUDE.md for what the sim does and doesn't model):

```sh
python3 tools/sim.py --matches 12 --seed 1 -- python3 -u bot.py   # prints a score like the real one
python3 tools/fuzz.py                                               # exceptions + worst decision time
```

In `bot.py`, call `botlog.trace(obs["tick"], mode="...", ...)` once per decision so reports show what the bot was trying to do.
Replayed observations don't react to the bot: they test timing, crashes and decisions, not how well it plays.

## Team workflow

- `main` is what gets scored (submitting with no commit hash scores the newest commit on the default branch).
  Keep `main` passing `check.py`.
- Do experiments on branches (`git switch -c <name>`), then merge into `main` once they pass the check.
- Note each submission's commit hash and score below, so we can pick our best for the final.
- **Never force-push or delete a submitted commit.** The repo must stay public with every submitted commit until results are out.

## Submissions log

| Time | Commit | Score | Notes |
| --- | --- | --- | --- |
| Fri ~8:35 PM | `c995b28` | 1.15 | Starter bot + logging harness. Same as the baseline: the starter is deterministic on the fixed seeds. |
| Fri ~8:40 PM | `3c42f4f` | **2.92** | Survival bot v2: hide when 2+ see us, fight only the hunter, A* pathing, cover. Sim had predicted ~2.0. |
| Sat | `eed4dc6` | 0.73 | `v2-zone-drops` (v2-integrated arbiter + zone.py + drops.py). Big regression; the integrated arbiter, not zone/drops, is the suspect (it was already below main in the sim). |
| Sat | `b064eeb` | **3.02** | `claude/nifty-galileo-lw5l5t`: main's v2 + zone.py (critical -> zone run) + drops.py (supply drops, hold the ring while capturing). Sim had it neutral (2.21 vs 2.35). |
| Sat | `ee4f3fc` | 2.90 | + face threat while evading, time-based third-party check, unstick sidestep. Neutral (noise ~0.3); sim also neutral. |
| Sat | `5c59a78` | **3.40** | ee4f3fc + aggressive loot: lightning first, two specials (drop the gun), wider loot range, shoot crates. New best. |
| Sat | `5d80994` | 3.40 | + farther early loot, lightning closes in, weapon-aware TTK and upgrades. Neutral. |
| Sat | `21267c5` | 3.27 | + laser fights to 250 m, removed '2 close and HP < 85% -> evade'. Neutral/slightly worse. |
