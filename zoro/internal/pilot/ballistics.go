package pilot

import (
	"math"

	"zoro/internal/arena"
	"zoro/internal/wire"
)

// mark is something to shoot at.
type mark struct {
	pos, vel vec3
	radius   float64
	centre   float64 // aim-point height above pos
	mech     bool
	gunLead  float64 // share of the velocity lead for bullets (1 = full)
}

func (p *Pilot) markOf(c *Contact) mark {
	if c.Drone {
		return mark{pos: c.Pos, vel: c.Vel, radius: p.cfg.Npc.Get("radius", 1.8), centre: p.centreHeight(c), gunLead: 1}
	}
	sc := p.bodyScale(c.Cubes)
	return mark{pos: c.Pos, vel: c.Vel, radius: p.mechStat("radius", 2.5) * sc, centre: 4.5 * sc, mech: true, gunLead: p.gunLead(c)}
}

// solution is an aim for one weapon.
type solution struct {
	ok         bool
	yaw, pitch float64
	dist       float64
	flight     float64 // seconds (lobbed shells only)
	clear      bool    // no solid between muzzle and target
}

// solve aims a straight shot of the given speed (0 = instant) at m, from our muzzle, with the
// fraction lead of the target's velocity.
func (p *Pilot) solve(m mark, speed, lead float64) solution {
	ox := p.pos[0] + p.vel[0]*shotLatency
	oy := p.pos[1] + p.vel[1]*shotLatency
	oz := p.pos[2] + p.muzzle
	if !p.o.Self.Grounded {
		oz += p.vel[2] * shotLatency
	}
	var tx, ty, tz, flight float64
	for pass := 0; pass < 4; pass++ {
		horiz := (shotLatency + flight*p.leadTrust(flight)) * lead
		tx = m.pos[0] + m.vel[0]*horiz
		ty = m.pos[1] + m.vel[1]*horiz
		tz = m.pos[2] + m.centre + clamp(m.vel[2], -15, 12)*(shotLatency+flight)*0.6
		if speed <= 0 {
			break
		}
		flight = math.Max(0, math.Sqrt((tx-ox)*(tx-ox)+(ty-oy)*(ty-oy)+(tz-oz)*(tz-oz))-3) / speed
	}
	h := length(tx-ox, ty-oy)
	s := solution{ok: true, yaw: math.Atan2(ty-oy, tx-ox), pitch: math.Atan2(tz-oz, h)}
	s.dist = math.Sqrt(h*h + (tz-oz)*(tz-oz))
	reach := s.dist - m.radius*0.9
	s.clear = reach < 0.5 || s.dist <= 1e-3 ||
		p.m.Cast(arena.Ray{X: ox, Y: oy, Z: oz, DX: (tx - ox) / s.dist, DY: (ty - oy) / s.dist, DZ: (tz - oz) / s.dist}, reach) >= reach-1e-6
	return s
}

// solveBest aims at the body, falling back to the head when only the head shows over cover.
func (p *Pilot) solveBest(m mark, speed, lead float64) (solution, bool) {
	s := p.solve(m, speed, lead)
	if s.clear || !m.mech {
		return s, false
	}
	head := m
	head.centre *= 1.82
	head.radius *= 0.8
	if alt := p.solve(head, speed, lead); alt.clear {
		return alt, true
	}
	return s, false
}

// slewErr is how far the torso will still be off a solution after one tick of turning.
func (p *Pilot) slewErr(s solution) (float64, float64) {
	ey := math.Abs(wrap(s.yaw, p.aim[0])) - p.turn*p.tick*0.9
	ep := math.Abs(s.pitch-p.aim[1]) - p.pitchRate*p.tick*0.9
	return math.Max(ey, 0), math.Max(ep, 0)
}

// laserHit is the damage a laser does at the given charge.
func (p *Pilot) laserHit(st wire.Stats, charge float64) float64 {
	full := st.Get("charge", 0.75)
	f := 1.0
	if full > 0 {
		f = clamp(charge/full, 0, 1)
	}
	floor := st.Get("min_frac", 0.35)
	return st.Get("damage", 315) * (floor + (1-floor)*f) * p.damageMul(p.o.Self.Cubes)
}

