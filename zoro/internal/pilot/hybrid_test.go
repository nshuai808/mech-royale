package pilot

import (
	"testing"
	"zoro/internal/wire"
)

func TestHybridPractice(t *testing.T) {
	p := Pilot{now: 5, T: Defaults(), o: &wire.Obs{Alive: 8, Zone: wire.Zone{NextRadius: 120}}}
	if !p.practice() {
		t.Fatal("practice opening")
	}
	p.lob.ffa = true
	if p.practice() {
		t.Fatal("confirmed FFA entered practice")
	}
	p.now = 160
	c := Contact{ID: 12, HP: 800, MaxHP: 1000}
	squad := stance{squad: true}
	if !p.deferHunter(squad, 0.55, &c, 80) || p.deferHunter(stance{}, 0.55, &c, 80) || p.deferHunter(squad, 0.7, &c, 80) || p.deferHunter(squad, 0.55, &c, 40) {
		t.Fatal("recovery eligibility")
	}
	c.HitMeT = 159
	if p.deferHunter(squad, 0.55, &c, 80) {
		t.Fatal("ignored recent attacker")
	}
	c.HitMeT = 0
	p.fightID, p.fightT = 12, 159
	if p.deferHunter(squad, 0.55, &c, 80) {
		t.Fatal("interrupted active fight")
	}
	if fightCubeReach(true, 0.8, 3) != 40 || fightCubeReach(true, 0.4, 3) != 22.8 || fightCubeReach(false, 0.4, 3) != 110 {
		t.Fatal("cube limits")
	}
}
