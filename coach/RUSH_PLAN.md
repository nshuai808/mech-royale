# Big-picture plan: build up power, then beat the 5-minute rush

## What we know (real practice, not sim)
- Kills by time: **2.33 by 150 s, 3.69 by 300 s, 3.71 total**. Nothing after 300 s, when the remaining ~11 house bots hunt us at once.
- The leader is over 6. Score ≈ house bots that die before us ≈ our kills. So +2.5 kills are needed, and the rush (worth ~0 now)
  is where they are.
- What has won for real: power and loot (2.90 -> 3.56), firepower and better execution (evade_unstick 3.71).
  What has lost for real: caution and disengaging (heal_gate 3.17/3.29, laser_flee 2.92) and holding fire (gun_aim 3.33).
- The sim misjudged 4 of 5 practice changes. Use it only for movement, positioning and the rush (it models the rush, gun-only).

## Why the rush kills us (arithmetic)
Base 1400 HP. 10 cubes -> 1960 HP and +40% damage. One house gun = 45 dmg / 0.24 s ≈ 190 dps. Three shooting at once ≈ 560 dps:
**3.5 s to die even at 10 cubes in the open.** No build tanks the rush in the open. Beating it needs **geometry** (attackers see us
one or two at a time, in front of us) **plus maximum power** (cubes, upgrades, full HP and energy at 300 s) **plus area damage**
(lightning chains to 2 more within 14 m; mortar splash) on a converging pack.

## Resources on the map (protocol)
| Source | Count | Cubes | Notes |
| --- | --- | --- | --- |
| NPC drones | 12 | 2 each | 350 HP; only shoot attackers, or mechs within 45 m of home. Easy with lightning. |
| Crates | 36 | 1 each | 300 HP; half drop a weapon. |
| Supply drops | 3 (70/140/210 s) | 3 each | + **full HP + full energy**. Drop 3 lands ~235 s: perfect rush prep. |
| Kills | each hunter | its cubes + 2 | snowball |
Upgrade offers at 1, 3, 6, 10, 15, 21 cubes. Stats cap at 10 cubes; size keeps growing +5% per cube (easier to hit).

## The plan, by phase
**A. Opening (0-90 s): power first.** Off spawn sight (done), take a special (lightning first), farm the nearest NPCs and crates on the
way. Target: **6 cubes by ~90 s** (3 upgrades). Lever: farm reach and order (NPCs give 2 cubes for ~350 HP, the best cube per second).
**B. Hunter phase (90-240 s): kill each hunter from cover, take its cubes, take drops 2 and 3.** Target **10 cubes and full HP at 240 s**.
Lever: drop capture rate (the sim models drops), and collecting kill cubes right after each kill.
**C. Fortress (240-300 s):** full HP and energy, at a spot inside the circle with walls behind/beside and a short lane in front,
facing the squad's side. (Codex 1 is building this now: `rush` flag.)
**D. Rush (300 s+): fight from the fortress, never flee into the open.** Laser on the approach (280 m, 315 dmg), lightning when they
bunch inside 45 m (chain-aware aim), gun in between, energy saved for lightning (`lt_energy`, scoring now).

## Who does what
- **Codex 1:** C and D positioning: `rush` (running; sim measures kills after 300 s and share alive at 300/360 s).
- **Codex 5:** B: supply drops. Capture rate of drops 2 and 3 in the sim and fixes (it models drops and rival bots).
- **Claude:** A and D firepower (sim-blind, logic): NPC/crate/cube farming order and reach, upgrade picks for a tanky rush build,
  chain-aware lightning aim.
- **Submissions:** one change at a time on integ-3, kept only if real practice rises; then stack the winners and score them together.
