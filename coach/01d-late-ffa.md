Agreed: drop `zone_cover_detour` (no need to deliver it). Next: CODEX_PLAN.md **Task 4**, the `late` flag (late-game hold,
already built in this code, off by default). With `second_shooter` and `zone_cover_detour` off, this tree plays exactly like
integ-2, so work here; change only params for the test arms.

Why: practice can't show late play, and the final is a free-for-all that pays for placement. Default `--ffa` lobbies empty by
~200-280 s, before the late circles, so use the longer-lobby options Session E added: `--ffa --ffa-shy 0.6 --ffa-calm <value>`
(read `tools/sim.py` for what `--ffa-calm` takes; pick a value that makes most matches last past 300 s, and say which).

Runs: that long-FFA setting, seeds 1 and 2, 16 matches each, `late.enabled` false vs true (4 runs; `--record` not needed).
Report per arm: score, top-4 rate, wins, median and mean survival time, zone deaths, share of matches where late mode activated.
If `late` on is clearly better (score up on both seeds, zone deaths not up): commit `late.enabled: true` and bundle it as
`replays\t1-late.bundle`. Otherwise commit nothing. Report under 15 lines.
