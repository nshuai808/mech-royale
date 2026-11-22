I found 16 off-arm replays, all from practice seed 1. All 16 ended in gun deaths. The other practice seed and both FFA off-arm replay sets are missing from `replays/t1_off`, so these counts cover practice seed 1 only.

| Measurement | Pooled result |
|---|---|
| Mode in the final 6 s, 960 ticks | Evade 478 (49.8%), fight 69 (7.2%), hide 21 (2.2%), heal 29 (3.0%), loot 0, move 0, other 363 (37.8%, almost all `zone`). |
| Mode when the second attacker first hit | 13 fights had a recorded second attacker. At impact, 6 were in `zone`, 4 already in `evade`, and 3 in `fight`, using the preceding decision. The first response was `evade` in 8 and `zone` in 5. |
| Second hit to death | Median 8.5 s, range 0.4–18.1 s, measured from the observation that reported the hit. |
| HP immediately before that hit | Median 67.9% of max, range 11.1–96.8%, reconstructed from the observation and its damage events. |
| Cover and movement | 9 fights used evade in the final 6 s. All 9 logged `to cover`, and 4 also logged `in cover`. Five moved under 2 m in a continuous 1.5 s evade window while commanding movement. The trace gives no cover coordinates, so start/death distances and physical blockage are unverified. |
| Rear hits | 5 of the 9 late evaders took a recorded rear hit during evade in the final 6 s. Across the full fatal fights, rear hits accounted for 25.6% of recorded gun damage overall and 27.1% during evade. The simulator omits the lethal hit from the replay, so the exact share including that hit is unknown. |

**Biggest failure pattern:** The zone run took priority over cover while the bot was still inside the circle.  
**Count:** 6 of 16 deaths ended in `zone` with reason `late`, including 5 of the 13 multi-attacker deaths.  
**Next experiment:** Add `zone_cover_detour` in `Bot.act` to allow a brief cover detour under fire while still inside the circle and with time to reach the next circle.