# Codex brief: capture more supply drops, especially drop 3 (branch `t12-drops`)

New task. Your worktree is now on branch `t12-drops` at `5d196e3` (= integ-3 + Claude's power changes: lt_energy, rush_build,
cube_cap, farm_plus, lt_chain). Read `coach/RUSH_PLAN.md` (in the main checkout: `C:\Users\natha\Downloads\mech-royale\coach\`,
read-only for you) for the plan. Deliver as a bundle `replays\t12-drops.bundle`. Your gun_aim work is done (it scored 3.33 real).

## Why
Real practice: 0 kills after 300 s, when the whole squad rushes us. The plan is to reach 300 s with max power. Each supply drop gives
**3 cubes + full HP + full energy**; drops are called at 70/140/210 s and land 25 s later inside the next circle. **Drop 3 lands
~235 s: full HP and energy right before the rush.** `drops.py` decides whether/how to go for a drop. The sim models drops and rival
house bots (`--drop-rivals`, default 0.5).

## Step 1: measure (practice sim, seeds 1-3, 16 matches, `--record`, this base as-is)
Per drop (1, 2, 3): share of matches where we were alive when it was called, went for it, captured it, and why not (too far,
zone, contested, killed on the way, a fight in progress). Also: our HP and cubes at 240 s and at 300 s (sim cubes come only from drops
and kills here).

## Step 2: build (flag `drop_push`, `enabled`; off = exactly this base)
Make the drop planner more willing for drops 2 and especially 3 (wider reach, accept a contested ring if we can win the 1v1 there,
go even mid-fight if the drop is in the direction of cover), without walking into zone deaths. Touch `drops.py` and its call in
`Bot.act` only.

## Measure
practice s1-s3 and `--ffa` s1-s2, 16 matches, off vs on (both arms run by you on this base). Report: drop captures per drop number,
score, kills/match, alive at 300 s, HP at 300 s, deaths<30s, zone deaths. Tests, check, fuzz. Bundle with the flag **on** if captures
of drops 2-3 rise without more deaths or zone deaths, else off. Report under 25 lines.
