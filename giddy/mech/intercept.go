package mech

import "math"

// One fixed destination per sighting, so a succession of ticks cannot turn
// a short sidestep into a chase.
type interceptPlan struct {
	hunter       int
	seen         float64
	stand, cross Vec3
}

func (b *Brain) intercept(o *Obs, seen []*Track) (interceptPlan, bool) {
	var hunter *Track
	for _, t := range seen {
		age := o.T - t.Seen
		if age <= 0 || t.clearSeen != t.Seen || age > 0.8 || t.Kind != "mech" {
			continue
		}
		if hunter != nil {
			return interceptPlan{}, false
		}
		hunter = t
	}
	if hunter == nil {
		return interceptPlan{}, false
	}
	if b.lane.hunter == hunter.ID && b.lane.seen == hunter.Seen && b.lane.seen > 0 {
		return b.lane, true
	}
	me := &o.Self
	x, y := me.Pos[0], me.Pos[1]
	dx, dy := hunter.Pos[0]-x, hunter.Pos[1]-y
	dist := hyp(dx, dy)
	if dist < 15 || dist > 130 || -(dx*hunter.Vel[0]+dy*hunter.Vel[1])/dist < 2 {
		return interceptPlan{}, false
	}
	age := o.T - hunter.Seen
	muzzle := Vec3{x, y, me.Pos[2] + me.Stats.MuzzleHeight}
	for _, ahead := range []float64{0.5, 0.9} {
		cross := b.center(hunter)
		cross[0] += hunter.Vel[0] * (age + ahead)
		cross[1] += hunter.Vel[1] * (age + ahead)
		if !b.W.LineWalkable(hunter.Pos[0], hunter.Pos[1], cross[0], cross[1]) {
			continue
		}
		cross[2] += b.W.WalkAt(cross[0], cross[1]) - b.W.WalkAt(hunter.Pos[0], hunter.Pos[1])
		lastBlocked := !b.W.Clear(muzzle, b.center(hunter))
		fromHere := b.W.Clear(muzzle, cross)
		if fromHere && !lastBlocked {
			continue
		}
		for _, step := range []float64{0, 3, -3, 5, -5} {
			if step == 0 && !fromHere {
				continue
			}
			sx, sy := x-step*dy/dist, y+step*dx/dist
			if math.Abs(step) > me.Stats.WalkSpeed*ahead || !b.W.Free(sx, sy) || !b.W.LineWalkable(x, y, sx, sy) || b.zonePenalty(&o.Zone, sx, sy) > 0 {
				continue
			}
			if !b.W.Clear(Vec3{sx, sy, b.W.WalkAt(sx, sy) + me.Stats.MuzzleHeight}, cross) {
				continue
			}
			b.lane = interceptPlan{hunter.ID, hunter.Seen, Vec3{sx, sy, 0}, cross}
			return b.lane, true
		}
	}
	return interceptPlan{}, false
}
