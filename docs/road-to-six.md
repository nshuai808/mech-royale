# From 5.58 to 6+ on Builders

Advit selected `8621477` after its 5.84 practice score. The comparison control is `768b8a3` (5.75). The question before freeze is whether switching to squad settings 15 s earlier is worth the opening risk in the final. [Submission log, 8:29 AM ET entry](../coach/advit-submissions.md)

Earlier shooting-cutoff experiments put most scoring before 150 seconds, with a smaller contribution from 150–300 seconds. Those probes used the previous scorer. We still need to learn whether the selected build loses the next fight because it arrives hurt, gets hit first, or trades poorly once engaged. Each experiment below tests one of those explanations. [Earlier probes and simulator results](advit_summary.md)

## Claim an experiment

Start new branches at `768b8a3` for a one-change comparison. Add your name and branch below when you pick one up.

| Experiment | Owner | Branch or PR | Status |
| --- | --- | --- | --- |
| 1. Choose the next fighting position | Advit | `claude/nifty-galileo-lw5l5t` `7294ba0` (= `768b8a3` + Corner 15 s) | 5.48: worse, dropped |
| 2. Predict both sides of a duel | Advit | `claude/nifty-galileo-lw5l5t` `c430120` (= `768b8a3` + DuelBoth) | 5.40: worse, dropped |
| 3. Recover between hunters | Advit | `claude/nifty-galileo-lw5l5t` `768b8a3` | **5.75**, new best |

## 1. Choose the next fighting position

**Hypothesis.** We can win the next exchange more cheaply by choosing where the hunter first sees us. After a kill, compare staying put with a nearby corner and a covered position along the next zone route. Favor a firing lane suited to our loadout, a short lateral step that breaks sight, and enough time before the next shrink. Charge each candidate for time exposed on the way there. Keep the current position when the alternatives offer little.

**First test.** Set up one approach where we already hold a good corner and another where we just finished a kill in the open. Check that the first bot holds and the second reaches cover before contact. In matched runs, record who lands the first damaging shot, our HP at first contact, and how often the hunter catches us in transit. Repeated losses in transit are grounds to revise the position selector. [Movement and cover logic](../giddy/mech/brain.go)

## 2. Predict both sides of a duel

**Hypothesis.** The current finish estimate evaluates each of our weapons separately. A route that shortens our time to kill can still give the hunter a lethal shot. Compare three actions over the next few seconds: fire from here, break sight and re-peek, or close while firing. Estimate outgoing and incoming damage using weapon readiness, enemy aim and visible charge, recent hits, and time crossing open ground. Give a safe immediate finish priority.

**First test.** Use two otherwise identical encounters. In one, our gun can finish before the enemy laser bears on us. In the other, our gun is reloading and the charged laser already has the angle. Check for an immediate shot in the first case and a move behind cover in the second. Track mid-game duel win rate alongside damage received per kill; include lost contacts and deaths so disengaging cannot inflate the result. [Duel estimator](../giddy/mech/duel.go)

## 3. Recover between hunters

**Hypothesis.** Time already spent out of combat has value. Regen starts after five seconds without dealing or taking damage. After a kill or clean break in contact, estimate how much HP we can regain before the next hunter arrives or the zone forces movement. Choose among reloading in cover, holding an angle, or moving immediately. Suppress optional shots when they would reset a valuable recovery interval.

**First test.** Start hurt behind cover, four seconds into the regen wait, with an optional NPC shot. Compare a distant hunter with one about to round the corner. Verify that the bot preserves the recovery window in the first case and prepares for contact in the second. Track actual HP regained between hunters, HP entering the next duel, and how often the hunter lands the first hit while we wait. [Regen and zone rules](../kit/protocol.md)

## Compare results and choose the next submission

Use matched local scenarios to check the predicted behavior and compare against the control on the same seeds. Record sample counts and early kills so a middle-game improvement cannot hide an opening regression. The local gun-only simulator can exercise pathing and contact geometry. Laser timing and lightning trades need focused weapon-state tests. Builders supplies the practice score; the detailed encounter measurements come from local runs.

Before submitting, run the repo's protocol and timing checks and coordinate a scoring slot with the team. Log the commit, local evidence, and builders-4 result below.

