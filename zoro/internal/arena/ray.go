package arena

import "math"

// Ray is a half-line with a unit direction.
type Ray struct {
	X, Y, Z    float64
	DX, DY, DZ float64
}

func (r Ray) at(t float64) (float64, float64, float64) {
	return r.X + r.DX*t, r.Y + r.DY*t, r.Z + r.DZ*t
}

func (r Ray) finite() bool {
	for _, v := range [...]float64{r.X, r.Y, r.Z, r.DX, r.DY, r.DZ} {
		if math.IsNaN(v) || math.IsInf(v, 0) {
			return false
		}
	}
	return true
}

// Cast returns the distance along r to the first solid surface (terrain, wall, roof or underside),
// or limit when nothing is hit before it.
func (m *Map) Cast(r Ray, limit float64) float64 {
	if !r.finite() {
		return limit
	}
	if math.IsNaN(limit) || limit <= 0 {
		return 0
	}
	hit := m.castBlocks(r, limit)
	return m.castTerrain(r, hit)
}

// Clear reports whether the straight segment between two points is free of terrain and blocks.
func (m *Map) Clear(ax, ay, az, bx, by, bz float64) bool {
	dx, dy, dz := bx-ax, by-ay, bz-az
	d := math.Sqrt(dx*dx + dy*dy + dz*dz)
	if d < 1e-6 {
		return true
	}
	reach := d - 0.05
	return m.Cast(Ray{ax, ay, az, dx / d, dy / d, dz / d}, reach) >= reach
}

// castBlocks walks the bucket grid along the ray (2D DDA) testing walls and horizontal faces.
func (m *Map) castBlocks(r Ray, limit float64) float64 {
	g := &m.wallGrid
	ci := int(math.Floor((r.X - g.x0) / bucketSize))
	cj := int(math.Floor((r.Y - g.y0) / bucketSize))
	if ci < 0 || cj < 0 || ci >= g.nx || cj >= g.ny {
		return limit
	}
	axis := func(o, d, base float64, cell int) (step int, next, delta float64) {
		switch {
		case d > 1e-12:
			return 1, (base + float64(cell+1)*bucketSize - o) / d, bucketSize / d
		case d < -1e-12:
			return -1, (base + float64(cell)*bucketSize - o) / d, -bucketSize / d
		}
		return 0, math.Inf(1), math.Inf(1)
	}
	si, nextX, dX := axis(r.X, r.DX, g.x0, ci)
	sj, nextY, dY := axis(r.Y, r.DY, g.y0, cj)
	best := limit
	enter := 0.0
	vertical := r.DZ < -1e-9 || r.DZ > 1e-9
	for guard := 2*(g.nx+g.ny) + 8; guard > 0; guard-- {
		c := cj*g.nx + ci
		exit := math.Min(nextX, nextY)
		for _, wi := range m.wallGrid.list(c) {
			if t, ok := m.hitWall(&m.Walls[wi], r, best); ok {
				best = t
			}
		}
		if vertical {
			for _, bi := range m.blockGrid.list(c) {
				if t, ok := m.hitFace(&m.Blocks[bi], r, enter, exit, best); ok {
					best = t
				}
			}
		}
		if exit >= best {
			break
		}
		enter = exit
		if nextX < nextY {
			ci += si
			nextX += dX
		} else {
			cj += sj
			nextY += dY
		}
		if ci < 0 || cj < 0 || ci >= g.nx || cj >= g.ny {
			break
		}
	}
	return best
}

// hitWall intersects the ray with a vertical wall face, returning a hit closer than best.
func (m *Map) hitWall(w *Wall, r Ray, best float64) (float64, bool) {
	ex, ey := w.Bx-w.Ax, w.By-w.Ay
	den := r.DX*ey - r.DY*ex
	if math.Abs(den) < 1e-12 {
		return 0, false
	}
	ox, oy := w.Ax-r.X, w.Ay-r.Y
	t := (ox*ey - oy*ex) / den
	if t <= 1e-9 || t >= best {
		return 0, false
	}
	if s := (ox*r.DY - oy*r.DX) / den; s < 0 || s > 1 {
		return 0, false
	}
	if z := r.Z + t*r.DZ; z < w.Bottom || z > w.Top {
		return 0, false
	}
	return t, true
}

// hitFace intersects the ray with a block's roof (going down) or underside (going up), within the
// part of the ray inside the current bucket.
func (m *Map) hitFace(b *Block, r Ray, enter, exit, best float64) (float64, bool) {
	var t float64
	if r.DZ < 0 {
		if r.Z < b.Top {
			return 0, false
		}
		t = (b.Top - r.Z) / r.DZ
	} else {
		if r.Z > b.Bottom {
			return 0, false
		}
		t = (b.Bottom - r.Z) / r.DZ
	}
	if t < 0 || t >= best || t < enter-1e-6 || t > exit+1e-6 {
		return 0, false
	}
	x, y, _ := r.at(t)
	return t, b.Covers(x, y)
}

// castTerrain marches the ray over the heightfield with adaptive steps and refines the crossing by
// bisection.
func (m *Map) castTerrain(r Ray, limit float64) float64 {
	if r.Z > m.peak && r.Z+r.DZ*limit > m.peak {
		return limit
	}
	above := func(t float64) float64 {
		x, y, z := r.at(t)
		return z - m.Ground(x, y)
	}
	clearance := above(0)
	if clearance < 0 {
		return 0
	}
	const skip = 8.0
	t, last := 0.0, 0.0
	for t < limit {
		if t+skip < limit {
			x0, y0, z0 := r.at(t)
			x1, y1, z1 := r.at(t + skip)
			low := math.Min(z0, z1)
			if top1 := m.tileTop(x1, y1); low > m.tileTop(x0, y0)+0.3 && low > top1+0.3 {
				t += skip
				last, clearance = t, z1-top1
				continue
			}
		}
		t += clampF(clearance*0.5, 1, 12)
		if t > limit {
			t = limit
		}
		h := above(t)
		if h < 0 {
			lo, hi := last, t
			for k := 0; k < 12; k++ {
				mid := 0.5 * (lo + hi)
				if above(mid) < 0 {
					hi = mid
				} else {
					lo = mid
				}
			}
			return lo
		}
		last, clearance = t, h
	}
	return limit
}
