# Parallel work plan

One brief per session. Each session works in its own worktree on its own branch off `main` (currently `8eb5828`, bot code = `ac6e281`, scored 3.6).
Paste the brief for one session into one chat. Read `STRATEGY.md` for the background and `CLAUDE.md` for the repo and tools.

## Rules that apply to every session
1. **Own branch, own worktree.** Never work in the main checkout while another session is. Create it with:
   `git worktree add ../mech-royale-<name> -b <branch> main` (from the repo root), then work only inside that folder.
2. **One behavior change per branch**, behind a `params.json` flag (`enabled`), so `enabled: false` equals `main`.
3. **Stay in your lane.** Only touch the functions and files listed in the brief. If you need a change elsewhere in `bot.py`, stop and say so.
4. **Before you hand back:** `python kit/check/check.py -- python -u bot.py` prints PASS, `python tools/fuzz.py` shows 0 exceptions, p99 answer time well under 35 ms.
5. **Simulator load:** at most 2 simulator runs at a time per session (the machine slows down and answers get late). Use `tools/sim.py --matches 16 --seed N` on at least two seed sets, and an A/B against the same code with the flag off. The sim standard error is about 0.3 to 0.6 per 12 matches, so judge by score, kills and early-death share together.
6. **Never push to `main`, never force-push, never delete a submitted commit.** Push your branch and report its commit hash. Only the owner merges and submits.
7. **Reporting:** branch, commit hash, files and functions changed, flag name, sim A/B numbers, what was not verified. State plainly what the sim cannot show (it has only gun fights: no loot, NPCs, special weapons or upgrades).
8. **Submission bar:** a real practice score must clear about +0.4 over 3.6 to count as an improvement (leaderboard noise is 0.2 to 0.3). Submit one branch at a time; 4 per hour max.

