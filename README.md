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

## Team workflow

- `main` is what gets scored (submitting with no commit hash scores the newest commit on the default branch).
  Keep `main` passing `check.py`.
- Do experiments on branches (`git switch -c <name>`), then merge into `main` once they pass the check.
- Note each submission's commit hash and score below, so we can pick our best for the final.
- **Never force-push or delete a submitted commit.** The repo must stay public with every submitted commit until results are out.

## Submissions log

| Time | Commit | Score | Notes |
| --- | --- | --- | --- |
| | | | |
