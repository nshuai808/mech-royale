package pilot

import (
	"encoding/binary"
	"encoding/json"
	"math"
	"os"
	"path/filepath"
	"testing"
	"time"

	"zoro/internal/arena"
	"zoro/internal/grid"
	"zoro/internal/wire"
)

// writeArena creates a small synthetic arena: rolling terrain, a tall building with a roof, a low
// plinth and a few trees.
func writeArena(t *testing.T) string {
	t.Helper()
	dir := t.TempDir()
	if err := os.MkdirAll(filepath.Join(dir, "v2"), 0o755); err != nil {
		t.Fatal(err)
	}
	const n, step, x0 = 221, 2.0, -220.0
	terr := make([]byte, 2*n*n)
	for j := 0; j < n; j++ {
		for i := 0; i < n; i++ {
			x, y := x0+float64(i)*step, x0+float64(j)*step
			h := 3*math.Sin(x/40) + 2*math.Cos(y/55)
			binary.LittleEndian.PutUint16(terr[2*(j*n+i):], uint16(int16(h*100)))
		}
	}
	world := map[string]any{
		"bounds":  map[string]float64{"minX": -200, "maxX": 200, "minY": -200, "maxY": 200},
		"rules":   map[string]float64{"canopyDensity": 0.12, "canopyBlockT": 0.3},
		"terrain": map[string]any{"minX": x0, "minY": x0, "step": step, "nx": n, "ny": n, "scale": 0.01},
		"prisms": []map[string]any{
			{"kind": "building", "base": -5, "top": 22, "ring": []float64{20, 20, 60, 20, 60, 60, 20, 60}},
			{"kind": "building", "base": -5, "top": 1, "ring": []float64{-60, -60, -40, -60, -40, -40, -60, -40}},
			{"kind": "building", "base": -5, "top": 14, "ring": []float64{-100, 40, -70, 40, -70, 70, -100, 70}},
		},
		"trees": map[string]any{
			"fields": []string{"x", "y", "z", "height", "crownR", "crownBase", "trunkR"},
			"data":   []float64{0, -80, 0, 14, 4, 5, 0.6, 10, -90, 0, 12, 3.5, 4, 0.5},
		},
	}
	raw, _ := json.Marshal(world)
	if err := os.WriteFile(filepath.Join(dir, "v2", "world.json"), raw, 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "v2", "terrain.i16"), terr, 0o644); err != nil {
		t.Fatal(err)
	}
	return dir
}

func testHello(dir string) *wire.Hello {
	h := &wire.Hello{Type: "hello", Slot: 3, Seed: 42}
	h.Map.Dir = dir
	h.Config = wire.Config{
		Match:   wire.Stats{"tick_hz": 20, "decide_every": 2, "mechs": 16},
		Mech:    wire.Stats{"step_up": 1.2, "height": 9, "radius": 2.5},
		Vision:  wire.VisionCfg{Range: 230, FovDeg: 120, NearRange: 45, MemoryS: 5},
		Weapons: map[string]wire.Stats{"gun": {"speed": 252, "damage": 45, "range": 230}, "laser": {"damage": 315, "range": 280}},
		Cubes:   wire.CubeCfg{DamagePerCube: 0.05, StatCap: 10, SizePerCube: 0.03},
		Loot:    wire.LootCfg{PickupRadius: 4},
	}
	return h
}

func TestMatchSmoke(t *testing.T) {
	dir := writeArena(t)
	m, err := arena.Load(dir)
	if err != nil {
		t.Fatal(err)
	}
	h := testHello(dir)
	g := grid.Build(m, 1.2, 9)
	if roofs, _ := g.Roofs(); len(roofs) == 0 {
		t.Fatalf("expected the tall building to give a usable roof")
	}
	p := New(h, m, g, Defaults())

	pos := vec3{-150, -150, m.Ground(-150, -150)}
	enemy := vec3{-60, -150, m.Ground(-60, -150)}
	slowest := time.Duration(0)
	hp := 1400.0
	for tick := 0; tick < 2400; tick += 2 {
		tt := float64(tick) / 20
		o := &wire.Obs{Type: "obs", Tick: tick, T: tt, Alive: 16}
		o.Self = wire.Me{ID: 3, Pos: pos, HP: hp, MaxHP: 1400, Energy: 80, MaxEnergy: 100, Grounded: true, InZone: true,
			Weapons: []*wire.WeaponState{{Kind: "gun", Ammo: 12}}}
		o.Zone = wire.Zone{Center: [2]float64{0, 0}, Radius: 300 - tt, NextCenter: [2]float64{30, -10}, NextRadius: 140, ShrinkStart: 30, ShrinkEnd: 110}
		o.Mechs = []wire.Actor{{ID: 7, Kind: "mech", Pos: enemy, Aim: [2]float64{math.Atan2(pos[1]-enemy[1], pos[0]-enemy[0]), 0}, HP: 1100, MaxHP: 1400, Weapons: []string{"gun", "laser"}}}
		o.Crates = []wire.Thing{{ID: 50, Pos: vec3{-120, -100, m.Ground(-120, -100)}, HP: 200}}
		o.Pickups = []wire.Pickup{{ID: 60, Kind: "laser", Pos: vec3{-130, -130, m.Ground(-130, -130)}}}
		o.Projectiles = []wire.Projectile{{Kind: "gun", Pos: vec3{enemy[0], enemy[1], enemy[2] + 7}, Vel: vec3{252, 0, 0}}}
		if tick%40 == 0 {
			b := math.Pi
			by := 7
			o.Events = []wire.Event{{Type: "damaged", Amount: 45, Weapon: "gun", Bearing: &b, By: &by}}
			hp -= 20
		}
		if tick == 600 {
			o.Offer = &wire.Offer{Choices: []wire.Choice{{ID: "sensors"}, {ID: "plating"}}}
		}
		start := time.Now()
		cmd := p.Act(o)
		if d := time.Since(start); d > slowest {
			slowest = d
		}
		if cmd.Tick != tick {
			t.Fatalf("tick %d: command for tick %d", tick, cmd.Tick)
		}
		var check map[string]any
		if err := json.Unmarshal(cmd.AppendLine(nil), &check); err != nil {
			t.Fatalf("tick %d: invalid command JSON: %v", tick, err)
		}
		if tick == 600 && cmd.Pick != 1 {
			t.Errorf("expected plating (choice 1), got %d", cmd.Pick)
		}
		// integrate our movement crudely
		pos[0] = clamp(pos[0]+cmd.Move[0]*11.7*0.1, -199, 199)
		pos[1] = clamp(pos[1]+cmd.Move[1]*11.7*0.1, -199, 199)
		pos[2] = m.Floor(pos[0], pos[1], pos[2]+1.2)
		if hp < 300 {
			hp = 1400
		}
	}
	t.Logf("slowest decision: %v, final mode %q", slowest, p.mode)
	if slowest > 200*time.Millisecond {
		t.Errorf("a decision took %v", slowest)
	}
}

func TestRayAndGround(t *testing.T) {
	m, err := arena.Load(writeArena(t))
	if err != nil {
		t.Fatal(err)
	}
	if !m.Clear(-150, -150, 20, -150, 150, 20) {
		t.Error("open line at 20 m should be clear")
	}
	if m.Clear(0, 40, 10, 80, 40, 10) {
		t.Error("line through the tall building should be blocked")
	}
	if f := m.Floor(40, 40, 100); math.Abs(f-22) > 1e-9 {
		t.Errorf("roof floor = %v, want 22", f)
	}
}
