package pilot

import "math"

// stance is how we play: the normal careful brawler, or all-in once only two are left.
type stance struct {
	duel       bool
	squad      bool // the house squad: hunt them, with the hit model that suits them
	engage     float64
	disengage  float64
	careful    bool // decline even exchanges at range; go for cover instead
	lootRadius float64
	wantCubes  int
}

func (p *Pilot) stance() stance {
	if p.o.Alive <= 2 {
		// second place is banked: nothing to lose by fighting for first
		return stance{duel: true, engage: 0, disengage: 0.45, lootRadius: 150, wantCubes: 40}
	}
	if p.practice() {
		return stance{squad: true, engage: p.T.SquadEngage, disengage: p.T.Disengage, lootRadius: p.T.LootRadius, wantCubes: p.T.SquadCubes}
	}
	return stance{engage: p.T.Engage, disengage: p.T.Disengage, careful: true, lootRadius: p.T.LootRadius, wantCubes: p.T.WantCubes}
}

// threat is an enemy mech as it matters to this decision.
type threat struct {
	c       *Contact
	d       float64
	adv     float64 // best advantage over the ranges we could fight at
	near    float64 // the range band that gives it
	far     float64
	engaged bool
	dps     float64
	ghost   bool // an unseen shooter placed along a damage bearing
}

// assess lists the enemy mechs worth thinking about.
func (p *Pilot) assess() []threat {
	var out []threat
	for _, c := range p.contacts {
		if c.Drone {
			continue
		}
		ghost := !c.Listed && p.now-c.GhostT < 4 && p.now-c.SeenT > 1
		if p.now-c.SeenT > 8 && !ghost {
			continue
		}
		t := threat{c: c, d: spaceDist(p.pos, c.Pos), ghost: ghost}
		t.adv, t.near, t.far = p.odds(c, t.d)
		t.dps = p.theirDPS(c, t.d)
		watch := 200.0
		if c.Laser {
			watch = math.Max(watch, p.T.LaserWatch) // a laser hits as well at 280 m as anywhere
		}
		t.engaged = p.now-c.HitMeT < 4 || (c.Visible && p.now-c.FacedT < 0.6 && t.d < watch) || (c.Visible && t.d < 40)
		if !t.engaged && c.Visible && t.d < 90 {
			// walking at us with its torso turned our way: about to open up
			closing := (c.Vel[0]*(p.pos[0]-c.Pos[0]) + c.Vel[1]*(p.pos[1]-c.Pos[1])) / math.Max(t.d, 1)
			if math.Abs(wrap(c.Aim[0], bearing(c.Pos, p.pos))) < 0.5 && closing > 4 {
				t.engaged = true
			}
		}
		if ghost {
			// we only know it is hurting us: assume the worst until we see it
			t.engaged = true
			t.dps = math.Max(t.dps, c.HitMe/3)
			t.adv = math.Min(t.adv, 0.5)
		}
		// a little hysteresis, so a flickering flag does not flip the whole decision
		if t.engaged {
			c.EngagedT = p.now
		} else if p.now-c.EngagedT < 0.8 && c.Listed {
			t.engaged = true
		}
		out = append(out, t)
	}
	return out
}

// eye is a point an enemy looks from.
type eye struct{ x, y, z float64 }

// eyesOf returns the eye points of the threats seen in the last memory seconds within maxD.
func (p *Pilot) eyesOf(ths []threat, maxD, memory float64) []eye {
	var out []eye
	for i := range ths {
		c := ths[i].c
		if ths[i].d > maxD || (p.now-c.SeenT > memory && !ths[i].ghost) {
			continue
		}
		out = append(out, eye{c.Pos[0], c.Pos[1], c.Pos[2] + 8*p.bodyScale(c.Cubes)})
	}
	return out
}

// seenFrom reports whether a mech standing with its feet at (x,y,feet) shows (middle or head) to e.
func (p *Pilot) seenFrom(e eye, x, y, feet, head float64) bool {
	return p.m.Clear(e.x, e.y, e.z, x, y, feet+p.height*0.5) || p.m.Clear(e.x, e.y, e.z, x, y, feet+p.height*head)
}

// hiddenFrom reports whether none of the eyes sees a mech standing at (x,y,feet).
func (p *Pilot) hiddenFrom(eyes []eye, x, y, feet, head float64) bool {
	for _, e := range eyes {
		if p.seenFrom(e, x, y, feet, head) {
			return false
		}
	}
	return true
}

// hiddenNow reports whether no recent threat can see us where we stand.
func (p *Pilot) hiddenNow(ths []threat) bool {
	return p.hiddenFrom(p.eyesOf(ths, 260, 6), p.pos[0], p.pos[1], p.pos[2], 0.95)
}

// cellHidden reports whether a mech standing in cell k is out of every recent threat's sight.
func (p *Pilot) cellHidden(k int, ths []threat) bool {
	x, y := p.g.Pos(k)
	return p.hiddenFrom(p.eyesOf(ths, 260, 6), x, y, float64(p.g.Floor[k]), 0.95)
}

