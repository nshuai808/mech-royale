package pilot

import (
	"math"

	"zoro/internal/wire"
)

// turn holds everything one decision works out before moving and shooting.
type turn struct {
	st       stance
	zi       zoneView
	ths      []threat
	tgt      *threat
	engaged  int
	pressure float64 // summed damage rate of everyone engaged with us
	overall  float64 // can we out-trade everyone on us, one at a time
	hpFrac   float64
	danger   bool
	hurting  bool // weapon damage in the last 3 s
	watched  []*threat
	onRoof   bool
	roofPlan bool

	// intent
	fight      bool
	slip       bool // go behind cover, shooting back
	plink      bool // light fire from range: keep farming, shoot back in between
	unprovoked bool // watched, not attacked: guns quiet
	duck       bool // on our roof: step behind its edge
	quiet      bool

	// legs
	lg         legs
	heading    float64
	hasHeading bool
	goal       [2]float64
	goalOK     bool
	travelling bool
	direct     bool // the command's movement was written directly

	// torso
	item     *mark
	itemHP   float64
	holdFire bool
	pestShot bool
}

func (p *Pilot) decide(cmd *wire.Command) {
	p.chooseUpgrade(cmd)
	p.grabWeapon(cmd)
	p.readLobby()
	tn := &turn{st: p.stance(), zi: p.zone(), ths: p.assess(), hpFrac: p.hp / p.maxHP, goalOK: true}
	tn.lg.shells = p.incoming()
	p.pickTarget(tn)
	tn.watched = watchers(tn.ths, 230)
	tn.hurting = p.now-p.hurtT < 3
	tn.danger = tn.engaged > 0 || tn.hurting
	tn.onRoof = p.roofUnder() >= 0 && p.o.Self.Grounded
	tn.roofPlan = p.wantRoof(tn.st, tn.zi)
	p.weighFight(tn)
	p.updateRetreat(tn)
	p.chooseIntent(tn)
	p.updateQuiet(tn)
	p.setupLegs(tn)
	p.chooseMode(cmd, tn)
	if !tn.direct && tn.travelling && !tn.lg.still && !tn.lg.stayOnRoof && (!p.onGround() || !tn.goalOK) {
		// off the walk grid, or heading somewhere it cannot reach: go over things
		if length(tn.goal[0]-p.pos[0], tn.goal[1]-p.pos[1]) > 3 {
			p.overland(cmd, tn.goal[0], tn.goal[1])
			tn.direct = true
		}
	}
	p.jink(tn)
	if !tn.direct {
		p.steer(cmd, tn.lg)
		p.unstick(cmd, tn.travelling && !tn.lg.still && !tn.lg.stayOnRoof)
	}
	p.aimAndFire(cmd, tn)
	td := -1.0
	if tn.tgt != nil {
		td = tn.tgt.d
	}
	cmd.Comment = p.summary(tn.st.tag(p.lob.ffa), tn.engaged, td)
}

// pickTarget chooses whom to shoot and totals up the pressure on us.
func (p *Pilot) pickTarget(tn *turn) {
	bestScore := -1.0
	for i := range tn.ths {
		t := &tn.ths[i]
		if t.engaged {
			tn.pressure += t.dps
			tn.engaged++
		}
		if !t.c.Listed {
			continue
		}
		s := 1 / (1 + t.d/60)
		if t.c.Visible {
			s *= 3
		}
		if t.engaged {
			s *= 1.6
		}
		if t.c.MaxHP > 0 {
			s *= 2 - t.c.HP/t.c.MaxHP
		}
		if t.c.ID == p.targetID {
			s *= 1.2
		}
		if s > bestScore {
			bestScore, tn.tgt = s, t
		}
	}
	p.targetID = -1
	if tn.tgt != nil {
		p.targetID = tn.tgt.c.ID
	}
}

// weighFight estimates whether we can out-trade everyone engaged with us.
func (p *Pilot) weighFight(tn *turn) {
	tn.overall = 10
	if tn.pressure <= 1 {
		return
	}
	mine := 1.0
	if tn.tgt != nil {
		mine = p.ourDPS(tn.tgt.d)
	}
	need := 0.0
	for i := range tn.ths {
		if tn.ths[i].engaged {
			need += math.Max(tn.ths[i].c.HP, 20) / math.Max(mine, 1)
		}
	}
	tn.overall = (p.hp / (tn.pressure * (1 - p.armor))) / math.Max(need, 0.1)
	if tn.engaged == 1 && tn.tgt != nil && tn.tgt.engaged {
		tn.overall = tn.tgt.adv // one opponent: the range-aware estimate is better
	}
}

