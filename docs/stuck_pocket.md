# The "pocket" at (-217, 77): Ohio Stadium

Found by the `step4-late` session: in `tools/sim.py --ffa`, seeds 1014 and 7000 (`--ffa-shy 0.6`) end with
the bot dying to the zone in place 3 while it jitters around (-217, 77). This note covers what that spot is,
why the bot doesn't leave, and whether the same thing can happen in a real match.

**Short answer:** the pocket is the **Ohio Stadium bowl**. Our nav model (`nav.py`) treats the bowl as fully
sealed. In seeds 1014 and 7000 **the bot spawned inside it**. Once inside, A* never finds a path, so the bot
walks straight at the goal into the stands. `_unstick` fires, but after its first attempt it only sidesteps,
switching sides every time, and never climbs again. The sim has no jets, so there the bowl is a death trap.
In the real game, jets can clear every wall of the bowl (100 energy climbs about 60 m). The real risk is our
`_unstick`: in practice it makes **one** 1.2 s jet attempt per pocket, often pointed along the wall, then
sidesteps forever. A flagged fix (`params.json` `unstick.v2`, off by default) is below.

## 1. Geometry: a real bowl, sealed in our model, not just an artifact of growing the walls

- `world.json` `stadium`: center (-276.3, 128.7), field at z -9.23, field radius 36-73 m, outer radius
  105-142 m, two `openings` (gates), both in the south: (-245.1, 43.3) and (-326.8, 53.6). The seating is
  **terrain** (the heightfield climbs from -9 to about +32 m in tiers). The solid parts are 27 `stadium`
  prisms (tops -0.6 to 44 m).
- (-217, 77) is on the lower east stands (z 4.8), right against a tier face: the ground rises from 6.5 m at
  x -213.5 to 15.8 m at x -210.5. `nav.py` marks a cell as wall where the 2 m neighbour differs by more than
  2·tan 50° = 2.38 m, so this face is a solid N-S wall from y 20 to y 130+.
- Flood fill from (-217, 77), 4-connected (all three grids give the same result):

  | grid | component | reaches the rest of the map? |
  | --- | --- | --- |
  | `Map.wall` (raw 2 m walls, no mech radius) | 6968 cells ≈ 28,000 m², x -353..-205, y -6..236 | **no** |
  | `Map.nav` (walls grown 1 cell, what A* uses) | 6009 cells | no |
  | sim footprint (`Sim._blocked`: centre ± 2.2 m on `wall`) | 6274 cells | no |

  So growing the walls is **not** what closes the bowl: even the raw wall grid is sealed. The nearest place
  where the bowl and the main map come within 6 m of each other needs a 9.6 m climb, at (-343, 52).
- The SE gate (`openings[0]`), in detail: the tunnel runs at z ≈ -5 to -7 under the stands and ends at y ≈ 32
  in a **7 m terrain step** (-5.1 → +2.4 m). Inside the tunnel a 1-2 m wide terrain spike at (-242, 34)
  (+4.3 m) splits it into two 4 m gaps, narrower than the 5 m mech. The SW gate behaves the same way.
