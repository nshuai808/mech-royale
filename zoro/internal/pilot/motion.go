package pilot

import (
	"math"

	"zoro/internal/arena"
	"zoro/internal/wire"
)

// shell is an enemy projectile that may reach us.
type shell struct {
	arcing   bool // mortar
	pos, vel vec3
	until    float64 // seconds until it stops
	impact   vec3
	damage   float64
	blast    float64
}

// incoming lists the visible projectiles that could hit us in the next couple of seconds.
func (p *Pilot) incoming() []shell {
	var out []shell
	mortar := p.cfg.Weapon("mortar")
	grav := mortar.Get("gravity", 22)
	for _, pr := range p.o.Projectiles {
		speed := math.Sqrt(pr.Vel[0]*pr.Vel[0] + pr.Vel[1]*pr.Vel[1] + pr.Vel[2]*pr.Vel[2])
		if speed < 1 {
			continue
		}
		if pr.Kind == "mortar" {
			if s, ok := p.mortarLanding(pr.Pos, pr.Vel, grav, mortar); ok {
				out = append(out, s)
			}
			continue
		}
		rx, ry := p.pos[0]-pr.Pos[0], p.pos[1]-pr.Pos[1]
		if (rx*pr.Vel[0]+ry*pr.Vel[1])/speed < -3 {
			continue // going away
		}
		d := length(rx, ry)
		if d > 330 {
			continue
		}
		if math.Abs(rx*pr.Vel[1]-ry*pr.Vel[0])/math.Max(length(pr.Vel[0], pr.Vel[1]), 1) > 14+p.radius {
			continue // passes wide
		}
		reach := p.m.Cast(arena.Ray{X: pr.Pos[0], Y: pr.Pos[1], Z: pr.Pos[2], DX: pr.Vel[0] / speed, DY: pr.Vel[1] / speed, DZ: pr.Vel[2] / speed}, d+20)
		if reach < d-p.radius-3 {
			continue // a wall stops it
		}
		dmg := p.cfg.Weapon("gun").Get("damage", 45)
		if pr.Kind == "npc" {
			dmg = p.cfg.Npc.Get("damage", 25)
		}
		out = append(out, shell{pos: pr.Pos, vel: pr.Vel, until: reach / speed, damage: dmg})
	}
	return out
}

// mortarLanding integrates a shell's arc to where it lands.
func (p *Pilot) mortarLanding(pos, vel vec3, grav float64, st wire.Stats) (shell, bool) {
	const h = 0.05
	x, y, z := pos[0], pos[1], pos[2]
	vx, vy, vz := vel[0], vel[1], vel[2]
	for t := 0.0; t < 7; t += h {
		nx, ny, nz := x+vx*h, y+vy*h, z+vz*h-0.5*grav*h*h
		if !p.m.Clear(x, y, z, nx, ny, nz) {
			blast := st.Get("splash_radius", 7) * 1.3
			if spaceDist(vec3{x, y, z}, p.pos) > blast+p.radius+45 {
				return shell{}, false
			}
			return shell{arcing: true, pos: pos, vel: vel, until: t + h, impact: vec3{x, y, z}, damage: st.Get("splash", 160), blast: blast}, true
		}
		x, y, z = nx, ny, nz
		vz -= grav * h
	}
	return shell{}, false
}

// legs is what the decision asks of the movement planner.
type legs struct {
	dirX, dirY float64 // wanted heading (unit or zero)
	weight     float64 // value of one metre of progress along it
	run        bool    // sprinting is wanted
	slow       bool    // laser charging: half speed
	extra      func(x, y float64) float64
	still      bool // prefer standing when nothing threatens
	shells     []shell
	look       int  // evaluate positions this many ticks ahead
	mayRun     bool // sprinting is worth considering even with nothing incoming
	stayOnRoof bool
	zoneOwned  bool // the route already deals with the zone
}

type candidate struct {
	dx, dy float64
	run    bool
	score  float64
}

var compass = func() (d [16][2]float64) {
	for i := range d {
		a := float64(i) * math.Pi / 8
		d[i] = [2]float64{math.Cos(a), math.Sin(a)}
	}
	return
}()