| Experiment and commit | Scenario or seed set and count | Control → candidate metric | Builders score | Decision |
| --- | --- | --- | --- | --- |
| Original duel control `8f7f9b8` | Builders-4, 96 matches | — | 5.58 | Reference for #3. |
| #3 `768b8a3` duel control + laser-first + 60% gate from 150 s + robust FFA fix | Builders-4, 96 | +0.17 vs `8f7f9b8` | **5.75** | 20 s control and FFA fallback. |
| #1 `7294ba0` adds Corner 15 s to `768b8a3`. After a kill from 150 s, move 8–24 m to lower exposure when clear. | Builders-4, 96. Local sim had no qualifying kills. | −0.27 vs `768b8a3` | 5.48 | Keep Corner off. Test the approach before shortening the hold. |
| #3 tuning `5722027` delays HealGate on `768b8a3` from 150 s to 200 s at the same 60% HP threshold. | Builders-4, 96 | −0.24 vs `768b8a3` | 5.51 | Keep the 150 s start. Timing test complete. |
| #2 `c430120` adds DuelBoth to `768b8a3`. Break sight when the hunter wins the estimated trade, except for a finish under 1.2 s. | Builders-4, 96 | −0.35 vs `768b8a3` | 5.40 | Drop DuelBoth. Keep the control’s duel behavior. |
| Early duels `f62bdcd` starts the control’s practice duel logic at 60 s instead of 150 s. HealGate still starts at 150 s. | Builders-4, 96 | −0.20 vs `768b8a3` | 5.55 | Keep the 150 s duel start. |
| #3 tuning `cf0611d` lowers HealGate from 60% to 50% HP on `768b8a3`, still from 150 s. | Builders-4, 96 | −0.30 vs `768b8a3` | 5.45 | Keep 60%. Park threshold tuning. |
| `2a8fa35` reloads any partial magazine with no target in the 10 s after a mech kill. | Builders-4, 96 | −0.26 vs `768b8a3` | 5.49 | Drop the 10 s rule. Check whether a hunter arrives mid-reload. |
| `62cf6af` sets practice upgrades to laser_damage, laser_charge, nanites, plating, armor. | Builders-4, 96 | −0.36 vs `768b8a3` | 5.39 | Keep the control’s upgrade order. |
| `1c47fc9` enables Opening to seek a laser and nearby loot before the practice switch. | Builders-4, 96 | −0.06 vs `768b8a3` | 5.69 | Within noise. Compare opening exposure locally for the final. |
| `081f0d7` tracks the last hunter for 1 s after losing sight from 60 s. Duel positioning still starts at 150 s. | Builders-4, 96. Paired sim +0.23 over 48. | −0.42 vs `768b8a3` | 5.33 | Drop early tracking. The sim gain did not transfer. |
| `830814f` suppresses optional NPC/crate shots from 150 s below 60% HP. | Builders-4, 96. Sim unchanged, gate rarely reached. | −0.24 vs `768b8a3` | 5.51 | Within noise. Keep the control’s firing behavior. |
| `06383db` sets practice upgrades to laser damage, laser charge, gun damage, gun rate, then plating and armor. | Builders-4, 96 | −0.16 vs `768b8a3` | 5.59 | Within noise. Keep plating and armor ahead of gun upgrades. |
| `8621477` enables squad settings after 5 s (was 20 s) while the FFA detector is still undecided. | Builders-4, 96 | +0.09 vs `768b8a3` | **5.84** | New practice best and Advit’s selected final entry. See FFA review below. |

**Note (Advit):** `8f7f9b8` is built on `515bce5`, not `robust`, so it lost robust's FFA-detector fix (an NPC kill counted as a mech
kill can hide other mechs' deaths and keep giddy in its aggressive practice settings in the final). The #3 commit restores it.

**Advit's builds (all on `768b8a3`, 5.75, one change each):** #1 `7294ba0` Corner: after a kill with nobody in sight (duel phase),
hold a nearby spot with clearly lower `World.Exposure` for 15 s. #2 `c430120` DuelBoth: break sight when the foe's estimated time
to kill us (its weapons, cubes, house-bot accuracy) beats our finish at 70 % hits, unless our finish is under 1.2 s. #3 tuning:
HealGate from 200 s `5722027`.

## Analysis and next steps (Codex review, 2026-11-22)

**What happened.** The 5 s switch is the first of twelve one-change builds to beat the 5.75 control. Its +0.09 fits the estimated ±0.18–0.25 variation per submission. The house squad rarely supplies the signal that ends practice mode, so its score tells us little about the cost of an early FFA encounter. [Builders-4 submissions](../coach/advit-submissions.md)

