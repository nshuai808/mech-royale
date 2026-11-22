**Verdict** Keep `evade_unstick.enabled` off by default. With it enabled, FFA gained **0.91 ± 0.58 points** per match against the paired reruns (standard error), and fatal stuck windows fell from **5 to 1**. Practice results were mixed.

**Diagnosis** Baseline practice had 11 stuck windows across seven gun deaths. Eight involved building or solid contact, and three involved backtracking without contact. Cover was 2.6–53.3 m away when available. All 11 overlapped `_unstick_v2`, and none used A*. [Per-window diagnosis](C:/Users/natha/Downloads/mech-royale-t5/replays/evade-stuck-diagnosis.txt)

**Fix** `_evade` calls `_evade_slide` to choose the closest heading that clears the mech’s footprint. Torso aim tracks the threat during the slide.

| 16 matches per seed | Off | On |
|---|---:|---:|
| Practice s1 | 1.19 / 1.00 / 2 / 9 | 1.94 / 1.44 / 2 / 5 |
| Practice s2 | 2.00 / 1.31 / 1 / 2 | 1.62 / 1.06 / 1 / 5 |
| FFA s1 | 10.94 / 1.63 / 4 / 1 | 11.69 / 1.50 / 4 / 1 |
| FFA s2 | 13.62 / 2.63 / 1 / 4 | 14.56 / 2.38 / 0 / 0 |

Cells show **score / kills per match / deaths under 30 s / stuck windows**. Off uses Task 0 figures and rerun window counts. Reruns differed on practice s2 kills (1.38) and FFA score/kills (11.00/1.38 and 13.44/2.44). [Fight breakdowns](C:/Users/natha/Downloads/mech-royale-t5/replays/evade-stuck-fights.txt)

All tests and protocol checks passed. Fuzz found zero exceptions. Local check p99 was 7.1 ms. Flag-off actions matched `integ-2` across 17,358 replayed decisions. Docker timing remains unverified. The gun-only sim omits loot, NPCs, special weapons, upgrades, and jets.

**`t5-evade-stuck`** · `d7e9ae5358f7f4819596c0b195b86d798811a4d6` · [Verified bundle](C:/Users/natha/Downloads/mech-royale-t5/replays/t5-evade-stuck.bundle)