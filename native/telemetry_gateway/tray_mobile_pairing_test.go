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
		Edition:          mobileEditionEnhanced,
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
	if parsed.Scheme != "https" || parsed.Host != "bomana.ruikang.wang" || parsed.Path != "/mobile/Enhanced/" || parsed.RawQuery != "handoff=bridge-tray" {
		t.Fatalf("invalid public handoff: %s", raw)
	}
	for _, privateField := range []string{"mobile-lan", "mobile-pairing", "bridge-pairing", "pairing-expires"} {
		if parsed.Query().Has(privateField) {
			t.Fatalf("public handoff query leaked %s", privateField)
		}
	}
	fragmentStart := strings.IndexByte(raw, '#')
	if fragmentStart < 0 {
		t.Fatalf("public handoff has no fragment: %s", raw)
	}
	rawFragment := raw[fragmentStart+1:]
	if strings.Contains(rawFragment, "%25") {
		t.Fatalf("public handoff fragment was percent-encoded twice: %s", rawFragment)
	}
	fragment, err := url.ParseQuery(rawFragment)
	if err != nil {
		t.Fatalf("browser could not parse handoff fragment: %v", err)
	}
	if fragment.Get("mobile-tray") != "1" || fragment.Get("mobile-pairing") != descriptor.PairingToken || fragment.Get("bridge-pairing") != descriptor.BridgePairingID {
		t.Fatalf("incomplete tray handoff fragment: %v", fragment)
	}
	if fragment.Get("mobile-lan") != "http://192.168.1.20:43123/mobile/Enhanced/" || fragment.Get("pairing-expires") != descriptor.PairingExpiresAt {
		t.Fatalf("invalid local handoff target: %v", fragment)
	}
}

