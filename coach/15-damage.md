# Codex brief: swing 4b "damage build" (branch `t15-damage`)

Your worktree is now on branch `t15-damage` at `integ-3` (`6bb23c4`, **3.71 real, our best**). Deliver as a bundle
`replays\t15-damage.bundle`. This part is **sim-blind** (the sim has no upgrades or lightning): build it carefully, prove it with
unit tests on synthetic observations, and run the gates. A real practice submission will judge it.

## Ground truths (real practice)
Every change that gave up damage lost (laser_flee 2.92, gun_aim 3.33, heal_gate 3.17/3.29). A tank-first upgrade order (swing 1)
was neutral (3.65). Lightning: 60 dmg per 0.25 s = **240 dps**, can't miss inside 45 m and a 30° cone, chains to 2 more within 14 m,
3 energy/shot. Gun: ~190 dps, needs lead, misses. Real upgrade list: `hello.config.upgrades` (kit/check/stream.jsonl.gz first line).

## Build (two flags in `params.json`; off = exactly integ-3)
1. **`dmg_build`**: upgrade picks damage-first: weapon upgrades for the weapon we deal most damage with (lightning_efficiency,
   lightning_chain, lightning_range; laser_damage, laser_charge; gun_damage, gun_rate), then plating, armor, capacitor (lightning
   ammo), nanites, the rest. Touch `_pick_upgrade` only.
2. **`lt_close`**: today the bot closes in to lightning range only if HP > 50%, exposed enemies <= 1, energy > 35 and target > 40 m
   (`Bot.act`, "close in"). Make it more willing: HP > 35%, allow 2 exposed if the target is below 50% HP, keep the energy gate,
   and don't boost the last 25 m (arrive with energy for the arc). Touch only that "close in" block.
Unit tests: a `test_damage.py` with synthetic offers and observations covering both flags (run with stdin closed:
`.\.pyrt\python.exe test_damage.py` from PowerShell reads no stdin; if anything hangs, it's the `bot` import reading stdin).

## Gates
All `test_*.py` ok, `kit\check\check.py -- .\.pyrt\python.exe -u bot.py` PASS, `tools\fuzz.py` 0 exceptions. One `--ffa` seed
(default sim) to confirm nothing breaks movement. Bundle with both flags **on**. Report under 15 lines.