// updateRetreat starts or ends a retreat.
func (p *Pilot) updateRetreat(tn *turn) {
	retreatHP, returnHP, swarmTTD, duelLeave := p.T.RetreatHP, p.T.ReturnHP, p.T.SwarmTTD, p.T.DuelLeave
	if tn.st.squad {
		retreatHP, returnHP, swarmTTD, duelLeave = p.T.SquadRetreatHP, p.T.SquadReturnHP, p.T.SquadSwarmTTD, p.T.SquadDuelLeave
	}
	if tn.st.squad && p.T.SquadNoRetreat {
		// against the house squad a retreat across open ground only gives away free hits: hold the fight
		p.retreating = false
		return
	}
	tgt := tn.tgt
	seenFoe := tgt != nil && tgt.engaged && tgt.c.Visible && tgt.c.Listed
	knownFoe := tgt != nil && tgt.engaged && tgt.c.Listed
	if p.retreating {
		winnable := tn.overall > math.Max(tn.st.disengage*1.25, 0.95)
		switch {
		case tn.hpFrac >= returnHP && (!tn.danger || winnable):
			p.retreating = false
		case !tn.danger && tn.hpFrac >= returnHP-0.1:
			p.retreating = false
		case winnable && tn.hpFrac > 0.3 && tn.engaged <= 1 && knownFoe:
			p.retreating = false // the odds turned
		case seenFoe && tgt.d < 45 && p.now-p.retreatT > 2 && tn.engaged <= 1 && tn.overall > 0.35:
			p.retreating = false // cornered: shooting back beats being shot in the back
			p.corneredT = p.now
		}
	} else if tn.danger && p.now-p.corneredT > 4 {
		ttd := p.hp / math.Max(p.hurtRecent/3, 1) // seconds left at the current rate
		ghosts := 0
		for i := range tn.ths {
			if tn.ths[i].ghost {
				ghosts++
			}
		}
		leave := false
		switch {
		case tn.engaged <= 1 && knownFoe:
			leave = tn.overall < duelLeave && tgt.d > 30 && ttd < 25
		case tn.engaged >= 2:
			leave = (ttd < swarmTTD && tn.hpFrac < 0.8) || (tn.hpFrac < retreatHP && ttd < 2*swarmTTD)
		default:
			leave = tn.hurting && ghosts > 0 && (ttd < 1.5*swarmTTD || tn.hpFrac < 0.6)
		}
		if leave {
			p.retreating, p.retreatT, p.coverCell = true, p.now, -1
		}
	}
	// never walk away from a kill one burst from done
	if tgt != nil && tgt.c.Listed && p.nearlyDead(tgt, 1.2, 40) && tn.hpFrac > 0.12 {
		p.retreating = false
	}
}

// chooseIntent decides between fighting, slipping into cover, ducking and leaving it alone.
func (p *Pilot) chooseIntent(tn *turn) {
	tgt := tn.tgt
	if tgt == nil || p.retreating {
		return
	}
	if p.patient(tn) && tn.engaged <= 1 && tgt.d > p.T.PatientRange && tn.hpFrac > 0.55 {
		tn.holdFire = true // building up: killing hunters only brings more of them
		return
	}
	switch {
	case tgt.engaged && tn.st.careful:
		p.carefulResponse(tn)
	case tgt.engaged:
		tn.fight = true
	case tgt.adv >= tn.st.engage && tgt.d < p.huntRange(tn.st) && tgt.c.Visible && tn.hpFrac > p.T.HuntHP &&
		(!tn.st.careful || p.laserEdge(tgt.c) || tgt.adv >= p.T.BigEdge):
		tn.fight = true // a hunt: only with a laser against none, or overwhelming odds
	case tn.st.duel && tn.hpFrac > 0.5:
		tn.fight = true
	}
	if tn.plink && p.pickErrand(true, tn.st) == nil {
		// nothing to farm: hide from it or have it out
		tn.plink = false
		if p.slipAway(tgt, tn.ths, false) {
			tn.slip = true
		} else {
			tn.fight = true
		}
	}
}

