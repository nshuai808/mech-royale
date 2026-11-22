package grid

import "math"

// scratch is the reusable state of one search. Generation counters avoid clearing the arrays.
type scratch struct {
	cost   []float32
	from   []int32
	opened []uint32
	done   []uint32
	gen    uint32
	heap   minHeap
}

func newScratch(n int) scratch {
	return scratch{cost: make([]float32, n), from: make([]int32, n), opened: make([]uint32, n), done: make([]uint32, n)}
}

func (s *scratch) begin() uint32 {
	s.gen++
	if s.gen == 0 {
		clear(s.opened)
		clear(s.done)
		s.gen = 1
	}
	s.heap = s.heap[:0]
	return s.gen
}

// offer records cost c for cell k reached from p if it improves on what is known.
func (s *scratch) offer(gen uint32, k, p int, c, prio float32) {
	if s.opened[k] == gen && c >= s.cost[k] {
		return
	}
	s.opened[k] = gen
	s.cost[k] = c
	s.from[k] = int32(p)
	s.heap.push(node{int32(k), prio})
}

// trail walks the parent links back from k and returns the cells in start-to-k order.
func (s *scratch) trail(k int) []int32 {
	var out []int32
	for c := int32(k); c >= 0 && len(out) <= 100000; c = s.from[c] {
		out = append(out, c)
	}
	for i, j := 0, len(out)-1; i < j; i, j = i+1, j-1 {
		out[i], out[j] = out[j], out[i]
	}
	return out
}

type node struct {
	cell int32
	prio float32
}

// minHeap is a binary heap of nodes ordered by prio (hand-rolled: no interface boxing).
type minHeap []node

func (h *minHeap) push(n node) {
	*h = append(*h, n)
	a := *h
	for i := len(a) - 1; i > 0; {
		p := (i - 1) / 2
		if a[p].prio <= a[i].prio {
			break
		}
		a[p], a[i] = a[i], a[p]
		i = p
	}
}

func (h *minHeap) pop() node {
	a := *h
	top := a[0]
	last := len(a) - 1
	a[0] = a[last]
	a = a[:last]
	for i := 0; ; {
		l := 2*i + 1
		if l >= last {
			break
		}
		m := l
		if r := l + 1; r < last && a[r].prio < a[l].prio {
			m = r
		}
		if a[i].prio <= a[m].prio {
			break
		}
		a[i], a[m] = a[m], a[i]
		i = m
	}
	*h = a
	return top
}

// octile is the 8-connected distance in cells between two cells, times scale.
func (g *Grid) octile(a, b int, scale float64) float32 {
	dc := math.Abs(float64(a%g.NX - b%g.NX))
	dr := math.Abs(float64(a/g.NX - b/g.NX))
	lo, hi := math.Min(dc, dr), math.Max(dc, dr)
	return float32((hi + 0.4142*lo) * g.Cell * scale)
}

// Closest returns the walkable cell nearest to (x,y) within maxRing rings of cells, or -1.
func (g *Grid) Closest(x, y, rad, h float64, maxRing int) int {
	c0, r0 := g.ColRow(x, y)
	best, bestD := -1, math.Inf(1)
	for ring := 0; ring <= maxRing; ring++ {
		for dr := -ring; dr <= ring; dr++ {
			for dc := -ring; dc <= ring; dc++ {
				if max(abs(dc), abs(dr)) != ring {
					continue
				}
				c, r := c0+dc, r0+dr
				if !g.inside(c, r) {
					continue
				}
				k := r*g.NX + c
				if !g.Fits(k, rad, h) {
					continue
				}
				px, py := g.Pos(k)
				if d := (px-x)*(px-x) + (py-y)*(py-y); d < bestD {
					best, bestD = k, d
				}
			}
		}
		if best >= 0 {
			return best
		}
	}
	return best
}

func abs(v int) int {
	if v < 0 {
		return -v
	}
	return v
}

// Extra adds a per-cell cost on top of distance (nil means none).
type Extra func(k int) float32

