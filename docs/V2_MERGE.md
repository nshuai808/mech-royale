# V2 merge guide

How components get merged into bot v2, what v2 already contains, and a prompt to paste into each component's chat.
Branch: `v2-loot` (built from `main` = the kit example bot, v1). `main` is what gets scored: do not merge there without the owner's say-so.

## 1. What was done in v2 so far (loot and weapon choice, H-LOO / H-WPN)

| File | Change |
| --- | --- |
| `loot.py` | New. `LootPlanner.step(obs, threats=None, path_cost=None) -> Decision`. Remembers pickups by id, scores them, returns a goal, a `take` (plus `drop` slot for a swap), or a liability `drop`. Pure stdlib, about 2 ms worst case per call. |
| `test_loot.py` | New. 27 unit tests, `python3 test_loot.py`. Excluded from the Docker image. |
| `params.json` | New. Single home for tunable knobs. v2 has `loot` and `fire` sections. Loaded in `Bot.__init__`; a missing or bad file falls back to defaults. |
| `bot.py` | Calls the planner each tick inside a try/except (an error means "no loot", i.e. v1 behaviour). Applies `take`/`drop`. Uses `Decision.goal` instead of the zone centre as the waypoint when there is one. Jumps and boosts toward roof pickups. Fire is now per slot: gun always, laser/lightning only inside 90% of their range, mortar never (there is no ballistic aim yet). |
| `.dockerignore`, `README.md`, `CLAUDE.md` | Docs and ignore updates. |

Decisions worth knowing:
- Slot 0 is the gun, slot 1 is the weapon we choose. Never hard-code `fire=[gun, special]`; use `loot.slot_of(weapons, kind)`.
- Pickup order is lightning > laser > mortar, discounted by path distance. In `params.json` mortar's base value is 0, so v2 never picks one up: with flat aim it would only be a laser cook-off liability. Raise it when an aim component can lob shells.
- Loot detour budget (path metres): 150 until t=60 s, 60 until t=110 s, 25 after.
- The planner does nothing while we are outside the zone.
- Straight-line walking to the loot goal: no pathing yet, so it can run into walls and slide.
- Verified: unit tests, `kit/check/check.py` (PASS, p99 about 1 ms on the dev machine), replay of the 300 recorded observations (decisions logged, timing fine), and a synthetic observation test of take/walk/fire. Not verified: play strength against real opponents (replays do not react to our actions).
- Full design, numbers and test plan: `claude/loot-weapons-proposal.md` in the Claude project.

## 2. Integration contract (so components merge without fighting)

**One integrator.** `bot.py` is the only place components meet. A component adds a module file and a small hook in `bot.py`. It does not reshape `bot.py`.

**Module shape.** One stdlib file per component (`loot.py`, `nav.py`, `engage.py`, ...), one class built in `Bot.__init__(hello)` from `hello["config"]` and its own `params.json` section, one `step(obs, ...)` per tick, a `Decision`-style return value. No network, no files except reading `params.json` and the baked map, no writes outside `/tmp`.

**Budgets.** Whole bot under 50 ms per decision on 1 CPU; keep p99 under 35 ms. Give each component a time slice (loot is about 2 ms; sum of all slices should stay under about 25 ms). Long work must be time-sliced across ticks or precomputed in the 20 s ready window.

**Failure rule.** The bot wraps every component call in try/except and falls back to a safe default. A component must never be able to crash the bot or stall a tick.

**Who owns which action field.**

| Action field | Owner | Notes |
| --- | --- | --- |
| `take`, `drop` | loot | Nobody else sets them. |
| `pick` (upgrade offers) | upgrades | v2 still sends `0`. |
| `move`, `boost`, `jump` | one arbiter in `bot.py` | Takes goals from engage/retreat, zone, loot, in that priority; nav turns a goal into a direction. |
| `aim`, `fire`, `reload` | aiming (and engage for hold-fire / quiet rules) | Fire by slot lookup. Loot does not decide fire. |

**Goal priority (highest first):** retreat or regen, fight movement, supply-drop capture, zone safety, loot, default zone-centre walk. Loot only returns a *suggestion* (`Decision.goal`); the arbiter may ignore it.

**Hooks other components should use:**
- Perception -> loot: pass a list of `loot.Threat(id, dist, kinds, weight)` as `threats=`; otherwise loot builds one from `obs`.
- Navigation -> loot: pass `path_cost(src_xyz, dst_xyz) -> (length_m or None, exposure 0..1)` as `path_cost=`; `None` means unreachable.
- Aiming / engage -> loot: `loot.slot_of(weapons, kind)` and `loot.preferred_range(kind, cfg)`.
- Engage -> loot: `planner.equip_delay(kind)` if timing a swap. Loot already refuses far pickups during a fight (`fight_pickup_radius_m`).

**Params.** All knobs live in `params.json`, one section per component (`loot`, `nav`, `engage`, `fire`, ...). Unknown keys are ignored, partial overrides are allowed, defaults live in the module's dataclass. Keep keys `snake_case`.

**Trace.** One `botlog.trace(tick, mode=..., **fields)` call per decision (already in `bot.py`). Add your fields to it; do not add more trace calls.

## 3. Merge checklist (every component)

