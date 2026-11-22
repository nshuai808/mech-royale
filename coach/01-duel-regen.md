# Task 1: duel metrics + regen discipline (branch `step5-duel`)

You are the builder; Claude is the instructor and will send the next step after reading your report.
Read `AGENTS.md`, then `STRATEGY.md` sections 1-2, then the mode chain in `Bot.act()` in `bot.py`.

## Environment (important)
- Work only in this folder. Commit only to the current branch `step5-duel`. Never push, never touch `main`.
- Plain `python` is not on PATH here. Use `.\.pyrt\python.exe` for everything, including the bot command:
  `& .\.pyrt\python.exe tools\sim.py --matches 16 --seed 1 -- .\.pyrt\python.exe -u bot.py`
- At most 2 simulator runs at a time (other sims share this machine). Sims take several minutes; run them, don't skip them.

## Why
Practice score = house bots that die before us, so about +1 per extra duel won. The squad sends one hunter at a time,
each stronger than the last. A duel started at 60% HP loses to the next hunter. The bot currently goes back to
loot/roam/move as soon as no enemy is visible, often before regenerating (regen is 45 HP/s after 5 s without dealing
or taking damage; not outside the zone).

## Part A: fight metrics in the sim (no bot change)
Add an opt-in `--fights` flag to `tools/sim.py` that prints, per match, for each fight our mech was in
(a fight = we deal or take mech damage; it ends after 6 s with neither): our HP at the start, who hit first,
outcome (won = the other mech died, lost = we died, broke off), duration. At the end print totals:
fights, won %, mean start HP in won vs lost fights, share of fights where the enemy hit first.
Defaults unchanged when the flag is off.

## Part B: regen discipline (bot change, flag `params.json` `regen` -> `enabled`)
When no enemy mech is visible, we are not in a zone run (zone mode outranks this), and HP < `full_frac` (0.95):
- if any known enemy (last-seen within 12 s, `self.known`) could see us, move to cover that blocks those positions
  (reuse `find_cover`/the hide logic), otherwise hold still facing the last threat bearing;
- do not loot, roam, hunt or move until HP >= `full_frac`, except: supply-drop capture, a pickup or cube
  within `near_m` (15 m) that we can reach without being seen, and the zone.
- Give it its own mode name (`regen`) and a `botlog.trace` entry.
`regen.enabled = false` must give exactly the current behavior.

## Measure (paired, same seeds)
1. Practice sim, seeds 1, 2, 3, 4, 16 matches each, `--fights`, flag off vs on.
2. FFA sim, `--ffa --matches 24`, seeds 1 and 2, flag off vs on (a regression check for the final).
Then: `test_*.py` all pass, `kit/check/check.py` PASS, `tools/fuzz.py` 0 exceptions.
If on is clearly worse, try `full_frac` 0.8 once before giving up.

## Report (keep it under 30 lines; this is all Claude reads)
Commit hash(es); files/functions changed; a table: variant x seed set -> score, kills/match, deaths < 30 s,
fights won %, mean start HP of lost fights; FFA scores off/on; check/fuzz/tests result; one-line verdict
(keep / tune / drop) and anything that surprised you.
