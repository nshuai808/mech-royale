Task 0 complete on `step5-duel` at `5915f57a7f23c5232daf5abf65057d08919aab74`, the `integ-2` tip. Bot unchanged. All 64 replays are archived under `replays/t0_*`.

| Run (16 matches each) | Score | Kills/match | Deaths <30 s | Fights | Fights survived |
|---|---:|---:|---:|---:|---:|
| Practice seed 1 | 1.19 | 1.00 | 2 | 80 | 64 |
| Practice seed 2 | 2.00 | 1.31 | 1 | 71 | 56 |
| FFA seed 1 | 10.94 | 1.63 | 4 | 58 | 53 |
| FFA seed 2 | 13.62 | 2.63 | 1 | 84 | 81 |

| Pooled fatal gunfights | Total | 1 attacker | 2 attackers | 3+ attackers | HP <50% | HP 50–90% | HP >90% |
|---|---:|---:|---:|---:|---:|---:|---:|
| Practice | 31 | 4 | 10 | 17 | 10 | 4 | 17 |
| FFA | 8 | 2 | 2 | 4 | 1 | 1 | 6 |

**Task 1 first.** Pile-ups appeared in 33/39 fatal gunfights versus 11/39 starting below half HP. Practice was 27 vs 10, and FFA was 6 vs 1. Six fights met both criteria.

- Ran `fights.py` on each batch. Used simulator outcomes to correct its assumption that every last recorded fight was fatal and to include the shooter that landed the final blow.
- Zero late answers or crashes observed. Four zone deaths, one in practice and three in FFA. Two FFA matches showed less than 1 m of movement in the final 5 s despite movement commands. Match seed `2001` died to zone and `1011` won.
- Local conformance passed at 6.7 ms p99. Fuzz had zero exceptions and all seven test scripts passed. The simulator models gun fights and supply drops. Loot, NPCs, special weapons, upgrades, and jets were outside the measurement.