// walkEdges calls fn for every walkable 8-neighbour of k with its step length.
func (g *Grid) walkEdges(k int, rad, h float64, fn func(nk int, dist float64)) {
	c, r := k%g.NX, k/g.NX
	for d := 0; d < 8; d++ {
		nc, nr := c+offC[d], r+offR[d]
		if !g.inside(nc, nr) {
			continue
		}
		nk := nr*g.NX + nc
		if !g.Fits(nk, rad, h) {
			continue
		}
		dist := g.Cell
		if d >= 4 {
			// diagonal: both side cells must be open (no cutting corners)
			if !g.Fits(r*g.NX+nc, rad, h) || !g.Fits(nr*g.NX+c, rad, h) {
				continue
			}
			dist *= math.Sqrt2
		}
		if g.stepOK(k, nk, dist) {
			fn(nk, dist)
		}
	}
}

// Route runs A* from (sx,sy) to (tx,ty) for a body of radius rad and height h. It returns the cells
// from start to goal, a partial route towards the goal when the budget runs out or the goal cannot
// be reached, or nil.
func (g *Grid) Route(sx, sy, tx, ty, rad, h float64, budget int, extra Extra) []int32 {
	start := g.Closest(sx, sy, rad, h, 6)
	goal := g.Closest(tx, ty, rad, h, 10)
	if start < 0 || goal < 0 {
		return nil
	}
	if start == goal {
		return []int32{int32(start)}
	}
	s := &g.scr
	gen := s.begin()
	// a slightly inflated heuristic: far fewer expansions for routes a few percent longer
	est := func(k int) float32 { return g.octile(k, goal, 1.15) }
	s.offer(gen, start, -1, 0, est(start))
	closest, closestH := start, est(start)
	wantGap := float32(rad + 2)
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
		base := s.cost[k]
		g.walkEdges(k, rad, h, func(nk int, dist float64) {
			if s.done[nk] == gen {
				return
			}
			c := float32(dist)
			if g.Gap[nk] < wantGap {
				c += (wantGap - g.Gap[nk]) * 0.6 // keep off the walls
			}
			if extra != nil {
				c += extra(nk)
			}
			s.offer(gen, nk, k, base+c, base+c+est(nk))
		})
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

// Spread runs Dijkstra from (sx,sy) out to maxCost metres, calling visit on every settled cell in
// order of cost. visit returns false to stop.
func (g *Grid) Spread(sx, sy, rad, h, maxCost float64, extra Extra, visit func(k int, cost float32) bool) {
	start := g.Closest(sx, sy, rad, h, 6)
	if start < 0 {
		return
	}
	s := &g.scr
	gen := s.begin()
	s.offer(gen, start, -1, 0, 0)
	for len(s.heap) > 0 {
		k := int(s.heap.pop().cell)
		if s.done[k] == gen {
			continue
		}
		s.done[k] = gen
		if !visit(k, s.cost[k]) {
			return
		}
		base := s.cost[k]
		g.walkEdges(k, rad, h, func(nk int, dist float64) {
			if s.done[nk] == gen {
				return
			}
			c := base + float32(dist)
			if extra != nil {
				c += extra(nk)
			}
			if float64(c) <= maxCost {
				s.offer(gen, nk, k, c, c)
			}
		})
	}
}

// TrailTo returns the route to cell k found by the last Spread.
func (g *Grid) TrailTo(k int) []int32 { return g.scr.trail(k) }

// Straight reports whether a body can walk the straight segment a-b.
func (g *Grid) Straight(ax, ay, bx, by, rad, h float64) bool {
	prev := g.At(ax, ay)
	if !g.Fits(prev, rad, h) {
		return false
	}
	n := int(math.Hypot(bx-ax, by-ay)/(g.Cell*0.5)) + 1
	for i := 1; i <= n; i++ {
		f := float64(i) / float64(n)
		k := g.At(ax+(bx-ax)*f, ay+(by-ay)*f)
		if k == prev {
			continue
		}
		if !g.Fits(k, rad, h) || !g.stepOK(prev, k, g.Cell) {
			return false
		}
		prev = k
	}
	return true
}
