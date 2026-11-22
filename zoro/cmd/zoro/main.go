// Command zoro plays one mech in a mechfight/1 match: JSON lines in on stdin, one action line out
// for each observation. Nothing but protocol messages is ever written to stdout.
package main

import (
	"bufio"
	"bytes"
	"encoding/json"
	"fmt"
	"os"
	"runtime/debug"

	"zoro/internal/arena"
	"zoro/internal/grid"
	"zoro/internal/pilot"
	"zoro/internal/wire"
)

// brain is anything that turns observations into commands.
type brain interface {
	Act(o *wire.Obs) wire.Command
	Name() string
}

func logf(format string, args ...any) { fmt.Fprintf(os.Stderr, format+"\n", args...) }

func main() {
	// the live heap is small and the limit is 512 MB: collect rarely
	debug.SetGCPercent(800)
	debug.SetMemoryLimit(380 << 20)

	s := &session{out: bufio.NewWriterSize(os.Stdout, 1<<16)}
	for batch := range readBatches(os.Stdin) {
		if s.handle(batch) {
			return
		}
	}
}

// readBatches yields the input lines grouped into whatever has piled up since the last batch, so
// a slow decision answers only the newest observation.
func readBatches(r *os.File) <-chan [][]byte {
	lines := make(chan []byte, 256)
	go func() {
		defer close(lines)
		rd := bufio.NewReaderSize(r, 1<<20)
		for {
			line, err := rd.ReadBytes('\n')
			if len(bytes.TrimSpace(line)) > 0 {
				lines <- line
			}
			if err != nil {
				return
			}
		}
	}()
	out := make(chan [][]byte)
	go func() {
		defer close(out)
		for first := range lines {
			batch := [][]byte{first}
		more:
			for {
				select {
				case l, ok := <-lines:
					if !ok {
						break more
					}
					batch = append(batch, l)
				default:
					break more
				}
			}
			out <- batch
		}
	}()
	return out
}

type session struct {
	out    *bufio.Writer
	b      brain
	last   wire.Command
	buf    []byte
	badObs int
}

// handle processes one batch; it returns true when the match is over.
func (s *session) handle(batch [][]byte) bool {
	var newest []byte
	for _, line := range batch {
		switch kindOf(line) {
		case "obs":
			newest = line
		case "hello":
			s.hello(line)
		case "end":
			return true
		}
	}
	if newest != nil {
		s.observe(newest)
	}
	return false
}

// kindOf reads the message type cheaply (every server message starts with its type).
func kindOf(line []byte) string {
	if bytes.Contains(line[:min(len(line), 40)], []byte(`"obs"`)) {
		return "obs"
	}
	var head struct {
		Type string `json:"type"`
	}
	if json.Unmarshal(line, &head) != nil {
		return ""
	}
	return head.Type
}

// decode unmarshals a line, retrying once with whole-number floats rewritten as integers.
func decode(line []byte, v any) error {
	err := json.Unmarshal(line, v)
	if err == nil {
		return nil
	}
	if err2 := json.Unmarshal(integerize(line), v); err2 == nil {
		return nil
	}
	return err
}

func (s *session) hello(line []byte) {
	var h wire.Hello
	if err := decode(line, &h); err != nil {
		logf("hello: %v", err)
	}
	s.b = s.build(&h)
	fmt.Fprintf(s.out, "{\"type\":\"ready\",\"name\":%q}\n", s.b.Name())
	s.out.Flush()
}

// build loads the arena and makes the pilot, falling back to the simple brain on any failure.
func (s *session) build(h *wire.Hello) (b brain) {
	defer func() {
		if r := recover(); r != nil {
			logf("setup panic: %v\n%s", r, debug.Stack())
			b = fallback{}
		}
	}()
	for _, dir := range []string{h.Map.Dir, "/arena", "arena"} {
		if dir == "" {
			continue
		}
		m, err := arena.Load(dir)
		if err != nil {
			logf("arena %q: %v", dir, err)
			continue
		}
		g := grid.Build(m, h.Config.Mech.Get("step_up", 1.2), h.Config.Mech.Get("height", 9))
		return pilot.New(h, m, g, tuning())
	}
	return fallback{}
}

// tuning returns the defaults, with overrides from ZORO_TUNE (a JSON object of Tuning fields) for
// local experiments. Matches never set it.
func tuning() pilot.Tuning {
	t := pilot.Defaults()
	if v := os.Getenv("ZORO_TUNE"); v != "" {
		if err := json.Unmarshal([]byte(v), &t); err != nil {
			logf("ZORO_TUNE: %v", err)
		}
	}
	return t
}

func (s *session) observe(line []byte) {
	var o wire.Obs
	if err := decode(line, &o); err != nil {
		s.badObs++
		if s.badObs <= 5 || s.badObs%200 == 0 {
			logf("bad obs #%d: %v", s.badObs, err)
		}
		if tick, ok := tickOf(line); ok {
			s.send(s.coast(tick)) // never go silent
		}
		return
	}
	if s.b == nil {
		s.b = fallback{}
	}
	cmd := s.safeAct(&o)
	cmd.Tick = o.Tick
	s.last = cmd
	s.send(cmd)
}

// coast repeats the last movement and aim.
func (s *session) coast(tick int) wire.Command {
	c := wire.NewCommand(tick)
	c.Move, c.Boost, c.Aim, c.AimSet = s.last.Move, s.last.Boost, s.last.Aim, s.last.AimSet
	return c
}

func (s *session) safeAct(o *wire.Obs) (cmd wire.Command) {
	defer func() {
		if r := recover(); r != nil {
			logf("tick %d panic: %v\n%s", o.Tick, r, debug.Stack())
			cmd = s.coast(o.Tick)
		}
	}()
	return s.b.Act(o)
}

func (s *session) send(c wire.Command) {
	s.buf = c.AppendLine(s.buf[:0])
	s.out.Write(s.buf)
	s.out.Flush()
}

// tickOf extracts "tick":N from a line that would not decode.
func tickOf(line []byte) (int, bool) {
	i := bytes.Index(line, []byte(`"tick":`))
	if i < 0 {
		return 0, false
	}
	rest := bytes.TrimLeft(line[i+7:], " ")
	n, digits := 0, 0
	for _, ch := range rest {
		if ch < '0' || ch > '9' {
			break
		}
		n = n*10 + int(ch-'0')
		digits++
	}
	return n, digits > 0
}

// integerize rewrites numbers such as 12.0 or 7.000 outside strings as 12 and 7, so a server that
// prints whole numbers as floats cannot break decoding into integer fields.
func integerize(in []byte) []byte {
	out := make([]byte, 0, len(in))
	quoted, escaped := false, false
	for i := 0; i < len(in); i++ {
		ch := in[i]
		if quoted {
			out = append(out, ch)
			switch {
			case escaped:
				escaped = false
			case ch == '\\':
				escaped = true
			case ch == '"':
				quoted = false
			}
			continue
		}
		if ch == '"' {
			quoted = true
		} else if ch == '.' && i > 0 && in[i-1] >= '0' && in[i-1] <= '9' {
			j := i + 1
			for j < len(in) && in[j] == '0' {
				j++
			}
			if j > i+1 && j < len(in) && bytes.IndexByte([]byte(",]} \n\r\t"), in[j]) >= 0 {
				i = j - 1
				continue
			}
		}
		out = append(out, ch)
	}
	return out
}
