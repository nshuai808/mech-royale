# Codex brief: swing 4a "finisher" (branch `t14-finisher`)

Your worktree is now on branch `t14-finisher` at `integ-3` (`6bb23c4`, **3.71 real, our best**). The calibrated `tools/sim.py` and
`tools/simpar.py` are copied in (don't commit those two). Deliver as a bundle `replays\t14-finisher.bundle`.

## Ground truths (real practice)
Swing 2 (your fortress + swing 1) scored 3.46, swing 1 3.65; the calibrated sim's +0.42 didn't transfer. Only big real effects
are reliable, and they all say: **giving up damage or disengaging loses** (laser_flee 2.92, heal_gate 3.17/3.29, gun_aim 3.33).
Kills are capped by time (none after 300 s), hunters = 1 + our kills, weakest first. So: **end each fight faster and never let a
damaged hunter get away** (it regenerates and comes back at full HP).

## Build (flag `params.json` `finisher`, `enabled`; off = exactly integ-3)
1. **Focus fire:** in `_choose_target`, strongly prefer the visible enemy we can kill soonest (lowest HP / our time-to-kill
   `_ttk`), and don't switch away from a target below `lock_frac` (0.35) HP unless it's out of sight for > 1.5 s.
2. **Chase the kill:** if our last target dropped below `chase_frac` (0.4) HP and broke line of sight, go to its last-seen position
   (`self.known`) for up to `chase_s` (6 s) instead of hiding/looting, unless HP < 40% or a second enemy is in sight.
3. **Don't let evade abort a nearly-won fight:** if the target dies within ~2 s by `_ttk`, stay in `fight` even when evade would
   trigger (there's a related `_finishing` helper; reuse it).
Touch `_choose_target`, the evade/fight part of `Bot.act`, and one helper. Keep firepower: never set `fire` to False.

## Measure (calibrated sim; judge kills and survival only, never score)
`python tools/simpar.py --jobs 7 --matches 16 --seed N --aim-mult 4 -- .\.pyrt\python.exe -u bot.py`, practice seeds 1, 2, 3, flag
off vs on (both run by you). Report kills/match, kills by 150 s / 300 s, alive at 150/300 s. Then `--ffa` seeds 1, 2 (default sim,
no `--aim-mult`) off vs on: must not be clearly worse. If on doesn't add >= 0.2 kills/match, try `lock_frac` 0.5 and `chase_s` 4 once.
Tests (stdin closed), check, fuzz. Bundle with the flag on if it wins, else off. Report under 20 lines.
