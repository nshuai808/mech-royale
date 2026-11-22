# mech-royale

Our bot for the Builders Buildathon **Mech Royale** track: a 16-mech battle royale on a 3D map of the OSU Oval.
Score = mean of `16 - place` over 48 practice matches. **Placement beats kills.** Baseline (kit example bot): 1.15.

Submissions close **Sun 11:00 AM ET**. Max 6 submissions per hour per team (was 4 until Sat night).

[Shared experiment plan for reaching 6+](docs/road-to-six.md)

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
| Sat | `ea37402` | **3.56** | + power farming: NPCs to 150 m, cubes 120 m, crates 150 m, roam when idle in the first 3 min. New best. |
| Sat | `8ecaa3c` | 3.35 | + rooftop camping from 100 s (roof.py). Worse than 3.56: house bots climb, or the climb fails. |
| Sat | `ac6e281` | **3.6** | + all-out aggression switch (`params.json` `aggro`, on), roof camping off. New best, but only +0.04 over `ea37402`: inside the noise. Also the control for the 1.71 below: this commit without the v2 modules. |
| Sat | `f2aea8b` | 1.71 | `ac6e281` + upgrades, perception, loot, engage and aim modules wired into `bot.py` (branch `integrate-v2-modules`). Big regression vs `ac6e281`, so the modules (not aggression) caused it. Which one is unknown; flags in `params.json` allow bisecting. Don't build on it.|
| Sat | `a8c36d0` | 3.42 | `step1-dodge`: `ac6e281` + dodge of gun bullets and mortar shells, beam shooters added to known enemies. 0.18 below `ac6e281`: inside the noise, so no evidence it helps. Sim was neutral/slightly lower too. Not promoted; `main` stays on `ac6e281`. |
| Sat | `249ca9d` | not submitted | `step4-late`: late-game hold (`late.py`, `params.json` `late`, **off**). From next circle <= 140 m, hold the most concealed spot inside it instead of roam/hold/hunt; skip cubes past 10. Sim `--ffa --ffa-shy 0.6` seed 1: 10.69 on and off, identical (matches end before the late circles). Practice can't show it either; meant only for the combined final candidate. |
| Sat | `57342d8` | not submitted | `claude/stuck-pocket-7ac14b`: escalating unstick (`params.json` `unstick.v2`, **off**) after the bot got stuck in the Ohio Stadium bowl (nav treats it as sealed; old `_unstick` jets once, then only sidesteps). Write-up: `docs/stuck_pocket.md`. Sim A/B 32 matches: 9.59 off vs 9.78 on (noise; the sim has no jets). Submit alone, not with `late.enabled`. Sim seeds 1014, 7000 (stadium spawns) and 1021 (spawn in a wall) die to the zone whatever the bot does. |
| Sat | `c6c10d4` | 3.44 | `integ-2`: aggression off, `roam_fix`, `unstick.v2`, `unseen_hit`, `evade_fix`; other new flags off. |
| Sat 4:48 PM | `8a2aeac` | 3.60 | `t3-weapon-ctx`: integ-2 + `weapon_ctx` only. Noise. |
| Sat 4:52 PM | `99d6a09` | 3.50 | `t3-upgrade-ctx`: integ-2 + `upgrade_ctx` only. Noise. |
| Sat 4:54 PM | `65a728e` | 3.42 | `t3-special-guard`: integ-2 + `special_guard` only. Noise. |
| Sat 4:57 PM | `e139c2d` | 3.48 | `t3-mortar-lead`: integ-2 + `mortar_lead` only. Noise. |
| Sat 5:00 PM | `585b8e8` | 3.17 | `t2-heal-gate` v1: below 70% HP no new fights, regen. Froze looting. Worse. |
| Sat 5:23 PM | `a299738` | 3.29 | heal_gate v2 (keeps looting). Worse again: disengaging loses. Dropped. |
| Sat 6:06 PM | `6bb23c4` | **3.71** | `integ-3` = integ-2 + `evade_unstick` (slide around walls when an escape is blocked; FFA sim +0.91). **New best, current base.** |
| Sat 6:10 PM | `5a31d43` | 3.58 | integ-3 + `weapon_ctx`. Noise; dropped. |
| Sat 6:26 PM | `e37bac5` | 2.92 | integ-3 + `laser_flee` (release laser while fleeing). Much worse: retreat-time laser damage matters. |
| Sat 6:34 PM | `a7b621c` | 3.69 | PROBE: integ-3 that stops shooting mechs after 300 s (score = kills before 300 s). Never ship. |
| Sat 6:37 PM | `deaaa12` | 2.33 | PROBE: same, after 150 s. => real kills 2.33 by 150 s, 3.69 by 300 s, ~0 after. |
| Sat 6:47 PM | `1c37af2` | 3.33 | integ-3 + `gun_aim` (hold fire when buildings block the shot). Worse. |
| Sat 7:12 PM | `5d196e3` | 3.65 | Swing 1 `t11-power`: lt_energy, rush_build, cube_cap, farm_plus, lt_chain. Neutral. |
| Sat 8:38 PM | `b1ecbf2` | 3.46 | Swing 2 `swing2`: swing 1 + rush fortress (250 s). Calibrated sim +0.42 kills didn't transfer. |
| Sat | `66e3589` | 3.02 | Swing 3 `t13-hunter`: aggression only while one hunter is on us. Calibrated sim +0.96 kills, real -0.63. Leaving cover loses. |
| Sat 9:21 PM | `7744704` | 3.17 | Swing 4 `swing4`: integ-3 + finisher (no chase) + damage build. Worse. |
| Sat | `515bce5` | **5.73** | `giddy-base`: switch to giddygiddyboy's MIT Go bot (`giddy/`, unchanged but the name; see `giddy/README.md`, `docs/leaderboard_study.md`). check.py PASS, replay p99 1.4 ms. **New best; now `main` and the base for improvements.** |
| Sun | `da3afa0` | 3.46 | branch `claude/nifty-galileo-lw5l5t`: `ultra` (never flee, loot-first, jets, hops, bold drops). See `docs/trials_nifty_galileo.md`. |
| Sun | `df31a39` | 3.63 | branch: "medium" (ultra, flee < 40% vs 2+, heal before hunting, no hops). Noise. |
| Sun | `8ffc0c2` | 0.08 | PROBE pacifist (never shoots mechs, hides, farms). Points = our kills only; hiding never survives. Never ship. |
| Sun | `23c2aa1` | 3.42 | branch: medium + armor-first + third-party cover (sim +0.28 did not transfer). |
| Sun | `22fd5bd` | 3.50 | branch: "A" keep gun, loot bodies, drones 250 m, HP upgrades. Noise. |
| Sun | `e9f6823` | not scored yet | branch: aggressive A. |
| Sat 10:06 PM | `b08b466` | 5.73 | `v-cubes21`: practice mode collects cubes to 21, not 10. **Identical to base**: no behavior change in any of the 48 matches, so the bot never reached 10 cubes. Cube income, not the cap, is the gap. |
| Sat 10:09 PM | `23ad2f9` | 5.73 | `v-cubes45`: cubes to 45. Identical to base, same reason. |
| Sat 10:22 PM | `5de6212` | 5.25 | Swing `s-all`: Econ + Explore + FightLoot 70 + NanoUp (practice mode). -0.48 vs base: the stack hurts. Leave-one-outs `s-no-econ`, `s-no-explore`, `s-no-fightloot` pending to find which. |
| Sun | `b35b174` | 5.40 | giddy + practice UseDrops, NanoUp, Explore, CubeGoal 15 (stacked, Advit). -0.33: sim blames Explore (1.48 vs 2.31) and drops (2.02). |
| Sun | `6a7c88e` | 5.52 | giddy + practice `NoMortar = false` (take a mortar when slot 2 is empty). -0.21, noise but no gain: mortars stay off. |
| Sat 10:46 PM | `acffb08` | 5.10 | `s-no-explore`: Econ + FightLoot 70 + NanoUp (+ robust). Below s-all: Explore is not the culprit. NanoUp is in every losing run (s-all 5.25, this 5.10, Advit b35b174 5.40); next test NanoUp alone (`e9bd9ef`). |
| Sun | `27392a9` | 5.73 | PROBE: giddy, no shots after 300 s. **Identical to base: giddy is dead before 300 s in all 48 practice matches.** Every kill happens before the rush; +1 must come from surviving it or from more kills before 300 s. Never ship. |
| Sun | `5001814` | 4.58 | PROBE: giddy, no shots after 150 s. => giddy kills **4.58 by 150 s, 1.15 in 150-300 s, 0 after** (always dead by 300 s). The +1 is surviving / winning the multi-hunter phase. Never ship. |
| Sun | `c3e2d53` | 5.73 | robust + practice `CrowdHide = false`. **Identical: 'swamped' (3+ foes in view, or 2 below 65% HP) never happens in practice.** giddy dies in mid-game 1v1s against stronger hunters, not to crowds. Sim agrees: RetreatHP 0.25/0.5 and RecoverHP 0.95 are identical to base too. |
| Sat 11:28 PM | `7802713` | 5.10 | `s-econ-fight`: Econ + FightLoot 70, no NanoUp (+ robust). **Same 5.10 as Econ + FightLoot + NanoUp**: NanoUp is not the culprit (likely a near no-op: the bot gets only ~2 upgrade offers, plating/armor first). The loss comes from Econ and/or FightLoot. Loot line closed. |
| Sun | `d983a4c` | 5.75 | robust + practice upgrade order laser_damage, laser_charge before plating, armor. Behavior changed (not identical) but +0.02 is inside the ±0.25 noise: neutral, not harmful. |
| Sun | `d5dffcc` | 5.67 | robust + practice `EngageDist = 90`. Neutral; the sim's +0.33 didn't transfer. |
| Sun | `96a804f` | 5.67 | robust + practice `AllFoes = true`. Neutral: the sim's +0.40 (two seed pairs) didn't transfer, like EngageDist 90. The house-bot sim can't pick giddy combat flags. |
| Sun | `79eb097` | 5.42 | robust + `BodyLoot` (practice: walk to each kill's body when clear, for its cubes + 2). -0.31: worse. Fifth cube-gathering change to lose; cubes are not the practice lever (the exposure costs more). |
| Sun | `c5fdfc3` | 5.69 | robust + `LaserHold` (practice: keep a laser charge through a <= 1 s loss of the target instead of firing into the idle aim; confirmed bug, `tools/laser_hold_check.py`). Neutral. |
| Sun | `81f68b4` | 5.67 | robust + all neutral-or-better practice changes combined (laser-first upgrades, LaserHold, AllFoes, EngageDist 90, CrowdHide off). Neutral: the small effects don't add up. |
| Sun 12:47 AM | `83d46a4` | 5.54 | `farm-early-laser`: until 70 s farm NPC drones from 250 m (valued higher, remembered 60 s) + laser_damage first in upgrades (on robust + zr-base switches off). -0.19: noise, no gain. Early cubes/laser upgrade is not the missing kill. |
| Sun 1 AM | `d983a4c` | **5.46 (builders-4)** | Rescore on the new scorer (96 fresh random seeds, identical code keeps its first score). Was 5.75 on builders-3. ~Unchanged giddy, so **~5.46 is the new baseline**; noise now ~±0.18. |
| Sun | `eed4dc6` | (accidental resubmit) | old v2-zone-drops Python bot; not an entry. |
| Sun | `39847d4` | 5.30 (builders-4) | robust + laser-first upgrades + LaserHold + HealGate 0.6 from 150 s. -0.16 vs ~5.46 baseline (noise). |
| Sun | `e48ac24` | **5.57 (builders-4)** | robust + laser-first upgrades + HealGate 0.6 from 150 s (no LaserHold). +0.11 vs ~5.46 baseline: best on builders-4 so far, inside the ±0.18 noise. |
| Sun 2:08 AM | `8f7f9b8` | **5.58 (builders-4)** | Mid-game duel health trades. Selected final entry BB-250F80CF. +0.12 vs the rescored 5.46 baseline. |
| Sun | `77b3f7d` | 5.30 (builders-4) | e48ac24 with HealGate below 70 % (was 60 %). -0.27 vs e48ac24: a higher bar turns down too many fights. |
| Sun | `77e6758` | 5.51 (builders-4) | e48ac24 with HealGate from 120 s (was 150 s). Tie with e48ac24 (5.57); heal-gate tuning done. |
| Sun | `768b8a3` | **5.75 (builders-4)** | road-to-six #3: duel bot `8f7f9b8` + laser-first upgrades + HealGate 0.6 from 150 s + robust FFA fix. **+0.17 vs 8f7f9b8 (5.58); new best. 33rd, 0.01 off the top 32.** |
| Sun | `7294ba0` | 5.48 (builders-4) | road-to-six #1 on 768b8a3: Corner (hold a low-exposure spot 15 s after a kill). -0.27: dropped. |
