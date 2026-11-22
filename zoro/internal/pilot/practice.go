package pilot

import (
	"math"

	"zoro/internal/wire"
)

// tag names the stance for the debug label.
func (st stance) tag(ffa bool) string {
	switch {
	case st.duel:
		return "duel"
	case st.squad:
		return "squad"
	case ffa:
		return "ffa"
	}
	return "open"
}

// dropRun returns a supply drop worth breaking off for against the house squad: in reach, landing
// about when we would get there, and staying inside the zone. A drop is a full repair and cubes, a
// second life with the squad on us. nil when we are healthy with cubes, or nothing qualifies.
func (p *Pilot) dropRun(st stance, hpFrac float64) *wire.Drop {
	if p.T.DropRun <= 0 || !st.squad || (hpFrac > p.T.DropRunHP && p.o.Self.Cubes >= 10) {
		return nil
	}
	var best *wire.Drop
	bd := math.Inf(1)
	for i := range p.o.Drops {
		dr := &p.o.Drops[i]
		d := flatDist(p.pos, dr.Pos)
		if p.banned(dr.ID) || d > p.T.DropRun || dr.LandsIn > d/p.walk*1.25+p.T.DropRunLead {
			continue
		}
		if !p.safeLater(dr.Pos[0], dr.Pos[1], d/p.walk+6, 4) {
			continue
		}
		if d < bd {
			best, bd = dr, d
		}
	}
	return best
}

// seekTarget is where to go looking for the next fight against the squad when there is nothing else to
// do: the last place of the nearest mech seen lately that we would take on, else somewhere unexplored.
// Practice score is about kills, so time spent waiting for them to come is wasted.
func (p *Pilot) seekTarget(st stance, hpFrac float64) (x, y float64, id int, ok bool) {
	if p.T.Seek <= 0 || !st.squad || hpFrac < p.T.SeekHP {
		return 0, 0, -1, false
	}
	var best *Contact
	bd := math.Inf(1)
	for _, c := range p.contacts {
		if c.Drone || p.now-c.SeenT > p.T.Seek {
			continue
		}
		if u, banned := p.seekBans[c.ID]; banned && p.now < u {
			continue
		}
		d := flatDist(p.pos, c.Pos)
		if d > p.T.SeekRange || !p.safeLater(c.Pos[0], c.Pos[1], 8, 6) {
			continue
		}
		if d < 22 && !c.Listed {
			p.seekBans[c.ID] = p.now + 20 // we are where it was and it is not here
			continue
		}
		if adv, _, _ := p.odds(c, d); adv < st.engage {
			continue
		}
		if d < bd || (d == bd && best != nil && c.ID < best.ID) {
			best, bd = c, d
		}
	}
	if best != nil {
		return best.Pos[0], best.Pos[1], best.ID, true
	}
	x, y, ok = p.exploreGoal()
	return x, y, -1, ok
}

// jink zig-zags the heading while we walk somewhere under fire from range: shooters lead with our
// current velocity, so a straight walk away is the easiest target there is.
func (p *Pilot) jink(tn *turn) {
	lg := &tn.lg
	if p.T.Jink <= 0 || tn.direct || !tn.travelling || lg.still || lg.stayOnRoof || !tn.hurting || (lg.dirX == 0 && lg.dirY == 0) {
		return
	}
	if length(tn.goal[0]-p.pos[0], tn.goal[1]-p.pos[1]) <= 12 {
		return
	}
	far := false
	for i := range tn.ths {
		t := &tn.ths[i]
		if t.engaged && !t.ghost && t.d > 55 && p.now-t.c.HitMeT < 3 {
			far = true
		}
	}
	if !far {
		return
	}
	if p.now >= p.jinkT {
		if p.rng.Float64() < 0.85 {
			p.jinkDir = -p.jinkDir
		}
		p.jinkT = p.now + 0.3 + p.rng.Float64()*0.4
	}
	k := p.T.Jink * p.jinkDir
	lg.dirX, lg.dirY = unit(lg.dirX-lg.dirY*k, lg.dirY+lg.dirX*k)
}

// patient reports whether we are still building up against the squad (cubes and a laser first).
func (p *Pilot) patient(tn *turn) bool {
	return tn.st.squad && p.T.PatientSecs > 0 && p.now < p.T.PatientSecs &&
		(p.o.Self.Cubes < p.T.PatientCubes || p.holding("laser") < 0)
}
