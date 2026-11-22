package arena

import "math"

// SightThroughTrees returns how far a sight line along r gets before trees hide what lies beyond:
// a trunk in the way, or enough crown foliage that the transmittance drops below the map's cutoff.
// The result is at most limit.
func (m *Map) SightThroughTrees(r Ray, limit float64) float64 {
	if len(m.Trees) == 0 {
		return limit
	}
	budget := math.Inf(1)
	if m.canopyDensity > 0 && m.canopyCutoff > 0 && m.canopyCutoff < 1 {
		budget = -math.Log(m.canopyCutoff) / m.canopyDensity
	}
	flat := r.DX*r.DX + r.DY*r.DY
	foliage := 0.0
	reach := limit
	visited := make(map[int32]struct{}, 16)
	const stride = 4.0
	n := int(limit/stride) + 1
	seg := limit / float64(n)
	prevCell := -1
	for s := 0; s <= n; s++ {
		t := float64(s) * seg
		if t > reach+bucketSize {
			break
		}
		x, y, _ := r.at(t)
		c := m.treeGrid.at(x, y)
		if c == prevCell {
			continue
		}
		prevCell = c
		for _, ti := range m.treeGrid.list(c) {
			if _, seen := visited[ti]; seen {
				continue
			}
			visited[ti] = struct{}{}
			tr := &m.Trees[ti]
			if tt, ok := trunkHit(tr, r, flat, reach); ok {
				reach = tt
				continue
			}
			chord := crownChord(tr, r, limit)
			if chord <= 0 {
				continue
			}
			foliage += chord
			if foliage > budget {
				// blocked at about the crown centre's projection on the ray
				tc := (tr.CrownX-r.X)*r.DX + (tr.CrownY-r.Y)*r.DY
				if flat > 1e-12 {
					tc /= flat
				}
				reach = math.Min(reach, math.Max(tc, 0))
			}
		}
	}
	return reach
}

// trunkHit tests the ray against a tree trunk (a vertical cylinder up to the crown base).
func trunkHit(tr *Tree, r Ray, flat, before float64) (float64, bool) {
	if tr.TrunkR <= 0 || flat <= 1e-12 {
		return 0, false
	}
	t := ((tr.X-r.X)*r.DX + (tr.Y-r.Y)*r.DY) / flat
	if t <= 0 || t >= before {
		return 0, false
	}
	x, y, z := r.at(t)
	if (x-tr.X)*(x-tr.X)+(y-tr.Y)*(y-tr.Y) >= tr.TrunkR*tr.TrunkR {
		return 0, false
	}
	return t, z >= tr.Z && z <= tr.Z+tr.CrownBase
}

// crownChord is the length of the ray (t in [0,limit]) inside the tree's crown ellipsoid.
func crownChord(tr *Tree, r Ray, limit float64) float64 {
	rh := tr.CrownR
	rv := 0.5 * (tr.Height - tr.CrownBase)
	if rh <= 0 || rv <= 0 {
		return 0
	}
	cz := tr.Z + tr.CrownBase + rv
	// in coordinates where the crown is the unit sphere
	px, py, pz := (r.X-tr.CrownX)/rh, (r.Y-tr.CrownY)/rh, (r.Z-cz)/rv
	vx, vy, vz := r.DX/rh, r.DY/rh, r.DZ/rv
	a := vx*vx + vy*vy + vz*vz
	if a < 1e-12 {
		return 0
	}
	b := 2 * (px*vx + py*vy + pz*vz)
	c := px*px + py*py + pz*pz - 1
	disc := b*b - 4*a*c
	if disc <= 0 {
		return 0
	}
	root := math.Sqrt(disc)
	t0 := math.Max((-b-root)/(2*a), 0)
	t1 := math.Min((-b+root)/(2*a), limit)
	return math.Max(t1-t0, 0)
}
