package pilot

import "math"

type vec3 = [3]float64

func clamp(v, lo, hi float64) float64 { return math.Max(lo, math.Min(hi, v)) }

func length(x, y float64) float64 { return math.Sqrt(x*x + y*y) }

func flatDist(a, b vec3) float64 { return length(a[0]-b[0], a[1]-b[1]) }

func spaceDist(a, b vec3) float64 {
	dx, dy, dz := a[0]-b[0], a[1]-b[1], a[2]-b[2]
	return math.Sqrt(dx*dx + dy*dy + dz*dz)
}

// wrap returns angle a-b folded into (-pi, pi].
func wrap(a, b float64) float64 {
	d := math.Mod(a-b, 2*math.Pi)
	switch {
	case d > math.Pi:
		d -= 2 * math.Pi
	case d <= -math.Pi:
		d += 2 * math.Pi
	}
	return d
}

func unit(x, y float64) (float64, float64) {
	l := length(x, y)
	if l < 1e-9 {
		return 0, 0
	}
	return x / l, y / l
}

func bearing(from, to vec3) float64 { return math.Atan2(to[1]-from[1], to[0]-from[0]) }

// stepToward moves (cx,cy) toward (tx,ty) by at most d.
func stepToward(cx, cy, tx, ty, d float64) (float64, float64) {
	dx, dy := tx-cx, ty-cy
	l := length(dx, dy)
	if l <= d || l < 1e-12 {
		return tx, ty
	}
	return cx + dx/l*d, cy + dy/l*d
}

// segmentGap returns the distance from p to segment a-b and the segment parameter of the closest point.
func segmentGap(px, py, ax, ay, bx, by float64) (float64, float64) {
	ex, ey := bx-ax, by-ay
	t := 0.0
	if l2 := ex*ex + ey*ey; l2 > 1e-12 {
		t = clamp(((px-ax)*ex+(py-ay)*ey)/l2, 0, 1)
	}
	return length(px-ax-ex*t, py-ay-ey*t), t
}

// curve linearly interpolates y over x from sorted (x, y) knots, flat beyond the ends.
type curve [][2]float64

func (c curve) at(x float64) float64 {
	if x <= c[0][0] {
		return c[0][1]
	}
	for i := 1; i < len(c); i++ {
		if x <= c[i][0] {
			f := (x - c[i-1][0]) / (c[i][0] - c[i-1][0])
			return c[i-1][1] + f*(c[i][1]-c[i-1][1])
		}
	}
	return c[len(c)-1][1]
}
