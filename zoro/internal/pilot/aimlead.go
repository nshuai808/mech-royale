package pilot

import "math"

// Gun lead, learned per opponent.
//
// Some bots keep walking under fire (lead them), others jitter on the spot (aim where they stand).
// Every observation we score one imaginary shot fired one flight time ago, both with and without the
// lead, against where the mech actually is now, and aim the way that has been missing by less.
// Until there is enough evidence, the lead is scaled by how straight its recent motion was.

const motionKeep = 40 // samples (four seconds at ten a second)

type motionSample struct {
	t, x, y, vx, vy float64
	facing          bool // its torso was turned on us
}

type motionLog struct {
	buf      [motionKeep]motionSample
	n, next  int
	shots    float64 // decayed count of imaginary shots
	missFlat float64 // decayed miss sum aiming where it stood
	missLead float64 // ... and aiming with the lead
}

// back returns the i-th most recent sample (0 = newest).
func (l *motionLog) back(i int) *motionSample {
	return &l.buf[(l.next+motionKeep-1-i)%motionKeep]
}

func (l *motionLog) add(s motionSample) {
	l.buf[l.next] = s
	l.next = (l.next + 1) % motionKeep
	if l.n < motionKeep {
		l.n++
	}
}

// near returns the stored sample within 0.07 s of t, closest first.
func (l *motionLog) near(t float64) *motionSample {
	var best *motionSample
	bd := 0.07
	for i := 0; i < l.n; i++ {
		s := l.back(i)
		if d := math.Abs(s.t - t); d < bd {
			best, bd = s, d
		}
		if s.t < t-0.1 {
			break
		}
	}
	return best
}

// straightness is 1 for a steady walk over the 1.2 s before t (or when we cannot tell), 0 for
// motion that goes nowhere.
func (l *motionLog) straightness(t float64) float64 {
	var newest, oldest *motionSample
	n, speed := 0, 0.0
	for i := 0; i < l.n; i++ {
		s := l.back(i)
		if s.t > t+0.01 {
			continue
		}
		if s.t < t-1.25 {
			break
		}
		if newest == nil {
			newest = s
		}
		oldest = s
		speed += length(s.vx, s.vy)
		n++
	}
	if n < 8 || newest.t-oldest.t < 0.7 {
		return 1
	}
	net := length(newest.x-oldest.x, newest.y-oldest.y) / (newest.t - oldest.t)
	return clamp((net/math.Max(speed/float64(n), 0.5)-0.2)/0.5, 0, 1)
}

const bulletSpeed = 252.0
const shotLatency = 0.075 // our command lands a tick or two after the observation

// recordMotion stores the contact's current state and scores one imaginary shot.
func (p *Pilot) recordMotion(c *Contact, facing bool) {
	l := &c.motion
	if l.n > 0 {
		prev := l.back(0)
		if p.now <= prev.t {
			return
		}
		if p.now-prev.t > 0.25 {
			l.n, l.next = 0, 0 // a gap: the old samples do not connect
		}
	}
	l.add(motionSample{p.now, c.Pos[0], c.Pos[1], c.Vel[0], c.Vel[1], facing})
	d := flatDist(c.Pos, p.pos)
	if d < 55 || d > 240 {
		return
	}
	flight := math.Max(0, d-3) / bulletSpeed
	then := l.near(p.now - shotLatency - flight)
	if then == nil || !then.facing {
		return // only how it moves while fighting us counts
	}
	// sideways miss at the target of an aim point chosen back then
	miss := func(ax, ay float64) float64 {
		ux, uy := unit(ax-p.pos[0], ay-p.pos[1])
		return math.Min(math.Abs(-(c.Pos[0]-p.pos[0])*uy+(c.Pos[1]-p.pos[1])*ux), 6)
	}
	lead := (shotLatency + flight*p.leadTrust(flight)) * l.straightness(then.t)
	const decay = 0.997
	l.shots = l.shots*decay + 1
	l.missFlat = l.missFlat*decay + miss(then.x, then.y)
	l.missLead = l.missLead*decay + miss(then.x+then.vx*lead, then.y+then.vy*lead)
}

// gunLead returns the share of the velocity lead to use when shooting the gun at c.
func (p *Pilot) gunLead(c *Contact) float64 {
	if c.Drone {
		return 1
	}
	l := &c.motion
	if l.shots >= p.T.LeadEvidence {
		margin := 0.2 * l.shots
		switch {
		case l.missFlat < l.missLead-margin:
			return 0
		case l.missLead < l.missFlat-margin:
			return 1
		}
	}
	return l.straightness(p.now)
}

// leadTrust is how much of a target's velocity to believe over a flight of tf seconds.
func (p *Pilot) leadTrust(tf float64) float64 {
	if tf <= 0.3 {
		return 1
	}
	return math.Max(p.T.LeadFloor, 1-(tf-0.3)/0.5*(1-p.T.LeadFloor))
}
