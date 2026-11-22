package grid

import "math"

// Roof is a flat rooftop region (connected blocked cells with about the same roof height).
type Roof struct {
	ID     int
	Z      float64 // surface height
	Cells  []int32
	Area   float64 // m²
	Climb  float64 // height above the lowest ground next to it
	Core   int     // the cell deepest inside the region
	CoreD  float64 // its distance to the region edge (m)
	CX, CY float64 // centroid
	Ways   []Way   // places where the wall can be jetted up
}

// Way is a climbable spot: stand on Foot, jet up, land on Top.
type Way struct {
	Foot int
	Top  int
	Rise float64
}

// Roofs returns the usable rooftop regions and, per cell, the roof id (-1 for none).
func (g *Grid) Roofs() ([]Roof, []int32) {
	g.cache.roofsOnce.Do(g.findRoofs)
	return g.cache.roofs, g.cache.roofID
}

// RoofDepth returns, per roof cell, its distance to the roof edge in cells (1 = an edge cell).
func (g *Grid) RoofDepth() []int16 {
	g.Roofs()
	return g.cache.roofDepth
}

func (g *Grid) roofCell(k int) bool { return g.Blocked[k] && !math.IsNaN(float64(g.RoofTop[k])) }

func (g *Grid) findRoofs() {
	n := g.NX * g.NY
	owner := make([]int32, n)
	for i := range owner {
		owner[i] = -1
	}
	var all []Roof
	var stack []int
	for seed := 0; seed < n; seed++ {
		if owner[seed] >= 0 || !g.roofCell(seed) {
			continue
		}
		id := int32(len(all))
		level := float64(g.RoofTop[seed])
		owner[seed] = id
		stack = append(stack[:0], seed)
		var cells []int32
		sum := 0.0
		for len(stack) > 0 {
			k := stack[len(stack)-1]
			stack = stack[:len(stack)-1]
			cells = append(cells, int32(k))
			sum += float64(g.RoofTop[k])
			c, r := k%g.NX, k/g.NX
			for d := 0; d < 4; d++ {
				nc, nr := c+offC[d], r+offR[d]
				if !g.inside(nc, nr) {
					continue
				}
				nk := nr*g.NX + nc
				if owner[nk] >= 0 || !g.roofCell(nk) {
					continue
				}
				h := float64(g.RoofTop[nk])
				if math.Abs(h-level) > 0.8 || math.Abs(h-float64(g.RoofTop[k])) > 0.6 {
					continue
				}
				owner[nk] = id
				stack = append(stack, nk)
			}
		}
		all = append(all, Roof{ID: int(id), Z: sum / float64(len(cells)), Cells: cells, Area: float64(len(cells)) * g.Cell * g.Cell})
	}
	depth := make([]int16, n)
	for i := range all {
		g.measureRoof(&all[i], owner, depth)
	}
	// keep the roofs worth standing on and renumber them
	remap := make([]int32, len(all))
	var kept []Roof
	for i := range all {
		r := all[i]
		remap[i] = -1
		if r.Area < 250 || r.CoreD < 5 || len(r.Ways) == 0 {
			continue
		}
		remap[i] = int32(len(kept))
		r.ID = len(kept)
		kept = append(kept, r)
	}
	for k := range owner {
		if owner[k] >= 0 {
			owner[k] = remap[owner[k]]
		}
		if owner[k] < 0 {
			depth[k] = 0
		}
	}
	g.cache.roofs, g.cache.roofID, g.cache.roofDepth = kept, owner, depth
}

// measureRoof fills in depth (BFS from the edge), core, centroid, climb height and the climb ways.
func (g *Grid) measureRoof(r *Roof, owner []int32, depth []int16) {
	me := int32(r.ID)
	var queue []int32
	lowest := math.Inf(1)
	sx, sy := 0.0, 0.0
	for _, cell := range r.Cells {
		k := int(cell)
		x, y := g.Pos(k)
		sx += x
		sy += y
		c, row := k%g.NX, k/g.NX
		edge := false
		for d := 0; d < 8; d++ {
			nc, nr := c+offC[d], row+offR[d]
			if !g.inside(nc, nr) {
				edge = true
				continue
			}
			nk := nr*g.NX + nc
			if owner[nk] == me {
				continue
			}
			edge = true
			if !g.Blocked[nk] {
				lowest = math.Min(lowest, float64(g.Floor[nk]))
			}
		}
		depth[k] = 0
		if edge {
			depth[k] = 1
			queue = append(queue, cell)
		}
	}
	r.CX, r.CY = sx/float64(len(r.Cells)), sy/float64(len(r.Cells))
	for i := 0; i < len(queue); i++ {
		k := int(queue[i])
		c, row := k%g.NX, k/g.NX
		for d := 0; d < 4; d++ {
			nc, nr := c+offC[d], row+offR[d]
			if !g.inside(nc, nr) {
				continue
			}
			nk := nr*g.NX + nc
			if owner[nk] == me && depth[nk] == 0 {
				depth[nk] = depth[k] + 1
				queue = append(queue, int32(nk))
			}
		}
	}
	core, coreD := int(r.Cells[0]), int16(0)
	for _, cell := range r.Cells {
		if depth[cell] > coreD {
			core, coreD = int(cell), depth[cell]
		}
	}
	r.Core = core
	r.CoreD = (float64(coreD) - 0.5) * g.Cell
	if !math.IsInf(lowest, 1) {
		r.Climb = r.Z - lowest
	}
	// climb ways: from an edge cell, open air right outside, a standable cell 2-3 cells out, and
	// roof two cells in to land on
	for _, cell := range r.Cells {
		k := int(cell)
		if depth[k] != 1 {
			continue
		}
		c, row := k%g.NX, k/g.NX
		for d := 0; d < 4; d++ {
			dc, dr := offC[d], offR[d]
			if !g.inside(c+dc, row+dr) || g.Blocked[(row+dr)*g.NX+c+dc] {
				continue
			}
			for out := 2; out <= 3; out++ {
				fc, fr := c+dc*out, row+dr*out
				if !g.inside(fc, fr) {
					break
				}
				foot := fr*g.NX + fc
				if g.Blocked[foot] {
					break
				}
				if !g.Fits(foot, 2.7, 9) {
					continue
				}
				lc, lr := c-dc*2, row-dr*2
				if !g.inside(lc, lr) || owner[lr*g.NX+lc] != me {
					break
				}
				r.Ways = append(r.Ways, Way{Foot: foot, Top: lr*g.NX + lc, Rise: r.Z - float64(g.Floor[foot])})
				break
			}
		}
	}
}
