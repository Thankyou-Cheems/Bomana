package main

import (
	"math"
	"slices"
	"testing"
)

func flight(at int64) frame {
	return frame{At: at, IndicatorsAt: at, StateAt: at, ObjectsAt: at, MapAt: at,
		Indicators: map[string]any{"valid": true, "army": "air", "compass1": float64(0)},
		State:      map[string]any{"valid": true, "IAS, km/h": float64(500), "Vy, m/s": float64(0), "gear, %": float64(0)},
		Objects: []map[string]any{
			{"type": "player", "x": 0.5, "y": 0.5},
			{"type": "bombing_point", "id": "a", "x": 0.5, "y": 0.3},
			{"type": "bombing_point", "id": "b", "x": 0.55, "y": 0.2},
			{"type": "airfield", "side": "friendly", "sx": 0.2, "sy": 0.7, "ex": 0.2, "ey": 0.8},
			{"type": "point_of_interest", "x": 0.5, "y": 0.3},
			{"type": "aircraft", "color": "red", "x": 0.5, "y": 0.2},
		}, MapInfo: map[string]any{"valid": true, "map_min": []any{float64(-50000), float64(-50000)}, "map_max": []any{float64(50000), float64(50000)}, "grid_steps": []any{float64(10000), float64(10000)}, "hud_type": float64(0)}}
}
func running() *model {
	m := newModel(defaults())
	m.ingest(flight(1000))
	m.ingest(flight(2000))
	return m
}
func TestTimerContinuityAndGroundMarkerLoss(t *testing.T) {
	m := running()
	if got := m.snapshot(62000).Remaining; got != "14:00" {
		t.Fatal(got)
	}
	f := flight(63000)
	f.ObjectsAt = 62000
	m.ingest(f)
	if m.started != 2000 {
		t.Fatal("held route reset timer")
	}
	f = flight(64000)
	m.ingest(f)
	if m.started != 2000 {
		t.Fatal("short gap reset timer")
	}
	f = flight(65000)
	f.State["IAS, km/h"] = float64(150)
	f.State["gear, %"] = float64(100)
	m.ingest(f)
	f = flight(66000)
	f.Objects = f.Objects[1:]
	f.State["IAS, km/h"] = float64(0)
	m.ingest(f)
	if m.started != 2000 {
		t.Fatal("grounded marker loss reset timer")
	}
	f.At, f.IndicatorsAt, f.StateAt, f.ObjectsAt, f.MapAt = 100000, 100000, 100000, 100000, 100000
	m.ingest(f)
	if m.started != 2000 {
		t.Fatal("ground continuity was not retained")
	}
	f = flight(101000)
	m.ingest(f)
	if m.started != 2000 {
		t.Fatal("ground recovery reset timer")
	}
	m.Settings.Minutes = 10
	if got := m.snapshot(122000).Remaining; got != "08:00" {
		t.Fatal(got)
	}
	m.reset(122000)
	if got := m.snapshot(122000).Remaining; got != "10:00" {
		t.Fatal(got)
	}
}
func TestConfirmedLossAndOutageReset(t *testing.T) {
	for _, mode := range []string{"hangar", "airborne-loss", "outage", "ground-expiry"} {
		t.Run(mode, func(t *testing.T) {
			m := running()
			f := flight(3000)
			switch mode {
			case "hangar":
				f.Indicators["valid"] = false
			case "airborne-loss":
				f.Objects = f.Objects[1:]
			case "outage":
				m.ingest(frame{At: 3000})
				if m.started == 0 {
					t.Fatal("no grace")
				}
				f = frame{At: 15000}
			case "ground-expiry":
				f.State["IAS, km/h"] = float64(0)
				m.ingest(f)
				f = flight(4000)
				f.Objects = f.Objects[1:]
				f.State["IAS, km/h"] = float64(0)
				m.ingest(f)
				f.At, f.IndicatorsAt, f.StateAt, f.ObjectsAt, f.MapAt = 65000, 65000, 65000, 65000, 65000
			}
			m.ingest(f)
			if m.started != 0 {
				t.Fatal("timer retained after loss")
			}
		})
	}
}
func TestNavigationUsesOnlyOfficialFeaturesAndStableManualTarget(t *testing.T) {
	m := running()
	v := m.snapshot(2100)
	if !v.HasHeading || len(v.Targets) != 3 || v.Selected == nil || v.Selected.ID != "zone:a" || math.Abs(v.Selected.Distance-20) > 0.001 {
		t.Fatalf("%+v", v)
	}
	if !slices.ContainsFunc(v.Targets, func(t target) bool { return t.Friendly && t.Relative < -90 }) {
		t.Fatal("friendly runway direction missing")
	}
	m.selectedID = "zone:b"
	f := flight(2200)
	slices.Reverse(f.Objects)
	m.ingest(f)
	if m.snapshot(2200).Selected.ID != "zone:b" {
		t.Fatal("manual target changed on reorder")
	}
	f = flight(2300)
	f.Objects = append(f.Objects[:2], f.Objects[3:]...)
	m.ingest(f)
	if v = m.snapshot(2300); v.Selected != nil || v.Status != "目标已消失" {
		t.Fatal("silently changed missing manual target")
	}
}
func TestNavigationRejectsMissingAndStaleInputs(t *testing.T) {
	for _, mode := range []string{"heading", "scale", "ownship", "stale-objects", "stale-map", "invalid"} {
		t.Run(mode, func(t *testing.T) {
			m := running()
			f := flight(6000)
			switch mode {
			case "heading":
				delete(f.Indicators, "compass1")
			case "scale":
				delete(f.MapInfo, "map_max")
			case "ownship":
				f.Objects = f.Objects[1:]
			case "stale-objects":
				f.ObjectsAt = 2000
			case "stale-map":
				f.MapAt = 2000
			case "invalid":
				f.Indicators["valid"] = false
			}
			m.ingest(f)
			v := m.snapshot(6000)
			if v.HasHeading || v.Selected != nil || len(v.Targets) != 0 {
				t.Fatalf("fabricated navigation: %+v", v)
			}
		})
	}
	m := running()
	if m.snapshot(5001).HasHeading {
		t.Fatal("stale navigation visible")
	}
	f := flight(6000)
	delete(f.Indicators, "compass1")
	f.Objects[0]["dx"] = float64(1)
	f.Objects[0]["dy"] = float64(0)
	m.ingest(f)
	if m.snapshot(6000).Heading != 90 {
		t.Fatal("official direction fallback failed")
	}
}
func TestAutomaticSelectionHasHysteresis(t *testing.T) {
	m := running()
	m.snapshot(2000)
	f := flight(3000)
	f.Objects[2]["y"] = 0.4
	f.Objects[2]["x"] = 0.5
	m.ingest(f)
	if m.snapshot(3000).Selected.ID != "zone:a" {
		t.Fatal("switched on single sample")
	}
	if m.snapshot(4499).Selected.ID != "zone:a" {
		t.Fatal("switched before confirmation")
	}
	if m.snapshot(4500).Selected.ID != "zone:b" {
		t.Fatal("did not confirm better forward target")
	}
	if angle(1-359) != 2 || angle(359-1) != -2 {
		t.Fatal("heading wrap takes long route")
	}
}
func TestOfficialAliasesAffiliationAndAmbiguousPlayer(t *testing.T) {
	if friendly(map[string]any{"side": "enemy", "color": "blue"}) {
		t.Fatal("color overrode explicit side")
	}
	if !friendly(map[string]any{"color[]": []any{float64(20), float64(50), float64(220)}}) {
		t.Fatal("official RGB runway")
	}
	if friendly(map[string]any{"color": "#ee00ff"}) {
		t.Fatal("purple is not friendly blue")
	}
	f := flight(1000)
	f.Objects[0] = map[string]any{"type": "aircraft", "icon": "player", "x": 0.5, "y": 0.5}
	f.Objects = append(f.Objects, map[string]any{"type": "aircraft", "icon": "player", "x": 0.7, "y": 0.7})
	if own, _ := objects(f.Objects); own != nil {
		t.Fatal("ambiguous player chosen")
	}
	f.Objects[0]["color"] = "yellow"
	if own, _ := objects(f.Objects); own == nil {
		t.Fatal("explicit player preference")
	}
}
