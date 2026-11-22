Good, clear result: drop `second_shooter` (no need to deliver the bundle again; leave the branch as is).

Your result says the trigger isn't the problem: the existing evade rules (`unseen_hit`, `evade_fix`, `_third_party`) already fire
in pile-ups, yet 2+ attacker fights still kill us. So the question is **why the escape fails**. Measurement only, no bot changes.

Use the replays you already have (`replays\t1_off\`, i.e. integ-2 as-is, practice + ffa). For every fatal gunfight, from the
trace/actions in the replay, report pooled counts for:
1. Mode in the last 6 s before death (share of ticks: fight / evade / hide / heal / loot / move / other), and the mode at the moment
   of the first hit from the 2nd attacker.
2. Time from the 2nd attacker's first hit to death, and whether we were already in `evade` when it came.
3. In evade: did the bot reach its chosen cover point? distance to cover when evade started vs at death; was the path blocked/stuck
   (moved < 2 m in a 1.5 s window)?
4. Were we hit in the rear (rear-hit x1.5) during evade, and what share of the fatal damage was rear?
5. HP at the 2nd attacker's first hit.
Then 3 lines: the single biggest failure pattern, its count, and the change you'd build for it (one flag, which function).

Report under 25 lines. If a field can't be read from the replays, say so instead of guessing.