// coverCandidate filters cells for the cover searches: every other cell, room to stand, and safe from
// the zone for a while.
func (p *Pilot) coverCandidate(k int) bool {
	if (k%p.g.NX+k/p.g.NX)%2 != 0 || float64(p.g.Gap[k]) < p.radius+0.6 {
		return false
	}
	x, y := p.g.Pos(k)
	z := &p.o.Zone
	if length(x-z.Center[0], y-z.Center[1]) > z.Radius-6 {
		return false
	}
	return z.ShrinkEnd-p.now >= 25 || length(x-z.NextCenter[0], y-z.NextCenter[1]) <= z.NextRadius-4
}

// nearestCover returns the closest walkable cell hidden from every recent threat, within maxCost
// metres of walking, or -1.
func (p *Pilot) nearestCover(ths []threat, maxCost float64) int {
	eyes := p.eyesOf(ths, 260, 6)
	if len(eyes) == 0 {
		return -1
	}
	found, checked := -1, 0
	p.g.Spread(p.pos[0], p.pos[1], p.radius+0.15, p.height, maxCost, nil, func(k int, _ float32) bool {
		if !p.coverCandidate(k) {
			return true
		}
		if checked++; checked > 700 {
			return false
		}
		x, y := p.g.Pos(k)
		if !p.hiddenFrom(eyes, x, y, float64(p.g.Floor[k]), 0.95) {
			return true
		}
		found = k
		return false
	})
	return found
}

// deeperCover goes on from the edge of a shadow to a spot that stays hidden when the threats step
// DeepMargin metres sideways, with the straight way there hidden too. With away set and a threat
// inside DeepRange, the spot must also be DeepGain metres farther from it. -1: where we stand is good
// enough, or nothing qualifies.
func (p *Pilot) deeperCover(ths []threat, maxCost float64, away bool) int {
	eyes := p.eyesOf(ths, 260, 6)
	if len(eyes) == 0 {
		return -1
	}
	nearest := math.Inf(1)
	for _, e := range eyes {
		nearest = math.Min(nearest, length(e.x-p.pos[0], e.y-p.pos[1]))
	}
	needAway := away && p.T.DeepRange > 0 && nearest <= p.T.DeepRange
	margin := p.T.DeepMargin
	if margin <= 0 && !needAway {
		return -1
	}
	solid := func(x, y, feet float64) bool {
		for _, e := range eyes {
			if p.seenFrom(e, x, y, feet, 0.95) {
				return false
			}
			if margin <= 0 {
				continue
			}
			dx, dy := x-e.x, y-e.y
			l := length(dx, dy)
			if l < 1 {
				return false
			}
			sx, sy := -dy/l*margin, dx/l*margin
			if p.seenFrom(eye{e.x + sx, e.y + sy, e.z}, x, y, feet, 0.95) || p.seenFrom(eye{e.x - sx, e.y - sy, e.z}, x, y, feet, 0.95) {
				return false
			}
		}
		return true
	}
	if !needAway && solid(p.pos[0], p.pos[1], p.pos[2]) {
		return -1
	}
	found, checked := -1, 0
	p.g.Spread(p.pos[0], p.pos[1], p.radius+0.15, p.height, maxCost, nil, func(k int, _ float32) bool {
		if !p.coverCandidate(k) {
			return true
		}
		x, y := p.g.Pos(k)
		if needAway {
			far := math.Inf(1)
			for _, e := range eyes {
				far = math.Min(far, length(x-e.x, y-e.y))
			}
			if far < nearest+p.T.DeepGain {
				return true
			}
		}
		if checked++; checked > 300 {
			return false
		}
		if !solid(x, y, float64(p.g.Floor[k])) {
			return true
		}
		for _, f := range [...]float64{0.25, 0.5, 0.75} {
			mx, my := p.pos[0]+(x-p.pos[0])*f, p.pos[1]+(y-p.pos[1])*f
			if mk := p.g.At(mx, my); !p.g.Blocked[mk] && !p.hiddenFrom(eyes, mx, my, float64(p.g.Floor[mk]), 0.95) {
				return true
			}
		}
		found = k
		return false
	})
	return found
}

// watchers lists the threats that have a line to us right now.
func watchers(ths []threat, maxD float64) []*threat {
	var out []*threat
	for i := range ths {
		if ths[i].c.Visible && ths[i].c.Listed && ths[i].d < maxD {
			out = append(out, &ths[i])
		}
	}
	return out
}

// laserEdge reports whether we hold a laser and c does not.
func (p *Pilot) laserEdge(c *Contact) bool { return p.holding("laser") >= 0 && !c.Laser }

// nearlyDead reports whether a visible contact would fall to one more burst of ours.
func (p *Pilot) nearlyDead(t *threat, slack, extra float64) bool {
	c := t.c
	return c.Visible && c.HP > 0 && c.HP < p.ourDPS(t.d)*slack+extra
}