- **Finer model of the real rules** (1 m terrain samples, a step up allowed if ≤ the limit per 1 m, any drop
  allowed, prisms rasterised at 1 m; a script like `pocket_map.py`/`fine.py` in this session's scratch notes):

  | model | max up-step per 1 m | gets out of the bowl? |
  | --- | --- | --- |
  | ground under the centre only, raw prisms | 1.2 m (= step_up, about 50°) | yes: up the east stands to z ≈ 26 at (-210, 37), then drop 31 m to (-201, 34) |
  | prisms grown by the 2.5 m radius | 1.2 m | **no** |
  | prisms grown by the 2.5 m radius | 2.0 m | yes, over the west stands, z ≈ 28 at (-362, 52) |

  Whether a mech can **walk** out in the real game depends on exactly how the server checks slopes and
  ledges against a 5 m cylinder ("standing on the surface under your center", protocol §6 Movement). It is
  borderline, and the only routes go over the top of the stands, not through the gates. With jets it is easy:
  every wall in the way is a terrain tier of ≤ 11 m or a prism of ≤ 44 m, and 100 energy climbs about 60 m.

## 2. Why the bot oscillates instead of leaving

Per-tick instrumentation of `_go_point`, `_steer` and `_unstick` (a wrapper around `Bot`, seed 7000,
t = 150-154 s):

1. **`_go_point`**: the goal (36, 13) is far ESE. There's no free straight line, so it starts `AStar`. The
   search exhausts the 6000-cell component in about 2 ticks and ends with `path = None`. Since `job is None
   and path is None`, the next tick starts a new search, forever, each one spending the tick's budget. Every
   tick returns the straight-line direction (0.97, -0.24) toward the goal.
2. **`_steer`**: the ray east is blocked within 6 m, so it picks the best open heading, south (0.02, -1) or
   east (1.0, 0.02), depending on the exact position.
3. **`_unstick` does fire**, about every 1.6 s: `hist` refills to 16 entries, the bot has moved < 2 m, and
   `hist` is cleared each time. The detection is fine; the escalation is the problem:
   - Only the first event in a 10 s / 6 m window climbs. Every later event is `again`, which means a
     sidestep with `escape_climb = False` (no jump, no jets) for 1.2 s.
   - Each event adds itself to `stuck_at`, so the window never empties and `again` stays true for the rest
     of the match: **the bot never climbs again**.
   - The sidestep is perpendicular to the *steered* direction (south), so it goes east or west, and
     `side_sign` flips on every event: 1.2 s east (into the wall, no motion), 0.4 s steered south (blocked),
     1.2 s west (1.7 m), back east... Net displacement is zero. This is the (1,0) / (0,-1) / (-1,0) flicker
     in the CSV.
   - Energy stayed at 100 during this phase of 7000. The energy drop to about 19 in 1014 came from boosting
     in `drop` mode, not from escape jets.

## 3. Real game or sim artifact?

- The sim (`_move`) has no z: jumps and jets do nothing, and every `wall` cell is impassable. In the sim the
  bowl is a guaranteed death for a bot that spawns in it (it always ends around place 3 when the zone closes
  elsewhere). **Part of that is a sim artifact.**
- In the real game the bot *can* leave with jets, but `main`'s `_unstick` makes about one real attempt: a
  1.2 s jump + jet (≈ 11-12 m of rise). That attempt is pointed in the steered direction, which is usually
  along the wall, not over it. After that it only sidesteps. Whether one badly aimed 1.2 s hop clears the
  tier depends on the spot. With the zone moving away and no path, a real-match zone death from a stadium
  spawn is **plausible, not proven**: no local tool models the server's climbing.
- How often: if spawns are uniform over open ground within 0.8 × 560 m of the zone start (the sim's rule;
  the real rule is only "random"), the bowl is about 4-5 % of that area. That's roughly 1 match in 20-25 for
  us, and in the final, every match probably has a rival bot spawning there too.

## 4. How it got in

In **both** 1014 and 7000 the bot **spawned in the bowl**: (-293.7, 111.7) and (-295.2, 177.1), on the field,
and was inside it on 100 % of ticks. No mode walked it in: A* and the straight-line check both run on
`nav`, which has no way in. In 1014 it then moved around inside (roam, drop, fight, hunt) until the zone
left. Dropping in from the stands, or being knocked in by a mortar, is possible in the real game but not
seen here.

**Seed 1021 is a different bug, in the sim only.** The bot spawned at (138.8, 260.8), open ground just south
of a building. `Sim._free_point` only checks that the `nav` cell is free, but `Sim._blocked` tests the
centre ± 2.2 m, and the +2.2 m north probe lands in the building's wall cell. Each step from a position that
is already "blocked" is rejected and the velocity zeroed, so the mech never moves (its position is constant
to the cm for 197 s). The real server never leaves a mech inside a wall, so this doesn't happen in real
matches. Fix in the sim: have `_free_point` use `_blocked`, or let `_move` accept steps that don't increase
overlap.

## 5. Fix (flag `unstick.v2`, default off)

`Bot._unstick_v2` replaces `_unstick` when `params.json` `"unstick": {"v2": true}`. Detection is the same
(1.5 s, < 2 m). The response escalates with `n`, the number of earlier stuck events within 6 m in the last
20 s:

- **n even (0, 2, 4, ...) and energy > 35: climb** toward the **unsteered** desired direction (where
  `_go_point` wants to go, not where `_steer` deflected it). Jump, then jet while airborne and energy > 8.
  The first attempt lasts 1.2 s, as on `main`. Later ones last up to 0.6 + energy/15 s (≤ 4.5 s), i.e.
  enough jet for 30-45 m of climb.
- **n odd, or low energy: slide** perpendicular to the desired direction (along the wall), for 2.0 s. The
  same side is used for two slides in a row (n = 1, 3), then the other (n = 5, 7), so the slides add up
  instead of cancelling.

In the sim this can't show its real benefit, since jets do nothing there. The sim A/B is a regression check
for normal movement.

### A/B (`tools/sim.py --ffa`, 16 matches per seed set, same seeds for both arms)

Score is the sim's mean points (16 - place) per match.

| arm | seeds 1000-1015 | seeds 2000-2015 | mean (32) | zone deaths |
| --- | --- | --- | --- | --- |
| `unstick.v2` off (= `main`) | 9.88 ± 1.53 | 9.31 ± 1.30 | 9.59 | 2 |
| `unstick.v2` on | 9.56 ± 1.61 | 10.00 ± 1.36 | 9.78 | 2 |

The difference is noise. Once the two arms make one different decision, the rest of the match plays out
differently, which is why matches with no stuck spot also differ. Stadium spawn 1014: place 3 → 2. In the
`step4-late` sim with `--ffa-shy 0.6`, seed 7000: place 3 → 2 (died 259 s instead of 215 s). Both are still
zone deaths because the sim can't jet. Conclusion: **no movement regression in the sim. The benefit, if any,
only shows in the real game**, so turning it on is a call for a practice submission.

`python kit/check/check.py -- python -u bot.py`: PASS with the flag off and on (p99 9.5 ms on this machine).
`python tools/fuzz.py`: 0 exceptions in 1200 decisions, worst 8.8 ms (off) and 8.4 ms (on). Fuzz rarely
reaches the stuck path, since it needs 16 ticks without moving.

## Follow-ups (outside this change)

- **Sim**: let jets climb (even crudely: while boosting in the air, a `wall` cell whose ground is < z + 1.2
  becomes passable) so the sim can judge escapes. Also fix the 1021 spawn-in-wall bug above.
- **Nav**: when `AStar` fails, don't start a new search the very next tick (cache "no path to this goal" for
  a few seconds). Optionally, mark components that are sealed in `nav` at hello, so the bot knows it has to
  climb instead of sliding along the wall for a while first.
- **Real check**: a practice submission with `unstick.v2` on is the only real test of the climbing.
