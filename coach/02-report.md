**Keep `heal_gate` at 0.70.** Across paired seeds, practice gained **0.53 score and 0.38 kills/match**, and fatal fights starting below half HP fell from 10 to 5. FFA gained **0.47 score** on average (+1.44 / −0.50 by seed), with kills down 0.06/match.

Changed `Bot.act()` and `Bot._choose_target()`. Measured `enabled: true`, `hp_frac: 0.7`. The practice results did not trigger a threshold retry.

| Variant | Run | Score | Kills/match | Deaths <30 s | Fatal starts <50% HP |
|---|---|---:|---:|---:|---:|
| Off | Practice s1 | 1.19 | 1.00 | 2 | — |
| Off | Practice s2 | 2.00 | 1.31 | 1 | — |
| Off | FFA s1 | 10.94 | 1.63 | 4 | — |
| Off | FFA s2 | 13.62 | 2.63 | 1 | — |
| 0.70 | Practice s1 | 1.81 | 1.38 | 2 | 3 |
| 0.70 | Practice s2 | 2.44 | 1.69 | 1 | 2 |
| 0.70 | FFA s1 | 12.38 | 1.75 | 2 | 0 |
| 0.70 | FFA s2 | 13.12 | 2.38 | 2 | 1 |

Task 0 supplied aggregate fatal-start counts of 10 practice and 1 FFA. `fights.py` counts the last fight as fatal even in surviving replays. All 64 on-arm replays are archived in [replays/t2_on_070](C:/Users/natha/Downloads/mech-royale-t2/replays/t2_on_070). The sim models guns and supply drops and omits loose loot, NPCs, special weapons, upgrades, and jets.

All seven test scripts passed. Conformance passed at **8.1 ms p99**, fuzzing found **0 exceptions**, and flag-off actions matched integ-2 on all 300 kit observations.

Commit `585b8e8b116b037b9419ff97fd27b1be589d90c4` is on `t2-heal-gate` in the local mirror. The sandbox denied writes to the original worktree’s Git index, so the edits are still unstaged there. The [verified Git bundle](C:/Users/natha/Downloads/mech-royale-t2/replays/t2-heal-gate.bundle) carries the commit for Claude. Nothing was pushed.