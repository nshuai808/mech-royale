package mech

import "math"

// Trace is one decision's summary for local analysis tools (MECH_TRACE_FILE). Not used in matches.
type Trace struct {
	T        float64  `json:"t"`
	HP       float64  `json:"hp"`
	MaxHP    float64  `json:"max_hp"`
	Cubes    int      `json:"cubes"`
	Mode     string   `json:"mode"`
	Retreat  bool     `json:"retreat"`
	Prac     bool     `json:"prac"`
	Alive    int      `json:"alive"`
	Kills    int      `json:"kills"`
	Seen     int      `json:"seen"`      // enemy mechs in view now
	LOS160   int      `json:"los160"`    // in view, with line of sight, within 160 m
	Hitters6 int      `json:"hitters6"`  // distinct mechs that damaged us in the last 6 s
	Dmg      float64  `json:"dmg"`       // damage taken this decision
	RearDmg  float64  `json:"rear_dmg"`  // of which from behind
	Dealt    float64  `json:"dealt"`     // damage dealt this decision (hit events)
	TgtDist  float64  `json:"tgt_dist"`  // nearest engaged/LOS enemy distance, -1 if none
	Weapons  []string `json:"weapons"`
	Upgrades []string `json:"upgrades"`
}

func (b *Brain) TraceOf(o *Obs) Trace {
	me := &o.Self
	tr := Trace{T: o.T, HP: me.HP, MaxHP: me.MaxHP, Cubes: me.Cubes, Mode: b.Mode, Retreat: b.retreat, Prac: b.pracOn,
		Alive: o.Alive, Kills: b.kills, TgtDist: -1, Upgrades: me.Upgrades}
	for _, w := range me.Weapons {
		if w != nil {
			tr.Weapons = append(tr.Weapons, w.Kind)
		}
	}
	best := math.Inf(1)
	for _, t := range b.tracks {
		if t.Seen != o.T {
			continue
		}
		tr.Seen++
		if t.LOS && t.Dist < 160 {
			tr.LOS160++
			if t.Dist < best {
				best = t.Dist
			}
		}
		if o.T-t.HitMe < 6 {
			tr.Hitters6++
		}
	}
	for _, t := range b.tracks {
		if t.Seen != o.T && o.T-t.HitMe < 6 {
			tr.Hitters6++
		}
	}
	if !math.IsInf(best, 1) {
		tr.TgtDist = best
	}
	for i := range o.Events {
		e := &o.Events[i]
		switch e.Type {
		case "damaged":
			tr.Dmg += e.Amount
			if e.Rear {
				tr.RearDmg += e.Amount
			}
		case "hit":
			tr.Dealt += e.Amount
		}
	}
	return tr
}