// steer simulates a set of candidate moves against what is incoming and picks the best one.
func (p *Pilot) steer(cmd *wire.Command, lg legs) {
	grounded := p.o.Self.Grounded
	accel := p.mechStat("ground_accel", 58.5)
	if !grounded {
		accel = p.mechStat("air_accel", 12)
	}
	walk, run := p.walk, p.sprint
	if lg.slow {
		m := p.mechStat("charge_move_mult", 0.5)
		walk, run = walk*m, run*m
	}
	horizon := 8
	for _, s := range lg.shells {
		horizon = max(horizon, int(s.until/p.tick)+2)
	}
	horizon = min(horizon, 44)
	probe := 6
	if lg.look > probe {
		probe = lg.look
		horizon = max(horizon, probe)
	}

	c := p.cands[:0]
	c = append(c, candidate{})
	for _, d := range compass {
		c = append(c, candidate{dx: d[0], dy: d[1]})
	}
	if lg.dirX != 0 || lg.dirY != 0 {
		c = append(c, candidate{dx: lg.dirX, dy: lg.dirY})
	}
	if p.energy > 12 && grounded && (lg.run || lg.mayRun || len(lg.shells) > 0) {
		for i, n := 1, len(c); i < n; i++ {
			c = append(c, candidate{dx: c[i].dx, dy: c[i].dy, run: true})
		}
	}

	startCell := p.g.At(p.pos[0], p.pos[1])
	startGap := p.g.Gap[startCell]
	ground := p.onGround()
	minGap := float32(p.radius * 0.8)
	roofID := -1
	var roofOf []int32
	var depth []int16
	var startDepth int16
	if lg.stayOnRoof {
		roofID = p.roofUnder()
		_, roofOf = p.g.Roofs()
		depth = p.g.RoofDepth()
		startDepth = depth[startCell]
	}
	walled := func(cell int, x, y float64) bool {
		if cell == startCell {
			return false
		}
		if roofID >= 0 {
			return int(roofOf[cell]) != roofID || (depth[cell] < 2 && depth[cell] < startDepth)
		}
		// a cell is a wall only if it is worse than where we already stand (pressed to a wall, our own
		// cell fails the test too)
		return ground && (p.g.Blocked[cell] || !p.m.InBounds(x, y) || (p.g.Gap[cell] < minGap && p.g.Gap[cell] < startGap))
	}
	z := &p.o.Zone
	outNow := length(p.pos[0]-z.Center[0], p.pos[1]-z.Center[1]) - z.Radius

	best := -1
	for i := range c {
		cd := &c[i]
		speed := walk
		if cd.run {
			speed = run
		}
		x, y := p.pos[0], p.pos[1]
		vx, vy := p.vel[0], p.vel[1]
		px, py := x, y
		score := 0.0
		bumped := false
		for k := 1; k <= horizon; k++ {
			vx, vy = stepToward(vx, vy, cd.dx*speed, cd.dy*speed, accel*p.tick)
			nx, ny := x+vx*p.tick, y+vy*p.tick
			if walled(p.g.At(nx, ny), nx, ny) {
				bumped = true
				vx, vy, nx, ny = 0, 0, x, y
			}
			x, y = nx, ny
			if k == probe {
				px, py = x, y
			}
			score -= p.shellDamage(lg.shells, x, y, float64(k-1)*p.tick, float64(k)*p.tick, k == horizon)
		}
		if horizon < probe {
			px, py = x, y
		}
		score += ((px-p.pos[0])*lg.dirX + (py-p.pos[1])*lg.dirY) * lg.weight
		if bumped {
			score -= 3
		}
		// do not side-step out of the zone while we are in it (outside, the way in may start sideways)
		if z.Radius > 0 && !lg.zoneOwned {
			out := length(px-z.Center[0], py-z.Center[1]) - z.Radius
			if outNow < -0.5 && out > -4 && out > outNow {
				score -= (out - outNow) * 8
			}
		}
		if lg.extra != nil {
			score -= lg.extra(px, py)
		}
		if cd.run && !lg.run {
			score -= 1.5 // energy is not free
		}
		if cd.dx == 0 && cd.dy == 0 {
			if lg.still {
				score += 0.6
			}
		} else {
			score += 0.25 * (cd.dx*p.lastMove[0] + cd.dy*p.lastMove[1]) // less jitter
		}
		cd.score = score
		if best < 0 || score > c[best].score {
			best = i
		}
	}
	p.cands = c
	cmd.Move = [2]float64{c[best].dx, c[best].dy}
	cmd.Boost = c[best].run
}

