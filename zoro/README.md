> **In this repo (UMICH IBE):** an unchanged copy of Team Sulertia's V2 build (TEMOtkesh/mech-royale-bot, branch `v2`,
> commit `6da1573`), itself a fork of [zoro](https://github.com/Specz04/zoro) by Specz04. Both MIT; `LICENSE` is kept unchanged.
> Our changes: the bot name, and two free-for-all-only nuances that act once the lobby is a proven free-for-all
> (always after the cutoff), so practice play is unchanged: `FFAEngageAdd` 0.1 (start a hunt only at a slightly better
> advantage) and `FFALootRadius` 180 m (was 220 m: shorter loot trips across open ground). See `stance()` in
> `internal/pilot/threats.go`. The top-level `Dockerfile` builds this folder.

# zoro

A `mechfight/1` bot for the Builders Buildathon **Mech Royale** track. It pilots one mech in the
16-mech battle royale: it reads observations as JSON lines on stdin and answers each one with a single
action line on stdout.

Go, standard library only. It recognises practice lobbies and hunts the house squad there; in a
free-for-all it plays a careful, cover-first game.

## Layout

| Path | What it is |
| --- | --- |
| `cmd/zoro` | Protocol loop: answers only the newest observation, never writes anything else to stdout, has a fallback brain if the map cannot be loaded |
| `internal/wire` | `mechfight/1` message types and the command encoder |
| `internal/arena` | Map loading (`/arena/v2`), spatial buckets, terrain, ray casts, line of sight, tree cover |
| `internal/grid` | 2 m walk grid, A*/Dijkstra, connected regions, rooftop regions, top-surface routes, openness map |
| `internal/pilot` | The agent: memory, ballistics and lead, fight odds, dodging, cover, roofs, loot, zone, decision |

## Build

```sh
docker build --platform linux/amd64 -t zoro .
```

To build without Docker (Go 1.25 or newer):

```sh
go build -o zoro ./cmd/zoro
go test ./...
```

To run the kit's conformance check against the image, from the `mechfight-kit` folder:

```sh
python3 check/check.py --map-dir /arena -- docker run --rm -i --network none --cpus 1 --memory 512m \
  --read-only --tmpfs /tmp:rw,size=64m --user 65534:65534 -v "$PWD/arena:/arena:ro" zoro
```

## Runtime

- All map analysis runs before answering `hello`. Decisions take a few milliseconds at most.
- No network access, no files written.
- A panic inside a decision is caught and answered by repeating the previous movement, so the mech
  never goes silent.

## License

MIT. See `LICENSE` (it also carries the notice of the MIT project this was originally derived from).

## Team Sulertia changes (fork notice)

Based on [zoro](https://github.com/Specz04/zoro) by Specz04, MIT licensed (see `LICENSE`, kept unchanged).
Changes, all limited to practice games against the house squad (free-for-all play is unchanged):

- `SquadDamageFirst`: against the squad, upgrades are taken damage first (drum magazine, lens, tungsten, capacitors, rotary feed) before plating and armor.
- `SquadRetreatHP` 0.2 → 0: no low-health retreat from the squad.
- `SquadNoRetreat` (on)
- `SquadTiers`: house bots are weighed by their likely tier (easy → expert) from how many are already dead.: never break off a fight against the squad.
- `FFAClock`: after the submission cutoff every match is played as a free-for-all from the first tick.
- `SquadLook`: between fights the torso sweeps around the nearest recently seen squad member, so hunters are spotted at 200 m.
- Practice upgrade order: sensors (+25 m vision) right after drum magazine and lens: vision, not range, limits the laser.
- `SquadHunt` 80, `SquadHuntLaser` 100: only hunt nearby squad members (do not wake idle ones).

> Re-roll 1: same code as `627ffea` (5.84 on 22 Nov 9:50 AM ET), re-submitted for a fresh set of practice seeds.
> Re-roll 2: same code again, another fresh set of practice seeds.
