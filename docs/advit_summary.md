# Advit's session: everything in one page (Sat-Sun 2026-11-21/22)

Branch `claude/nifty-galileo-lw5l5t`. Details: `docs/trials_nifty_galileo.md` (Python era), `docs/PARTNER_BRIEF.md`
section 6 (giddy era), README Submissions log (every score).

## 1. The facts we measured (real practice submissions)

| What | Result | Meaning |
| --- | --- | --- |
| Pacifist probe (`8ffc0c2`, Python bot) | 0.08 | Practice points are **only our kills**. Hiding never survives; the endgame is worth nothing in practice. |
| giddy, no shots after 300 s (`27392a9`) | 5.73, identical | giddy is **dead before 300 s in all 48 matches**. |
| giddy, no shots after 150 s (`5001814`) | 4.58 | giddy kills **4.58 by 150 s, 1.15 in 150-300 s**, then dies. The gap to the top is the mid game. |
| giddy, `CrowdHide = false` (`c3e2d53`) | 5.73, identical | giddy is never "swamped" (3+ foes in view): it loses **mid-game 1v1s against the stronger hunters**, not crowds. |
| Nathanael: cube cap 21 / 45 | 5.73, identical | giddy never reaches 10 cubes in practice. |

**Identical score = no decision changed in any of the 48 matches** (the scorer is deterministic per commit).
Any change that does alter behavior reshuffles every fight: noise is then about ±0.25 per submission.

## 2. What we tried on giddy (practice `squadParams` unless noted)

| Commit | Change | Real |
| --- | --- | --- |
| `515bce5` | unchanged giddy (base) | **5.73** |
| `d983a4c` | upgrade order laser_damage, laser_charge before plating, armor (on `robust`) | 5.75 (neutral) |
| `d5dffcc` | `EngageDist = 90` | 5.67 (neutral) |
| `6a7c88e` | `NoMortar = false` | 5.52 |
| `c5fdfc3` | `LaserHold`: hold the laser charge through a brief loss of the target (real bug fix) | 5.69 |
| `79eb097` | `BodyLoot`: walk to each kill's body when clear (its cubes + 2) | 5.42 |
| `96a804f` | `AllFoes = true` (sim +0.40) | 5.67 |
| `b35b174` | `UseDrops` + `NanoUp` + `Explore` + `CubeGoal 15` | 5.40 |
| Nathanael `s-all` / `s-no-explore` / `s-econ-fight` | Econ, Explore, FightLoot, NanoUp combinations | 5.25 / 5.10 / 5.10 |

**Pattern:** more looting / exploring / drops lowers giddy (more exposure). Its practice settings are close to their best;
single flags are neutral or worse. On the Python bot the same rule held: anything that disengages, fires less or walks
into the open lost.

## 3. Sim sweep of giddy's practice combat settings (house-bot sim, gun only)

26 one-line variants, 24-48 matches each, compared match by match with unchanged giddy.

- **Inert** (identical or nearly identical matches): RetreatHP 0.25/0.5, RecoverHP 0.6/0.95, LowBonus 0/250, MaxTarget 300,
  Dodge off, EarlyHide 20, HPw 0, Pursue 0.3. These code paths almost never run in practice.
- **Worse:** Peek on (-0.42), GunRange 110 (-0.33) and 60 (-0.25), FinishHP 0.45 (-0.29), EngageDist 40 (-0.17).
- **Better in the sim:** `AllFoes = true` **+0.40** (two seed pairs agree: +0.42, +0.38; kills 1.48 vs 1.19, same life),
  `EngageDist = 90` +0.33, which then scored 5.67 real (didn't transfer).
- `96a804f` = robust + `AllFoes = true` scored **5.67** real: didn't transfer either. **The house-bot sim can't pick giddy combat flags.**

## 4. Tools built (all on the branch; none are in the bot image)

| Tool | What |
| --- | --- |
| `tools/sim.py --clones N --clone-cmd BIN [--ffa]` | **Clone arena**: N opponents are real bot processes. ~6 s/match with 16 giddy. giddy vs 15 giddy = 5.96 ± 0.97 (identical bots should be 7.5). |
| `tools/sim.py` drops, `--first`, `--ffa` | Supply drops with rival house bots; rerun one match; free-for-all house bots (merged to main earlier). |
| `tools/feed_record.py` | Records the public spectator feed `wss://watch.joinbuilders.org/live` (showdowns = the final's format), one gzip per match. Works from the cloud session through `HTTPS_PROXY`. **Recording now.** |
| `tools/feed_analyze.py FILES` | Per-bot table: points, kills, damage, cubes (max, at 60/150 s), max HP, first weapon time, early deaths, roof %, air %, drops; points by loadout; correlations; first upgrades. |

## 5. Outside observations (not ours)

- Track designer (Watch chat): practice bots are "nerfed"; her best honest score 6.75; "seeds are visible to bots" (a
  fixed-seed exploit, 9.7; not pursued).
- Other teams' notes (mh-anwar, CyberCoder-bit; read, not run): in showdowns cubes predict points (+0.65), gun+laser
  averages 9.0 pts vs gun+lightning 6.3, gun only 4.5; top bots break off fights at ~87-91 % HP and take armor/plating/
  nanites first; ~32 % of bots die in the first 60 s. House bots hit 51 % gun / 28 % laser, react in 1.6 s, are airborne 27 %.
- The site's one served replay (`/replays/mechanics-v2-16.jsonl.gz`) is a house-bot match: types expert, hard, medium,
  brawler, sniper, thirdparty, farmer; they spend 14-28 % of the time on roofs and 21-37 % in the air (why roof camping lost).

## 6. Where the +1 is, and what's next

- The practice gap is **mid-game duels (150-300 s) against stronger hunters**. No single giddy flag has moved it.
- Next: (1) done: AllFoes 5.67; (2) analyze recorded showdowns for the final (how giddy copies die,
  what top bots do differently), and rank final candidates in the clone arena; (3) if a duel change is tried, make it
  a code change in giddy's fight logic (laser hold / peek timing against strong hunters), not another flag.
- The final entry should be a giddy build that is at least as good as 5.73 in practice (practice-only flags can't hurt
  the final: giddy switches to its FFA settings when it sees another bot die).
