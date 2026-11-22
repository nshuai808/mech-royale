**Enable default 250 s prep.** It won the calibrated practice comparison with 176 kills versus 156 off, a gain of **+0.42 kills/match**.

| Practice arm, 48 matches each | Kills/match | By 150 s | By 300 s | Alive at 150 s | Alive at 300 s | Deaths <30 s |
|---|---:|---:|---:|---:|---:|---:|
| Off | 3.25 | 1.88 | 3.25 | 43/48 | 2/48 | 0 |
| Default 250 s | **3.67** | 1.92 | 3.60 | 45/48 | 3/48 | 0 |
| Prep at 120 s | 3.56 | 2.00 | 3.56 | 42/48 | 2/48 | 0 |
| Two kills or 250 s | 3.13 | 1.85 | 3.10 | 42/48 | 2/48 | 0 |

The FFA seed 1 check was weaker than the prior off run. Kills/match fell from 1.56 to 1.31, survival at 150 s from 12/16 to 11/16, and survival at 300 s from 1/16 to 0/16.

Commit `5ea165546e172fd199ffbf6b1c9d199bc73a5d09` directly atop `61f34c9` changes only `rush.enabled` in `params.json`. [Verified t9-rush-cal.bundle](C:/Users/natha/Downloads/mech-royale-t1/replays/t9-rush-cal.bundle). All seven test scripts passed, conformance passed at 8.5 ms p99, and fuzz found zero exceptions.