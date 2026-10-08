package main

import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"testing"
	"time"
)

func TestTimerReadWithoutTrustedOriginDoesNotClaimDesktop(t *testing.T) {
	upstream, _ := url.Parse("http://127.0.0.1:8111")
	for _, origin := range []string{"", "https://evil.example", "https://bomana.ruikang.wang"} {
		gateway := newRelay(upstream, "https://bomana.ruikang.wang")
		request := httptest.NewRequest(http.MethodGet, "/api/v1/presentation/timer", nil)
		request.RemoteAddr = "127.0.0.1:54321"
		if origin != "" {
			request.Header.Set("Origin", origin)
		}
		response := httptest.NewRecorder()
		gateway.ServeHTTP(response, request)
		trusted := origin == "https://bomana.ruikang.wang"
		if !gateway.presentation.desktopSeenAt.IsZero() != trusted {
			t.Fatalf("origin %q claimed desktop incorrectly", origin)
		}
		if origin == "" && response.Code != 200 {
			t.Fatalf("originless read must remain supported: %d", response.Code)
		}
		if origin == "https://evil.example" && response.Code != 403 {
			t.Fatalf("untrusted origin accepted: %d", response.Code)
		}
	}
}

func TestTimerReentryDoesNotClaimPriorContinuity(t *testing.T) {
	upstream, _ := url.Parse("http://127.0.0.1:8111")
	for _, gap := range []time.Duration{time.Second, 6 * time.Second, 16 * time.Minute} {
		t.Run(gap.String(), func(t *testing.T) {
			gateway := newRelay(upstream, "https://bomana.ruikang.wang")
			state := gateway.presentation
			state.timer = &timerProjection{Active: true, ElapsedSec: 120, CycleSeconds: 900, LifeIndex: 1}
			state.timerAt = state.startedAt
			state.timerRevision = 1
			state.timerReaderSeenAt = time.Now().Add(-gap)
			request := httptest.NewRequest(http.MethodGet, "/api/v1/presentation/timer", nil)
			request.Header.Set("Origin", gateway.allowedOrigin)
			response := httptest.NewRecorder()
			gateway.ServeHTTP(response, request)
			var result timerPresentation
			if err := json.Unmarshal(response.Body.Bytes(), &result); err != nil {
				t.Fatal(err)
			}
			if result.ReadersPresent != (gap < 5*time.Second) {
				t.Fatalf("presence renewed by incoming request: %+v", result)
			}
			if (result.Timer == nil) != (gap > 15*time.Minute) {
				t.Fatalf("unexpected timer expiry: %+v", result)
			}
			if gap > 15*time.Minute && result.Revision != 2 {
				t.Fatal("expiry must invalidate outstanding writes")
			}
		})
	}
}

func TestTimerPresentationSnapshotAndCompareAndSwap(t *testing.T) {
	upstream, _ := url.Parse("http://127.0.0.1:8111")
	gateway := newRelay(upstream, "https://bomana.ruikang.wang")
	read := func() map[string]any {
		request := httptest.NewRequest(http.MethodGet, "/api/v1/presentation/timer", nil)
		request.Header.Set("Origin", "https://bomana.ruikang.wang")
		response := httptest.NewRecorder()
		gateway.ServeHTTP(response, request)
		if response.Code != 200 {
			t.Fatalf("read status=%d: %s", response.Code, response.Body.String())
		}
		var state map[string]any
		if err := json.Unmarshal(response.Body.Bytes(), &state); err != nil {
			t.Fatal(err)
		}
		return state
	}
	initial := read()
	if initial["timer"] != nil || initial["revision"] != float64(0) || initial["desktop_present"] != true {
		t.Fatalf("initial state: %v", initial)
	}
	write := func(epoch any, revision any, payload string) *httptest.ResponseRecorder {
		body := fmt.Sprintf(`{"schema_version":1,"epoch":%q,"expected_revision":%v,"timer":%s}`, epoch, revision, payload)
		request := httptest.NewRequest(http.MethodPut, "/api/v1/presentation/timer", strings.NewReader(body))
		request.Header.Set("Origin", "https://bomana.ruikang.wang")
		response := httptest.NewRecorder()
		gateway.ServeHTTP(response, request)
		return response
	}
	payload := `{"active":true,"elapsed_sec":120,"cycle_seconds":900,"life_index":1}`
	if response := write(initial["epoch"], initial["revision"], payload); response.Code != 200 {
		t.Fatalf("write status=%d: %s", response.Code, response.Body.String())
	}
	state := read()
	if state["revision"] != float64(1) || state["timer"].(map[string]any)["elapsed_sec"] != float64(120) {
		t.Fatalf("state=%v", state)
	}
	if response := write(initial["epoch"], 0, payload); response.Code != 409 {
		t.Fatalf("stale revision status=%d", response.Code)
	}
	if response := write("old-bridge", 1, payload); response.Code != 409 {
		t.Fatalf("stale epoch status=%d", response.Code)
	}
	if response := write(state["epoch"], 1, `{"active":true,"elapsed_sec":-1,"cycle_seconds":900,"life_index":1}`); response.Code != 400 {
		t.Fatalf("negative elapsed status=%d", response.Code)
	}
	if response := write(state["epoch"], 1, `{"active":true,"elapsed_sec":0,"cycle_seconds":1,"life_index":1}`); response.Code != 400 {
		t.Fatalf("unbounded cycle status=%d", response.Code)
	}
	for _, invalid := range []string{
		`{"active":true,"elapsed_sec":0,"cycle_seconds":900,"life_index":0}`,
		`{"active":false,"elapsed_sec":1,"cycle_seconds":900,"life_index":1}`,
		`{"active":true,"elapsed_sec":604801,"cycle_seconds":900,"life_index":1}`,
		`{"active":true,"elapsed_sec":0,"cycle_seconds":900,"life_index":1,"extra":true}`,
		payload + `} {"extra":true`,
	} {
		if response := write(state["epoch"], 1, invalid); response.Code != 400 {
			t.Fatalf("invalid projection %q status=%d", invalid, response.Code)
		}
	}
	if got := read()["revision"]; got != float64(1) {
		t.Fatalf("rejected writes must not mutate revision: %v", got)
	}
	request := httptest.NewRequest(http.MethodPut, "/api/v1/presentation/timer", strings.NewReader(payload))
	request.Header.Set("Origin", "https://untrusted.example")
	response := httptest.NewRecorder()
	gateway.ServeHTTP(response, request)
	if response.Code != 403 {
		t.Fatalf("untrusted writer status=%d", response.Code)
	}
}
