# Spawn safety (Session A follow-up), branch `step2-spawn-safety`

Base: `step2-early-evade` (`eae65a2`, = main `ac6e281` + `early_evade` hp_frac 0.6). Its A/B left early deaths unchanged (14/48).

## Why we die before 25 s (sim, 8 deaths on seeds 1-2)
- In 6 of 8, most damage came from a mech we **could not see**, mostly in the back (rear hits x1.5): we dueled the
  visible hunter while a second bot shot us from outside our 120 deg wedge. With aggro on, nothing reacts to that.
- After that was fixed, the rest: evade found **no cover within 40 m** (open spawns, "evade away") and
  **dithered** fight <-> evade every 0.3-0.5 s, so it never reached the cover it picked.
- Left over: swarms of 3-4 shooters (e.g. seed 1002 hunts into four bots at t=7). Partial cover doesn't save those.

## Changes (each its own flag in `params.json`; both `enabled: false` = base)
- `unseen_hit`: a mech we can't see hit us within `window_s` (1.5 s).
  `cover`: evade (cover search also blocks that bearing) unless the target dies within `finish_s` (1.5 s, gun TTK).
  `face`: turn the torso to the newest unseen attacker (fight/evade/hide/hunt) so it enters vision and hits land in front.
  Code: `Bot._unseen_cover`, `Bot._finishing`, `self.unseen` in `act()`, aim override in `_aim_and_fire`.
- `evade_fix`: once evade starts, stay in it `commit_s` (2.5 s) unless the target is about to die; cover search
  radii out to 70 m (was 40). Code: `self.evade_until` in the evade condition of `act()`, radii in `_evade`.

## Sim A/B (practice sim, 16 matches per seed)
| variant | s1 | s2 | s3 | s4 | mean | kills/match | died < 25 s | died < 30 s |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| both off (base) | 2.00 | 1.81 | 1.69 | 2.06 | 1.89 | 1.77 | 16/64 | 18/64 |
| unseen_hit only | 2.06 | 1.62 | - | - | 1.84 | 1.81 | 6/32 | 7/32 |
| both on | 2.19 | 1.94 | 2.44 | 1.69 | **2.07** | 1.80 | **8/64** | 11/64 |

Verdict: early deaths halve (25% -> 12.5%) with kills unchanged; score +0.18 is inside the noise (diff s.e. ~0.27).
Seed 4 alone went down (2.06 -> 1.69). check PASS, fuzz 0 exceptions (worst 12.9 ms), zone/drop tests pass, kit p99 9 ms.

Not verified: real practice score, `--ffa` (final) mode, Docker timing. The sim has gun fights only and its house bots
shoot on sight, so it likely overstates how often unseen bots hit us.
