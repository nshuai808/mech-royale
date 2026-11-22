// Package pilot is the zoro agent. Each observation is folded into memory (sense.go), then one
// decision picks a mode — zone, climb, retreat, cover, fight, loot, hold — and turns it into legs
// (motion.go, travel.go) and a torso (ballistics.go).
package pilot

import (
	"fmt"
	"math"
	"math/rand"

	"zoro/internal/arena"
	"zoro/internal/grid"
	"zoro/internal/wire"
)

// Contact is what we remember about another mech or a drone.
type Contact struct {
	ID       int
	Drone    bool
	Pos, Vel vec3
	Aim      [2]float64
	HP       float64
	MaxHP    float64
	Cubes    int
	Gun      bool
	Laser    bool
	Mortar   bool
	Arc      bool // lightning
	Charging bool

	Listed    bool    // in the current observation
	WasListed bool    // in the previous one
	Visible   bool    // a clear line from our eye right now
	SeenT     float64 // last observation that listed it
	SightT    float64 // last time Visible
	ViewT     float64 // last time inside our own field of view
	FirstT    float64 // start of the current sighting
	HitMeT    float64 // last time it hurt us
	HitMe     float64 // decayed damage it dealt us
	IHitT     float64 // last time we hurt it
	IHit      float64 // decayed damage we dealt it
	FacedT    float64 // last time its torso pointed at us
	GhostT    float64 // last time it hit us unseen (Pos is then a guess)
	EngagedT  float64 // last time it counted as engaged with us

	motion motionLog // for the gun lead (aimlead.go)
}

func newContact(id int, now float64) *Contact {
	never := -100.0
	return &Contact{ID: id, HitMeT: never, IHitT: never, FacedT: never, SightT: never, GhostT: never,
		ViewT: never, EngagedT: never, FirstT: now, SeenT: never}
}

// Item is a remembered crate, cube or weapon pickup.
type Item struct {
	ID     int
	Kind   string
	Pos    vec3
	HP     float64
	SeenT  float64
	OnFoot bool // reachable on the walk grid
	Cell   int
}

// slot is one of our weapon slots.
type slot struct {
	ok       bool
	kind     string
	cooldown float64
	ammo     float64
	reload   float64
	charge   float64
	stats    wire.Stats
}

// Pilot is the agent.
type Pilot struct {
	T    Tuning
	cfg  *wire.Config
	m    *arena.Map
	g    *grid.Grid
	rng  *rand.Rand
	slot int

	tick    float64 // seconds per server tick
	period  float64 // seconds per decision
	sizePer float64 // body scale per cube

	// this observation
	o                      *wire.Obs
	now                    float64
	pos, vel               vec3
	aim                    [2]float64
	hp, maxHP, energy      float64
	scale, radius, height  float64
	eye, muzzle            float64
	walk, sprint           float64
	turn, pitchRate, armor float64
	slots                  [2]slot

	// memory
	contacts map[int]*Contact
	crates   map[int]*Item
	cubes    map[int]*Item
	pickups  map[int]*Item

	hurtT       float64 // last weapon damage
	droneHurtT  float64 // last drone damage
	hurtRecent  float64 // decayed weapon damage taken
	hurtBearing float64
	hurtBy      int
	soundT      float64
	soundBear   float64
	kills       int

	// legs
	route     routeState
	surf      surfState
	strafeDir float64
	strafeT   float64
	stuck     stuckState
	lastMove  [2]float64
	cands     []candidate

	// decision state
	mode       string
	targetID   int
	retreating bool
	retreatT   float64
	corneredT  float64
	coverCell  int
	coverT     float64
	deepCell   int
	deepT      float64
	deepTryT   float64
	slipCell   int
	slipT      float64
	slipOnT    float64
	edgeOnT    float64
	unquietT   float64
	holdCell   int
	holdT      float64
	scan       float64
	squadBear  float64
	takeT      float64
	lootID     int
	bans       map[int]float64 // loot ids (and negative roam cells) we gave up on, until when
	work       workLog
	myRegion   int32
	zoneCache  zoneCache
	explore    exploreMap
	roof       roofPlan
	duckCell   int
	duckT      float64
	duckHoldT  float64
	holdClimb  bool
	pinnedRoof bool
	lob        lobby
	seekBans   map[int]float64
	jinkDir    float64
	jinkT      float64
}

