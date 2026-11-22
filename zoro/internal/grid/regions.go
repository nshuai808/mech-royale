package grid

import "math"

// regionBody is the reference body used to split the walk grid into connected regions.
const (
	regionRad = 2.9
	regionH   = 9.0
)

// Regions labels each cell with the connected walkable region a standard mech can reach from it
// (0 = not walkable). Built once.
func (g *Grid) Regions() []int32 {
	g.cache.regionsOnce.Do(func() {
		lab := make([]int32, g.NX*g.NY)
		var stack []int
		var next int32
		for seed := range lab {
			if lab[seed] != 0 || !g.Fits(seed, regionRad, regionH) {
				continue
			}
			next++
			lab[seed] = next
			stack = append(stack[:0], seed)
			for len(stack) > 0 {
				k := stack[len(stack)-1]
				stack = stack[:len(stack)-1]
				c, r := k%g.NX, k/g.NX
				for d := 0; d < 4; d++ {
					nc, nr := c+offC[d], r+offR[d]
					if !g.inside(nc, nr) {
						continue
					}
					nk := nr*g.NX + nc
					if lab[nk] != 0 || !g.Fits(nk, regionRad, regionH) {
						continue
					}
					if !g.stepOK(k, nk, g.Cell) && !g.stepOK(nk, k, g.Cell) {
						continue
					}
					lab[nk] = next
					stack = append(stack, nk)
				}
			}
		}
		g.cache.regions = lab
	})
	return g.cache.regions
}

// RegionAt returns the region of the walkable cell nearest (x,y), or 0.
func (g *Grid) RegionAt(x, y float64, ring int) int32 {
	if k := g.Closest(x, y, regionRad, regionH, ring); k >= 0 {
		return g.Regions()[k]
	}
	return 0
}

// Tops returns, for every cell, the height of the highest surface there (terrain or block top).
func (g *Grid) Tops() []float32 {
	g.cache.topsOnce.Do(func() {
		t := make([]float32, g.NX*g.NY)
		for k := range t {
			x, y := g.Pos(k)
			t[k] = float32(g.Map.Floor(x, y, math.Inf(1)))
		}
		g.cache.tops = t
	})
	return g.cache.tops
}
