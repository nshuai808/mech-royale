**Verdict** Ship `gun_aim.enabled: false`. Hit rate rose on all four runs, and score and kills rose on both practice seeds. FFA score fell on both seeds.

**Diagnosis** Across 48 baseline matches, 60.1% of shots hit a mech. Walls stopped 2,014 of 2,171 misses, with a median closest approach of 52.4 m to the target axis. The replay geometry flagged 92 spread-sensitive misses (median 3.3 m) and 33 possible lead errors (31 behind, two ahead). [Shot breakdown](C:/Users/natha/Downloads/mech-royale-t5/replays/t7/baseline-shot-diagnosis.txt)

Baseline hit rates, still/moving, were **65.4%/79.7%** at 0–40 m, **56.5%/64.7%** at 40–80 m, **58.3%/56.4%** at 80–130 m, and **54.0%/57.7%** at 130+ m. Still means below 0.5 m/s.

**Fix** `_engage` holds gun fire when both the current and predicted paths to a ground-level mech are occluded. The sim matches the protocol’s 252 m/s bullet speed and Gaussian spread. It checks cover on a grid and fires about every 0.25 s, versus exact geometry and a 0.24 s cadence in the protocol.

| 16 matches per arm | Off | On |
|---|---:|---:|
| Practice s1 | 56.8% / 1.62 / 1.25 / 2 | 86.0% / 2.00 / 1.62 / 3 |
| Practice s2 | 59.5% / 1.75 / 1.25 / 1 | 88.3% / 2.31 / 1.75 / 1 |
| FFA s1 | 65.6% / 11.69 / 1.50 / 4 | 79.2% / 10.88 / 1.31 / 5 |
| FFA s2 | 59.8% / 14.69 / 2.44 / 0 | 82.1% / 13.81 / 2.94 / 1 |

Cells show **hit rate / score / kills per match / deaths under 30 s**. [Full A/B results](C:/Users/natha/Downloads/mech-royale-t5/replays/t7/gun-aim-ab.txt) · [Fight breakdowns](C:/Users/natha/Downloads/mech-royale-t5/replays/t7/fights.txt)

All tests passed after the simulators stopped. Protocol check passed at 8.6 ms local p99, and fuzz found zero exceptions. Flag-off actions matched `integ-3` across 19,260 replayed decisions under a deterministic clock. Docker timing remains unverified. The gun-only sim omits loot, NPCs, special weapons, upgrades, and jets.

**`t7-gun-aim`** · `ef51ead5322035de5b0a5ebcb3a78479ee3fd2b2` · [Verified bundle](C:/Users/natha/Downloads/mech-royale-t5/replays/t7-gun-aim.bundle)