// shellDamage is the damage we expect from the shells if we are at (x,y) between t0 and t1.
func (p *Pilot) shellDamage(shells []shell, x, y, t0, t1 float64, last bool) float64 {
	total := 0.0
	for i := range shells {
		s := &shells[i]
		if s.arcing {
			if (s.until > t0 && s.until <= t1+1e-9) || (last && s.until > t1) {
				dz := p.pos[2] + p.height*0.5 - s.impact[2]
				d := math.Sqrt((x-s.impact[0])*(x-s.impact[0]) + (y-s.impact[1])*(y-s.impact[1]) + dz*dz)
				if reach := s.blast + p.radius; d < reach {
					total += s.damage*(1-0.7*d/reach) + 40
				}
			}
			continue
		}
		if t0 >= s.until {
			continue
		}
		te := math.Min(t1, s.until)
		gap, f := segmentGap(x, y, s.pos[0]+s.vel[0]*t0, s.pos[1]+s.vel[1]*t0, s.pos[0]+s.vel[0]*te, s.pos[1]+s.vel[1]*te)
		if gap < p.radius+0.85 {
			if z := s.pos[2] + s.vel[2]*(t0+(te-t0)*f); z > p.pos[2]-0.6 && z < p.pos[2]+p.height+0.6 {
				total += s.damage
			}
		}
	}
	return total
}

// onGround reports whether our feet are at walk-grid level (not on a roof, not in the air).
func (p *Pilot) onGround() bool {
	k := p.g.At(p.pos[0], p.pos[1])
	return !p.g.Blocked[k] && p.pos[2]-float64(p.g.Floor[k]) < 3.5
}

// routeState is the walk-grid route we are following.
type routeState struct {
	cells []int32
	goal  [2]float64
	at    float64 // when it was searched
	idx   int
	set   bool
	short bool // the search failed or stopped short of the goal
}

// heading returns the direction to walk now to reach (gx,gy) and the straight-line distance left.
// ok is false when the goal cannot be reached on foot from here.
func (p *Pilot) heading(gx, gy float64) (dx, dy, dist float64, ok bool) {
	dist = length(gx-p.pos[0], gy-p.pos[1])
	straight := func() (float64, float64) { return unit(gx-p.pos[0], gy-p.pos[1]) }
	if dist < 1 {
		return 0, 0, dist, true
	}
	if !p.onGround() {
		dx, dy = straight() // on a roof or airborne: head for it and drop off
		return dx, dy, dist, true
	}
	rad, h := p.radius+0.15, p.height
	if dist < 14 && p.g.Straight(p.pos[0], p.pos[1], gx, gy, rad, h) {
		dx, dy = straight()
		return dx, dy, dist, true
	}
	r := &p.route
	elsewhere := !r.set || length(gx-r.goal[0], gy-r.goal[1]) > 5
	again := len(r.cells) == 0 || elsewhere || p.now-r.at > 1.6
	if !again && r.idx < len(r.cells) {
		if x, y := p.g.Pos(int(r.cells[r.idx])); length(x-p.pos[0], y-p.pos[1]) > 12 {
			again = true
		}
	}
	// searches are the expensive part: rate-limit them, a failed one more so
	gap := 0.35
	if r.short {
		gap = 1
	}
	if elsewhere {
		gap = 0.15
	}
	if again && r.set && p.now-r.at < gap {
		again = false
	}
	if elsewhere && !again {
		// no search for this goal yet: head straight at it (never report it unreachable on the
		// strength of a route that was for somewhere else)
		dx, dy = straight()
		return dx, dy, dist, true
	}
	if again {
		r.set, r.goal, r.at, r.idx = true, [2]float64{gx, gy}, p.now, 0
		r.cells = p.g.Route(p.pos[0], p.pos[1], gx, gy, rad, h, 9000, p.zoneCost())
		r.short = len(r.cells) == 0
		if !r.short {
			ex, ey := p.g.Pos(int(r.cells[len(r.cells)-1]))
			r.short = length(ex-gx, ey-gy) > 7
		}
	}
	if len(r.cells) == 0 {
		dx, dy = straight()
		return dx, dy, dist, false
	}
	if r.short {
		if ex, ey := p.g.Pos(int(r.cells[len(r.cells)-1])); length(ex-p.pos[0], ey-p.pos[1]) < 4 {
			dx, dy = straight()
			return dx, dy, dist, false // at the end of a partial route: no way on from here
		}
	}
	for r.idx < len(r.cells)-1 {
		if x, y := p.g.Pos(int(r.cells[r.idx])); length(x-p.pos[0], y-p.pos[1]) < 3.2 {
			r.idx++
		} else {
			break
		}
	}
	// aim at the farthest cell a little way ahead that we can walk to in a straight line
	tgt := r.idx
	for j := min(r.idx+14, len(r.cells)-1); j > r.idx; j -= 2 {
		if x, y := p.g.Pos(int(r.cells[j])); p.g.Straight(p.pos[0], p.pos[1], x, y, rad, h) {
			tgt = j
			break
		}
	}
	if tgt > r.idx+1 {
		r.idx = tgt - 1
	}
	tx, ty := p.g.Pos(int(r.cells[tgt]))
	if tgt == len(r.cells)-1 && length(gx-tx, gy-ty) < 4 {
		tx, ty = gx, gy
	}
	dx, dy = unit(tx-p.pos[0], ty-p.pos[1])
	return dx, dy, dist, true
}

