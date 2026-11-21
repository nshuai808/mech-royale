# CLAUDE.md: context for Claude Code sessions on this repo

Nathanael's bot for the Builders Buildathon **Mech Royale** track (UMich IBE team). Read `README.md` for
layout and limits, and `kit/protocol.md` for the full rules. This file is the short version plus where we are.

## The game in five lines
- 16 mechs, OSU campus map, shrinking zone (closes ~6:55, match max 8:00). Bot answers JSON obs with a JSON action.
- Score = mean of `16 - place` over 48 practice matches. **Placement beats kills.** Baseline 1.15.
- Practice opponents: 15 house bots acting as one squad that **hunts us, weakest first**. The final is a
  free-for-all against other teams' bots, so prefer robust behavior over exploits of the house bots.
- Decision every 0.1 s, **50 ms wall-time budget on 1 CPU**. Late = coast 1 s without firing, then idle.
- Matches show us nothing but the score: **no stderr, no logs**. Local tools are our only visibility.

## Rules that matter most for strategy (protocol.md)
- Zone: `obs.zone` gives current and next circle + shrink window; outside = `dps` HP/s, no regen.
- HP regen 45/s after 5 s without dealing or taking damage (not outside the zone).
- Rear hits (outside 180° front arc of torso aim) do x1.5: face attackers.
- Vision: 45 m all around + 200 m in a 120° wedge of torso aim; buildings block, trees partly. Sounds give bearing (+-7°) and near/mid/far.
- Weapons: gun (start), mortar (lob, splash, concussion), laser (charge, hitscan, telegraphed), lightning (45 m cone, chains).
  Triangle: laser > mortar > lightning > laser. Trees don't stop shots.
- Cubes: +4% HP/dmg each (cap 10), but +5% size each (easier to hit). Thresholds 1,3,6,10,... give upgrade offers (`pick`, default 0 after 5 s).
- Supply drops at 70/140/210 s inside the next circle: stand alone 4 s for 3 cubes + full HP/energy.
- `alive` in obs = our place if we died now.

## Local tools (tools/, stdlib only, not in the Docker image)
| Command | What |
| --- | --- |
| `python3 tools/replay.py -- python3 -u bot.py` | Feed the kit's 300 recorded observations to the bot, lockstep; log actions, traces, answer times |
| `python3 tools/replay.py --repeat 3 --map-dir /arena -- docker run --rm -i --network none --cpus 1 --memory 512m --read-only --tmpfs /tmp:rw,size=64m --user 65534:65534 -e MECH_TRACE=1 -v "$PWD/kit/arena:/arena:ro" mech-royale` | Same, inside the match sandbox: the real timing test |
| `python3 kit/check/check.py -- python3 tools/record.py -- python3 -u bot.py` | Conformance check, recorded |
| `python3 tools/analyze.py replays/<file>.jsonl.gz [--csv out.csv]` | Report: timing, HP, zone, damage by weapon/attacker, rear hits, loot, modes, last seconds, timeline |
| `python3 tools/analyze.py --diff A.jsonl.gz B.jsonl.gz` | Where two bot versions decided differently on the same stream |

- `record.py` wraps any bot command transparently, so it will also work with a simulator if we build one.
- In the bot, call `botlog.trace(tick, mode=..., **fields)` once per decision. Off unless `MECH_TRACE=1`
  (the tools set it), so it costs nothing in matches. `analyze.py` reports time per mode and mode switching.
- Replay files go in `replays/` (gitignored). Format documented in `tools/replaylog.py`.
- **Caveat:** replayed observations don't react to our actions. In a replay report, HP, damage, zone and
  death are the original recording's; only answer times, actions and modes are ours. Replays test timing,
  crashes and decisions, not play strength. Play strength = practice submissions (or a future simulator).

## Merging components into v2
See `docs/V2_MERGE.md`: what v2 contains, the integration contract (action-field ownership, goal priority, params, budgets), a merge checklist, the `survival-v1` conflict, and the prompt to paste into each component chat.

## Workflow
- `main` is what gets scored. Experiments on branches; merge after `check.py` passes.
- Before every submission: `check.py` locally, then the docker replay above, and look at p99 answer time (keep it well under 35 ms).
- Log every submission (commit, score, change) in README's Submissions log. 4 submissions per hour max.
- Never force-push or delete a submitted commit; the repo must stay public until results are out.
- Freeze by **Sun 9:00 AM ET**; cutoff **Sun 11:00 AM ET**.

## Status / next steps
- [x] Repo set up from the Python starter (`bot.py` = kit example bot + a `botlog.trace` call).
- [x] Logging harness: `tools/record.py`, `tools/replay.py`, `tools/analyze.py`, `botlog.py`.
- [ ] Submit the unmodified starter once to confirm the pipeline (expect ~1.15).
- [ ] Survival core: zone-aware movement with margin, cover / line-of-sight breaking, retreat + regen when hurt.
- [x] Loot + weapon pick v1 (branch `v2-loot`): `loot.py`, knobs in `params.json`, straight-line walk to loot goal (no nav yet). Mortar base value is 0 until a ballistic aim solver exists.
- [x] Upgrade policy (branch `v2-upgrades`): `upgrades.py`, `test_upgrades.py`, knobs in `params.json` `upgrades`. Ranks the 3 offered upgrades by marginal combat-power gain (gun_mag, plating, then weapon upgrades first; nanites mid-tier until a retreat-and-heal routine exists, then raise `regen_cycles`). Sim-validated only.
- [ ] Charge-laser handling, mortar lobs.
- [ ] Squad handling: avoid being the weakest visible target; third-party instead of first contact.
- [ ] Timing guard: fall back to a cheap action if a decision runs long.
- [ ] Maybe: a crude local simulator (map collision + zone + simple enemies) so play strength can be tested offline.
