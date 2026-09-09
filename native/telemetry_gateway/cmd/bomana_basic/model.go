package main

import (
	"fmt"
	"math"
	"slices"
	"sort"
	"strconv"
	"strings"
)

type point struct{ X, Y float64 }
type target struct {
	ID, Label, Kind             string
	Position                    point
	Friendly                    bool
	Distance, Bearing, Relative float64
}
type frame struct {
	At, IndicatorsAt, StateAt, ObjectsAt, MapAt int64
	Indicators, State, MapInfo                  map[string]any
	Objects                                     []map[string]any
}
type settings struct {
	Background, Text, Icons int
	Minutes                 int
	Border                  bool
	Width                   int
	X, Y                    int
	Positioned              bool
}

func defaults() settings {
	return settings{Background: 35, Text: 100, Icons: 100, Minutes: 15, Width: 560}
}
func (s *settings) normalize() {
	d := defaults()
	for _, value := range []*int{&s.Background, &s.Text, &s.Icons} {
		*value = max(0, min(100, *value))
	}
	if s.Minutes < 1 || s.Minutes > 180 {
		s.Minutes = d.Minutes
	}
	if s.Width < 360 || s.Width > 1600 {
		s.Width = d.Width
	}
}

type view struct {
	Heading           float64
	HasHeading        bool
	Targets           []target
	Selected          *target
	Status, Remaining string
	Cycle             int
	Progress          float64
}
type model struct {
	Settings                                              settings
	last                                                  frame
	started, candidate, missing, lastPlayerAt, groundedAt int64
	lastGround, lastApproach                              bool
	mapID, selectedID, autoID, pendingID                  string
	pendingAt                                             int64
}

