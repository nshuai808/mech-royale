package mech

import "testing"

func TestLaserAimReservation(t *testing.T) {
	me := Self{}
	me.Stats.TurnRate = 2
	me.Stats.PitchRate = 1
	w := WeaponState{Charge: 0.4, Stats: WeaponStats{Charge: 0.75}}
	if reserveLaserAim(&me, &w, 0, 0) {
		t.Fatal("gun should own this window")
	}
	if !reserveLaserAim(&me, &w, 1, 0) {
		t.Fatal("large turn needs an early handoff")
	}
	w.Charge = 0.7
	if !reserveLaserAim(&me, &w, 0, 0) {
		t.Fatal("release imminent")
	}
}
