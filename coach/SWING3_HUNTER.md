# Swing 3: "hunter-killer". Handoff brief for a separate session

You are implementing one candidate for Nathanael's Mech Royale bot (Builders Buildathon). Another Claude session (the "coach")
is running two Codex builders on **swing 2** (rush fortress + supply drops) at the same time. Stay out of their way (rules at
the end). Read `CLAUDE.md` / `AGENTS.md` and `kit/protocol.md` for the game; this file gives you everything learned since.

**Deadline:** freeze Sun 9:00 AM ET, cutoff 11:00 AM. Practice submissions: max 4/hour, and **Nathanael submits, not you**.

---

## 1. Ground truths (from real practice submissions; trust these over the sim)

Score = mean of `16 - place` over 48 practice matches. The 15 house bots act as one squad and never fight each other, so
**our points ≈ house bots we kill before we die.** Leaderboard noise is about 0.2-0.3.

| What | Real score | Lesson |
| --- | --- | --- |
| `integ-3` = `6bb23c4` (evade_unstick: slide around walls when an escape is blocked) | **3.71** | best so far, current base |
| `t11-power` = `5d196e3` (integ-3 + lt_energy, rush_build upgrades, cube_cap, farm_plus, lt_chain) | 3.65 | neutral; base for swings 2 and 3 |
| `ac6e281` (old base with **aggression on**) | 3.60 | was the best before integ-3 |
| integ-2 family (aggression **off**) | 3.44 | |
| heal_gate v1 / v2 (disengage while hurt) | 3.17 / 3.29 | **caution loses** |
| laser_flee (release laser while fleeing) | 2.92 | **giving up damage loses badly** |
| gun_aim (hold fire at "blocked" shots) | 3.33 | **holding fire loses** |
| weapon_ctx, upgrade_ctx, mortar_lead, special_guard | 3.42-3.60 | loot tuning: noise |

**Kill timeline, measured with probe submissions** (bot that stops shooting after T, so score = kills before T):
**2.33 kills by 150 s, 3.69 by 300 s, 3.71 total.** Nothing after 300 s. The kill rate halves after 150 s (0.93/min -> 0.54/min).

**Squad behaviour** (sim model, consistent with the real numbers): hunters = **1 + our kills so far**, weakest bots first; all of
them after 300 s. So every kill adds a hunter, later hunters are stronger, and pile-ups kill us (33/39 sim deaths had 2+ attackers).

**Final round is a 16-way free-for-all** against other teams' bots. In the FFA sim, always-on aggression cost **-2.0 points per
match** (paired, 48 matches, 3 s.e.: `docs/ffa_check.md` on branch `ffa-check`). So anything aggressive must switch off in FFA-like
situations.

The leader's practice score is **over 6**, so roughly +2.5 kills per match are available.

## 2. The swing: kill faster while hunters are weak and alone

Swing 2 is defensive (survive the build-up). Swing 3 goes the other way: **bank kills earlier and faster.** Kills are capped by
time (nothing after 300 s), early hunters are the weakest, and every "more careful" change lost. Aggression had the best practice
record before integ-3, but it must not run in a free-for-all.

**Design: aggression that switches itself on only in practice-like situations.** On while at most one mech has hit us in the last
`window_s` (20 s) and at most one enemy mech is in sight (one hunter at a time); off the moment a second shooter or stranger shows
up (pile-up or FFA). While on, the existing `aggro` code applies: fight anything within 230 m, hunt the last known enemy instead of
hiding, flee only at < 25% HP against 2+.

### Already built (WIP, untested)
Branch **`t13-hunter`** = `a39d7a3f07d26cefb1b4e323ed3ece7141ed364e` (on top of `t11-power`, pushed). In `bot.py`:
- `__init__`: `self.aggro_hunted = aggro.enabled and aggro.mode == "hunted"`, `self.aggro_window = aggro.window_s`.
- In `act()`, right after `self._enemies = enemies`: if `aggro_hunted`,
  `self.aggro = (mechs that hit us within window_s) <= 1 and len(enemies) <= 1`.