func newModel(s settings) *model { s.normalize(); return &model{Settings: s} }
func (m *model) reset(now int64) { m.started = now; m.candidate = 0 }
func (m *model) ingest(f frame) {
	m.last = f
	_, id, mapOK := mapScale(f.MapInfo)
	if mapOK && id != m.mapID {
		if m.mapID != "" {
			m.started, m.candidate = 0, 0
			m.selectedID, m.autoID = "", ""
		}
		m.mapID = id
	}
	own, _ := objects(f.Objects)
	stateValid := f.State != nil && f.State["valid"] != false
	entity := f.Indicators["valid"] == true
	fresh := f.ObjectsAt == f.At && f.IndicatorsAt == f.At && f.StateAt == f.At
	if !fresh {
		m.candidate = 0
		if m.missing == 0 {
			m.missing = f.At
		}
		if f.At-m.missing >= 12_000 {
			m.started = 0
		}
		return
	}
	m.missing = 0
	ias, iasOK := number(f.State, "IAS, km/h", "IAS", "ias")
	vy, vyOK := number(f.State, "Vy, m/s", "Vy", "vy")
	gear, _ := number(f.State, "gear, %", "gear")
	ground := stateValid && iasOK && vyOK && ias < 40 && math.Abs(vy) < 2
	if own != nil && entity && stateValid {
		m.groundedAt = 0
		m.lastPlayerAt, m.lastGround = f.At, ground
		m.lastApproach = iasOK && vyOK && gear >= 50 && ias <= 180 && math.Abs(vy) <= 8
		if m.started == 0 {
			if m.candidate == 0 {
				m.candidate = f.At
			}
			if f.At-m.candidate >= 1000 {
				m.started, m.candidate = f.At, 0
			}
		}
		return
	}
	m.candidate = 0
	if m.started > 0 && own == nil && entity && ground {
		qualified := m.groundedAt > 0 && f.At-m.groundedAt <= 60_000 || m.lastPlayerAt > 0 && f.At-m.lastPlayerAt <= 1500 && (m.lastGround || m.lastApproach)
		if qualified {
			if m.groundedAt == 0 {
				m.groundedAt = f.At
			}
			return
		}
	}
	m.started, m.groundedAt = 0, 0
}
func (m *model) snapshot(now int64) view {
	v := view{Status: "等待游戏", Remaining: "--:--"}
	if m.started > 0 {
		elapsed := max(0, float64(now-m.started)/1000)
		period := float64(m.Settings.Minutes * 60)
		remaining := period - math.Mod(elapsed, period)
		seconds := int(math.Ceil(remaining))
		v.Remaining, v.Cycle, v.Progress = fmt.Sprintf("%02d:%02d", seconds/60, seconds%60), int(elapsed/period)+1, 1-remaining/period
	}
	f := m.last
	if f.At == 0 || now-f.At > 3000 || f.IndicatorsAt == 0 || now-f.IndicatorsAt > 3000 || f.Indicators["valid"] != true {
		return v
	}
	v.Status = "等待导航"
	if m.missing > 0 {
		v.Status = "数据暂断"
	}
	if f.ObjectsAt == 0 || now-f.ObjectsAt > 3000 || f.MapAt == 0 || now-f.MapAt > 3000 {
		return v
	}
	own, items := objects(f.Objects)
	scale, _, ok := mapScale(f.MapInfo)
	if own == nil || !ok {
		return v
	}
	hdg, hasHeading := number(f.Indicators, "compass1", "compass", "compass1, deg", "compass, deg")
	if !hasHeading {
		dx, xOK := number(own, "dx")
		dy, yOK := number(own, "dy")
		if xOK && yOK && math.Hypot(dx, dy) > 0.000001 {
			hdg, hasHeading = math.Atan2(dx, -dy)*180/math.Pi, true
		}
	}
	if !hasHeading {
		return v
	}
	p, _ := position(own)
	v.Heading, v.HasHeading = heading(hdg), true
	for i := range items {
		t := &items[i]
		dx, dy := (t.Position.X-p.X)*scale.X, (t.Position.Y-p.Y)*scale.Y
		t.Distance = math.Hypot(dx, dy) / 1000
		t.Bearing = heading(math.Atan2(dx, -dy) * 180 / math.Pi)
		t.Relative = angle(t.Bearing - v.Heading)
	}
	sort.SliceStable(items, func(i, j int) bool { return items[i].Distance < items[j].Distance })
	v.Targets = items
	id := m.selectedID
	if id == "" {
		id = m.choose(items, now)
	}
	for i := range items {
		if items[i].ID == id {
			v.Selected = &items[i]
			break
		}
	}
	if v.Selected != nil {
		v.Status = v.Selected.Label
	} else if m.selectedID != "" {
		v.Status = "目标已消失"
	} else {
		v.Status = "前方无目标"
	}
	return v
}
func (m *model) choose(items []target, now int64) string {
	bestID := ""
	best, current := math.Inf(1), math.Inf(1)
	for _, t := range items {
		if math.Abs(t.Relative) > 65 {
			continue
		}
		score := t.Distance * (1 + math.Abs(t.Relative)/30)
		if t.ID == m.autoID {
			current = score
		}
		if score < best {
			bestID, best = t.ID, score
		}
	}
	if bestID == "" {
		m.autoID, m.pendingID = "", ""
		return ""
	}
	if math.IsInf(current, 1) {
		m.autoID, m.pendingID = bestID, ""
		return bestID
	}
	if bestID == m.autoID || best >= current*0.85 {
		m.pendingID = ""
		return m.autoID
	}
	if m.pendingID != bestID {
		m.pendingID, m.pendingAt = bestID, now
	}
	if now-m.pendingAt >= 1500 {
		m.autoID, m.pendingID = bestID, ""
	}
	return m.autoID
}
func heading(v float64) float64 { return math.Mod(math.Mod(v, 360)+360, 360) }
func angle(v float64) float64   { return heading(v+180) - 180 }
func number(o map[string]any, keys ...string) (float64, bool) {
	for _, k := range keys {
		var v float64
		var ok bool
		switch raw := o[k].(type) {
		case float64:
			v, ok = raw, true
		case string:
			var err error
			v, err = strconv.ParseFloat(raw, 64)
			ok = err == nil
		}
		if ok && !math.IsNaN(v) && !math.IsInf(v, 0) {
			return v, true
		}
	}
	return 0, false
}
func text(o map[string]any, key string) string { s, _ := o[key].(string); return strings.ToLower(s) }
func position(o map[string]any) (point, bool) {
	x, a := number(o, "x", "X", "pos_x", "position_x")
	y, b := number(o, "y", "Y", "pos_y", "position_y")
	return point{x, y}, a && b && x >= 0 && x <= 1 && y >= 0 && y <= 1
}
func playerRank(o map[string]any) int {
	for _, k := range []string{"is_player", "player", "is_self", "self"} {
		if o[k] == true {
			return 3
		}
	}
	typ, icon := text(o, "type"), text(o, "icon")
	if typ == "player" || typ == "player_aircraft" {
		return 3
	}
	if (typ == "aircraft" || typ == "plane") && (strings.Contains(icon, "player") || text(o, "name") == "player" || text(o, "label") == "player") {
		color := text(o, "color")
		if strings.Contains(color, "yellow") || strings.Contains(color, "gold") || strings.Contains(color, "amber") {
			return 2
		}
		return 1
	}
	return 0
}
func friendly(o map[string]any) bool {
	for _, k := range []string{"friendly", "is_friendly"} {
		if o[k] == true {
			return true
		}
	}
	for _, key := range []string{"side", "team", "army"} {
		side := text(o, key)
		if slices.Contains([]string{"enemy", "hostile", "red", "team_b", "2"}, side) {
			return false
		}
		if slices.Contains([]string{"friendly", "ally", "allied", "blue", "team_a", "1"}, side) {
			return true
		}
	}
	if strings.Contains(text(o, "color"), "blue") {
		return true
	}
	if c, ok := o["color[]"].([]any); ok && len(c) >= 3 {
		r, a := c[0].(float64)
		g, y := c[1].(float64)
		b, z := c[2].(float64)
		return a && y && z && b <= 255 && r >= 0 && g >= 0 && b-r >= 48 && b-g >= 48
	}
	color := strings.Replace(text(o, "color"), "0x", "#", 1)
	if len(color) == 7 && color[0] == '#' {
		r, a := strconv.ParseUint(color[1:3], 16, 8)
		g, y := strconv.ParseUint(color[3:5], 16, 8)
		b, z := strconv.ParseUint(color[5:7], 16, 8)
		return a == nil && y == nil && z == nil && b >= r+48 && b >= g+48
	}
	return false
}
func objects(records []map[string]any) (map[string]any, []target) {
	var own map[string]any
	rank, count := 0, 0
	for _, o := range records {
		r := playerRank(o)
		if r == 1 {
			count++
		}
		if _, ok := position(o); ok && r > rank {
			own, rank = o, r
		}
	}
	if rank == 1 && count != 1 {
		own = nil
	}
	items := []target{}
	for _, o := range records {
		if playerRank(o) > 0 {
			continue
		}
		typ, icon := text(o, "type"), text(o, "icon")
		kind := ""
		if typ == "airfield" || typ == "airport" || typ == "runway" || icon == "airfield" || icon == "airport" || icon == "runway" {
			kind = "airfield"
		} else if slices.Contains([]string{"bombing_point", "bombingpoint", "bombing point", "bomb_target", "bomb_target_point"}, typ) || strings.Contains(icon, "bombing") || strings.Contains(icon, "bomb_target") {
			kind = "zone"
		}
		if kind == "" {
			continue
		}
		p, ok := position(o)
		if kind == "airfield" {
			sx, a := number(o, "sx", "start_x", "runway_start_x")
			sy, b := number(o, "sy", "start_y", "runway_start_y")
			ex, c := number(o, "ex", "end_x", "runway_end_x")
			ey, d := number(o, "ey", "end_y", "runway_end_y")
			if a && b && c && d {
				p = point{(sx + ex) / 2, (sy + ey) / 2}
				ok = p.X >= 0 && p.X <= 1 && p.Y >= 0 && p.Y <= 1
			}
		}
		if !ok {
			continue
		}
		id := fmt.Sprintf("%s:%.6f:%.6f", kind, p.X, p.Y)
		for _, k := range []string{"id", "uid", "object_id"} {
			if s, yes := o[k].(string); yes && s != "" {
				id = kind + ":" + s
				break
			}
			if n, yes := number(o, k); yes {
				id = fmt.Sprintf("%s:%g", kind, n)
				break
			}
		}
		items = append(items, target{ID: id, Kind: kind, Position: p, Friendly: kind == "airfield" && friendly(o)})
	}
	sort.Slice(items, func(i, j int) bool { return items[i].ID < items[j].ID })
	counts := map[string]int{}
	for i := range items {
		t := &items[i]
		name := "战区"
		if t.Kind == "airfield" {
			name = "机场"
			if t.Friendly {
				name = "友方机场"
			}
		}
		counts[name]++
		t.Label = fmt.Sprintf("%s %d", name, counts[name])
	}
	return own, items
}
func mapScale(info map[string]any) (point, string, bool) {
	if info == nil || info["valid"] == false {
		return point{}, "", false
	}
	lo, a := info["map_min"].([]any)
	hi, b := info["map_max"].([]any)
	if !a || !b || len(lo) != 2 || len(hi) != 2 {
		return point{}, "", false
	}
	v := make([]float64, 4)
	for i, raw := range []any{lo[0], lo[1], hi[0], hi[1]} {
		n, ok := raw.(float64)
		if !ok || math.IsNaN(n) || math.IsInf(n, 0) {
			return point{}, "", false
		}
		v[i] = n
	}
	p := point{v[2] - v[0], v[3] - v[1]}
	if p.X <= 0 || p.Y <= 0 {
		return point{}, "", false
	}
	return p, fmt.Sprint(v), true
}