func TestTrayPairingStandardQRTargetsTheLocalPublicEdition(t *testing.T) {
	descriptor := mobilePairingDescriptor{
		Edition:          mobileEditionStandard,
		BridgePairingID:  "bridge_pairing_1234567890",
		PairingToken:     strings.Repeat("a", 43),
		PairingExpiresAt: "2099-08-26T00:05:00Z",
		Networks: []mobileNetworkCandidate{{
			Interface: "Wi-Fi", Address: "192.168.1.20", Endpoint: "http://192.168.1.20:43123/",
		}},
	}
	raw := trayPairingHandoffURL(descriptor, 0)
	parsed, err := url.Parse(raw)
	if err != nil {
		t.Fatal(err)
	}
	if parsed.Scheme != "http" || parsed.Host != "192.168.1.20:43123" || parsed.Path != "/mobile/Standard/" {
		t.Fatalf("invalid Standard local target: %s", raw)
	}
	fragment, err := url.ParseQuery(parsed.Fragment)
	if err != nil {
		t.Fatal(err)
	}
	if fragment.Get("mobile-edition") != "Standard" || fragment.Get("mobile-pairing") != descriptor.PairingToken || fragment.Has("mobile-tray") {
		t.Fatalf("invalid Standard pairing fragment: %v", fragment)
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
	for _, expected := range []string{"连接手机", "普通版", "超级爆弹版", "data:image/png;base64,", "手机上登录 CheemsPay", "重新生成并撤销旧会话", `name="pairing-token" value="`} {
		if !strings.Contains(body, expected) {
			t.Fatalf("tray pairing page missing %q", expected)
		}
	}
	if strings.Contains(body, "Authorization") {
		t.Fatal("tray pairing page leaked an account authorization surface")
	}
}

func TestTrayPairingPageKeepsTheClaimedEditionUnlessTheUserSwitches(t *testing.T) {
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
	now := time.Now()
	descriptor, err := gateway.mobile.StartEdition(gateway, now, mobileEditionStandard, false)
	if err != nil {
		t.Fatal(err)
	}
	if _, result := gateway.mobile.Claim(descriptor.PairingToken, now.Add(time.Second)); result != mobilePairingCompleteOK {
		t.Fatalf("standard claim result = %v", result)
	}
	request := httptest.NewRequest(http.MethodGet, "/mobile-pairing", nil)
	request.RemoteAddr = "127.0.0.1:50100"
	response := httptest.NewRecorder()
	gateway.ServeHTTP(response, request)
	after, claimed, ok := gateway.mobile.Current(now.Add(2 * time.Second))
	if response.Code != http.StatusOK || !ok || !claimed || after.BridgePairingID != descriptor.BridgePairingID || after.Edition != mobileEditionStandard {
		t.Fatalf("opening tray changed claimed session: status=%d current=%+v claimed=%v", response.Code, after, claimed)
	}
	if !strings.Contains(response.Body.String(), "手机已连接") || !strings.Contains(response.Body.String(), "普通版") {
		t.Fatalf("claimed Standard page did not preserve its edition: %s", response.Body.String())
	}
}

func TestTrayPairingRegenerationAcceptsSameOriginOrCurrentPageTokenAndRotates(t *testing.T) {
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

	missingToken := httptest.NewRequest(http.MethodPost, "http://127.0.0.1:8878/mobile-pairing?rotate=1", nil)
	missingToken.RemoteAddr = "127.0.0.1:50102"
	missingTokenResponse := httptest.NewRecorder()
	gateway.ServeHTTP(missingTokenResponse, missingToken)
	afterMissingToken, _, _ := gateway.mobile.Current(time.Now())
	if missingTokenResponse.Code != http.StatusForbidden || afterMissingToken.BridgePairingID != first.BridgePairingID {
		t.Fatalf("missing-origin regeneration without page token = %d, session rotated=%v", missingTokenResponse.Code, afterMissingToken.BridgePairingID != first.BridgePairingID)
	}

	withoutOrigin := httptest.NewRequest(
		http.MethodPost,
		"http://127.0.0.1:8878/mobile-pairing?rotate=1",
		strings.NewReader(url.Values{"pairing-token": {first.PairingToken}}.Encode()),
	)
	withoutOrigin.RemoteAddr = "127.0.0.1:50103"
	withoutOrigin.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	withoutOriginResponse := httptest.NewRecorder()
	gateway.ServeHTTP(withoutOriginResponse, withoutOrigin)
	rotatedByToken, _, ok := gateway.mobile.Current(time.Now())
	if withoutOriginResponse.Code != http.StatusSeeOther || withoutOriginResponse.Header().Get("Location") != "/mobile-pairing" || !ok {
		t.Fatalf("page-token regeneration = %d location=%q current=%v", withoutOriginResponse.Code, withoutOriginResponse.Header().Get("Location"), ok)
	}
	if rotatedByToken.BridgePairingID == first.BridgePairingID || rotatedByToken.PairingToken == first.PairingToken {
		t.Fatal("page-token regeneration reused the old pairing capability")
	}

	staleToken := httptest.NewRequest(
		http.MethodPost,
		"http://127.0.0.1:8878/mobile-pairing?rotate=1",
		strings.NewReader(url.Values{"pairing-token": {first.PairingToken}}.Encode()),
	)
	staleToken.RemoteAddr = "127.0.0.1:50104"
	staleToken.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	staleTokenResponse := httptest.NewRecorder()
	gateway.ServeHTTP(staleTokenResponse, staleToken)
	afterStaleToken, _, _ := gateway.mobile.Current(time.Now())
	if staleTokenResponse.Code != http.StatusForbidden || afterStaleToken.BridgePairingID != rotatedByToken.BridgePairingID {
		t.Fatalf("stale page-token regeneration = %d, session rotated=%v", staleTokenResponse.Code, afterStaleToken.BridgePairingID != rotatedByToken.BridgePairingID)
	}

	regenerate := httptest.NewRequest(http.MethodPost, "http://127.0.0.1:8878/mobile-pairing?rotate=1", nil)
	regenerate.RemoteAddr = "127.0.0.1:50105"
	regenerate.Header.Set("Origin", "http://127.0.0.1:8878")
	regenerateResponse := httptest.NewRecorder()
	gateway.ServeHTTP(regenerateResponse, regenerate)
	rotated, _, ok := gateway.mobile.Current(time.Now())
	if regenerateResponse.Code != http.StatusSeeOther || regenerateResponse.Header().Get("Location") != "/mobile-pairing" || !ok {
		t.Fatalf("same-origin regeneration = %d location=%q current=%v", regenerateResponse.Code, regenerateResponse.Header().Get("Location"), ok)
	}
	if rotated.BridgePairingID == rotatedByToken.BridgePairingID || rotated.PairingToken == rotatedByToken.PairingToken {
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
	missingOrigin := httptest.NewRequest(http.MethodPost, "/api/v1/mobile/pairing/prepare", strings.NewReader(body))
	missingOrigin = missingOrigin.WithContext(context.WithValue(missingOrigin.Context(), http.LocalAddrContextKey, &net.TCPAddr{IP: net.ParseIP("192.168.1.20"), Port: gateway.mobile.port}))
	missingOrigin.Host = strings.TrimPrefix(strings.TrimSuffix(descriptor.Networks[0].Endpoint, "/"), "http://")
	missingOrigin.RemoteAddr = "192.168.1.30:50101"
	missingOriginResponse := httptest.NewRecorder()

	gateway.ServeHTTP(missingOriginResponse, missingOrigin)

	if missingOriginResponse.Code != http.StatusNoContent {
		t.Fatalf("phone tray prepare without Origin status = %d: %s", missingOriginResponse.Code, missingOriginResponse.Body.String())
	}
	nullOrigin := httptest.NewRequest(http.MethodPost, "/api/v1/mobile/pairing/prepare", strings.NewReader(body))
	nullOrigin = nullOrigin.WithContext(context.WithValue(nullOrigin.Context(), http.LocalAddrContextKey, &net.TCPAddr{IP: net.ParseIP("192.168.1.20"), Port: gateway.mobile.port}))
	nullOrigin.Host = missingOrigin.Host
	nullOrigin.RemoteAddr = "192.168.1.30:50102"
	nullOrigin.Header.Set("Origin", "null")
	nullOriginResponse := httptest.NewRecorder()

	gateway.ServeHTTP(nullOriginResponse, nullOrigin)

	if nullOriginResponse.Code != http.StatusNoContent {
		t.Fatalf("phone tray prepare with null Origin status = %d: %s", nullOriginResponse.Code, nullOriginResponse.Body.String())
	}

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
	crossOrigin := httptest.NewRequest(http.MethodPost, "/api/v1/mobile/pairing/prepare", strings.NewReader(body))
	crossOrigin = crossOrigin.WithContext(context.WithValue(crossOrigin.Context(), http.LocalAddrContextKey, &net.TCPAddr{IP: net.ParseIP("192.168.1.20"), Port: gateway.mobile.port}))
	crossOrigin.Host = request.Host
	crossOrigin.RemoteAddr = "192.168.1.30:50103"
	crossOrigin.Header.Set("Origin", "https://evil.example")
	crossOriginResponse := httptest.NewRecorder()

	gateway.ServeHTTP(crossOriginResponse, crossOrigin)

	if crossOriginResponse.Code != http.StatusForbidden {
		t.Fatalf("cross-origin phone tray prepare status = %d: %s", crossOriginResponse.Code, crossOriginResponse.Body.String())
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
