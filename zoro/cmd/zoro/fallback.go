package main

import (
	"math"

	"zoro/internal/wire"
)

// fallback is used when the arena cannot be loaded: walk into the next circle and shoot the
// nearest mech in view.
type fallback struct{}

func (fallback) Name() string { return "anc" }

func (fallback) Act(o *wire.Obs) wire.Command {
	c := wire.NewCommand(o.Tick)
	me := o.Self.Pos
	to := o.Zone.NextCenter
	yaw := math.Atan2(to[1]-me[1], to[0]-me[0])
	if math.Hypot(to[0]-me[0], to[1]-me[1]) > 10 {
		c.Move = [2]float64{math.Cos(yaw), math.Sin(yaw)}
	}
	c.Boost = !o.Self.InZone
	c.Aim, c.AimSet = [2]float64{yaw, 0}, true
	nearest := math.Inf(1)
	for _, m := range o.Mechs {
		if m.Kind != "mech" {
			continue
		}
		d := math.Hypot(m.Pos[0]-me[0], m.Pos[1]-me[1])
		if d >= nearest {
			continue
		}
		nearest = d
		flight := d / 252
		lx, ly := m.Pos[0]+m.Vel[0]*flight, m.Pos[1]+m.Vel[1]*flight
		c.Aim = [2]float64{math.Atan2(ly-me[1], lx-me[0]), math.Atan2(m.Pos[2]+4.5-me[2]-7, math.Max(d, 1))}
		c.Fire = [2]bool{true, true}
	}
	if o.Offer != nil {
		c.Pick = 0
	}
	return c
}
