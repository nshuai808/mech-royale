# Codex brief: CODEX_PLAN.md Task 1, `second_shooter`

You are the builder; Claude is the instructor. Read `CODEX_PLAN.md` (sections 1-2 and Task 1) and `AGENTS.md` first.

## Overrides for this machine
- Use `.\.pyrt\python.exe` for everything, including as the bot command (plain `python` isn't on PATH in your sandbox).
- No network: **do not push** (Claude pushes). Work only in this folder, on branch `t1-second-shooter`. Never touch `main`.
- At most 2 simulator runs at a time; run every requested sim in full.

## Why (from Task 0 on this exact base, integ-2 `5915f57`)
39 fatal gunfights: **33 had 2+ attackers** (21 had 3+), only 11 started below 50% HP. 23 of the 39 started above 90% HP.
The bot loses full-HP fights because it stays in them after a second/third shooter joins.

## Build (flag `params.json` `second_shooter`, `enabled`; off = exactly integ-2)
Break off to the existing evade path (keep its 2.5 s commit and wide cover search) at **any HP** when either:
- `attackers` (2) different mechs hit us within `window_s` (2.0 s), or
- while fighting, a second enemy mech other than the target is visible within `los_r` (150 m) and has line of sight to us,
unless the target dies within `finish_s` (1.5 s) (`Bot._finishing`).
Touch only the evade condition in `act()` and one helper. `Bot._multi_hit` (flag `early_evade`, off) is the same idea with an
HP gate: replace it with the new helper rather than adding a third rule (keep `early_evade` working as an alias, or note it's removed).

## Measure (paired, same seeds)
- **Off arm = Task 0** (same code). Don't rerun it, except: rerun practice seed 1 with the flag off once and confirm it matches
  Task 0 exactly (1.19, kills 1.00). Task 0 numbers: practice s1 1.19 / 1.00 kills / 2 deaths<30s; s2 2.00 / 1.31 / 1;
  ffa s1 10.94 / 1.63 / 4; ffa s2 13.62 / 2.63 / 1.
- **On arm:** practice seeds 1, 2 and `--ffa` seeds 1, 2, 16 matches each, `--record`, then `tools\fights.py` per run
  (archive replays to `replays\t1_<arm>\` between runs).
- If kills/match in practice drop by more than ~0.3 or the score drops, try one variant once: second-shooter LOS rule off
  (hits rule only), or `attackers` 3. Report all variants.
- Then: all `test_*.py` ok, `kit\check\check.py` PASS, `tools\fuzz.py` 0 exceptions. Commit (no push).

## Report (under 30 lines)
Full commit hash; functions changed; flag values; table variant x run -> score, kills/match, deaths<30s, fatal fights with 2+
attackers; one-line verdict (keep / tune / drop) with the paired differences; anything odd.
