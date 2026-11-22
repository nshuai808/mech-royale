package pilot

import (
	"math"

	"zoro/internal/wire"
)

// lobShot aims a mortar shell at the ground under m: the low arc first, the high one when the low arc
// is blocked. The zero solution means no clear arc.
func (p *Pilot) lobShot(m mark, st wire.Stats) solution {
	v := st.Get("speed", 72)
	g := st.Get("gravity", 22)
	ox := p.pos[0] + p.vel[0]*shotLatency
	oy := p.pos[1] + p.vel[1]*shotLatency
	oz := p.pos[2] + p.height + 0.5*p.scale
	lo, hi := p.mechStat("min_pitch", -0.7), p.mechStat("max_pitch", 1.3)
	for _, high := range [...]bool{false, true} {
		flight, pitch := 0.6, 0.0
		var tx, ty, tz float64
		ok := true
		for pass := 0; pass < 5 && ok; pass++ {
			lead := shotLatency + flight*p.leadTrust(flight)
			tx, ty = m.pos[0]+m.vel[0]*lead, m.pos[1]+m.vel[1]*lead
			tz = p.m.Floor(tx, ty, m.pos[2]+3) + 0.3
			d := length(tx-ox, ty-oy)
			disc := v*v*v*v - g*(g*d*d+2*(tz-oz)*v*v)
			if d < 1 || disc < 0 {
				ok = false
				break
			}
			root := math.Sqrt(disc)
			if high {
				pitch = math.Atan2(v*v+root, g*d)
			} else {
				pitch = math.Atan2(v*v-root, g*d)
			}
			if math.Cos(pitch) < 0.05 {
				ok = false
				break
			}
			flight = d / (v * math.Cos(pitch))
		}
		if !ok || pitch < lo || pitch > hi || flight > st.Get("ttl", 7)-0.3 {
			continue
		}
		s := solution{ok: true, yaw: math.Atan2(ty-oy, tx-ox), pitch: pitch, dist: length(tx-ox, ty-oy), clear: true}
		// walk the arc: anything solid before the last few metres blocks it
		cy, sy := math.Cos(s.yaw), math.Sin(s.yaw)
		vh, vz := v*math.Cos(pitch), v*math.Sin(pitch)
		px, py, pz := ox+cy*3*math.Cos(pitch), oy+sy*3*math.Cos(pitch), oz+3*math.Sin(pitch)
		n := int(flight/0.12) + 2
		for i := 1; i <= n; i++ {
			t := flight * float64(i) / float64(n)
			if i == n {
				t = flight - 0.04
			}
			nx, ny, nz := ox+cy*vh*t, oy+sy*vh*t, oz+vz*t-0.5*g*t*t
			if !p.m.Clear(px, py, pz, nx, ny, nz) {
				s.clear = length(nx-tx, ny-ty) <= 3.5
				break
			}
			px, py, pz = nx, ny, nz
		}
		if s.clear {
			s.flight = flight
			return s
		}
	}
	return solution{}
}

// lobWorth reports whether a shell along s is likely to catch m (and not us).
func (p *Pilot) lobWorth(m mark, s solution, st wire.Stats) bool {
	splash := st.Get("splash_radius", 7)
	if s.dist < splash+p.radius+3 {
		return false
	}
	drift := length(m.vel[0], m.vel[1]) * s.flight * 0.5
	if !m.mech {
		drift *= 0.4
	}
	return drift < splash*0.75
}
