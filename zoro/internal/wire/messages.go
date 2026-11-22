// Package wire defines the mechfight/1 messages exchanged with the match server.
//
// Only the fields the pilot actually reads are declared; encoding/json ignores the rest.
package wire

import "strconv"

// Hello is the first message of a match.
type Hello struct {
	Type   string `json:"type"`
	Slot   int    `json:"slot"`
	Seed   int64  `json:"seed"`
	Map    MapRef `json:"map"`
	Config Config `json:"config"`
}

// MapRef points at the arena files.
type MapRef struct {
	Dir string `json:"dir"`
}

// Stats is a bag of named numbers (the server sends most tunables this way).
type Stats map[string]float64

// Get returns the value for key, or def when it is missing.
func (s Stats) Get(key string, def float64) float64 {
	if s == nil {
		return def
	}
	if v, ok := s[key]; ok {
		return v
	}
	return def
}

// VisionCfg describes what a mech can perceive.
type VisionCfg struct {
	Range     float64 `json:"range"`
	FovDeg    float64 `json:"fov_deg"`
	NearRange float64 `json:"near_range"`
	MemoryS   float64 `json:"memory_s"`
}

// CubeCfg describes how collected cubes change a mech.
type CubeCfg struct {
	DamagePerCube float64 `json:"damage_per_cube"`
	StatCap       float64 `json:"stat_cap"`
	SizePerCube   float64 `json:"size_per_cube"`
}

// LootCfg describes weapon pickups.
type LootCfg struct {
	PickupRadius float64 `json:"pickup_radius"`
}

// Config is the match configuration sent with Hello.
type Config struct {
	Match   Stats            `json:"match"`
	Mech    Stats            `json:"mech"`
	Vision  VisionCfg        `json:"vision"`
	Weapons map[string]Stats `json:"weapons"`
	Cubes   CubeCfg          `json:"cubes"`
	Crates  Stats            `json:"crates"`
	Loot    LootCfg          `json:"loot"`
	Npc     Stats            `json:"npc"`
}

// Weapon returns the configured stats of a weapon kind (never nil-panics).
func (c *Config) Weapon(kind string) Stats {
	if c.Weapons == nil {
		return nil
	}
	return c.Weapons[kind]
}

// WeaponState is one of our own weapon slots.
type WeaponState struct {
	Kind     string  `json:"kind"`
	Cooldown float64 `json:"cooldown"`
	Ammo     float64 `json:"ammo"`
	Reload   float64 `json:"reload"`
	Charge   float64 `json:"charge"`
	Stats    Stats   `json:"stats"`
}

// Me is our own mech.
type Me struct {
	ID        int            `json:"id"`
	Pos       [3]float64     `json:"pos"`
	Vel       [3]float64     `json:"vel"`
	Aim       [2]float64     `json:"aim"`
	HP        float64        `json:"hp"`
	MaxHP     float64        `json:"max_hp"`
	Energy    float64        `json:"energy"`
	MaxEnergy float64        `json:"max_energy"`
	Grounded  bool           `json:"grounded"`
	Cubes     int            `json:"cubes"`
	InZone    bool           `json:"in_zone"`
	Weapons   []*WeaponState `json:"weapons"`
	Stats     Stats          `json:"stats"`
}

// Actor is another mech or a drone.
type Actor struct {
	ID       int        `json:"id"`
	Kind     string     `json:"kind"`
	Pos      [3]float64 `json:"pos"`
	Vel      [3]float64 `json:"vel"`
	Aim      [2]float64 `json:"aim"`
	HP       float64    `json:"hp"`
	MaxHP    float64    `json:"max_hp"`
	Cubes    int        `json:"cubes"`
	Weapons  []string   `json:"weapons"`
	Charging bool       `json:"charging"`
}

// Projectile is a shot in flight.
type Projectile struct {
	Kind string     `json:"kind"`
	Pos  [3]float64 `json:"pos"`
	Vel  [3]float64 `json:"vel"`
}

// Thing is a crate or a cube.
type Thing struct {
	ID  int        `json:"id"`
	Pos [3]float64 `json:"pos"`
	HP  float64    `json:"hp"`
}

// Pickup is a weapon lying on the ground.
type Pickup struct {
	ID   int        `json:"id"`
	Kind string     `json:"kind"`
	Pos  [3]float64 `json:"pos"`
}

// Sound is something we heard.
type Sound struct {
	Kind    string  `json:"kind"`
	Bearing float64 `json:"bearing"`
	Dist    string  `json:"dist"`
	Age     float64 `json:"age"`
}

// Event covers every event type; fields that do not apply stay zero.
type Event struct {
	Type    string   `json:"type"`
	Amount  float64  `json:"amount"`
	Weapon  string   `json:"weapon"`
	Bearing *float64 `json:"bearing"`
	By      *int     `json:"by"`
	Target  int      `json:"target"`
	ID      FlexID   `json:"id"`
	Reason  string   `json:"reason"`
}

// FlexID is an id that is a number for most events and a string for upgrades.
type FlexID struct {
	Num  int
	Text string
}

// UnmarshalJSON accepts either a JSON number or a JSON string and never fails.
func (f *FlexID) UnmarshalJSON(data []byte) error {
	if len(data) == 0 {
		return nil
	}
	if data[0] == '"' {
		if s, err := strconv.Unquote(string(data)); err == nil {
			f.Text = s
		}
		return nil
	}
	if v, err := strconv.ParseFloat(string(data), 64); err == nil {
		f.Num = int(v)
	}
	return nil
}

// Drop is a supply drop.
type Drop struct {
	ID      int        `json:"id"`
	Pos     [3]float64 `json:"pos"`
	LandsIn float64    `json:"lands_in"`
	Holder  *int       `json:"holder"`
}

// Zone is the safe circle and where it is going.
type Zone struct {
	Center      [2]float64 `json:"center"`
	Radius      float64    `json:"radius"`
	NextCenter  [2]float64 `json:"next_center"`
	NextRadius  float64    `json:"next_radius"`
	ShrinkStart float64    `json:"shrink_start"`
	ShrinkEnd   float64    `json:"shrink_end"`
}

// Choice is one option of an upgrade offer.
type Choice struct {
	ID string `json:"id"`
}

// Offer is a pending upgrade choice.
type Offer struct {
	Choices []Choice `json:"choices"`
}

// Obs is one observation.
type Obs struct {
	Type        string       `json:"type"`
	Tick        int          `json:"tick"`
	T           float64      `json:"t"`
	Alive       int          `json:"alive"`
	Self        Me           `json:"self"`
	Mechs       []Actor      `json:"mechs"`
	Projectiles []Projectile `json:"projectiles"`
	Crates      []Thing      `json:"crates"`
	Cubes       []Thing      `json:"cubes"`
	Pickups     []Pickup     `json:"pickups"`
	Sounds      []Sound      `json:"sounds"`
	Events      []Event      `json:"events"`
	Drops       []Drop       `json:"drops"`
	Zone        Zone         `json:"zone"`
	Offer       *Offer       `json:"offer"`
}
