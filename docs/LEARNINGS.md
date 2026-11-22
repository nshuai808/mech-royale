# What we learned (Fri-Sat, 2026-11-20/21)

The short version of every test we ran. Details: README's Submissions log (every real score), `coach/LOG.md`
(day log, decisions), `coach/NN-*.md` (test briefs) and `coach/NN-report.md` (results), `docs/leaderboard_study.md`
(what the top teams run). Branch `claude/nifty-galileo-lw5l5t` trials, the pacifist probe, sim A/Bs and
outside observations (designer chat, top bots' cubes and loadouts): `docs/trials_nifty_galileo.md`. `main` now runs giddygiddyboy's Go bot (`giddy/`, 5.73); everything below the "Python bot"
heading was learned on our own Python bot (best 3.71, `integ-3` = `6bb23c4`).

## 1. The scorer and the board

- **Score ≈ house bots that die before us ≈ our kills.** The squad never fights itself. Surviving alone scores ~0.
- **The scorer is deterministic per commit** (the starter re-scored exactly 1.15), but any code change reshuffles the 48
  fights: **noise is ±0.2-0.3**. Ten neutral changes landed between 3.29 and 3.71. Only trust effects of ~0.4 or more.
- The board keeps each team's **best** score. Some teams resubmit the same bot with a different RNG salt to re-roll the
  48 matches. That is noise fishing (+0.2-0.3 at most) and says nothing about the final.
- Probe submissions work as a measuring tool: a bot that stops shooting after time T scores its kills before T.
  integ-3: **2.33 kills by 150 s, 3.69 by 300 s, 3.71 total**. Nothing after 300 s, when the rest of the squad comes at once.
  The kill rate halves after 150 s (stronger hunters, often two at once).

## 2. What won and lost in real practice (Python bot)

| Direction | Real result | Lesson |
| --- | --- | --- |
| Hide when 2+ see us, fight only the hunter (v2) | 1.15 -> 2.92 | The big early gain: fight one hunter at a time |
| Aggressive loot: lightning first, two specials, crates | 3.02 -> 3.40 -> 3.56 | Power gain paid well, then flattened |
| `evade_unstick` (slide along walls when an escape is blocked) | **3.71** | Execute better without giving up damage: wins |
| `heal_gate` v1 / v2 (no new fights while hurt) | 3.17 / 3.29 | Disengaging loses |
| `laser_flee` (release laser while fleeing) | **2.92** (-0.79) | Many kills come from lasers fired while repositioning |
| `gun_aim` (hold fire when a building blocks the shot) | 3.33 | Firing less loses, even "wasted" shots |
| Swing 1 power build (cube cap, lightning chain, NPC farm) | 3.65 | Neutral: it only pays in the rush, which we never reached |
| Swing 2 rush fortress | 3.46 | Calibrated sim +0.42 kills did not transfer |
| Swing 3 hunter-killer (aggro while one hunter is on us) | **3.02** | Leaving cover to hunt loses badly |
| Swing 4 finisher + damage build | 3.17 | Worse |
| Loot/weapon flags (`weapon_ctx`, `upgrade_ctx`, `mortar_lead`, `special_guard`) | 3.42-3.60 | All noise |

**The pattern:** changes that make the bot disengage, fire less, or leave cover lost. Changes that keep firepower and only
execute better won. Practice pays for damage dealt.

## 3. The local sim

- `tools/sim.py` is gun-only: no loot, cubes, NPCs, upgrades, lasers, lightning, jets or roofs. It **ranks** versions
  correctly when the gap is big. It does not predict real deltas of ±0.5.
- It ranks the switch to giddy correctly (default sim, 24 matches, seeds 1 / 2):

  | Bot | sim s1 | sim s2 | real |
  | --- | --- | --- | --- |
  | integ-3 (Python) | 1.83 | 1.25 | 3.71 |
  | giddy (`515bce5`) | 2.83 | 2.88 | 5.73 |

- The default sim dies before 300 s almost every match, so rush/drop changes show no effect in it. The calibrated sim
  (`--aim-mult 4`, branch `sim-calib`, `tools/simpar.py` for parallel runs) matches the real kill timeline
  (2.12 / 3.31 vs 2.33 / 3.69 real), but **its gains did not transfer twice** (swing 2 +0.42 -> -0.25 real, swing 3
  +0.96 -> -0.69 real). It underprices the cost of being exposed.
- **Rules:** never promote a change that alters exposure (hunting, chasing, moving under fire) on sim evidence. A change
  that touches loot, cubes, drops, NPCs, crates or specials is in the sim's blind spot: its sim result is upside-only.
- Sim findings that held up: most fatal fights have 2+ attackers (33/39); the bot dies **while leaving** fights, not by
  staying (zone runs across open ground under fire, stuck escapes against walls); rear hits ~26% of fatal gun damage;
  60% of gun shots hit, and 93% of misses hit walls.

## 4. What the top teams do (see `docs/leaderboard_study.md`)

- The 6.2-6.4 plateau is mostly one public MIT bot (giddygiddyboy, Go). Teams with their own brains score 2-4.5.
- Its keys: detect practice vs FFA (deaths we didn't cause) and switch parameter sets; laser first in practice
  (seek 240 m, laser upgrades after plating/armor, fight at ~120 m); laser fired early when lethal, held through brief
  target loss; retreat in 1.5 s pulses, overridden when the target dies within one burst; a fitted win-probability model;
  fight movement from scoring 16-32 nearby points; cubes picked up mid-fight.
- This agrees with section 2: it never gives up damage in practice.
- Unchanged giddy scored **5.73** for us (another team's unchanged copy also scored 5.73). Tuned copies reach 6.2-6.3.

## 5. Process

- Matches give no logs. Local tools (check, replay, sim, fuzz, analyze) are the only visibility.
- No Go or Docker on Nathanael's machine: Go 1.26.11 was downloaded to a session scratch folder to build giddy.
  The Docker sandbox timing check has never been run locally. giddy answers in p99 1.4 ms (Python bot ~2-9 ms).
- Codex worked in sandboxed worktrees and handed commits back as bundles in `replays/` (it can't write git's shared index).
- One change per submission, 4 submissions per hour; queue in `coach/SUBMIT.md`, log every score in README.

## 6. Next, on the giddy base

Everything above says: keep the damage, change execution. Candidates (each a small flag in `giddy/`, logged in
`giddy/README.md`'s change table):
1. Our FFA work for the final: giddy's FFA mode is untested by us. Compare its FFA behavior in `sim.py --ffa`.
2. Stuck-pocket escape (Ohio Stadium bowl, `docs/stuck_pocket.md`) if giddy has the same problem.
3. Small fixes other teams made public and tested (e.g. laser hold through target loss already in; supply drops off by default).
