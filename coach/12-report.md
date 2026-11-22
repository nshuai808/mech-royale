**Bundle ships with `drop_push.enabled: true`.** Across all 160 matches, drop-2 captures rose **16→19** and drop-3 captures **8→9**. Total deaths held at 55 and zone deaths fell **7→5**. All capture gains came in FFA. Practice captured zero in both arms.

`drops.py` raises the reach caps from 280 m to 370 m for drop 2 and 425 m for drop 3. `Bot.act` can follow a covered approach or contest one known weaker mech while keeping zone and evade priority.

**Practice baseline, alive at call / went / captured:** Drop 1 **34/15/0**, drop 2 **19/7/0**, drop 3 **7/2/0**, out of 48 matches. For drop 3, three misses were zone-related, two involved fights or nearby mechs, one was taken by a rival, and one ended in death after an earlier attempt. [Full baseline diagnosis](C:/Users/natha/Downloads/mech-royale-t5/replays/t12/baseline-practice.txt)

| 16 matches per arm, off → on | Captures D1/D2/D3 | Score | Kills/match | Alive at 300 s | Mean HP at 300 s | Deaths <30 s | Zone deaths |
|---|---|---|---|---|---|---|---|
| Practice s1 | 0/0/0 → 0/0/0 | 1.88 → 1.50 | 1.38 → 1.06 | 0 → 0 | — | 2 → 2 | 3 → 2 |
| Practice s2 | 0/0/0 → 0/0/0 | 1.81 → 1.62 | 1.19 → 1.25 | 0 → 0 | — | 1 → 1 | 1 → 0 |
| Practice s3 | 0/0/0 → 0/0/0 | 1.56 → 1.69 | 1.31 → 1.38 | 0 → 0 | — | 4 → 4 | 1 → 1 |
| FFA s1 | 5/7/4 → 5/8/6 | 11.69 → 11.62 | 1.56 → 1.62 | 1 → 3 | 1,904 → 1,736 | 4 → 4 | 1 → 1 |
| FFA s2 | 4/9/4 → 5/11/3 | 14.69 → 14.69 | 2.56 → 2.75 | 1 → 1 | 1,736 → 1,736 | 0 → 0 | 1 → 1 |

At 240 s, three practice matches per arm were still alive, with mean HP **1,065→1,250** and zero cubes in both arms. Milestone counts exclude matches won earlier. This simulator grants cubes from drops only. [Full A/B results](C:/Users/natha/Downloads/mech-royale-t5/replays/t12/drop-ab.txt)

Tests and protocol check passed. Local p99 was **8.9 ms**, fuzz found zero exceptions, and flag-off actions matched the base across **20,177** replay decisions. Docker timing remains unverified.

**`t12-drops`** · `ac398fe83fa714a206c9e5c84b07a2724cba7712` · [Verified bundle](C:/Users/natha/Downloads/mech-royale-t5/replays/t12-drops.bundle)