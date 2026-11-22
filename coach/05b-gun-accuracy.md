Great work: evade_unstick scored **3.71** in real practice (best ever) and is now the base `integ-3` = this worktree's HEAD
`6bb23c4` (flag on). Keep working on this branch, but create a new branch `t7-gun-aim` from HEAD for this task.

Lesson from the real scores so far: changes that make the bot disengage more lost; changes that make it **execute better** won.
Next "execute better" target: **gun accuracy** (everyone's starting weapon; most early duels are gun-only, and the sim models guns).

## Step 1: measure (short)
From recorded practice s1, s2 and ffa s1 (16 matches each, `--record`): our gun hit rate (bullets that hit a mech / bullets fired),
split by target distance (0-40, 40-80, 80-130, 130+ m) and by target moving vs still; and for misses, the miss distance and whether
it was ahead/behind the target's motion (lead error) or random spread. Read `tools/sim.py` to see how the sim models spread and
bullet speed, and `kit/protocol.md` for the real gun, and say if the sim differs from the protocol.

## Step 2: build one fix for the biggest error (flag `gun_aim`, `enabled`; off = exactly integ-3)
Typical options, pick what the data supports: better lead (target acceleration / strafe reversal, latency of one tick), don't fire
beyond the range where hit rate is very low (saves ammo and reload time), burst timing vs spread, aim at the cylinder centre height.
Touch only the gun aim/fire code in `_engage` (or a helper it calls).

## Measure
practice s1, s2 and `--ffa` s1, s2, 16 matches, off vs on (run the off arm yourself on integ-3; don't reuse Task 0 numbers, the base
changed). Report hit rate off/on, score, kills/match, deaths<30s. Tests, check, fuzz. Deliver as a bundle
`replays\t7-gun-aim.bundle` with the flag **on** if it wins (score and kills up on both practice seeds, FFA not worse), else off.

Report under 25 lines.
