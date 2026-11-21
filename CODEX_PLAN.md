# Work plan for Codex (written Sat 2026-11-21, 4 PM ET)

Codex does the work; Claude reviews it. Read `AGENTS.md` (or `CLAUDE.md`), `README.md` and `kit/protocol.md` first.
Times are ET. **Freeze Sun 9:00 AM, cutoff Sun 11:00 AM.** That leaves about 17 hours, and at most 4 submissions per hour.

## 1. Where we are

### Real practice scores that matter (full log: README "Submissions log")
| Commit | Score | What |
| --- | --- | --- |
| `ac6e281` | **3.6** (best) | main: loot + power farming + aggression on |
| `ea37402` | 3.56 | same without the aggression code |
| `a8c36d0` | 3.42 | `ac6e281` + dodge |
| `c6c10d4` | 3.44 | **`integ-2`**: aggression off, `roam_fix`, `unstick.v2`, `unseen_hit`, `evade_fix`; every other new flag off |
| `f2aea8b` | 1.71 | v2 modules wired in all at once. Never build on it. |

Leaderboard noise is 0.2 to 0.3. Everything since `ea37402` (3.56) has landed inside that noise: **we are on a plateau
around 3.4 to 3.6.** A change counts as better only at about **+0.4** (4.0 or more).

### What the simulator says
- **Final = free-for-all.** In `sim.py --ffa`, aggression costs about 2 points per match (paired -2.00 +- 0.64, 48 matches;
  `docs/ffa_check.md` on branch `ffa-check`). In practice it gained only +0.04 (noise). **So the final bot has aggression off.**
  `integ-2` already has it off.
- **Spawn deaths** (`docs/spawn_safety.md`): with `unseen_hit` and `evade_fix` on, deaths under 25 s fell from 16/64 to
  8/64 and kills were unchanged (practice sim, aggression on). Not measured with aggression off.
- **The main bottleneck** (`tools/fights.py` on 32 sim replays, aggression on):
  - 25 of 32 fatal fights had **2 or more mechs shooting us** (13 had 3 or more). Of the fights we survived, 39 of 57 had 0 or 1 shooter.
  - 12 of 32 fatal fights **started below 50% HP**: we start the next fight before we have regenerated.
    A fight starts every ~20 s (median), and regenerating from 50% also takes ~20 s.
  - 17 of 32 started at full HP and were lost to 2 or 3 shooters.
  - The bot already wins 1v1s. It dies to pile-ups and to re-engaging while hurt.

