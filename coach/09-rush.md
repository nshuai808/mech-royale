# Codex brief: survive and score in the 5-minute rush (branch `t9-rush`)

Your worktree has been moved to a new branch `t9-rush` at integ-3 (`6bb23c4`, evade_unstick on, **3.71 real**, our best).
Your old `second_shooter`/`zone_cover` edits are safe in your bundles. Deliver this task as a bundle `replays\t9-rush.bundle`.

## The finding (real practice, measured with probe submissions)
Our real kills by time: **2.33 by 150 s, 3.69 by 300 s, 3.71 total. Zero kills after 300 s.** At ~300 s the whole remaining squad
(~11) comes at once and we die in that rush without scoring. The leaderboard top is **over 6**. The sim models this rush
(`tools/sim.py` `_hunters`: all house bots hunt after 300 s). Real-practice lessons so far: changes that make the bot disengage or
fire less **lost** (heal_gate 3.17/3.29, laser_flee 2.92); keep firepower up.

## Build (flag `params.json` `rush`, `enabled`; off = exactly integ-3)
1. **Prepare** from `prep_s` (250 s): regen to full HP if no fight is on; move to a defensive spot inside the next circle. A good spot
   has walls/buildings behind and to the sides (low openness: `late.py` already has a 16-ray openness score you can reuse) and a
   short open lane in front (15-60 m) so attackers enter our 120° view one or two at a time, at gun range, and hit our front.
   Prefer spots near the circle's centre so later zone moves are short. Face the most likely approach (the squad's last-known side).
2. **Hold** from `hold_s` (290 s) while enemies come: stay at the spot and fight from it. Don't let evade/hide take us out into the
   open unless HP < `flee_hp` (0.25) or the spot becomes outside the zone. Keep shooting (don't reduce firepower).
3. Zone always wins over the hold when the spot is about to leave the safe circle (reuse zone.py urgency).
Touch `Bot.act` (one new branch high in the mode chain, after zone) and new helpers; `late.py` only to reuse its scorer.

## Measure
Practice sim, seeds 1, 2, 3 (16 matches each, `--record`), off vs on, both arms run by you on this base. Report score, kills/match,
**kills after 300 s**, **share of matches alive at 300 s and at 360 s**, deaths<30s. Also `--ffa` seeds 1, 2 off vs on (must not be
clearly worse; the trigger is time-based so it also fires in FFA). If the first version doesn't add kills after 300 s, try one
variant: `prep_s` 220 and a stricter spot (openness weight x2). Tests, check, fuzz, then the bundle with the flag **on** if it adds
kills after 300 s without losing practice score, else off.

Report under 25 lines.
