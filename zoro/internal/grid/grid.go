// Package grid is a 2 m walk grid over the ground level of the arena, with path search, connected
// regions, rooftop regions and a top-surface planner for jet-assisted travel.
package grid

import (
	"math"
	"sync"

	"zoro/internal/arena"
)

const (
	// GapCap caps the stored distance to the nearest wall.
	GapCap = 8.0
	// RoomCap caps the stored headroom.
	RoomCap = 40.0
	// maxSlope is tan(50 degrees): the steepest ground a mech walks up.
	maxSlope = 1.19
)

// Grid is the walk grid. The exported slices are indexed by cell (row-major).
type Grid struct {
	Map    *arena.Map
	Cell   float64
	NX, NY int
	X0, Y0 float64

	Floor   []float32 // walk surface height (valid where !Blocked)
	Gap     []float32 // distance to the nearest wall a standing body would touch (capped)
	Room    []float32 // headroom above the walk surface (capped)
	Blocked []bool    // inside a building or out of bounds
	RoofTop []float32 // top of the building over a blocked cell (NaN if none)

	cache *derived // lazily built, shared by clones
	scr   scratch  // per-clone search state
}

type derived struct {
	regionsOnce sync.Once
	regions     []int32

	roofsOnce sync.Once
	roofs     []Roof
	roofID    []int32
	roofDepth []int16

	topsOnce sync.Once
	tops     []float32

	openOnce sync.Once
	open     *Openness
}

// Build computes the walk grid. stepUp is the tallest ledge a mech walks onto, bodyH its height.
func Build(m *arena.Map, stepUp, bodyH float64) *Grid {
	g := &Grid{Map: m, Cell: 2, cache: &derived{}}
	g.X0, g.Y0 = math.Floor(m.Bounds.X0), math.Floor(m.Bounds.Y0)
	g.NX = int(math.Ceil((m.Bounds.X1 - g.X0) / g.Cell))
	g.NY = int(math.Ceil((m.Bounds.Y1 - g.Y0) / g.Cell))
	n := g.NX * g.NY
	g.Floor = make([]float32, n)
	g.Gap = make([]float32, n)
	g.Room = make([]float32, n)
	g.Blocked = make([]bool, n)
	g.RoofTop = make([]float32, n)
	for k := 0; k < n; k++ {
		g.classify(k, stepUp, bodyH)
	}
	g.scr = newScratch(n)
	return g
}

// classify fills in one cell: either a standable surface (terrain, or low blocks stepped onto) or a
// blocked cell with the roof height above it.
func (g *Grid) classify(k int, stepUp, bodyH float64) {
	m := g.Map
	x, y := g.Pos(k)
	g.RoofTop[k] = float32(math.NaN())
	if !m.InBounds(x, y) {
		g.Blocked[k] = true
		return
	}
	near := m.BlocksAt(x, y)
	surface := m.Ground(x, y)
	roof := math.NaN()
	// climb onto plinths we can step up on; anything taller makes the cell solid
	for pass := 0; pass < 4; pass++ {
		raised := false
		for _, bi := range near {
			b := &m.Blocks[bi]
			if b.Top <= surface || b.Bottom > surface+0.3 || !b.Covers(x, y) {
				continue
			}
			if b.Top-surface <= stepUp {
				surface, raised = b.Top, true
			} else if math.IsNaN(roof) || b.Top > roof {
				roof = b.Top
			}
		}
		if !raised {
			break
		}
	}
	if !math.IsNaN(roof) {
		// blocks stacked on that one raise the roof further
		for pass := 0; pass < 4; pass++ {
			raised := false
			for _, bi := range near {
				b := &m.Blocks[bi]
				if b.Top > roof && b.Bottom <= roof+0.3 && b.Covers(x, y) {
					roof, raised = b.Top, true
				}
			}
			if !raised {
				break
			}
		}
		g.RoofTop[k] = float32(roof)
		g.Blocked[k] = true
		return
	}
	g.Floor[k] = float32(surface)
	g.Room[k] = float32(math.Min(m.Ceiling(x, y, surface+0.3)-surface, RoomCap))
	g.Gap[k] = float32(m.WallGap(x, y, surface+stepUp+0.05, surface+bodyH, GapCap))
}

// Pos returns the centre of cell k.
func (g *Grid) Pos(k int) (float64, float64) {
	return g.X0 + (float64(k%g.NX)+0.5)*g.Cell, g.Y0 + (float64(k/g.NX)+0.5)*g.Cell
}

// ColRow returns the (clamped) column and row containing (x,y).
func (g *Grid) ColRow(x, y float64) (int, int) {
	c := int((x - g.X0) / g.Cell)
	r := int((y - g.Y0) / g.Cell)
	return max(0, min(c, g.NX-1)), max(0, min(r, g.NY-1))
}

// At returns the cell containing (x,y) (clamped to the grid).
func (g *Grid) At(x, y float64) int {
	c, r := g.ColRow(x, y)
	return r*g.NX + c
}

// inside reports whether column c, row r is on the grid.
func (g *Grid) inside(c, r int) bool { return c >= 0 && r >= 0 && c < g.NX && r < g.NY }

// Fits reports whether a body of radius rad and height h can stand in cell k.
func (g *Grid) Fits(k int, rad, h float64) bool {
	return !g.Blocked[k] && float64(g.Gap[k]) >= rad && float64(g.Room[k]) >= h
}

// stepOK reports whether the rise from cell a to cell b over dist metres is walkable.
func (g *Grid) stepOK(a, b int, dist float64) bool {
	return float64(g.Floor[b]-g.Floor[a]) <= math.Max(maxSlope*dist*0.85, 1.2)
}

// Clone returns a grid sharing every map but with its own search scratch.
func (g *Grid) Clone() *Grid {
	c := *g
	c.scr = newScratch(g.NX * g.NY)
	return &c
}

// Warm builds every lazily derived map now (so no decision pays for it later).
func (g *Grid) Warm() {
	g.Regions()
	g.Roofs()
	g.Tops()
	g.Openness()
}

// neighbour offsets: four straight, then four diagonal
var (
	offC = [8]int{1, -1, 0, 0, 1, 1, -1, -1}
	offR = [8]int{0, 0, 1, -1, 1, -1, 1, -1}
)
