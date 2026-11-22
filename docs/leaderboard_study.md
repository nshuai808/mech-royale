# What the top of the Mech Royale leaderboard does (2026-11-21 study)

Board at study time: #1 tigerbyte 6.44, then about 25 teams between 6.19 and 6.42. We are #204 at 3.71.
The board does not link repositories. Repos were found through GitHub search and their READMEs.

## Who is up there, and on what code

| Rank | Team | Repo | Code |
| --- | --- | --- | --- |
| 9 | not even close | Th3r0n/mech-royale-bot | Own Rust bot. **Skipped**: the repo asks AI tools not to read or use it while the event runs. |
| 10 | giddygiddyboy | justnau/giddygiddyboy-mech-royale (now 404, binary only) | Go bot, MIT. Source mirrored in `blanc-team/try_again` |
| 17 | 2.3% | charliescull/mech-royale-bot | giddy bot for practice, own Python brain once FFA is detected |
| 22 | GMUNVIS | SuperHuyGaming/mech-royale | Same Rust code as #9 (not read, same reason) |
| 25 | Wai and Jai | waiprotein/mech-royale-bot | giddy bot plus small fixes with tests |

Others on giddy: EvanDamron, radioheadfan123, brycehcmcgrath, teetham-t. The 6.2-6.4 plateau is
mostly **one public MIT bot plus small tweaks**. Teams with their own brains score 2-4.5 (2.3%'s own
brain: 2.15 / 3.15 / 4.54), the same band as us. The gap is the giddy design, not effort.

The board keeps each team's best score, and several teams resubmit the same bot with a different RNG
"salt" to re-roll the 48 practice matches (Th3r0n's log: a dozen `salt N` commits, 2.3%'s `test_slotsalts.py`).
This buys maybe +0.2-0.3 of noise on the practice board. It does nothing for the final.

## What giddy does that we don't (ideas, not code)

Read from `mech/brain.go` (~2000 lines). Ordered by how much I think each explains the 6.3 vs 3.7 gap.

1. **It knows when it is in practice and plays a different game there.** It counts deaths it did not
   cause. If other mechs keep dying (5 ticks in a row), it is FFA. Otherwise, after 20 s, it swaps to a
   "squad" parameter set: no hiding, no peeking, always fight, laser first, loot within 150 m, crates
   always, stick to the current target, prefer targets under 30% HP, targets out to 240 m.
   *Us:* one behavior for both. Our own notes show disengaging always lost in practice (heal_gate 3.17,
   laser_flee 2.92). Giddy keeps a careful FFA mode and a pure-aggression practice mode, switched by evidence.
   This also answers our worry that practice tuning hurts the final.

2. **Laser is the main weapon in practice.** It seeks a laser up to 240 m away. Upgrades go plating,
   armor, laser_damage, laser_charge. Preferred range with laser is 120 m in practice. The hunters come
   one at a time across open ground, and a 315-damage hitscan shot at 120 m kills them before they close.
   *Us:* lightning > laser (`WEAPON_RANK`), lightning wants 45 m. Against hunters that approach, long range wins.

3. **Laser handling that never wastes a shot.**
   - Lethal early release: when a partial charge already kills (with cube bonus, x(1+cookoff) on mortar
     carriers), fire now instead of waiting for full.
   - When the target blinks out of view for a tick, keep holding the charge for up to 1 s, aimed at its
     last seen center, so the shot fires when it comes back. (Before this fix their shot went into the
     idle aim.)
   - Don't start a new charge (it halves speed) while running for cover or into the zone.
   - With a laser and no visible target, pre-charge when a known foe is in range.

4. **Short, reactive retreats instead of long hides** ("LoseRule"). "Losing" = 2+ near and HP < 55%,
   3+ near and HP < 80%, or our HP < 35% and the target healthier. Retreat lasts 1.5 s after the last
   "losing" tick, then it fights again. A target under 25% HP with at most 2 near cancels "losing".
   A "finishing" check overrides retreat when the target's HP is under one burst (a ready laser shot
   + 1.5 s of gun at 50% accuracy, with cube bonus) and at most 2 mechs are on us.

5. **Win-probability model fitted to data.** A logistic model:
   `z = 1.51*ln(myHP/theirHP) + 0.70*(cube diff)/10 + 0.96*(weapon count diff) - 0.56*(someone else on me - someone else on them)`
   plus, for an opening shot, distance and "they aren't facing me". It engages above a threshold and
   flees below one for 5 s. The coefficients look regressed from logged fights.
   *Us:* we can fit the same thing from `sim.py --record` replays (fights won/lost against those features).

6. **Fight movement by sampling, not by mode.** Each tick it scores 16 (or 32) points 6-12 m around
   itself: distance to preferred range, line of sight wanted or not (LOS wanted only when a shot is
   ready; else step behind cover = peek), seen by other enemies (-30 each), zone penalty, wall
   clearance, strafe side, and progress toward a nearby cube. One scoring function covers strafe, peek,
   cover and cube pickup in one move.

7. **Cubes mid-fight.** During a fight it walks onto cubes within 40-70 m (less when hurt), until the
   stat cap (past the cap a cube only makes you bigger). Kills drop cubes, so each kill makes the next
   one easier.

8. **Smaller things worth checking on our side:**
   - Cover search: BFS over nav cells hidden from up to 4 threats (head and mid-body rays), cost = steps + zone
     penalty, small bonus for staying close to the threats (so it can peek back).
   - If hit with nothing in view: hide from the hit bearing as if a ghost enemy were 80 m that way.
   - Shoots the NPC that hurts it. Reloads only with no threat for 3 s or below 60% mag.
   - Idle aim sweeps ±1.15 rad around the move direction to find enemies early.
   - Mortar shell landing prediction (step the arc until it hits solid) and side-step on a walkable line.
   - Home spot (FFA only): sample 40 points in the next circle, cost = exposure + distance + enemies
     near + drops near + edge; walk slowly when calm (quieter, less seen).

## What to try, in order

1. **Practice/FFA switch** using the "deaths we didn't cause" signal. In practice mode: no hide/evade
   except the short losing pulse, stick to target, finish low targets. Keep our current careful mode for FFA.
2. **Laser-first in practice**: rank laser over lightning, laser upgrades after plating/armor,
   preferred range ~120 m, the lethal-release and hold-through-flicker rules.
3. **Replace long evades with the 1.5 s losing pulse** plus the finishing override.
4. Fit the win-probability model on sim replays and use it for engage/flee.
5. Cubes mid-fight up to the stat cap.

Each one alone is testable with our flags in `params.json`, the sim, and one practice submission.
None needs giddy's code: these are rules we can write in our own `bot.py` style.
