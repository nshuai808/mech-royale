# FFA check of the aggression switch (Session B)

2026-11-21. Measurement only, no bot code changed. Raw output is in `docs/ffa_runs/*.txt`; `docs/ffa_runs/summarize.py` rebuilds the table.

## Verdict
**Drop the aggression switch for the final** (`params.json` `aggro.enabled: false`). In the FFA sim it costs about **2 points per match**
(paired -2.00 +- 0.64 on 48 matches), a 3-s.e. effect that has the same sign on both seed sets. It gets more kills (2.3 vs 1.7)
but survives much less (mean 132 s vs 182 s) and wins far less often (18 vs 29 of 48). With the flag off, `ac6e281` plays the same
as `ea37402` (paired +0.04 +- 0.04), so turning it off is a safe return to known behavior.

## Setup
- `python tools/sim.py --ffa --matches 24 --seed N`, N = 1 and 2 (seeds 1000-1023 and 2000-2023), sim.py from `main` (`8eb5828`).
- Variants, each in its own detached worktree:
  - **ea**: `ea37402` (no aggression code, 3.56 real practice)
  - **on**: `ac6e281`, current `main` bot (`aggro.enabled: true`, 3.6 real practice)
  - **off**: `ac6e281` with `aggro.enabled: false`
- Same seeds for every variant, so the comparisons are paired match by match.
- No late answers and no stderr in any run.

## Results (24 matches per seed set, 48 per variant)

Score = mean of `16 - place` (max 15). "Survived" = last mech alive (a win: the sim ends the match there). "Top 4" = place <= 4.

| Variant | Seeds | Score | Kills/match | Mean time alive | Median time alive | Dead < 30 s | Wins | Top 4 | Zone deaths | Drops taken |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ea | s1 | 10.83 +- 1.23 | 1.50 | 167 s | 206 s | 25% | 13 | 16 | 2 | 18 |
| ea | s2 | 13.29 +- 0.70 | 1.83 | 193 s | 215 s | 8% | 15 | 21 | 3 | 17 |
| **ea** | **all** | **12.06 +- 0.72** | 1.67 | 180 s | 211 s | 17% | 28 | 37 | 5 | 35 |
| off | s1 | 10.92 +- 1.24 | 1.54 | 170 s | 206 s | 25% | 14 | 16 | 2 | 21 |
| off | s2 | 13.29 +- 0.70 | 1.83 | 194 s | 213 s | 8% | 15 | 21 | 3 | 18 |
| **off** | **all** | **12.10 +- 0.72** | 1.69 | 182 s | 211 s | 17% | 29 | 37 | 5 | 39 |
| on | s1 | 9.88 +- 1.13 | 2.25 | 133 s | 101 s | 25% | 9 | 11 | 2 | 13 |
| on | s2 | 10.33 +- 1.01 | 2.38 | 132 s | 112 s | 25% | 9 | 12 | 3 | 12 |
| **on** | **all** | **10.10 +- 0.75** | 2.31 | 132 s | 101 s | 25% | 18 | 23 | 5 | 25 |

Paired differences (same seed, per match, 48 matches):

| Comparison | Mean diff | s.e. |
| --- | --- | --- |
| on - ea | -1.96 | 0.64 |
| on - off | -2.00 | 0.64 |
| off - ea | +0.04 | 0.04 |

Notes:
- The loss comes from both ends. "on" has more early deaths on s2 (25% vs 8% under 30 s), and it dies much earlier in the mid game
  (median ~100 s vs ~210 s). Likely cause, inferred from the code and not checked in replays: the `hunt` mode walks to the
  last-known enemy, and the 230 m fight range starts long duels, both of which expose us to third mechs.
- The early-death share is 25% on s1 for every variant: the spawn duel problem (Session A) is not about aggression.
- Kills go up with aggression, which is why practice (which pays only for kills) rewards it and FFA does not.

## How far to trust `--ffa`
`_house_ffa` (tools/sim.py): each house bot shoots the **nearest mech it can see**, strafes at 35-70 m, otherwise roams inside the
next circle and moves in before the shrink. Gun only, aim noise by skill tier (easy to expert).

What it gets right for this question:
- Everyone is an enemy, so third parties are real: a mech that chases into the open gets shot by whoever else sees it. That is
  exactly what aggression risks, and exactly what the final has.
- Vision, LOS, cover, regen, zone and placement are the same model as the practice sim, which ranked versions correctly
  against the real leaderboard before (CLAUDE.md).

What it gets wrong or leaves out:
- **House bots are simple.** No cover-seeking, no retreat, no third-party discipline, no use of sounds. They kill each other fast,
  so the lobby empties in ~200 s (real FFA lobbies of tuned bots probably last longer, with more late-game play). The
  absolute score (~12) is far too high; read only the differences.
- **No loot, cubes from kills, NPCs, specials or upgrades.** In the real game a kill drops cubes (+2), so aggression buys power
  that the sim doesn't credit. That narrows the gap but is unlikely to close 2 points: the deaths it causes are third-party deaths
  in the open, and extra HP doesn't stop those.
- House bots ignore supply drops in FFA (`_house_ffa` has no drop logic), so our drop captures are easier than in reality.
- Other teams' bots may be more aggressive or more passive than these. Against passive campers, hunting walks into their fire
  (worse for "on"). Against reckless bots, staying hidden lets them thin each other out (also worse for "on").
- 48 matches per variant, two seed sets. The s.e. on a single variant is ~0.7; the paired s.e. is ~0.64.

Overall: good enough for the **sign and rough size** of a big behavior switch like this one. Not good enough to tune thresholds.

## Recommendation
1. **For the final, ship with `aggro.enabled: false`.** It costs ~2 points per match in FFA and gains nothing we can measure there.
2. For practice, aggression's measured gain is +0.04 (3.56 to 3.6), inside the 0.2-0.3 leaderboard noise. If one commit has to
   serve both, set the flag to false: the practice loss is unproven, the FFA loss is 3 s.e.
3. A middle option for later (not tested): keep aggression only while the squad is hunting us (the "FFA mode switch" in STRATEGY.md
   Step 2), e.g. aggro on only when exactly one mech has hit us and none other is visible. Test it in `--ffa` before any use.
4. Every future candidate should get the same `--ffa` A/B (two seed sets, 24 matches each) before the freeze.

## Not verified
- Real FFA behavior of other teams' bots (unknowable before the final).
- Any effect of loot, cubes from kills or special weapons on this trade-off (the sim has none).
- Matches longer than ~5 min (few sim lobbies last that long).
