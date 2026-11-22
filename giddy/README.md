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
| `mech/brain.go` `observe` | `kill` events for known NPCs no longer count as mech kills (they would hide other mechs' deaths from the FFA detector) |
| `mech/brain.go` `Act`, `cmd/bot/main.go` | With `MECH_DEBUG=1`, recovered panics are printed to stderr with a stack (local tools only; off in matches) |
| `mech/brain.go` | new `LaserHold` (practice only, 1 s): when the target drops out of view mid-charge, keep holding aimed at its last centre instead of releasing into the idle aim |
| `mech/brain.go` `upgradeOrderLaser` | practice only: laser_damage, laser_charge before plating, armor |
| `mech/brain.go` `squadParams` | `AllFoes = true`, `EngageDist = 90`, `CrowdHide = false` (practice only) |

Everything else is unchanged. Any later change goes in this table.

## Build and check

```sh
cd giddy && go build -o mechbot ./cmd/bot
python kit/check/check.py -- giddy/mechbot          # from the repo root
```

The top-level `Dockerfile` builds this folder.