// carefulResponse handles a mech that is on us: cover first unless we hold a clear edge, and being
// looked at from range is not being attacked.
func (p *Pilot) carefulResponse(tn *turn) {
	tgt := tn.tgt
	c := tgt.c
	hostile := p.now-c.HitMeT < p.T.HostileMemory ||
		(c.Laser && c.Charging && p.now-c.FacedT < 0.4) ||
		(c.Laser && c.Visible && p.now-c.FacedT < 0.6) // a laser on us is a third of our health about to go
	provoked := hostile || tgt.d < p.T.ProvokeRange
	far := tgt.d >= p.T.FarRange && tgt.adv < p.T.FarEdge
	heavy := c.Laser || p.hurtRecent/3 > p.T.LightFireDPS || tn.hpFrac < 0.5 || tn.engaged >= 2
	// hysteresis: a borderline estimate must not flip us between the firing line and cover
	thr, big := p.T.FarEdge, p.T.BigEdge
	switch {
	case p.now-p.edgeOnT < p.T.EdgeMemory:
		thr, big = thr*0.75, big*0.75
	case p.now-p.slipOnT < p.T.EdgeMemory:
		thr, big = thr*1.3, big*1.3
	}
	edge := (p.laserEdge(c) && tgt.adv >= thr) || tgt.adv >= big
	if edge && provoked {
		p.edgeOnT = p.now
	}
	roofed := tn.onRoof && tn.roofPlan
	switch {
	case !provoked:
		tn.unprovoked = true
	case !edge && tgt.d >= p.T.CoverMinRange && !roofed && p.slipAway(tgt, tn.ths, true):
		tn.slip = true
	case roofed && !p.mechUpHere(tn.ths):
		tn.duck = true
	case !hostile && !edge && tgt.d > p.T.QuietRange && p.now-p.hurtT > 2.5:
		tn.unprovoked = true // it has not touched us: we do not start it either
	case far && heavy && p.slipAway(tgt, tn.ths, false):
		tn.slip = true
	case far && !heavy:
		tn.plink = true
	case far && p.slipAway(tgt, tn.ths, false):
		tn.slip = true
	default:
		tn.fight = true
	}
}

// slipAway decides whether to decline an exchange and go for cover (kept in p.slipCell). With
// always set the advantage does not matter (the caller already ruled out standing).
func (p *Pilot) slipAway(tgt *threat, ths []threat, always bool) bool {
	minR, maxAdv := math.Min(p.T.FarRange, p.T.CoverMinRange), p.T.FarEdge
	if p.now-p.slipOnT < 1 {
		minR, maxAdv = minR*0.85, maxAdv*1.15 // already going: do not flip back on the threshold
	}
	if always {
		maxAdv = math.Inf(1)
	}
	if tgt.d < minR || tgt.adv >= maxAdv || p.nearlyDead(tgt, 1.5, 60) {
		return false
	}
	if p.now-p.slipT > 0.5 {
		reach := p.T.CoverReach
		if tgt.c.Laser {
			reach = math.Max(reach, p.T.CoverReachLas)
		}
		// a search that comes up empty for a moment does not cancel a run already begun
		if c := p.nearestCover(ths, reach); c >= 0 || p.now-p.slipOnT > 1.5 {
			p.slipCell = c
		}
		p.slipT = p.now
	}
	if p.slipCell < 0 {
		return false
	}
	p.slipOnT = p.now
	return true
}

// updateQuiet decides whether it has been calm long enough to go about our business.
func (p *Pilot) updateQuiet(tn *turn) {
	q := len(tn.watched) == 0 && !tn.danger
	for i := range tn.ths {
		if q && p.now-tn.ths[i].c.SeenT < 6 && tn.ths[i].d < 180 {
			q = false
		}
	}
	if !q {
		p.unquietT = p.now
	}
	tn.quiet = q && p.now-p.unquietT >= p.T.QuietHold
}