1. `git switch -c v2-<component> origin/v2-loot`. Rebase onto `origin/v2-loot` again right before you push.
2. Touch only your own module, your own tests, your `params.json` section, and the hook lines in `bot.py`.
3. `python3 test_loot.py` and your own tests pass.
4. `python3 kit/check/check.py -- python3 -u bot.py` prints PASS.
5. `python3 tools/replay.py -- python3 -u bot.py`, then `python3 tools/analyze.py replays/<file>.jsonl.gz`: no crashes, p99 answer time well under 35 ms. For the real timing test use the Docker replay in `CLAUDE.md`.
6. Add a row to the table in section 4 below and a line to `CLAUDE.md` status.
7. Commit with the attribution lines your tooling requires, push the branch, and report: what changed, what you tested, what you did not, and which knobs matter. Do not merge to `main`.

## 4. Integrated components

| Component | Branch | Hook in `bot.py` | Params section | Status |
| --- | --- | --- | --- | --- |
| Loot and weapon choice (H-LOO, H-WPN) | `v2-loot` | `Bot._loot`, goal override, `take`/`drop`, `Bot._fire` | `loot`, `fire` | merged into `v2-loot`; untested against opponents |
| Navigation and stealth (H-NAV, H-STL) | | | `nav`, `stealth` | |
| Fight-or-flee and regen (H-ENG, H-REG) | | | `engage` | |
| Zone and supply drops (H-ZON, H-DRP) | | | `zone`, `drops` | |
| Aiming and movement (H-AIM, H-MOV) | | | `aim`, `move` | |
| Upgrades (H-UPG) | `v2-upgrades` | `Bot._pick` (every tick; sets only `pick`), one `upg=` field in the existing trace | `upgrades` | merged into `v2-upgrades`; ranking validated in a crude duel sim only, not against opponents. Design: `claude/h-upg.md` |
| Perception (H-PER) | | | `perception` | |

## 5. Known conflict: `survival-v1`

A separate branch `survival-v1` (not built from `v2-loot`) rewrites `bot.py` (about 580 lines with its own modes, `nav.py`, `tools/sim.py`, `tools/fuzz.py`). It has simple loot code of its own (`_loot_goal`, `_take`) that overlaps with `loot.py`, and it will conflict with the `bot.py` here. Do not resolve this inside a component branch. One integration pass should:
1. Decide the base (`survival-v1` has the working survival core and a local simulator; `v2-loot` has the loot module).
2. Replace `_loot_goal` / `_take` in the chosen base with calls to `LootPlanner.step`, keep the `params.json` loading, and keep slot-aware firing.
3. Use `tools/sim.py` to compare loot on and off (`"enabled": false` in the `loot` section) before spending a leaderboard submission.

## 6. Prompt to paste into each component chat

```text
You are integrating one component into the Mech Royale bot v2. Work in the repo nshuai808/mech-royale (attach it if you do not have it; clone shallow).

Read first, in this order: docs/V2_MERGE.md (the integration contract and checklist), CLAUDE.md, README.md, kit/protocol.md, and your own proposal doc in the Claude project (claude/<your-component>.md). Branch v2-loot already contains the loot planner, params.json and the slot-aware fire logic; use it as the example of how a component is wired in.

Your task: merge YOUR component (the module you designed in this project, with its tests) into v2.
1. git switch -c v2-<component> origin/v2-loot
2. Copy your module and tests into the repo root as stdlib-only files. Do not add dependencies.
3. Add a params section for your knobs to params.json (snake_case, partial overrides allowed, defaults in your module).
4. Wire it into bot.py with the smallest possible hook: build your class in Bot.__init__ from hello["config"] and your params section; call it once per decision inside try/except so any failure falls back to v1/v2 behaviour; set only the action fields you own (see the ownership table in docs/V2_MERGE.md); never set take/drop (loot owns them); look up weapon slots with loot.slot_of instead of assuming fire=[gun, special]. Return goals to the arbiter instead of overriding move directly, and follow the goal priority in the guide. If another component is not merged yet, use the hook it defines (path_cost=, threats=) with a safe default.
5. Do not rewrite bot.py, reformat it, or touch other components' files. If your change needs a structural change to bot.py, stop and explain it instead of doing it.
6. Budget: your component must stay within its slice of the 50 ms decision (aim for under 5 ms typical, under 10 ms worst case); precompute from the map in the 20 s ready window; time-slice anything longer.
7. Verify and paste the results: your unit tests, python3 test_loot.py, python3 kit/check/check.py -- python3 -u bot.py (must PASS), python3 tools/replay.py -- python3 -u bot.py plus python3 tools/analyze.py on the new replay (no crashes, p99 answer time well under 35 ms). Say plainly what you could not verify; replays do not react to our actions, so they do not prove play strength.
8. Update docs/V2_MERGE.md (your row in the integrated-components table) and the status list in CLAUDE.md. Add one botlog.trace field if you need it; do not add trace calls.
9. Rebase onto origin/v2-loot, commit, push your branch. Do NOT merge to main and do NOT touch the survival-v1 branch.
10. Report: files changed, hook lines in bot.py, knobs that matter most, tests run with results, risks, and anything that will conflict with another component.

Constraints that always apply: 50 ms per decision on 1 CPU, no network, read-only disk (write only /tmp), stdlib only, never crash, freeze Sunday 9:00 AM ET, cutoff Sunday 11:00 AM ET. Score is mean of 16 minus place, so survival matters more than kills.
```
