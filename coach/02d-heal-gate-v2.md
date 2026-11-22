Stop the 0.85 work (Claude killed that run; the worktree is reset to `585b8e8`). New finding changes the plan.

**Real practice score of `585b8e8` (heal_gate 0.70): 3.17**, vs 3.44 for integ-2. The sim said +0.53; the real game says -0.27.
Likely cause: the `elif healing:` branch sits above the drop / loot / cube / crate / move branches in `act()`, so below 70% HP the
bot only evades or stands still. The real game's score depends on loot and power farming (cubes, weapons, crates, supply drops),
which the sim doesn't model, so the sim only saw the upside.

## Build heal_gate v2 (same flag, new key `heal_gate.scope`: "all" = current behaviour, "fights" = new default)
With `scope: "fights"`, while healing:
- keep: `_choose_target` skips mechs that aren't shooting us, and skips NPC farming (both deal/take damage, which blocks regen);
- keep: if a known enemy is visible (LOS), evade to break LOS (your current branch);
- **change: if no known enemy is visible, don't hold: fall through to the normal drop / loot / cube / crate / move chain**, except
  crate shooting (dealing damage resets the regen timer: skip `crate` targets while healing).
`enabled: false` must still equal integ-2 exactly; `scope: "all"` must equal `585b8e8`.

## Measure
practice s1, s2 and `--ffa` s1, s2, 16 matches, `--record`, fights.py (archive to `replays\t2_v2\`). Compare to Task 0 (off) and
to your 0.70 "all" runs. The sim can't show the loot benefit, so the bar here is only: **not clearly worse than "all"** in the sim.
Then tests, check, fuzz.

## Deliver
Commit on top of `585b8e8`, then a bundle as before: `replays\t2-heal-gate-v2.bundle` (branch `t2-heal-gate`).

## Report (under 20 lines)
Commit hash; functions changed; table: off / all / fights for the four runs (score, kills/match, deaths<30s); verdict.
