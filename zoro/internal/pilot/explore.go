package pilot

import (
	"math"
	"sort"
)

// exploreCell is the side of a cell of the "when did we last look there" map.
const exploreCell = 32.0

type exploreMap struct {
	nx, ny int
	lastT  []float32
	goal   int // cell we are walking to look at (-1 none)
	goalT  float64
}

func (p *Pilot) exploreCentre(k int) (float64, float64) {
	e := &p.explore
	b := p.m.Bounds
	return b.X0 + (float64(k%e.nx)+0.5)*exploreCell, b.Y0 + (float64(k/e.nx)+0.5)*exploreCell
}

// markExplored stamps the cells in view.
func (p *Pilot) markExplored() {
	e := &p.explore
	b := p.m.Bounds
	if e.lastT == nil {
		e.nx = int(math.Ceil((b.X1-b.X0)/exploreCell)) + 1
		e.ny = int(math.Ceil((b.Y1-b.Y0)/exploreCell)) + 1
		e.lastT = make([]float32, e.nx*e.ny)
		for i := range e.lastT {
			e.lastT[i] = -1e6
		}
		e.goal = -1
	}
	const reach = 150.0
	half := p.cfg.Vision.FovDeg * math.Pi / 360
	if half <= 0 {
		half = math.Pi / 3
	}
	ex, ey, ez := p.pos[0], p.pos[1], p.pos[2]+p.eye
	i0, i1 := int((ex-reach-b.X0)/exploreCell), int((ex+reach-b.X0)/exploreCell)
	j0, j1 := int((ey-reach-b.Y0)/exploreCell), int((ey+reach-b.Y0)/exploreCell)
	for j := max(j0, 0); j <= min(j1, e.ny-1); j++ {
		for i := max(i0, 0); i <= min(i1, e.nx-1); i++ {
			k := j*e.nx + i
			if float64(e.lastT[k]) > p.now-2 {
				continue
			}
			cx, cy := p.exploreCentre(k)
			d := length(cx-ex, cy-ey)
			if d > reach || (d > 40 && math.Abs(wrap(math.Atan2(cy-ey, cx-ex), p.aim[0])) > half) {
				continue
			}
			if d < 20 || p.m.Clear(ex, ey, ez, cx, cy, p.m.Ground(cx, cy)+2) {
				e.lastT[k] = float32(p.now)
			}
		}
	}
}

// exploreGoal picks somewhere inside the next circle we have not looked at for a while.
func (p *Pilot) exploreGoal() (float64, float64, bool) {
	e := &p.explore
	if e.lastT == nil {
		return 0, 0, false
	}
	standAt := func(k int) (float64, float64, bool) {
		x, y := p.exploreCentre(k)
		if c := p.g.Closest(x, y, p.radius+0.3, p.height, 8); c >= 0 {
			px, py := p.g.Pos(c)
			return px, py, true
		}
		return 0, 0, false
	}
	if e.goal >= 0 && p.now-e.goalT < 12 && float64(e.lastT[e.goal]) < p.now-20 {
		if x, y, ok := standAt(e.goal); ok {
			return x, y, true
		}
	}
	z := &p.o.Zone
	best, bs := -1, math.Inf(1)
	for k := range e.lastT {
		age := p.now - float64(e.lastT[k])
		if age < 45 {
			continue
		}
		x, y := p.exploreCentre(k)
		if !p.m.InBounds(x, y) || length(x-z.NextCenter[0], y-z.NextCenter[1]) > z.NextRadius-15 {
			continue
		}
		if p.g.Blocked[p.g.At(x, y)] || p.banned(-(k + 1)) {
			continue
		}
		if !p.walkable(x, y) {
			e.lastT[k] = float32(p.now) // cut off from us
			continue
		}
		if s := length(x-p.pos[0], y-p.pos[1]) - math.Min(age, 300)*0.15; s < bs {
			best, bs = k, s
		}
	}
	if best < 0 {
		return 0, 0, false
	}
	e.goal, e.goalT = best, p.now
	if x, y, ok := standAt(best); ok {
		return x, y, true
	}
	e.lastT[best] = float32(p.now)
	return 0, 0, false
}

// banExploreGoal stops us choosing the current exploration cell for a while.
func (p *Pilot) banExploreGoal() {
	if e := &p.explore; e.goal >= 0 {
		p.bans[-(e.goal + 1)] = p.now + 120
		e.goal = -1
	}
}

// holdSpot picks a sheltered place to wait inside the circle we must end up in, or -1.
func (p *Pilot) holdSpot() int {
	z := &p.o.Zone
	op := p.g.Openness()
	regions := p.g.Regions()
	margin := math.Min(14, z.NextRadius*0.25)
	type option struct {
		cell  int
		score float64
	}
	var opts []option
	for j := 0; j < op.NY; j++ {
		for i := 0; i < op.NX; i++ {
			v := op.V[j*op.NX+i]
			if v > 1.5 {
				continue
			}
			k := op.Cell(i, j)
			if p.myRegion != 0 && regions[k] != p.myRegion {
				continue
			}
			x, y := p.g.Pos(k)
			dn := length(x-z.NextCenter[0], y-z.NextCenter[1])
			if dn > z.NextRadius-margin || !p.g.Fits(k, p.radius+0.4, p.height) {
				continue
			}
			d := length(x-p.pos[0], y-p.pos[1])
			if d > 320 {
				continue
			}
			s := float64(v)*100 + d*0.07 + float64(p.g.Gap[k])*0.8
			if z.NextRadius > 60 && dn < z.NextRadius*0.35 {
				s += 10 // everyone walks through the middle
			}
			if k == p.holdCell {
				s -= 9
			}
			opts = append(opts, option{k, s})
		}
	}
	if len(opts) == 0 {
		return -1
	}
	sort.Slice(opts, func(a, b int) bool { return opts[a].score < opts[b].score })
	if len(opts) > 60 {
		opts = opts[:60]
	}
	best, bs := -1, math.Inf(1)
	for _, o := range opts {
		x, y := p.g.Pos(o.cell)
		feet := float64(p.g.Floor[o.cell])
		s := o.score
		for _, c := range p.contacts {
			if c.Drone || p.now-c.SeenT > 25 {
				continue
			}
			d := length(c.Pos[0]-x, c.Pos[1]-y)
			if d < 90 {
				s += (90 - d) * 0.35
			}
			if d < 260 && p.now-c.SeenT < 8 && p.m.Clear(c.Pos[0], c.Pos[1], c.Pos[2]+8*p.bodyScale(c.Cubes), x, y, feet+p.height*0.6) {
				s += 30
			}
		}
		for _, dr := range p.o.Drops {
			if length(dr.Pos[0]-x, dr.Pos[1]-y) < 70 {
				s += 15
			}
		}
		if s < bs {
			best, bs = o.cell, s
		}
	}
	return best
}