## Session A: Early-game survival (in progress)
- **Branch:** `step2-early-evade` (uncommitted work exists in the main checkout; move it into this branch's worktree).
- **Problem:** in the sim, 38% of matches end before 30 s (0.33 points each). The deaths are 12 to 16 s gun duels in the open where a second and third shooter join and hit our back. With aggression on, the normal evade rules are off, and evade only triggers at HP under 25% with 2 enemies visible.
- **Change so far:** `Bot._multi_hit()` plus a hook in `act()`: break off to cover when >= 2 different mechs hit us within 2 s and HP < 80%. Flag: `params.json` `early_evade`.
- **Touches:** `Bot._multi_hit`, the evade condition in `act()` (one line), `params.json`. Nothing else.
- **Next:** read the A/B (sims `eA_*` off vs `eB_*` on, seeds 1 to 3, 16 matches each). If it raises mean score or cuts the share of deaths under 30 s without cutting kills, tune `hp_frac` (0.6 to 0.9) and `attackers` (2 or 3). If it hurts, drop it.
- **Done when:** a flagged commit with an A/B on two seed sets and a one-line verdict.

## Session B: Final-round (free-for-all) check of the aggression switch
- **Branch:** none required. This is measurement. Put results in `docs/ffa_check.md` on branch `ffa-check`.
- **Problem:** `ac6e281` (aggression on) is tuned for the practice squad that hunts us. The final is a 16-way free-for-all. We have no measurement of how it plays when everyone fights everyone.
- **Do:** run `python tools/sim.py --ffa --matches 24 --seed N` for N in 1 and 2 on three variants: `ea37402` (no aggression), `ac6e281` (current `main`), and `ac6e281` with `aggro.enabled: false`. Use worktrees or temporary copies, not `git checkout` in one folder.
- **Report:** mean score, kills, survival time and the share dying before 30 s, per variant, plus a recommendation: keep or drop the aggression switch for the final. Say how far the sim `--ffa` mode can be trusted (read `_house_ffa` in `tools/sim.py` first).
- **Touches:** no bot code.

## Session C: Timing and packaging safety
- **Branch:** `timing-check` (no bot changes expected).
- **Problem:** the Docker 1-CPU timing check on `main` has never been run. A timeout is the worst failure (coast one second without firing, then idle).
- **Do (needs Docker, so run it where Docker exists):** build the image, run `python kit/check/check.py --map-dir /arena -- docker run ...` (flags in `README.md`) and `python tools/replay.py --repeat 3 --map-dir /arena -- docker run ...` as in `CLAUDE.md`. Confirm the map builds well under 20 s at hello, p99 answer time stays under 35 ms, and the repo stays under 20 MB.
- **Also check:** `git ls-files` for stale unused code that the Docker image copies (roof planner, tests) and confirm nothing imports a missing module in the image.
- **Report:** the numbers and any failure. Fix only packaging problems; do not change behavior.

### Session C results (2026-11-21): done
- **Branch `timing-check`, commit `79c0978`.** Full report: `docs/timing_check.md` on that branch.
- **No Docker on this machine** (none on Windows or in WSL; installing it needs sudo). Stand-in used: the image's exact files
  (`git archive` + `.dockerignore`) in WSL, one core (`taskset`), bot folder and arena read-only, memory cap, clean env.
  Also run on Windows Python 3.13 (the image is 3.13.18). **Still to do once:** the real Docker commands from `README.md`.
- **Numbers:** hello 0.6 s on one core (1.2 s on half a core; budget 20 s). Kit stream p99 8 ms, max 11 ms; on half a core
  p99 15 to 18 ms, max 23 ms. Peak RSS 25 MB. No writes. Repo 2.2 MB (330 KB packed). check PASS, fuzz 0 exceptions, tests pass.
- **Packaging fix:** `test_*.py` added to `.dockerignore` (copied, never imported). Every import in the image is satisfied
  (`roof.py` is still needed: imported at top level).
- **Risk found:** in long sim matches (200 s and up), roam-mode A* to unreachable random points ran at its ~20 ms cap for up to
  11 s at a time (p90 21 ms, max 30 ms on one core; 6 ticks over 35 ms on half a core; one 48.6 ms tick on Windows).

### Follow-up: roam A* fix, branch `roam-astar`, commit `edc54eb` (not submitted)
- **Flag:** `params.json` `roam_fix.enabled` (on in the branch; off = `main`).
- **Touches:** roam point choice in `act()` (try up to 6 points, keep one with free nav ground within 4 m), `_go_point`
  (after a failed A*, don't restart it for the same goal for 3 s, and drop a search for another goal), new `Bot._goal_key`.
- **Timing** (two long sim `--ffa` matches, flag off -> on): ticks over 15 ms 327 -> 4 and 702 -> 84, max 48.6 -> 32 ms.
  Of the 84 slow ticks left, 74 are in `hunt` mode, and none came near 35 ms.
- **Sim A/B** (practice sim, 16 matches, off vs on): seed 1 1.75 vs 1.69, seed 2 1.69 vs 1.75; kills 53 vs 53; deaths under
  30 s 9/32 vs 9/32. Neutral, as expected: it is a timing safeguard, not a play change.
- check PASS, fuzz 0 exceptions (worst 12 ms), zone and drop tests pass.
- **Not verified:** a real practice score (practice probably can't show it), real Docker, the scorer's CPU speed.

## Session D: Loot and weapon choice
- **Branch:** `step3-loot`.
- **Problem:** loot gave the biggest real gains (2.90 to 3.40 to 3.56), so this layer pays. Remaining gaps: weapon choice ignores the counter triangle (laser beats mortar, mortar beats lightning, lightning beats laser), mortar is rank 1 of 4 and rarely taken, the upgrade list is fixed, and there is no rule for protecting a held special.
- **Touches:** `WEAPON_RANK`, `_loot_goal`, `_gun_swap`, `_take`, `_pick_upgrade`, `UPGRADE_PREF`, `params.json`. Do not touch the mode order in `act()`.
- **First experiment:** pick the upgrade by weapon held and by enemy weapons seen (visible `weapons` field on enemy mechs). Keep each experiment on its own flag and its own commit.
- **Caution:** the sim has no loot, so it cannot judge this. Do unit tests on synthetic observations, then rely on a practice submission. The v2 `loot.py` and `upgrades.py` (branch `integrate-v2-modules`) scored badly when wired in together; reuse ideas, not the wiring.

## Session E: Late-game and placement
- **Branch:** `step4-late`.
- **Problem:** nothing plays the last two circles specifically. The final pays for placement, and practice mostly doesn't show late play (most sim matches end before 2 minutes).
- **Touches:** the `heal`/`hold`/`move` branches at the end of `act()`, `zone.py` knobs, `params.json`. Do not touch fight or evade logic.
- **Ideas to test:** from circle 4 on, choose the best cover spot inside the safe zone and hold at full HP instead of roaming, stop farming cubes beyond the 10-cube stat cap (extra size makes us easier to hit), prefer the circle edge facing away from the center.
- **Caution:** measure with `tools/sim.py --ffa` over long matches; practice cannot show this. Report the median survival time.

## Not parallel: do these after the above
- **Combining winners.** After each branch has a real score, merge the winners into one candidate and score it alone. Combined results do not equal the sum.
- **Re-testing v2 modules** (`percept.py`, `upgrades.py`, `engage.py`), one per submission, only after A to E, since they overlap Sessions A and D.
- **Freeze:** Sunday 9:00 AM ET. Cutoff Sunday 11:00 AM ET.

## Overlap map (which sessions can collide)
| | A early evade | B FFA check | C timing | D loot | E late-game |
| --- | --- | --- | --- | --- | --- |
| A | - | none | none | none | low (both read `act()`) |
| B | none | - | none | none | none |
| C | none | none | - | none | none |
| D | none | none | none | - | none |
| E | low | none | none | none | - |

A and E both touch `act()`, in different branches of the mode chain; merge them one after the other.
