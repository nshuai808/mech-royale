**Drop.** Zone deaths rose from 3 off to 6 with the 10 s margin and 5 with the 15 s margin. Fatal gunfights ending in `zone` mode fell from 10 to 3 and 2, respectively. Both `zone_cover_detour` and `second_shooter` are off in the delivered config.

Commit `164b43a7d60a00437d358c04fc6d3695ef6679c8` on `t1-second-shooter`, directly atop `1d8894a`. Committed in the workspace-local clone because the original Git metadata is read-only. [Verified bundle](C:/Users/natha/Downloads/mech-royale-t1/replays/t1-zone-cover.bundle). Nothing pushed.

Changed `Bot.act` and added `Bot._zone_cover_detour`. `zone.py` was unchanged. If the cover search found no point within the 15 m allowance, the bot continued the zone run.

Each cell shows **score · kills/match · deaths <30 s · zone deaths · gun deaths ending in `zone` / all gun deaths**.

| Run | Off | On, 10 s | On, 15 s |
|---|---|---|---|
| Practice 1 | 1.19 · 1.00 · 2 · 0 · 6/16 | 1.56 · 1.12 · 2 · 1 · 1/15 | 1.56 · 1.12 · 2 · 1 · 1/15 |
| Practice 2 | 2.00 · 1.38 · 1 · 0 · 4/16 | 1.88 · 1.38 · 1 · 2 · 2/14 | 2.06 · 1.44 · 1 · 2 · 1/14 |
| FFA 1 | 10.94 · 1.50 · 4 · 1 · 0/5 | 11.00 · 1.50 · 4 · 1 · 0/5 | 11.00 · 1.44 · 4 · 1 · 0/5 |
| FFA 2 | 13.62 · 2.62 · 1 · 2 · 0/3 | 13.88 · 2.69 · 1 · 2 · 0/2 | 13.50 · 2.56 · 1 · 1 · 0/4 |

The off column uses recorded controls. Scores and early-death counts matched Task 0. Kills differed by +1 in practice seed 2 and −2 in FFA seed 1 across 16 matches. Neither enabled arm activated a detour in FFA seed 1.

All seven test scripts passed. Conformance passed at 6.9 ms p99, and fuzz found zero exceptions.