Good analysis. Build your proposal, `zone_cover_detour`, on this branch (`t1-second-shooter`; keep `second_shooter` off).

## Build (flag `params.json` `zone_cover_detour`, `enabled`; off = exactly integ-2)
When the zone logic wants a run for a non-critical reason (e.g. "late", not CRITICAL / already outside the circle), and we are
under fire (hit within `hit_s` 2.0 s, or 2+ enemy mechs with LOS to us), and we are **inside the current circle**, and there is
time to spare (time until the circle we must reach closes, minus our straight-line travel time at walking speed, > `margin_s` 10 s):
- take the evade/cover path instead of the zone run, preferring cover points that are **not farther from the next circle's
  centre** than where we stand (+ `slack_m` 15 m), so the detour still makes progress toward safety;
- re-check each decision: as soon as the margin drops below `margin_s` or we're outside the circle, the zone run wins again.
Read `zone.py` first and reuse its urgency/time estimates rather than inventing new ones. Touch `Bot.act` (zone branch) and
one helper; if zone.py needs a change, keep it minimal and say so.

## Measure
practice s1, s2 and `--ffa` s1, s2, 16 matches, `--record`; compare to Task 0 (off). Also report zone deaths per arm (must not
rise) and how many fatal fights ended in `zone` mode (was 6/16 on practice s1). If zone deaths rise, try `margin_s` 15 once.
Then tests, check, fuzz.

## Deliver
Commit on top of `1d8894a`, bundle `replays\t1-zone-cover.bundle` (branch `t1-second-shooter`). Report under 20 lines:
hash, functions changed, table off/on for the 4 runs (score, kills/match, deaths<30s, zone deaths), verdict.
