package grid

import (
	"math"

	"zoro/internal/arena"
)

// Openness is a coarse map of how exposed each ground spot is: the mean free sight distance of a
// ring of horizontal rays at eye height, scaled to 0..1. Low values are sheltered pockets; Unusable
// marks lattice points where nobody can stand.
type Openness struct {
	Step   int // lattice spacing in grid cells
	NX, NY int
	V      []float32
	g      *Grid
}

// Unusable is the Openness value of a point where a mech cannot stand.
const Unusable = 2

// Openness returns the shared openness map (built on first use).
func (g *Grid) Openness() *Openness {
	g.cache.openOnce.Do(func() { g.cache.open = measureOpenness(g, 3, 24, 8, 200) })
	return g.cache.open
}

// treeSensorRange is how far proximity sensing reaches regardless of trees.
const treeSensorRange = 45.0

func measureOpenness(g *Grid, step, rays int, eye, reach float64) *Openness {
	o := &Openness{Step: step, g: g, NX: (g.NX + step - 1) / step, NY: (g.NY + step - 1) / step}
	o.V = make([]float32, o.NX*o.NY)
	dirs := make([][2]float64, rays)
	for i := range dirs {
		a := (float64(i) + 0.5) * 2 * math.Pi / float64(rays)
		dirs[i] = [2]float64{math.Cos(a), math.Sin(a)}
	}
	for j := 0; j < o.NY; j++ {
		for i := 0; i < o.NX; i++ {
			k := o.Cell(i, j)
			if g.Blocked[k] || g.Gap[k] < 2.6 {
				o.V[j*o.NX+i] = Unusable
				continue
			}
			x, y := g.Pos(k)
			z := float64(g.Floor[k]) + eye
			total := 0.0
			for _, d := range dirs {
				ray := arena.Ray{X: x, Y: y, Z: z, DX: d[0], DY: d[1]}
				free := g.Map.Cast(ray, reach)
				if free > treeSensorRange {
					if c := g.Map.SightThroughTrees(ray, free); c < free {
						free = math.Max(c, treeSensorRange)
					}
				}
				total += free
			}
			o.V[j*o.NX+i] = float32(total / (float64(rays) * reach))
		}
	}
	return o
}

// Cell returns the grid cell of lattice point (i,j).
func (o *Openness) Cell(i, j int) int {
	c := min(i*o.Step+o.Step/2, o.g.NX-1)
	r := min(j*o.Step+o.Step/2, o.g.NY-1)
	return r*o.g.NX + c
}

// At returns the openness of the lattice point covering grid cell k.
func (o *Openness) At(k int) float32 {
	i := min((k%o.g.NX)/o.Step, o.NX-1)
	j := min((k/o.g.NX)/o.Step, o.NY-1)
	return o.V[j*o.NX+i]
}
