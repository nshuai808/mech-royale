package pilot

import (
	"math"

	"zoro/internal/wire"
)

// jetRise is about how fast the jets lift a mech (m/s).
const jetRise = 8.9

func (p *Pilot) jetDrain() float64 {
	d := p.o.Self.Stats.Get("jet_drain", p.mechStat("jet_drain", 15))
	if d <= 0 {
		d = 15
	}
	return d
}

// climbLimit is the tallest wall a full charge gets us over, with a reserve for the lip.
func (p *Pilot) climbLimit() float64 {
	return (p.o.Self.MaxEnergy - 28) / p.jetDrain() * jetRise
}

// surfState is a route over the top surface (for travel the walk grid cannot do).
type surfState struct {
	cells   []int32
	goal    [2]float64
	at      float64
	idx     int
	bans    map[int]float64
	watchT  float64
	watchAt vec3
	pushing bool
}

// overland goes to (gx,gy) over whatever is in the way: walking, dropping off ledges, jetting up
// walls. It writes the command directly.
func (p *Pilot) overland(cmd *wire.Command, gx, gy float64) {
	s := &p.surf
	if s.bans == nil {
		s.bans = map[int]float64{}
	}
	tops := p.g.Tops()
	feet := p.pos[2]
	grounded := p.o.Self.Grounded
	// pushing along the route without moving: something the surface map does not show is in the way
	if p.now-s.watchT >= 1.5 {
		if s.pushing && spaceDist(p.pos, s.watchAt) < 1.2 && len(s.cells) >= 2 {
			for j := s.idx + 1; j < len(s.cells) && j <= s.idx+3; j++ {
				s.bans[int(s.cells[j])] = p.now + 25
			}
			s.cells, s.at = nil, -100
		}
		s.watchT, s.watchAt, s.pushing = p.now, p.pos, false
	}
	again := len(s.cells) < 2 || length(gx-s.goal[0], gy-s.goal[1]) > 6 || p.now-s.at > 1.2
	if !again {
		if x, y := p.g.Pos(int(s.cells[s.idx])); length(x-p.pos[0], y-p.pos[1]) > 7 {
			again = true
		}
	}
	if again && p.now-s.at >= 0.3 {
		avoid := func(k int) bool { u, ok := s.bans[k]; return ok && p.now < u }
		s.cells = p.g.SurfaceRoute(p.pos[0], p.pos[1], feet, gx, gy, p.climbLimit(), p.radius, 14000, avoid)
		s.goal, s.at, s.idx = [2]float64{gx, gy}, p.now, 0
	}
	dx, dy := unit(gx-p.pos[0], gy-p.pos[1])
	need := feet
	if len(s.cells) >= 2 {
		best, bd := s.idx, math.Inf(1)
		for j := s.idx; j < len(s.cells) && j < s.idx+8; j++ {
			x, y := p.g.Pos(int(s.cells[j]))
			if d := length(x-p.pos[0], y-p.pos[1]); d < bd {
				best, bd = j, d
			}
		}
		s.idx = best
		next := min(best+1, len(s.cells)-1)
		tgt := next
		// look further ahead while the way stays level
		for tgt < len(s.cells)-1 && tgt < best+3 &&
			math.Abs(float64(tops[s.cells[tgt+1]]-tops[s.cells[next]])) < 0.6 && float64(tops[s.cells[next]]) <= feet+1 {
			tgt++
		}
		if int(s.cells[tgt]) != p.g.At(p.pos[0], p.pos[1]) {
			tx, ty := p.g.Pos(int(s.cells[tgt]))
			dx, dy = unit(tx-p.pos[0], ty-p.pos[1])
		}
		need = math.Max(float64(tops[s.cells[next]]), float64(tops[s.cells[tgt]]))
	} else {
		for _, ahead := range [...]float64{p.radius + 1, p.radius + 3.5} {
			need = math.Max(need, p.m.Floor(p.pos[0]+dx*ahead, p.pos[1]+dy*ahead, math.Inf(1)))
		}
	}
	cmd.Move = [2]float64{dx, dy}
	rise := need - feet
	switch {
	case rise < 1:
		cmd.Boost = grounded && !p.o.Self.InZone && p.energy > 70
		s.pushing = true
	case grounded:
		// a wall: jump once we can clear it, otherwise wait for the energy
		if p.energy >= math.Min(rise/jetRise*p.jetDrain()+16, p.o.Self.MaxEnergy-3) {
			cmd.Jump = true
			s.pushing = true
		} else {
			cmd.Move = [2]float64{}
		}
	default:
		cmd.Boost = feet < need+0.8 && p.energy > 1
	}
}
