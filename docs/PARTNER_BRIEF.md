# Partner brief: what Nathanael's session is doing (Sat 2026-11-21, ~10:30 PM ET)

For Advit's Claude: read this before starting work, so we don't build the same thing twice. Pick something from
"Open lanes" (section 4) or something new, and tell Nathanael which one you take.

## 1. Where `main` is

- `main` runs **giddygiddyboy's MIT Go bot** in `giddy/` (license + our change table in `giddy/README.md`).
  Real practice score **5.73** (`515bce5`). Our old Python bot (best 3.71) is still in the repo but not in the image.
- Background: `docs/leaderboard_study.md` (why giddy: most of the 6.2-6.44 top runs tuned copies of it),
  `docs/LEARNINGS.md` (everything learned so far), `docs/trials_nifty_galileo.md` (your trials).
- Build: no Go installed system-wide on Nathanael's PC; he uses a downloaded Go zip. `cd giddy && go build -o mechbot ./cmd/bot`,
  then `python kit/check/check.py -- giddy/mechbot` (or the `.exe`). `tools/replay.py` and `tools/sim.py` take the binary as the bot.

## 2. Done and measured

| Branch | Change (practice mode, `squadParams` in `giddy/mech/brain.go`) | Real score |
| --- | --- | --- |
| `v-cubes21` | Keep collecting cubes to 21 (stat cap is 10; upgrade offers at 15, 21, ...) | 5.73 |
| `v-cubes45` | Cubes to 45 | 5.73 |

Both identical to the base: **the bot never reaches 10 cubes in practice**. So the cube cap is irrelevant; cube
**income** is the gap (top bots were seen at 22-27 cubes, 1400-2250 max HP). Don't spend submissions on the cap.

## 3. In flight (waiting for submission slots; don't duplicate)

A 4-run swing that tests 4 loot/upgrade factors at once and can still separate their effects:

| Branch | Contains | Hash |
| --- | --- | --- |
| `s-all` | E + X + F + N | `5de62121990750a4dc73bab5c3051cd3b5cf0e92` |
| `s-no-econ` | X + F + N | `ed432426c21a66026ae00786069e4d8842a27e33` |
| `s-no-explore` | E + F + N | `baa73b89578490f1eb3346b4bfb9023518924ff9` |
| `s-no-fightloot` | E + X + N | `037b6eaa28e8d1c823c5be3a135b3aeb738840dc` |

- **E** `p.Econ = true`: giddy's value-based loot mode + shooting crates from up to 110 m when nothing is in sight.
- **X** `p.Explore = true`: roam the next circle for loot when idle.
- **F** `p.FightLoot = 70`: walk to cubes within 70 m during fights (giddy: 40).
- **N** `p.NanoUp = true`: upgrade order plating, armor, nanites, then laser.

Effect of E = `s-all` - `s-no-econ` (same for X, F); N = sum of the 3 leave-one-outs - 2*`s-all` - 5.73.
Single-change branches `v-econ`, `v-explore`, `v-farm`, `v-econ-explore`, `v-cubes21-loot`, `v-cubes21-nano` exist
but are superseded by this swing: don't submit them.

**Next in this session:** robustness for the final (free-for-all against other teams' bots), not practice score:
how giddy tells practice from FFA (`observe()`: `otherDead`, `notPractice`, `squadParams` after 20 s), panics
(swallowed by `recover` in `Act`), worst-case answer time, a quick `sim.py --ffa` look for zone deaths / stuck matches.
**Please leave these to us**, and leave the E/X/F/N loot/upgrade parameters in `squadParams` alone until the swing scores are in.

## 4. Open lanes (nobody is on these)

1. **Clone arena**: a local sim where the opponents are copies of the giddy binary (the real final field is mostly
   giddy copies). Today `tools/sim.py` only has our scripted house bots. The most useful tool for picking the final entry.
2. **Supply drops in giddy**: `UseDrops` is off in giddy. Drops give 3 cubes + full HP/energy (70/140/210 s). Our
   Python `drops.py` worked in practice; giddy's drop logic is in `chooseLoot` (`o.Drops`). Cube income + HP.
3. **Weapon choice**: top bots keep the gun + one special (azing laser, tigerbyte mortar, kyoto-max lightning).
   giddy is laser-first and never picks up a mortar (`NoMortar`). Is lightning or mortar better for some phases?
4. **Late game / zone endgame in FFA**: giddy's Ghost mode (home spot by exposure) when every bot hides like giddy.
5. **Stadium bowl stuck pocket** (`docs/stuck_pocket.md`): does giddy get stuck there too?

## 5. Rules and gotchas

- **4 submissions per hour for the whole team.** Tell Nathanael before you submit, so we don't burn each other's slots.
  Log every score in README's Submissions log. Freeze **Sun 9:00 AM ET**, cutoff **11:00 AM ET**.
- Work on branches; `main` changes only when something clearly beats 5.73 (noise is about ±0.25 per submission;
  the scorer is deterministic per commit, so an identical score means no behavior change at all).
- One change per branch, or a designed swing like section 3, so results can be attributed.
- giddy files in the working copy have CRLF line endings on Windows: string edits that assume `\n` silently do nothing.
- In `squadParams`, later lines override earlier ones (`p.FightLoot = 40` is set twice); put overrides last.
- Windows Application Control on Nathanael's PC sometimes blocks a freshly built `.exe`; that's the machine, not the bot.
- Don't copy from repos that opted out of AI use (one top repo has an `AGENTS.md` asking that). giddy is MIT; keep its
  `LICENSE` and credit.
