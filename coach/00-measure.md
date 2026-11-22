# Codex brief: CODEX_PLAN.md Task 0 (measurement only)

You are the builder; Claude is the instructor and sends the next task after reading your report.
Read `CODEX_PLAN.md` (sections 1-2 and Task 0) and `AGENTS.md` first. Do **Task 0 only**.

## Overrides to CODEX_PLAN.md for this machine
- Python: plain `python` is not on PATH in your sandbox. Use `.\.pyrt\python.exe` everywhere, including as the bot command:
  `& .\.pyrt\python.exe tools\sim.py --matches 16 --seed 1 --record -- .\.pyrt\python.exe -u bot.py`
- No network: **do not push** (Claude pushes). Work only in this folder, on its current branch. Never touch `main`.
- At most 2 simulator runs at a time. They take several minutes each; run them all, don't skip or shorten.

## Do
Bot as-is (no code changes). Four runs with `--record`, 16 matches each:
practice seeds 1 and 2, `--ffa` seeds 1 and 2. After each run, run `tools\fights.py` on its replays,
then move `replays\sim-*` into `replays\t0_<arm>\` so the next run doesn't overwrite them.

## Report (under 30 lines; this is all Claude reads)
1. Table per run: score, kills/match, deaths < 30 s, fights total, fights won.
2. Fatal fights pooled over practice and pooled over FFA: count by number of attackers (1 / 2 / 3+),
   and count by HP at start (< 50% / 50-90% / > 90%).
3. One line: which is the bigger killer on this bot, pile-ups (Task 1) or re-engaging hurt (Task 2), with the numbers.
4. Anything odd (late answers, crashes, zone deaths, stuck).
