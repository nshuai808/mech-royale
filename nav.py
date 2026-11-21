"""nav.py: navigation + stealth (H-NAV, H-STL). Standard library only.

Owns: turning a goal into a movement direction on the real map (walls, ledges, slopes, clearance for the
2.5 m mech), stuck recovery, `path_cost` for the loot planner, and the stealth rule (hold still / creep
under 5 m/s). Does NOT own: which goal to chase (zone, loot, retreat), aiming, firing, take/drop.

Usage inside a bot (see bot.py):

    nav = Navigator.create(hello, NavParams.from_dict(p.get("nav")), StealthParams.from_dict(p.get("stealth")))
    d = nav.step(obs, goal_xyz, default_goal=True)         # NavDecision; d.move None = "no opinion"
    loot.step(obs, path_cost=nav.path_cost)

Design (numbers measured on the real map, see claude/nav-stealth-plan.md):
- The map is identical every match, so the grid is baked offline into `navmap.bin` (tools/bake_nav.py)
  and verified by a hash of world.json + terrain.i16. Hash mismatch or missing file: rebuild at runtime
  inside the 20 s ready window (about 3-5 s), with a deadline; on failure nav is simply off.
- Grid: 4 m cells built from a 2 m grid. A cell is blocked if its centre is within radius + margin of any
  wall prism (exact edge distance, not sampled). Edges carry directional "ledge up > step_up" flags, so
  slopes over 50 deg and ledges over 1.2 m are not walkable (at 1 m terrain spacing both are one test).
- Search: A* from the goal outward with parent pointers (so the path is the parent chain from our cell),
  cost = length * (1 + open_weight * openness^exp) plus optional threat/penalty terms. Time-sliced: a
  tick spends at most `slice_ms` on it; until a path exists the caller keeps v1 straight-line walking.
- Failure rule: anything unexpected returns "no opinion" (move None), never raises out of step().
"""
from __future__ import annotations

import array
import hashlib
import heapq
import json
import math
import os
import sys
import time
import zlib
from dataclasses import dataclass, fields
from typing import Callable, Dict, List, Optional, Sequence, Tuple

CELL = 4            # field grid, metres
SUB = 2             # build grid, metres (CELL = 2 * SUB)
EXPO_CELL = 8       # static exposure grid, metres
BAKE_VERSION = 1
S2 = math.sqrt(2.0)
E, N_, W_, S_ = 1, 2, 4, 8          # edge mask bits: walker may step east / north / west / south
DIRS8 = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, 1), (1, -1), (-1, -1))


# ----------------------------------------------------------------------------------------- params
@dataclass
class NavParams:
    enabled: bool = True
    clearance_margin_m: float = 0.5     # blocked if closer than mech radius + this to a wall
    open_weight: float = 3.0            # cost x (1 + open_weight * openness^open_exp)
    open_exp: float = 2.0
    threat_weight: float = 6.0          # extra cost multiplier at a threat's centre (threats= hook)
    threat_radius_m: float = 60.0
    slice_ms: float = 6.0               # search time per tick
    replan_goal_move_m: float = 12.0    # goal moved this far: replan
    replan_period_s: float = 2.0        # only used while threats are supplied
    deviate_m: float = 10.0             # farther than this from the path: replan
    lookahead_m: float = 14.0           # steer toward the farthest clear path node within this
    handoff_m: float = 12.0             # elevated goal (roof): path to its foot, then go straight
    climb_dz_m: float = 4.0             # goal this far above our feet = needs a jet climb
    snap_cells: int = 2                 # snap a blocked start/goal to a free cell within this many cells
    snap_far_cells: int = 10            # same for the default (zone) goal and roof goals, which are approximate
    exposure_scale: float = 1.0         # path_cost exposure handed to loot (0 = loot ignores exposure)
    detour: float = 1.25                # path_cost estimate: euclid x detour (loot calls it for many pickups)
    stuck_speed_frac: float = 0.3
    stuck_s: float = 1.0
    stuck_jump_s: float = 0.4
    stuck_jet_s: float = 0.8
    stuck_sidestep_s: float = 0.6
    stuck_penalty_s: float = 6.0
    build_deadline_s: float = 9.0       # runtime map build gives up after this (nav off)
    baked_file: str = "navmap.bin"

    @classmethod
    def from_dict(cls, d: Optional[dict]) -> "NavParams":
        p = cls()
        names = {f.name for f in fields(cls)}
        for k, v in (d or {}).items():
            if k in names:
                setattr(p, k, v)
        return p


