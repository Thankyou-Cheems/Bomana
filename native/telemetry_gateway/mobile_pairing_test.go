package main

import (
	"bytes"
	"context"
	"crypto/tls"
	"encoding/json"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strconv"
	"strings"
	"testing"
	"time"
)

func TestMobilePairingCodePreparesAndClaimsOnePhoneSession(t *testing.T) {
	upstreamURL, _ := url.Parse("http://127.0.0.1:8111")
	gateway := newRelay(upstreamURL, testOrigin)
	gateway.mobile.listen = func(network, _ string) (net.Listener, error) {
		return net.Listen(network, "127.0.0.1:0")
	}
	gateway.mobile.networks = func(httpPort, tlsPort int) ([]mobileNetworkCandidate, error) {
		return []mobileNetworkCandidate{{Interface: "Wi-Fi", Address: "192.168.1.20", Endpoint: "http://192.168.1.20:" + strconv.Itoa(httpPort) + "/", TLSEndpoint: "https://192.168.1.20:" + strconv.Itoa(tlsPort) + "/"}}, nil
	}
	t.Cleanup(func() { _ = gateway.mobile.Close() })

	start := httptest.NewRequest(http.MethodPost, "/api/v1/mobile/pairing/start", nil)
	start.RemoteAddr = "127.0.0.1:50100"
	start.Header.Set("Origin", testOrigin)
	startResponse := httptest.NewRecorder()
	gateway.ServeHTTP(startResponse, start)
	if startResponse.Code != http.StatusCreated {
		t.Fatalf("pairing start status = %d: %s", startResponse.Code, startResponse.Body.String())
	}
	var descriptor map[string]any
	if err := json.Unmarshal(startResponse.Body.Bytes(), &descriptor); err != nil {
		t.Fatal(err)
	}
	pairingCode, _ := descriptor["pairing_code"].(string)
	if pairingCode == "" {
		t.Fatal("pairing start did not return a human pairing code")
	}
	if descriptor["mobile_pairing_protocol"] != float64(6) {
		t.Fatalf("pairing protocol = %v", descriptor["mobile_pairing_protocol"])
	}

	trustMobileLeaseForTest(gateway.mobile, time.Date(2099, 8, 26, 8, 0, 0, 0, time.UTC))
	prepareBody := []byte(`{"schema_version":1,"bridge_pairing_id":"` + descriptor["bridge_pairing_id"].(string) + `","pairing_token":"` + descriptor["pairing_token"].(string) + `","mobile_lease":"signed-mobile-lease","mobile_lease_expires_at":"2099-08-26T08:00:00Z","pairing_expires_at":"2099-08-26T00:05:00Z"}`)
	prepare := httptest.NewRequest(http.MethodPost, "/api/v1/mobile/pairing/prepare", bytes.NewReader(prepareBody))
	prepare.RemoteAddr = "127.0.0.1:50101"
	prepare.Header.Set("Origin", testOrigin)
	prepare.Header.Set("Content-Type", "application/json")
	prepareResponse := httptest.NewRecorder()
	gateway.ServeHTTP(prepareResponse, prepare)
	if prepareResponse.Code != http.StatusNoContent {
		t.Fatalf("pairing prepare status = %d: %s", prepareResponse.Code, prepareResponse.Body.String())
	}

	httpOrigin := strings.TrimSuffix(descriptor["networks"].([]any)[0].(map[string]any)["endpoint"].(string), "/")
	completeBody := []byte(`{"schema_version":1,"pairing_code":"` + pairingCode + `"}`)
	crossOriginComplete := httptest.NewRequest(http.MethodPost, "/api/v1/mobile/pairing/complete", bytes.NewReader(completeBody))
	crossOriginComplete = crossOriginComplete.WithContext(context.WithValue(crossOriginComplete.Context(), http.LocalAddrContextKey, &net.TCPAddr{IP: net.ParseIP("192.168.1.20"), Port: gateway.mobile.port}))
	crossOriginComplete.Host = strings.TrimPrefix(httpOrigin, "http://")
	crossOriginComplete.RemoteAddr = "192.168.1.30:50102"
	crossOriginComplete.Header.Set("Origin", testOrigin)
	crossOriginComplete.Header.Set("Content-Type", "application/json")
	crossOriginCompleteResponse := httptest.NewRecorder()
	gateway.ServeHTTP(crossOriginCompleteResponse, crossOriginComplete)
	if crossOriginCompleteResponse.Code != http.StatusForbidden {
		t.Fatalf("cross-origin pairing complete status = %d: %s", crossOriginCompleteResponse.Code, crossOriginCompleteResponse.Body.String())
	}

	complete := httptest.NewRequest(http.MethodPost, "/api/v1/mobile/pairing/complete", bytes.NewReader(completeBody))
	complete = complete.WithContext(context.WithValue(complete.Context(), http.LocalAddrContextKey, &net.TCPAddr{IP: net.ParseIP("192.168.1.20"), Port: gateway.mobile.port}))
	complete.Host = strings.TrimPrefix(httpOrigin, "http://")
	complete.RemoteAddr = "192.168.1.30:50102"
	complete.Header.Set("Origin", httpOrigin)
	complete.Header.Set("Content-Type", "application/json")
	completeResponse := httptest.NewRecorder()
	gateway.ServeHTTP(completeResponse, complete)
	if completeResponse.Code != http.StatusOK {
		t.Fatalf("pairing complete status = %d: %s", completeResponse.Code, completeResponse.Body.String())
	}
	var completed map[string]any
	if err := json.Unmarshal(completeResponse.Body.Bytes(), &completed); err != nil {
		t.Fatal(err)
	}
	if completed["mobile_lease"] != "signed-mobile-lease" || completed["pairing_token"] != descriptor["pairing_token"] {
		t.Fatalf("pairing completion did not return prepared session: %+v", completed)
	}

	replay := httptest.NewRequest(http.MethodPost, "/api/v1/mobile/pairing/complete", bytes.NewReader(completeBody))
	replay = replay.WithContext(context.WithValue(replay.Context(), http.LocalAddrContextKey, &net.TCPAddr{IP: net.ParseIP("192.168.1.20"), Port: gateway.mobile.port}))
	replay.Host = strings.TrimPrefix(httpOrigin, "http://")
	replay.RemoteAddr = "192.168.1.31:50103"
	replay.Header.Set("Origin", httpOrigin)
	replay.Header.Set("Content-Type", "application/json")
	replayResponse := httptest.NewRecorder()
	gateway.ServeHTTP(replayResponse, replay)
	if replayResponse.Code != http.StatusGone {
		t.Fatalf("pairing code replay status = %d: %s", replayResponse.Code, replayResponse.Body.String())
	}
}

