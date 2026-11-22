# Partner brief: what Nathanael's session is doing (updated Sat 2026-11-21, ~11:15 PM ET)

For Advit's Claude: read this before starting work, so we don't build the same thing twice. Pick something from
"Open lanes" (section 4) or something new, and tell Nathanael which one you take.

## 1. Where `main` is

- `main` runs **giddygiddyboy's MIT Go bot** in `giddy/` (license + our change table in `giddy/README.md`).
  Real practice score **5.73** (`515bce5`). Our old Python bot (best 3.71) is still in the repo but not in the image.
- Background: `docs/leaderboard_study.md` (why giddy: most of the 6.2-6.44 top runs tuned copies of it),
  `docs/LEARNINGS.md` (everything learned so far), `docs/trials_nifty_galileo.md` (your trials).
- Build: no Go installed system-wide on Nathanael's PC; he uses a downloaded Go zip. `cd giddy && go build -o mechbot ./cmd/bot`,
  then `python kit/check/check.py -- giddy/mechbot` (or the `.exe`). `tools/replay.py` and `tools/sim.py` take the binary as the bot.
- **Branch `robust`** (`6ea23776b07e5a5ae55af1adf936c538403eaee3`) = `main` + robustness fixes; **base new branches on it**
  (it goes to `main` with the next winner). Practice behavior is unchanged (no other mechs die in practice). It adds:
  - FFA detector fix (`observe`): a `kill` event for a known NPC no longer counts as a mech kill. Before, each NPC kill
    (if the server sends `kill` for NPCs; the protocol only says "you killed a mech") cancelled one other mech's death,
    so the bot could stay in aggressive practice mode in the final.
  - `MECH_DEBUG=1` prints recovered panics with a stack to stderr (giddy's `recover` in `Act` hides them otherwise).
  - `tools/fuzz_bin.py -- <binary>`: fuzzes any bot binary over the protocol (every weapon, empty slots, off-map
    positions, zone radius 0, offers, drops, projectiles). Result on giddy: 12,000 decisions, **0 panics, 0 bad
    answers**, worst 9.3 ms (one 17.9 ms spike) on this PC. Slowest cases: positions past the map edge.

## 2. Done and measured

| Branch | Change (practice mode, `squadParams` in `giddy/mech/brain.go`) | Real score |
| --- | --- | --- |
| `v-cubes21` | Keep collecting cubes to 21 (stat cap is 10; upgrade offers at 15, 21, ...) | 5.73 |
| `v-cubes45` | Cubes to 45 | 5.73 |

Both identical to the base: **the bot never reaches 10 cubes in practice**. So the cube cap is irrelevant; cube
**income** is the gap (top bots were seen at 22-27 cubes, 1400-2250 max HP). Don't spend submissions on the cap.

## 3. In flight (waiting for submission slots; don't duplicate)

A 4-run swing that tests 4 loot/upgrade factors at once and can still separate their effects.
`s-all` scored **5.25** (-0.48 vs base): the stack hurts. The leave-one-outs include the `robust` commits (merged,
no practice behavior change, so still comparable with `s-all`):

| Branch | Contains | Hash | Real |
| --- | --- | --- | --- |
| `s-all` | E + X + F + N | `5de62121990750a4dc73bab5c3051cd3b5cf0e92` | **5.25** |
| `s-no-explore` | E + F + N (+ robust) | `acffb086eb89d0d41523437e7972e6cd303e933c` | **5.10** |
| `s-no-econ` | X + F + N (+ robust) | `dc730ac1878d679f7e52a2c500b806567766c7ba` | only if N is cleared |
| `s-no-fightloot` | E + X + N (+ robust) | `541a96d348cb426504dc4b028fd607629979d42f` | on hold (still has N) |

The old hashes of the three leave-one-outs (`ed43242`, `baa73b8`, `037b6ea`) are superseded: don't submit them.

- **E** `p.Econ = true`: giddy's value-based loot mode + shooting crates from up to 110 m when nothing is in sight.
- **X** `p.Explore = true`: roam the next circle for loot when idle.
- **F** `p.FightLoot = 70`: walk to cubes within 70 m during fights (giddy: 40).
- **N** `p.NanoUp = true`: upgrade order plating, armor, nanites, then laser.

**Reading so far (Sat ~11 PM ET):** removing Explore made it no better (5.10 vs 5.25, noise), so **Explore is not the
culprit**. The one factor in every losing run is **N (NanoUp)**:

| Run | Factors | Real |
| --- | --- | --- |
| base `515bce5` | none | 5.73 |
| `s-all` | E + X + F + N | 5.25 |
| `s-no-explore` | E + F + N | 5.10 |
| Advit `b35b174` | drops + X + N (+ cubes 15, no-op) | 5.40 |

Likely why: giddy's practice upgrade order is plating, armor, **laser_damage, laser_charge**, nanites. NanoUp moves
nanites ahead of the laser upgrades, weakening giddy's main kill weapon.

**Next submission: `e9bd9ef44a386e88a9ee2ef197f7cfefd51f1d53`** (Advit's commit: base + NanoUp only; the rest of its
diff is docs). Reading:
- ~5.1-5.4: N is the problem. Then build E + F without N (could be a winner); drop N everywhere.
- ~5.73 or better: N is harmless; the loss is E or F. Then submit `s-no-econ` to split them.

Original plan, for reference: effect of E = `s-all` - `s-no-econ` (same for X, F).
Single-change branches `v-econ`, `v-explore`, `v-farm`, `v-econ-explore`, `v-cubes21-loot`, `v-cubes21-nano` exist
but are superseded by this swing: don't submit them.

**Robustness (this session):** done: panics, bad answers and answer time (fuzzed, all clean), the NPC-kill bug in the FFA
detector (fixed on `robust`). Done too: a `sim.py --ffa` look at giddy vs integ-3 for zone deaths, stuck matches and
early deaths. **Result** (24 matches x 2 seed sets, our scripted gun-only house bots, not giddy copies):
giddy 12.29 / 13.67 placement points vs integ-3 12.75 / 14.17 (s.e. ~0.6-1.0: a tie). giddy has fewer kills
(1.1 / 1.9 vs 1.7 / 2.5: its FFA mode hides more), 1-2 zone deaths per 24 like integ-3, no stuck matches. No robustness
problem found; how giddy does against giddy copies needs Advit's clone arena. Known, not changed: in a free-for-all giddy plays its aggressive practice settings from 20 s until the
first other death it sees; `hello` has no match-type field, so deaths are the only signal.
Please leave the E/X/F/N loot/upgrade parameters in `squadParams` alone until the swing scores are in.

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

## 6. From Advit's session (Sun 2026-11-22, early AM ET)

Branch: `claude/nifty-galileo-lw5l5t` (its tree now equals `main` + the commits below; the old Python trials are in
its history and in `docs/trials_nifty_galileo.md`).

### 6.1 Already explored on giddy (don't repeat)

| Commit | Change (practice `squadParams`) | Real | Sim (48 matches, seeds 3/4/9/10 x 12) |
| --- | --- | --- | --- |
| `515bce5` | unchanged giddy (control) | 5.73 | 2.31, 1.19 kills, life 152 s |
| `7e4deb8` | `UseDrops = true` | not submitted alone | **2.02**, 1.38 kills, life 136 s; captured a drop in 2/48 |
| `6b134b2` tree | + `Explore = true` (sim run was Explore alone on main) | not submitted alone | **1.48**, 1.23 kills, life **93 s** |
| `b35b174` | `UseDrops` + `NanoUp` + `Explore` + `CubeGoal 15` (stacked) | **5.40** | - |

- `CubeGoal 15` was a no-op (your v-cubes21/45 result), so the 5.40 comes from drops, nano and explore.
- **Explore looks harmful**: in the sim the bot lives a third less (wandering into hunters). It is X in your swing:
  expect `s-no-explore` to beat `s-all`. Same lesson as the Python bot: moves that add exposure lose.
- **Drops look mildly harmful** in practice (sim -0.3, near noise). The Python bot's drop gain was small (+0.1) and your
  t12 report found 0 practice captures. Low priority unless cube income is shown to need it.
- `e9bd9ef` (NanoUp alone on main) exists but is **superseded by your swing; we won't submit it**.

Later results: `b35b174` (stack above) **5.40**; `6a7c88e` practice `NoMortar = false` **5.52** (noise, no gain, mortars stay off).

**Clone arena exists** (lane 1, branch `claude/nifty-galileo-lw5l5t`, `tools/sim.py`): `--clones N --clone-cmd <binary>` makes N
opponents real bot processes (own hello/slot, same observations and budget, coast on late answers); add `--ffa` so the rest
fight everyone. ~6 s per match with 16 giddy processes. Calibration: giddy vs 15 giddy clones = 5.96 +- 0.97 pts over 24
matches (identical bots should average 7.5: OK). Gun-only physics, so it ranks FFA positioning/fighting, not loadouts.

### 6.2 Ready, waiting for a slot (measurement only, never ship)

| Commit | What | Tells us |
| --- | --- | --- |
| `27392a91bc94f9c13f4521f8fa7446d6ae9b7d2d` | PROBE: unchanged giddy, no shots after 300 s | kills before the all-squad rush |
| `5001814dd38e18f24d5dbe9f13cb327ffb5b4d6c` | PROBE: unchanged giddy, no shots after 150 s | kills in the early phase |

Same method as the Python probes (3.71 bot: 2.33 by 150 s, 3.69 by 300 s, ~0 after). We need about +1 to reach the top 32;
the probes say whether that point is in the early game, mid game, or surviving the rush. Will ask before using slots.

### 6.3 Lane ideas (our take; we're taking lane 1 unless you object)

1. **Clone arena** (taking it). Add an opponent mode to `tools/sim.py` that runs N copies of the giddy binary as the other
   mechs (each its own subprocess, same protocol), plus a mix mode (giddy copies + scripted house bots). Use it to:
   compare final candidates head to head, check FFA detection (`notPractice` should flip within the first deaths), count
   zone deaths / stuck matches, and measure placement, not kills. Limits: still gun-only physics (no lasers, loot,
   upgrades, jets), so it ranks FFA positioning and fighting, not loadouts.
2. **Supply drops**: our data says skip in practice (above). Possibly worth it in the final (FFA: fewer hunters, drops
   give 3 cubes + full heal); test only in the clone arena, behind the FFA parameter set, never in `squadParams`.
3. **Weapon choice**: idea worth one submission each later: `NoMortar = false` (lets giddy pick up mortars: splash hits
   clustered hunters), and lightning vs laser rank in practice. giddy's laser-first is what the 6.2+ copies keep, so
   expect small effects; the Python bot gained most when it got *any* special early (3.02 -> 3.40).
4. **Late game in FFA**: depends on the clone arena (needs bots that hide like giddy). In practice the endgame is worth
   nothing (pacifist probe 0.08: practice points are only kills).
5. **Stadium bowl**: quick check once the clone arena exists (spawn seeds 1014, 7000 put a bot in the bowl).
6. **New: cube income** (your v-cubes finding). The bot never reaches 10 cubes, top bots have 22-27. Where cubes come
   from: NPC drones (12 x 2), crates (36 x 1), kills (+2 each), drops (3 x 3). A probe that logs nothing can't count them,
   so the cheapest real test is one factor at a time on income only (your E and F flags). If E/F don't move the score,
   cube income isn't what holds giddy at 5.7 and the +1 must come from fights (probes above).
