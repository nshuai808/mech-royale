# H-ENG / H-REG: fight-or-flee and retreat-and-regen

Owner: engage/disengage chat. Code: `engage.py` (stdlib only), `test_engage.py` (46 tests), `tools/engage_calibrate.py`. Wired into `bot.py` on branch `v2-engage` (section 9).

## 1. What the protocol says that shapes this design

1. **Regen is symmetric.** Both sides heal 45 HP/s after 5 s without dealing or taking damage (nanites: +60%, 1.5 s sooner). Retreat-then-return does not win kills; it converts a losing fight into survival. Because score is placement, that is the point, but it means *never start a fight that is only winnable if you may retreat*.
2. **Breaking contact works if three things hold:** LOS broken, the 5 s `memory_s` lapsed, and we are quiet. Steps are audible only within 40 m and only above 5 m/s; boost within 90 m; a gun shot within 320 m; reload within 60 m. So: boost only while seen, walk once clear (>45 m, unseen), then drop under 4.4 m/s, hold fire, reload only if the last-known threat is >80 m away.
3. **Legs are independent of the torso.** Backpedalling while aiming at the pursuer keeps our front arc toward them, so a retreat costs no x1.5 rear damage. The retreat faces the nearest threat by default.
4. **Rear armor is a short window.** Torso slews at 4 rad/s, so an enemy that has its back to us needs ~0.4 s to bring us back into its 180-degree arc (plus reaction). Circling cannot out-turn a tracking enemy (at 30 m our angular speed is 0.4 rad/s). Real rear value comes from enemies *busy elsewhere*. The estimator models both: the geometric window, plus `distracted_bonus_s` once an enemy has shown its back for `distracted_after_s`.
5. **Weapon triangle is in the estimator**: lightning zeroes an enemy laser while in arc range; laser x1.6 vs a mortar holder; mortar halves lightning (concussion); mortar is dropped inside 10 m.
6. **Zone**: no regen outside it, and zone damage resets the 5 s timer. Refuge candidates outside the next circle are penalised; REGEN is aborted early enough to walk back inside before the squeeze.
7. **A supply drop is a faster regen** (full HP and energy after 4 s alone). The Zone/Drop chat should preempt REGEN when a drop is capturable and we would be alone; `Decision.wants_regen` and `mode == "regen"` are hints, not orders.

## 2. The estimator

`simulate_fight()` is an expected-value fight sim at 0.2 s steps with event-scheduled shots (gun mag/reload from current `ammo`, laser charge+cooldown, lightning, mortar direct+splash, NPC gun). It folds in: current weapon cooldowns, approach time for out-of-range weapons, enemy time-to-bear (angle gap / turn rate + reaction), rear windows both ways, cube damage, unseen-upgrade padding (+4% HP and damage per implied offer), my armor, joiners within 110 m (damage x`join_weight`, killed in ascending-HP order), zone dps when outside, and a third-party hazard that scales with `(alive-1)/15`.

**R = my effective HP / damage I take while killing everything in the fight.** For 1v1 it equals TTK(them)/TTK(me). Unfinished fights are extrapolated, so R still orders them.

Calibration (`calibrate_ratio.py`, 1200 random duels x 40 Bernoulli replays, shared hit-rate assumptions):

| R | P(win) | | R | P(win) |
|---|---|---|---|---|
| 0.6-0.8 | 0.13 | | 1.4-1.7 | 0.86 |
| 0.8-1.0 | 0.34 | | 1.7-2.0 | 0.97 |
| 1.0-1.2 | 0.60 | | 2.0-3.0 | 0.98 |
| 1.2-1.4 | 0.79 | | | |

Fit: `logit P = 0.07 + 3.22 ln R`. R=1 is a coin flip, so the estimator is unbiased against its own model; engage at 1.4 is ~75-80% to win, 1.9 is ~90%. This validates variance structure only, not the hit-rate guesses.

## 3. State machine and decision rules

`neutral -> engage -> retreat -> regen -> neutral`, with `retreat -> engage` ("cornered") and `regen -> engage` ("ambush").

- **Start a fight** if `R >= thr` and HP >= 50% and not `must_flee`. `thr = engage_ratio` (1.40) +0.30 while alive >= 11, x0.8 when alive <= 3, minus 5% per cube the kill would drop (+2), capped at 25%.
- **Stay in a fight** while `R >= disengage_ratio` (1.00; this gap is the hysteresis) and `min_fight_s` has passed.
- **Flee triggers (`must_flee`)**: HP < 30%, or `my_ehp <= escape_cost*(1+escape_margin) + reserve`, where `escape_cost = enemy dps x seconds-to-refuge`. This is a point-of-no-return rule: leave while we can still afford the run.
- **Finisher override**: if the target dies within 1.2 s and we take < 80% of our HP by then, stay (unless HP < 12%).
- **Retreat**: pick a refuge (12 headings x rings 12/24/40 m, scored on hidden-from-threats, distance gained, travel time, path exposure, zone). Budget 12 ms (measured 2 ms on the real map), replan every 0.5 s, commit 1.5 s. Unseen shooters (`damaged.by` not visible) become phantom threats at 90 m along the bearing.
- **Pursuit**: running > 6 s with the nearest threat not receding and R >= 0.55 -> turn and fight ("cornered").
- **Regen**: stand still, hold fire, face the last-known threat, wait for 85% HP (cap 45 s). Re-run the estimator if a mech shows up: ambush only if R clears the engage bar, otherwise retreat again. Remembered enemies are healed forward in time (`predicted_enemy_hp`) so we never assume a fled enemy stayed hurt.
- **Lockout**: no re-engage of a target we fled for 4 s.

