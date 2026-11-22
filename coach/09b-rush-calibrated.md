Good build; your result exposed a sim problem: the default practice sim kills us long before 300 s (0/144 reached it), while real
practice keeps killing until ~300 s. Claude added a **calibrated sim** and a **parallel runner** (already copied into your `tools/`;
don't commit those two files):
- `--aim-mult 4` makes house aim noise x4. On seed 1 it matches the real kill timeline (sim 2.12 kills by 150 s / 3.31 by 300 s vs
  real 2.33 / 3.69). **Judge only kills and survival in this sim, never score**: its house bots die in the zone a lot, which the real
  game doesn't show, so calibrated scores run 2-3 points above kills.
- `python tools/simpar.py --jobs 6 --matches 16 --seed N --aim-mult 4 [--record] -- .\.pyrt\python.exe -u bot.py`: same results as
  sim.py, ~5x faster. Use at most 6 jobs (another Codex is also running).

New insight: `_hunters` sends **1 + (kills so far)** hunters at once, so after 3 kills we face 4 hunters together. The "rush" builds
up through 150-300 s; holding the fortress only from 250 s is too late.

Retest in the calibrated sim, practice seeds 1, 2, 3 (16 matches each), four arms: off; your default (prep 250 s); **prep from
120 s**; **prep triggered by kills >= 2** (whichever comes first with 250 s). Report per arm: kills/match, kills by 150 s / by 300 s,
alive at 150 s / 300 s, deaths < 30 s (the TIMELINE line has most of it). Pick the best arm by total kills (ties: alive at 300 s);
if it beats off by >= 0.3 kills/match pooled, commit that setting (flag on) on top of your `61f34c9` and bundle it as
`replays\t9-rush-cal.bundle`. FFA was neutral before; one FFA seed with the chosen setting is enough. Report under 20 lines.
