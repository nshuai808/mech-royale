package mech

import "testing"

func TestShortWindow(t *testing.T) {
	me := Self{HP: 800, MaxHP: 1000, Energy: 40}
	me.Stats.BoostSpeed = 20
	foe := Track{Dist: 54, LOS: true}
	foe.Weapons = []string{"laser"}
	light := &WeaponState{Stats: WeaponStats{Range: 45, Energy: 3}}
	if r, ok := matchupRange(&me, &foe, light, nil, 1); !ok || r != 39 {
		t.Fatal(r, ok)
	}
	foe.Dist = 100
	if _, ok := matchupRange(&me, &foe, light, nil, 1); ok {
		t.Fatal("long rush")
	}
	foe.Dist = 40
	foe.Weapons = []string{"lightning"}
	if r, ok := matchupRange(&me, &foe, nil, &WeaponState{}, 1); !ok || r <= 45 {
		t.Fatal(r, ok)
	}
}