### Flags already built on `integ-2`, but off and never scored alone
`upgrade_ctx`, `weapon_ctx`, `special_guard`, `mortar_lead` (loot and weapon layer; the sim has no loot and can't judge them),
`early_evade`, `dodge` (dodge scored 3.42 on top of `ac6e281`: noise), `late` (late-game hold; matches rarely get that far).

## 2. Rules for every Codex task
1. Branch off **`integ-2`** (`c6c10d4` or later), in its own worktree: `git worktree add ../mech-royale-<name> -b <branch> integ-2`.
2. **One behavior per branch, behind a `params.json` flag.** With the flag off, the bot must behave exactly like `integ-2`.
3. Touch only the functions the task names. If you need to change anything else, stop and say so in the report.
4. Before handing back: `python kit/check/check.py -- python -u bot.py` prints PASS, `python tools/fuzz.py` shows 0 exceptions,
   every `test_*.py` prints `ok`, and p99 answer time stays well under 35 ms.
5. Sim A/B: flag off vs flag on, the same seeds for both arms, 16 matches each, **at least 2 seed sets**, at most 2 sims at once.
   Use `--record` and run `python tools/fights.py replays/sim-*.jsonl.gz` on each arm. Judge score, kills, deaths under 30 s and the
   fights table together, because a 16-match score alone is noise (s.e. 0.3 to 0.45).
   Clear `replays/sim-*` between arms (the files are named by seed and get overwritten).
6. For anything that changes fighting or survival, also run `--ffa` (16 matches, 2 seeds). **The final is FFA. A change that helps
   practice but hurts `--ffa` is rejected.**
7. Never push to `main`, never force-push, never delete a submitted commit. Push your branch; Nathanael merges and submits.
8. Report: branch, full commit hash, functions changed, flag name and values, A/B table (practice and `--ffa`), fights table,
   what was not verified. Say plainly that the sim has gun fights only: no loot, NPCs, special weapons, upgrades or jets.

## 3. Tasks, in priority order

### Task 0: re-measure the bottleneck on `integ-2` (measurement only, ~30 min)
The fights numbers above came from an aggression-on branch. Before changing anything, measure `integ-2` as it is:
practice sim `--record` on seeds 1 and 2 (16 each) plus `--ffa --record` on seeds 1 and 2, then run `tools/fights.py` on each.
Report the same fights table (attackers in fatal fights, HP at the start of fatal fights). **This sets the order of Tasks 1 and 2.**

### Task 1: leave a fight when a second shooter joins (flag `second_shooter`)
- **Problem:** most deaths are 2v1 or 3v1. With aggression off, `_third_party` and `_should_evade` decide this, but by then we are
  already caught (look at the last 6 s of fatal fights in `tools/analyze.py`).
- **Idea:** if 2 or more different mechs hit us within ~2 s, **or** a second enemy has line of sight within 150 m while we fight,
  break off at any HP unless the target dies within ~1.5 s (`Bot._finishing`). Use the existing evade path, which already has the
  2.5 s commit and the wider cover search.
- **Where:** the evade condition in `act()`, plus one helper. A reference is `Bot._multi_hit` (`early_evade`); this is the same
  idea without the HP gate. Consider replacing it rather than adding a third rule next to it.
- **Watch:** kills per match must not fall much. Fewer kills means a lower practice score even if we live longer.

### Task 2: heal before the next fight (flag `heal_gate`)
- **Problem:** 12 of 32 fatal fights started below 50% HP.
- **Idea:** below ~70% HP, don't pick a new target that isn't shooting us. Break line of sight and regenerate (45 HP/s after
  5 s without damage). Return fire only when hit. Tune the threshold between 0.6 and 0.85.
- **Where:** `_choose_target` (skip targets that aren't shooting us when HP is low) and the `heal` branch in `act()`.
  Don't touch zone priority: zone damage beats everything.

### Task 3: practice-score the loot and weapon flags (no code; Nathanael submits)
Loot was the only layer that ever moved the real score (2.90 to 3.40 to 3.56). These flags exist on `integ-2` but are off.
Make one branch per flag with only that flag on, then submit them in this order, one per submission:
`weapon_ctx` -> `upgrade_ctx` -> `special_guard` -> `mortar_lead`. Keep a flag only if it scores about 3.8 or more.
Submissions are scarce, so interleave these with Tasks 1 and 2.

### Task 4: free-for-all endgame (flag `late`, already built)
Only `--ffa` can show this. Run long `--ffa` matches with `late` off vs on and report median survival time and top-4 rate.
Keep it if it doesn't lower the `--ffa` score.

### Task 5: real Docker timing check (needs a machine with Docker)
It has never been run with real Docker. Run the commands in `README.md` / `AGENTS.md` on the final candidate. The map must build
well under the 20 s hello budget, and p99 must stay under 35 ms.

### Not doing
Rooftop camping (3.35, house bots climb), wiring v2 modules in all together (1.71), exploits of the practice squad that wouldn't
work in an FFA, big rewrites.

## 4. Building the final candidate (Sun, before 9:00 AM)
1. Start from `integ-2` (aggression off).
2. Add, one at a time, each flag that passed its bar: practice about +0.4 or more, or `--ffa` clearly better with practice no worse.
3. After each addition run check, fuzz, tests and a 16-match `--ffa` run. If the combination drops, take the last addition out.
   Combined results are not the sum of the parts.
4. Submit the combined candidate alone and log it. If it doesn't hold up, fall back to the best **single** scored commit
   that has aggression off.
5. Freeze at 9:00 AM: merge into `main`, check passes, log it in README, nothing after that.
