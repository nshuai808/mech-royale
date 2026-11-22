# Submissions queue (what Nathanael should submit next)

Top = submit first. Paste the scores back to Claude.
**Current base: `main` = giddy Go bot (`515bce5`) = 5.73.** Python best was `integ-3` = `6bb23c4` = 3.71. Noise is 0.2-0.3.

## Pending
_Paused: no changes for now (Nathanael is focusing on fight recording and analysis)._

## Done
| Commit | What | Score | Verdict |
| --- | --- | --- | --- |
| `8a2aeac` | weapon_ctx (on integ-2) | 3.60 | noise; retest on integ-3 |
| `99d6a09` | upgrade_ctx | 3.50 | noise, off |
| `e139c2d` | mortar_lead | 3.48 | noise, off |
| `65a728e` | special_guard | 3.42 | noise, off |
| `585b8e8` | heal_gate v1 (0.70) | 3.17 | worse: freezes looting |
| `a299738` | heal_gate v2 (keeps looting) | 3.29 | worse again: heal_gate dropped |
| `6bb23c4` | **evade_unstick** | **3.71** | **KEEP: new base `integ-3`** (sim FFA +0.91, practice agrees) |
| `5a31d43` | integ-3 + weapon_ctx | 3.58 | noise (-0.13 vs 3.71): weapon_ctx dropped for good |
| `e37bac5` | integ-3 + laser_flee | **2.92** | much worse (-0.79): retreat-time laser kills matter more than retreat speed. Dropped |
| `a7b621c` | PROBE: no shots after 300 s | 3.69 | = kills before 300 s (measurement) |
| `deaaa12` | PROBE: no shots after 150 s | 2.33 | = kills before 150 s (measurement) |
| `1c37af2` | integ-3 + gun_aim | 3.33 | worse (-0.38): holding fire at 'blocked' shots costs real hits. Dropped |
| `5d196e3` | BIG SWING 1: power (lt_energy + rush_build + cube_cap + farm_plus + lt_chain) | 3.65 | neutral (-0.06). Kept as the base for swing 2: it's rush prep, which only pays if we survive into the rush |
| `b1ecbf2` | BIG SWING 2: power + rush fortress | 3.46 | worse than integ-3 (3.71) and swing 1 (3.65); calibrated sim's +0.42 kills didn't transfer. Not promoted, not bisected |
| `66e3589` | BIG SWING 3: power + hunted aggro (on while <= 1 hitter in 20 s and <= 1 in sight) | **3.02** | much worse (-0.63 vs swing 1, -0.69 vs integ-3); calibrated sim's +0.96 kills didn't transfer. Dropped |
| `7744704` | BIG SWING 4: damage-max (finisher, no chase + damage build) | 3.17 | worse (-0.54). Dropped |
| `515bce5` | giddygiddyboy MIT Go bot (`giddy/`), unchanged but the name | **5.73** | **KEEP: new base, now `main`** |
