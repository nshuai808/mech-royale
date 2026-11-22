package wire

import (
	"math"
	"strconv"
)

// Unset marks an optional integer field of a Command that should not be sent.
const Unset = -1

// Command is one reply to an observation.
type Command struct {
	Tick    int
	Move    [2]float64
	Boost   bool
	Jump    bool
	Aim     [2]float64
	AimSet  bool
	Fire    [2]bool
	Reload  bool
	Pick    int // upgrade choice index
	Take    int // pickup id
	Drop    int // weapon slot to drop when taking
	Comment string
}

// NewCommand returns a command for tick with every optional field unset.
func NewCommand(tick int) Command {
	return Command{Tick: tick, Pick: Unset, Take: Unset, Drop: Unset}
}

// Sanitize removes anything that would not encode as valid JSON numbers.
func (c *Command) Sanitize() {
	if bad(c.Move[0]) || bad(c.Move[1]) {
		c.Move = [2]float64{}
	}
	if bad(c.Aim[0]) || bad(c.Aim[1]) {
		c.AimSet = false
	}
}

func bad(v float64) bool { return math.IsNaN(v) || math.IsInf(v, 0) }

// enc is a tiny append-only JSON object writer.
type enc struct {
	buf   []byte
	first bool
}

func (e *enc) key(k string) {
	if !e.first {
		e.buf = append(e.buf, ',')
	}
	e.first = false
	e.buf = append(e.buf, '"')
	e.buf = append(e.buf, k...)
	e.buf = append(e.buf, '"', ':')
}

func (e *enc) num(v float64, digits int) {
	if bad(v) || math.Abs(v) > 1e15 {
		v = 0
	}
	e.buf = strconv.AppendFloat(e.buf, v, 'f', digits, 64)
}

func (e *enc) pair(a, b float64, digits int) {
	e.buf = append(e.buf, '[')
	e.num(a, digits)
	e.buf = append(e.buf, ',')
	e.num(b, digits)
	e.buf = append(e.buf, ']')
}

func (e *enc) flags(a, b bool) {
	e.buf = append(e.buf, '[')
	e.buf = strconv.AppendBool(e.buf, a)
	e.buf = append(e.buf, ',')
	e.buf = strconv.AppendBool(e.buf, b)
	e.buf = append(e.buf, ']')
}

// AppendLine writes the command as one JSON line, newline included.
func (c *Command) AppendLine(dst []byte) []byte {
	e := enc{buf: append(dst, '{'), first: true}
	e.key("tick")
	e.buf = strconv.AppendInt(e.buf, int64(c.Tick), 10)
	e.key("move")
	e.pair(c.Move[0], c.Move[1], 4)
	e.key("boost")
	e.buf = strconv.AppendBool(e.buf, c.Boost)
	e.key("jump")
	e.buf = strconv.AppendBool(e.buf, c.Jump)
	if c.AimSet {
		e.key("aim")
		e.pair(c.Aim[0], c.Aim[1], 5)
	}
	e.key("fire")
	e.flags(c.Fire[0], c.Fire[1])
	if c.Reload {
		e.key("reload")
		e.buf = append(e.buf, "true"...)
	}
	for _, f := range [...]struct {
		name string
		v    int
	}{{"pick", c.Pick}, {"take", c.Take}, {"drop", c.Drop}} {
		if f.v >= 0 {
			e.key(f.name)
			e.buf = strconv.AppendInt(e.buf, int64(f.v), 10)
		}
	}
	if c.Comment != "" {
		s := c.Comment
		if len(s) > 64 {
			s = s[:64]
		}
		e.key("debug")
		e.buf = append(e.buf, `{"label":`...)
		e.buf = strconv.AppendQuoteToASCII(e.buf, s)
		e.buf = append(e.buf, '}')
	}
	e.buf = append(e.buf, '}', '\n')
	return e.buf
}
