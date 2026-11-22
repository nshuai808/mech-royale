package pilot

import (
	"math"

	"zoro/internal/wire"
)

// errand is something worth fetching or breaking.
type errand struct {
	kind  string // pickup, cube, crate, npc, drop
	id    int
	pos   vec3
	score float64
}

// worth ranks weapon kinds.
func (p *Pilot) worth(kind string) float64 {
	switch kind {
	case "laser":
		return p.T.LaserValue
	case "lightning":
		return p.T.LightValue
	case "gun":
		return 2
	case "mortar":
		return 1.2
	}
	return 0
}

// wants reports whether we would take a weapon kind and which slot it replaces (-1: a free slot).
// Mortars are taken only against the house squad: carrying one makes every laser hit on us worse.
func (p *Pilot) wants(kind string) (bool, int) {
	if (kind == "mortar" && !p.practice()) || p.holding(kind) >= 0 {
		return false, -1
	}
	for i := range p.slots {
		if !p.slots[i].ok {
			return true, -1
		}
	}
	worst, wv := -1, math.Inf(1)
	for i := range p.slots {
		if p.slots[i].kind == "gun" {
			continue
		}
		if v := p.worth(p.slots[i].kind); v < wv {
			worst, wv = i, v
		}
	}
	if worst >= 0 && p.worth(kind) > wv+0.3 && p.slots[worst].charge <= 0 {
		return true, worst
	}
	return false, -1
}

func (p *Pilot) banned(id int) bool {
	u, ok := p.bans[id]
	return ok && p.now < u
}

// pickErrand chooses the best thing to go and get, or nil.
func (p *Pilot) pickErrand(danger bool, st stance) *errand {
	var best *errand
	var eyes [][3]float64
	if p.T.HiddenBias > 0 && st.careful {
		for _, c := range p.contacts {
			if c.Drone || p.now-c.SeenT > 4 {
				continue
			}
			eyes = append(eyes, vec3{c.Pos[0], c.Pos[1], c.Pos[2] + 8*p.bodyScale(c.Cubes)})
			if len(eyes) >= 6 {
				break
			}
		}
	}
	consider := func(e errand, value, handling, radius float64) {
		d := flatDist(p.pos, e.pos)
		if d > radius || p.banned(e.id) || !p.walkable(e.pos[0], e.pos[1]) {
			return
		}
		eta := d*1.25/p.walk + handling
		if !p.safeLater(e.pos[0], e.pos[1], eta+2+p.T.ZoneSlack, 6) {
			return
		}
		if e.kind != "cube" && p.mechNear(e.pos, 45) {
			value *= 0.35
		}
		// errands out of other mechs' sight first
		for _, w := range eyes {
			if length(w[0]-e.pos[0], w[1]-e.pos[1]) < 230 && p.m.Clear(w[0], w[1], w[2], e.pos[0], e.pos[1], e.pos[2]+4.5) {
				value *= 1 - p.T.HiddenBias
				break
			}
		}
		e.score = value / (eta + 1.5)
		if e.id == p.lootID {
			e.score *= 1.25 // stick with the current pick
		}
		if best == nil || e.score > best.score {
			c := e
			best = &c
		}
	}
	for _, it := range p.pickups {
		if !it.OnFoot {
			continue
		}
		if ok, rep := p.wants(it.Kind); ok {
			v := p.worth(it.Kind) * 4
			if rep >= 0 {
				v -= p.worth(p.slots[rep].kind) * 4
			}
			consider(errand{kind: "pickup", id: it.ID, pos: it.Pos}, v, 0.5, st.lootRadius)
		}
	}
	if p.o.Self.Cubes < st.wantCubes {
		for _, it := range p.cubes {
			if it.OnFoot {
				consider(errand{kind: "cube", id: it.ID, pos: it.Pos}, 11, 0, st.lootRadius)
			}
		}
		for _, it := range p.crates {
			if it.OnFoot { // a crate on a roof drops its cube up there: skip it
				consider(errand{kind: "crate", id: it.ID, pos: it.Pos}, 7, 2.5, st.lootRadius)
			}
		}
		if !danger {
			for _, c := range p.contacts {
				if !c.Drone || p.now-c.SeenT >= 20 {
					continue
				}
				if k := p.g.At(c.Pos[0], c.Pos[1]); !p.g.Blocked[k] && math.Abs(float64(p.g.Floor[k])-c.Pos[2]) < 4 {
					consider(errand{kind: "npc", id: c.ID, pos: c.Pos}, 11, 5, st.lootRadius)
				}
			}
		}
	}
	// supply drops: cubes and a full repair, but everyone knows where they are
	for _, dr := range p.o.Drops {
		d := flatDist(p.pos, dr.Pos)
		if d > p.T.DropRadius {
			continue
		}
		if dr.LandsIn > d/p.walk*1.3+6 && dr.ID != p.lootID {
			continue // too early to set off (but once on our way we stay on it)
		}
		if st.careful && p.o.Self.Cubes >= st.wantCubes && p.hp > p.maxHP*0.7 {
			continue // past the stat cap it is worth it only for the repair
		}
		v := 60 * p.T.DropGreed
		if p.hp < p.maxHP*0.6 {
			v *= 1.5
		}
		consider(errand{kind: "drop", id: dr.ID, pos: dr.Pos}, v, 4+dr.LandsIn*0.3, p.T.DropRadius)
	}
	return best
}