// setupLegs fills in the parts of the movement request that do not depend on the mode.
func (p *Pilot) setupLegs(tn *turn) {
	if l := p.holding("laser"); l >= 0 && p.slots[l].charge > 0 {
		tn.lg.slow = true
	}
	// a laser charging at us: value positions that break its line
	for i := range tn.ths {
		c := tn.ths[i].c
		if !(c.Laser && c.Charging && c.Visible && p.now-c.FacedT < 0.25) {
			continue
		}
		e := eye{c.Pos[0], c.Pos[1], c.Pos[2] + 7*p.bodyScale(c.Cubes)}
		dmg := p.cfg.Weapon("laser").Get("damage", 315) * p.damageMul(c.Cubes) * 0.85
		prev := tn.lg.extra
		feet := p.pos[2]
		tn.lg.extra = func(x, y float64) float64 {
			cost := 0.0
			if prev != nil {
				cost = prev(x, y)
			}
			if p.seenFrom(e, x, y, feet, 0.9) {
				cost += dmg
			}
			return cost
		}
		tn.lg.look, tn.lg.mayRun = 12, true
	}
	// jetting up a wall in someone's sights is how mechs die
	p.holdClimb = len(tn.watched) > 0 || tn.hurting
	for i := range tn.ths {
		if !p.holdClimb && tn.ths[i].c.Listed && tn.ths[i].c.Visible && tn.ths[i].d < p.T.ClimbClear {
			p.holdClimb = true
		}
	}
	// and climbing down from a roof under someone's eyes is no better
	p.pinnedRoof = tn.st.careful && tn.onRoof && (len(tn.watched) > 0 || tn.hurting) && tn.zi.edgeIn > p.T.RoofLeaveCalm && !tn.zi.urgent
	if p.roof.stage == roofGoing && p.now-p.roof.active > 2.5 {
		p.roof.stage = roofIdle // an approach interrupted for a while starts over
	}
}

// walkTo sets a walking goal and returns the straight-line distance left.
func (p *Pilot) walkTo(tn *turn, gx, gy, w float64, run bool) float64 {
	dx, dy, d, ok := p.heading(gx, gy)
	tn.goalOK, tn.travelling, tn.goal = ok, true, [2]float64{gx, gy}
	tn.lg.dirX, tn.lg.dirY, tn.lg.weight, tn.lg.run = dx, dy, w, run
	if dx != 0 || dy != 0 {
		tn.heading, tn.hasHeading = math.Atan2(dy, dx), true
	}
	return d
}

// settle makes the legs stand still.
func (tn *turn) settle() {
	tn.lg.weight = 0
	tn.lg.still = true
}

// goCell walks to a grid cell and settles once there (or once hidden, near it).
func (p *Pilot) goCell(tn *turn, k int, w float64, run bool) bool {
	x, y := p.g.Pos(k)
	d := p.walkTo(tn, x, y, w, run)
	if d < 0.9 || (d < 3 && p.hiddenNow(tn.ths)) {
		tn.settle()
		return true
	}
	return false
}

