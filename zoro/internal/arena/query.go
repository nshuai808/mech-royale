package arena

import "math"

// Ground samples the terrain height at (x,y) with bilinear interpolation (clamped at the edges).
func (m *Map) Ground(x, y float64) float64 {
	u := clampF((x-m.hx0)/m.hStep, 0, float64(m.hw-1))
	v := clampF((y-m.hy0)/m.hStep, 0, float64(m.hh-1))
	i := min(int(u), m.hw-2)
	j := min(int(v), m.hh-2)
	fu, fv := u-float64(i), v-float64(j)
	k := j*m.hw + i
	a := float64(m.heights[k])*(1-fu) + float64(m.heights[k+1])*fu
	b := float64(m.heights[k+m.hw])*(1-fu) + float64(m.heights[k+m.hw+1])*fu
	return a*(1-fv) + b*fv
}

func clampF(v, lo, hi float64) float64 {
	return math.Max(lo, math.Min(hi, v))
}

// ringHas is the even-odd point-in-polygon test.
func ringHas(ring []float64, x, y float64) bool {
	inside := false
	n := len(ring) / 2
	for i, j := 0, n-1; i < n; j, i = i, i+1 {
		xi, yi := ring[2*i], ring[2*i+1]
		xj, yj := ring[2*j], ring[2*j+1]
		if (yi > y) != (yj > y) && x < (xj-xi)*(y-yi)/(yj-yi)+xi {
			inside = !inside
		}
	}
	return inside
}

// Covers reports whether the block's footprint contains (x,y).
func (b *Block) Covers(x, y float64) bool {
	if !b.Box.Contains(x, y) || !ringHas(b.Outer, x, y) {
		return false
	}
	for _, h := range b.Holes {
		if ringHas(h, x, y) {
			return false
		}
	}
	return true
}

// BlocksAt returns the indices of the blocks whose bounding boxes may cover (x,y).
func (m *Map) BlocksAt(x, y float64) []int32 { return m.blockGrid.list(m.blockGrid.at(x, y)) }

// Floor returns the highest surface at (x,y) that is not above z: the terrain or a block top.
func (m *Map) Floor(x, y, z float64) float64 {
	f := m.Ground(x, y)
	for _, bi := range m.BlocksAt(x, y) {
		b := &m.Blocks[bi]
		if b.Top > f && b.Top <= z && b.Covers(x, y) {
			f = b.Top
		}
	}
	return f
}

// Ceiling returns the lowest block underside at or above z at (x,y), or +Inf.
func (m *Map) Ceiling(x, y, z float64) float64 {
	c := math.Inf(1)
	for _, bi := range m.BlocksAt(x, y) {
		b := &m.Blocks[bi]
		if b.Bottom >= z && b.Bottom < c && b.Covers(x, y) {
			c = b.Bottom
		}
	}
	return c
}

// nearestOnSegment returns the point of segment a-b closest to p.
func nearestOnSegment(px, py, ax, ay, bx, by float64) (float64, float64) {
	dx, dy := bx-ax, by-ay
	l2 := dx*dx + dy*dy
	if l2 < 1e-18 {
		return ax, ay
	}
	t := clampF(((px-ax)*dx+(py-ay)*dy)/l2, 0, 1)
	return ax + dx*t, ay + dy*t
}

// WallGap returns the horizontal distance from (x,y) to the closest wall whose vertical extent
// overlaps (z0,z1), or limit if there is none that close.
func (m *Map) WallGap(x, y, z0, z1, limit float64) float64 {
	best := limit * limit
	m.wallGrid.forEachIn(x, y, limit, func(c int) {
		for _, wi := range m.wallGrid.list(c) {
			w := &m.Walls[wi]
			if z1 <= w.Bottom || z0 >= w.Top {
				continue
			}
			qx, qy := nearestOnSegment(x, y, w.Ax, w.Ay, w.Bx, w.By)
			if d2 := (x-qx)*(x-qx) + (y-qy)*(y-qy); d2 < best {
				best = d2
			}
		}
	})
	return math.Sqrt(best)
}
