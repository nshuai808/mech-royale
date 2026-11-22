package pilot

import (
	"math"

	"zoro/internal/grid"
	"zoro/internal/wire"
)

// Rooftops: standing back from the edge of a tall roof, a mech cannot be seen from the ground
// around the building. Getting up costs a third of the energy bar and is dangerous in view of others.

type roofStage int

const (
	roofIdle roofStage = iota
	roofGoing
	roofClimbing
	roofUp
)

type roofPlan struct {
	stage   roofStage
	id      int
	way     grid.Way
	since   float64 // when the current stage began
	picked  float64 // last time a roof was chosen
	active  float64 // last decision that used the plan
	waiting float64 // since when we wait at the wall for watchers to go (0 = not waiting)
	bans    map[int]float64
}

// roofUnder returns the roof we are standing on, or -1.
func (p *Pilot) roofUnder() int {
	roofs, owner := p.g.Roofs()
	id := int(owner[p.g.At(p.pos[0], p.pos[1])])
	if id < 0 || id >= len(roofs) || math.Abs(p.pos[2]-roofs[id].Z) >= 1.6 {
		return -1
	}
	return id
}

func (p *Pilot) banRoof(id int, secs float64) {
	p.roof.bans[id] = p.now + secs
	p.roof.stage = roofIdle
}

// wantRoof reports whether waiting on a roof is the plan once nothing else needs doing.
func (p *Pilot) wantRoof(st stance, zi zoneView) bool {
	if !p.T.UseRoofs || st.duel || st.squad || zi.final || p.o.Zone.NextRadius < p.T.RoofMinZone {
		return false
	}
	return p.holding("laser") >= 0 || p.o.Self.Cubes >= p.T.RoofCubes || p.now >= p.T.RoofAfter
}

// roofCoreInZone reports whether a roof's deepest cell is comfortably inside the next circle.
func (p *Pilot) roofCoreInZone(r *grid.Roof) bool {
	z := &p.o.Zone
	x, y := p.g.Pos(r.Core)
	return length(x-z.NextCenter[0], y-z.NextCenter[1]) < z.NextRadius-8
}

// pickRoof chooses the roof to go to and the way up.
func (p *Pilot) pickRoof() (int, grid.Way, bool) {
	roofs, _ := p.g.Roofs()
	regions := p.g.Regions()
	mine := p.g.RegionAt(p.pos[0], p.pos[1], 6)
	limit := math.Min(p.climbLimit(), p.T.RoofMaxClimb)
	bestID, bestScore := -1, math.Inf(1)
	var bestWay grid.Way
	for i := range roofs {
		r := &roofs[i]
		if u, ok := p.roof.bans[i]; ok && p.now < u {
			continue
		}
		if r.Climb < p.T.RoofMinHeight || r.CoreD < 6+p.radius || !p.roofCoreInZone(r) {
			continue
		}
		if length(r.CX-p.pos[0], r.CY-p.pos[1]) > 260+math.Sqrt(r.Area) {
			continue
		}
		var way grid.Way
		wd := math.Inf(1)
		for _, w := range r.Ways {
			if w.Rise > limit || w.Rise < 6 || (mine != 0 && regions[w.Foot] != mine) || !p.g.Fits(w.Foot, p.radius+0.2, p.height) {
				continue
			}
			x, y := p.g.Pos(w.Foot)
			if d := length(x-p.pos[0], y-p.pos[1]); d < wd {
				way, wd = w, d
			}
		}
		if math.IsInf(wd, 1) {
			continue
		}
		score := wd*1.2 - math.Min(r.CoreD, 25)*2.5 - math.Min(r.Climb, 30)*1.5
		cx, cy := p.g.Pos(r.Core)
		for _, c := range p.contacts {
			if c.Drone || p.now-c.SeenT > 20 {
				continue
			}
			if d := length(c.Pos[0]-cx, c.Pos[1]-cy); d < 120 {
				score += (120 - d) * 0.6
			}
		}
		if i == p.roof.id && p.roof.stage != roofIdle {
			score -= 40
		}
		if score < bestScore {
			bestID, bestScore, bestWay = i, score, way
		}
	}
	return bestID, bestWay, bestID >= 0
}

// roofStand returns where to stand on roof id: its core, or uphill on the edge-distance field when
// the straight way there would cross the edge.
func (p *Pilot) roofStand(id int) (float64, float64) {
	roofs, owner := p.g.Roofs()
	depth := p.g.RoofDepth()
	r := &roofs[id]
	here := p.g.At(p.pos[0], p.pos[1])
	cx, cy := p.g.Pos(r.Core)
	if int(owner[here]) != id {
		return cx, cy
	}
	n := int(length(cx-p.pos[0], cy-p.pos[1])/2) + 1
	direct := true
	for s := 1; s <= n && direct; s++ {
		f := float64(s) / float64(n)
		k := p.g.At(p.pos[0]+(cx-p.pos[0])*f, p.pos[1]+(cy-p.pos[1])*f)
		direct = int(owner[k]) == id && depth[k] >= 2
	}
	if direct {
		return cx, cy
	}
	col, row := here%p.g.NX, here/p.g.NX
	best, bd := here, depth[here]
	for dr := -3; dr <= 3; dr++ {
		for dc := -3; dc <= 3; dc++ {
			c, rr := col+dc, row+dr
			if c < 0 || rr < 0 || c >= p.g.NX || rr >= p.g.NY {
				continue
			}
			if k := rr*p.g.NX + c; int(owner[k]) == id && depth[k] > bd {
				best, bd = k, depth[k]
			}
		}
	}
	return p.g.Pos(best)
}

