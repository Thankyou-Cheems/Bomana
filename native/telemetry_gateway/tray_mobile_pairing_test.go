package main

import (
	"context"
	"encoding/json"
	"net"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strconv"
	"strings"
	"testing"
	"time"
)

func TestTrayPairingHandoffKeepsPrivateDetailsInFragment(t *testing.T) {
	descriptor := mobilePairingDescriptor{
		BridgePairingID:  "bridge_pairing_1234567890",
		PairingToken:     strings.Repeat("a", 43),
		PairingExpiresAt: "2099-08-26T00:05:00Z",
		ExpiresAt:        "2099-08-26T08:00:00Z",
		Networks: []mobileNetworkCandidate{
			{Interface: "Wi-Fi", Address: "192.168.1.20", Endpoint: "http://192.168.1.20:43123/"},
		},
	}
	raw := trayPairingHandoffURL(descriptor, 0)
	parsed, err := url.Parse(raw)
	if err != nil {
		t.Fatal(err)
	}
	if parsed.Scheme != "https" || parsed.Host != "bomana.ruikang.wang" || parsed.Path != "/mobile/Enhanced/" || parsed.RawQuery != "" {
		t.Fatalf("invalid public handoff: %s", raw)
	}
	fragment, _ := url.ParseQuery(parsed.Fragment)
	if fragment.Get("mobile-tray") != "1" || fragment.Get("mobile-pairing") != descriptor.PairingToken || fragment.Get("bridge-pairing") != descriptor.BridgePairingID {
		t.Fatalf("incomplete tray handoff fragment: %v", fragment)
	}
	if fragment.Get("mobile-lan") != "http://192.168.1.20:43123/mobile/Enhanced/" || fragment.Get("pairing-expires") != descriptor.PairingExpiresAt {
		t.Fatalf("invalid local handoff target: %v", fragment)
	}
}

func TestTrayPairingPageCreatesQRWithoutDesktopWebAuthorization(t *testing.T) {
	gateway := newRelay(mustURL("http://127.0.0.1:8111"), testOrigin)
	gateway.mobile.listen = func(network, _ string) (net.Listener, error) {
		return net.Listen(network, "127.0.0.1:0")
	}
	gateway.mobile.networks = func(httpPort, tlsPort int) ([]mobileNetworkCandidate, error) {
		return []mobileNetworkCandidate{{
			Interface: "Wi-Fi", Address: "192.168.1.20",
			Endpoint:    "http://192.168.1.20:" + strconv.Itoa(httpPort) + "/",
			TLSEndpoint: "https://192.168.1.20:" + strconv.Itoa(tlsPort) + "/",
		}}, nil
	}
	t.Cleanup(func() { _ = gateway.mobile.Close() })
	request := httptest.NewRequest(http.MethodGet, "/mobile-pairing", nil)
	request.RemoteAddr = "127.0.0.1:50100"
	response := httptest.NewRecorder()

	gateway.ServeHTTP(response, request)

	if response.Code != http.StatusOK {
		t.Fatalf("tray pairing page status = %d: %s", response.Code, response.Body.String())
	}
	body := response.Body.String()
	for _, expected := range []string{"连接手机", "data:image/png;base64,", "手机上登录 CheemsPay", "重新生成并撤销旧会话"} {
		if !strings.Contains(body, expected) {
			t.Fatalf("tray pairing page missing %q", expected)
		}
	}
	if strings.Contains(body, "Authorization") {
		t.Fatal("tray pairing page leaked an account authorization surface")
	}
}

