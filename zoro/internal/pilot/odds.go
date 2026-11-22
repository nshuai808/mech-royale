package pilot

import "math"

// Gun hit rates by range against a mech that is watching the shooter: up close almost everything
// lands, beyond about 100 m most shots are side-stepped during the flight.
var (
	ourGunHits   = curve{{30, 0.95}, {60, 0.86}, {100, 0.55}, {150, 0.28}, {200, 0.18}, {230, 0.12}}
	theirGunHits = curve{{30, 0.92}, {60, 0.78}, {100, 0.57}, {150, 0.32}, {200, 0.15}, {230, 0.10}}
)

// Against the house squad the exchange looks different: they barely dodge (our gun keeps hitting
// at range) and their own accuracy falls off quickly with distance.
var (
	squadOurGunHits   = curve{{60, 0.95}, {120, 0.83}, {180, 0.73}, {230, 0.58}, {230.01, 0.05}}
	squadTheirGunHits = curve{{40, 0.97}, {80, 0.85}, {120, 0.45}, {180, 0.25}, {180.01, 0.12}}
)

// laserRate is the share of laser shots that land (misses are mostly beams stopped by cover).
func (p *Pilot) laserRate() float64 {
	if p.practice() {
		return 0.85
	}
	return 0.75
}

func (p *Pilot) gunCurves() (ours, theirs curve) {
	if p.practice() {
		return squadOurGunHits, squadTheirGunHits
	}
	return ourGunHits, theirGunHits
}

// loadout is what a mech carries, for damage estimates.
type loadout struct {
	gun, laser, arc, mortar bool
	cubes                   int
	arcPower                bool // enough energy to keep arcing
}

// dps estimates the sustained damage per second of a loadout at range d.
func (p *Pilot) dps(l loadout, d float64, gunHits curve) float64 {
	total := 0.0
	if l.gun {
		g := p.cfg.Weapon("gun")
		if d < g.Get("range", 230) {
			mag, cd, rl := g.Get("mag", 12), g.Get("cooldown", 0.24), g.Get("reload", 2.4)
			total += g.Get("damage", 45) * mag / (mag*cd + rl) * gunHits.at(d)
		}
	}
	if l.laser {
		w := p.cfg.Weapon("laser")
		if d < w.Get("range", 280) {
			total += w.Get("damage", 315) / (w.Get("charge", 0.75) + w.Get("cooldown", 1.65)) * p.laserRate()
		}
	}
	if l.arc && l.arcPower {
		w := p.cfg.Weapon("lightning")
		if d < w.Get("range", 45) {
			total += w.Get("damage", 60) / w.Get("cooldown", 0.25)
		}
	}
	if l.mortar && d > 12 && d < 200 {
		w := p.cfg.Weapon("mortar")
		total += w.Get("damage", 200) / w.Get("cooldown", 2.6) * 0.25
	}
	return total * p.damageMul(l.cubes)
}

// ourDPS is our own damage rate at range d.
func (p *Pilot) ourDPS(d float64) float64 {
	l := loadout{
		gun:      p.holding("gun") >= 0 && d < p.T.GunMaxRange,
		laser:    p.holding("laser") >= 0,
		arc:      p.holding("lightning") >= 0,
		mortar:   p.holding("mortar") >= 0,
		cubes:    p.o.Self.Cubes,
		arcPower: p.energy > 15,
	}
	ours, _ := p.gunCurves()
	return p.dps(l, d, ours)
}

// theirDPS is a contact's damage rate on us at range d (before our armour).
func (p *Pilot) theirDPS(c *Contact, d float64) float64 {
	if c.Drone {
		if d > 95 {
			return 0
		}
		return p.cfg.Npc.Get("damage", 25) / p.cfg.Npc.Get("cooldown", 1) * 0.5
	}
	l := loadout{gun: c.Gun || !(c.Laser || c.Mortar || c.Arc), laser: c.Laser, arc: c.Arc, mortar: c.Mortar, cubes: c.Cubes, arcPower: true}
	// while we keep arcing them their laser is shorted out
	if a := p.holding("lightning"); a >= 0 && p.energy > 20 && d < p.slots[a].stats.Get("range", 45)-3 {
		l.laser = false
	}
	_, theirs := p.gunCurves()
	return p.dps(l, d, theirs) * p.tierFactor()
}

// tierFactor scales a house bot's damage by its likely tier. The practice squad is 4 easy, 4 medium,
// 4 hard and 3 expert bots that hunt us weakest first, so the number already dead tells us who is
// coming now: fight the early easy hunters hard, pick fights against the late experts more carefully.
func (p *Pilot) tierFactor() float64 {
	if !p.T.SquadTiers || !p.practice() {
		return 1
	}
	kills := 16 - p.o.Alive
	switch {
	case kills < 4:
		return 0.6
	case kills < 8:
		return 0.8
	case kills < 12:
		return 1.0
	}
	return 1.2
}

// odds evaluates a fight with c at several ranges, paying for the trip to each, and returns the
// best advantage — (time they need to kill us) / (time we need to kill them) — with the range band
// to hold for it.
func (p *Pilot) odds(c *Contact, d float64) (adv, near, far float64) {
	theirHP := c.HP
	if theirHP <= 0 {
		theirHP = math.Max(c.MaxHP, 1)
	}
	keep := 1 - p.armor
	droneFactor := 1.0
	if c.Drone {
		droneFactor = 0.6
	}
	best, bestR := -1.0, d
	try := func(r float64, stay bool) {
		mine := p.ourDPS(r)
		if mine < 1 {
			return
		}
		theirs := p.theirDPS(c, r) * keep * droneFactor
		taken, dealt := 0.0, 0.0
		if travel := math.Abs(d - r); !stay && travel > 8 {
			mid, secs := (d+r)/2, travel/9*0.8
			taken = p.theirDPS(c, mid) * keep * droneFactor * secs
			dealt = p.ourDPS(mid) * secs // the torso keeps shooting on the way
			if r > d && !c.Drone {
				taken += 60 // a longer range is hard to hold against someone closing
			}
		}
		left := p.hp - taken
		if left <= 0 {
			return
		}
		a := 10.0
		if theirs >= 1 {
			a = (left / theirs) / (math.Max(theirHP-dealt, 20) / mine)
		}
		if stay {
			a *= 1.05
		}
		if a > best {
			best, bestR = a, r
		}
	}
	try(d, true)
	for _, r := range [...]float64{22, 45, 75, 115, 160, 200} {
		try(r, false)
	}
	if best < 0 {
		return 0, 30, 55
	}
	w := 10 + bestR*0.15
	return best, math.Max(8, bestR-w), bestR + w
}