// mechNear reports whether a recently seen mech is within r of pos.
func (p *Pilot) mechNear(pos vec3, r float64) bool {
	for _, c := range p.contacts {
		if !c.Drone && p.now-c.SeenT <= 6 && flatDist(c.Pos, pos) < r {
			return true
		}
	}
	return false
}

// mechSeenWithin reports whether any mech was seen in the last secs seconds.
func (p *Pilot) mechSeenWithin(secs float64) bool {
	for _, c := range p.contacts {
		if !c.Drone && p.now-c.SeenT <= secs {
			return true
		}
	}
	return false
}

// upgradeOrder ranks the upgrade ids (higher first); unknown ids rank 0.25.
var upgradeOrder = map[string]float64{
	"plating": 1.00, "armor": 0.96, "lightning_efficiency": 0.92, "laser_damage": 0.91, "gun_rate": 0.90,
	"gun_damage": 0.88, "lightning_range": 0.87, "laser_charge": 0.86, "gun_velocity": 0.80, "servos": 0.76,
	"nanites": 0.72, "gun_mag": 0.60, "reactor": 0.50, "capacitor": 0.45, "mortar_splash": 0.45,
	"mortar_reload": 0.42, "mortar_velocity": 0.40, "lightning_chain": 0.40,
	"gyros": 0.30, "jets": 0.30, "laser_pierce": 0.20,
}

// practiceUpgradeOrder: against the house squad, damage first. The squad comes one hunter after another, so
// killing each one faster (drum magazine +31% sustained gun damage, lens +18% laser) beats taking 8% less damage.
var practiceUpgradeOrder = map[string]float64{
	"gun_mag": 1.00, "laser_damage": 0.98, "sensors": 0.97, "gun_damage": 0.96, "laser_charge": 0.94, "gun_rate": 0.93,
	"plating": 0.90, "armor": 0.88, "lightning_efficiency": 0.86, "lightning_range": 0.84, "gun_velocity": 0.80,
	"servos": 0.76, "nanites": 0.72, "reactor": 0.50, "capacitor": 0.45, "mortar_splash": 0.45,
	"mortar_reload": 0.42, "mortar_velocity": 0.40, "lightning_chain": 0.40,
	"gyros": 0.30, "jets": 0.30, "laser_pierce": 0.20,
}

func (p *Pilot) chooseUpgrade(cmd *wire.Command) {
	of := p.o.Offer
	if of == nil || len(of.Choices) == 0 {
		return
	}
	order := upgradeOrder
	if p.T.SquadDamageFirst && p.practice() {
		order = practiceUpgradeOrder
	}
	best, bv := 0, -1.0
	for i, c := range of.Choices {
		v, ok := order[c.ID]
		if !ok {
			v = 0.25
		}
		if p.holding("lightning") >= 0 && (c.ID == "reactor" || c.ID == "capacitor") {
			v += 0.3
		}
		if v > bv {
			best, bv = i, v
		}
	}
	cmd.Pick = best
}

