package arena

import "math"

// bucketSize is the side of a spatial-index cell in metres.
const bucketSize = 8.0

// buckets is a uniform grid over the arena; each cell lists the ids of the objects whose bounding
// box touches it (compressed: start offsets plus one flat id array).
type buckets struct {
	x0, y0 float64
	nx, ny int
	start  []int32
	ids    []int32
}

func newBucketFrame(b Rect) buckets {
	x0 := math.Floor(b.X0/bucketSize)*bucketSize - bucketSize
	y0 := math.Floor(b.Y0/bucketSize)*bucketSize - bucketSize
	return buckets{
		x0: x0, y0: y0,
		nx: int(math.Ceil((b.X1-x0)/bucketSize)) + 2,
		ny: int(math.Ceil((b.Y1-y0)/bucketSize)) + 2,
	}
}

func (g *buckets) col(x float64) int {
	return clampInt(int(math.Floor((x-g.x0)/bucketSize)), 0, g.nx-1)
}
func (g *buckets) row(y float64) int {
	return clampInt(int(math.Floor((y-g.y0)/bucketSize)), 0, g.ny-1)
}

// at returns the cell index holding (x,y), clamped to the grid.
func (g *buckets) at(x, y float64) int { return g.row(y)*g.nx + g.col(x) }

// list returns the object ids registered in cell c.
func (g *buckets) list(c int) []int32 { return g.ids[g.start[c]:g.start[c+1]] }

// fill builds the index for n objects with the given bounding boxes (two passes: count, then place).
func (g *buckets) fill(n int, box func(i int) Rect) {
	cells := g.nx * g.ny
	g.start = make([]int32, cells+1)
	span := func(r Rect) (int, int, int, int) { return g.col(r.X0), g.row(r.Y0), g.col(r.X1), g.row(r.Y1) }
	for i := 0; i < n; i++ {
		c0, r0, c1, r1 := span(box(i))
		for r := r0; r <= r1; r++ {
			for c := c0; c <= c1; c++ {
				g.start[r*g.nx+c+1]++
			}
		}
	}
	for c := 1; c <= cells; c++ {
		g.start[c] += g.start[c-1]
	}
	g.ids = make([]int32, g.start[cells])
	cursor := make([]int32, cells)
	copy(cursor, g.start[:cells])
	for i := 0; i < n; i++ {
		c0, r0, c1, r1 := span(box(i))
		for r := r0; r <= r1; r++ {
			for c := c0; c <= c1; c++ {
				k := r*g.nx + c
				g.ids[cursor[k]] = int32(i)
				cursor[k]++
			}
		}
	}
}

// forEachIn calls fn for every cell overlapping the square of half-size r around (x,y).
func (g *buckets) forEachIn(x, y, r float64, fn func(c int)) {
	c0, c1 := g.col(x-r), g.col(x+r)
	r0, r1 := g.row(y-r), g.row(y+r)
	for row := r0; row <= r1; row++ {
		for c := c0; c <= c1; c++ {
			fn(row*g.nx + c)
		}
	}
}

func (m *Map) buildBuckets() {
	frame := newBucketFrame(m.Bounds)
	const eps = 0.01
	m.wallGrid, m.blockGrid, m.treeGrid = frame, frame, frame
	m.wallGrid.fill(len(m.Walls), func(i int) Rect {
		w := &m.Walls[i]
		return Rect{math.Min(w.Ax, w.Bx) - eps, math.Min(w.Ay, w.By) - eps, math.Max(w.Ax, w.Bx) + eps, math.Max(w.Ay, w.By) + eps}
	})
	m.blockGrid.fill(len(m.Blocks), func(i int) Rect { return m.Blocks[i].Box })
	m.treeGrid.fill(len(m.Trees), func(i int) Rect {
		t := &m.Trees[i]
		r := math.Max(t.CrownR, t.TrunkR)
		return Rect{math.Min(t.X, t.CrownX) - r, math.Min(t.Y, t.CrownY) - r, math.Max(t.X, t.CrownX) + r, math.Max(t.Y, t.CrownY) + r}
	})
}

// tileMax stores the highest terrain sample of every square tile of the height lattice, so a ray
// well above a tile can skip it.
type tileMax struct {
	size   int
	nx, ny int
	top    []float32
}

func newTileMax(m *Map, size int) tileMax {
	t := tileMax{size: size, nx: (m.hw + size - 1) / size, ny: (m.hh + size - 1) / size}
	t.top = make([]float32, t.nx*t.ny)
	for i := range t.top {
		t.top[i] = -1e9
	}
	raise := func(ti, tj int, h float32) {
		if ti < 0 || tj < 0 || ti >= t.nx || tj >= t.ny {
			return
		}
		if k := tj*t.nx + ti; h > t.top[k] {
			t.top[k] = h
		}
	}
	for j := 0; j < m.hh; j++ {
		for i := 0; i < m.hw; i++ {
			h := m.heights[j*m.hw+i]
			// a sample on a tile border shapes the surface of the tiles on both sides
			for _, tj := range [2]int{j / size, (j - 1) / size} {
				for _, ti := range [2]int{i / size, (i - 1) / size} {
					raise(ti, tj, h)
				}
			}
		}
	}
	return t
}

// tileTop returns the highest terrain in the tile containing (x,y).
func (m *Map) tileTop(x, y float64) float64 {
	i := clampInt(int((x-m.hx0)/m.hStep), 0, m.hw-1)
	j := clampInt(int((y-m.hy0)/m.hStep), 0, m.hh-1)
	t := &m.tiles
	return float64(t.top[(j/t.size)*t.nx+i/t.size])
}

func clampInt(v, lo, hi int) int {
	if v < lo {
		return lo
	}
	if v > hi {
		return hi
	}
	return v
}