func TestMobilePairingQRCodeClaimsWhenSafariOmitsOrigin(t *testing.T) {
	upstreamURL, _ := url.Parse("http://127.0.0.1:8111")
	gateway := newRelay(upstreamURL, testOrigin)
	gateway.mobile.listen = func(network, _ string) (net.Listener, error) {
		return net.Listen(network, "127.0.0.1:0")
	}
	gateway.mobile.networks = func(httpPort, tlsPort int) ([]mobileNetworkCandidate, error) {
		return []mobileNetworkCandidate{{Interface: "Wi-Fi", Address: "192.168.1.20", Endpoint: "http://192.168.1.20:" + strconv.Itoa(httpPort) + "/", TLSEndpoint: "https://192.168.1.20:" + strconv.Itoa(tlsPort) + "/"}}, nil
	}
	t.Cleanup(func() { _ = gateway.mobile.Close() })

	now := time.Now()
	descriptor, err := gateway.mobile.Start(gateway, now)
	if err != nil {
		t.Fatal(err)
	}
	leaseExpiresAt := now.Add(7 * time.Hour)
	trustMobileLeaseForTest(gateway.mobile, leaseExpiresAt)
	if err := gateway.mobile.Prepare(descriptor.BridgePairingID, descriptor.PairingToken, "signed-mobile-lease", leaseExpiresAt, now.Add(4*time.Minute), now); err != nil {
		t.Fatal(err)
	}
	if gateway.mobile.Authorize(descriptor.PairingToken, now) {
		t.Fatal("QR claim token authorized LAN APIs before one-time claim")
	}

	requestOnPairingListener := func(body []byte) *http.Request {
		request := httptest.NewRequest(http.MethodPost, "/api/v1/mobile/pairing/complete", bytes.NewReader(body))
		request = request.WithContext(context.WithValue(request.Context(), http.LocalAddrContextKey, &net.TCPAddr{IP: net.ParseIP("192.168.1.20"), Port: gateway.mobile.port}))
		request.Host = strings.TrimPrefix(strings.TrimSuffix(descriptor.Networks[0].Endpoint, "/"), "http://")
		request.RemoteAddr = "192.168.1.30:50102"
		request.Header.Set("Content-Type", "application/json")
		return request
	}

	codeWithoutOrigin := requestOnPairingListener([]byte(`{"schema_version":1,"pairing_code":"` + descriptor.PairingCode + `"}`))
	codeWithoutOrigin.Header.Set("Origin", "null")
	codeResponse := httptest.NewRecorder()
	gateway.ServeHTTP(codeResponse, codeWithoutOrigin)
	if codeResponse.Code != http.StatusForbidden {
		t.Fatalf("low-entropy code without trusted origin status = %d: %s", codeResponse.Code, codeResponse.Body.String())
	}

	claim := requestOnPairingListener([]byte(`{"schema_version":1,"pairing_token":"` + descriptor.PairingToken + `"}`))
	claim.Header.Set("Origin", "null")
	claimResponse := httptest.NewRecorder()
	gateway.ServeHTTP(claimResponse, claim)
	if claimResponse.Code != http.StatusOK {
		t.Fatalf("Safari QR claim status = %d: %s", claimResponse.Code, claimResponse.Body.String())
	}
	if !gateway.mobile.Authorize(descriptor.PairingToken, now.Add(time.Second)) {
		t.Fatal("claimed QR token did not authorize the paired LAN session")
	}
}

