# Codex brief: escapes that get stuck (new task, branch `t5-evade-stuck`)

You are the builder; Claude is the instructor. Read `CODEX_PLAN.md` sections 1-2 and `AGENTS.md`. Another Codex is changing the
**zone branch** of `Bot.act` (`zone_cover_detour`) elsewhere: don't touch the zone branch.

## Overrides for this machine
- Use `.\.pyrt\python.exe` for everything, including as the bot command. No network: don't push.
- Your sandbox can't write git's shared index: when done, commit in a local mirror and hand over a bundle
  `replays\t5-evade-stuck.bundle` (branch `t5-evade-stuck`), as you did before.
- At most 2 simulator runs at a time; run every requested sim in full.

## Why
On integ-2, in fatal fights, 5 of 9 bots that were evading in their last 6 s **moved < 2 m in a 1.5 s window while commanding
movement** (stuck/blocked on the way to cover), and ~26% of fatal gun damage was rear hits (x1.5).

## Step 1: diagnose (short)
Record practice s1, s2 (16 matches, `--record`, flag-free integ-2). For each evade-stuck window: was A* used or the straight line,
what blocked (wall/building corner/another mech/terrain step), distance to the cover point, did `_unstick`/`_unstick_v2` fire?

## Step 2: build one fix for the main cause (flag `params.json` `evade_unstick`, `enabled`; off = exactly integ-2)
Typical fixes, pick what the diagnosis supports: re-pick the cover point when progress toward it stalls for > ~0.8 s (excluding the
current one), route to cover with the nav grid instead of a straight line, or slide along the blocking wall toward the cover side.
Keep facing the threat while moving (rear hits). Touch `_evade` and at most one helper; `nav.find_cover` only if needed.

## Measure
practice s1, s2 and `--ffa` s1, s2, 16 matches, `--record`; off arm = Task 0 numbers (practice s1 1.19 / 1.00 kills / 2 deaths<30s;
s2 2.00 / 1.31 / 1; ffa s1 10.94 / 1.63 / 4; ffa s2 13.62 / 2.63 / 1). Report evade-stuck windows in fatal fights off vs on.
Then tests, check, fuzz, bundle.

## Report (under 25 lines)
Diagnosis counts; what you built (functions); table off/on (score, kills/match, deaths<30s, stuck windows); verdict; commit hash.
