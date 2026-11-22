// Package arena holds the static map (a terrain heightfield, extruded building footprints and trees)
// and answers geometric questions about it: ground and roof heights, wall distances, ray casts and
// lines of sight.
package arena

import (
	"encoding/binary"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"os"
	"path/filepath"
)

// Block is a solid polygon footprint (possibly with holes) extruded between Bottom and Top.
type Block struct {
	Bottom, Top float64
	Outer       []float64 // x0,y0,x1,y1,...
	Holes       [][]float64
	Box         Rect
}

// Wall is one vertical face of a block.
type Wall struct {
	Ax, Ay, Bx, By float64
	Bottom, Top    float64
	Block          int32
}

// Tree is a trunk with an ellipsoid crown.
type Tree struct {
	X, Y, Z   float64 // trunk foot
	Height    float64
	CrownR    float64
	CrownBase float64
	TrunkR    float64
	CrownX    float64
	CrownY    float64
}

// Rect is an axis-aligned rectangle.
type Rect struct{ X0, Y0, X1, Y1 float64 }

// Contains reports whether the point lies inside the rectangle (edges included).
func (r Rect) Contains(x, y float64) bool { return x >= r.X0 && x <= r.X1 && y >= r.Y0 && y <= r.Y1 }

// Map is the loaded arena.
type Map struct {
	Bounds Rect

	// terrain samples on a regular lattice
	hx0, hy0, hStep float64
	hw, hh          int
	heights         []float32
	peak            float64
	tiles           tileMax

	Blocks []Block
	Walls  []Wall
	Trees  []Tree

	canopyDensity float64
	canopyCutoff  float64

	wallGrid, blockGrid, treeGrid buckets
}

type fileFormat struct {
	Bounds struct {
		MinX float64 `json:"minX"`
		MaxX float64 `json:"maxX"`
		MinY float64 `json:"minY"`
		MaxY float64 `json:"maxY"`
	} `json:"bounds"`
	Rules struct {
		CanopyDensity float64 `json:"canopyDensity"`
		CanopyBlockT  float64 `json:"canopyBlockT"`
	} `json:"rules"`
	Terrain struct {
		MinX  float64 `json:"minX"`
		MinY  float64 `json:"minY"`
		Step  float64 `json:"step"`
		NX    int     `json:"nx"`
		NY    int     `json:"ny"`
		Scale float64 `json:"scale"`
	} `json:"terrain"`
	Prisms []struct {
		Base  float64     `json:"base"`
		Top   float64     `json:"top"`
		Ring  []float64   `json:"ring"`
		Holes [][]float64 `json:"holes"`
	} `json:"prisms"`
	Trees struct {
		Fields []string  `json:"fields"`
		Data   []float64 `json:"data"`
	} `json:"trees"`
}

// Load reads the arena from <dir>/v2/world.json and <dir>/v2/terrain.i16.
func Load(dir string) (*Map, error) {
	raw, err := os.ReadFile(filepath.Join(dir, "v2", "world.json"))
	if err != nil {
		return nil, err
	}
	var f fileFormat
	if err := json.Unmarshal(raw, &f); err != nil {
		return nil, fmt.Errorf("world.json: %w", err)
	}
	m := &Map{
		Bounds:        Rect{f.Bounds.MinX, f.Bounds.MinY, f.Bounds.MaxX, f.Bounds.MaxY},
		hx0:           f.Terrain.MinX,
		hy0:           f.Terrain.MinY,
		hStep:         f.Terrain.Step,
		hw:            f.Terrain.NX,
		hh:            f.Terrain.NY,
		canopyDensity: f.Rules.CanopyDensity,
		canopyCutoff:  f.Rules.CanopyBlockT,
	}
	if m.hStep <= 0 {
		m.hStep = 1
	}
	if m.hw < 2 || m.hh < 2 {
		return nil, errors.New("terrain grid too small")
	}
	if err := m.readTerrain(filepath.Join(dir, "v2", "terrain.i16"), f.Terrain.Scale); err != nil {
		return nil, err
	}
	for _, p := range f.Prisms {
		if len(p.Ring) < 6 {
			continue
		}
		m.Blocks = append(m.Blocks, Block{Bottom: p.Base, Top: p.Top, Outer: p.Ring, Holes: p.Holes, Box: ringBox(p.Ring)})
	}
	m.Trees = decodeTrees(f.Trees.Fields, f.Trees.Data)
	m.collectWalls()
	m.buildBuckets()
	m.tiles = newTileMax(m, 16)
	return m, nil
}

func (m *Map) readTerrain(path string, scale float64) error {
	if scale == 0 {
		scale = 0.01
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	n := m.hw * m.hh
	if len(data) < 2*n {
		return fmt.Errorf("terrain.i16: %d bytes, need %d", len(data), 2*n)
	}
	m.heights = make([]float32, n)
	m.peak = math.Inf(-1)
	for i := 0; i < n; i++ {
		h := float64(int16(binary.LittleEndian.Uint16(data[2*i:]))) * scale
		m.heights[i] = float32(h)
		m.peak = math.Max(m.peak, h)
	}
	return nil
}

func ringBox(r []float64) Rect {
	b := Rect{math.Inf(1), math.Inf(1), math.Inf(-1), math.Inf(-1)}
	for i := 0; i+1 < len(r); i += 2 {
		b.X0, b.X1 = math.Min(b.X0, r[i]), math.Max(b.X1, r[i])
		b.Y0, b.Y1 = math.Min(b.Y0, r[i+1]), math.Max(b.Y1, r[i+1])
	}
	return b
}

// decodeTrees turns the column-oriented tree table into records.
func decodeTrees(fields []string, data []float64) []Tree {
	if len(fields) == 0 {
		return nil
	}
	col := make(map[string]int, len(fields))
	for i, name := range fields {
		col[name] = i
	}
	stride := len(fields)
	field := func(row int, name string) float64 {
		if c, ok := col[name]; ok {
			return data[row*stride+c]
		}
		return 0
	}
	_, hasCrownPos := col["crownX"]
	out := make([]Tree, 0, len(data)/stride)
	for row := 0; row < len(data)/stride; row++ {
		t := Tree{
			X: field(row, "x"), Y: field(row, "y"), Z: field(row, "z"),
			Height: field(row, "height"), CrownR: field(row, "crownR"), CrownBase: field(row, "crownBase"),
			TrunkR: field(row, "trunkR"), CrownX: field(row, "crownX"), CrownY: field(row, "crownY"),
		}
		if !hasCrownPos {
			t.CrownX, t.CrownY = t.X, t.Y
		}
		out = append(out, t)
	}
	return out
}

// collectWalls lists every polygon edge (outer ring and holes) as a vertical wall.
func (m *Map) collectWalls() {
	for bi := range m.Blocks {
		blk := &m.Blocks[bi]
		emit := func(ring []float64) {
			n := len(ring) / 2
			if n < 3 {
				return
			}
			for i := 0; i < n; i++ {
				j := (i + n - 1) % n
				ax, ay := ring[2*j], ring[2*j+1]
				bx, by := ring[2*i], ring[2*i+1]
				if ax == bx && ay == by {
					continue
				}
				m.Walls = append(m.Walls, Wall{ax, ay, bx, by, blk.Bottom, blk.Top, int32(bi)})
			}
		}
		emit(blk.Outer)
		for _, h := range blk.Holes {
			emit(h)
		}
	}
}

// InBounds reports whether a point is inside the playable rectangle.
func (m *Map) InBounds(x, y float64) bool { return m.Bounds.Contains(x, y) }