@dataclass
class StealthParams:
    mode: str = "hide_only"             # off | hide_only | near_threat | always
    speed_cap_mps: float = 4.6          # server compares real speed with 5 m/s; keep a margin
    hold_radius_m: float = 15.0         # hold still this close to the default (zone) goal
    heard_window_s: float = 3.0         # near_threat: a near step/boost/jet/reload this recent = creep
    quiet_kinds: Tuple[str, ...] = ("step", "boost", "jet", "reload")

    @classmethod
    def from_dict(cls, d: Optional[dict]) -> "StealthParams":
        p = cls()
        names = {f.name for f in fields(cls)}
        for k, v in (d or {}).items():
            if k in names:
                setattr(p, k, tuple(v) if k == "quiet_kinds" else v)
        return p


@dataclass
class NavDecision:
    move: Optional[Tuple[float, float]] = None   # world-frame move vector (length <= 1); None = no opinion
    boost_ok: bool = True                        # False while creeping: the arbiter must not boost
    hold: bool = False                           # standing still on purpose (silent): do not jump
    jump: bool = False                           # unstick pulse
    boost: bool = False                          # unstick jet pulse (with jump)
    reason: str = ""
    remaining_m: Optional[float] = None          # path length left to the goal, if known


# ------------------------------------------------------------------------------------ map building
class BuildTimeout(Exception):
    pass


