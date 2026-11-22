package pilot

import (
	"math"

	"zoro/internal/wire"
)

// sense folds one observation into memory.
func (p *Pilot) sense(o *wire.Obs) {
	p.o, p.now = o, o.T
	p.readSelf(&o.Self)

	fade := func(tau float64) float64 { return math.Exp(-p.period / tau) }
	p.hurtRecent *= fade(3)
	for _, c := range p.contacts {
		c.WasListed, c.Listed, c.Visible = c.Listed, false, false
		c.HitMe *= fade(4)
		c.IHit *= fade(4)
	}
	if p.onGround() {
		if r := p.g.RegionAt(p.pos[0], p.pos[1], 4); r != 0 {
			p.myRegion = r
		}
	}
	for i := range o.Mechs {
		p.see(&o.Mechs[i])
	}
	p.forget()
	for i := range o.Events {
		p.event(&o.Events[i])
	}
	p.foldThings(o.Crates, p.crates, "crate")
	p.foldThings(o.Cubes, p.cubes, "cube")
	p.foldPickups(o.Pickups)
	for _, s := range o.Sounds {
		switch s.Kind {
		case "gun", "laser", "lightning", "mortar", "laser_charge", "boost", "step", "jet", "reload":
			if s.Dist != "far" {
				p.soundT, p.soundBear = p.now-s.Age, s.Bearing
			}
		}
	}
	if o.Tick%6 == 0 {
		p.markExplored()
	}
}

// readSelf copies our own state, trusting whichever of the reported and the size-scaled body
// numbers is larger.
func (p *Pilot) readSelf(s *wire.Me) {
	p.pos, p.vel, p.aim = s.Pos, s.Vel, s.Aim
	p.hp, p.maxHP, p.energy = s.HP, math.Max(s.MaxHP, 1), s.Energy
	p.scale = p.bodyScale(s.Cubes)
	scaled := func(key string, def float64) float64 {
		base := p.mechStat(key, def) * p.scale
		return math.Max(s.Stats.Get(key, base), base)
	}
	p.muzzle = scaled("muzzle_height", 7)
	p.eye = scaled("eye_height", 8)
	p.radius = scaled("radius", 2.5)
	p.height = scaled("height", 9)
	p.walk = s.Stats.Get("walk_speed", p.mechStat("walk_speed", 11.7))
	p.sprint = s.Stats.Get("boost_speed", p.mechStat("boost_speed", 19.5))
	p.turn = s.Stats.Get("turn_rate", p.mechStat("turn_rate", 4))
	p.pitchRate = s.Stats.Get("pitch_rate", p.mechStat("pitch_rate", 3))
	p.armor = s.Stats.Get("armor", 0)
	for i := range p.slots {
		p.slots[i] = slot{}
		if i >= len(s.Weapons) || s.Weapons[i] == nil {
			continue
		}
		w := s.Weapons[i]
		st := w.Stats
		if st == nil {
			st = p.cfg.Weapon(w.Kind)
		}
		p.slots[i] = slot{ok: true, kind: w.Kind, cooldown: w.Cooldown, ammo: w.Ammo, reload: w.Reload, charge: w.Charge, stats: st}
	}
}

func (p *Pilot) eyePos() vec3 { return vec3{p.pos[0], p.pos[1], p.pos[2] + p.eye} }

// centreHeight is the height of a contact's aim point above its feet.
func (p *Pilot) centreHeight(c *Contact) float64 {
	if c.Drone {
		return p.cfg.Npc.Get("height", 3.5) * 0.5
	}
	return 4.5 * p.bodyScale(c.Cubes)
}

// see updates (or creates) the contact for one listed actor.
func (p *Pilot) see(a *wire.Actor) {
	c := p.contacts[a.ID]
	if c == nil {
		c = newContact(a.ID, p.now)
		c.Drone = a.Kind == "npc"
		p.contacts[a.ID] = c
	}
	if p.now-c.SeenT > 6 {
		c.FirstT = p.now
	}
	c.Pos, c.Vel, c.Aim = a.Pos, a.Vel, a.Aim
	switch {
	case a.MaxHP > 0:
		c.HP, c.MaxHP = a.HP, a.MaxHP
	case c.MaxHP == 0:
		c.HP, c.MaxHP = 1400, 1400
	}
	c.Cubes, c.Charging = a.Cubes, a.Charging
	c.SeenT, c.Listed = p.now, true
	if !c.Drone {
		c.Gun, c.Laser, c.Mortar, c.Arc = false, false, false, false
		for _, w := range a.Weapons {
			c.noteWeapon(w)
		}
	}
	// the server's rule: visible when our eye has a line to its centre or near its top
	e := p.eyePos()
	ch := p.centreHeight(c)
	c.Visible = p.m.Clear(e[0], e[1], e[2], a.Pos[0], a.Pos[1], a.Pos[2]+ch) ||
		p.m.Clear(e[0], e[1], e[2], a.Pos[0], a.Pos[1], a.Pos[2]+ch*1.9)
	if !c.Visible {
		return
	}
	c.SightT = p.now
	half := p.cfg.Vision.FovDeg * math.Pi / 360
	if half <= 0 {
		half = math.Pi / 3
	}
	far := p.cfg.Vision.Range + p.o.Self.Stats.Get("vision_bonus", 0)
	near := p.cfg.Vision.NearRange + p.o.Self.Stats.Get("near_range_bonus", 0)
	d := spaceDist(e, vec3{a.Pos[0], a.Pos[1], a.Pos[2] + ch})
	if d < near-1 || (d < far-2 && math.Abs(wrap(bearing(p.pos, a.Pos), p.aim[0])) < half-0.05) {
		c.ViewT = p.now
	}
	if c.Drone {
		return
	}
	// is its torso turned on us?
	off := math.Abs(wrap(a.Aim[0], bearing(a.Pos, p.pos)))
	if off < 0.12+math.Atan2(p.radius*1.5, math.Max(flatDist(p.pos, a.Pos), 1)) {
		c.FacedT = p.now
	}
	p.recordMotion(c, off < 0.35)
}