// New builds a pilot for the match announced by h.
func New(h *wire.Hello, m *arena.Map, g *grid.Grid, t Tuning) *Pilot {
	p := &Pilot{T: t, cfg: &h.Config, m: m, g: g, slot: h.Slot}
	p.rng = rand.New(rand.NewSource(h.Seed*6271 + int64(h.Slot)*31 + 7))
	hz := h.Config.Match.Get("tick_hz", 20)
	if hz <= 0 {
		hz = 20
	}
	p.tick = 1 / hz
	p.period = h.Config.Match.Get("decide_every", 2) * p.tick
	p.sizePer = h.Config.Cubes.SizePerCube
	p.contacts = map[int]*Contact{}
	p.crates = map[int]*Item{}
	p.cubes = map[int]*Item{}
	p.pickups = map[int]*Item{}
	p.bans = map[int]float64{}
	p.seekBans = map[int]float64{}
	p.jinkDir = 1
	never := -100.0
	p.hurtT, p.droneHurtT, p.soundT = never, never, never
	p.hurtBy = -1
	p.strafeDir = 1
	p.targetID, p.lootID = -1, -1
	p.coverCell, p.deepCell, p.slipCell, p.holdCell, p.duckCell = -1, -1, -1, -1, -1
	p.coverT, p.deepT, p.deepTryT, p.slipT, p.slipOnT, p.edgeOnT = never, never, never, never, never, never
	p.retreatT, p.corneredT, p.unquietT, p.duckT, p.duckHoldT = never, never, never, never, never
	p.route.at = never
	p.surf.at = never
	p.work.id = -1
	p.roof = roofPlan{id: -1, bans: map[int]float64{}}
	p.mode = "start"
	g.Warm() // inside the hello budget, never during a decision
	return p
}

// Name is what we report in the ready message.
func (p *Pilot) Name() string { return p.T.Name }

// Act makes one decision.
func (p *Pilot) Act(o *wire.Obs) wire.Command {
	cmd := wire.NewCommand(o.Tick)
	p.sense(o)
	p.decide(&cmd)
	cmd.Sanitize()
	p.lastMove = cmd.Move
	return cmd
}

func (p *Pilot) mechStat(key string, def float64) float64 { return p.cfg.Mech.Get(key, def) }

// holding returns the slot that holds a weapon kind, or -1.
func (p *Pilot) holding(kind string) int {
	for i := range p.slots {
		if p.slots[i].ok && p.slots[i].kind == kind {
			return i
		}
	}
	return -1
}

// bodyScale is how much a mech with n cubes has grown.
func (p *Pilot) bodyScale(n int) float64 { return 1 + p.sizePer*float64(n) }

// damageMul is the damage multiplier of a mech with n cubes.
func (p *Pilot) damageMul(n int) float64 {
	return 1 + p.cfg.Cubes.DamagePerCube*math.Min(float64(n), p.cfg.Cubes.StatCap)
}

// summary is the short debug label sent with each command.
func (p *Pilot) summary(stance string, engaged int, target float64) string {
	w := ""
	for _, s := range p.slots {
		if s.ok && len(s.kind) >= 2 {
			w += s.kind[:2]
		}
	}
	return fmt.Sprintf("%s:%s u%d hp%.0f n%d on%d k%d c%d %s r%.0f", stance, p.mode, p.lob.unexplained, p.hp, p.o.Alive, engaged, p.kills, p.o.Self.Cubes, w, target)
}