func TestMobilePairingCodeLimitsGuessesPerClient(t *testing.T) {
	manager := newMobilePairingManager()
	manager.listen = func(network, _ string) (net.Listener, error) {
		return net.Listen(network, "127.0.0.1:0")
	}
	manager.networks = func(httpPort, tlsPort int) ([]mobileNetworkCandidate, error) {
		return []mobileNetworkCandidate{{Interface: "Wi-Fi", Address: "192.168.1.20", Endpoint: "http://192.168.1.20:" + strconv.Itoa(httpPort) + "/", TLSEndpoint: "https://192.168.1.20:" + strconv.Itoa(tlsPort) + "/"}}, nil
	}
	t.Cleanup(func() { _ = manager.Close() })
	now := time.Now()
	descriptor, err := manager.Start(http.NotFoundHandler(), now)
	if err != nil {
		t.Fatal(err)
	}
	leaseExpiresAt := now.Add(7 * time.Hour)
	trustMobileLeaseForTest(manager, leaseExpiresAt)
	if err := manager.Prepare(descriptor.BridgePairingID, descriptor.PairingToken, "signed-mobile-lease", leaseExpiresAt, now.Add(4*time.Minute), now); err != nil {
		t.Fatal(err)
	}
	for attempt := 0; attempt < mobilePairingAttemptLimit; attempt++ {
		if _, result := manager.Complete("192.168.1.30", "WRONG-2345", now.Add(time.Duration(attempt)*time.Millisecond)); result != mobilePairingCompleteInvalid {
			t.Fatalf("attempt %d result = %v", attempt+1, result)
		}
	}
	if _, result := manager.Complete("192.168.1.30", descriptor.PairingCode, now.Add(time.Second)); result != mobilePairingCompleteRateLimited {
		t.Fatalf("rate-limited client result = %v", result)
	}
	if _, result := manager.Complete("192.168.1.31", descriptor.PairingCode, now.Add(time.Second)); result != mobilePairingCompleteOK {
		t.Fatalf("independent client could not claim valid code: %v", result)
	}
}

func TestMobilePairingPrepareIgnoresTheCallerDeclaredLeaseExpiry(t *testing.T) {
	now := time.Date(2026, 8, 29, 12, 0, 0, 0, time.UTC)
	verifiedExpiry := now.Add(time.Hour)
	manager := newMobilePairingManager()
	manager.session = &mobilePairingSession{
		id:            "bridge_pairing_1234567890",
		token:         strings.Repeat("a", 43),
		code:          "ABCD2345",
		codeExpiresAt: now.Add(5 * time.Minute),
		expiresAt:     now.Add(8 * time.Hour),
		failures:      make(map[string][]time.Time),
	}
	trustMobileLeaseForTest(manager, verifiedExpiry)

	err := manager.Prepare(
		manager.session.id,
		manager.session.token,
		"signed-mobile-lease",
		now.Add(2*time.Hour),
		now.Add(4*time.Minute),
		now,
	)
	if err != nil {
		t.Fatal(err)
	}
	if !manager.session.expiresAt.Equal(verifiedExpiry) || !manager.session.mobileLeaseExpiry.Equal(verifiedExpiry) {
		t.Fatal("paired session did not use the verified lease expiry")
	}
}

func TestMobilePairingStartReusesTheVisibleUnclaimedCode(t *testing.T) {
	manager := newMobilePairingManager()
	manager.listen = func(network, _ string) (net.Listener, error) {
		return net.Listen(network, "127.0.0.1:0")
	}
	manager.networks = func(httpPort, tlsPort int) ([]mobileNetworkCandidate, error) {
		return []mobileNetworkCandidate{{Interface: "Wi-Fi", Address: "192.168.1.20", Endpoint: "http://192.168.1.20:" + strconv.Itoa(httpPort) + "/", TLSEndpoint: "https://192.168.1.20:" + strconv.Itoa(tlsPort) + "/"}}, nil
	}
	t.Cleanup(func() { _ = manager.Close() })
	now := time.Now()
	first, err := manager.Start(http.NotFoundHandler(), now)
	if err != nil {
		t.Fatal(err)
	}
	second, err := manager.Start(http.NotFoundHandler(), now.Add(time.Second))
	if err != nil {
		t.Fatal(err)
	}
	if second.BridgePairingID != first.BridgePairingID || second.PairingToken != first.PairingToken || second.PairingCode != first.PairingCode {
		t.Fatalf("visible unclaimed pairing rotated: first=%+v second=%+v", first, second)
	}
}

