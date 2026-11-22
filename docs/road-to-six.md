# From 5.58 to 6+ on Builders

Our selected final entry and control, `768b8a3`, scored 5.75. Reaching 6.00 takes 24 more placement points across 96 matches, or one extra hunter outlasted in one match out of four. The leaders in the Sunday snapshot scored 6.20–6.74. [Scoring-page snapshot](../coach/advit-submissions.md)

Earlier shooting-cutoff experiments put most scoring before 150 seconds, with a smaller contribution from 150–300 seconds. Those probes used the previous scorer. We still need to learn whether the selected build loses the next fight because it arrives hurt, gets hit first, or trades poorly once engaged. Each experiment below tests one of those explanations. [Earlier probes and simulator results](advit_summary.md)

## Claim an experiment

Start new branches at `768b8a3` for a one-change comparison. Add your name and branch below when you pick one up.

| Experiment | Owner | Branch or PR | Status |
| --- | --- | --- | --- |
| 1. Choose the next fighting position | Advit | `claude/nifty-galileo-lw5l5t` `7294ba0` (= `768b8a3` + Corner 15 s) | 5.48: worse, dropped |
| 2. Predict both sides of a duel | Advit | `claude/nifty-galileo-lw5l5t` `c430120` (= `768b8a3` + DuelBoth) | Ready to submit |
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

**Note (Advit):** `8f7f9b8` is built on `515bce5`, not `robust`, so it lost robust's FFA-detector fix (an NPC kill counted as a mech
kill can hide other mechs' deaths and keep giddy in its aggressive practice settings in the final). The #3 commit restores it.

**Advit's builds (all on `768b8a3`, 5.75, one change each):** #1 `7294ba0` Corner: after a kill with nobody in sight (duel phase),
hold a nearby spot with clearly lower `World.Exposure` for 15 s. #2 `c430120` DuelBoth: break sight when the foe's estimated time
to kill us (its weapons, cubes, house-bot accuracy) beats our finish at 70 % hits, unless our finish is under 1.2 s. #3 tuning:
HealGate from 200 s `5722027`.

## Analysis and next steps (Codex review, 2026-11-22)

**What happened.** `768b8a3` scored 5.75, up 0.17 from the original duel control. That gain is within the estimated ±0.18–0.25 variation per submission, and the build bundled several changes. Adding Corner 15 s on its own (`7294ba0`) scored 5.48, down 0.27. A single pair of 96-match batches leaves the size of the Corner effect uncertain. Keep `768b8a3` selected and check whether the walk to cover costs us the first shot before spending another slot on Corner. [Builders-4 submissions](../coach/advit-submissions.md)

**Submission order.** Work from the ~3 AM ET snapshot. Check the team queue for newer results before using any of the six hourly slots. Freeze by 9 AM ET for the 11 AM cutoff. Use `768b8a3` as the control for fresh experiments and `7294ba0` for the Corner follow-up.

| Priority | Experiment | What would justify the slot |
| --- | --- | --- |
| 1 | #2, price the incoming shot before closing for lightning (`giddy/mech/duel.go`). | The current estimate can favor closing even when an aimed, charged laser will fire en route. Check that a lethal crossing is rejected and an immediate safe finish still fires. This targets the 150–300 s duel without changing the opening. |
| 2 | #3, delay `HealFrom` to 200 s (`5722027`, ready on Advit's branch). | Isolate whether the gate passes up winnable fights at 150–200 s. Compare with 5.75. The other ready variant, `009eb29`, also carries Corner relative to our control. Park it. Neither has a verified score in the snapshot. |
| 3 | #1, charge the corner move for exposure **along the walk** (`cornerSpot` in `giddy/mech/brain.go` on `7294ba0`). | One change from the scored Corner variant. In the two #1 scenarios, require it to stay when the crossing is exposed and move when the route is covered. Compare against 5.48 for the change and 5.75 for selection. |
| 4 | #3, skip an optional NPC shot just before regen starts (`giddy/mech/brain.go`). | Try only if the hurt-at-four-seconds scenario preserves HP before next contact while still firing at an arriving hunter. The submitted HP gate tested starting fights, not the value of this quiet interval. |

- **Final selection, zero slots.** Analyze recorded showdowns for first contact and causes of death, then compare finalists on paired seeds against giddy clones in `--ffa`. The scripted FFA check and clone calibration already ran. A ranking of these finalists is unverified. Keep `768b8a3` for its best recorded builders-4 score and restored FFA detector unless a checked candidate shows a gain beyond ordinary variation and holds up in the FFA comparison. [Advit's next steps](advit_summary.md#6-where-the-1-is-and-whats-next) · [FFA checks](PARTNER_BRIEF.md)
- **Reserve only.** Reproduce a giddy stadium trap on spawn seeds 1014/7000 before spending a slot on escape logic. The scripted FFA check found no stuck matches. For laser timing, revisit a re-peek only if a focused encounter shows a missed damaging release. The blanket one-second LaserHold already ran. [Giddy backlog](LEARNINGS.md#6-next-on-the-giddy-base) · [Stadium pocket](stuck_pocket.md)
- **Release the loot slots.** README's standalone NanoUp (`e9bd9ef`) and remaining Econ/FightLoot omissions lack verified scores in the log. The later 5.10 with and without NanoUp in the same stack makes that isolation low value. AllFoes, EngageDist 90, body looting and the combined neutral flags also had their turn on the old scorer. [Submission log](../README.md#submissions-log)