**When the builds disagree.** Both start with base settings. On every observation, `observe` checks whether the drop from the initial alive count exceeds our own mech kills (known NPC kills are excluded). Five consecutive positive observations, roughly half a second, permanently set `notPractice` and restore base settings if squad mode is active. A zero or negative difference resets the counter. The only code change is the time gate, from `now > 20` to `now > 5`. [Detector at the scored commit](https://github.com/nshuai808/mech-royale/blob/8621477/giddy/mech/brain.go#L317-L348)

| FFA evidence on the same observation stream | Consequence |
| --- | --- |
| FFA confirmed by 5 s | Both keep base settings throughout. |
| FFA confirmed at 12 s, for example | The 5 s build spends about 7 s in squad mode, then switches back. The 20 s control stays in base mode. |
| FFA still unconfirmed at 20 s | The new build gets up to 15 extra seconds in squad mode. Both then use it until confirmation. A quiet lobby or deaths entirely credited to us can delay that signal indefinitely. |

**Cost in the final.** Yes, the earlier gate creates more opportunity for a temporary false practice classification. It changes neither the death test nor the ability to recover. During the extra window, squad settings disable `Ghost` and `Peek`, widen loot search from 90 to 150 m and allow mid-fight cube detours up to 40 m. Earlier loot could help, but stepping into a second opponent’s sightline can cost HP or placement before the detector corrects. Restoring parameters cannot undo that move or an early death. The frequency and net placement cost in real finals are unmeasured. [Squad settings](https://github.com/nshuai808/mech-royale/blob/8621477/giddy/mech/brain.go#L1958-L1986)

**Freeze decision.** Advit currently has `8621477` selected. **Recommend returning to `768b8a3` for the FFA final** unless available showdown evidence or paired FFA openings favor the 5 s build. With about 25 minutes left, first check when the first sustained, uncredited death occurs in recorded openings. For matches still undecided at 5 s, compare first contact, HP at 20 s and early deaths on matched spawns. Give this check priority over new practice submissions. If evidence is sparse at 9 AM ET, use the 20 s fallback. An identical resubmission cannot generate an independent practice score. [Scorer notes](advit_summary.md)

**Advit, builds for the Codex priorities (one change on `768b8a3` each):**
- Priority 1, regen guard: `830814f` skips optional NPC/crate shots inside the HealGate band (from 150 s, below 60 % HP). Sim: identical (gate band rarely reached).
- Priority 4, early target tracking: `081f0d7` keeps the same hunter as the foe for 1 s after losing sight, from 60 s (duel positioning still 150 s). Sim vs `768b8a3`: +0.42 (seeds 3/9), +0.04 (seeds 4/10), pooled +0.23 over 48.
- Also queued: `1c47fc9` giddy's `Opening` mode on; `8621477` practice switch at 5 s (do not use in the final entry: aggressive settings 5-20 s in FFA).

## Advit's queue (Sun ~4:45 AM ET): loot less

Every change that made giddy loot more lost 0.3-0.6 (Econ+FightLoot 5.10, Explore, drops 5.40, body loot 5.42), and every
fight-behavior change lost too. Untested direction: giddy's own practice looting, which is already heavy (crates all match,
cubes within 40 m mid-fight, loot within 150 m, NPC farming above 50 % HP). One change each on `768b8a3`:

| Order | Commit | Change (practice `squadParams`) |
| --- | --- | --- |
| 1 | `4c50b36` | `FightLoot = 0`: no cube walks during fights (was 40 m) |
| 2 | `11242ed` | `CrateUntil = 150`: stop shooting crates after 150 s (was all match) |
| 3 | `e967e8f` | `FarmHP = 0.75`: farm NPCs/crates only above 75 % HP (was 50 %) |
| 4 | `089ffe9` | `LootRadius = 100` (was 150) |
| 5 | `8621477` | practice switch at 5 s (practice only; not for the final entry) |
| later | combinations | any two that beat 5.75, plus `1c47fc9` Opening (5.69) |

## Three independent builds from the 5.84 control

The practice target of 6.10 requires about 25 extra placement points per 96-match batch over `8621477`. Earlier tracking (5.33), unconditional post-kill repositioning (5.48), and breaking sight on predicted losing trades (5.40) all scored below their 5.75 control. These candidates change first contact or damage delivery while keeping the 5.84 build's practice switch and HealGate. Submit independently in the suggested order. All scores are pending.

| Order | Candidate commit | Change and main uncertainty |
| --- | --- | --- |
| 1 | [Sound acquisition](https://github.com/nshuai808/mech-royale/commit/ed07546760653635910dc79787dddc00c34e8eae) | Turn the vision cone toward recent close weapon or movement sounds while searching. A nearby weapon can interrupt farming aim. This can win a first shot across loadouts, but an anonymous sound can point away from the next hunter. |
| 2 | [Gun and laser timing](https://github.com/nshuai808/mech-royale/commit/84780e619cebd577f838b1147b16178ae114a756) | Give the gun more aiming time during a laser charge when the torso can still align for release. Release a usable partial charge when the target is projected to cross behind cover. Value depends on how often both weapons can contribute or a firing window closes. |
| 3 | [Lightning matchup](https://github.com/nshuai808/mech-royale/commit/71096ec453ee210fd80a50cb9a8d9f9613378bc0) | Close on an isolated laser carrier when healthy, sufficiently energized, and within a short approach of lightning range. A laser carrier facing lightning instead prefers a range buffer. This exploits charge interruption, but only applies to specific loadouts. |

All three passed Go unit tests, compiled for Linux amd64, and answered 300/300 protocol observations within 50 ms locally. Contact and lightning used native Windows binaries. Volley used Go WebAssembly on Node because Windows Application Control blocked its native executable. These checks establish protocol behavior. Match strength and FFA placement are unmeasured.

## Revised queue after the 8:32–8:42 AM results

The submitted bot code was compared directly with the scored control. Some immediate parent commits were other experiments whose settings had been restored before submission.

| Submitted commit | Change from its control | Builders score | Difference |
| --- | --- | ---: | ---: |
| `d721f58` | Disable the usual mid-fight cube detour | 5.15 | −0.69 vs 5.84 |
| `2f9fdd6` | Raise the quiet-period NPC/crate farming threshold from 50% HP to 75% | 5.45 | −0.39 vs 5.84 |
| `877119e` | Enter squad settings at 1 s instead of 5 s | 5.47 | −0.37 vs 5.84 |
| `11242ed` | End quiet-period crate **and NPC** goal selection at 150 s | 5.52 | −0.23 vs the 20 s control, 5.75 |

The strongest signal is the cost of removing the nearby cube option. Earlier losses from body-loot trips and wider farming suggest a distinction between collecting resources along an existing fight and deliberately extending the trip. Aggregate scores cannot separate the value of the cubes from the movement used to reach them. The 1 s result also weakens the case for starting squad behavior progressively earlier.

**Revised submission order.** First try `84780e6` (gun–laser timing). Of the three published candidates it most cleanly tests a combat gain while preserving resource decisions. Defer `ed07546` (sound acquisition) until the scan can be tested during otherwise idle aim; the published version can interrupt farming fire. Put `71096ec` (lightning matchup) behind a test that keeps the ordinary cube-detour decision available during the matchup. Both are still unscored in the four results above.

**Revised interception experiment.** Start from `8621477`. First test pre-aiming a predicted crossing while following the baseline loot route, only when the torso would otherwise be idle. Compare damage dealt before the first incoming hit, time to the next kill, and cubes at the next contact on matched starts. Expand to rerouting only if pre-aim improves the opening exchange and the economy measurements hold up.

## Advit's findings (Sun ~8:55 AM ET)

**FFA cost of the 5 s switch, from 14 recorded showdowns** (`tools/feed_record.py`, top-team free-for-alls): the first mech death
came at 8.0-23.9 s, median 12.3 s, **never before 5 s**; 11 of 14 between 5 and 20 s, 3 after 20 s. So `8621477` plays squad
settings in a typical final opening for about 7 s (5 s to first death + 0.5 s detection), up to 15 s in 3/14 matches; the 20 s
control plays base settings there. giddy died before 60 s in 31 % of recorded showdowns. **Final entry: `768b8a3`** (agrees
with the Codex recommendation).

**Practice results on `8621477` (5.84):** every one-change variant lost 0.3-0.7: FightLoot 0 5.15, FarmHP 0.75 5.45, switch at
1 s 5.47, FightLoot 60 5.54. With CrateUntil 150 (5.51 on 768b8a3): every cut to giddy's own loot loses on builders-4, and so
does widening mid-fight cubes. giddy's loot settings look locally optimal. Pending: `e68afed` FarmHP 0.35, `8e51ee0` LootRadius 200.
Both bests (5.75, 5.84) are likely partly high draws (each was the best of ~10 runs; all neighbours land 0.25-0.4 lower).

## Advit (Sun ~9:50 AM ET): the noise floor

All 27 builders-4 scores of giddy variants (each a small change of 8f7f9b8 / 768b8a3 / 8621477): **mean 5.47, sd 0.16, range
5.11-5.84**. That spread is what ±0.16-0.18 noise around one true level of ~5.47 looks like, so no change so far is
distinguishable from noise, including the two "bests" (5.75 = +1.7 sd, 5.84 = +2.3 sd, both the maximum of many tries).
6.10 would be +3.8 sd: out of reach for small tweaks of this bot. Final pick unchanged: `768b8a3` (robust FFA detector).

**Sun ~10:45 AM ET:** `9fa225a` (zoro V2 + giddy practice economy and recovery, `zoro-giddy-hybrid`) scored **6.10**: about +0.6
over every giddy variant (mean 5.47, sd 0.16), the first change of the bot itself that clearly beats the noise floor. The gain
came from a different base bot, not from tuning giddy. Its FFA play (zoro's) is unchecked against the recorded showdowns.
