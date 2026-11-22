# Codex brief: CODEX_PLAN.md Task 2, `heal_gate`

You are the builder; Claude is the instructor. Read `CODEX_PLAN.md` (sections 1-2 and Task 2) and `AGENTS.md` first.
Another Codex is doing Task 1 (`second_shooter`, the evade condition) in a different folder at the same time: don't touch
the evade condition in `act()`.

## Overrides for this machine
- Use `.\.pyrt\python.exe` for everything, including as the bot command (plain `python` isn't on PATH in your sandbox).
- No network: **do not push** (Claude pushes). Work only in this folder, on branch `t2-heal-gate`. Never touch `main`.
- At most 2 simulator runs at a time; run every requested sim in full.

## Why (from Task 0 on this exact base, integ-2 `5915f57`)
39 fatal gunfights: 11 started below 50% HP (10 of the 31 in practice). Fights start every ~20 s; regen from 50% takes ~20 s
(45 HP/s after 5 s without dealing or taking damage, not outside the zone).

## Build (flag `params.json` `heal_gate`, `enabled`, `hp_frac` 0.7; off = exactly integ-2)
Below `hp_frac`: don't pick a new target that isn't shooting us (`_choose_target`), break line of sight to known enemies and
regenerate (the `heal` branch in `act()`, own mode name or trace field so it shows in analyze.py), return fire only when hit.
Zone priority stays above it. Supply-drop capture stays as it is.

## Measure (paired, same seeds)
- **Off arm = Task 0** (same code), don't rerun. Task 0: practice s1 1.19 score / 1.00 kills/match / 2 deaths<30s;
  s2 2.00 / 1.31 / 1; ffa s1 10.94 / 1.63 / 4; ffa s2 13.62 / 2.63 / 1. Fatal fights starting < 50% HP: 10 practice, 1 ffa.
- **On arm:** practice seeds 1, 2 and `--ffa` seeds 1, 2, 16 matches each, `--record`, `tools\fights.py` per run
  (archive replays to `replays\t2_<arm>\` between runs).
- If practice kills drop by more than ~0.3 or score drops, try `hp_frac` 0.6 once; if it's neutral, try 0.85 once. Report all.
- Then: all `test_*.py` ok, `kit\check\check.py` PASS, `tools\fuzz.py` 0 exceptions. Commit (no push).

## Report (under 30 lines)
Full commit hash; functions changed; flag values; table variant x run -> score, kills/match, deaths<30s, fatal fights
starting < 50% HP; one-line verdict (keep / tune / drop) with paired differences; anything odd.
