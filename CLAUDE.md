# CLAUDE.md: context for Claude Code sessions on this repo

Nathanael's bot for the Builders Buildathon **Mech Royale** track (UMich IBE team). Read `README.md` for
layout and limits, and `kit/protocol.md` for the full rules. This file is the short version plus where we are.

## The game in five lines
- 16 mechs, OSU campus map, shrinking zone (closes ~6:55, match max 8:00). Bot answers JSON obs with a JSON action.
- Score = mean of `16 - place` over 48 practice matches. **Placement beats kills.** Baseline 1.15.
- Practice opponents: 15 house bots acting as one squad that **hunts us, weakest first**. The final is a
  free-for-all against other teams' bots, so prefer robust behavior over exploits of the house bots.
- Decision every 0.1 s, **50 ms wall-time budget on 1 CPU**. Late = coast 1 s without firing, then idle.
- Matches show us nothing but the score: **no stderr, no logs**. Local tools are our only visibility.

## How practice scoring really works (key insight)
The house squad never fights itself, so in practice **our points = house bots that die before us**, which
are almost all our own kills (plus rare zone deaths). Surviving alone scores ~0. The squad sends its weakest
bot first, one at a time, more as we kill them, all of them after ~5 min. So the practice recipe is: kill the
lone hunter from a spot only it can see, regenerate to full, repeat. Starter 1.15 ~ one kill a match.
The final is a real free-for-all against other teams: there, survival and placement matter.

## Rules that matter most for strategy (protocol.md)
- Zone: `obs.zone` gives current and next circle + shrink window; outside = `dps` HP/s, no regen.
- HP regen 45/s after 5 s without dealing or taking damage (not outside the zone).
- Rear hits (outside 180° front arc of torso aim) do x1.5: face attackers.
- Vision: 45 m all around + 200 m in a 120° wedge of torso aim; buildings block, trees partly. Sounds give bearing (+-7°) and near/mid/far.
- Weapons: gun (start), mortar (lob, splash, concussion), laser (charge, hitscan, telegraphed), lightning (45 m cone, chains).
  Triangle: laser > mortar > lightning > laser. Trees don't stop shots.
- Cubes: +4% HP/dmg each (cap 10), but +5% size each (easier to hit). Thresholds 1,3,6,10,... give upgrade offers (`pick`, default 0 after 5 s).
- Supply drops at 70/140/210 s inside the next circle: stand alone 4 s for 3 cubes + full HP/energy.
- `alive` in obs = our place if we died now.

## Local tools (tools/, stdlib only, not in the Docker image)
| Command | What |
| --- | --- |
| `python3 tools/replay.py -- python3 -u bot.py` | Feed the kit's 300 recorded observations to the bot, lockstep; log actions, traces, answer times |
| `python3 tools/replay.py --repeat 3 --map-dir /arena -- docker run --rm -i --network none --cpus 1 --memory 512m --read-only --tmpfs /tmp:rw,size=64m --user 65534:65534 -e MECH_TRACE=1 -v "$PWD/kit/arena:/arena:ro" mech-royale` | Same, inside the match sandbox: the real timing test |
| `python3 kit/check/check.py -- python3 tools/record.py -- python3 -u bot.py` | Conformance check, recorded |
| `python3 tools/analyze.py replays/<file>.jsonl.gz [--csv out.csv]` | Report: timing, HP, zone, damage by weapon/attacker, rear hits, loot, modes, last seconds, timeline |
| `python3 tools/analyze.py --diff A.jsonl.gz B.jsonl.gz` | Where two bot versions decided differently on the same stream |
| `python3 tools/sim.py --matches 12 --seed 1 [--record] -- python3 -u bot.py` | **Local simulator**: real map + zone, gun-only fights vs a 15-bot hunting squad. Prints a score like the real one |
| `python3 tools/fuzz.py` | Throws generated observations (every weapon, loot, offers, drops, effects) at `Bot.act`: exceptions + worst time |

- `record.py` wraps any bot command transparently.
- `sim.py` is crude (no climbing/jets, gun only, no loot/NPCs/upgrades, house bots shoot us whenever they see us).
  Calibration: the starter bot scores ~0.9-1.1 in the sim vs 1.15 real. Use it for relative comparisons on
  12+ matches (s.e. is ~0.5 per 12) and always on two seed sets. `--record` writes replays with real HP/damage.
- In the bot, call `botlog.trace(tick, mode=..., **fields)` once per decision. Off unless `MECH_TRACE=1`
  (the tools set it), so it costs nothing in matches. `analyze.py` reports time per mode and mode switching.
- Replay files go in `replays/` (gitignored). Format documented in `tools/replaylog.py`.
- **Caveat:** replayed observations don't react to our actions. In a replay report, HP, damage, zone and
  death are the original recording's; only answer times, actions and modes are ours. Replays test timing,
  crashes and decisions, not play strength. Play strength = practice submissions (or a future simulator).

## Workflow
- `main` is what gets scored. Experiments on branches; merge after `check.py` passes.
- Before every submission: `check.py` locally, then the docker replay above, and look at p99 answer time (keep it well under 35 ms).
- Log every submission (commit, score, change) in README's Submissions log. 6 submissions per hour max (team-wide; was 4).
- Never force-push or delete a submitted commit; the repo must stay public until results are out.
- Freeze by **Sun 9:00 AM ET**; cutoff **Sun 11:00 AM ET**.