// roofHide finds the nearest spot on roof id that none of the threats can see, or -1.
func (p *Pilot) roofHide(id int, ths []threat) int {
	roofs, owner := p.g.Roofs()
	depth := p.g.RoofDepth()
	r := &roofs[id]
	eyes := p.eyesOf(ths, 280, 8)
	if len(eyes) == 0 {
		return -1
	}
	best, bd := -1, math.Inf(1)
	for _, cell := range r.Cells {
		k := int(cell)
		if (k%p.g.NX+k/p.g.NX)%2 != 0 || depth[k] < 3 || int(owner[k]) != id {
			continue
		}
		x, y := p.g.Pos(k)
		d := length(x-p.pos[0], y-p.pos[1])
		if d > 50 || d >= bd {
			continue
		}
		if p.hiddenFrom(eyes, x, y, r.Z, 0.97) {
			best, bd = k, d
		}
	}
	return best
}

// mechUpHere reports whether an enemy is on the roof with us.
func (p *Pilot) mechUpHere(ths []threat) bool {
	for i := range ths {
		if ths[i].c.Listed && ths[i].d < 70 && math.Abs(ths[i].c.Pos[2]-p.pos[2]) < 5 {
			return true
		}
	}
	return false
}

// climb drives the jet climb up the chosen way (writes the command directly).
func (p *Pilot) climb(cmd *wire.Command) {
	roofs, owner := p.g.Roofs()
	r := &roofs[p.roof.id]
	tx, ty := p.g.Pos(p.roof.way.Top)
	dx, dy := unit(tx-p.pos[0], ty-p.pos[1])
	cmd.Move = [2]float64{dx, dy}
	feet, grounded := p.pos[2], p.o.Self.Grounded
	over := int(owner[p.g.At(p.pos[0], p.pos[1])]) == p.roof.id
	switch {
	case grounded && over && math.Abs(feet-r.Z) < 1.6:
		p.roof.stage, p.roof.since = roofUp, p.now
		return
	case grounded && feet < r.Z-1:
		cmd.Jump = true
	case feet < r.Z+0.7:
		cmd.Boost = true
	case !over:
		cmd.Boost = p.vel[2] < 0.5 // hold height while drifting over the lip
	}
	if p.now-p.roof.since > p.roof.way.Rise/8+5 || (p.energy < 2 && !grounded && feet < r.Z-0.5) {
		p.banRoof(p.roof.id, 90)
	}
}

// roofStep runs the roof plan as the idle behaviour. It returns where to walk and whether we are
// settled; ok is false when there is no roof to use.
func (p *Pilot) roofStep() (gx, gy float64, settled, ok bool) {
	roofs, _ := p.g.Roofs()
	rp := &p.roof
	if p.now-rp.active > 1.5 {
		rp.since = p.now // resuming after other business
	}
	rp.active = p.now
	if id := p.roofUnder(); id >= 0 && p.o.Self.Grounded {
		r := &roofs[id]
		stay := p.roofCoreInZone(r) && r.Climb >= p.T.RoofMinHeight-3
		if stay {
			z := &p.o.Zone
			if sx, sy := p.roofStand(id); length(sx-z.NextCenter[0], sy-z.NextCenter[1]) > z.NextRadius-4 {
				stay = false
				p.banRoof(id, 60)
			}
		}
		if !stay && p.pinnedRoof {
			stay = true // watched, and the zone is not here yet: do not climb down in front of them
		}
		if stay {
			rp.stage, rp.id = roofUp, id
			x, y := p.roofStand(id)
			return x, y, length(x-p.pos[0], y-p.pos[1]) < 2, true
		}
		rp.stage = roofIdle
	}
	if rp.stage == roofUp {
		rp.stage = roofIdle // fell or walked off
	}
	if rp.stage == roofIdle || p.now-rp.picked > 3 {
		id, way, found := p.pickRoof()
		rp.picked = p.now
		if !found {
			rp.stage = roofIdle
			return 0, 0, false, false
		}
		if rp.stage == roofIdle || id != rp.id {
			rp.stage, rp.id, rp.way, rp.since = roofGoing, id, way, p.now
		}
	}
	gx, gy = p.g.Pos(rp.way.Foot)
	if length(gx-p.pos[0], gy-p.pos[1]) < 1.6 && p.onGround() {
		if p.holdClimb {
			// someone is about: no jetting up in front of them; if it lasts, try another roof later
			if rp.waiting <= 0 {
				rp.waiting = p.now
			}
			if p.now-rp.waiting > 4 {
				rp.waiting = 0
				p.banRoof(rp.id, 20)
				return 0, 0, false, false
			}
			return gx, gy, true, true
		}
		rp.waiting = 0
		if p.energy >= rp.way.Rise/jetRise*p.o.Self.Stats.Get("jet_drain", 15)+24 {
			rp.stage, rp.since = roofClimbing, p.now
		}
		return gx, gy, true, true
	}
	if p.now-rp.since > 60 {
		p.banRoof(rp.id, 60)
		return 0, 0, false, false
	}
	return gx, gy, false, true
}
