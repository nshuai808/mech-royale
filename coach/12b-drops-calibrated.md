Good work; your practice result (0 captures in both arms) came from a sim problem: the default practice sim kills us long before the
drops, while real practice keeps killing to ~300 s. Claude added a **calibrated sim** and a **parallel runner** (already copied
into your `tools/`; don't commit those two files):
- `--aim-mult 4`: house aim noise x4; matches the real kill timeline. **Judge only kills, survival and captures here, never score**
  (its house bots die in the zone, which the real game doesn't show, so calibrated scores run 2-3 points high).
- `python tools/simpar.py --jobs 6 --matches 16 --seed N --aim-mult 4 [--record] -- .\.pyrt\python.exe -u bot.py`: same results,
  ~5x faster. At most 6 jobs (another Codex is also running).

Retest `drop_push` off vs on in the calibrated sim: practice seeds 1, 2, 3, 16 matches each. Report per arm: captures D1/D2/D3,
kills/match, kills by 300 s, alive at 240 s and 300 s, HP at 240 s, deaths < 30 s, zone deaths. Keep your bundle as is if `on` adds
captures without costing kills; say so either way. Report under 15 lines.