// chooseMode picks what the legs do this decision.
func (p *Pilot) chooseMode(cmd *wire.Command, tn *turn) {
	tgt := tn.tgt
	// on our roof with eyes on us (or lately): the roof's edge is our cover
	duckCell := -1
	wantDuck := tn.duck || p.retreating || len(tn.watched) > 0 || tn.hurting
	if wantDuck {
		p.duckHoldT = p.now
	} else if p.now-p.duckHoldT < p.T.RoofDuckHold {
		wantDuck = true
	}
	if tn.onRoof && tn.roofPlan && wantDuck && !p.mechUpHere(tn.ths) {
		if p.now-p.duckT > 0.4 {
			p.duckCell, p.duckT = p.roofHide(p.roofUnder(), tn.ths), p.now
		}
		duckCell = p.duckCell
	} else {
		p.duckCell, p.duckT = -1, -100
	}
	if tn.duck && duckCell < 0 && !p.retreating {
		tn.fight = true // nowhere to duck up here: have it out from the roof
	}

	zi := &tn.zi
	switch {
	case zi.critical || (zi.urgent && (!tn.fight || tgt == nil || tgt.d > 60)) || (zi.urgent && zi.edgeIn < 5):
		p.mode = "zone"
		p.roof.stage = roofIdle
		if p.lootID >= 0 {
			p.bans[p.lootID] = p.now + 20 // where we were going is about to be outside
			p.lootID = -1
		}
		p.walkTo(tn, zi.goal[0], zi.goal[1], 3, zi.critical && p.energy > 15)
		tn.lg.zoneOwned = true
		if !zi.onFoot {
			p.mode = "zone-over"
			p.overland(cmd, zi.goal[0], zi.goal[1])
			tn.direct = true
		}

	case p.roof.stage == roofClimbing:
		p.mode = "climb" // half way up a wall is no place to change our mind
		p.climb(cmd)
		tn.direct = true

	case p.dropRun(tn.st, tn.hpFrac) != nil:
		// the supply drop first (full repair and cubes); the torso keeps fighting
		dr := p.dropRun(tn.st, tn.hpFrac)
		p.mode, p.lootID = "drop-run", dr.ID
		if d := flatDist(p.pos, dr.Pos); d > 4.5 {
			p.walkTo(tn, dr.Pos[0], dr.Pos[1], 2.6, p.energy > 30 && d > 25 && (tn.hurting || dr.LandsIn < d/p.walk))
			if !tn.goalOK {
				p.bans[dr.ID] = p.now + 20
			}
		} else {
			p.mode = "drop-hold"
			tn.settle()
		}

	case duckCell >= 0:
		p.mode = "roof-duck"
		x, y := p.g.Pos(duckCell)
		if p.walkTo(tn, x, y, 2.4, false) < 1.8 {
			tn.settle()
		}
		tn.lg.stayOnRoof = true
		tn.holdFire = tgt == nil || !tgt.engaged || tgt.d > p.T.ReturnFire

	case tn.slip:
		p.modeSlip(tn)

	case p.retreating:
		p.modeRetreat(tn)

	case tn.fight:
		p.modeFight(tn)

	case p.pest() != nil:
		// a drone shooting us blocks our regeneration, and it is worth cubes
		d := p.pest()
		p.mode = "pest"
		if p.futile(d.ID, d.HP, p.T.DroneGiveUp) {
			p.bans[d.ID] = p.now + 60
		}
		if d.Visible && flatDist(p.pos, d.Pos) < 120 {
			m := p.markOf(d)
			tn.item, tn.itemHP = &m, d.HP
			p.circle(&tn.lg, d.Pos, 35, 60, 1)
		} else {
			p.walkTo(tn, d.Pos[0], d.Pos[1], 1.5, false)
		}

	default:
		p.modeIdle(tn)
	}
}

func (p *Pilot) modeSlip(tn *turn) {
	p.mode = "slip"
	deep := p.deepCell >= 0 && p.now-p.deepT < 8 && p.now-p.hurtT > 0.45 && p.cellHidden(p.deepCell, tn.ths)
	if !deep {
		p.deepCell = -1
		x, y := p.g.Pos(p.slipCell)
		if d := p.walkTo(tn, x, y, 2.5, p.energy > 25 && tn.hurting); d < 0.9 || (d < 3 && p.hiddenNow(tn.ths)) {
			if p.now-p.deepTryT > 0.6 {
				p.deepTryT = p.now
				if c := p.deeperCover(tn.ths, 45, false); c >= 0 {
					p.deepCell, p.deepT = c, p.now
				}
			}
			if p.deepCell < 0 {
				tn.settle()
				p.mode = "ambush"
				return
			}
			deep = true
		}
	}
	if deep {
		x, y := p.g.Pos(p.deepCell)
		if d := p.walkTo(tn, x, y, 2.5, false); d < 1.5 || !tn.goalOK {
			tn.settle()
			p.mode = "ambush"
		}
	}
	// do not start it on the way
	if t := tn.tgt; t != nil && p.now-t.c.HitMeT > p.T.HostileMemory && p.now-p.hurtT > 2.5 &&
		!(t.c.Laser && t.c.Charging && p.now-t.c.FacedT < 0.6) && !p.laserEdge(t.c) && t.d > p.T.QuietRange {
		tn.holdFire = true
	}
}

