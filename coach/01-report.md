**Drop.** Across the paired seeds, hits+LOS changed mean practice/FFA score by +0.00/−0.06. Hits-only changed it by −0.09/+0.06. Early deaths held steady in both variants. The committed flag defaults to off.

Commit `1d8894a11af4aad81647343b3caf91ff98b2fb09` on `t1-second-shooter`. The original worktree’s Git metadata denied writes, so the commit is in `replays/t1_commit` and the [verified Git bundle](C:/Users/natha/Downloads/mech-royale-t1/replays/t1-second-shooter.bundle). Nothing was pushed.

Changed `Bot.act` and replaced `_multi_hit` with `_second_shooter`. Settings were `attackers=2`, `window_s=2.0`, `los_r=150`, `finish_s=1.5`. Hits-only set `los_enabled=false`. The existing 2.5 s evade commit, wide cover search, and legacy `early_evade` behavior were preserved.

| Variant | Run | Score | Kills/match | Deaths <30s | Fatal fights with 2+ attackers |
|---|---|---:|---:|---:|---:|
| Off | Practice 1, rerun | 1.19 | 1.00 | 2 | 13/16 |
| Off | Practice 2 | 2.00 | 1.31 | 1 | — |
| Off | FFA 1 | 10.94 | 1.63 | 4 | — |
| Off | FFA 2 | 13.62 | 2.63 | 1 | — |
| Hits+LOS | Practice 1 | 1.19 | 1.00 | 2 | 13/16 |
| Hits+LOS | Practice 2 | 2.00 | 1.44 | 1 | 14/15 |
| Hits+LOS | FFA 1 | 10.94 | 1.38 | 4 | 5/5 |
| Hits+LOS | FFA 2 | 13.50 | 2.50 | 1 | 1/4 |
| Hits-only | Practice 1 | 1.12 | 0.94 | 2 | 13/16 |
| Hits-only | Practice 2 | 1.88 | 1.25 | 1 | 13/15 |
| Hits-only | FFA 1 | 11.06 | 1.44 | 4 | 5/5 |
| Hits-only | FFA 2 | 13.62 | 2.50 | 1 | 1/3 |

The off rerun matched Task 0 exactly. Task 0 supplied 33/39 fatal fights with 2+ attackers in aggregate. The table counts gun deaths because `fights.py` also labels the last fight of survivors as fatal. One hits-only replay first diverged in cover choice while both bots were already evading from the same observation.

All seven test scripts passed, conformance passed at 7.1 ms p99, and fuzz found zero exceptions. All nine 16-match runs were recorded and analyzed. Combat simulation is gun-only and omits loot, NPCs, special weapons, upgrades, and jets. Docker timing remains unverified.