func TestMobilePairingExplicitRotationRevokesTheVisibleOffer(t *testing.T) {
	manager := newMobilePairingManager()
	manager.listen = func(network, _ string) (net.Listener, error) {
		return net.Listen(network, "127.0.0.1:0")
	}
	manager.networks = func(httpPort, tlsPort int) ([]mobileNetworkCandidate, error) {
		return []mobileNetworkCandidate{{Interface: "Wi-Fi", Address: "192.168.1.20", Endpoint: "http://192.168.1.20:" + strconv.Itoa(httpPort) + "/", TLSEndpoint: "https://192.168.1.20:" + strconv.Itoa(tlsPort) + "/"}}, nil
	}
	t.Cleanup(func() { _ = manager.Close() })
	now := time.Now()
	first, err := manager.Start(http.NotFoundHandler(), now)
	if err != nil {
		t.Fatal(err)
	}
	rotated, err := manager.Start(http.NotFoundHandler(), now.Add(time.Second), true)
	if err != nil {
		t.Fatal(err)
	}
	if rotated.BridgePairingID == first.BridgePairingID || rotated.PairingToken == first.PairingToken || rotated.PairingCode == first.PairingCode {
		t.Fatalf("explicit rotation reused visible offer: first=%+v rotated=%+v", first, rotated)
	}
}

func TestMobilePairingRotateRouteReturnsFreshMaterial(t *testing.T) {
	upstreamURL, _ := url.Parse("http://127.0.0.1:8111")
	gateway := newRelay(upstreamURL, testOrigin)
	gateway.mobile.listen = func(network, _ string) (net.Listener, error) {
		return net.Listen(network, "127.0.0.1:0")
	}
	gateway.mobile.networks = func(httpPort, tlsPort int) ([]mobileNetworkCandidate, error) {
		return []mobileNetworkCandidate{{Interface: "Wi-Fi", Address: "192.168.1.20", Endpoint: "http://192.168.1.20:" + strconv.Itoa(httpPort) + "/", TLSEndpoint: "https://192.168.1.20:" + strconv.Itoa(tlsPort) + "/"}}, nil
	}
	t.Cleanup(func() { _ = gateway.mobile.Close() })
	request := func(path string) mobilePairingDescriptor {
		req := httptest.NewRequest(http.MethodPost, path, nil)
		req.RemoteAddr = "127.0.0.1:50100"
		req.Header.Set("Origin", testOrigin)
		response := httptest.NewRecorder()
		gateway.ServeHTTP(response, req)
		if response.Code != http.StatusCreated {
			t.Fatalf("%s status = %d: %s", path, response.Code, response.Body.String())
		}
		var descriptor mobilePairingDescriptor
		if err := json.Unmarshal(response.Body.Bytes(), &descriptor); err != nil {
			t.Fatal(err)
		}
		return descriptor
	}
	first := request("/api/v1/mobile/pairing/start")
	rotated := request("/api/v1/mobile/pairing/rotate")
	if first.BridgePairingID == rotated.BridgePairingID || first.PairingCode == rotated.PairingCode {
		t.Fatalf("rotate route reused material: first=%+v rotated=%+v", first, rotated)
	}
}

func TestMobilePairingReusesOneTokenAcrossLANEndpointsUntilCodeExpiry(t *testing.T) {
	manager := newMobilePairingManager()
	manager.listen = func(network, _ string) (net.Listener, error) {
		return net.Listen(network, "127.0.0.1:0")
	}
	manager.networks = func(httpPort, tlsPort int) ([]mobileNetworkCandidate, error) {
		return []mobileNetworkCandidate{
			{Interface: "Wi-Fi", Address: "192.168.1.20", Endpoint: "http://192.168.1.20:" + strconv.Itoa(httpPort) + "/", TLSEndpoint: "https://192.168.1.20:" + strconv.Itoa(tlsPort) + "/"},
			{Interface: "Ethernet", Address: "10.0.0.20", Endpoint: "http://10.0.0.20:" + strconv.Itoa(httpPort) + "/", TLSEndpoint: "https://10.0.0.20:" + strconv.Itoa(tlsPort) + "/"},
		}, nil
	}
	t.Cleanup(func() { _ = manager.Close() })
	now := time.Date(2026, 8, 26, 0, 0, 0, 0, time.UTC)
	first, err := manager.Start(http.NotFoundHandler(), now)
	if err != nil {
		t.Fatal(err)
	}
	if len(first.Networks) != 2 || manager.Authorize(first.PairingToken, now) {
		t.Fatalf("invalid first pairing: %+v", first)
	}
	if !strings.HasPrefix(first.Networks[0].TLSEndpoint, "https://192.168.1.20:") {
		t.Fatalf("missing TLS endpoint: %+v", first.Networks[0])
	}
	second, err := manager.Start(http.NotFoundHandler(), now.Add(time.Minute))
	if err != nil {
		t.Fatal(err)
	}
	if first.BridgePairingID != second.BridgePairingID || first.PairingToken != second.PairingToken || first.PairingCode != second.PairingCode {
		t.Fatal("active visible pairing was unexpectedly rotated")
	}
	third, err := manager.Start(http.NotFoundHandler(), now.Add(mobilePairingCodeDuration))
	if err != nil {
		t.Fatal(err)
	}
	if third.BridgePairingID == first.BridgePairingID || third.PairingToken == first.PairingToken {
		t.Fatal("expired pairing identity or token was reused")
	}
	if manager.Authorize(first.PairingToken, now.Add(mobilePairingCodeDuration)) || manager.Authorize(third.PairingToken, now.Add(mobilePairingCodeDuration)) {
		t.Fatal("expired pairing rotation did not revoke the old token")
	}
	if manager.Authorize(third.PairingToken, now.Add(mobilePairingCodeDuration+mobilePairingSessionDuration)) {
		t.Fatal("pairing token remained valid at its absolute expiry")
	}
}