func (p *Pilot) modeRetreat(tn *turn) {
	p.mode = "retreat"
	runAway := p.energy > 35 && p.nearestEye(tn.ths) < 60
	deep := tn.st.careful && p.deepCell >= 0 && p.now-p.deepT < 8 && p.now-p.hurtT >= 0.45 && p.cellHidden(p.deepCell, tn.ths)
	if !deep {
		p.deepCell = -1
		if p.now-p.coverT > 0.5 {
			p.coverCell, p.coverT = p.nearestCover(tn.ths, 90), p.now
		}
	}
	switch {
	case deep:
		p.mode = "retreat-deep"
		x, y := p.g.Pos(p.deepCell)
		if d := p.walkTo(tn, x, y, 2.5, runAway); d < 1.5 || !tn.goalOK {
			p.deepCell, p.coverT = -1, -100 // there: look again from here
		}
	case p.coverCell >= 0:
		x, y := p.g.Pos(p.coverCell)
		d := p.walkTo(tn, x, y, 2.5, p.energy > 20 && tn.hurting)
		if d < 0.9 || (d < 3 && p.hiddenNow(tn.ths)) {
			// the nearest hidden spot is the very edge of the shadow: go on to one that lasts
			if tn.st.careful && p.now-p.deepTryT > 0.6 {
				p.deepTryT = p.now
				if c := p.deeperCover(tn.ths, 75, true); c >= 0 {
					p.deepCell, p.deepT = c, p.now
				}
			}
			if p.deepCell >= 0 {
				p.mode = "retreat-deep"
				x, y = p.g.Pos(p.deepCell)
				p.walkTo(tn, x, y, 2.5, runAway)
			} else {
				tn.settle()
				p.mode = "heal"
			}
		}
	default:
		if from := p.fleeFrom(tn); from != nil {
			dx, dy := unit(p.pos[0]-from.c.Pos[0], p.pos[1]-from.c.Pos[1])
			p.walkTo(tn, p.pos[0]+dx*30, p.pos[1]+dy*30, 2, p.energy > 30)
		} else if tn.st.careful && tn.zi.outNext < -5 && p.now-p.droneHurtT > 4 && p.now-p.hurtT < 30 {
			tn.settle()
			p.mode = "heal"
		} else {
			p.walkTo(tn, tn.zi.goal[0], tn.zi.goal[1], 1.5, false)
		}
	}
	// a drone chipping at a hurt mech stops the health coming back: with no mech on us, shoot it
	if d := p.pest(); d != nil && d.Visible && flatDist(p.pos, d.Pos) < 110 {
		if t := tn.tgt; t == nil || !t.c.Visible || (p.now-t.c.HitMeT > 3 && t.d > 60) {
			m := p.markOf(d)
			tn.item, tn.itemHP, tn.pestShot = &m, d.HP, true
		}
	}
}

// nearestEye is the distance to the nearest recent threat (Inf: none).
func (p *Pilot) nearestEye(ths []threat) float64 {
	best := math.Inf(1)
	for _, e := range p.eyesOf(ths, 260, 6) {
		best = math.Min(best, length(e.x-p.pos[0], e.y-p.pos[1]))
	}
	return best
}

// fleeFrom is whom to back away from: our target, else whoever hurt us last.
func (p *Pilot) fleeFrom(tn *turn) *threat {
	if tn.tgt != nil {
		return tn.tgt
	}
	var best *threat
	for i := range tn.ths {
		if tn.ths[i].engaged && (best == nil || tn.ths[i].c.HitMeT > best.c.HitMeT) {
			best = &tn.ths[i]
		}
	}
	return best
}

func (p *Pilot) modeFight(tn *turn) {
	p.mode = "fight"
	tgt := tn.tgt
	switch {
	case !tn.onRoof && p.weaponNearby(32) != nil:
		w := p.weaponNearby(32)
		p.mode = "fight+arm" // a better weapon right here beats another second of shooting
		tn.lg.dirX, tn.lg.dirY, _, _ = p.heading(w.Pos[0], w.Pos[1])
		tn.lg.weight = 2.4
	case p.cubeNearby(tgt, tn.st, tn.hpFrac) != nil:
		c := p.cubeNearby(tgt, tn.st, tn.hpFrac)
		p.mode = "fight+cube"
		tn.lg.dirX, tn.lg.dirY, _, _ = p.heading(c.Pos[0], c.Pos[1])
		tn.lg.weight = 2.2
	case p.kiteFrom(tn) != nil:
		// several on us: open the range; their gunnery falls off faster than our laser
		near := p.kiteFrom(tn)
		p.mode = "kite"
		p.circle(&tn.lg, near.c.Pos, p.T.KiteMin, p.T.KiteMax, 2)
		tn.lg.run = near.d < 70 && p.energy > 45
	case !tgt.c.Visible:
		dx, dy, _, _ := p.heading(tgt.c.Pos[0], tgt.c.Pos[1])
		tn.lg.dirX, tn.lg.dirY, tn.lg.weight = dx, dy, 1.2
	default:
		near, far := tgt.near, tgt.far
		if far <= 0 {
			near, far = 30, 55
		}
		if tn.st.squad && p.T.SquadKite && p.holding("laser") >= 0 && tgt.c.Visible {
			near, far = p.T.SquadKiteMin, p.T.SquadKiteMax // their accuracy falls off with range, a laser's does not
		}
		p.circle(&tn.lg, tgt.c.Pos, near, far, 1.6)
		if p.holding("lightning") >= 0 && tgt.d > far+10 && p.energy > 55 {
			tn.lg.run = true
		}
	}
	tn.lg.stayOnRoof = tn.onRoof && tn.roofPlan
}