// shoot points the torso at m and works the triggers. With fire false it only aims (but lets go a
// laser charge already under way). seen: a clear line now; recent: lost it only a moment ago.
func (p *Pilot) shoot(cmd *wire.Command, m mark, seen, recent bool, hpLeft float64, fire bool) {
	gun, las, arc := p.holding("gun"), p.holding("laser"), p.holding("lightning")
	var gunS, beamS solution
	pitchTol := m.centre * 0.8
	if gun >= 0 {
		var head bool
		gunS, head = p.solveBest(m, p.slots[gun].stats.Get("speed", bulletSpeed), m.gunLead)
		if head {
			pitchTol = 0.7
		}
	}
	if las >= 0 || arc >= 0 {
		var head bool
		beamS, head = p.solveBest(m, 0, 1)
		if head {
			pitchTol = 0.7
		}
	}
	// the torso follows the gun, unless a laser charge is about to be let go
	track, trackGun := beamS, false
	if gun >= 0 {
		track, trackGun = gunS, true
	}
	laserReady := false
	if las >= 0 {
		sl := &p.slots[las]
		laserReady = sl.charge > 0 && (sl.charge >= sl.stats.Get("charge", 0.75)-0.16 || p.laserHit(sl.stats, sl.charge+0.1) >= hpLeft)
		if laserReady || gun < 0 {
			track, trackGun = beamS, false
		}
	}
	// a shell wants its own pitched aim: take it when it is likely to land and the laser is not about
	// to fire (or the gun cannot shoot anyway)
	var lobS solution
	lobbing := false
	if mor := p.holding("mortar"); mor >= 0 && fire {
		sl := &p.slots[mor]
		if lobS = p.lobShot(m, sl.stats); lobS.ok && sl.cooldown <= 0.15 && !laserReady {
			gunIdle := gun < 0 || p.slots[gun].reload > 0 || p.slots[gun].ammo == 0 || !gunS.clear || gunS.dist > p.T.GunMaxRange
			if p.lobWorth(m, lobS, sl.stats) || (gunIdle && lobS.dist > 25) {
				track, trackGun, lobbing = lobS, false, true
			}
		}
	}
	if !track.ok {
		return
	}
	cmd.Aim = [2]float64{track.yaw, clamp(track.pitch, p.mechStat("min_pitch", -0.7), p.mechStat("max_pitch", 1.3))}
	cmd.AimSet = true
	if !fire && !(las >= 0 && p.slots[las].charge > 0) {
		return
	}
	if gun >= 0 && fire {
		p.fireGun(cmd, gun, m, gunS, trackGun, seen, pitchTol)
	}
	if las >= 0 {
		p.fireLaser(cmd, las, m, beamS, seen, recent, hpLeft, pitchTol, fire)
	}
	if lobbing {
		if mor := p.holding("mortar"); p.slots[mor].cooldown <= 0.05 {
			if ey, ep := p.slewErr(lobS); ey < 0.03 && ep < 0.02 {
				cmd.Fire[mor] = true
			}
		}
	}
	if arc >= 0 && fire {
		sl := &p.slots[arc]
		d := spaceDist(vec3{p.pos[0], p.pos[1], p.pos[2] + p.muzzle}, vec3{m.pos[0], m.pos[1], m.pos[2] + m.centre})
		closing := length(m.vel[0]-p.vel[0], m.vel[1]-p.vel[1]) * 0.05
		if seen && beamS.clear && d < sl.stats.Get("range", 45)-1-closing && p.energy >= sl.stats.Get("energy", 3) {
			cone := sl.stats.Get("cone_deg", 30) * math.Pi / 180
			if math.Abs(wrap(beamS.yaw, p.aim[0]))-p.turn*p.tick*0.9 < cone*0.4 {
				cmd.Fire[arc] = true
			}
		}
	}
}