func TestTrayPairingRegenerationRequiresSameOriginPostAndRotates(t *testing.T) {
	gateway := newRelay(mustURL("http://127.0.0.1:8111"), testOrigin)
	gateway.mobile.listen = func(network, _ string) (net.Listener, error) {
		return net.Listen(network, "127.0.0.1:0")
	}
	gateway.mobile.networks = func(httpPort, tlsPort int) ([]mobileNetworkCandidate, error) {
		return []mobileNetworkCandidate{{
			Interface: "Wi-Fi", Address: "192.168.1.20",
			Endpoint:    "http://192.168.1.20:" + strconv.Itoa(httpPort) + "/",
			TLSEndpoint: "https://192.168.1.20:" + strconv.Itoa(tlsPort) + "/",
		}}, nil
	}
	t.Cleanup(func() { _ = gateway.mobile.Close() })

	open := httptest.NewRequest(http.MethodGet, "http://127.0.0.1:8878/mobile-pairing", nil)
	open.RemoteAddr = "127.0.0.1:50100"
	openResponse := httptest.NewRecorder()
	gateway.ServeHTTP(openResponse, open)
	first, _, ok := gateway.mobile.Current(time.Now())
	if openResponse.Code != http.StatusOK || !ok {
		t.Fatalf("initial tray pairing = %d, current=%v", openResponse.Code, ok)
	}

	crossOrigin := httptest.NewRequest(http.MethodPost, "http://127.0.0.1:8878/mobile-pairing?rotate=1", nil)
	crossOrigin.RemoteAddr = "127.0.0.1:50101"
	crossOrigin.Header.Set("Origin", "https://bomana.ruikang.wang")
	crossOriginResponse := httptest.NewRecorder()
	gateway.ServeHTTP(crossOriginResponse, crossOrigin)
	afterRejected, _, _ := gateway.mobile.Current(time.Now())
	if crossOriginResponse.Code != http.StatusForbidden || afterRejected.BridgePairingID != first.BridgePairingID {
		t.Fatalf("cross-origin regeneration = %d, session rotated=%v", crossOriginResponse.Code, afterRejected.BridgePairingID != first.BridgePairingID)
	}

	regenerate := httptest.NewRequest(http.MethodPost, "http://127.0.0.1:8878/mobile-pairing?rotate=1", nil)
	regenerate.RemoteAddr = "127.0.0.1:50102"
	regenerate.Header.Set("Origin", "http://127.0.0.1:8878")
	regenerateResponse := httptest.NewRecorder()
	gateway.ServeHTTP(regenerateResponse, regenerate)
	rotated, _, ok := gateway.mobile.Current(time.Now())
	if regenerateResponse.Code != http.StatusSeeOther || regenerateResponse.Header().Get("Location") != "/mobile-pairing" || !ok {
		t.Fatalf("same-origin regeneration = %d location=%q current=%v", regenerateResponse.Code, regenerateResponse.Header().Get("Location"), ok)
	}
	if rotated.BridgePairingID == first.BridgePairingID || rotated.PairingToken == first.PairingToken {
		t.Fatal("same-origin regeneration reused the old pairing capability")
	}
}

func TestPhoneMayPrepareTrayPairingFromTheSelectedLANOrigin(t *testing.T) {
	now := time.Now()
	gateway := newRelay(mustURL("http://127.0.0.1:8111"), testOrigin)
	gateway.mobile.listen = func(network, _ string) (net.Listener, error) {
		return net.Listen(network, "127.0.0.1:0")
	}
	gateway.mobile.networks = func(httpPort, tlsPort int) ([]mobileNetworkCandidate, error) {
		return []mobileNetworkCandidate{{
			Interface: "Wi-Fi", Address: "192.168.1.20",
			Endpoint:    "http://192.168.1.20:" + strconv.Itoa(httpPort) + "/",
			TLSEndpoint: "https://192.168.1.20:" + strconv.Itoa(tlsPort) + "/",
		}}, nil
	}
	t.Cleanup(func() { _ = gateway.mobile.Close() })
	descriptor, err := gateway.mobile.Start(gateway, now)
	if err != nil {
		t.Fatal(err)
	}
	leaseExpiresAt := now.Add(7 * time.Hour)
	trustMobileLeaseForTest(gateway.mobile, leaseExpiresAt)
	payload, _ := json.Marshal(map[string]any{
		"schema_version":          1,
		"bridge_pairing_id":       descriptor.BridgePairingID,
		"pairing_token":           descriptor.PairingToken,
		"mobile_lease":            "signed-mobile-lease",
		"mobile_lease_expires_at": leaseExpiresAt.UTC().Format(time.RFC3339Nano),
		"pairing_expires_at":      now.Add(4 * time.Minute).UTC().Format(time.RFC3339),
	})
	body := string(payload)
	request := httptest.NewRequest(http.MethodPost, "/api/v1/mobile/pairing/prepare", strings.NewReader(body))
	request = request.WithContext(context.WithValue(request.Context(), http.LocalAddrContextKey, &net.TCPAddr{IP: net.ParseIP("192.168.1.20"), Port: gateway.mobile.port}))
	request.Host = strings.TrimPrefix(strings.TrimSuffix(descriptor.Networks[0].Endpoint, "/"), "http://")
	request.RemoteAddr = "192.168.1.30:50102"
	request.Header.Set("Origin", descriptor.Networks[0].Endpoint[:len(descriptor.Networks[0].Endpoint)-1])
	response := httptest.NewRecorder()

	gateway.ServeHTTP(response, request)

	if response.Code != http.StatusNoContent {
		t.Fatalf("phone tray prepare status = %d: %s", response.Code, response.Body.String())
	}
	if gateway.mobile.Authorize(descriptor.PairingToken, now.Add(time.Second)) {
		t.Fatal("prepare authorized APIs before the one-time phone claim")
	}
}

func mustURL(raw string) *url.URL {
	value, err := url.Parse(raw)
	if err != nil {
		panic(err)
	}
	return value
}
