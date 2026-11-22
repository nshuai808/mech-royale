package pilot

import "math"

// zoneView is what the zone means for us right now.
type zoneView struct {
	outNext  float64 // metres outside the next circle (negative: inside)
	outNow   float64 // metres outside the current circle
	edgeIn   float64 // seconds until the shrinking edge passes where we stand
	goal     [2]float64
	onFoot   bool // goal can be walked to
	urgent   bool
	critical bool
	final    bool // the next circle is about a point
}

// zoneCache remembers the standing goal for a second.
type zoneCache struct {
	key    [3]float64
	at     float64
	region int32
	goal   [2]float64
	onFoot bool
}

func (p *Pilot) zone() zoneView {
	z := &p.o.Zone
	var v zoneView
	v.outNext = length(p.pos[0]-z.NextCenter[0], p.pos[1]-z.NextCenter[1]) - z.NextRadius
	v.outNow = length(p.pos[0]-z.Center[0], p.pos[1]-z.Center[1]) - z.Radius
	v.final = z.NextRadius < 12
	v.edgeIn = p.edgeArrival()
	v.goal, v.onFoot = p.zoneGoal()
	need := 0.0
	if v.outNext > 0 {
		need = (v.outNext+8)/p.walk*1.35 + 4
	}
	v.critical = v.outNow > -2 || v.edgeIn < 2.5
	v.urgent = v.critical || v.edgeIn < 9 || (v.outNext > 0 && (z.ShrinkEnd-p.now < need || v.edgeIn-need < 3))
	return v
}

// edgeArrival is the number of seconds until the shrinking circle no longer contains us.
func (p *Pilot) edgeArrival() float64 {
	z := &p.o.Zone
	outNow := length(p.pos[0]-z.Center[0], p.pos[1]-z.Center[1]) - z.Radius
	outNext := length(p.pos[0]-z.NextCenter[0], p.pos[1]-z.NextCenter[1]) - z.NextRadius
	start := math.Max(p.now, z.ShrinkStart)
	switch {
	case outNow > 0:
		return 0
	case outNext <= 0:
		return math.Inf(1)
	case z.ShrinkEnd <= start:
		return 0
	}
	for i := 1; i <= 50; i++ {
		f := float64(i) / 50
		cx, cy, r := p.zoneAt(f)
		if length(p.pos[0]-cx, p.pos[1]-cy) > r {
			return (start - p.now) + f*(z.ShrinkEnd-start)
		}
	}
	return math.Inf(1)
}

// zoneAt interpolates the circle a fraction f of the way through the shrink.
func (p *Pilot) zoneAt(f float64) (cx, cy, r float64) {
	z := &p.o.Zone
	return z.Center[0] + (z.NextCenter[0]-z.Center[0])*f,
		z.Center[1] + (z.NextCenter[1]-z.Center[1])*f,
		z.Radius + (z.NextRadius-z.Radius)*f
}

// zoneGoal picks a standable cell well inside the next circle on our side of it, preferring one in
// our own walkable region. Recomputed about once a second.
func (p *Pilot) zoneGoal() ([2]float64, bool) {
	z := &p.o.Zone
	zc := &p.zoneCache
	key := [3]float64{z.NextCenter[0], z.NextCenter[1], z.NextRadius}
	if key == zc.key && p.now-zc.at <= 1 && zc.region == p.myRegion {
		return zc.goal, zc.onFoot
	}
	zc.key, zc.at, zc.region = key, p.now, p.myRegion
	margin := math.Min(5, z.NextRadius*0.3)
	dx, dy := unit(p.pos[0]-z.NextCenter[0], p.pos[1]-z.NextCenter[1])
	side := math.Atan2(dy, dx)
	var fallback *[2]float64
	for _, frac := range [...]float64{0.6, 0.45, 0.75, 0.3, 0.15, 0.9, 0} {
		rr := math.Max(0, math.Min(z.NextRadius*frac, z.NextRadius-10))
		for _, turn := range [...]float64{0, 0.4, -0.4, 0.8, -0.8, 1.4, -1.4, 2.2, -2.2, math.Pi} {
			x := z.NextCenter[0] + math.Cos(side+turn)*rr
			y := z.NextCenter[1] + math.Sin(side+turn)*rr
			k := p.g.Closest(x, y, p.radius+0.3, p.height, 4)
			if k < 0 {
				continue
			}
			px, py := p.g.Pos(k)
			if z.NextRadius > 12 && length(px-z.NextCenter[0], py-z.NextCenter[1]) > z.NextRadius-margin {
				continue
			}
			if !p.inMyRegion(k) {
				if fallback == nil {
					fallback = &[2]float64{px, py}
				}
				continue
			}
			zc.goal, zc.onFoot = [2]float64{px, py}, true
			return zc.goal, true
		}
	}
	zc.onFoot = false
	if fallback != nil {
		zc.goal = *fallback // standable, but we will have to go over things
	} else {
		zc.goal = z.NextCenter
	}
	return zc.goal, false
}

// safeLater reports whether (x,y) will still be inside the zone, with a margin, in secs seconds.
func (p *Pilot) safeLater(x, y, secs, margin float64) bool {
	z := &p.o.Zone
	if length(x-z.Center[0], y-z.Center[1]) > z.Radius-margin {
		return false
	}
	if p.now+secs <= z.ShrinkStart {
		return true
	}
	f := 1.0
	if z.ShrinkEnd > z.ShrinkStart {
		f = clamp((p.now+secs-z.ShrinkStart)/(z.ShrinkEnd-z.ShrinkStart), 0, 1)
	}
	cx, cy, r := p.zoneAt(f)
	return length(x-cx, y-cy) <= r-margin
}

// inMyRegion reports whether a cell is in the walkable region we stand in.
func (p *Pilot) inMyRegion(k int) bool {
	return p.myRegion == 0 || k < 0 || p.g.Regions()[k] == p.myRegion
}

// walkable reports whether a ground point can be walked to from here.
func (p *Pilot) walkable(x, y float64) bool {
	if p.myRegion == 0 {
		return true
	}
	return p.g.RegionAt(x, y, 3) == p.myRegion
}