// kiteFrom returns the nearest attacker to back away from when two or more are on us and we hold a
// laser (nil: do not kite).
func (p *Pilot) kiteFrom(tn *turn) *threat {
	if tn.engaged < 2 || p.T.KiteMin <= 0 || (!tn.st.squad && p.holding("laser") < 0) {
		return nil
	}
	var near *threat
	for i := range tn.ths {
		t := &tn.ths[i]
		if t.engaged && !t.ghost && t.c.Listed && (near == nil || t.d < near.d) {
			near = t
		}
	}
	if near == nil || near.d > p.T.KiteMax+20 {
		return nil
	}
	return near
}

// modeIdle is looting, then exploring, then waiting (on a roof or in a sheltered spot).
func (p *Pilot) modeIdle(tn *turn) {
	e := p.pickErrand(tn.danger, tn.st)
	if e != nil && tn.onRoof && tn.roofPlan && e.kind != "drop" {
		// hidden on a roof: only a laser close by is worth coming down for
		if !(e.kind == "pickup" && p.holding("laser") < 0 && flatDist(p.pos, e.pos) < 90 && p.pickups[e.id] != nil && p.pickups[e.id].Kind == "laser") {
			e = nil
		}
	}
	if e != nil {
		p.doErrand(tn, e)
		return
	}
	p.lootID = -1
	p.mode = "hold"
	if tn.zi.final {
		z := &p.o.Zone
		if p.walkTo(tn, z.NextCenter[0], z.NextCenter[1], 1.5, false) < 2 {
			tn.settle()
		}
		return
	}
	if x, y, id, ok := p.seekTarget(tn.st, tn.hpFrac); ok {
		p.mode = "seek"
		p.walkTo(tn, x, y, 1.6, false)
		if !tn.goalOK {
			if id >= 0 {
				p.seekBans[id] = p.now + 30
			} else {
				p.banExploreGoal()
			}
		}
		return
	}
	if (p.T.Roam || tn.st.squad) && tn.hpFrac >= 0.7 && p.o.Self.Cubes < tn.st.wantCubes && (!tn.roofPlan || (!p.armed() && tn.quiet)) {
		if x, y, ok := p.exploreGoal(); ok {
			p.mode = "explore"
			p.walkTo(tn, x, y, 1.5, false)
			if !tn.goalOK {
				p.banExploreGoal()
			}
			return
		}
	}
	if tn.roofPlan {
		if x, y, settled, ok := p.roofStep(); ok {
			p.mode = "roof"
			if settled {
				tn.lg.still = true
			} else {
				p.walkTo(tn, x, y, 1.6, false)
			}
			tn.lg.stayOnRoof = tn.onRoof && p.roof.stage == roofUp
			return
		}
	} else {
		p.roof.stage = roofIdle
	}
	if p.holdCell < 0 || p.now-p.holdT > 2 {
		p.holdCell, p.holdT = p.holdSpot(), p.now
	}
	gx, gy := tn.zi.goal[0], tn.zi.goal[1]
	if p.holdCell >= 0 {
		gx, gy = p.g.Pos(p.holdCell)
	}
	if p.walkTo(tn, gx, gy, 1.4, false) < 2.5 {
		tn.settle()
	}
}

