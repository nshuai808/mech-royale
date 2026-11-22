# Coach log (Claude = instructor, Codex = builder)

Newest entry at the bottom. Each entry: what I saw, what I decided, what Codex is doing next and how.
Briefs are in `coach/NN-*.md`, Codex's reports in `coach/NN-report.md`. Watch Codex live: `.\coach\watch.ps1`.

---

## Sat 16:15 ET: setup done, Task 0 running

**State**
- Base: `integ-2` at `5915f57` (your CODEX_PLAN.md + tools/fights.py). `c6c10d4` scored **3.44** in practice.
- Codex worktree: `../mech-royale-duel`, branch `step5-duel` (no code changes yet).
- Codex runs sandboxed (no network, can't push, writes only in its worktree) with a Python copied into `.pyrt/`.

**Running now: CODEX_PLAN Task 0** (brief `coach/00-measure.md`). Bot unchanged; 4 recorded sims, 16 matches each:
practice seeds 1, 2 and `--ffa` seeds 1, 2, then `tools/fights.py` on each. ETA ~30-45 min.

**What I'll decide from it**
- If most fatal fights have 2+ attackers -> **Task 1 `second_shooter`** next (break off when a second shooter joins).
- If many fatal fights start below 50% HP -> **Task 2 `heal_gate`** next (don't take new fights while hurt; regen first).
- Plan: run the second one right after the first, in its own branch/worktree, one flag each, A/B practice + `--ffa`.

**Waiting on you (no rush):** Task 3 practice submissions (one flag per submission). I'll prepare the branches; you submit.

## Sat 16:25 ET: Task 3 branches ready for you to submit (done by me, not Codex)

Each is `integ-2` (`5915f57`) with **only** that one flag turned on. check.py PASS on all four (p99 7-10 ms). Pushed.
Submit in this order (CODEX_PLAN Task 3), one per submission, and log each in README. **Keep a flag only at ~3.8+**
(baseline `integ-2` = 3.44; noise 0.2-0.3).

| Order | Branch | Full hash to submit |
| --- | --- | --- |
| 1 | `t3-weapon-ctx` | `8a2aeacac8c5acf53cefcdc5ee1c5cde66b327ae` |
| 2 | `t3-upgrade-ctx` | `99d6a09148387088fe0300b190d0f7b753483009` |
| 3 | `t3-special-guard` | `65a728e4da9be57c8e6264cff6eabccde07227cb` |
| 4 | `t3-mortar-lead` | `e139c2dbccaf39043d3a20075720fdd18eb34dec` |

All four fit in one hour (4/hour limit). Tell me the scores when you're back; a flag that clears the bar goes into the final candidate.

## Sat ~17:00 ET: Task 0 result -> Tasks 1 and 2 launched in parallel

**Task 0 (integ-2 as-is, 16 matches per run; report `coach/00-report.md`)**

| Run | Score | Kills/match | Deaths < 30 s |
| --- | --- | --- | --- |
| practice s1 | 1.19 | 1.00 | 2 |
| practice s2 | 2.00 | 1.31 | 1 |
| ffa s1 | 10.94 | 1.63 | 4 |
| ffa s2 | 13.62 | 2.63 | 1 |

- **Observation: pile-ups are the killer.** 39 fatal gunfights: **33 had 2+ attackers** (21 had 3+); only 11 started below 50% HP;
  23 started above 90% HP. So the bot loses full-HP fights by staying in after a 2nd/3rd shooter joins.
- Spawn deaths are now small (3/32 practice, 5/32 ffa under 30 s): your spawn-safety work shows.
- Odd but minor: 4 zone deaths; 2 FFA matches barely moved in the last 5 s (probably the stuck-in-pocket sim artifact: no jets in the sim).
- No late answers, check PASS p99 6.7 ms.

**Decision:** Task 1 (`second_shooter`) is the main lever. Task 2 (`heal_gate`) touches different code, the machine has 16 cores,
so both run at once.
- **Task 1** (brief `coach/01-second-shooter.md`, worktree `../mech-royale-t1`, branch `t1-second-shooter`): break off to the evade
  path at any HP when 2 mechs hit us within 2 s, or a second enemy has LOS within 150 m while we fight, unless the target dies within
  1.5 s. Replaces the old `_multi_hit`/`early_evade` rule. Off arm = Task 0 (Codex re-runs one seed to prove it's identical).
  Fallback variants if kills drop: hits-only, or 3 attackers.
- **Task 2** (brief `coach/02-heal-gate.md`, worktree `../mech-royale-t2`, branch `t2-heal-gate`): below 70% HP, no new targets that
  aren't shooting us; break LOS and regen. Variants 0.6 / 0.85.
- **Bar for keeping a flag:** practice sim not worse (kills/match within ~0.3) AND `--ffa` not worse. Then a real practice submission.

## Sat ~17:45 ET: Task 2 `heal_gate` = KEEP. Ready for a practice submission

Report `coach/02-report.md`. Below 70% HP: no new targets that aren't shooting us, break LOS and regen (`act()` + `_choose_target`, +21 lines).

| Run | Off (Task 0) | On (0.70) |
| --- | --- | --- |
| practice s1 | 1.19 / 1.00 kills | **1.81 / 1.38** |
| practice s2 | 2.00 / 1.31 | **2.44 / 1.69** |
| ffa s1 | 10.94 | **12.38** |
| ffa s2 | 13.62 | 13.12 |

- Practice +0.53 score, +0.38 kills/match (both seeds up). FFA +0.47 mean, but mixed by seed (+1.44 / -0.50): treat FFA as "not worse".
- Fatal fights starting below 50% HP: 10 -> 5 in practice.
- check PASS (p99 8.1 ms), fuzz 0, tests ok; flag off = integ-2 on all 300 kit observations.
- Observation: it **raises kills** (more fights started at full HP win), so it should show in practice, not just the final.

**For you: submit `t2-heal-gate`** = `585b8e8b116b037b9419ff97fd27b1be589d90c4` (pushed). Bar: ~3.8 (integ-2 = 3.44).
Priority: submit this one **before** the Task 3 loot flags; it has sim evidence, they have none.

Process note: Codex's sandbox can't write git's shared index (it lives in the main repo's `.git`), so it hands commits over as a
bundle (`replays/*.bundle`); I import it and push. Future briefs tell it to do that directly.

- Next on Task 2: Codex is testing `hp_frac` 0.85 vs 0.70 (brief `coach/02b-heal-gate-085.md`). The pushed 0.70 commit stays valid to submit either way.
- Fixed two wrapper bugs in `coach/codex.sh` (resume used relative paths, and resumed in a read-only sandbox). The 0.85 test is now actually running.

## Sat ~18:00 ET: Task 3 practice scores are in: none clears the bar

| Flag (branch) | Commit | Real practice score | vs integ-2 3.44 |
| --- | --- | --- | --- |
| `weapon_ctx` | `8a2aeac` | 3.60 | +0.16 |
| `upgrade_ctx` | `99d6a09` | 3.50 | +0.06 |
| `mortar_lead` | `e139c2d` | 3.48 | +0.04 |
| `special_guard` | `65a728e` | 3.42 | -0.02 |

- **Observation:** all four are inside the 0.2-0.3 leaderboard noise; none reaches ~3.8. None of them hurts either.
- **Decision:** leave all four **off** in the final candidate (plan rule: keep a flag only at ~3.8+). `weapon_ctx` is the only one
  worth a second look: if a submission slot is spare Sunday morning, test it **on top of the final candidate**, not alone.
- Loot/weapon tuning has stopped paying; the remaining gains are in fight survival (Tasks 1 and 2), as the sim said.
- **Next submission for you:** `t2-heal-gate` = `585b8e8b116b037b9419ff97fd27b1be589d90c4`.
- README's Submissions log doesn't have these four yet (it lives on `main`/`integ-2`, which I'm not committing to while you work there).

## Sat ~18:15 ET: heal_gate scored 3.17 in practice (sim said +0.53) -> heal_gate v2

- **Observation:** `585b8e8` = **3.17** vs integ-2 3.44. Sign flipped from the sim. Reading the code: the `elif healing:` branch sits
  above drop / loot / cube / crate / move, so below 70% HP the bot freezes its power farming. The sim has no loot, so it only saw the
  upside. This was visible in the code; I should have caught it before you submitted.
- Stopped the 0.85 test (moot: more freezing). Codex is now building **heal_gate v2** (brief `coach/02d-heal-gate-v2.md`): still
  no new mech fights and no NPC/crate damage while hurt, still break LOS when a threat is visible, but otherwise keep looting/moving.
- **Lesson for every flag from here:** before trusting a sim gain, check whether the change touches loot, cubes, drops, NPCs, crates
  or specials (the sim's blind spots). If it does, the sim result is upside-only.

## Sat ~19:00 ET: Task 1 `second_shooter` = DROP -> measure why escapes fail

Report `coach/01-report.md`. Paired vs Task 0: hits+LOS +0.00 practice / -0.06 ffa; hits-only -0.09 / +0.06. Several runs were
identical to flag-off: the new trigger rarely fired. Commit `1d8894a` (flag off) stays local, not pushed, not for submission.

- **Observation:** the existing evade rules (`unseen_hit`, `evade_fix`, `_third_party`) already trigger in pile-ups. So the bot isn't
  dying because it stays in; it's dying **while leaving**. The fix has to be about how it escapes, not when.
- **Next (running, measurement only, brief `coach/01b-death-anatomy.md`):** from integ-2's replays, for each fatal fight: mode in
  the last 6 s, time from 2nd attacker's first hit to death, whether cover was reached or the bot got stuck, rear-hit share, HP at
  that moment. Codex proposes one flag for the biggest pattern; I decide whether it's built.
- Wrapper note: `codex.sh` exited 2 only because I edited it mid-run; Codex's work was complete.

## Sat ~19:30 ET: why escapes fail -> building `zone_cover_detour`

Report `coach/01b-report.md` (practice seed 1 only, 16 deaths; the other replay sets had been cleared).
- **Biggest pattern: the zone run overrides cover under fire.** 6/16 deaths ended in `zone` mode, reason "late": still inside the
  circle, running across open ground while being shot instead of breaking LOS first. 5 of the 13 multi-attacker deaths.
- Second: 5 of 9 fatal escapes moved < 2 m for 1.5 s while trying to reach cover (stuck or blocked).
- Rear hits ~26% of fatal gun damage (x1.5 multiplier: facing while fleeing still matters).
- Second attacker's first hit came at median 68% HP; death followed ~8.5 s later, so there's time to act.

**Decision:** build `zone_cover_detour` (brief `coach/01c-zone-cover.md`, same worktree/branch as Task 1): when the zone wants a
non-critical run, we're inside the circle, under fire, and have >10 s of margin, take cover first (cover that doesn't move us away
from the next circle), and re-check every tick. Zone deaths must not rise. This is squarely in what the sim models (no loot effect),
and it should matter in the final too, where third parties hit you on the way to the circle.
Next after it: the "stuck while escaping" pattern, if this one pays.

## Sat ~19:45 ET: heal_gate v2 READY TO SUBMIT -> `a299738247fb9e271e80490390470bd8d1118715`

Report `coach/02d-report.md`. Sim (score/kills): practice s1 1.50/1.25, s2 2.38/1.63; ffa s1 12.25, s2 13.19.
vs flag-off: practice +0.35, ffa +0.44; vs v1 ("all"): -0.19 practice, -0.03 ffa (noise; v1 lost loot time the sim can't see).
**My code read:** hurt + no enemy in sight now falls through to the drop/loot/cube/move chain (v1 froze there); skipped while hurt:
`fight` mode, `hunt`, `hide`, the idle `heal` stand-still and crate shooting (regen reset). Still returns fire at a target shooting us.
Residual risk: a loot route can walk into unseen enemies, same as at full HP. check PASS. Pushed; in `coach/SUBMIT.md`.

- Launched **evade_unstick** (brief `coach/05-evade-stuck.md`, worktree `../mech-royale-t5`, branch `t5-evade-stuck`): diagnose the 5/9 stuck escapes, then one flagged fix in `_evade`. Runs in parallel with `zone_cover_detour` (different code).

## Sat ~20:00 ET: heal_gate v2 scored 3.29 -> heal_gate DROPPED

- v1 3.17, v2 3.29, baseline 3.44. Sim said +0.53 / +0.35. **Two misses in the same direction = the sim is wrong about disengaging
  while hurt**, not noise. Likely: real hunters punish backing off (they get the first shot or catch us mid-retreat); the sim's house
  bots shoot on sight and never push, so retreating looks free there.
- **Consequence for the two running tasks:** `zone_cover_detour` and `evade_unstick` are also "how we leave a fight" changes.
  I'll judge them more strictly: they must win in the sim on both practice seeds *and* not cost kills, and even then a real
  submission decides. Survival changes that cost kills have now failed twice in practice.
- **Open question for Nathanael:** the scorer shows "wait N ms" per submission, rising 33 -> 139 -> 185 -> 293 -> 452 ms. If that is
  the bot's worst answer time in real matches, it's way over the 50 ms budget (late = coast 1 s without firing) and could explain
  falling scores. If it's queue time, ignore. Need to know which.

## Sat ~20:30 ET: zone_cover_detour DROPPED; evade_unstick READY (`6bb23c448c329c1e413436654e5d82a9882e535f`)

**zone_cover_detour** (`coach/01c-report.md`): score within noise (15 s margin: practice +0.22, ffa -0.03), zone deaths **up** 3 -> 5-6.
It traded gun deaths for zone deaths. Dropped (commit `164b43a`, local only).

**evade_unstick** (`coach/05-report.md`): diagnosis: 11 stuck escape windows, 8 against buildings/solid contact, none used A*,
all overlapped `_unstick_v2`. Fix: `_evade_slide` turns to the nearest heading whose 7 m ray clears the mech footprint (5 rays per
heading, up to 17 headings), torso stays on the threat. Only in `evade` mode.

| Run | Off (Task 0) | On |
| --- | --- | --- |
| practice s1 | 1.19 / 1.00 kills | 1.94 / 1.44 |
| practice s2 | 2.00 / 1.31 | 1.62 / 1.06 |
| ffa s1 | 10.94 | 11.69 |
| ffa s2 | 13.62 | 14.56 (0 early deaths, 0 stuck) |

- **FFA +0.91 ± 0.58 paired**: the first change with a real FFA signal. Practice mixed (+0.19 mean).
- My code read: movement direction only, evade mode only; `self.cfg["mech"]` is guaranteed by the protocol. Codex had committed it off;
  I added the "on" commit. check PASS (p99 9.5 ms), fuzz 0. Pushed. **In `coach/SUBMIT.md` as a sanity gate** (keep unless < ~3.3).

**Direction change:** three survival ideas in a row were noise or worse in practice; practice has sat at 3.4-3.6 for ~10 versions.
From here I'm aiming at the **final (FFA)**: Codex 1 now tests the `late` hold in long FFA lobbies (`coach/01d-late-ffa.md`).

## Sat ~21:10 ET: evade_unstick scored 3.71 -> KEPT, new base `integ-3` = `6bb23c4`

- Best real score ever (previous best 3.6 with aggression on; integ-2 3.44). +0.27 is inside noise on its own, but it's the first
  change where the sim (FFA +0.91, practice +0.19) and the real score point the same way, and it can't plausibly hurt (it only
  changes direction when an escape is physically blocked). Branch `integ-3` pushed.
- **Pattern so far:** changes that make the bot *disengage more* (heal_gate x2) lose in practice; changes that make the bot
  *execute better* without changing what it chooses to do (evade_unstick) win in both. Next ideas should be of the second kind.
- Queued the free test: integ-3 + weapon_ctx = `5a31d434c2c968a023a2ed7ed76ed948c9e52f4e` (in SUBMIT.md).
- Codex 1: `late` hold in long FFA lobbies (running). Codex 5 (evade_unstick author) idle; next brief after the late result.
- Codex 5 now on **gun accuracy** (brief `coach/05b-gun-accuracy.md`, branch `t7-gun-aim` off integ-3): measure hit rate by range and lead error, then one flagged fix in the gun aim code; off arm re-run on integ-3.

## Sat ~21:30 ET: integ-3 + weapon_ctx = 3.58 -> dropped. Claude started a special-weapon logic review (sim-blind area)

## Sat ~22:00 ET: Claude's special-weapon review -> `laser_flee` READY (`e37bac5460f5180b8ac16c2b3d37a50ca3cd6401`)

Reviewed `_engage` / `_aim_and_fire` (laser, lightning, mortar) against protocol.md and the real hello config (kit stream).
- **Bug (fixed):** `_engage` holds the laser trigger whenever a target is in range, in any mode. Protocol: charging = half move speed.
  So a laser carrier fled pile-ups (evade/hide) and ran the zone at **half speed**: exactly the deaths Task 0 found. Fix: in
  evade/hide/zone, release the laser (started charge fires at >= min_charge along our aim), never start one; gun/lightning unaffected.
  Touches `_aim_and_fire` only (not the gun code Codex 5 is changing). Flag `laser_flee`. check PASS, fuzz 0, test_laser_flee ok.
- Checked, fine: max_pitch 1.3 rad (mortar arcs not clipped), lightning cone is yaw-only as the protocol says, laser release
  tolerance 0.03 rad vs ~1-2 m tracking lag (inside the 2.5 m radius), energy 3/shot vs 18/s regen.
- Minor, not changed: no laser lead (~1-2 m lag), lightning fires at targets behind walls (wastes energy), mortar never lobbed at
  unseen known enemies (bot rarely holds a mortar).
- Sim has no lasers -> **real submission is the only test.** Queued in SUBMIT.md.

## Sat ~22:20 ET: top score is over 6 -> stop tuning, measure the real game first (probe submissions)

- **Observation:** the leader is above 6 vs our 3.71. In practice score ≈ house bots that die before us ≈ our kills, so they get
  ~6 kills/match. That's structural, not tuning. Our sim scores us 1.5-2 vs 3.7 real: it can't tell us where real points come from.
- **Probe idea:** the score is our only channel out of real matches. A probe = integ-3 that never shoots mechs after time T, so its
  score = our kills before T. Built and pushed: probe-150 `deaaa12ebc4d10a9a6e35599ea1ea287227118a4`, probe-300
  `a7b621c8678c5a15c4a3e671debf611c94f7f435` (check PASS, fuzz 0). Never ship these.
- **How I'll read it** (with integ-3 = 3.71 total):
  - kills(150) high, little after -> we die early/mid: the lever is surviving (rush at ~5 min, positioning, roofs/jets, drops HP).
  - steady growth to 3.71 -> kill speed is the lever: ambush each arriving hunter, better specials.
  - kills(300) << 3.71 -> late game matters: we already survive the rush sometimes; push the endgame (cubes, late hold).
- Then pick ONE big change for Codex(es) and me, and spend the remaining submissions on it.

## Sat ~22:35 ET: laser_flee scored 2.92 (-0.79 vs 3.71) -> DROPPED

- Far outside noise. The bot gets many of its kills with the laser **while in hide/evade/zone** (shooting while repositioning);
  forcing early release cut those shots from 315 to ~110 damage and added 1.65 s cooldowns.
- **Firm pattern now:** "be more careful / disengage / prioritize escape" lost 3 times in real practice (heal_gate v1 3.17, v2 3.29,
  laser_flee 2.92). "Execute better without giving up damage" won once (evade_unstick 3.71). Practice pays for damage dealt.
- Probes (150 s, 300 s) still queued first in SUBMIT.md; they decide the big change.

## Sat ~22:45 ET: `late` hold in long FFA lobbies -> keep OFF

Report `coach/01d-report.md`. Long-lobby setting `--ffa --ffa-shy 0.6 --ffa-calm 0.0` (35/64 matches past 300 s).
late on vs off: score -0.25 on both seeds (pooled 7.50 vs 7.75), top-4 equal (31%), wins 3 vs 5, zone deaths 6 vs 8.
Late mode did activate (56% of matches), so this is a real negative, not "never ran". `late` stays off.
Codex 1 is idle; next brief waits for the probe scores (they decide the big change).

## Sat ~22:55 ET: PROBE RESULTS -> the big change is the 5-minute rush

| Window | Real kills | Rate |
| --- | --- | --- |
| 0-150 s | 2.33 | 0.93/min |
| 150-300 s | 1.36 | 0.54/min |
| after 300 s | 0.02 | ~0 |

- **We score nothing after 300 s**: the whole remaining squad (~11) comes at once and we die without killing. Kill rate also halves
  in 150-300 s (stronger hunters, sometimes 2 at once). To reach 6 we need ~+2.5 kills: the rush (worth ~0 today) is the obvious
  place, and a converging pack is ideal for lightning chains and mortar splash.
- Sim models the rush (`_hunters`: all house bots hunt after 300 s), gun-only.
- **Codex 1 -> rush defense** (brief `coach/09-rush.md`, branch `t9-rush` off integ-3): from 250 s regen + take a defensive spot
  (walls behind/sides, short lane in front, reuse late.py openness), hold and fight from it during the rush, no fleeing into the open.
  Metric: kills after 300 s and share alive at 300/360 s.
- **Claude -> rush firepower** (sim-blind, logic): aim lightning to maximise chain hits; mortar at clusters.
- `late` (Codex 1's previous task): keep off; -0.25 in long FFA lobbies.

## Sat ~23:15 ET: Claude's rush-firepower change: `lt_energy` READY (`26695519a7c2b774ecff2287218646f2fafa9646`)

- Arithmetic: lightning = 3 energy per 60-damage shot (240 dps, chains 2 more within 14 m) -> 20 damage per energy point. Boost burns
  17 energy/s = ~340 lightning damage per second. The bot boosted in evade whenever 2+ enemies were exposed (the pile-ups) and when
  closing in from > 60 m, so the lightning ran dry in the fights where it matters most, and especially in the rush.
- Change: holding lightning + enemy < 50 m -> no boost in evade/hide (in zone); fight close-in boost only at energy >= 70. Zone runs,
  drop runs, jets unchanged. Flag `lt_energy`. check PASS, fuzz 0. In SUBMIT.md (keep >= 3.8, drop < 3.5).
- Chain-aware lightning aiming is the next firepower idea, held until this one is scored (one change per submission).

## Sat ~23:40 ET: gun_aim READY (`1c37af2d750d59661e26368e9fee5e1a4102fdfd`), queued 2nd

Report `coach/05b-report.md`. Diagnosis: 60% of shots hit a mech; of 2,171 misses, **2,014 hit walls** (we fire at targets behind
cover); lead/spread errors minor. Fix: hold gun fire when both the current and predicted bullet paths are building-blocked.
Practice sim: score 1.62->2.00 and 1.75->2.31, kills +0.37/+0.50, hit rate ~58% -> ~87%. FFA sim: 11.69->10.88, 14.69->13.81
(same sign, each < 1 s.e.). My code read: `los` = buildings only, trees ignored (matches "trees don't stop shots"); roof/jet shots
kept. Codex had shipped it off for the FFA rule; I added the "on" commit for a real practice test, and Codex 5 is re-running FFA
on seeds 3-4 to see whether the loss is real (`coach/05c-gun-aim-ffa.md`). Decision for the final waits on that.

## Sat ~23:55 ET: gun_aim = 3.33 -> dropped. New big-picture plan in `coach/RUSH_PLAN.md` (power build-up -> fortress -> rush)

## Sun ~00:30 ET: switching to big batched swings. BIG SWING 1 READY: `t11-power` = `5d196e3789a1e0329141eafe8e2b7476558401f5`

You asked for bigger swings per submission. Each candidate now bundles one whole phase of `coach/RUSH_PLAN.md`; every part keeps
its own flag so a flop can be bisected in 1-2 submissions.
- **Swing 1 (power), mine, ready:** integ-3 + lt_energy + `rush_build` (upgrade order plating > armor > lightning_chain >
  lightning_efficiency > laser_pierce > nanites > ...) + `cube_cap` (no loose cubes past 10: no stat gain, +5% size each) +
  `farm_plus` (NPC drones, 2 cubes each, to 220 m until 270 s; was 150 m / 240 s) + `lt_chain` (lightning aims at the enemy with
  the most neighbours within 14 m). Real upgrade list read from the hello config. check PASS, fuzz 0, test_power ok.
- **Swing 2 (rush), next:** swing 1 + Codex 1's rush fortress (+ Codex 5's drop capture if ready). Built as soon as Codex 1 reports.
- Codex 5 -> **supply drops** (brief `coach/12-drops.md`, branch `t12-drops` on top of swing 1): measure captures of drops 1-3 and push harder for drops 2-3 (drop 3 lands ~235 s = full HP/energy before the rush). Goes into swing 2 with the rush fortress.

## Sun ~00:45 ET: swing 1 = 3.65 (neutral) -> keep as base for swing 2

- -0.06 vs integ-3: noise. Expected-ish: rush_build / cube_cap / lt_chain only pay inside the rush, where we score 0 today.
  (lt_energy alone was never scored separately; the swing contains it.)
- Swing 2 = swing 1 + rush fortress (Codex 1) + drop push (Codex 5). **That's the real test of the rush plan.** If swing 2 is also
  flat, the rush-prep idea is wrong; then bisect and rethink (e.g. kill pace before 300 s instead).

## Sat ~19:45 ET (real time; earlier entry times drifted ahead): sim calibration

- Found by both Codex runs: **the practice sim never reaches the rush.** Codex 1: fortress never activated in 48 matches (dead before
  250 s every time). Codex 5: 7/48 alive at drop 3's call, 0 drops captured. Real play keeps killing to ~300 s. So rush/drop changes
  would read "no effect" in the current sim regardless of merit.
- Fix (mine, branch `sim-calib`): opt-in flags `--aim-mult` (house aim noise x M) and `--calm-watchers` (only current hunters, or
  bots we just hit, shoot us). **Defaults verified identical** to the original sim (same match lines on seed 1), so no earlier result
  changes. Sim now prints `TIMELINE` (kills by 150 s / 300 s, alive at 150/300 s) to match against the real probes.
- Calibration target = real timeline (2.33 / 3.69 / 3.71), not just the score. Sweep running (aim x1.5/2.5/4, with/without calm).
  Calibrated-sim numbers will be labelled as such and never mixed with old sim numbers.

## Sat ~20:15 ET: calibrated sim + parallel runner; Codex 1 and 5 re-testing in it

**Calibration sweep (seed 1, 16 matches, kills timeline vs real probes 2.33 / 3.69 / 3.71):**
original sim ~0.5/0.5 (alive at 300 s 0/4) | aim x2.5 1.88/2.69 | **aim x4 2.12/3.31, alive at 150 s 15/16, at 300 s 1/16** |
aim x4 + calm-watchers 1.81/3.38. -> use `--aim-mult 4`. Judge kills/survival only: calibrated scores run 2-3 above kills
because sim house bots die in the zone, which real probes rule out.
**Key insight from the sim code:** `_hunters` = 1 + kills so far. After 3 kills, 4 hunters at once. The "rush" builds through
150-300 s (matches Task 0's pile-ups and the halved real kill rate after 150 s); at real-like strength we're usually dead before
300 s. So the fortress must start much earlier than 250 s.
**Speed:** `tools/simpar.py` shards matches across processes; identical match lines to sim.py, ~5x faster (8 jobs).
Both on branch `sim-calib` (pushed), defaults of sim.py unchanged (verified identical).
**Uncalibrated results (superseded):** rush 0/144 reached 300 s, FFA neutral; drop_push 0 practice captures, FFA D2 16->19, D3 8->9,
zone deaths 7->5. Both now re-testing calibrated: Codex 1 rush with prep at 250 s / 120 s / at 2 kills (`coach/09b-...`),
Codex 5 drops (`coach/12b-...`).
- Seed-2 confirmation of aim x4: kills by 150 s 1.88, by 300 s 3.44, total 3.62; alive at 150 s 15/16, at 300 s 2/16 (real: 2.33 / 3.69 / 3.71). Calibration holds on a second seed set. Deaths mostly to the later, harder hunters (#9-#14).

## Sat ~20:10 ET: swing 3 (hunter-killer) handed off to another session

Different direction from swing 2: kill faster while hunters are weak and alone, instead of surviving the build-up. Aggression
(best practice record before integ-3, but -2.0 in FFA sim) switched on only while <= 1 mech hit us in 20 s and <= 1 is in sight.
WIP branch `t13-hunter` = `a39d7a3` (on t11-power, untested). Handoff brief: **`coach/SWING3_HUNTER.md`**. I no longer edit it.

## Sat ~20:10 ET: swing 2 pre-stacked to save time

Branch `swing2` (pushed) = swing 1 (`t11-power`) + Codex 5's drop push (`ac398fe`, on) + Codex 1's fortress (`61f34c9` cherry-picked,
**off** for now). Clean merge. Code read: the fortress keeps full firepower (still `_aim_and_fire` on its target, swaps to a visible
attacker), sits above evade by design (no fleeing into the open; leaves only < 25% HP or for the zone). Gates pass with the
fortress off and on (prep 120 s): tests ok, check PASS, fuzz 0 (worst ~18 ms under full machine load).
When Codex 1/5 report, I only set the winning params (fortress prep timing on/off, drop push on/off), commit, push, queue.

## Sat ~20:20 ET: drop_push (calibrated) -> OFF in swing 2

Captures 9 -> 6 (D3 2 -> 1), kills 3.52 -> 3.58/match (noise), alive at 240 s 16 -> 15 of 48, HP at 240 s 1072 -> 951.
Observation: at real-like strength only ~1/3 of matches are alive at 240 s, so drop 3 rarely matters. Swing 2 now waits only on
Codex 1's fortress result.

## Sat ~20:30 ET: swing 3 (hunter-killer) early result, calibrated sim (from the swing 3 session)

Branch `t13-hunter` = `66e35891a6e33c51f131beadd3e6703a190f49e2` (pushed). On top of `a39d7a3`: 5 s off-hold hysteresis on the hunted
switch (`aggro.off_hold_s`; a traced match shows no flapping, 12 switches in 250 s), plus two flagged ideas, **off**: `chase_r` /
`chase_until_s` (hunt limits) and `meet_s` (walk toward the last sighting). Gates pass (tests ok, check PASS, fuzz 0, local replay
p99 8.3 ms under full load). No Docker on this machine, so the sandbox timing check is still open.

Calibrated practice (`--aim-mult 4`), 16 matches per cell, kills by 150 s / total / alive at 150 s:

| seed | off (= t11-power) | hunted (20 s window) | always-on aggro |
| --- | --- | --- | --- |
| 1 | 1.81 / 3.00 / 15 | 2.94 / **4.69** / 14 | 3.81 / 4.94 / 7 |
| 2 | 1.94 / 3.88 / 14 | 2.62 / **4.00** / 15 | 4.62 / 5.06 / 5 |
| 3 | 1.88 / 3.50 / 15 | 2.38 / **4.56** / 14 | (running) |
| pooled | 1.88 / 3.46 | 2.65 / **4.42 (+0.96)** | 4.22 / 5.00 (2 seeds) |

- Hunted beats off on every seed, +0.96 kills/match pooled (bar was +0.3), with no loss in alive at 150 s. Always-on gets more kills
  but dies early (12/32 alive at 150 s), and it was -2.0 in the FFA sim before.
- **Not done yet:** FFA seeds 1-2 for all three arms (the hunted switch must not lose in FFA). No SUBMIT.md row until then.
- Queued after: `window_s` 10 (practice x3 + FFA x2), chase limits (x3), meet (x1 probe). Meet never fired in a test match: every
  quiet stretch came < 20 s after two mechs hit us, so aggro was still off.
- For swing 2: swing 3 is a bigger sim effect than either swing 2 piece. The fortress sits above evade and is defensive, so the two
  will need a deliberate merge (e.g. fortress only after the hunted switch goes off for good, ~5 min), not a blind stack.

## Sat ~20:35 ET: SWING 2 READY -> `b1ecbf2ca61b0315ace3b1ae7ed770ed02b43254`

Codex 1 calibrated fortress (48 matches/arm): off 3.25 kills/match | **prep 250 s 3.67 (+0.42)** | prep 120 s 3.56 | at 2nd kill 3.13.
Alive at 300 s barely moves (2 -> 3 of 48); the gain is kills between 150 and 300 s (3.25 -> 3.60 by 300 s). FFA seed 1: kills
1.56 -> 1.31 (one seed, within noise). Swing 2 = swing 1 + fortress 250 s on + drop_push off. check PASS (p99 9.3), fuzz 0. Queued.

## Sat ~20:45 ET: swing 2 = 3.46 -> not promoted. integ-3 (3.71) stays the base and fallback final entry

- Seven real results since 3.6 sit in 3.29-3.71, including both big swings (3.65, 3.46). The scorer is deterministic per commit,
  but any change reshuffles the 48 fights by ~±0.25, and the sim (even calibrated) hasn't predicted which ±0.3 change holds.
- Only large real effects are trustworthy: disengaging / giving up damage lost hard (laser_flee -0.79, heal_gate ~-0.4).
- Not bisecting swing 2: it would re-measure swing 1 (3.65) inside the noise.
- Plan: integ-3 = fallback final (aggro off: FFA sim +2.0; evade_unstick: FFA sim +0.91, 3.71 real). Swing 3 (hunter-killer, other
  session) is the best remaining bet: only direction with a real positive (aggro 3.6). Codex 1/5 idle pending a direction.

## Sat ~20:55 ET: swing 4 "damage-max" (offensive) launched on integ-3

Complements swing 3 (when to be aggressive) by ending fights faster, the one direction real results support.
- **Codex 1 -> finisher** (`coach/14-finisher.md`, branch `t14-finisher`): focus the soonest kill, lock targets < 35% HP, chase a
  fleeing low-HP hunter for up to 6 s, don't let evade abort a nearly-won fight. Calibrated sim (kills only) + FFA check.
- **Codex 5 -> damage build** (`coach/15-damage.md`, branch `t15-damage`): damage-first upgrade order; lightning close-in at HP > 35%
  (2 exposed allowed if target < 50%), no boost for the last 25 m. Sim-blind: unit tests + gates.
- I'll combine both into one swing 4 submission on integ-3. (Fixed on the way: copied the calibrated sim from `sim-calib`; the t3
  worktree's copy was the old one.)

## Sat ~21:00 ET: swing 3 FFA check passed; queued in SUBMIT.md (from the swing 3 session)

Default FFA sim, 16 matches per cell, score (placement) / kills:

| seed | off | hunted | always-on |
| --- | --- | --- | --- |
| 1 | 11.62 / 1.56 | 13.00 / 3.00 | 10.19 / 1.94 |
| 2 | 14.69 / 2.44 | 13.88 / 2.81 | 11.38 / 2.81 |
| mean | 13.16 | **13.44 (+0.28)** | 10.78 (-2.38) |

- Hunted is not worse in FFA (+1.38 / -0.81 by seed, within noise); always-on reproduces the old -2 loss. The switch does its job.
- Calibrated practice, final: off 3.46, **hunted 4.42**, always 5.04 kills/match (always: 23/48 alive at 150 s).
- Queued `66e35891a6e33c51f131beadd3e6703a190f49e2` in SUBMIT.md Pending (keep >= ~3.8, drop < 3.5). Still running: `window_s` 10,
  chase limits, meet probe. If one of them clearly wins I'll queue it as a separate commit.

- Damage build delivered (`f9b7048`, both flags on, test_damage.py 5 checks, check/fuzz clean, 16 FFA smoke matches ok). Code read clean: flags off = old close-in rule exactly. Staged as branch `swing4`; finisher pending.

## Sat ~21:00 ET: swing 3 real result 3.02, dropped (from the swing 3 session)

`66e3589` (t13-hunter, hunted aggro) scored **3.02** real vs 3.65 for its base t11-power and 3.71 for integ-3: a clear loss, beyond
noise. Calibrated sim said +0.96 kills/match. Second time in a row a calibrated-sim gain failed to transfer (swing 2: +0.42 sim,
3.46 real), and this one moved the opposite way. Takeaways:
- The calibrated sim reproduces the off-arm kill timeline but not how the real game punishes walking into the open. Hunt mode leaves
  cover to chase the last known spot; real practice has jets, roofs, special weapons and loot the gun-only sim lacks.
- In real play the gate is probably on far more than in the sim (fewer real hits from non-hunters), so "hunted" ran close to the old
  always-on aggro, on a base whose evade/unstick gains assume it falls back to cover.
- Don't use the calibrated sim to promote changes that alter how exposed we are. Only trust it for changes that don't (e.g. timing).

## Sat ~21:15 ET (coach): swing 3 = 3.02 -> affects swing 4

- Confirmed pattern across swings 2 and 3: the calibrated sim matches the kill timeline but **not the real cost of leaving cover**.
  Rule from here: nothing that increases exposure (hunting, chasing, moving to positions under fire) gets promoted on sim evidence.
- Swing 4 consequence: ship the finisher with **chase off** (it walks to a fleeing target's last-known spot, the same move that
  lost in swing 3); keep focus fire + target lock + don't-abort-near-kill, plus the damage build.
- README's Submissions log on main still lacks the evening's results (asked Nathanael whether to append without committing).

## Sat ~21:35 ET: SWING 4 READY -> `774470421ed987bbf199f7f857e887c361fa7949`

Finisher (Codex 1, `9b3ae20`): calibrated practice +0.88 kills (3.56 -> 4.44), FFA worse with chase on (seed 2 kills 2.56 -> 2.19,
alive at 150 s 15 -> 11). Shipped with chase off (`chase_s` 0), stacked on the damage build (`f9b7048`). FFA seed 2 of the exact
combination: 2.12 kills, 13/16 alive at 150 s (integ-3 2.56, 15/16). test_damage's 3-exposed case updated (finisher stays to finish
a 60-HP target: intended). Gates pass. Queued; if it wins practice, run more FFA seeds before considering it for the final.

## Sat ~21:45 ET: swing 4 = 3.17 -> dropped. Changes paused; focus moves to recording and analyzing fights

Four big swings in a row below integ-3: 3.65, 3.46, 3.02, 3.17. Even the calibrated sim predicts gains that reverse in real play.
integ-3 (`6bb23c4`, 3.71) stays the base and the recommended final entry. Codex 1 and 5 idle.