class NavMap:
    """Baked grid. Cell (i, j) is the terrain vertex (4i, 4j); idx = j * W + i."""

    def __init__(self, W, H, minx, miny, blocked, edge, expo, gz, comp, key, has_expo=True):
        self.W, self.H, self.minx, self.miny = W, H, minx, miny
        self.blocked = blocked      # bytearray(W*H): 1 = centre not standable (solid or too near a wall)
        self.edge = edge            # bytearray(W*H): bits E,N,W,S = a walker here may step that way
        self.expo = expo            # bytearray(EW*EH): openness 0..255 on the 8 m grid
        self.gz = gz                # array('h'): ground height in cm at the cell
        self.comp = comp            # array('H'): weak connected component id (0 = blocked)
        self.key = key
        self.has_expo = has_expo
        self.EW = (W - 1) * CELL // EXPO_CELL + 1
        self.EH = (H - 1) * CELL // EXPO_CELL + 1

    # -- geometry
    def idx(self, x: float, y: float) -> int:
        i = int(round((x - self.minx) / CELL))
        j = int(round((y - self.miny) / CELL))
        if i < 0 or j < 0 or i >= self.W or j >= self.H:
            return -1
        return j * self.W + i

    def center(self, k: int) -> Tuple[float, float]:
        return (self.minx + (k % self.W) * CELL, self.miny + (k // self.W) * CELL)

    def openness(self, k: int) -> float:
        if not self.has_expo:
            return 0.0
        i, j = k % self.W, k // self.W
        ei, ej = min(self.EW - 1, i * CELL // EXPO_CELL), min(self.EH - 1, j * CELL // EXPO_CELL)
        return self.expo[ej * self.EW + ei] / 255.0

    def snap(self, x: float, y: float, r: int) -> int:
        """Nearest free cell to (x, y) within r cells, else -1."""
        k0 = self.idx(x, y)
        if k0 < 0:
            return -1
        if not self.blocked[k0]:
            return k0
        ci, cj = k0 % self.W, k0 // self.W
        best, bd = -1, 1e18
        for dj in range(-r, r + 1):
            for di in range(-r, r + 1):
                i, j = ci + di, cj + dj
                if 0 <= i < self.W and 0 <= j < self.H and not self.blocked[j * self.W + i]:
                    px, py = self.minx + i * CELL, self.miny + j * CELL
                    d = (px - x) ** 2 + (py - y) ** 2
                    if d < bd:
                        best, bd = j * self.W + i, d
        return best

    def ground_z(self, k: int) -> float:
        return self.gz[k] * 0.01

    # -- (de)serialisation
    def dumps(self) -> bytes:
        head = json.dumps({"v": BAKE_VERSION, "W": self.W, "H": self.H, "minx": self.minx, "miny": self.miny,
                           "key": self.key, "has_expo": self.has_expo, "n": [len(self.blocked), len(self.edge),
                           len(self.expo), len(self.gz) * 2, len(self.comp) * 2]}, separators=(",", ":"))
        body = bytes(self.blocked) + bytes(self.edge) + bytes(self.expo) + self.gz.tobytes() + self.comp.tobytes()
        return head.encode() + b"\n" + zlib.compress(body, 9)

    @classmethod
    def loads(cls, data: bytes) -> "NavMap":
        head, _, rest = data.partition(b"\n")
        h = json.loads(head)
        if h.get("v") != BAKE_VERSION:
            raise ValueError("navmap version")
        body = zlib.decompress(rest)
        n = h["n"]
        o = 0
        parts = []
        for ln in n:
            parts.append(body[o:o + ln])
            o += ln
        gz = array.array("h"); gz.frombytes(parts[3])
        comp = array.array("H"); comp.frombytes(parts[4])
        return cls(h["W"], h["H"], h["minx"], h["miny"], bytearray(parts[0]), bytearray(parts[1]),
                   bytearray(parts[2]), gz, comp, h["key"], h.get("has_expo", True))


def map_key(arena_dir: str, radius: float, margin: float, step_up: float, height: float) -> str:
    """Hash of the source map files plus the numbers the bake depends on."""
    h = hashlib.sha1()
    for rel in ("v2/world.json", "v2/terrain.i16"):
        with open(os.path.join(arena_dir, rel), "rb") as f:
            h.update(f.read())
    h.update(("|%g|%g|%g|%g|%d|%d" % (radius, margin, step_up, height, CELL, BAKE_VERSION)).encode())
    return h.hexdigest()


def _pip(x: float, y: float, ring: Sequence[float]) -> bool:
    inside = False
    n = len(ring) // 2
    xj, yj = ring[2 * n - 2], ring[2 * n - 1]
    for k in range(n):
        xi, yi = ring[2 * k], ring[2 * k + 1]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        xj, yj = xi, yi
    return inside


def build_map(arena_dir: str, radius: float = 2.5, margin: float = 0.5, step_up: float = 1.2,
              height: float = 9.0, deadline: Optional[float] = None, with_expo: bool = True) -> NavMap:
    """Build the grid from world.json + terrain.i16. Pure Python, about 3-5 s. Raises BuildTimeout."""
    def check():
        if deadline is not None and time.perf_counter() > deadline:
            raise BuildTimeout()

    key = map_key(arena_dir, radius, margin, step_up, height)
    with open(os.path.join(arena_dir, "v2/world.json")) as f:
        w = json.load(f)
    tr = w["terrain"]
    NX, NY, MINX, MINY = tr["nx"], tr["ny"], tr["minX"], tr["minY"]
    ter = array.array("h")
    with open(os.path.join(arena_dir, "v2/terrain.i16"), "rb") as f:
        ter.frombytes(f.read())
    if sys.byteorder == "big":  # pragma: no cover
        ter.byteswap()
    check()

    # vertex-level "rise over step_up going E/W/N/S" flags
    lim = int(step_up * 100)
    upE, upW, upN, upS = (bytearray(NX * NY) for _ in range(4))
    for j in range(NY):
        r = j * NX
        for i in range(NX - 1):
            d = ter[r + i + 1] - ter[r + i]
            if d > lim:
                upE[r + i] = 1
            elif -d > lim:
                upW[r + i + 1] = 1
    for j in range(NY - 1):
        r = j * NX
        for i in range(NX):
            d = ter[r + NX + i] - ter[r + i]
            if d > lim:
                upN[r + i] = 1
            elif -d > lim:
                upS[r + NX + i] = 1
    check()

    # 2 m build grid (vertices 2i, 2j)
    W2, H2 = (NX - 1) // SUB + 1, (NY - 1) // SUB + 1
    N2 = W2 * H2
    gz2 = array.array("d", [0.0]) * N2
    for j in range(H2):
        for i in range(W2):
            gz2[j * W2 + i] = ter[(j * SUB) * NX + i * SUB] * 0.01
    edge2 = bytearray(N2)
    for j in range(H2):
        for i in range(W2):
            v0 = (j * SUB) * NX + i * SUB
            m = 0
            if i < W2 - 1 and not (upE[v0] or upE[v0 + 1]):
                m |= E
            if j < H2 - 1 and not (upN[v0] or upN[v0 + NX]):
                m |= N_
            if i > 0 and not (upW[v0] or upW[v0 - 1]):
                m |= W_
            if j > 0 and not (upS[v0] or upS[v0 - NX]):
                m |= S_
            edge2[j * W2 + i] = m
    check()

    # walls: solid cells (centre inside a prism that blocks the standing volume), exact edge distance
    need = radius + margin
    INF = 1e9
    solid2 = bytearray(N2)
    roof2 = array.array("d", [-1e9]) * N2          # tallest non-bridge top, for the exposure rays
    dist2 = array.array("d", [INF]) * N2
    for p in w["prisms"]:
        check()
        ring = p["ring"]
        holes = [h for h in (p.get("holes") or []) if h]
        base, top, kind = p["base"], p["top"], p["kind"]
        xs, ys = ring[0::2], ring[1::2]
        i0 = max(0, int((min(xs) - MINX) / SUB) - 1); i1 = min(W2 - 1, int((max(xs) - MINX) / SUB) + 2)
        j0 = max(0, int((min(ys) - MINY) / SUB) - 1); j1 = min(H2 - 1, int((max(ys) - MINY) / SUB) + 2)
        for j in range(j0, j1 + 1):
            y = MINY + j * SUB
            for i in range(i0, i1 + 1):
                x = MINX + i * SUB
                k = j * W2 + i
                if not _pip(x, y, ring):
                    continue
                if holes and any(_pip(x, y, h) for h in holes):
                    continue
                g = gz2[k]
                if kind != "bridge" and top > roof2[k]:
                    roof2[k] = top
                if top > g + step_up and base < g + height:
                    solid2[k] = 1
                    dist2[k] = 0.0
        # exact distance from nearby cells to every wall edge of this prism (outer ring and holes)
        for rg in [ring] + holes:
            n = len(rg) // 2
            for a in range(n):
                ax, ay = rg[2 * a], rg[2 * a + 1]
                bx, by = rg[2 * ((a + 1) % n)], rg[2 * ((a + 1) % n) + 1]
                ei0 = max(0, int((min(ax, bx) - need - MINX) / SUB)); ei1 = min(W2 - 1, int((max(ax, bx) + need - MINX) / SUB) + 1)
                ej0 = max(0, int((min(ay, by) - need - MINY) / SUB)); ej1 = min(H2 - 1, int((max(ay, by) + need - MINY) / SUB) + 1)
                dx, dy = bx - ax, by - ay
                L2 = dx * dx + dy * dy
                for j in range(ej0, ej1 + 1):
                    py = MINY + j * SUB
                    row = j * W2
                    for i in range(ei0, ei1 + 1):
                        k = row + i
                        if dist2[k] == 0.0:
                            continue
                        px = MINX + i * SUB
                        t = 0.0 if L2 == 0.0 else ((px - ax) * dx + (py - ay) * dy) / L2
                        t = 0.0 if t < 0.0 else 1.0 if t > 1.0 else t
                        ddx, ddy = px - (ax + t * dx), py - (ay + t * dy)
                        d2 = ddx * ddx + ddy * ddy
                        if d2 < dist2[k] * dist2[k] and d2 < need * need:
                            g = gz2[k]
                            if top > g + step_up and base < g + height:
                                dist2[k] = math.sqrt(d2)
    blocked2 = bytearray(1 if (solid2[k] or dist2[k] < need) else 0 for k in range(N2))
    check()

    # 4 m field grid: cell (I, J) = build cell (2I, 2J); an edge also needs the 2 m cell in between free
    W4, H4 = (NX - 1) // CELL + 1, (NY - 1) // CELL + 1
    N4 = W4 * H4
    blocked = bytearray(N4)
    edge = bytearray(N4)
    gz = array.array("h", [0]) * N4
    for J in range(H4):
        for I in range(W4):
            k4 = J * W4 + I
            k2 = (J * 2) * W2 + I * 2
            blocked[k4] = blocked2[k2]
            gz[k4] = int(round(gz2[k2] * 100))
            if blocked2[k2]:
                continue
            m = 0
            if I < W4 - 1 and edge2[k2] & E and edge2[k2 + 1] & E and not blocked2[k2 + 1]:
                m |= E
            if J < H4 - 1 and edge2[k2] & N_ and edge2[k2 + W2] & N_ and not blocked2[k2 + W2]:
                m |= N_
            if I > 0 and edge2[k2] & W_ and edge2[k2 - 1] & W_ and not blocked2[k2 - 1]:
                m |= W_
            if J > 0 and edge2[k2] & S_ and edge2[k2 - W2] & S_ and not blocked2[k2 - W2]:
                m |= S_
            edge[k4] = m
    check()

    # static exposure: mean visible distance over 16 rays at eye height, 8 m cells
    EW, EH = (W4 - 1) * CELL // EXPO_CELL + 1, (H4 - 1) * CELL // EXPO_CELL + 1
    expo = bytearray(EW * EH)
    if with_expo:
        ndir, step, rmax, eye = 16, 4.0, 160.0, 8.0
        dirs = [(math.cos(2 * math.pi * d / ndir), math.sin(2 * math.pi * d / ndir)) for d in range(ndir)]
        for ej in range(EH):
            if ej % 8 == 0:
                check()
            for ei in range(EW):
                x0, y0 = MINX + ei * EXPO_CELL, MINY + ej * EXPO_CELL
                k0 = (ej * EXPO_CELL // SUB) * W2 + ei * EXPO_CELL // SUB
                if blocked2[k0]:
                    continue
                ez = gz2[k0] + eye
                tot = 0.0
                for dx, dy in dirs:
                    d = step
                    while d <= rmax:
                        x, y = x0 + dx * d, y0 + dy * d
                        ci, cj = int((x - MINX) / SUB), int((y - MINY) / SUB)
                        if ci < 0 or cj < 0 or ci >= W2 or cj >= H2:
                            break
                        kk = cj * W2 + ci
                        if roof2[kk] > ez or gz2[kk] > ez:
                            break
                        d += step
                    tot += min(d, rmax) / rmax
                expo[ej * EW + ei] = int(255 * tot / ndir)

    # weak connected components (either direction open), used to answer "unreachable" cheaply
    comp = array.array("H", [0]) * N4
    cid = 0
    for s in range(N4):
        if blocked[s] or comp[s]:
            continue
        cid += 1
        if cid > 65000:
            break
        comp[s] = cid
        stack = [s]
        while stack:
            a = stack.pop()
            ai, aj = a % W4, a // W4
            m = edge[a]
            for bit, di, dj, back in ((E, 1, 0, W_), (N_, 0, 1, S_), (W_, -1, 0, E), (S_, 0, -1, N_)):
                b = (aj + dj) * W4 + ai + di
                if 0 <= ai + di < W4 and 0 <= aj + dj < H4 and not blocked[b] and not comp[b] and (m & bit or edge[b] & back):
                    comp[b] = cid
                    stack.append(b)
    return NavMap(W4, H4, MINX, MINY, blocked, edge, expo, gz, comp, key, with_expo)



def load_or_build(arena_dir: Optional[str], baked_path: str, radius: float, margin: float, step_up: float,
                  height: float, deadline_s: float) -> Optional[NavMap]:
    """Baked map if its key matches the real map files, else build now (bounded), else None."""
    key = None
    if arena_dir:
        try:
            key = map_key(arena_dir, radius, margin, step_up, height)
        except Exception:
            key = None
    baked = None
    try:
        with open(baked_path, "rb") as f:
            baked = NavMap.loads(f.read())
    except Exception:
        baked = None
    if baked is not None and (key is None or baked.key == key):
        return baked              # no map files to compare with: trust the bake (the map never changes)
    if key is None:
        return None
    try:
        return build_map(arena_dir, radius, margin, step_up, height, deadline=time.perf_counter() + deadline_s)
    except BuildTimeout:
        return None
    except Exception:
        return None


# ---------------------------------------------------------------------------------------- navigator
class _Search:
    """Time-sliced A* from the goal outward toward our cell; the parent chain from our cell is the path."""

    def __init__(self, nm: NavMap, start: int, goal: int, mult: List[float], extra: Dict[int, float]):
        self.nm, self.start, self.goal, self.mult, self.extra = nm, start, goal, mult, extra
        n = nm.W * nm.H
        self.g = [1e30] * n
        self.parent = array.array("i", [-1]) * n
        self.g[goal] = 0.0
        self.si, self.sj = start % nm.W, start // nm.W
        self.heap = [(self._h(goal), 0.0, goal)]
        self.done = False
        self.found = False

    def _h(self, k: int) -> float:
        W = self.nm.W
        dx, dy = abs(k % W - self.si), abs(k // W - self.sj)
        return (max(dx, dy) + (S2 - 1.0) * min(dx, dy)) * CELL

    def run(self, deadline: float) -> bool:
        nm = self.nm
        W, H, blocked, edge = nm.W, nm.H, nm.blocked, nm.edge
        g, parent, mult, extra, heap = self.g, self.parent, self.mult, self.extra, self.heap
        start, si, sj = self.start, self.si, self.sj
        pop, push = heapq.heappop, heapq.heappush
        n = 0
        while heap:
            f, ga, a = pop(heap)
            if ga > g[a]:
                continue                       # stale entry
            if a == start:
                self.done = self.found = True
                return True
            n += 1
            if n & 31 == 0 and time.perf_counter() > deadline:
                push(heap, (f, ga, a))
                return False
            ai, aj = a % W, a // W
            for di, dj in DIRS8:
                bi, bj = ai + di, aj + dj
                if bi < 0 or bj < 0 or bi >= W or bj >= H:
                    continue
                b = bj * W + bi
                if blocked[b]:
                    continue
                eb = edge[b]
                # b walks to a: direction (-di, -dj)
                if di == 0 or dj == 0:
                    bit = E if -di == 1 else W_ if -di == -1 else N_ if -dj == 1 else S_
                    if not eb & bit:
                        continue
                    step = CELL
                else:
                    bx = E if -di == 1 else W_
                    by = N_ if -dj == 1 else S_
                    if not (eb & bx and eb & by) or blocked[bj * W + ai] or blocked[aj * W + bi]:
                        continue
                    step = CELL * S2
                m = mult[b]
                if extra:
                    m += extra.get(b, 0.0)
                nd = ga + step * m
                if nd < g[b]:
                    g[b] = nd
                    parent[b] = a
                    dx, dy = abs(bi - si), abs(bj - sj)
                    push(heap, (nd + (max(dx, dy) + (S2 - 1.0) * min(dx, dy)) * CELL, nd, b))
        self.done = True
        return True

    def path(self) -> List[int]:
        out, k = [self.start], self.start
        guard = 0
        while k != self.goal and guard < 100000:
            k = self.parent[k]
            if k < 0:
                return []
            out.append(k)
            guard += 1
        return out


class Navigator:
    @classmethod
    def create(cls, hello: dict, params: Optional[NavParams] = None, stealth: Optional[StealthParams] = None,
               here: Optional[str] = None) -> Optional["Navigator"]:
        """Never raises. Returns None when nav is disabled or the map cannot be loaded."""
        try:
            params = params or NavParams()
            if not params.enabled:
                return None
            cfg = hello["config"]
            m = cfg["mech"]
            here = here or os.path.dirname(os.path.abspath(__file__))
            arena = (hello.get("map") or {}).get("dir")
            if not (arena and os.path.exists(os.path.join(arena, "v2", "world.json"))):
                alt = os.path.join(here, "kit", "arena")      # dev checkouts; kit/ is not in the image
                arena = alt if os.path.exists(os.path.join(alt, "v2", "world.json")) else None
            nm = load_or_build(arena, os.path.join(here, params.baked_file), m["radius"], params.clearance_margin_m,
                               m["step_up"], m["height"], params.build_deadline_s)
            if nm is None:
                return None
            return cls(nm, cfg, params, stealth or StealthParams())
        except Exception:
            return None

    def __init__(self, nm: NavMap, cfg: dict, params: NavParams, stealth: StealthParams):
        self.nm, self.p, self.sp = nm, params, stealth
        mech = cfg["mech"]
        self.walk = float(mech["walk_speed"])
        self.radius = float(mech["radius"])
        n = nm.W * nm.H
        self.mult = [1.0 + params.open_weight * nm.openness(k) ** params.open_exp for k in range(n)] if nm.has_expo else [1.0] * n
        self.search: Optional[_Search] = None
        self.path: List[int] = []
        self.pi = 0
        self.goal_k = -1
        self.goal_xy: Tuple[float, float] = (0.0, 0.0)
        self.planned_t = -1e9
        self.threat_sig = None
        self.extra: Dict[int, float] = {}
        self.penalties: Dict[int, float] = {}       # cell -> until t (stuck recovery)
        self.hist: List[Tuple[float, float, float]] = []
        self.stuck_stage = 0
        self.stuck_until = 0.0
        self.stuck_kind = ""
        self.stuck_side = 1.0
        self.last_cmd = 0.0
        self.stat = {"searches": 0, "stuck": 0, "slice_max_ms": 0.0}

    # -- loot hook ---------------------------------------------------------------------------
    def path_cost(self, src, dst):
        """(length_m or None, exposure 0..1). Cheap on purpose: loot calls it for every remembered pickup
        each tick, so this is euclid x detour, plus 'None' when the two points are in different components."""
        try:
            nm = self.nm
            d = math.hypot(dst[0] - src[0], dst[1] - src[1])
            kd = nm.idx(dst[0], dst[1])
            if kd < 0:
                return (d * self.p.detour, 0.0)
            if len(dst) > 2 and dst[2] - nm.ground_z(kd) > self.p.climb_dz_m:
                return (d * 1.1, 0.0)                         # roof: a jet climb, not a ground path
            ks = nm.snap(src[0], src[1], self.p.snap_cells)
            kt = nm.snap(dst[0], dst[1], self.p.snap_cells)
            if ks >= 0 and kt >= 0 and nm.comp[ks] and nm.comp[kt] and nm.comp[ks] != nm.comp[kt]:
                return (None, 0.0)
            return (d * self.p.detour, self.p.exposure_scale * nm.openness(kt if kt >= 0 else kd))
        except Exception:
            return (math.hypot(dst[0] - src[0], dst[1] - src[1]) * self.p.detour, 0.0)

    # -- internals ---------------------------------------------------------------------------
    def _clear_line(self, ax, ay, bx, by) -> bool:
        nm = self.nm
        d = math.hypot(bx - ax, by - ay)
        n = max(1, int(d / 2.0))
        W, H, blocked = nm.W, nm.H, nm.blocked
        for s in range(1, n + 1):
            t = s / n
            fx = (ax + (bx - ax) * t - nm.minx) / CELL
            fy = (ay + (by - ay) * t - nm.miny) / CELL
            i0, j0 = int(math.floor(fx)), int(math.floor(fy))
            if i0 < 0 or j0 < 0 or i0 + 1 >= W or j0 + 1 >= H:
                return False
            k = j0 * W + i0
            # all four surrounding cell centres must be free: nearest-centre rounding alone lets a line
            # pass up to 2 m from a blocked cell, i.e. well inside the wall clearance
            if blocked[k] or blocked[k + 1] or blocked[k + W] or blocked[k + W + 1]:
                return False
        return True

    def _threat_extra(self, threats, t) -> Dict[int, float]:
        out: Dict[int, float] = {}
        nm, p = self.nm, self.p
        r = p.threat_radius_m
        rc = int(r / CELL) + 1
        for th in threats or ():
            k = nm.idx(th[0], th[1])
            if k < 0:
                continue
            ci, cj = k % nm.W, k // nm.W
            w = th[2] if len(th) > 2 else 1.0
            for dj in range(-rc, rc + 1):
                for di in range(-rc, rc + 1):
                    i, j = ci + di, cj + dj
                    if 0 <= i < nm.W and 0 <= j < nm.H:
                        d = math.hypot(di, dj) * CELL
                        if d < r:
                            kk = j * nm.W + i
                            out[kk] = out.get(kk, 0.0) + p.threat_weight * w * (1.0 - d / r)
        return out

    def _merged_extra(self, t) -> Dict[int, float]:
        for k in [k for k, u in self.penalties.items() if u < t]:
            del self.penalties[k]
        if not self.penalties:
            return self.extra
        out = dict(self.extra)
        for k in self.penalties:
            out[k] = out.get(k, 0.0) + 6.0
        return out

    def _start_search(self, start_k: int, goal_k: int, t: float) -> None:
        self.search = _Search(self.nm, start_k, goal_k, self.mult, self._merged_extra(t))
        self.planned_t = t
        self.stat["searches"] += 1

    def _speed_scale(self, obs, me, default_goal: bool, dist_goal: float) -> Tuple[float, bool, str]:
        """(speed scale, hold, reason) from the stealth rule. Only inside the zone and with nobody in sight."""
        sp = self.sp
        if sp.mode == "off" or not me.get("in_zone", True):
            return 1.0, False, ""
        if any(m.get("kind") == "mech" for m in obs.get("mechs", ())):
            return 1.0, False, ""
        if default_goal and dist_goal <= sp.hold_radius_m:
            return 0.0, True, "hold"
        cap = min(1.0, sp.speed_cap_mps / self.walk)
        if sp.mode == "always":
            return cap, False, "creep"
        if sp.mode == "near_threat":
            for s in obs.get("sounds", ()):
                if s.get("kind") in sp.quiet_kinds and s.get("dist") == "near" and s.get("age", 9.0) <= sp.heard_window_s:
                    return cap, False, "creep"
        return 1.0, False, ""

    def _stuck_check(self, t: float, x: float, y: float, expected_speed: float, grounded: bool) -> None:
        p = self.p
        if expected_speed <= 0.5 or not grounded:
            self.hist.clear()
            return
        self.hist.append((t, x, y))
        while self.hist and t - self.hist[0][0] > p.stuck_s + 0.25:
            self.hist.pop(0)
        if len(self.hist) < 4 or t - self.hist[0][0] < p.stuck_s - 1e-6 or t < self.stuck_until:
            return
        t0, x0, y0 = self.hist[0]
        if math.hypot(x - x0, y - y0) < p.stuck_speed_frac * expected_speed * (t - t0):
            self.stat["stuck"] += 1
            stage = self.stuck_stage % 3
            self.stuck_stage += 1
            self.hist.clear()
            if stage == 0:
                self.stuck_kind, dur = "jump", p.stuck_jump_s
                for k in self.path[self.pi:self.pi + 3]:
                    self.penalties[k] = t + p.stuck_penalty_s
                self.path = []                      # replan around it
                self.stuck_side = -self.stuck_side
            elif stage == 1:
                self.stuck_kind, dur = "jet", p.stuck_jet_s
            else:
                self.stuck_kind, dur = "side", p.stuck_sidestep_s
            self.stuck_until = t + dur

    # -- main entry --------------------------------------------------------------------------
    def step(self, obs: dict, goal, default_goal: bool = False, threats=None) -> NavDecision:
        try:
            return self._step(obs, goal, default_goal, threats)
        except Exception as e:                      # never let nav stall or crash a tick
            self.path, self.search = [], None
            return NavDecision(reason="nav_error:" + type(e).__name__)

    def _step(self, obs, goal, default_goal, threats) -> NavDecision:
        t0 = time.perf_counter()
        nm, p = self.nm, self.p
        me, t = obs["self"], obs["t"]
        x, y, z = me["pos"]
        gx, gy = goal[0], goal[1]
        dist_goal = math.hypot(gx - x, gy - y)
        scale, hold, why = self._speed_scale(obs, me, default_goal, dist_goal)
        boost_ok = scale >= 1.0

        if hold:
            self.hist.clear()
            self.last_cmd = 0.0
            return NavDecision(move=(0.0, 0.0), hold=True, boost_ok=False, reason="hold", remaining_m=dist_goal)

        # unstick pulses override pathing
        if t < self.stuck_until:
            ang = math.atan2(gy - y, gx - x)
            if self.stuck_kind == "side":
                ang += self.stuck_side * math.pi / 2
            return NavDecision(move=(math.cos(ang), math.sin(ang)), jump=self.stuck_kind in ("jump", "jet"),
                               boost=self.stuck_kind == "jet", reason="unstick_" + self.stuck_kind)

        sk = nm.snap(x, y, p.snap_cells)
        if sk < 0:
            self.path, self.search = [], None
            return NavDecision(reason="off_grid")        # on a roof or out of bounds: v1 straight line
        elevated_goal = len(goal) > 2 and goal[2] - z > p.climb_dz_m
        gk = nm.snap(gx, gy, p.snap_far_cells if (elevated_goal or default_goal) else p.snap_cells)
        if gk < 0 or (nm.comp[sk] and nm.comp[gk] and nm.comp[sk] != nm.comp[gk]):
            self.path, self.search = [], None
            return NavDecision(reason="goal_unreachable")
        if elevated_goal and dist_goal <= p.handoff_m:
            ang = math.atan2(gy - y, gx - x)
            return NavDecision(move=(math.cos(ang), math.sin(ang)), reason="handoff", remaining_m=dist_goal)

        # (re)plan
        thr_sig = tuple((round(a[0] / 8), round(a[1] / 8)) for a in threats) if threats else None
        restart = False
        if self.goal_k < 0 or math.hypot(gx - self.goal_xy[0], gy - self.goal_xy[1]) > p.replan_goal_move_m:
            restart = True
            self.path = []                                # a path to the old goal is useless
        elif thr_sig != self.threat_sig or (threats and t - self.planned_t > p.replan_period_s):
            restart = True                                # costs changed: keep the old path until the new one lands
        elif self.search is None:
            if not self.path:
                restart = True
            else:
                nxt = self.path[self.pi:self.pi + 12]
                cx, cy = nm.center(min(nxt, key=lambda k: (nm.center(k)[0] - x) ** 2 + (nm.center(k)[1] - y) ** 2))
                restart = math.hypot(cx - x, cy - y) > p.deviate_m
        if restart:
            if thr_sig != self.threat_sig or threats:
                self.threat_sig = thr_sig
                self.extra = self._threat_extra(threats, t) if threats else {}
            self.goal_k, self.goal_xy = gk, (gx, gy)
            self._start_search(sk, gk, t)

        if self.search is not None:
            s0 = time.perf_counter()
            if self.search.run(s0 + p.slice_ms / 1000.0):
                if self.search.found:
                    self.path, self.pi = self.search.path(), 0
                else:
                    self.path = []
                s = self.search
                self.search = None
                if not s.found:
                    return NavDecision(reason="no_path")
            self.stat["slice_max_ms"] = max(self.stat["slice_max_ms"], 1000.0 * (time.perf_counter() - s0))

        if not self.path:
            return NavDecision(reason="searching" if self.search is not None else "no_path")

        # steer
        path = self.path
        hi = min(len(path), self.pi + 12)
        best, bd = self.pi, 1e18
        for i in range(self.pi, hi):
            cx, cy = nm.center(path[i])
            d = (cx - x) ** 2 + (cy - y) ** 2
            if d < bd:
                best, bd = i, d
        self.pi = best
        remaining = (len(path) - 1 - self.pi) * CELL
        tx, ty = gx, gy
        if self.pi < len(path) - 1:
            tgt = self.pi + 1
            for i in range(self.pi + 1, min(len(path), self.pi + 1 + int(p.lookahead_m / CELL) + 1)):
                cx, cy = nm.center(path[i])
                if self._clear_line(x, y, cx, cy):
                    tgt = i
                else:
                    break
            tx, ty = nm.center(path[tgt])
        dx, dy = tx - x, ty - y
        d = math.hypot(dx, dy)
        if d < 1e-6:
            return NavDecision(reason="at_target", remaining_m=remaining)
        mv = (dx / d * (scale if scale < 1.0 else 1.0), dy / d * (scale if scale < 1.0 else 1.0))
        charging = any(w and w.get("charge", 0) > 0 for w in me.get("weapons", ()))
        self._stuck_check(t, x, y, math.hypot(*mv) * self.walk * (0.5 if charging else 1.0), bool(me.get("grounded", True)))
        self.stat["tick_ms"] = 1000.0 * (time.perf_counter() - t0)
        return NavDecision(move=mv, boost_ok=boost_ok, reason=why or "path", remaining_m=remaining)
