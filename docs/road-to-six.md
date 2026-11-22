# From 5.58 to 6+ on Builders

Our selected final entry and control, `768b8a3`, scored 5.75. Reaching 6.00 takes 24 more placement points across 96 matches, or one extra hunter outlasted in one match out of four. The leaders in the Sunday snapshot scored 6.20–6.74. [Scoring-page snapshot](../coach/advit-submissions.md)

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

Before submitting, run the repo's protocol and timing checks and coordinate a scoring slot with the team. Log the commit, local evidence, and builders-4 result below. Keep `768b8a3` selected during testing.

| Experiment and commit | Scenario or seed set and count | Control → candidate metric | Builders score | Decision |
| --- | --- | --- | --- | --- |
| Original duel control `8f7f9b8` | Builders-4, 96 matches | — | 5.58 | Reference for #3. |
| #3 `768b8a3` duel control + laser-first + 60% gate from 150 s + robust FFA fix | Builders-4, 96 | +0.17 vs `8f7f9b8` | **5.75** | Selected final pick and new control. |
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

**Note (Advit):** `8f7f9b8` is built on `515bce5`, not `robust`, so it lost robust's FFA-detector fix (an NPC kill counted as a mech
kill can hide other mechs' deaths and keep giddy in its aggressive practice settings in the final). The #3 commit restores it.

**Advit's builds (all on `768b8a3`, 5.75, one change each):** #1 `7294ba0` Corner: after a kill with nobody in sight (duel phase),
hold a nearby spot with clearly lower `World.Exposure` for 15 s. #2 `c430120` DuelBoth: break sight when the foe's estimated time
to kill us (its weapons, cubes, house-bot accuracy) beats our finish at 70 % hits, unless our finish is under 1.2 s. #3 tuning:
HealGate from 200 s `5722027`.

## Analysis and next steps (Codex review, 2026-11-22)

**What happened.** All ten one-change trials trailed `768b8a3` (5.75), with a mean of 5.48 and a range of 5.33–5.69. Early tracking posted the largest shortfall (−0.42) despite a positive paired sim result. The regen guard (−0.24), delayed HealGate (−0.24), early duel start (−0.20) and Opening (−0.06) fit the estimated ±0.18–0.25 variation per submission. We picked the highest observed score, and all ten comparisons share that one 96-match control batch. A favorable draw for `768b8a3` could explain part of every gap. The variants’ average cannot estimate the control’s true level. [Builders-4 submissions through 4:24 AM ET](../coach/advit-submissions.md)

**Use the remaining time for FFA robustness first.** At 4:24 AM ET there are 4 h 36 min to the 9 AM freeze and 6 h 36 min to cutoff. Practice rewards beating a hunting squad. The final rewards placement among opponents who also fight each other. Spend the first block of time on evidence from that format.

| Order | Work before freeze | Submission decision |
| --- | --- | --- |
| 1 | Review recorded showdown openings and test the control’s FFA switch with a known NPC kill followed by another mech’s death. Compare the control and the already-scored Opening build on the same two seed sets against clones in `--ffa`. Track placement, deaths before 60 s and time spent in practice mode. | Zero practice slots for diagnosis. If a repeatable FFA failure appears, fix that behavior alone and rerun the paired comparison. The gun-only clone sim can test exposure and switching. Use showdown evidence for loadout effects. |
| 2 | Reserve the first new entry for an FFA fix that corrects the reproduced failure and holds up on both seed sets. Run protocol and timing checks before submission. | Use practice as a regression check. Judge the FFA benefit by the matched FFA results. Keep the 5 s practice switch (`8621477`) out of the final. |
| 3 | Allow one bolder practice trial if time remains. In `giddy/mech/duel.go`, veto a lightning approach when an aimed laser can finish us during the crossing. Test a lethal crossing and a safe immediate finish. | Submit only if it corrects the first encounter and preserves the shot in the second. Combine changes only after showing how one enables the other in the same encounter. Stacking the dropped tracking and regen builds has no such evidence. Leave unused slots open. |

**Control resubmission: zero slots.** Builders-4 keeps the first score for identical code. Resubmitting `768b8a3` or a byte-identical rebuild returns the existing 5.75 and provides no independent batch. More local seeds can measure local FFA robustness, but the control’s expected builders-4 score remains unknown. [Scorer notes](advit_summary.md)

**Final pick.** Keep `768b8a3` selected for its best observed practice result and restored FFA detector. Switch only for a checked candidate with repeatable evidence of better final-format placement or a demonstrated fix for a consequential FFA failure. A practice-only gain cannot establish either. [FFA checks](PARTNER_BRIEF.md)

**Advit, builds for the Codex priorities (one change on `768b8a3` each):**
- Priority 1, regen guard: `830814f` skips optional NPC/crate shots inside the HealGate band (from 150 s, below 60 % HP). Sim: identical (gate band rarely reached).
- Priority 4, early target tracking: `081f0d7` keeps the same hunter as the foe for 1 s after losing sight, from 60 s (duel positioning still 150 s). Sim vs `768b8a3`: +0.42 (seeds 3/9), +0.04 (seeds 4/10), pooled +0.23 over 48.
- Also queued: `1c47fc9` giddy's `Opening` mode on; `8621477` practice switch at 5 s (do not use in the final entry: aggressive settings 5-20 s in FFA).
