package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"os"

	"mechbot/mech"
)

// MECH_DEBUG=1 prints recovered panics to stderr (matches show no stderr; local tools only).
var debugOn = os.Getenv("MECH_DEBUG") != ""

// MECH_TRACE_FILE=prefix writes one JSON line per decision to prefix-<pid>.jsonl (local analysis only).
var traceOut *bufio.Writer

func main() {
	if pre := os.Getenv("MECH_TRACE_FILE"); pre != "" {
		if f, err := os.Create(fmt.Sprintf("%s-%d.jsonl", pre, os.Getpid())); err == nil {
			traceOut = bufio.NewWriter(f)
		}
	}
	lines := make(chan []byte, 256)
	go func() {
		r := bufio.NewReaderSize(os.Stdin, 1<<20)
		for {
			line, err := r.ReadBytes('\n')
			if len(line) > 0 {
				lines <- line
			}
			if err != nil {
				close(lines)
				return
			}
		}
	}()
	out := bufio.NewWriterSize(os.Stdout, 1<<16)
	send := func(v any) {
		b, err := json.Marshal(v)
		if err != nil {
			return
		}
		out.Write(b)
		out.WriteByte('\n')
		out.Flush()
	}
	var brain *mech.Brain
	var probe struct {
		Type string `json:"type"`
	}
	for {
		first, ok := <-lines
		if !ok {
			return
		}
		batch := [][]byte{first}
	drain:
		for {
			select {
			case l, ok := <-lines:
				if !ok {
					break drain
				}
				batch = append(batch, l)
			default:
				break drain
			}
		}
		var latest []byte
		for _, raw := range batch {
			probe.Type = ""
			if json.Unmarshal(raw, &probe) != nil {
				continue
			}
			switch probe.Type {
			case "hello":
				var h mech.Hello
				if err := json.Unmarshal(raw, &h); err != nil {
					fmt.Fprintln(os.Stderr, "hello:", err)
				}
				dir := h.Map.Dir
				if dir == "" {
					dir = "/arena"
				}
				w, err := mech.LoadWorld(dir)
				if err != nil {
					fmt.Fprintln(os.Stderr, "map:", err, "- playing on a flat map")
					w = mech.FlatWorld()
				}
				brain = mech.NewBrain(&h, w)
				send(map[string]string{"type": "ready", "name": "umich-ibe"})
			case "obs":
				latest = raw
			case "end":
				return
			}
		}
		if latest == nil {
			continue
		}
		var o mech.Obs
		if err := json.Unmarshal(latest, &o); err != nil || brain == nil {
			var t struct {
				Tick int `json:"tick"`
			}
			json.Unmarshal(latest, &t)
			send(mech.Action{Tick: t.Tick})
			continue
		}
		before := brain.Panics
		send(brain.Act(&o))
		if traceOut != nil {
			if b, err := json.Marshal(brain.TraceOf(&o)); err == nil {
				traceOut.Write(b)
				traceOut.WriteByte('\n')
				traceOut.Flush()
			}
		}
		if debugOn && brain.Panics > before {
			fmt.Fprintf(os.Stderr, "PANIC tick %d: %s\n", o.Tick, brain.LastPanic)
		}
	}
}