- `params.json`: `aggro = {enabled: true, mode: "hunted", window_s: 20}`.
`self.aggro` is read in three places: the evade condition (~line 300), hunt mode (~line 322), and the long-range filter in
`_choose_target` (~line 581). Check that recomputing it each tick doesn't make modes flip-flop (hunt -> evade -> hunt); add
hysteresis (e.g. stay off for 5 s after switching off) if the trace shows flapping.

### Ideas to add if the first version works (each its own flag, measured separately)
- **Meet the hunter early:** while aggressive and HP > 60%, go toward the squad's last-known side instead of waiting.
- **Grab the kill's cubes immediately** (each kill drops the victim's cubes + 2) before the next hunter arrives.
- **Don't over-chase:** stop a hunt that leads more than ~150 m from the circle centre or past 270 s (the rush).

## 3. How to measure

### Calibrated sim (important)
The default practice sim is far deadlier than the real game (it scores the bot ~1.5-2 vs 3.7 real and never reaches 300 s). Use
the **calibrated** sim on branch `sim-calib` (pushed; `tools/sim.py` with opt-in flags, defaults unchanged) and the parallel runner
`tools/simpar.py` from the same branch. Copy those two files into your worktree's `tools/` (don't commit them on your branch).
- `--aim-mult 4` (house aim noise x4) reproduces the real kill timeline: sim 2.12 / 3.31 (seed 1), 1.88 / 3.44 (seed 2) vs real
  2.33 / 3.69.
- **Judge only kills and survival in the calibrated sim, never the score.** Its house bots die in the zone a lot (the real game
  doesn't show that), so calibrated scores run 2-3 points above kills.
- The `TIMELINE` line prints kills by 150 s / 300 s / total and alive at 150 s / 300 s.

Commands (from your worktree; `python -u bot.py` is the bot):
```
python tools/simpar.py --jobs 4 --matches 16 --seed 1 --aim-mult 4 -- python -u bot.py   # calibrated practice
python tools/simpar.py --jobs 4 --matches 16 --seed 1 --ffa -- python -u bot.py          # FFA (default sim)
```
**Use at most 4 jobs**: the coach's two Codex runs share the 16-core machine.

### A/B plan
- Off arm = `aggro.enabled: false` on the same branch (that's `t11-power` behaviour). On arm = `mode: "hunted"`. Optional third arm:
  always-on aggro (`enabled: true`, no mode) to see how much the switch gives up.
- Calibrated practice: seeds 1, 2, 3 x 16 matches. Report kills/match, kills by 150 s and by 300 s, alive at 150/300 s.
- FFA: seeds 1, 2 x 16. **The hunted switch must not lose clearly in FFA** (always-on lost ~2.0 points per match there).
- Bar to hand over for a real submission: calibrated kills up >= ~0.3 per match pooled, FFA not clearly worse.

### Gates before handing over
`python kit/check/check.py -- python -u bot.py` prints PASS; `python tools/fuzz.py` shows 0 exceptions; every `test_*.py` prints
ok. **Run tests with stdin closed** (`python test_x.py </dev/null` in bash): importing `bot` reads stdin and hangs otherwise.

## 4. Rules for this session
1. Work in your **own worktree**: `git worktree add ../mech-royale-s3 t13-hunter` (from `C:\Users\natha\Downloads\mech-royale`).
   **Don't touch** `../mech-royale-t1`, `../mech-royale-t5` (Codex builders), `../mech-royale-t3`, `../mech-royale-early`, or the main
   checkout's working tree.
2. Keep every behaviour behind a `params.json` flag; with the flag off the bot must behave exactly like `t11-power`.
3. Commit to `t13-hunter` (or a child branch), push it, **never push `main`**, never force-push.
4. When it's ready, add a row to `C:\Users\natha\Downloads\mech-royale\coach\SUBMIT.md` under "Pending" with the **full 40-char
   hash**, what it is, and the keep bar (keep if >= ~3.8 real; drop if < 3.5), and append a short entry to `coach/LOG.md`.
   The coach session reads both files.
5. Remember: the sim has guns only (no loot, NPCs, special weapons, upgrades or jets). Practice decides.
