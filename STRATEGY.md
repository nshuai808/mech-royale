# Improvement plan for the 3.6 bot (`ac6e281`, now `main`)

Updated 2026-11-21 after `ac6e281` scored 3.6 and `f2aea8b` scored 1.71. Originally written for `ea37402` (3.56). Sources: `bot.py`/`zone.py`/`drops.py`/`nav.py` at `ea37402`, the README submission log, `CLAUDE.md`,
`kit/protocol.md`, and the "Competitive Game Bot Research Strategy" doc. This replaces the earlier plan, which was written
against the kit example bot.

## 1. What the bot is

A rule-based bot with a fixed mode priority: zone > drop capture > evade > fight > hide > (drop / loot / heal / move / roam / hold).

| Layer | What is there | Quality |
| --- | --- | --- |
| Map and nav | 2 m grids, LOS rays, `find_cover`, time-sliced A*, stuck detection with jet/sidestep | Solid. p99 about 2 ms. |
| Zone (`zone.py`) | Urgency levels, CRITICAL forces a zone run | Solid; added about +0.1 (2.92 to 3.02). |
| Supply drops (`drops.py`) | Approach, wait off the ring, capture alone for 4 s | Works in practice; untested in the sim (it has no drops except as an add-on). |
| Fight | Target choice (distance, HP, "shot us"), range band per weapon, strafe, close-in with lightning, time-to-kill estimate for the third-party rule | Good; the third-party check matches the research's survival-first advice. |
| Aim | Gun lead (2 iterations), laser charge and release, lightning cone, ballistic mortar | Good. |
| Loot | Lightning > laser > mortar, drops the gun for two specials, cubes, crates, NPC farming, early roam | This is where most of the gain came from (2.90 to 3.40 to 3.56). |
| Upgrades | Fixed preference list | Static. |

**What it never reads:** `obs.projectiles`, `obs.beams`, enemy `charging`, and sound bearings beyond "last gun sound". It has no
dodge: a laser telegraph or an incoming bullet changes nothing. Memory of unseen enemies is a last-seen position kept 12 s, with no
motion model.

## 2. What the score means

From `CLAUDE.md`: house bots never fight each other, so in practice **our points are the house bots we kill before we die**.
3.56 is roughly 3.5 kills per match. That tells us what the 48 practice matches reward: kills from a position where only the hunter
can reach us, then regen, then repeat. The final is a 16-way FFA, where the hunt does not exist and third parties do.

Submission history (README): 1.15 starter, 2.92, 3.02, 2.90, 3.40, 3.40, 3.27, **3.56**, 3.35 (roof camping), 0.73 (v2-integrated
arbiter), 1.71 (`f2aea8b`, v2 modules wired onto the aggression-switch commit).

Two facts about that history matter more than any single idea:
1. **The leaderboard noise is about 0.2 to 0.3.** Neutral changes moved the score between 3.27 and 3.40 with no real difference. The
   starter re-scored exactly 1.15, so the same code on the same 48 seeds is deterministic: the noise comes from any code change
   reshuffling the fights. 3.56 vs 3.40 is not a proven improvement.
2. **We pick the best of about ten tries on the same 48 seeds.** The research warns about exactly this (seed memorization). The
   expected final score is lower than 3.56, and different in kind, since the final has fresh seeds and no hunting squad.

## 3. Comparison with the research doc