// grabWeapon takes the best wanted weapon within reach.
func (p *Pilot) grabWeapon(cmd *wire.Command) {
	if p.now < p.takeT {
		return
	}
	reach := p.cfg.Loot.PickupRadius
	if reach <= 0 {
		reach = 4
	}
	id, val, rep := -1, 0.0, -1
	for _, it := range p.pickups {
		if p.now-it.SeenT > 0.5 || flatDist(p.pos, it.Pos) > reach-0.3 || math.Abs(it.Pos[2]-p.pos[2]) > 3.7 {
			continue
		}
		if ok, r := p.wants(it.Kind); ok && p.worth(it.Kind) > val {
			id, val, rep = it.ID, p.worth(it.Kind), r
		}
	}
	if id >= 0 {
		cmd.Take = id
		if rep >= 0 {
			cmd.Drop = rep
		}
		p.takeT = p.now + 0.25
	}
}

// weaponNearby returns an uncontested weapon on the ground within maxD worth a detour right now.
func (p *Pilot) weaponNearby(maxD float64) *Item {
	var best *Item
	bv := 0.0
	for _, it := range p.pickups {
		if !it.OnFoot || !p.inMyRegion(it.Cell) || p.banned(it.ID) {
			continue
		}
		ok, rep := p.wants(it.Kind)
		if !ok {
			continue
		}
		v := p.worth(it.Kind)
		if rep >= 0 {
			if v -= p.worth(p.slots[rep].kind); v < p.T.ArmSwapMin {
				continue
			}
		}
		d := flatDist(p.pos, it.Pos)
		if d > maxD || !p.safeLater(it.Pos[0], it.Pos[1], d/p.walk+2, 5) {
			continue
		}
		contested := false
		for _, c := range p.contacts {
			if !c.Drone && p.now-c.SeenT <= 5 {
				if dc := flatDist(c.Pos, it.Pos); dc < 30 || dc < d*0.8 {
					contested = true
					break
				}
			}
		}
		if contested {
			continue
		}
		if s := v / (d + 15); s > bv {
			best, bv = it, s
		}
	}
	return best
}

// cubeNearby picks cubes worth walking to mid-fight (a pile from a kill is health and damage).
func (p *Pilot) cubeNearby(tgt *threat, st stance, hpFrac float64) *Item {
	if p.o.Self.Cubes >= st.wantCubes+6 {
		return nil
	}
	var best *Item
	bv := 0.0
	for _, c := range p.cubes {
		if !c.OnFoot || p.now-c.SeenT > 20 || !p.inMyRegion(c.Cell) {
			continue
		}
		pile := 0
		for _, o := range p.cubes {
			if flatDist(o.Pos, c.Pos) < 7 {
				pile++
			}
		}
		limit := 40.0
		if pile >= 2 {
			limit = 110
		}
		d := flatDist(p.pos, c.Pos)
		if d > limit || (d > 30 && hpFrac < 0.3) {
			continue
		}
		if tgt != nil && tgt.c.Arc && p.holding("lightning") < 0 && flatDist(c.Pos, tgt.c.Pos) < 50 {
			continue // not into a lightning arc for it
		}
		if !p.safeLater(c.Pos[0], c.Pos[1], d/p.walk+1, 3) {
			continue
		}
		if v := float64(pile) / (d + 12); v > bv {
			best, bv = c, v
		}
	}
	return best
}

// pest returns the drone that has been shooting us, closest first.
func (p *Pilot) pest() *Contact {
	if p.now-p.droneHurtT > 4 {
		return nil
	}
	var best *Contact
	bd := math.Inf(1)
	for _, c := range p.contacts {
		if !c.Drone || p.now-c.HitMeT > 4 || p.now-c.SeenT > 3 || p.banned(c.ID) {
			continue
		}
		if d := flatDist(p.pos, c.Pos); d < bd {
			best, bd = c, d
		}
	}
	return best
}

// workLog tracks how long we have been working on one crate or drone without hurting it.
type workLog struct {
	id     int
	since  float64
	hpThen float64
	last   float64
}

// futile reports whether we have spent more than limit seconds on the same target without taking
// 20 health off it. Call it on every decision spent on that target.
func (p *Pilot) futile(id int, hp, limit float64) bool {
	w := &p.work
	if id != w.id || hp < w.hpThen-20 || p.now-w.last > 1.5 {
		w.id, w.since, w.hpThen = id, p.now, hp
	}
	w.last = p.now
	if p.now-w.since > limit {
		w.id = -1
		return true
	}
	return false
}

// armed reports whether we carry two weapons.
func (p *Pilot) armed() bool { return p.slots[0].ok && p.slots[1].ok }