## 4. Knobs (all in `params.json["engage"]`; `python3 engage.py --dump-params`)

| Knob | Default | Sweep | Trades off | Metric |
|---|---|---|---|---|
| `engage_ratio` | 1.40 | 1.0, 1.2, 1.4, 1.7, 2.0 | more kills/cubes vs more deaths | placement; fights/match |
| `disengage_ratio` | 1.00 | 0.7, 1.0, 1.2 | sticking vs fleeing a fight already started | deaths while engaged; mode flips/min |
| `early_ratio_add`, `early_alive` | 0.30, 11 | 0-0.6; 8-14 | early passivity vs third parties | placement by alive-bucket |
| `late_alive`, `late_ratio_mult` | 3, 0.8 | 2-4; 0.6-1.0 | forced endgame fights | placement when alive<=4 |
| `retreat_hp_frac` | 0.30 | 0.2, 0.3, 0.4 | early flee vs dying mid-escape | deaths while retreating |
| `escape_margin`, `escape_reserve_hp` | 0.6, 120 | 0.3, 0.6, 1.0 | same, dynamic | retreat success rate |
| `regen_resume_frac` | 0.85 | 0.6, 0.85, 1.0 | time spent hiding vs HP at next contact | HP at next contact; time in regen |
| `hit_gun/laser/mortar_*` | 0.5/0.55/.15,.55 | +-0.2 | estimator optimism | fraction of decisions that flip |
| `enemy_skill`, `join_weight`, `third_party_dps` | 1.0, 0.5, 14 | 0.8-1.3; 0.3-0.9; 0-30 | how crowded we think the field is | placement; deaths by third party |
| `pursuit_giveup_s`, `cornered_ratio` | 6, 0.55 | 3-10; 0.4-0.8 | run vs turn and fight | deaths while retreating |
| `distracted_bonus_s` | 2.0 | 0, 1, 2, 3 | rear-armor optimism | rear-hit share of damage dealt |
| refuge `w_*`, `clear_dist`, `slip_speed` | see file | x0.5, x2 | cover quality vs detour | time-to-regen-start; re-detection rate |

## 5. How to test

**What we have**: 46 unit tests (monotonicity in HP/cubes/armor/zone/joiners, triangle effects, rear window math, hysteresis, retreat->regen->resume, finisher, lockout, phantom shooter, regen ETA with nanites, predicted enemy regen), LOS tests on the real map, a conformance pass, and the calibration table above. Typical `update()` 0.3-1 ms; retreat start 3 ms; LOS 0.05 ms/query; Occluder load well inside the 20 s ready window.

**What we need (H-SIM)**. Instrument the sim bot with counters: fights started, fights won (target dead before we leave), retreats begun, retreats that reached REGEN, REGEN completions, deaths by mode (engage/retreat/regen/neutral), HP at death, mode flips per minute, time in regen, damage taken during retreat, zone damage during regen. Opponent sets: hunter squad, passive looter, peer-like fighter, and a mix.

1. **Ablation** (the only test big enough for the leaderboard): A0 fight nearest, never flee; A1 estimator gating only; A2 full module. 500+ sim matches per arm. Submit A0 and A2 once each.
2. **Single-knob sweeps in sim** per the table, 300+ matches per point, same seeds across points (paired), report mean points with a paired bootstrap interval.
3. **Estimator robustness**: sweep hit rates +-0.2 and report how often the fight/flee decision flips; a threshold that flips on every 0.1 of accuracy is not tuned, it is noise.
4. **Failure checks** (expected zero): thrash (>2 mode flips/min), regen with no HP gain for 10 s, refuge goal inside a wall or outside the zone, retreat running into an unseen second enemy.

**Leaderboard noise.** The registry states ~+-0.3 on 48 matches. If that is one standard error, a difference between two submissions has SE ~0.42, so only effects of ~0.85 points or more are resolvable. Treat leaderboard runs as ablation and sanity checks; do knob tuning in the sim. Only the scalar score comes back and stderr is not shown, so the counters above exist in the sim only.

## 6. Practice vs final

