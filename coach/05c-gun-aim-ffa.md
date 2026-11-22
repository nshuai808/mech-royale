Strong diagnosis (93% of misses into walls). Claude imported your commit, added an "on" commit (`1c37af2`) and queued it for a
real practice submission. Your branch in this worktree is now `t7-gun-aim` at `1c37af2` (flag on).

The open question is your FFA result (-0.81 / -0.88). Measurement only, no code change:
1. `--ffa` seeds 3 and 4, 16 matches each, flag off vs on (4 runs).
2. Pool with your seeds 1-2: paired mean difference and its standard error over the 64 matches.
3. From the replays, a guess at the mechanism if the loss holds: e.g. we stop firing and the target peeks first, or we lose a
   duel we used to win by suppressing, or deaths happen later/earlier. Count, don't speculate beyond the data.
Report under 12 lines.