func TestRemoteBridgeRequestsRequireTheActiveMobilePairingToken(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, _ *http.Request) {
		response.Header().Set("Content-Type", "application/json")
		_, _ = response.Write([]byte(`{"H, m":3000}`))
	}))
	defer upstream.Close()
	upstreamURL, _ := url.Parse(upstream.URL)
	gateway := newRelay(upstreamURL, testOrigin)
	gateway.mobile.listen = func(network, _ string) (net.Listener, error) {
		return net.Listen(network, "127.0.0.1:0")
	}
	gateway.mobile.networks = func(httpPort, tlsPort int) ([]mobileNetworkCandidate, error) {
		return []mobileNetworkCandidate{{Interface: "Wi-Fi", Address: "192.168.1.20", Endpoint: "http://192.168.1.20:" + strconv.Itoa(httpPort) + "/", TLSEndpoint: "https://192.168.1.20:" + strconv.Itoa(tlsPort) + "/"}}, nil
	}
	t.Cleanup(func() { _ = gateway.mobile.Close() })

	start := httptest.NewRequest(http.MethodPost, "/api/v1/mobile/pairing/start", nil)
	start.RemoteAddr = "127.0.0.1:50100"
	start.Header.Set("Origin", testOrigin)
	startResponse := httptest.NewRecorder()
	gateway.ServeHTTP(startResponse, start)
	if startResponse.Code != http.StatusCreated {
		t.Fatalf("pairing start status = %d: %s", startResponse.Code, startResponse.Body.String())
	}
	remoteStart := httptest.NewRequest(http.MethodPost, "/api/v1/mobile/pairing/start", nil)
	remoteStart.RemoteAddr = "192.168.1.30:50100"
	remoteStart.Header.Set("Origin", testOrigin)
	remoteStartResponse := httptest.NewRecorder()
	gateway.ServeHTTP(remoteStartResponse, remoteStart)
	if remoteStartResponse.Code != http.StatusForbidden {
		t.Fatalf("remote pairing start status = %d", remoteStartResponse.Code)
	}
	var descriptor mobilePairingDescriptor
	if err := jsonDecode(startResponse.Body.Bytes(), &descriptor); err != nil {
		t.Fatal(err)
	}
	now := time.Now()
	leaseExpiresAt := now.Add(7 * time.Hour)
	trustMobileLeaseForTest(gateway.mobile, leaseExpiresAt)
	if err := gateway.mobile.Prepare(descriptor.BridgePairingID, descriptor.PairingToken, "signed-mobile-lease", leaseExpiresAt, now.Add(4*time.Minute), now); err != nil {
		t.Fatal(err)
	}
	if _, result := gateway.mobile.Claim(descriptor.PairingToken, now); result != mobilePairingCompleteOK {
		t.Fatalf("pairing claim result = %v", result)
	}

	request := httptest.NewRequest(http.MethodGet, "/api/v1/8111/state", nil)
	request = request.WithContext(context.WithValue(request.Context(), http.LocalAddrContextKey, &net.TCPAddr{IP: net.ParseIP("192.168.1.20"), Port: 9000}))
	request.RemoteAddr = "192.168.1.30:50101"
	request.Header.Set("Origin", testOrigin)
	request.Header.Set("X-Bomana-Mobile-Pairing", descriptor.PairingToken)
	response := httptest.NewRecorder()
	gateway.ServeHTTP(response, request)
	if response.Code != http.StatusOK {
		t.Fatalf("paired request status = %d: %s", response.Code, response.Body.String())
	}

	weaponWrite := httptest.NewRequest(http.MethodPut, "/api/v1/presentation/weapon-selection", strings.NewReader(`{"schema_version":1,"selected_weapon_id":"gbu_39"}`))
	weaponWrite = weaponWrite.WithContext(context.WithValue(weaponWrite.Context(), http.LocalAddrContextKey, &net.TCPAddr{IP: net.ParseIP("192.168.1.20"), Port: 9000}))
	weaponWrite.RemoteAddr = "192.168.1.30:50101"
	weaponWrite.Header.Set("Origin", testOrigin)
	weaponWrite.Header.Set("Content-Type", "application/json")
	weaponWrite.Header.Set("X-Bomana-Mobile-Pairing", descriptor.PairingToken)
	weaponWriteResponse := httptest.NewRecorder()
	gateway.ServeHTTP(weaponWriteResponse, weaponWrite)
	if weaponWriteResponse.Code != http.StatusOK || !strings.Contains(weaponWriteResponse.Body.String(), `"selected_weapon_id":"gbu_39"`) {
		t.Fatalf("paired weapon write status = %d: %s", weaponWriteResponse.Code, weaponWriteResponse.Body.String())
	}

	wrong := httptest.NewRequest(http.MethodGet, "/api/v1/8111/state", nil)
	wrong = wrong.WithContext(context.WithValue(wrong.Context(), http.LocalAddrContextKey, &net.TCPAddr{IP: net.ParseIP("192.168.1.20"), Port: 9000}))
	wrong.RemoteAddr = "192.168.1.30:50102"
	wrong.Header.Set("Origin", testOrigin)
	wrong.Header.Set("X-Bomana-Mobile-Pairing", "wrong")
	wrongResponse := httptest.NewRecorder()
	gateway.ServeHTTP(wrongResponse, wrong)
	if wrongResponse.Code != http.StatusUnauthorized {
		t.Fatalf("wrong token status = %d", wrongResponse.Code)
	}

	preflight := httptest.NewRequest(http.MethodOptions, "/api/v1/8111/state", nil)
	preflight = preflight.WithContext(context.WithValue(preflight.Context(), http.LocalAddrContextKey, &net.TCPAddr{IP: net.ParseIP("192.168.1.20"), Port: 9000}))
	preflight.RemoteAddr = "192.168.1.30:50103"
	preflight.Header.Set("Origin", testOrigin)
	preflight.Header.Set("Access-Control-Request-Private-Network", "true")
	preflight.Header.Set("Access-Control-Request-Headers", "x-bomana-mobile-pairing")
	preflightResponse := httptest.NewRecorder()
	gateway.ServeHTTP(preflightResponse, preflight)
	if preflightResponse.Code != http.StatusNoContent ||
		preflightResponse.Header().Get("Access-Control-Allow-Private-Network") != "true" {
		t.Fatalf("mobile preflight failed: %d %+v", preflightResponse.Code, preflightResponse.Header())
	}
	if preflightResponse.Header().Get("Access-Control-Allow-Origin") != testOrigin {
		t.Fatalf("mobile preflight origin = %q", preflightResponse.Header().Get("Access-Control-Allow-Origin"))
	}
	allowedHeaders := strings.ToLower(preflightResponse.Header().Get("Access-Control-Allow-Headers"))
	if !strings.Contains(allowedHeaders, "x-bomana-mobile-pairing") {
		t.Fatalf("mobile preflight headers = %q", preflightResponse.Header().Get("Access-Control-Allow-Headers"))
	}

	for _, path := range []string{"/api/v1/capabilities", "/api/v1/8111/state", "/api/v1/8111/indicators", "/api/v1/8111/map-objects"} {
		options := httptest.NewRequest(http.MethodOptions, path, nil)
		options = options.WithContext(context.WithValue(options.Context(), http.LocalAddrContextKey, &net.TCPAddr{IP: net.ParseIP("192.168.1.20"), Port: 9000}))
		options.RemoteAddr = "192.168.1.30:50104"
		options.Header.Set("Origin", testOrigin)
		options.Header.Set("Access-Control-Request-Private-Network", "true")
		options.Header.Set("Access-Control-Request-Headers", "accept, x-bomana-mobile-pairing")
		optionsResponse := httptest.NewRecorder()
		gateway.ServeHTTP(optionsResponse, options)
		if optionsResponse.Code != http.StatusNoContent ||
			optionsResponse.Header().Get("Access-Control-Allow-Origin") != testOrigin ||
			optionsResponse.Header().Get("Access-Control-Allow-Private-Network") != "true" ||
			!strings.Contains(strings.ToLower(optionsResponse.Header().Get("Access-Control-Allow-Headers")), "x-bomana-mobile-pairing") {
			t.Fatalf("%s phone preflight failed: %d %+v", path, optionsResponse.Code, optionsResponse.Header())
		}

		get := httptest.NewRequest(http.MethodGet, path, nil)
		get = get.WithContext(context.WithValue(get.Context(), http.LocalAddrContextKey, &net.TCPAddr{IP: net.ParseIP("192.168.1.20"), Port: 9000}))
		get.RemoteAddr = "192.168.1.30:50105"
		get.Header.Set("Origin", testOrigin)
		get.Header.Set("Accept", "application/json")
		get.Header.Set("X-Bomana-Mobile-Pairing", descriptor.PairingToken)
		getResponse := httptest.NewRecorder()
		gateway.ServeHTTP(getResponse, get)
		if getResponse.Code != http.StatusOK {
			t.Fatalf("%s paired GET status = %d: %s", path, getResponse.Code, getResponse.Body.String())
		}
		if getResponse.Header().Get("Access-Control-Allow-Origin") != testOrigin {
			t.Fatalf("%s paired GET origin = %q", path, getResponse.Header().Get("Access-Control-Allow-Origin"))
		}
	}

	httpOrigin := strings.TrimSuffix(descriptor.Networks[0].Endpoint, "/")
	httpCockpit := httptest.NewRequest(http.MethodGet, "/api/v1/capabilities", nil)
	httpCockpit = httpCockpit.WithContext(context.WithValue(httpCockpit.Context(), http.LocalAddrContextKey, &net.TCPAddr{IP: net.ParseIP("192.168.1.20"), Port: gateway.mobile.port}))
	httpCockpit.RemoteAddr = "192.168.1.30:50106"
	httpCockpit.Header.Set("Origin", httpOrigin)
	httpCockpit.Header.Set("X-Bomana-Mobile-Pairing", descriptor.PairingToken)
	httpCockpitResponse := httptest.NewRecorder()
	gateway.ServeHTTP(httpCockpitResponse, httpCockpit)
	if httpCockpitResponse.Code != http.StatusOK {
		t.Fatalf("HTTP cockpit same-origin request = %d: %s", httpCockpitResponse.Code, httpCockpitResponse.Body.String())
	}
	if httpCockpitResponse.Header().Get("Access-Control-Allow-Origin") != httpOrigin {
		t.Fatalf("HTTP cockpit origin = %q", httpCockpitResponse.Header().Get("Access-Control-Allow-Origin"))
	}
}

