# Mech Royale: wrap-up (UMich IBE, Builders Buildathon, Nov 20-22 2026)

**Result: 10th overall.** Entered qualifying at about 25th on the practice board, with `41402c5` (6.31 on builders-4).

## The path

| Stage | Bot | Practice score |
| --- | --- | --- |
| Fri | Python starter kit | 1.15 |
| Fri | Python survival bot v2 (fight one hunter at a time, cover) | 2.92 |
| Sat | Python + zone/drops, loot, NPC farming (best `6bb23c4` integ-3) | 3.02 -> 3.71 |
| Sat | Switch to giddygiddyboy's MIT Go bot (`515bce5`) | 5.73 (builders-3) |
| Sun | giddy + duel bot + laser-first upgrades + HealGate (`768b8a3`), practice switch at 5 s (`8621477`) | 5.75 / 5.84 |
| Sun | Team Sulertia's MIT "zoro" V2 + giddy practice economy and recovery (`9fa225a`) | 6.10-6.17 |
| Sun | + `SquadDuelLeave` 0.30 (hold squad duels a little longer) (`41402c5`) | **6.31**, final entry |

## What we learned

1. **Practice points are our kills.** The pacifist probe scored 0.08; house bots never die otherwise. Probes that stopped
   shooting after 150 / 300 s showed where kills happen (giddy: 4.58 by 150 s, none after 300 s).
2. **The base bot mattered far more than tuning.** 27 builders-4 runs of small giddy variants: mean 5.47, sd 0.16. No single
   tweak was distinguishable from noise. The big steps were base changes: Python -> giddy (+2), giddy -> zoro hybrid (+0.6).
3. **Exposure loses.** Hiding, chasing, long loot trips, roof camping and disengaging rules all lost in real practice, even
   when the local sim liked them. Cutting giddy's own loot settings lost too: its defaults were locally optimal.
4. **Know the noise before reading a score.** 48 fixed seeds (builders-3): identical code = identical score, any change ±0.25.
   96 fresh seeds (builders-4): ±0.16-0.18. A "best of N" score is usually a lucky draw; judge a bot by its neighbours.
5. **The sim was a crash check, not a predictor.** Gun-only house-bot sim gains (AllFoes, early tracking, EngageDist) did not
   transfer; it can't see loot, lasers, upgrades or roofs.
6. **Real data beat guesses.** Recorded showdowns (`tools/feed_record.py`, `tools/feed_analyze.py`) showed gun+laser as the best
   loadout, early deaths as the main FFA risk, and first deaths at 8-24 s (why the 5 s practice switch was unsafe for the final).

## Tools worth keeping

- `tools/sim.py`: house-bot sim with supply drops, `--ffa`, clone arena (`--clones N --clone-cmd BIN`).
- `tools/feed_record.py` / `tools/feed_analyze.py`: record and analyze the public spectator feed.
- `tools/fuzz_bin.py`, `kit/check/check.py`, `tools/laser_hold_check.py`: protocol, crash and scripted-behavior checks.

## Credits

giddygiddyboy (giddy, MIT), Team Sulertia / Specz04 (zoro, MIT), waiprotein (upstream giddy tuning reference, MIT).
Repositories that asked AI tools not to read or adapt them were not used.
Details: README Submissions log, `docs/road-to-six.md`, `docs/advit_summary.md`, `docs/LEARNINGS.md`.
