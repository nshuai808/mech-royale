**Keep `rush` off.** None of the 144 practice matches reached 300 s, so neither variant added rush kills. Pooled practice score fell from 1.90 off to 1.56 with default prep and 1.69 with earlier prep. The simulator did not reproduce the real five-minute rush.

[Verified t9-rush.bundle](C:/Users/natha/Downloads/mech-royale-t1/replays/t9-rush.bundle) contains commit `61f34c9a6f4cf9d732190e80a2fbfe17f9bb8045` directly atop `6bb23c4`. Committed in a workspace-local clone. Nothing was pushed.

`Bot.act`, `_rush_order`, and `_rush_position` implement prep and hold with zone priority and normal weapon engagement. `late.py` shares its 16-ray scorer. Default prep is 250 s, hold is 290 s, and flee HP is 25%. The retry used 220 s prep and double openness weight.

Each cell shows **score · kills/match · kills after 300 s · alive at 300/360 s · deaths before 30 s**. Each run had 16 matches.

| Run | Off | Default | Earlier prep |
|---|---|---|---|
| Practice 1 | 1.94 · 1.44 · 0 · 0%/0% · 2 | 1.50 · 1.12 · 0 · 0%/0% · 2 | 1.56 · 1.19 · 0 · 0%/0% · 2 |
| Practice 2 | 1.75 · 1.25 · 0 · 0%/0% · 1 | 1.62 · 1.25 · 0 · 0%/0% · 1 | 1.88 · 1.44 · 0 · 0%/0% · 1 |
| Practice 3 | 2.00 · 1.56 · 0 · 0%/0% · 4 | 1.56 · 1.31 · 0 · 0%/0% · 4 | 1.62 · 1.38 · 0 · 0%/0% · 4 |
| FFA 1 | 11.62 · 1.56 · 0 · 6.25%/6.25% · 4 | 11.69 · 1.56 · 0 · 0%/0% · 4 | 11.44 · 1.62 · 0 · 0%/0% · 4 |
| FFA 2 | 14.69 · 2.50 · 0 · 6.25%/0% · 0 | 14.75 · 2.56 · 1* · 18.75%/0% · 0 | 14.69 · 2.38 · 0 · 18.75%/0% · 0 |

\* One additional terminal kill could not be placed strictly after the 300 s boundary. Survival counts require the match to reach the stated time.

All seven test scripts passed, conformance passed at 8.5 ms p99, and fuzz found zero exceptions. An enabled smoke check verified stationary firing and zone priority.