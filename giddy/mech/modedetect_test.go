package mech

import "testing"

func newDetectBrain() *Brain {
	p := DefaultParams()
	return &Brain{P: p, base: p, Slot: 2, tracks: map[int]*Track{}, npcs: map[int]*Track{}}
}

func obsAt(alive int, mechs []MechSeen, beams []Beam) *Obs {
	return &Obs{Alive: alive, Self: Self{Pos: Vec3{0, 0, 0}}, Mechs: mechs, Beams: beams}
}

func TestModeDetectOwnKillsStayPractice(t *testing.T) {
	b := newDetectBrain()
	b.now = 10
	b.modeDetect(obsAt(16, nil, nil), 0)
	b.now = 20
	b.modeDetect(obsAt(15, nil, nil), 1) // our kill
	if b.uncredited != 0 || b.notPractice {
		t.Fatalf("own kill counted: uncredited=%d notPractice=%v", b.uncredited, b.notPractice)
	}
}

func TestModeDetectCreditsRecentHitOutOfView(t *testing.T) {
	b := newDetectBrain()
	b.now = 10
	b.modeDetect(obsAt(16, nil, nil), 0)
	b.hitAt = map[int]float64{7: 12}
	b.now = 15 // 3 s after our last hit on #7, which is now out of view, and no kill event
	b.modeDetect(obsAt(15, nil, nil), 0)
	if b.uncredited != 0 {
		t.Fatalf("recent hit not credited: uncredited=%d", b.uncredited)
	}
	b.hitAt = map[int]float64{8: 1}
	b.now = 20 // hit 19 s ago: too old to credit
	b.modeDetect(obsAt(14, nil, nil), 0)
	if b.uncredited != 1 {
		t.Fatalf("old hit credited: uncredited=%d", b.uncredited)
	}
}

func TestModeDetectFiveUncreditedDeathsMeanFFA(t *testing.T) {
	b := newDetectBrain()
	b.now = 1
	b.modeDetect(obsAt(16, nil, nil), 0)
	for i := 1; i <= 4; i++ {
		b.now = float64(1 + i)
		b.modeDetect(obsAt(16-i, nil, nil), 0)
	}
	if b.notPractice {
		t.Fatal("4 uncredited deaths already flipped to FFA")
	}
	b.now = 6
	b.modeDetect(obsAt(11, nil, nil), 0)
	if !b.notPractice {
		t.Fatal("5 uncredited deaths did not flip to FFA")
	}
}

func TestModeDetectFourCreditedKillsStayPractice(t *testing.T) {
	b := newDetectBrain()
	b.now = 1
	b.modeDetect(obsAt(16, nil, nil), 0)
	for i := 1; i <= 4; i++ { // four splash/zone finishes on mechs we hit 2 s earlier, no kill event
		b.hitAt = map[int]float64{i: float64(i*10) - 2}
		b.now = float64(i * 10)
		b.modeDetect(obsAt(16-i, nil, nil), 0)
	}
	if b.uncredited != 0 || b.notPractice {
		t.Fatalf("credited kills flipped the mode: uncredited=%d notPractice=%v", b.uncredited, b.notPractice)
	}
}

func TestModeDetectBeams(t *testing.T) {
	b := newDetectBrain()
	b.base.BeamFFA, b.P.BeamFFA = 2, 2 // beam detection is off by default (final-only); test it switched on
	b.now = 1
	b.modeDetect(obsAt(16, nil, nil), 0)
	missUs := Beam{By: 5, Kind: "laser", Path: []Vec3{{-100, 0, 7}, {100, 3, 7}}} // passes 3 m from us, ends far away
	mine := Beam{By: 2, Kind: "laser", Path: []Vec3{{0, 0, 7}, {200, 200, 7}}}
	arc := Beam{By: 5, Kind: "lightning", Path: []Vec3{{100, 100, 7}, {110, 100, 7}}}
	b.modeDetect(obsAt(16, nil, []Beam{missUs, mine, arc, missUs}), 0)
	if b.foreignBeams != 0 {
		t.Fatalf("beams aimed at us / ours / lightning counted: %d", b.foreignBeams)
	}
	far := Beam{By: 5, Kind: "laser", Path: []Vec3{{100, 100, 7}, {200, 120, 7}}}
	b.modeDetect(obsAt(16, nil, []Beam{far}), 0)
	if b.notPractice {
		t.Fatal("one foreign beam flipped to FFA")
	}
	b.modeDetect(obsAt(16, nil, []Beam{far}), 0)
	if !b.notPractice {
		t.Fatal("two foreign beams did not flip to FFA")
	}
}
