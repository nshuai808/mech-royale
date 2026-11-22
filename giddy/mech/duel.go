package mech

import "math"

// Estimate a weapon's solo finish time. Concurrent fire and opponent motion
// are deliberately omitted; only change range for a clear lightning advantage.
func duelTimes(w *WeaponState, hp, scale, energy, dist float64) (first, finish float64) {
	unavailable := math.Inf(1)
	if w == nil || w.Stats.Damage <= 0 {
		return unavailable, unavailable
	}
	s := w.Stats
	shots := math.Ceil(hp / (s.Damage * scale))
	first = w.Cooldown
	cycle := s.Cooldown
	pauses := 0.0
	switch w.Kind {
	case "gun":
		if dist > s.Range*0.96 || s.Speed <= 0 || s.Mag < 1 {
			return unavailable, unavailable
		}
		ammo := w.Ammo
		if ammo < 1 || w.Reload > 0 {
			delay := w.Reload
			if delay <= 0 {
				delay = s.Reload
			}
			first = math.Max(first, delay)
			ammo = s.Mag
		}
		pauses = math.Max(0, math.Ceil((shots-ammo)/s.Mag)) * s.Reload
		finish = dist / s.Speed
	case "laser":
		if dist > s.Range*0.97 {
			return unavailable, unavailable
		}
		charge := s.Charge
		if hp <= 0.8*s.Damage*scale && s.MinFrac < 1 {
			charge = math.Max(s.MinCharge, s.Charge*(hp/(0.8*s.Damage*scale)-s.MinFrac)/(1-s.MinFrac))
		}
		first += math.Max(0, charge-w.Charge)
		cycle += s.Charge
	case "lightning":
		if dist >= s.Range-1.5 || energy < s.Energy {
			return unavailable, unavailable
		}
		if shots*s.Energy > energy {
			return first, unavailable
		}
	default:
		return unavailable, unavailable
	}
	return first, finish + first + math.Max(0, shots-1)*cycle + pauses
}

func (b *Brain) duelPosition(me *Self, foe *Track) (float64, float64) {
	scale := 1 + b.Cfg.Cubes.DamagePerCube*float64(min(me.Cubes, b.Cfg.Cubes.StatCap))
	first, finish := math.Inf(1), math.Inf(1)
	for _, w := range me.Weapons {
		next, kill := duelTimes(w, foe.HP, scale, me.Energy, foe.Dist)
		first, finish = math.Min(first, next), math.Min(finish, kill)
	}
	r := foe.Dist
	if math.IsInf(first, 1) {
		r = b.prefRange(me, foe)
	}
	_, light := hasWeapon(me.Weapons, "lightning")
	if light != nil {
		reach := light.Stats.Range - 3
		if foe.Dist > reach && me.Stats.WalkSpeed > 0 {
			_, kill := duelTimes(light, foe.HP, scale, me.Energy, reach)
			if (foe.Dist-reach)/me.Stats.WalkSpeed+kill+0.3 < finish {
				r = reach
			}
		}
	}
	bearing := math.Atan2(me.Pos[1]-foe.Pos[1], me.Pos[0]-foe.Pos[0])
	threat := b.now-foe.HitMe < 2 || math.Abs(angDiff(foe.Aim[0], bearing)) < 0.22
	if first > 0.35 && !math.IsInf(first, 1) && threat && r >= foe.Dist {
		return r, -1
	}
	return r, 1
}
