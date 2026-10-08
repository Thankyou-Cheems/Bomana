package main

import (
	"encoding/json"
	"io"
	"math"
	"net/http"
	"time"
)

// An opaque, bounded App presentation. Bridge supplies transport sequence and
// a monotonic clock; it never observes or decides spawn/death/reset semantics.
type timerProjection struct {
	Active       bool    `json:"active"`
	ElapsedSec   float64 `json:"elapsed_sec"`
	CycleSeconds int     `json:"cycle_seconds"`
	LifeIndex    int     `json:"life_index"`
}
type timerPresentation struct {
	SchemaVersion  int              `json:"schema_version"`
	Epoch          string           `json:"epoch"`
	Revision       uint64           `json:"revision"`
	ServerNowMs    int64            `json:"server_now_ms"`
	AnchorAtMs     int64            `json:"anchor_at_ms"`
	DesktopPresent bool             `json:"desktop_present"`
	Timer          *timerProjection `json:"timer"`
	ReadersPresent bool             `json:"readers_present"`
}

func (state *presentationState) timerSnapshot(now time.Time, readersPresent bool) timerPresentation {
	anchor := int64(0)
	if state.timer != nil {
		anchor = state.timerAt.Sub(state.startedAt).Milliseconds()
	}
	return timerPresentation{1, state.timerEpoch, state.timerRevision, now.Sub(state.startedAt).Milliseconds(), anchor,
		!state.desktopSeenAt.IsZero() && now.Sub(state.desktopSeenAt) < 5*time.Second, state.timer, readersPresent}
}
func (gateway *relay) serveTimerPresentation(response http.ResponseWriter, request *http.Request) {
	response.Header().Set("Cache-Control", "no-store")
	if request.Method == http.MethodOptions {
		if !gateway.allowOrigin(response, request) {
			http.Error(response, "origin forbidden", 403)
			return
		}
		response.Header().Set("Access-Control-Allow-Methods", "GET, PUT, OPTIONS")
		response.Header().Set("Access-Control-Allow-Headers", "Accept, Content-Type, X-Bomana-Mobile-Pairing")
		gateway.allowPrivateNetwork(response, request)
		response.WriteHeader(204)
		return
	}
	if request.Method != http.MethodGet && request.Method != http.MethodPut {
		response.Header().Set("Allow", "GET, PUT, OPTIONS")
		http.Error(response, "method not allowed", 405)
		return
	}
	if request.Method == http.MethodPut {
		if !gateway.requireBrowserOrigin(response, request) {
			http.Error(response, "origin forbidden", 403)
			return
		}
	} else if !gateway.allowOrigin(response, request) {
		http.Error(response, "origin forbidden", 403)
		return
	}
	var payload struct {
		SchemaVersion    int              `json:"schema_version"`
		Epoch            string           `json:"epoch"`
		ExpectedRevision uint64           `json:"expected_revision"`
		Timer            *timerProjection `json:"timer"`
	}
	if request.Method == http.MethodPut {
		decoder := json.NewDecoder(http.MaxBytesReader(response, request.Body, 1024))
		decoder.DisallowUnknownFields()
		if err := decoder.Decode(&payload); err != nil || payload.SchemaVersion != 1 || payload.Timer == nil {
			http.Error(response, "timer presentation rejected", 400)
			return
		}
		if err := decoder.Decode(&struct{}{}); err != io.EOF {
			http.Error(response, "timer presentation rejected", 400)
			return
		}
		timer := payload.Timer
		if math.IsNaN(timer.ElapsedSec) || math.IsInf(timer.ElapsedSec, 0) || timer.ElapsedSec < 0 || timer.ElapsedSec > 7*24*60*60 ||
			timer.CycleSeconds < 60 || timer.CycleSeconds > 180*60 || timer.CycleSeconds%60 != 0 ||
			timer.LifeIndex < 0 || timer.LifeIndex > 1000000 || timer.Active && timer.LifeIndex == 0 || !timer.Active && timer.ElapsedSec != 0 {
			http.Error(response, "timer presentation rejected", 400)
			return
		}
	}
	state := gateway.presentation
	state.mu.Lock()
	defer state.mu.Unlock()
	now := time.Now()
	// Report presence BEFORE registering this request: a new page must not
	// make an abandoned timer look continuously observed merely by reading it.
	readersPresent := !state.timerReaderSeenAt.IsZero() && now.Sub(state.timerReaderSeenAt) < 5*time.Second
	if state.timer != nil && (state.timerReaderSeenAt.IsZero() || now.Sub(state.timerReaderSeenAt) > 15*time.Minute) {
		state.timer = nil
		state.timerRevision++
	}
	if gateway.usesPairingListener(request) || request.Header.Get("Origin") == gateway.allowedOrigin {
		state.timerReaderSeenAt = now
	}
	if !gateway.usesPairingListener(request) && request.Header.Get("Origin") == gateway.allowedOrigin {
		state.desktopSeenAt = now
	}
	response.Header().Set("Content-Type", "application/json")
	if request.Method == http.MethodPut {
		if payload.Epoch != state.timerEpoch || payload.ExpectedRevision != state.timerRevision {
			response.WriteHeader(http.StatusConflict)
			_ = json.NewEncoder(response).Encode(state.timerSnapshot(now, readersPresent))
			return
		}
		state.timer = payload.Timer
		state.timerAt = now
		state.timerRevision++
	}
	_ = json.NewEncoder(response).Encode(state.timerSnapshot(now, readersPresent))
}
