**Keep `finisher` off.** Calibrated practice gained **+0.88 kills/match**, with gains on all three seeds. FFA kills and survival fell across the two seeds, so the enabled arm failed the FFA check. The practice gain cleared +0.20, so I skipped the retry.

| Run | Flag | Kills/match | Kills by 150 s | Kills by 300 s | Alive at 150 s | Alive at 300 s |
|---|---|---:|---:|---:|---:|---:|
| Calibrated practice | Off | 3.56 | 2.02 | 3.56 | 45/48 | 3/48 |
| Calibrated practice | On | **4.44** | 2.35 | 4.42 | 42/48 | 1/48 |
| FFA seed 1 | Off | 1.56 | 0.88 | 1.56 | 12/16 | 1/16 |
| FFA seed 1 | On | 1.56 | 0.75 | 1.56 | 11/16 | 1/16 |
| FFA seed 2 | Off | 2.56 | 1.56 | 2.50 | 15/16 | 2/16 |
| FFA seed 2 | On | 2.19 | 1.63 | 2.19 | 11/16 | 0/16 |

Commit `9b3ae20d595a1f0508d3ca1cb3daf448188d2c93` directly atop `6bb23c4` adds TTK targeting, target lock, last-seen pursuit, and the 2 s finish override. The workspace-local commit contains only `bot.py` and `params.json`. [Verified t14-finisher.bundle](C:/Users/natha/Downloads/mech-royale-t1/replays/t14-finisher.bundle)

All seven test scripts passed with stdin closed. Conformance and fuzz passed with the flag on and off, with zero fuzz exceptions.