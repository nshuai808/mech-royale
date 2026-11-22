package mech

import "testing"

func TestDuelPosition(t *testing.T) {
	b := Brain{now: 155}
	foe := Track{Dist: 70, HitMe: 154}
	foe.HP = 100
	gun := &WeaponState{Kind: "gun", Ammo: 4, Stats: WeaponStats{Damage: 100, Range: 180, Speed: 200, Mag: 4, Reload: 2, Cooldown: 0.2}}
	light := &WeaponState{Kind: "lightning", Stats: WeaponStats{Damage: 110, Range: 45, Energy: 5, Cooldown: 0.2}}
	me := Self{Energy: 90, Weapons: []*WeaponState{gun, light}}
	me.Stats.WalkSpeed = 10
	check := func(name string, wantRange, wantLOS float64) {
		t.Helper()
		r, los := b.duelPosition(&me, &foe)
		if r != wantRange || los != wantLOS {
			t.Errorf("%s: got (%v,%v), want (%v,%v)", name, r, los, wantRange, wantLOS)
		}
	}
	check("lethal gun beats approach", 70, 1)
	gun.Ammo, gun.Reload = 0, 1.5
	check("reload behind cover", 70, -1)
	gun.Reload = 5
	check("lightning finish beats long reload", 42, 1)
}
