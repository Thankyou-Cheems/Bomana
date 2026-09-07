package main

import (
	"net/http"
	"strings"
	"testing"
	"time"

	"bomana/native/telemetry_gateway/internal/extui"
)

func validPort() bridgePortCheck {
	return bridgePortCheck{
		Port:         8878,
		TCPReachable: true,
		Capabilities: httpCheck{Status: http.StatusOK},
		Identity: capabilities{
			SchemaVersion:  1,
			BridgeProtocol: 1,
			CacheProtocol:  4,
			BridgeVersion:  "1.5.9",
			Input:          "official-8111-only",
		},
		Preflight: preflightCheck{
			Status:              http.StatusNoContent,
			AllowOrigin:         officialOrigin,
			AllowMethods:        "GET, OPTIONS",
			AllowPrivateNetwork: "true",
		},
		Relay8111: httpCheck{Status: http.StatusOK},
	}
}

func TestDiagnoseSeparatesBridgeBrowserAndExtUIFailures(t *testing.T) {
	tests := []struct {
		name     string
		snapshot diagnosticSnapshot
		want     string
	}{
		{name: "no listener", snapshot: diagnosticSnapshot{}, want: "BRIDGE_NOT_LISTENING"},
		{name: "wrong protocol", snapshot: diagnosticSnapshot{Ports: []bridgePortCheck{{Port: 8878, TCPReachable: true}}}, want: "BRIDGE_PROTOCOL_MISMATCH"},
		{name: "bad preflight", snapshot: diagnosticSnapshot{Ports: []bridgePortCheck{func() bridgePortCheck { value := validPort(); value.Preflight.AllowOrigin = ""; return value }()}, GameExtUI: httpCheck{Status: 200}}, want: "BRIDGE_BROWSER_PREFLIGHT_FAILED"},
		{name: "game unavailable", snapshot: diagnosticSnapshot{Ports: []bridgePortCheck{validPort()}, GameExtUI: httpCheck{Status: 0, Error: "refused"}}, want: "GAME_8111_UNAVAILABLE"},
		{name: "ExtUI state unavailable", snapshot: diagnosticSnapshot{Ports: []bridgePortCheck{validPort()}, GameExtUI: httpCheck{Status: 503}, ExtUI: extui.Snapshot{State: extui.StateReady, Port: "9222"}}, want: "GAME_EXTUI_STATE_UNAVAILABLE"},
		{name: "relay failed", snapshot: diagnosticSnapshot{Ports: []bridgePortCheck{func() bridgePortCheck { value := validPort(); value.Relay8111.Status = 502; return value }()}, GameExtUI: httpCheck{Status: 200}, ExtUI: extui.Snapshot{State: extui.StateReady, Port: "9222"}}, want: "BRIDGE_8111_RELAY_FAILED"},
		{name: "edge side", snapshot: diagnosticSnapshot{Ports: []bridgePortCheck{validPort()}, GameExtUI: httpCheck{Status: 200}, ExtUI: extui.Snapshot{State: extui.StateReady, Port: "9222"}}, want: "LOCAL_CHAIN_OK"},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			if got := diagnose(test.snapshot).Code; got != test.want {
				t.Fatalf("diagnose code = %q, want %q", got, test.want)
			}
		})
	}
}

func TestReportExcludesRaw8111ValuesAndSecrets(t *testing.T) {
	snapshot := diagnosticSnapshot{
		CapturedAt: time.Date(2026, 8, 29, 0, 0, 0, 0, time.UTC),
		Ports:      []bridgePortCheck{validPort()},
		GameExtUI:  httpCheck{Status: 200, JSONKeys: []string{"H, m", "TAS, km/h"}},
		ExtUI:      extui.Snapshot{State: extui.StateReady, Port: "9222"},
	}
	report := formatReport(snapshot, diagnose(snapshot))
	for _, forbidden := range []string{"pairing", "Authorization", "3000.0", "chat"} {
		if strings.Contains(report, forbidden) {
			t.Fatalf("report leaked forbidden value %q", forbidden)
		}
	}
	for _, expected := range []string{"LOCAL_CHAIN_OK", "game_extui_port=9222", "json_keys=H, m,TAS, km/h", "隐私说明"} {
		if !strings.Contains(report, expected) {
			t.Fatalf("report missing %q", expected)
		}
	}
}