func (p *Pilot) fireGun(cmd *wire.Command, i int, m mark, s solution, tracked, seen bool, pitchTol float64) {
	sl := &p.slots[i]
	if sl.ammo <= 0 && sl.reload <= 0 {
		cmd.Reload = true
	}
	limit := math.Min(sl.stats.Get("range", 230)-5, p.T.GunMaxRange)
	if !m.mech {
		limit = math.Min(limit, 120)
	}
	if !seen || !s.clear || sl.ammo <= 0 || sl.reload > 0 || s.dist >= limit {
		return
	}
	ey, ep := p.slewErr(s)
	if !tracked {
		// the torso is chasing another solution: no credit for this tick's turn
		ey, ep = math.Abs(wrap(s.yaw, p.aim[0])), math.Abs(s.pitch-p.aim[1])
	}
	r := math.Max(s.dist, 1)
	if ey < math.Atan2(m.radius*0.8, r) && ep < math.Atan2(pitchTol, r) {
		cmd.Fire[i] = true
	}
}

// fireLaser holds a charge until it is full (or enough to kill) and lined up, then lets go; it starts
// a new charge only at a mech in reach (a charge cannot be cancelled and halves our speed).
func (p *Pilot) fireLaser(cmd *wire.Command, i int, m mark, s solution, seen, recent bool, hpLeft, pitchTol float64, fire bool) {
	sl := &p.slots[i]
	inRange := s.dist < sl.stats.Get("range", 280)-4
	if sl.charge > 0 {
		full := sl.charge >= sl.stats.Get("charge", 0.75)-1e-3
		lethal := sl.charge >= sl.stats.Get("min_charge", 0.15) && p.laserHit(sl.stats, sl.charge) >= hpLeft
		hold := true
		if (full || lethal) && seen && s.clear && inRange {
			ey, ep := p.slewErr(s)
			r := math.Max(s.dist, 1)
			if ey < math.Atan2(m.radius*0.75, r) && ep < math.Atan2(pitchTol*0.9, r) {
				hold = false
			}
		}
		cmd.Fire[i] = hold
		return
	}
	if fire && (m.mech || p.practice()) && sl.cooldown <= 0.12 && inRange && (seen || recent) {
		cmd.Fire[i] = true
	}
}

// lookAround sweeps the torso while nothing needs shooting.
func (p *Pilot) lookAround(cmd *wire.Command, heading float64, moving bool) {
	yaw := p.aim[0]
	switch {
	case p.now < 1.75:
		yaw += 0.39 // a quick full turn at the start: who can see us?
	case p.now-p.hurtT < 2.5 || p.now-p.droneHurtT < 2.5:
		yaw = p.hurtBearing
	case p.now-p.soundT < 1.5:
		yaw = p.soundBear
	case p.T.SquadLook && p.practice() && p.squadBearingOK():
		// hunters walk straight at us from where the squad was last seen: keep the 120-degree cone on them
		p.scan += p.period
		yaw = p.squadBear + 0.7*math.Sin(p.scan*2.2)
	case moving:
		p.scan += p.period
		yaw = heading + 1.9*math.Sin(p.scan*1.3)
	default:
		p.scan += p.period
		yaw += 0.35
	}
	cmd.Aim, cmd.AimSet = [2]float64{yaw, 0}, true
}

// squadBearingOK points squadBear at the nearest squad member seen in the last 20 s (practice only).
func (p *Pilot) squadBearingOK() bool {
	best, bd := -1.0, math.Inf(1)
	for _, c := range p.contacts {
		if c.Drone || p.now-c.SeenT > 20 || c.HP <= 0 {
			continue
		}
		d := math.Hypot(c.Pos[0]-p.pos[0], c.Pos[1]-p.pos[1])
		if d < bd && d > 1 {
			bd, best = d, math.Atan2(c.Pos[1]-p.pos[1], c.Pos[0]-p.pos[0])
		}
	}
	if best < -0.5 && math.IsInf(bd, 1) {
		return false
	}
	p.squadBear = best
	return !math.IsInf(bd, 1)
}
