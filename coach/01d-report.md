**Keep `late` off.** Enabling it lowered score by 0.25 on both seeds, despite two fewer zone deaths overall. No commit or bundle was created.

Four 16-match runs used `--ffa --ffa-shy 0.6 --ffa-calm 0.0` after calibration at `0.1` fell short. At `0.0`, house-vs-house gun damage is zero and 35 of 64 measured matches passed 300 s.

| Arm | Seed | Score | Top 4 | Wins | Median / mean survival | Zone deaths | `late` activated |
|---|---|---:|---:|---:|---:|---:|---:|
| Off | 1 | 8.69 | 31.3% | 2 | 326.3 / 282.3 s | 3 | 0% |
| On | 1 | 8.44 | 43.8% | 3 | 324.0 / 282.7 s | 2 | 62.5% |
| Off | 2 | 6.81 | 31.3% | 3 | 306.2 / 253.6 s | 5 | 0% |
| On | 2 | 6.56 | 18.8% | 0 | 303.2 / 249.0 s | 4 | 50.0% |
| Off | Pooled | 7.75 | 31.3% | 5 | 323.7 / 267.9 s | 8 | 0% |
| On | Pooled | 7.50 | 31.3% | 3 | 319.8 / 265.9 s | 6 | 56.3% |