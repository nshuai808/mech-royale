package mech

import "testing"

func TestInterceptCrossing(t *testing.T) {
	w, err := LoadWorld("../../kit/arena")
	if err != nil {
		t.Fatal(err)
	}
	b := Brain{W: w}
	b.Cfg.Mech.Height = 9
	o := Obs{T: 10.1}
	o.Zone.Radius = 400
	o.Zone.NextRadius = 350
	o.Zone.ShrinkStart = 60
	o.Self.Stats.WalkSpeed = 11.7
	o.Self.Stats.MuzzleHeight = 7
	o.Self.Pos = Vec3{85.491, 206.944, 1.77}
	hunter := Track{Seen: 10, clearSeen: 10}
	hunter.ID, hunter.Kind = 7, "mech"
	hunter.Pos = Vec3{108.7393, 254.5517, 2.3424}
	hunter.Vel = Vec3{5.4644, -9.9079, 0}
	seen := []*Track{&hunter}
	p, ok := b.intercept(&o, seen)
	step := hyp(p.stand[0]-o.Self.Pos[0], p.stand[1]-o.Self.Pos[1])
	if !ok || step < 2 || step > 5.01 {
		t.Fatal("expected a bounded lateral move", p)
	}
	o.T += 0.1
	if next, ok := b.intercept(&o, seen); !ok || next != p {
		t.Fatal("destination changed without a fresh sighting")
	}
	o.T = 11
	if _, ok := b.intercept(&o, seen); ok {
		t.Fatal("expired sighting")
	}
	b.lane = interceptPlan{}
	o.T = 10.1
	hunter.Vel = Vec3{-5.4644, 9.9079, 0}
	if _, ok := b.intercept(&o, seen); ok {
		t.Fatal("hunter moving away")
	}
}
