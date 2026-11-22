package grid

import "math"

// SurfaceRoute plans over the top surface of everything (ground, roofs, courtyards) for a mech that
// walks small steps, drops any height and jets up walls no taller than maxClimb. It covers what the
// walk grid cannot: leaving a roof, escaping a walled yard, reaching a circle that closes on top of
// something. feet is our current feet height; avoid (may be nil) rules cells out.
func (g *Grid) SurfaceRoute(sx, sy, feet, tx, ty, maxClimb, bodyR float64, budget int, avoid func(k int) bool) []int32 {
	tops := g.Tops()
	start, goal := g.At(sx, sy), g.At(tx, ty)
	if start == goal {
		return []int32{int32(start)}
	}
	s := &g.scr
	gen := s.begin()
	est := func(k int) float32 { return g.octile(k, goal, 1.1) }
	s.offer(gen, start, -1, 0, est(start))
	closest, closestH := start, est(start)
	reached := false
	for n := 0; len(s.heap) > 0; {
		k := int(s.heap.pop().cell)
		if s.done[k] == gen {
			continue
		}
		s.done[k] = gen
		if k == goal {
			reached = true
			break
		}
		if n++; n > budget {
			break
		}
		if e := est(k); e < closestH {
			closest, closestH = k, e
		}
		here := float64(tops[k])
		if k == start {
			here = feet
		}
		c, r := k%g.NX, k/g.NX
		for d := 0; d < 8; d++ {
			nc, nr := c+offC[d], r+offR[d]
			if !g.inside(nc, nr) {
				continue
			}
			nk := nr*g.NX + nc
			if s.done[nk] == gen {
				continue
			}
			if x, y := g.Pos(nk); !g.Map.InBounds(x, y) {
				continue
			}
			if avoid != nil && avoid(nk) {
				continue
			}
			step := g.Cell
			if d >= 4 {
				step *= math.Sqrt2
			}
			cost := step
			switch rise := float64(tops[nk]) - here; {
			case rise > maxClimb:
				continue
			case rise > 1.2:
				cost += 10 + 2.2*rise // jet climb: line up, rise, get over the lip
			case rise < -1.2:
				cost += 1.5
			}
			// ground pinched against a wall: fine to stand at (a climb starts there) but a gap of such
			// cells may be too narrow to pass, so it costs about as much as a low roof
			if !g.Blocked[nk] && float64(g.Gap[nk]) < bodyR-0.3 {
				cost += 14
			}
			nc2 := s.cost[k] + float32(cost)
			s.offer(gen, nk, k, nc2, nc2+est(nk))
		}
	}
	end := goal
	if !reached {
		if closest == start {
			return nil
		}
		end = closest
	}
	return s.trail(end)
}