func (p *Pilot) doErrand(tn *turn, e *errand) {
	p.mode = "loot:" + e.kind
	p.lootID = e.id
	d := flatDist(p.pos, e.pos)
	switch e.kind {
	case "crate":
		it := p.crates[e.id]
		m := mark{pos: e.pos, radius: p.cfg.Crates.Get("radius", 1.4), centre: p.cfg.Crates.Get("height", 2.4) * 0.5, gunLead: 1}
		hp := math.Inf(1)
		if it != nil {
			hp = it.HP
		}
		inView := d < 70 && p.m.Clear(p.pos[0], p.pos[1], p.pos[2]+p.muzzle, e.pos[0], e.pos[1], e.pos[2]+m.centre)
		if inView {
			tn.item, tn.itemHP = &m, hp
		}
		if d > 9 || !inView {
			p.walkTo(tn, e.pos[0], e.pos[1], 1.5, false)
		} else {
			tn.lg.still = true
		}
		if d <= 12 && p.futile(e.id, hp, p.T.CrateGiveUp) {
			p.bans[e.id] = p.now + 120 // standing at it and cannot break it
			p.lootID = -1
		}
	case "npc":
		c := p.contacts[e.id]
		if c == nil {
			return
		}
		if c.Visible && d < 110 {
			m := p.markOf(c)
			tn.item, tn.itemHP = &m, c.HP
		}
		if d > 60 || !c.Visible {
			p.walkTo(tn, e.pos[0], e.pos[1], 1.5, false)
		} else {
			p.circle(&tn.lg, c.Pos, 50, 70, 1)
		}
		if d < 80 && p.futile(c.ID, c.HP, p.T.DroneGiveUp) {
			p.bans[e.id] = p.now + 90
			p.lootID = -1
		}
	case "drop":
		if d > 3 {
			p.walkTo(tn, e.pos[0], e.pos[1], 2, false)
		} else {
			tn.lg.still = true
		}
	default:
		// a laser on the ground is worth sprinting for
		run := false
		if it := p.pickups[e.id]; e.kind == "pickup" && it != nil && it.Kind == "laser" && p.holding("laser") < 0 {
			run = p.energy > p.T.LaserSprint && d > 25
		}
		p.walkTo(tn, e.pos[0], e.pos[1], 2, run)
	}
	if tn.travelling && !tn.goalOK {
		p.bans[e.id] = p.now + 40 // cannot get there from here
	}
}

// aimAndFire decides what the torso points at and whether to pull the triggers.
func (p *Pilot) aimAndFire(cmd *wire.Command, tn *turn) {
	tgt := tn.tgt
	unseen := false
	for i := range tn.ths {
		if tn.ths[i].ghost && p.now-tn.ths[i].c.HitMeT < 1.5 {
			unseen = true
		}
	}
	las := p.holding("laser")
	charging := las >= 0 && p.slots[las].charge > 0
	switch {
	case tn.pestShot && tn.item != nil:
		p.shoot(cmd, *tn.item, true, true, tn.itemHP, true)
	case unseen && (tgt == nil || !tgt.engaged || !tgt.c.Visible):
		// something we cannot see is hitting us: look that way
		cmd.Aim, cmd.AimSet = [2]float64{p.hurtBearing, 0}, true
		if charging {
			cmd.Fire[las] = true
		}
	case tn.plink && tn.item != nil:
		p.shoot(cmd, *tn.item, true, true, tn.itemHP, true)
	case tgt != nil && !tn.holdFire && !tn.unprovoked && (tn.fight || tgt.engaged || p.retreating):
		p.shoot(cmd, p.markOf(tgt.c), tgt.c.Visible, p.now-tgt.c.SightT < 0.8, tgt.c.HP, true)
	case tn.item != nil:
		p.shoot(cmd, *tn.item, true, true, tn.itemHP, true)
	case tgt != nil && (tgt.c.Visible || p.now-tgt.c.SeenT < 3):
		p.shoot(cmd, p.markOf(tgt.c), tgt.c.Visible, false, tgt.c.HP, false) // watch it, do not provoke
	default:
		p.lookAround(cmd, tn.heading, tn.hasHeading)
		if g := p.holding("gun"); g >= 0 {
			if sl := &p.slots[g]; sl.reload <= 0 && sl.ammo < sl.stats.Get("mag", 12)*0.67 {
				cmd.Reload = true // top up while nothing is happening
			}
		}
		// a charge with nobody listed: keep it a moment in case the target steps back out
		if charging && p.mechSeenWithin(1.5) {
			cmd.Fire[las] = true
		}
	}
}

// huntRange is how far we go after a favourable target that is not on us.
func (p *Pilot) huntRange(st stance) float64 {
	if !st.squad {
		return p.T.HuntRange
	}
	if p.holding("laser") >= 0 {
		return p.T.SquadHuntLaser
	}
	return p.T.SquadHunt
}
