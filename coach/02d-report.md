**Verdict: Test `fights` in real practice.** At 0.70, it was within simulation noise of `all` (−0.19 practice score, −0.03 FFA score), with identical early-death counts. The real-game loot benefit remains unmeasured.

Commit `a299738247fb9e271e80490390470bd8d1118715` is on the local mirror’s `t2-heal-gate`, based on `585b8e8`. Changed `Bot.act()` and `Bot._aim_and_fire()`. The original worktree holds unstaged edits. [Verified Git bundle](C:/Users/natha/Downloads/mech-royale-t2/replays/t2-heal-gate-v2.bundle)

| Run | Off | All | Fights |
|---|---:|---:|---:|
| Practice s1 | 1.19 / 1.00 / 2 | 1.81 / 1.38 / 2 | 1.50 / 1.25 / 2 |
| Practice s2 | 2.00 / 1.31 / 1 | 2.44 / 1.69 / 1 | 2.38 / 1.63 / 1 |
| FFA s1 | 10.94 / 1.63 / 4 | 12.38 / 1.75 / 2 | 12.25 / 1.69 / 2 |
| FFA s2 | 13.62 / 2.63 / 1 | 13.12 / 2.38 / 2 | 13.19 / 2.25 / 2 |

Cells show score / kills per match / deaths before 30 seconds. All four 16-match runs and fight reports are in [replays/t2_v2](C:/Users/natha/Downloads/mech-royale-t2/replays/t2_v2).

All seven test scripts passed. Conformance passed at 8.6 ms p99, fuzzing found zero exceptions, and `off` and `all` each matched their baseline on 300 low-HP observations.