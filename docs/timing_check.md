# Session C: timing and packaging check (2026-11-21)

Bot code checked: `main` at `a2d0541` (bot code = `ac6e281`, real score 3.6).

## No Docker was available, so this is an approximation
Docker is not installed on Windows or in WSL, and WSL needs a sudo password to install it. Instead:
- **Image contents:** `git archive HEAD`, then `.dockerignore` applied, in WSL Ubuntu. That gives the same files `COPY . .` would copy.
- **Sandbox (`~/mrt/sandbox.sh` in WSL):** bot folder and arena `chmod a-w`, cwd `/`, clean env with `PYTHONDONTWRITEBYTECODE=1`,
  pinned to one core with `taskset`, address space capped with `prlimit`. No network namespace (no root), but the bot imports
  no networking modules.
- **Python:** WSL has 3.14.4 and the image uses 3.13.18, so check, fuzz and unit tests were also run on Windows Python 3.13.15.
- **Not covered:** the scorer's CPU speed, CFS quota throttling under `--cpus 1`, and the real `--read-only` root. Run the
  real Docker commands from `README.md` once on a machine that has Docker.

## Results
| Test | Hello (ready) | p50 | p90 | p99 | max | > 35 ms | > 50 ms |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `check.py`, sandbox, 1 core | 590 ms | 3.5 | 4.4 | 8.4 | 10.2 | 0 | 0 |
| `replay.py --repeat 3`, sandbox (3 passes) | - | 3.3-3.6 | 3.8-4.9 | 7.8-9.5 | 8.0-10.9 | 0 | 0 |
| `check.py`, sandbox, **half a core** (busy loop on the same core) | 1199 ms | 5.2 | 8.6 | 14.9 | 21.6 | 0 | 0 |
| `replay.py --repeat 2`, half a core | - | 5.6-6.4 | 9.4-9.7 | 15.0-18.1 | 18.9-22.6 | 0 | 0 |
| `sim.py --ffa` 6 matches, 1 core, long matches (217 s, 272 s) | ~530 ms | 0.9-1.0 | **21.3-21.4** | 22.0-22.4 | **30.0** | 0 | 0 |
| `sim.py --ffa` same long matches, **half a core** | - | 1.0 | 22.1-25.3 | 29.6-29.8 | **35.7+** | **5 + 1** | 0 recorded |
| `fuzz.py` (1 core, WSL / Windows 3.13) | - | - | - | - | 7.6 / 11.3 | - | - |

- Map build at hello: about 0.6 s on one core, 1.2 s on half a core. The budget is 20 s.
- Peak memory (RSS): **25 MB** (limit 512 MB).
- Writes: none under the bot folder after the runs. Nothing needs `/tmp`.
- `check.py` PASS (sandbox and Windows 3.13), `fuzz.py` 0 exceptions, `test_zone.py` and `test_drops.py` pass.
- Repo: 2.2 MB working tree, 330 KB packed (limit 20 MB). Image payload: about 120 KB of Python.

## The one timing risk: roam-mode A* runs at its cap for seconds at a time
The kit stream (37 s) and short sim matches answer in 2 to 10 ms. Long matches don't: more than 10% of ticks take 21 to 30 ms,
in runs of up to 108 consecutive ticks (11 s). Almost all of those ticks are `roam` mode (342 of 343 slow ticks in one match;
599 roam + 139 drop of 740 in the other).

Cause (reading the code, not changed): `roam` picks a random point (`bot.py` ~245). `_go_point` starts an `AStar` and steps it
with `deadline - now - 8 ms`, which is about 20 ms per tick (`BUDGET_S` = 28 ms). If the point is unreachable, A* expands up to
`max_expand` = 60000 nodes, which takes many ticks, ends with no path, and then the replan condition
(`self.path is None and self.job is None`) starts the same search again. The bot walks the straight line in the meantime, so
its behavior is unaffected, but it burns ~20 ms per tick for up to the 20 s roam window.

Why it matters: the budget is wall-clock, so A* itself stops on time even on a slow CPU, but everything else in the tick then
runs after 20 ms instead of after 1 ms. On half a core the worst ticks crossed 35 ms (6 times in two long matches; the sim was
run with `--budget-ms 35`, so values above 35 are not recorded). None were seen above 50 ms. On a scorer CPU much slower than
this laptop, roam ticks are the ones that would time out first.

Suggested fixes (behavior-adjacent, so not done here; each should go on its own flag):
1. Pick roam points with `m.nearest_free` or reject points whose nav cell is blocked, and don't restart a failed search for the
   same goal (remember failed goals for a few seconds).
2. Or lower the A* slice: e.g. `deadline - now - 16 ms` (about 12 ms per tick), which caps a tick near 20 ms. This only slows
   path planning, which is already incremental.

## Packaging
- Imports in the image: `bot.py` imports `botlog`, `drops`, `mechfight`, `roof`, `zone` and `nav`, all copied. `roof.py` is
  still needed (imported at top level) even though `roof.enabled` is false, and the planner is not built when disabled.
  The other modules import only the standard library.
- Stale files in the image: `test_zone.py` and `test_drops.py` were copied but never imported. **Fixed:** added `test_*.py` to
  `.dockerignore`. The image without them passes `check.py` in the sandbox. Harmless leftovers still copied: `Dockerfile`,
  `.dockerignore`, `.gitattributes`, `.gitignore` (a few hundred bytes).
- `.gitattributes` forces LF, and the `ENTRYPOINT` uses `python3 -u /bot/bot.py`, as the scorer expects.