func TestMobilePairingHTTPSCockpitServesCurrentOfficialAssets(t *testing.T) {
	cdn := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		switch request.URL.Path {
		case "/mobile/Enhanced/", "/mobile/Enhanced":
			response.Header().Set("Content-Type", "text/html; charset=utf-8")
			_, _ = io.WriteString(response, `<!doctype html><html><head><script type="module" src="./assets/app-1.5.9.js"></script></head><body>mobile-1.5.9</body></html>`)
		case "/mobile/Enhanced/assets/app-1.5.9.js":
			response.Header().Set("Content-Type", "text/javascript")
			_, _ = io.WriteString(response, "window.BOMANA_MOBILE_BUILD='1.5.9';")
		case "/mobile/Enhanced/assets/solver.worker-test.js":
			response.Header().Set("Content-Type", "text/javascript")
			_, _ = io.WriteString(response, "self.onmessage=()=>fetch('./guided-catalog-test.json');")
		case "/mobile/Enhanced/assets/guided-catalog-test.json":
			response.Header().Set("Content-Type", "application/json")
			_, _ = io.WriteString(response, `{"catalog":"guided"}`)
		case "/mobile/Enhanced/assets/powered-weapon-catalog-test.json":
			response.Header().Set("Content-Type", "application/json")
			_, _ = io.WriteString(response, `{"catalog":"powered"}`)
		case "/mobile/Enhanced/assets/ballistic-bomb-catalog-test.json":
			response.Header().Set("Content-Type", "application/json")
			_, _ = io.WriteString(response, `{"catalog":"ballistic"}`)
		case "/mobile/Enhanced/assets/solver-kernel-test.wasm":
			response.Header().Set("Content-Type", "application/wasm")
			_, _ = response.Write([]byte{0x00, 0x61, 0x73, 0x6d})
		default:
			http.NotFound(response, request)
		}
	}))
	defer cdn.Close()
	upstream := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, _ *http.Request) {
		response.Header().Set("Content-Type", "application/json")
		_, _ = response.Write([]byte(`{"ok":true}`))
	}))
	defer upstream.Close()
	upstreamURL, _ := url.Parse(upstream.URL)
	gateway := newRelay(upstreamURL, testOrigin)
	gateway.mobilePageClient = cdn.Client()
	originalBase := mobileAppBase
	t.Cleanup(func() { mobileAppBase = originalBase })
	mobileAppBase = cdn.URL + "/mobile/Enhanced/"
	gateway.mobile.listen = func(network, _ string) (net.Listener, error) {
		return net.Listen(network, "127.0.0.1:0")
	}
	t.Cleanup(func() { _ = gateway.mobile.Close() })

	now := time.Now()
	descriptor, err := gateway.mobile.Start(gateway, now)
	if err != nil {
		t.Fatal(err)
	}
	leaseExpiresAt := now.Add(7 * time.Hour)
	trustMobileLeaseForTest(gateway.mobile, leaseExpiresAt)
	if err := gateway.mobile.Prepare(descriptor.BridgePairingID, descriptor.PairingToken, "signed-mobile-lease", leaseExpiresAt, now.Add(4*time.Minute), now); err != nil {
		t.Fatal(err)
	}
	if _, result := gateway.mobile.Claim(descriptor.PairingToken, now); result != mobilePairingCompleteOK {
		t.Fatalf("pairing claim result = %v", result)
	}
	if descriptor.Networks[0].TLSEndpoint == "" {
		t.Fatal("TLS endpoint missing")
	}
	_, tlsPort, err := net.SplitHostPort(strings.TrimPrefix(strings.TrimSuffix(descriptor.Networks[0].TLSEndpoint, "/"), "https://"))
	if err != nil {
		t.Fatal(err)
	}
	client := &http.Client{Transport: &http.Transport{TLSClientConfig: &tls.Config{InsecureSkipVerify: true}}}
	page, err := client.Get("https://127.0.0.1:" + tlsPort + "/mobile/Enhanced/")
	if err != nil {
		t.Fatal(err)
	}
	defer page.Body.Close()
	body, _ := io.ReadAll(page.Body)
	if page.StatusCode != http.StatusOK || !strings.Contains(string(body), `src="./assets/app-1.5.9.js"`) || !strings.Contains(string(body), "mobile-1.5.9") {
		t.Fatalf("cockpit page = %d %s", page.StatusCode, body)
	}
	if strings.Contains(string(body), "<base ") {
		t.Fatalf("pairing page must stay same-origin, got base tag: %s", body)
	}

	script, err := client.Get("https://127.0.0.1:" + tlsPort + "/mobile/Enhanced/assets/app-1.5.9.js")
	if err != nil {
		t.Fatal(err)
	}
	defer script.Body.Close()
	scriptBody, _ := io.ReadAll(script.Body)
	if script.StatusCode != http.StatusOK || !strings.Contains(string(scriptBody), "1.5.9") {
		t.Fatalf("hashed asset = %d %s", script.StatusCode, scriptBody)
	}
	for _, asset := range []struct {
		path        string
		contentType string
		contains    string
	}{
		{"solver.worker-test.js", "text/javascript", "guided-catalog-test"},
		{"guided-catalog-test.json", "application/json", "guided"},
		{"powered-weapon-catalog-test.json", "application/json", "powered"},
		{"ballistic-bomb-catalog-test.json", "application/json", "ballistic"},
		{"solver-kernel-test.wasm", "application/wasm", "asm"},
	} {
		response, assetErr := client.Get("https://127.0.0.1:" + tlsPort + "/mobile/Enhanced/assets/" + asset.path)
		if assetErr != nil {
			t.Fatal(assetErr)
		}
		assetBody, _ := io.ReadAll(response.Body)
		_ = response.Body.Close()
		if response.StatusCode != http.StatusOK || !strings.HasPrefix(response.Header.Get("Content-Type"), asset.contentType) || !strings.Contains(string(assetBody), asset.contains) {
			t.Fatalf("solver asset %s = %d %q %q", asset.path, response.StatusCode, response.Header.Get("Content-Type"), assetBody)
		}
		if strings.Contains(asset.path, "worker") {
			policy := response.Header.Get("Content-Security-Policy")
			if !strings.Contains(policy, "connect-src 'self'") || !strings.Contains(policy, "script-src 'self'") || !strings.Contains(policy, "'wasm-unsafe-eval'") {
				t.Fatalf("worker CSP blocks solver assets: %q", policy)
			}
		}
	}

	traversal, err := client.Get("https://127.0.0.1:" + tlsPort + "/mobile/Enhanced/../launcher/")
	if err != nil {
		t.Fatal(err)
	}
	defer traversal.Body.Close()
	if traversal.StatusCode != http.StatusNotFound && traversal.StatusCode != http.StatusUnauthorized {
		t.Fatalf("path traversal status = %d", traversal.StatusCode)
	}

	capabilities, err := http.NewRequest(http.MethodGet, "https://127.0.0.1:"+tlsPort+"/api/v1/capabilities", nil)
	if err != nil {
		t.Fatal(err)
	}
	capabilities.Header.Set("X-Bomana-Mobile-Pairing", descriptor.PairingToken)
	capabilityResponse, err := client.Do(capabilities)
	if err != nil {
		t.Fatal(err)
	}
	defer capabilityResponse.Body.Close()
	if capabilityResponse.StatusCode != http.StatusOK {
		t.Fatalf("same-origin TLS capabilities = %d", capabilityResponse.StatusCode)
	}

	unauthorized, err := client.Get("https://127.0.0.1:" + tlsPort + "/api/v1/capabilities")
	if err != nil {
		t.Fatal(err)
	}
	defer unauthorized.Body.Close()
	if unauthorized.StatusCode != http.StatusUnauthorized {
		t.Fatalf("unauthenticated API status = %d", unauthorized.StatusCode)
	}

	cors, err := http.NewRequest(http.MethodGet, "https://127.0.0.1:"+tlsPort+"/api/v1/capabilities", nil)
	if err != nil {
		t.Fatal(err)
	}
	cors.Header.Set("Origin", "https://192.168.1.20:"+tlsPort)
	cors.Header.Set("X-Bomana-Mobile-Pairing", descriptor.PairingToken)
	corsResponse, err := client.Do(cors)
	if err != nil {
		t.Fatal(err)
	}
	defer corsResponse.Body.Close()
	if corsResponse.StatusCode != http.StatusOK {
		t.Fatalf("paired TLS capabilities = %d", corsResponse.StatusCode)
	}
	if corsResponse.Header.Get("Access-Control-Allow-Origin") != "https://192.168.1.20:"+tlsPort {
		t.Fatalf("pairing origin = %q", corsResponse.Header.Get("Access-Control-Allow-Origin"))
	}
}

func jsonDecode(payload []byte, output any) error {
	return json.Unmarshal(payload, output)
}

func trustMobileLeaseForTest(manager *mobilePairingManager, expiresAt time.Time) {
	manager.verifyLease = func(_ string, _ string, _ time.Time) (time.Time, error) {
		return expiresAt, nil
	}
}