// zoneCost makes routes prefer staying inside the current circle.
func (p *Pilot) zoneCost() func(k int) float32 {
	z := p.o.Zone
	return func(k int) float32 {
		x, y := p.g.Pos(k)
		if length(x-z.Center[0], y-z.Center[1]) > z.Radius-3 {
			return 6
		}
		return 0
	}
}

// stuckState notices pushing against something without getting anywhere.
type stuckState struct {
	checkT  float64
	checkAt vec3
	for_    float64
	until   float64
	dir     [2]float64
}

// unstick hops sideways after a second of walking into something.
func (p *Pilot) unstick(cmd *wire.Command, travelling bool) {
	s := &p.stuck
	if !travelling {
		*s = stuckState{checkT: p.now, checkAt: p.pos}
		return
	}
	if p.now-s.checkT >= 0.5 {
		if length(cmd.Move[0], cmd.Move[1]) > 0.3 && flatDist(p.pos, s.checkAt) < 1.2 {
			s.for_ += p.now - s.checkT
		} else {
			s.for_ = 0
		}
		s.checkT, s.checkAt = p.now, p.pos
	}
	if s.for_ >= 1 && p.now > s.until {
		a := p.rng.Float64() * 2 * math.Pi
		s.dir = [2]float64{math.Cos(a), math.Sin(a)}
		s.until = p.now + 0.7
		s.for_ = 0
		p.route.cells = nil
	}
	if p.now >= s.until {
		return
	}
	mx, my := cmd.Move[0]*0.4+s.dir[0], cmd.Move[1]*0.4+s.dir[1]
	if l := length(mx, my); l > 1 {
		mx, my = mx/l, my/l
	}
	cmd.Move = [2]float64{mx, my}
	if p.o.Self.Grounded {
		cmd.Jump = true
	} else if p.energy > 30 {
		cmd.Boost = true
	}
}

// circle strafes around a point while keeping the range inside [near, far].
func (p *Pilot) circle(lg *legs, at vec3, near, far, w float64) {
	if p.now >= p.strafeT {
		if p.rng.Float64() >= 0.25 {
			p.strafeDir = -p.strafeDir
		}
		p.strafeT = p.now + p.T.StrafeMin + p.rng.Float64()*(p.T.StrafeMax-p.T.StrafeMin)
	}
	rx, ry := unit(at[0]-p.pos[0], at[1]-p.pos[1])
	d := flatDist(p.pos, at)
	radial := 0.0
	if d > far {
		radial = clamp((d-far)/15, 0, 1)
	} else if d < near {
		radial = -clamp((near-d)/15, 0, 1)
	}
	side := 1 - 0.6*math.Abs(radial)
	lg.dirX, lg.dirY = unit(-ry*p.strafeDir*side+rx*radial, rx*p.strafeDir*side+ry*radial)
	lg.weight = w
}