func (c *Contact) noteWeapon(kind string) {
	switch kind {
	case "gun":
		c.Gun = true
	case "laser":
		c.Laser = true
	case "mortar":
		c.Mortar = true
	case "lightning":
		c.Arc = true
	}
}

// forget drops contacts that are long gone, and those that vanished from the list while we were
// looking right at them (the server keeps listing hidden mechs for a while, so that means dead).
func (p *Pilot) forget() {
	mem := p.cfg.Vision.MemoryS
	if mem <= 0 {
		mem = 5
	}
	for id, c := range p.contacts {
		gone := p.now-c.SeenT > 45 && p.now-c.HitMeT > 45
		died := c.WasListed && !c.Listed && p.now-c.ViewT < mem-1.5
		if gone || died {
			delete(p.contacts, id)
			if id == p.targetID {
				p.targetID = -1
			}
		}
	}
}

func (p *Pilot) event(e *wire.Event) {
	switch e.Type {
	case "damaged":
		p.damaged(e)
	case "hit":
		p.noteHit(e.Target)
		if c := p.contacts[e.Target]; c != nil {
			c.IHitT = p.now
			c.IHit += e.Amount
		}
	case "kill":
		p.kills++
		delete(p.contacts, e.Target)
		if p.targetID == e.Target {
			p.targetID = -1
		}
	case "took":
		delete(p.pickups, e.ID.Num)
	case "take_failed":
		if e.Reason == "gone" || e.Reason == "have" {
			delete(p.pickups, e.ID.Num)
		}
	}
}

// ghostRange is where we place an unseen shooter along the damage bearing, by weapon.
func ghostRange(weapon string) float64 {
	switch weapon {
	case "laser":
		return 150
	case "lightning":
		return 35
	}
	return 115
}

func (p *Pilot) damaged(e *wire.Event) {
	if e.Weapon == "zone" {
		return
	}
	if e.Bearing != nil {
		p.hurtBearing = *e.Bearing
	}
	if e.Weapon == "npc" {
		p.droneHurtT = p.now
		if e.By != nil {
			if c := p.contacts[*e.By]; c != nil {
				c.HitMeT = p.now
			}
		}
		return
	}
	p.hurtT = p.now
	p.hurtRecent += e.Amount
	if e.By == nil || *e.By == p.o.Self.ID {
		return
	}
	p.hurtBy = *e.By
	c := p.contacts[*e.By]
	if c == nil {
		c = newContact(*e.By, p.now)
		c.Drone = *e.By >= 100
		c.HP, c.MaxHP = 1400, 1400
		p.contacts[*e.By] = c
	}
	if !c.Listed && p.now-c.SeenT > 2 && e.Bearing != nil {
		r := ghostRange(e.Weapon)
		c.Pos = vec3{p.pos[0] + math.Cos(*e.Bearing)*r, p.pos[1] + math.Sin(*e.Bearing)*r, p.pos[2]}
		c.Vel = vec3{}
		c.GhostT = p.now
	}
	c.HitMeT = p.now
	c.HitMe += e.Amount
	if e.Weapon != "gun" {
		c.noteWeapon(e.Weapon)
	}
}

// foldThings merges listed crates or cubes into memory.
func (p *Pilot) foldThings(list []wire.Thing, into map[int]*Item, kind string) {
	listed := make(map[int]bool, len(list))
	for _, t := range list {
		listed[t.ID] = true
		it := into[t.ID]
		if it == nil {
			it = &Item{ID: t.ID, Kind: kind}
			into[t.ID] = it
		}
		it.Pos, it.HP, it.SeenT = t.Pos, t.HP, p.now
		p.locate(it)
	}
	p.prune(into, listed)
}

func (p *Pilot) foldPickups(list []wire.Pickup) {
	listed := make(map[int]bool, len(list))
	for _, t := range list {
		listed[t.ID] = true
		it := p.pickups[t.ID]
		if it == nil {
			it = &Item{ID: t.ID}
			p.pickups[t.ID] = it
		}
		it.Pos, it.Kind, it.SeenT = t.Pos, t.Kind, p.now
		p.locate(it)
	}
	p.prune(p.pickups, listed)
}

// prune drops items that are very old, or that we should be seeing right now and are not.
func (p *Pilot) prune(items map[int]*Item, listed map[int]bool) {
	e := p.eyePos()
	near := p.cfg.Vision.NearRange * 0.85
	for id, it := range items {
		if listed[id] {
			continue
		}
		if p.now-it.SeenT > 240 ||
			(spaceDist(it.Pos, e) < near && p.m.Clear(e[0], e[1], e[2], it.Pos[0], it.Pos[1], it.Pos[2]+0.8)) {
			delete(items, id)
		}
	}
}

// locate decides whether an item lies on the walk grid (directly or right next to it).
func (p *Pilot) locate(it *Item) {
	k := p.g.At(it.Pos[0], it.Pos[1])
	it.Cell, it.OnFoot = k, false
	if !p.g.Blocked[k] && math.Abs(float64(p.g.Floor[k])-it.Pos[2]) < 3 {
		it.OnFoot = true
		return
	}
	if c := p.g.Closest(it.Pos[0], it.Pos[1], p.radius, p.height, 2); c >= 0 && math.Abs(float64(p.g.Floor[c])-it.Pos[2]) < 3 {
		it.Cell, it.OnFoot = c, true
	}
}
