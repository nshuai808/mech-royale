# Trials on branch `claude/nifty-galileo-lw5l5t` (Sat-Sun, 2026-11-21/22)

Data and observations only; the code stays on the branch. The branch is our Python bot (`main`'s v2, 2.92) plus
`zone.py`, `drops.py`, `roof.py` and a stack of `params.json` switches (`aggro`, `ultra`, `pacifist`, `roof`). Every
commit below is on that branch. Real scores are 48-match practice submissions; noise is about ±0.3 per submission.

## 1. Real practice scores

| Commit | Score | What changed (cumulative unless noted) |
| --- | --- | --- |
| `b064eeb` | 3.02 | v2 + `zone.py` (CRITICAL forces a zone run) + `drops.py` (supply drops; holding a ring we capture outranks evade/fight) |
| `ee4f3fc` | 2.90 | + face nearest threat while evading/hiding, time-based third-party check, unstick sidestep |
| `5c59a78` | **3.40** | + aggressive loot: lightning > laser > mortar, two specials (drop the gun), loot 150 m, shoot crates |
| `5d80994` | 3.40 | + loot 250 m early, lightning closes in, weapon-aware time-to-kill and upgrades |
| `21267c5` | 3.27 | + laser fights to 250 m, removed "2 within 150 m and HP < 85% -> evade" |
| `ea37402` | **3.56** | + power farming: NPCs to 150 m, cubes 120 m, crates 150 m, roam when idle in the first 3 min |
| `8ecaa3c` | 3.35 | + rooftop camping from 100 s (`roof.py`) |
| `ac6e281` | 3.60 | `ea37402` + all-out aggression (`aggro`), roof off |
| `da3afa0` | 3.46 | + `ultra`: never flee, loot before hunting, cubes 200 m, crates all match, jet to roof loot, boost travel, fight hops, bold drops |
| `df31a39` | 3.63 | "medium": ultra with flee below 40% HP vs 2+, heal to 90% before hunting, no hops, middle drop settings |
| `8ffc0c2` | **0.08** | PROBE pacifist: never shoots mechs, hides from every threat, farms, parks at the final centre |
| `23c2aa1` | 3.42 | medium + armor-first upgrades + back into cover when a second enemy can join (`_third_party`) |
| `22fd5bd` | 3.50 | "A": keep the gun (no two-specials), loot the body after each kill, drones to 250 m, HP upgrades then gun_rate/gun_damage |
| `e9f6823` | not scored yet | "aggressive A": A + flee only below 25% vs 2+, hunt at 60% HP, no third-party cover, bold drops |

Everything from `5c59a78` on sits in 3.3-3.65: one band of noise. Only two steps were clearly real: loot/weapons
(3.02 -> 3.40) and power farming (-> 3.56).

## 2. What the probes and scores showed

- **Pacifist 0.08: practice points are only our kills.** House bots never die to the zone, NPCs or each other often
  enough to matter, and a bot that only hides is found and killed first almost every match. The final zone collapse is
  worth nothing in practice because we never live that long. (Agrees with the stop-shooting probes in LEARNINGS.md.)
- **Aggression is not the lever.** Aggro 3.60, ultra 3.46, medium 3.63, aggressive-A pending: all noise around 3.5.
  Never-flee (ultra) and roof camping were the two clear losers on this branch.
- **Getting stronger was the lever on the Python bot**, then it flattened: lightning/laser + crates (+0.4),
  NPC/cube/crate farming (+0.16). Wider ranges and more of the same added nothing.
- **Dropping the gun for two specials was probably a mistake** (see section 4): top bots keep the autocannon.

## 3. Local sim A/B (tools/sim.py; gun only, strong house bots; same seeds per row)

| Comparison | Matches | Result |
| --- | --- | --- |
| main v2 vs v2 + zone + drops (sim with drops modelled) | 192 | 2.35 vs 2.21 (noise); drop captures 8 vs 12 matches |
| + face threat / + third-party / + unstick sidestep | 96 each | 2.21 / 2.08 / 2.19 / 2.16 (all noise) |
| reload in cover (duck out of sight while the gun reloads) | 40 | 2.02 vs 2.17: lives longer (156 vs 149 s), kills less (1.23 vs 1.38). Dropped |
| chase wounded targets out of sight | 40 | 1.82 vs 2.17: chasing exposes us to the squad. Dropped |
| roam when idle early (part of `ea37402`) | 40 | **2.35 vs 2.17, kills 1.70 vs 1.38** (the one sim gain that also went up in real) |
| roam until 330 s instead of 180 s | 40 | 2.27 vs 2.35 (noise) |
| aggro / medium / ultra vs cautious farming | 40 | 1.85 / 1.65 / 1.27 vs 2.35: life 82 / 74 / 56 vs 145 s. Real gaps were far smaller (sim bots are much stronger than the "nerfed" real ones) |
| medium + third-party cover vs medium | 40 | 1.93 vs 1.65, kills 1.60 vs 1.45, life 96 vs 74 s. Real: 3.42 vs 3.63 (did not transfer) |
| rear-hit "rear guard" (face whoever hit us last) | 1 match | worse: rear hits are mostly two attackers ~220° apart; turning to one exposes the back to the other. Reverted |

Sim notes:
- Our accuracy is fine (56-65% of gun shots hit) and we deal more than we take (e.g. 4658 vs 2812), yet that is ~1 kill:
  damage is spread over several hunters that then regenerate while we evade.
- A recurring sim-only zone death (~200 s, bot trapped in a pocket it can't jet out of) affects every version equally.
- The sim cannot judge anything about loot, cubes, NPCs, crates, upgrades, drops, jets or roofs.

## 4. Outside observations (not measured by us)

From the event's Watch page chat (live stream), the track designer (LizTheFirst443):
- "The practice bots are nerfed."
- "My best honest score is 6.75"; "I can get 9.7"; "seeds are visible to bots actually". The 9.7 reads as a fixed-seed
  exploit; we did not pursue it (the final uses other matches, and it is not an honest score).
- Repos may be made private after they are scored (rules update).

From watching real top bots (teammate's notes):
- `azing` had 22 cubes by 2:39 and 27 by 4:49. Survivors seen at 2254, 1739 and 1456 max HP (all above 1400).
- Almost every kill seen was the autocannon. Top bots keep the gun and pair it with one special: azing + laser,
  tigerbyte + mortar, kyoto-max + lightning.
- They snowball by looting each kill (a dead mech drops all its cubes + 2 and its weapons).
- tigerbyte's route: farm + HP upgrades, then survive into the zone collapse.

## 5. Tools added on the branch (already merged to main)

- `tools/sim.py`: supply drops (called, land in the next circle, alone-in-ring capture -> full HP + cubes, rival house
  bots via `--drop-rivals`), `--first N` to rerun one match, `--ffa` free-for-all house bots for head-to-head checks.

## 6. Takeaways for the giddy base

- Practice = kills. Anything that trades firepower for safety (hiding, ducking out to reload, never fleeing into open
  ground) was neutral or worse; consistent with LEARNINGS.md section 2.
- Keep the gun plus one special; loot bodies; farm cubes early. giddy already keeps the gun and picks cubes mid-fight.
- Don't trust sim gains that change exposure (third-party cover: sim +0.28, real -0.21).
