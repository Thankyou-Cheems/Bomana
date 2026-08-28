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
	if err := manager.Prepare(descriptor.BridgePairingID, descriptor.PairingToken, "signed-mobile-lease", now.Add(7*time.Hour), now.Add(4*time.Minute), now); err != nil {
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

func TestMobilePairingRotatesOneTokenAcrossMultipleLANEndpoints(t *testing.T) {
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
	if len(first.Networks) != 2 || !manager.Authorize(first.PairingToken, now) {
		t.Fatalf("invalid first pairing: %+v", first)
	}
	if !strings.HasPrefix(first.Networks[0].TLSEndpoint, "https://192.168.1.20:") {
		t.Fatalf("missing TLS endpoint: %+v", first.Networks[0])
	}
	second, err := manager.Start(http.NotFoundHandler(), now.Add(time.Minute))
	if err != nil {
		t.Fatal(err)
	}
	if first.BridgePairingID == second.BridgePairingID || first.PairingToken == second.PairingToken {
		t.Fatal("pairing rotation reused an identity or token")
	}
	if manager.Authorize(first.PairingToken, now.Add(time.Minute)) || !manager.Authorize(second.PairingToken, now.Add(time.Minute)) {
		t.Fatal("pairing rotation did not revoke the old token")
	}
	if manager.Authorize(second.PairingToken, now.Add(time.Minute+mobilePairingSessionDuration)) {
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

	descriptor, err := gateway.mobile.Start(gateway, time.Now())
	if err != nil {
		t.Fatal(err)
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