- **The submitted image is one config for both.** We cannot switch profiles at runtime, so defaults must be robust to both; `PROFILES` (env `MECH_PROFILE`) exists only so H-SIM can replay the practice structure.
- **Practice (15 house bots hunting us)**: enemies converge, so joiners and third-party arrivals are likelier (profile: `join_weight` 0.8, `third_party_dps` 22, no early-game penalty). Breaking contact may fail if they track us, which makes `pursuit_giveup_s` and `cornered_ratio` matter more. Their accuracy is unknown, so no direction is assumed for `enemy_skill`.
- **Final (16 independent bots)**: fewer converging threats early, more opportunistic third parties, and some opponents will hide and regen like us, so enemy HP will be healed more often than practice suggests. The early bar and the late-game relief matter more; the late zone (70 m and under, 100+ dps) makes regen unreachable, which is why the bar drops at alive <= 3.
- **What transfers**: estimator mechanics, hysteresis, escape-cost trigger, stealth rules, refuge scoring. **What may not**: `engage_ratio`, `third_party_dps`, `join_weight`, `enemy_skill`, `pursuit_*`. Tune those under both profiles and pick the setting with the best worst case.
- **Do not read much into a practice score of the retreat routine**: if house bots hunt perfectly, retreat looks bad; if they lose us after 5 s, it looks great. Neither tells us about peers.

## 7. Assumptions and known gaps

- `self.weapons[i].stats` is assumed to exclude cube damage (the protocol says "after your upgrades"); cube scaling is applied separately. The recorded stream has no cubes, so this is unverified (`self_stats_include_cube` flips it; if wrong, my DPS is overstated by up to 40%).
- Hit rates are guesses until AIM supplies measurements. Enemy upgrades are padded, not known.
- Enemy HP is read from `obs` (`vision.show_enemy_hp` is true now; "balance changes between matches"). If it turns false, R assumes full HP and becomes pessimistic; lower `engage_ratio` in that case.
- Distance is static in the sim (no kiting or closing beyond approach delay). Refuge search is local (<= 40 m) and `walkable()` checks footprints only; Navigation must path to `Decision.goal` and own slopes/ledges/jets.
- LOS models buildings, bridges, stadium and terrain only. Trees and scenery are ignored (trunks and dense canopy block sight, so tree cover is undervalued).
- Retreat success is an assumption about how enemies (house or peer) re-acquire us after `memory_s`; only the sim or leaderboard ablation can confirm it.
- Perception owns tracking; this module keeps a minimal last-seen table and phantom threats. If Perception exposes better threat estimates, feed them in as `obs["mechs"]` entries or replace `threat_pos`.

## 8. Registry entries

| ID | Claim | Predicted effect | Knob | Metric | Verdict |
|---|---|---|---|---|---|
| H-ENG | Fight only when R >= ~1.4 (about 75-80% win) beats always engaging | +1 to +3 points over A0 | `engage_ratio` | placement | **Implemented, calibrated in the abstract model; unverified in sim** |
| H-ENG-2 | Lower the bar late (alive <= 3) and raise it early (alive >= 11) | +0.3 to +0.8 | `late_*`, `early_*` | placement by bucket | Implemented; untested |
| H-REG | Break LOS, go quiet, heal to 85% beats trading to death | fewer deaths in engage; survival time up | `retreat_hp_frac`, `escape_margin`, `regen_resume_frac` | placement; retreat success | Implemented; untested. Risk: symmetric enemy regen means no kill gain |
| H-REG-2 | The escape-cost trigger beats a fixed HP threshold | fewer deaths while retreating | `escape_margin` | deaths by mode | Implemented; untested |
| H-ENG-3 | Distracted-enemy rear-armor window is worth modelling | small (about 1% of damage from the geometric window, up to ~5% with the distracted bonus) | `distracted_bonus_s` | rear-hit share | Low priority; geometric window alone is ~0.6 s of x1.5 |

## 9. v2 integration (branch `v2-engage`)

- **Hook**: `Bot._make_engage` (built in `__init__`, loads the map `Occluder` in the ready window), `Bot._engage` (one `update()` per tick in try/except), and a few lines in `act()`. Any failure means `engage.Decision()` (neutral), i.e. v2 behaviour.
- **What it owns**: in `retreat` and `regen` only. Retreat sets the goal (it outranks loot and the zone walk), boosts only while seen, and walks at `speed < 1` once clear. Regen stands still, faces the last-known threat, and reloads the gun (found by kind, not slot) if no threat is near. Both hold fire and suppress the periodic jump. In `neutral` and `engage` nothing changes: v2 still aims, fires and walks as before. Never sets `take`/`drop`.
- **Added after the first replay**: `avoid_ratio`/`avoid_dist` (leave a hopeless matchup before it starts: the house squad hunts the weakest, so waiting to be hit first is the wrong default), `auto_regen` (hurt with nothing in view: hide from the last-known threat, else hold still), the observation as ground truth for "seen" (a mech in `obs.mechs` has LOS to us whatever the map model says), a 0.6 s unseen timer before standing still, and a memory of refuges that turned out visible. These fixed a retreat/regen flap seen on the recorded stream (18 transitions down to 4).
- **Not done**: `engage` mode does not steer or fire yet (v2 aims flat and always fires; the Aim/Move chat will plug in there). Refuge goals are straight-line; Navigation should path to `Decision.goal`.
