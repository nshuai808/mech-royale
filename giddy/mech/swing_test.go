package mech

import "testing"

func TestContactPriority(t *testing.T) {
	b := Brain{}
	b.listen(12, []Sound{{Kind: "gun", Dist: "near", Bearing: 2}, {Kind: "step", Dist: "near", Bearing: 1}, {Kind: "npc_gun", Dist: "near"}})
	if b.heardYaw != 2 || b.heardUntil <= 12 {
		t.Fatal(b.heardYaw, b.heardUntil)
	}
	b.listen(13, []Sound{{Kind: "step", Dist: "near", Bearing: 1}})
	if b.heardYaw != 1 {
		t.Fatal("expired gun blocked footsteps")
	}
}