## Bot on `main` (since `515bce5`, real **5.73**)
`main` runs **giddygiddyboy's MIT Go bot** in `giddy/` (license and our change table in `giddy/README.md`), built by the
top-level `Dockerfile`. Why: `docs/leaderboard_study.md`. Everything we learned before the switch: **`docs/LEARNINGS.md`**.
Build/check locally (no Go installed system-wide; download the Go zip to a scratch folder):
`cd giddy && go build -o mechbot ./cmd/bot`, then `python kit/check/check.py -- giddy/mechbot`, `tools/replay.py`, `tools/sim.py`
all take the binary as the bot command. Improvements go on branches as small changes in `giddy/`, one per submission.

## Old Python bot architecture (in the repo, not in the image; best real 3.71 at `6bb23c4`)
- `nav.py`: 2 m grids (walls incl. steep terrain, sight blockers, nav = walls grown 1 cell), rays, LOS,
  `find_cover`, incremental `AStar` (time-budgeted per tick). Builds in ~0.3 s at hello.
- `bot.py` modes, in priority: zone (committed once started) > evade (2+ enemies can see us, or losing) >
  fight (only targets < 130 m or shooting us) > hide (seen / recently shot) > drop > loot > heal > move > hold.
  Always faces the main threat. Gun lead, laser charge/release, lightning cone, mortar ballistic. Upgrade
  preference list `UPGRADE_PREF`, weapon rank laser > lightning > mortar. Stuck -> jump-jet over or slide.
- Timing: p99 ~2 ms on the stream, worst ~4 ms under fuzz (budget 50 ms).

## Sim results (score, 12 matches each)
| Version | seed 1 | seed 2 |
| --- | --- | --- |
| starter (main) | 0.67 (6 m) | 1.08 |
| v1 (fights anything in range) | 0.83 (6 m) | - |
| v2 (hide when 2+ see us, fight only the hunter) | 2.00 | 2.50 |
| v2 + zone commit (current) | 2.00 | 2.00 |
| **real leaderboard** | starter 1.15 | v2 **2.92** |

Sim with supply drops modelled (tools/sim.py now has drops + rival house bots), 24 matches per seed set:

| Version | s1 | s2 | s3 | s4 | s5 | s6 | s7 | s8 | mean (192) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| main (v2, 2.92 real) | 2.29 | 1.92 | 2.29 | 2.46 | 2.54 | 2.88 | 2.50 | 1.88 | 2.35 |
| main + zone.py + drops.py (`claude/nifty-galileo-lw5l5t`) | 2.42 | 1.54 | 2.42 | 2.12 | 2.00 | 2.42 | 2.92 | 1.88 | 2.21 |

Difference is inside the noise (s.e. ~0.18). Drop captures 12 vs 8 matches. The extra zone deaths are the sim's
"stuck in a pocket without jets" artifact or late-game runs that still placed better than main.

## Status / next steps
- [x] Repo set up from the Python starter.
- [x] Logging harness, simulator, fuzz test.
- [x] Survival bot v2: **real practice score 2.92** (starter 1.15, leader at the time 1.75). Now on `main`.
- [x] Sim check: v2 ~2.0 in the sim vs 2.92 real; starter ~1.0 vs 1.15. The sim ranks correctly and is harsher
      than the real squad (likely: real non-hunters shoot on sight less). Fine for A/B; don't read its absolute level.
- [ ] Docker timing check of survival-v1 (`replay.py --repeat 3` in the sandbox; map build must stay well under the 20 s hello budget).
- [ ] Early deaths at spawn (several sim matches die < 20 s): get out of sight first, then fight.
- [ ] Better 1v1: peek from cover, fight at the corner, reload in cover, use regen between hunters.
- [ ] Loot: go for laser/lightning early; cubes from kills (killed mechs drop cubes + 2).
- [ ] Late game: max HP via cubes/plating so we outlast others when the zone closes to 0.
- [x] `eed4dc6` (`v2-zone-drops`, built on `v2-integrated`) scored **0.73** real. Don't build on `v2-integrated`.
- [x] `claude/nifty-galileo-lw5l5t`: main's bot + `zone.py` (CRITICAL forces a zone run) + `drops.py` (replaces `_good_drop`;
      holding a ring we capture outranks evade/fight), `params.json` knobs. Tests/check/fuzz pass. Sim neutral vs main. **Real 3.02** (new best).
- [x] Sat: Python bot peaked at **3.71** (`integ-3` = `6bb23c4`); 4 big swings after it all scored lower (3.02-3.65).
      Lessons in `docs/LEARNINGS.md`: disengaging / firing less / leaving cover lost; the calibrated sim's gains didn't transfer.
- [x] Sat: switched `main` to giddygiddyboy's MIT Go bot (`giddy/`): `515bce5` scored **5.73** (new best). Default sim agrees
      (2.83 / 2.88 vs integ-3 1.83 / 1.25). Top of the board is 6.2-6.44, mostly tuned copies of the same bot.
- [ ] Improve on the giddy base: FFA behavior for the final, then small execution fixes (see `docs/LEARNINGS.md` section 6).
