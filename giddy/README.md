# giddy/: the bot this branch submits

This folder is **giddygiddyboy's Mech Royale bot** (Go, standard library only), used under its MIT License
(`LICENSE` here, Copyright (c) 2026 giddygiddyboy).

- Original: https://github.com/justnau/giddygiddyboy-mech-royale (the source is no longer published there).
- Taken from the unchanged mirror `blanc-team/try_again`, commit `c26c677` ("Import the giddygiddyboy Mech Royale
  bot unchanged"). The same code appears in other teams' repos as giddy commit `8b67d5b` (one parameter line differs).

## Our changes

| File | Change |
| --- | --- |
| `cmd/bot/main.go` | Bot name in `ready`: `umich-ibe` |
| `mech/duel.go`, `mech/brain.go` | Practice duels after 150 s compare firing from the current range with closing to lightning range and use nearby cover during weapon downtime. |
| `mech/brain.go` `upgradeOrderLaser` | practice only: laser_damage, laser_charge before plating, armor |
| `mech/brain.go` | `HealGate`/`HealFrom` (practice only, 0.6 from 150 s): below 60 % HP don't start a fight with a foe that isn't shooting us, isn't within 45 m, isn't below 30 % HP and isn't our current target (road-to-six #3) |
| `mech/brain.go` `observe` | robust's FFA-detector fix: an NPC kill doesn't count as a mech kill (no practice effect) |
| `mech/brain.go` | switch to the practice parameter set after 5 s (was 20 s) |
| `mech/brain.go` `squadParams` | practice tuning from upstream giddy `e19e3c8` as kept in [waiprotein/mech-royale-bot](https://github.com/waiprotein/mech-royale-bot) (MIT): Stick 200, LowBonus 200, HPw 0.18, `LethalK` 0.7 (new param: early laser release when dmg x 0.7 >= HP) |

Everything else is unchanged. Any later change goes in this table.

## Build and check

```sh
cd giddy && go build -o mechbot ./cmd/bot
python kit/check/check.py -- giddy/mechbot          # from the repo root
```

The top-level `Dockerfile` builds this folder.