| Research recommendation | Status in our bot | Verdict |
| --- | --- | --- |
| Zero timeouts, fast I/O | p99 about 2 ms on stream, worst 4 ms under fuzz. Docker 1-CPU timing check is still an open item in `CLAUDE.md`. | Done. Skip orjson/Rust. Run the Docker check once. |
| Pre-indexed map | Done (`nav.py`, 2 m grids, about 0.3 s at hello). | Done. |
| Hierarchical modes plus tactical layer | Fixed-priority mode arbiter and per-mode tactics. | Done, rule-based. No search layer. |
| Belief tracking for unseen enemies | Last-seen position for 12 s. `percept.py` exists but is not in this bot. | **Gap.** |
| Potential-field dodging of projectiles and laser lines | Not present. | **Gap, cheap to fix.** |
| Action masking (don't fire when it costs us) | Partly: range gates, cone gate, energy gate, mortar 25 to 225 m. No sound-aware masking. | Mostly done. |
| Third-party discipline | `_third_party` uses time-to-kill vs time-to-shoot of others. | Done, but untested against real FFA play. |
| Diverse opponent league | Only the practice squad plus a crude sim (`--ffa` house bots exist). | **Gap.** |
| Parameter tuning with held-out seeds | Magic numbers inline in `bot.py`; `params.json` holds only zone/drops. | **Gap.** |
| Failure-driven replay analysis | Matches give no stderr or logs. Only the sim and the replay tool see anything. | **Gap, and a hard limit.** |
| Paired comparison, variance reduction | Same 48 seeds do pair submissions, but noise is still about 0.3. | Use sim seeds in addition. |
| Search planner (RHEA / beam), RL, AlphaStar league, AIVAT, TrueSkill | Not applicable: no accurate forward model, 1 CPU, no time. | Skip. |

## 4. The main problem: evaluation, not ideas

- The local sim is gun-only: no loot, cubes, NPCs, upgrades, or special weapons. Its mean is about 2.2 against 3.0 to 3.56 real.
  Every change that moved the real score (loot, power farming) is invisible to it. It can only catch regressions in movement,
  zone play, cover and gunfights.
- That leaves practice submissions (4 per hour) as the only real signal, with 0.3 noise. A change needs to be worth more than
  about 0.4 to be seen, or must be tested more than once on different base commits.
- The two big failures (0.73, 1.71) both came from changing many things at once and then having no way to tell which one hurt.

## 5. Plan

### Rules for the rest of the weekend
1. **One change per submission, off `main` (`ea37402`).** Never stack. If a change scores under 3.2, drop it, don't patch it.
2. **Every behavior change gets a `params.json` flag**, default off. That way a submission can differ from `main` by one line and we
   can bisect.
3. **Trust a result only if it clears about 0.4**, or if two independent changes agree. Don't promote on a 0.1 gain.
4. **Judge candidates on two axes:** practice score (a sanity gate) and sim `--ffa` placement (a proxy for the final). Reject
   anything that wins practice by being more aggressive but loses in `--ffa`.
5. **Freeze Sun 9:00 AM ET.** Keep `main` on the best FFA-safe commit at all times.

### Step 0: DONE. The control run scored 3.6
- `ac6e281` (aggression on, no v2 modules) scored **3.6**, against 1.71 for the same code with the modules wired in. So the modules
  caused the 1.71, not aggression. `main` now points at `ac6e281` (plus a docs-only log commit).
- Still open: run the Docker 1-CPU timing replay once. No Docker on this machine, so someone with Docker has to do it.
- Aggression is now cleared for practice but not for the final: check it in the sim `--ffa` mode (Step 2) before the freeze.

### What the v2 module results say (see section 8)
Do not re-wire modules wholesale. Test at most one module per submission, and only after Steps 1 and 2.

### Step 1: cheap defensive gaps (best expected gain per hour)
1. **Laser and bullet dodge.** When an enemy mech is `charging` and its aim is within a few degrees of us, or a bullet in
   `projectiles` will reach our cylinder, sidestep perpendicular to the line (we already know our torso lags our legs, so strafing
   is free). The code to port exists in `percept.py` (`world.incoming[i].dodge`) and `aim.py`; take the dodge only, not the
   whole module.
2. **Use `beams` and sound bearings as threats.** A beam path gives the shooter's position exactly; add it to the `threats` list and
   to `known` (we already face and evade based on that list).
3. **Reload in cover, not mid-fight.** Reload when no enemy is visible or when breaking contact (already partly done when no target).

Flag each, submit separately.

### Step 2: FFA readiness (this decides the final, practice cannot show it)
- Run `tools/sim.py --ffa` for `main` vs variants on at least 24 matches over two seed sets. Treat this as the primary metric for the
  final and add loot and cubes to the sim only if time allows.
- Add an **FFA mode switch** driven by whether the squad is hunting us (e.g., more than one distinct attacker in the first 60 s,
  or a fight we did not start). In FFA mode: no long-range fights beyond 130 m unless already shot, disengage when two mechs are
  visible, and prefer fighting at the edge of the zone away from the center.
- Late game: in the last two circles our power (cubes, HP) should be spent on placement, not kills. Hold the best-cover position
  inside the circle with full HP; this is where `zone.py` and the existing `heal` mode already help.

### Step 3: parameter extraction and manual tuning
- Move the magic numbers into `params.json`: fight far-range (130/250), `_should_evade` thresholds, loot reach (250/150/90), farm
  radii (150/120/150), roam window (180 s), range bands, boost thresholds. No behavior change, so no submission needed.
- Tune by sim `--ffa` plus one practice submission at a time. Optuna is overkill without a trustworthy evaluator; a few hand-picked
  values are enough.

### Step 4: only if time remains
- Wire `percept.py` for belief tracking as a single flagged change (hot spots into `threats`), after Step 0 clears it.
- Wire `upgrades.py` (self-contained; one flag).
- Threat-weighted pathing from percept's `threat_grid()`.

### Not doing
- Re-wiring the whole v2 stack, roof camping, aggression as a default, search or RL planners, a Rust/orjson rewrite, TrueSkill or
  AIVAT. The first three were measured and lost; the rest cost more than they can return in the time left.

## 6. Risks to watch
- Practice improvements that come from exploiting the squad (kill the lone hunter, repeat) can lower the final score. Check every
  candidate in `--ffa`.
- The best-of-N effect: our 3.56 is probably 0.2 to 0.3 optimistic.
- A late regression we can't see: matches show no logs. Keep `main` unchanged unless a submission of the exact commit scored well.

## 8. What the v2 module results tell us

Evidence, in order of how much it proves:

| Result | What it shows |
| --- | --- |
| `ac6e281` 3.6 vs `f2aea8b` 1.71 (same base, five modules wired in) | A clean A/B on the real scorer: **-1.9 from the modules together**. This is the strongest fact we have. |
| `eed4dc6` 0.73 (older v2-integrated arbiter) vs 3.02 for the other line | The same pattern one day earlier: replacing the decision core loses badly. |
| Sim: v2-integrated 1.33 / 1.67 vs main 2.0 / 2.0 | The modules were already behind in the sim, so the failure is not a pure practice-vs-sim artifact. |
| Replay of `f2aea8b` on the kit stream: retreat 31%, hide 16%, regen 9%, fight 28% | The wired bot spends about 55% of its time not fighting. Practice pays for kills, so this fits the loss. (The replay doesn't react to our actions, so the shares are indicative only.) |
| `zone.py` +0.1, `drops.py` neutral-to-positive, loot and farming rules +0.5, aggression +0.04 | What worked was added **inside** the existing bot: it widened what the bot does without taking decisions away from it. |

**What seems to work**
- Small, targeted rules inside the working arbiter: a zone-critical override, a drop planner that only claims the bot when it is
  clearly worth it, wider loot reach, lightning-first loot, farming NPCs, cubes and crates early.
- Anything that adds cubes, HP or weapons early. Power compounds, and kills are what practice pays for.
- Higher aggression, at least against the practice squad (3.6, no worse than before).

**What seems not to work**
- A module that takes over a core decision: `engage.py` (retreat and regen outrank fight), `aim.py` (also steers the fight), and
  `loot.py` (replaces the tuned loot choice). These share one trait: they are more cautious or more generic than the tuned rules.
  In a game that pays for kills against a hunting squad, caution costs points.
- Wiring many things at once. Twice we got a large drop and could not say which part caused it.
- Roof camping (-0.2): the house bots climb, or the climb fails.

**What we can't conclude**
- Which module hurt. No module was ever submitted alone, so this is inference. My ranking of suspects, most likely first:
  1. `engage.py`: it changes the mode priority and its default thresholds (it wants about a 1.4x advantage to engage) are
     cautious. Most consistent with the replay mode shares.
  2. `loot.py`: its detour budget (150 / 60 / 25 m by time) is stingier than the tuned reach (250 / 150 / 90 m) and it drops the
     "keep two specials, drop the gun" rule.
  3. `aim.py`: its strafe band (60 to 140 m) fights the lightning close-in play.
  4. `percept.py` and `upgrades.py`: least likely to matter; they change little by themselves.
- Whether my own wiring, not the modules, was the fault. I chose the override order (engage outranks fight) and used `aim.py`
  movement on mech targets. A different wiring could behave differently.
- Whether any module helps in the final FFA. Practice rewards kills, so a cautious module might help the final even though it hurt
  practice. Nothing has measured that.

**How to use the modules from here, if we do**
1. One module per submission, off `main`, flag default off, flag on for the test.
2. Start with the most self-contained and least likely to change fights: `upgrades.py`, then `percept.py` (hot spots as threats).
3. Test `engage.py` only with a lower bar (e.g., `engage_ratio` about 0.9, `retreat_hp_frac` about 0.2) so it only fires in clearly
   lost fights, and only if the sim `--ffa` shows an FFA gain.
4. Leave `loot.py` and `aim.py` out: the tuned equivalents in `bot.py` are doing the job.

## 7. Open questions
- Does the Practice track page say anything beyond "built-in bots"? (The research doc cites it; we don't have it.)
- Is the final scoring set known (Qualifying 16 matches, Final 64)? Fewer matches mean more noise, which favors the safest commit.
