package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"net"
	"net/http"
	"net/http/httptest"
	"net/url"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"bomana/native/telemetry_gateway/internal/extui"
	"bomana/native/telemetry_gateway/internal/extuihttp"
)

const testOrigin = "https://bomana.example.test"

func TestBridgeStatusPageIsAUserFacingLocalDestination(t *testing.T) {
	upstream, _ := url.Parse("http://127.0.0.1:8111")
	gateway := newRelay(upstream, testOrigin)
	request := httptest.NewRequest(http.MethodGet, "/", nil)
	response := httptest.NewRecorder()
	gateway.ServeHTTP(response, request)

	if response.Code != http.StatusOK {
		t.Fatalf("Bridge status page returned %d", response.Code)
	}
	body := response.Body.String()
	if !strings.Contains(body, "Bomana Bridge") || !strings.Contains(body, launcherURL) {
		t.Fatalf("Bridge status page is incomplete: %q", body)
	}
}

func TestRelayForwardsOnlyTheFixed8111Route(t *testing.T) {
	var requestedPath string
	upstream := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		requestedPath = request.URL.Path
		response.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(response, `{"H, m":3000}`)
	}))
	defer upstream.Close()
	upstreamURL, _ := url.Parse(upstream.URL)
	gateway := newRelay(upstreamURL, testOrigin)

	request := httptest.NewRequest(http.MethodGet, "/api/v1/8111/state", nil)
	request.Header.Set("Origin", testOrigin)
	response := httptest.NewRecorder()
	gateway.ServeHTTP(response, request)

	if response.Code != http.StatusOK || requestedPath != "/state" {
		t.Fatalf("unexpected relay result: code=%d path=%q", response.Code, requestedPath)
	}
	if response.Header().Get("Access-Control-Allow-Origin") != testOrigin {
		t.Fatal("exact browser origin was not returned")
	}
}

func TestRelayDiscoversTheWarThunderExtUIFallback(t *testing.T) {
	occupied := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, _ *http.Request) {
		response.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(response, `{"not_extui":true}`)
	}))
	defer occupied.Close()
	fallback := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		switch request.URL.Path {
		case "/map_info.json", "/indicators":
			response.Header().Set("Content-Type", "application/json")
			_, _ = io.WriteString(response, `{"valid":false}`)
		case "/icons.ttf":
			response.Header().Set("Content-Type", "application/octet-stream")
			_, _ = response.Write(bridgeTestSFNT())
		case "/state":
			response.Header().Set("Content-Type", "application/json")
			_, _ = io.WriteString(response, `{"valid":false,"army":"tank"}`)
		default:
			http.NotFound(response, request)
		}
	}))
	defer fallback.Close()
	occupiedURL, _ := url.Parse(occupied.URL)
	fallbackURL, _ := url.Parse(fallback.URL)
	resolver, err := extui.NewResolver(extui.Options{
		Candidates: []*url.URL{occupiedURL, fallbackURL},
		Read:       extuihttp.NewReader(&http.Client{Timeout: time.Second}),
		RetryDelay: time.Second,
	})
	if err != nil {
		t.Fatal(err)
	}
	gateway := newRelayWithExtUI(resolver, testOrigin, nil)

	request := httptest.NewRequest(http.MethodGet, "/api/v1/8111/state", nil)
	request.Header.Set("Origin", testOrigin)
	response := httptest.NewRecorder()
	gateway.ServeHTTP(response, request)

	if response.Code != http.StatusOK || !strings.Contains(response.Body.String(), `"army":"tank"`) {
		t.Fatalf("fallback relay = status=%d body=%s", response.Code, response.Body.String())
	}
}

func TestRelayRecoversWhenWarThunderMovesToAnotherExtUIPort(t *testing.T) {
	firstAvailable := true
	first := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		if !firstAvailable {
			http.Error(response, "stopped", http.StatusServiceUnavailable)
			return
		}
		serveBridgeExtUI(response, request, `{"valid":false,"source":"first"}`)
	}))
	defer first.Close()
	second := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		serveBridgeExtUI(response, request, `{"valid":false,"source":"second"}`)
	}))
	defer second.Close()
	firstURL, _ := url.Parse(first.URL)
	secondURL, _ := url.Parse(second.URL)
	resolver, err := extui.NewResolver(extui.Options{
		Candidates: []*url.URL{firstURL, secondURL},
		Read:       extuihttp.NewReader(&http.Client{Timeout: time.Second}),
		RetryDelay: time.Second,
	})
	if err != nil {
		t.Fatal(err)
	}
	gateway := newRelayWithExtUI(resolver, testOrigin, nil)

	firstResponse := relayState(t, gateway)
	if firstResponse.Code != http.StatusOK || !strings.Contains(firstResponse.Body.String(), `"source":"first"`) {
		t.Fatalf("initial relay = %d %s", firstResponse.Code, firstResponse.Body.String())
	}
	firstAvailable = false
	recovered := relayState(t, gateway)
	if recovered.Code != http.StatusOK || !strings.Contains(recovered.Body.String(), `"source":"second"`) {
		t.Fatalf("recovered relay = %d %s", recovered.Code, recovered.Body.String())
	}
}

func serveBridgeExtUI(response http.ResponseWriter, request *http.Request, state string) {
	switch request.URL.Path {
	case "/map_info.json", "/indicators":
		response.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(response, `{"valid":false}`)
	case "/icons.ttf":
		response.Header().Set("Content-Type", "application/octet-stream")
		_, _ = response.Write(bridgeTestSFNT())
	case "/state":
		response.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(response, state)
	default:
		http.NotFound(response, request)
	}
}

func bridgeTestSFNT() []byte {
	return []byte{
		0x00, 0x01, 0x00, 0x00, 0x00, 0x01, 0x00, 0x10, 0x00, 0x00, 0x00, 0x00,
		'g', 'l', 'y', 'f', 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x1c,
		0x00, 0x00, 0x00, 0x01, 0x00,
	}
}

func relayState(t *testing.T, gateway *relay) *httptest.ResponseRecorder {
	t.Helper()
	request := httptest.NewRequest(http.MethodGet, "/api/v1/8111/state", nil)
	request.Header.Set("Origin", testOrigin)
	response := httptest.NewRecorder()
	gateway.ServeHTTP(response, request)
	return response
}

func TestRelayForwardsOfficialGameChatWithAFixedLastId(t *testing.T) {
	var requested url.URL
	upstream := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		requested = *request.URL
		response.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(response, `[{"id":1,"msg":"C4","sender":"Wingman","enemy":false,"mode":"Team"}]`)
	}))
	defer upstream.Close()
	upstreamURL, _ := url.Parse(upstream.URL)
	gateway := newRelay(upstreamURL, testOrigin)

	request := httptest.NewRequest(http.MethodGet, "/api/v1/8111/gamechat", nil)
	request.Header.Set("Origin", testOrigin)
	response := httptest.NewRecorder()
	gateway.ServeHTTP(response, request)
	if response.Code != http.StatusOK {
		t.Fatalf("gamechat status = %d: %s", response.Code, response.Body.String())
	}
	if requested.Path != "/gamechat" || requested.RawQuery != "lastId=0" {
		t.Fatalf("gamechat upstream = %s?%s", requested.Path, requested.RawQuery)
	}

	query := httptest.NewRequest(http.MethodGet, "/api/v1/8111/gamechat?lastId=9", nil)
	query.Header.Set("Origin", testOrigin)
	queryResponse := httptest.NewRecorder()
	gateway.ServeHTTP(queryResponse, query)
	if queryResponse.Code != http.StatusNotFound {
		t.Fatalf("client query was proxied: %d", queryResponse.Code)
	}
}

func TestRelayRejectsArbitraryRoutesQueriesOriginsAndMethods(t *testing.T) {
	upstream, _ := url.Parse("http://127.0.0.1:8111")
	gateway := newRelay(upstream, testOrigin)
	tests := []struct {
		method string
		path   string
		origin string
		status int
	}{
		{http.MethodGet, "/api/v1/8111/anything", testOrigin, http.StatusNotFound},
		{http.MethodGet, "/api/v1/8111/state?url=http://example.test", testOrigin, http.StatusNotFound},
		{http.MethodGet, "/api/v1/8111/state", "https://evil.example", http.StatusForbidden},
		{http.MethodPost, "/api/v1/8111/state", testOrigin, http.StatusMethodNotAllowed},
	}
	for _, test := range tests {
		request := httptest.NewRequest(test.method, test.path, strings.NewReader("ignored"))
		request.Header.Set("Origin", test.origin)
		response := httptest.NewRecorder()
		gateway.ServeHTTP(response, request)
		if response.Code != test.status {
			t.Errorf("%s %s: got %d, want %d", test.method, test.path, response.Code, test.status)
		}
	}
}

func TestRelayAllowsOnlyTheDeclaredBinaryContentTypes(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		if request.URL.Path == "/map.img" {
			response.Header().Set("Content-Type", "image/png")
			_, _ = response.Write([]byte("png"))
			return
		}
		response.Header().Set("Content-Type", "text/html")
		_, _ = response.Write([]byte("rejected"))
	}))
	defer upstream.Close()
	upstreamURL, _ := url.Parse(upstream.URL)
	gateway := newRelay(upstreamURL, testOrigin)

	imageRequest := httptest.NewRequest(http.MethodGet, "/api/v1/8111/map-image", nil)
	imageRequest.Header.Set("Origin", testOrigin)
	imageResponse := httptest.NewRecorder()
	gateway.ServeHTTP(imageResponse, imageRequest)
	if imageResponse.Code != http.StatusOK || imageResponse.Header().Get("Content-Type") != "image/png" {
		t.Fatalf("official map image was rejected: %d", imageResponse.Code)
	}

	fontRequest := httptest.NewRequest(http.MethodGet, "/api/v1/8111/icons-font", nil)
	fontRequest.Header.Set("Origin", testOrigin)
	fontResponse := httptest.NewRecorder()
	gateway.ServeHTTP(fontResponse, fontRequest)
	if fontResponse.Code != http.StatusBadGateway {
		t.Fatalf("unexpected font content type was accepted: %d", fontResponse.Code)
	}
}

func TestRelaySendsRouteSpecificAcceptHeaders(t *testing.T) {
	acceptByPath := map[string]string{}
	upstream := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		acceptByPath[request.URL.Path] = request.Header.Get("Accept")
		if request.URL.Path == "/map.img" {
			response.Header().Set("Content-Type", "image/png")
			_, _ = response.Write([]byte("png"))
			return
		}
		if request.URL.Path == "/icons.ttf" {
			response.Header().Set("Content-Type", "font/ttf")
			_, _ = response.Write([]byte("ttf"))
			return
		}
		response.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(response, `{"H, m":3000}`)
	}))
	defer upstream.Close()
	upstreamURL, _ := url.Parse(upstream.URL)
	gateway := newRelay(upstreamURL, testOrigin)

	for _, path := range []string{"/api/v1/8111/state", "/api/v1/8111/map-image", "/api/v1/8111/icons-font"} {
		request := httptest.NewRequest(http.MethodGet, path, nil)
		request.Header.Set("Origin", testOrigin)
		response := httptest.NewRecorder()
		gateway.ServeHTTP(response, request)
		if response.Code != http.StatusOK {
			t.Fatalf("%s status = %d", path, response.Code)
		}
	}
	if acceptByPath["/state"] != "application/json" {
		t.Fatalf("state Accept = %q", acceptByPath["/state"])
	}
	if acceptByPath["/map.img"] != "image/png, image/jpeg" {
		t.Fatalf("map image Accept = %q", acceptByPath["/map.img"])
	}
	if acceptByPath["/icons.ttf"] != "font/ttf, application/octet-stream" {
		t.Fatalf("icons font Accept = %q", acceptByPath["/icons.ttf"])
	}
}

func TestConfigurationAcceptsOnlyLoopbackListenerAndSafeOrigin(t *testing.T) {
	if err := validateLoopbackListener("127.0.0.1:8878"); err != nil {
		t.Fatal(err)
	}
	if err := validateLoopbackListener("0.0.0.0:8878"); err == nil {
		t.Fatal("wildcard listener must be rejected")
	}
	if _, err := validateOrigin("https://bomana.example.test"); err != nil {
		t.Fatal(err)
	}
	if _, err := validateOrigin("http://bomana.example.test"); err == nil {
		t.Fatal("remote HTTP origin must be rejected")
	}
}

func TestAutomaticListenerSkipsAnOccupiedBridgePort(t *testing.T) {
	occupied, err := net.Listen("tcp", "127.0.0.1:8878")
	if err != nil {
		t.Skipf("test port already occupied: %v", err)
	}
	defer occupied.Close()
	listener, err := listenBridge("auto")
	if err != nil {
		t.Fatal(err)
	}
	defer listener.Close()
	_, port, _ := net.SplitHostPort(listener.Addr().String())
	if port == "8878" {
		t.Fatal("automatic listener reused the occupied port")
	}
}

func TestBridgeCapabilitiesExposeOnlyStableReadOnlyContract(t *testing.T) {
	upstream, _ := url.Parse("http://127.0.0.1:8111")
	gateway := newRelay(upstream, testOrigin)
	request := httptest.NewRequest(http.MethodGet, "/api/v1/capabilities", nil)
	request.Header.Set("Origin", testOrigin)
	response := httptest.NewRecorder()
	gateway.ServeHTTP(response, request)
	if response.Code != http.StatusOK {
		t.Fatalf("capabilities status = %d", response.Code)
	}
	body := response.Body.String()
	for _, expected := range []string{`"bridge_protocol":1`, `"cache_protocol":4`, `"mobile_pairing_protocol":7`, `"bridge_version":"development"`, `"app_web_version":"development"`, `"input":"official-8111-only"`, `"write_commands":false`, `"authenticode":false`} {
		if !strings.Contains(body, expected) {
			t.Fatalf("capabilities missing %s: %s", expected, body)
		}
	}
	if strings.Contains(body, `"authenticode":true`) {
		t.Fatal("unsigned Bridge claimed Windows Authenticode trust")
	}
	for _, forbidden := range []string{"install", "download", "launch", "memory"} {
		if strings.Contains(strings.ToLower(body), forbidden) {
			t.Fatalf("capabilities leaked native authority %q", forbidden)
		}
	}
}

func TestBridgeSynchronizesOnlyABoundedWeaponSelection(t *testing.T) {
	upstream, _ := url.Parse("http://127.0.0.1:8111")
	gateway := newRelay(upstream, testOrigin)

	read := httptest.NewRequest(http.MethodGet, "/api/v1/presentation/weapon-selection", nil)
	read.Header.Set("Origin", testOrigin)
	readResponse := httptest.NewRecorder()
	gateway.ServeHTTP(readResponse, read)
	if readResponse.Code != http.StatusOK || !strings.Contains(readResponse.Body.String(), `"revision":0`) {
		t.Fatalf("initial weapon selection = %d %s", readResponse.Code, readResponse.Body.String())
	}

	write := httptest.NewRequest(http.MethodPut, "/api/v1/presentation/weapon-selection", strings.NewReader(`{"schema_version":1,"selected_weapon_id":"gbu_31_v_3_b"}`))
	write.Header.Set("Origin", testOrigin)
	write.Header.Set("Content-Type", "application/json")
	writeResponse := httptest.NewRecorder()
	gateway.ServeHTTP(writeResponse, write)
	if writeResponse.Code != http.StatusOK || !strings.Contains(writeResponse.Body.String(), `"revision":1`) {
		t.Fatalf("weapon selection write = %d %s", writeResponse.Code, writeResponse.Body.String())
	}

	readAgain := httptest.NewRequest(http.MethodGet, "/api/v1/presentation/weapon-selection", nil)
	readAgain.Header.Set("Origin", testOrigin)
	readAgainResponse := httptest.NewRecorder()
	gateway.ServeHTTP(readAgainResponse, readAgain)
	if readAgainResponse.Code != http.StatusOK || !strings.Contains(readAgainResponse.Body.String(), `"selected_weapon_id":"gbu_31_v_3_b"`) {
		t.Fatalf("weapon selection readback = %d %s", readAgainResponse.Code, readAgainResponse.Body.String())
	}

	invalid := httptest.NewRequest(http.MethodPut, "/api/v1/presentation/weapon-selection", strings.NewReader(`{"schema_version":1,"selected_weapon_id":"../../arbitrary"}`))
	invalid.Header.Set("Origin", testOrigin)
	invalidResponse := httptest.NewRecorder()
	gateway.ServeHTTP(invalidResponse, invalid)
	if invalidResponse.Code != http.StatusBadRequest {
		t.Fatalf("invalid weapon selection status = %d", invalidResponse.Code)
	}
}

func TestBridgeCacheInterfaceStoresOnlyVerifiedContentAddressedObjects(t *testing.T) {
	manifestURL, _ := url.Parse("http://127.0.0.1/terrain_manifest.json")
	store, err := newLocalDataStore(t.TempDir(), manifestURL, http.DefaultClient, func(terrainManifest) error { return nil })
	if err != nil {
		t.Fatal(err)
	}
	upstream, _ := url.Parse("http://127.0.0.1:8111")
	gateway := newRelayWithCache(upstream, testOrigin, store)
	payload := []byte("browser cache payload")
	digest := digestBytes(payload)
	allowed := terrainManifestFile{Path: "air_test.bth", Asset: "Bomana_terrain_object_" + digest + ".bth", SHA256: digest, SizeBytes: int64(len(payload))}
	store.beginManifest(terrainManifest{TerrainRevision: strings.Repeat("a", 64), MapCount: 1}, []terrainManifestFile{allowed})
	store.applyTerrainIndex(map[string][]string{"air_test": {"air_test.bth"}})
	if err := store.SetSelectedMaps([]string{"air_test"}); err != nil {
		t.Fatal(err)
	}

	put := httptest.NewRequest(http.MethodPut, "/api/v1/cache/objects/"+digest, bytes.NewReader(payload))
	put.Header.Set("Origin", testOrigin)
	putResponse := httptest.NewRecorder()
	gateway.ServeHTTP(putResponse, put)
	if putResponse.Code != http.StatusNoContent {
		t.Fatalf("cache PUT status = %d: %s", putResponse.Code, putResponse.Body.String())
	}

	get := httptest.NewRequest(http.MethodGet, "/api/v1/cache/objects/"+digest, nil)
	get.Header.Set("Origin", testOrigin)
	getResponse := httptest.NewRecorder()
	gateway.ServeHTTP(getResponse, get)
	if getResponse.Code != http.StatusOK || !bytes.Equal(getResponse.Body.Bytes(), payload) {
		t.Fatalf("cache GET failed: status=%d body=%q", getResponse.Code, getResponse.Body.Bytes())
	}

	wrong := httptest.NewRequest(http.MethodPut, "/api/v1/cache/objects/"+strings.Repeat("b", 64), bytes.NewReader(payload))
	wrong.Header.Set("Origin", testOrigin)
	wrongResponse := httptest.NewRecorder()
	gateway.ServeHTTP(wrongResponse, wrong)
	if wrongResponse.Code != http.StatusUnprocessableEntity {
		t.Fatalf("mismatched cache object status = %d", wrongResponse.Code)
	}

	loopbackPut := httptest.NewRequest(http.MethodPut, "/api/v1/cache/objects/"+digest, bytes.NewReader(payload))
	loopbackPut.RemoteAddr = "127.0.0.1:54321"
	loopbackPutResponse := httptest.NewRecorder()
	gateway.ServeHTTP(loopbackPutResponse, loopbackPut)
	if loopbackPutResponse.Code != http.StatusForbidden {
		t.Fatalf("loopback cache PUT without Origin status = %d", loopbackPutResponse.Code)
	}

	missing := httptest.NewRequest(http.MethodDelete, "/api/v1/cache/objects/"+strings.Repeat("c", 64), nil)
	missing.Header.Set("Origin", testOrigin)
	missingResponse := httptest.NewRecorder()
	gateway.ServeHTTP(missingResponse, missing)
	if missingResponse.Code != http.StatusNotFound {
		t.Fatalf("unknown cache DELETE status = %d", missingResponse.Code)
	}
}

func TestBridgeCacheSelectionRequiresBrowserOriginAndKnownMaps(t *testing.T) {
	manifestURL, _ := url.Parse("http://127.0.0.1/terrain_manifest.json")
	store, err := newLocalDataStore(t.TempDir(), manifestURL, http.DefaultClient, func(terrainManifest) error { return nil })
	if err != nil {
		t.Fatal(err)
	}
	files := []terrainManifestFile{
		{Path: "air_alpha.bth", Asset: "Bomana_terrain_object_" + strings.Repeat("a", 64) + ".bth", SHA256: strings.Repeat("a", 64), SizeBytes: 10},
		{Path: "air_bravo.bth", Asset: "Bomana_terrain_object_" + strings.Repeat("b", 64) + ".bth", SHA256: strings.Repeat("b", 64), SizeBytes: 20},
	}
	store.beginManifest(terrainManifest{TerrainRevision: strings.Repeat("c", 64), MapCount: 2}, files)
	store.applyTerrainIndex(map[string][]string{"air_alpha": {"air_alpha.bth"}, "air_bravo": {"air_bravo.bth"}})
	upstream, _ := url.Parse("http://127.0.0.1:8111")
	gateway := newRelayWithCache(upstream, testOrigin, store)

	request := httptest.NewRequest(http.MethodPut, "/api/v1/cache/selection", strings.NewReader(`{"map_ids":["air_alpha"]}`))
	request.Header.Set("Origin", testOrigin)
	request.Header.Set("Content-Type", "application/json")
	response := httptest.NewRecorder()
	gateway.ServeHTTP(response, request)
	if response.Code != http.StatusAccepted {
		t.Fatalf("selection status=%d body=%s", response.Code, response.Body.String())
	}
	status := store.Status()
	if status.SelectedMapCount != 1 || !status.Maps[0].Selected {
		t.Fatalf("selection not applied: %#v", status)
	}
	priority := httptest.NewRequest(http.MethodPut, "/api/v1/cache/selection", strings.NewReader(`{"priority_map_id":"air_bravo"}`))
	priority.Header.Set("Origin", testOrigin)
	priority.Header.Set("Content-Type", "application/json")
	priorityResponse := httptest.NewRecorder()
	gateway.ServeHTTP(priorityResponse, priority)
	if priorityResponse.Code != http.StatusAccepted || store.Status().SelectedMapCount != 2 || store.priorityMap != "air_bravo" {
		t.Fatalf("atomic current map selection failed: %d %s", priorityResponse.Code, priorityResponse.Body.String())
	}

	unknown := httptest.NewRequest(http.MethodPut, "/api/v1/cache/selection", strings.NewReader(`{"map_ids":["air_unknown"]}`))
	unknown.Header.Set("Origin", testOrigin)
	unknown.Header.Set("Content-Type", "application/json")
	unknownResponse := httptest.NewRecorder()
	gateway.ServeHTTP(unknownResponse, unknown)
	if unknownResponse.Code != http.StatusUnprocessableEntity {
		t.Fatalf("unknown selection status=%d", unknownResponse.Code)
	}

	loopback := httptest.NewRequest(http.MethodPut, "/api/v1/cache/selection", strings.NewReader(`{"map_ids":[]}`))
	loopback.RemoteAddr = "127.0.0.1:54321"
	loopbackResponse := httptest.NewRecorder()
	gateway.ServeHTTP(loopbackResponse, loopback)
	if loopbackResponse.Code != http.StatusForbidden {
		t.Fatalf("originless selection status=%d", loopbackResponse.Code)
	}
}

func TestBridgeCacheCatalogServesTheVerifiedPersistedManifest(t *testing.T) {
	root := t.TempDir()
	manifestURL, _ := url.Parse("http://127.0.0.1/terrain_manifest.json")
	store, err := newLocalDataStore(root, manifestURL, http.DefaultClient, func(terrainManifest) error { return nil })
	if err != nil {
		t.Fatal(err)
	}
	index := []byte(`{"schema_version":1,"maps":[{"id":"air_test","file":"air_test.bth","map_bounds":[0,0,1,1]}]}`)
	terrain := []byte("terrain")
	manifest := terrainManifest{
		SchemaVersion: 1, TerrainPackID: "terrain-v1", TerrainRevision: strings.Repeat("a", 64), MapCount: 1,
		Signature: terrainManifestSignature{Algorithm: "ed25519", KeyID: "test", Signature: "test"},
		Files: []terrainManifestFile{
			{Path: "index.json", Asset: "Bomana_terrain_object_" + digestBytes(index) + ".json", SHA256: digestBytes(index), SizeBytes: int64(len(index))},
			{Path: "air_test.bth", Asset: "Bomana_terrain_object_" + digestBytes(terrain) + ".bth", SHA256: digestBytes(terrain), SizeBytes: int64(len(terrain))},
		},
	}
	manifest.TotalSizeBytes = int64(len(index) + len(terrain))
	manifestBytes, _ := json.Marshal(manifest)
	if err := saveVerifiedCatalog(filepath.Join(root, terrainCatalogFileName), manifestBytes); err != nil {
		t.Fatal(err)
	}

	upstream, _ := url.Parse("http://127.0.0.1:8111")
	gateway := newRelayWithCache(upstream, testOrigin, store)
	request := httptest.NewRequest(http.MethodGet, "/api/v1/cache/catalog", nil)
	request.Header.Set("Origin", testOrigin)
	response := httptest.NewRecorder()
	gateway.ServeHTTP(response, request)
	if response.Code != http.StatusOK {
		t.Fatalf("catalog status=%d body=%s", response.Code, response.Body.String())
	}
	if !bytes.Equal(response.Body.Bytes(), manifestBytes) {
		t.Fatalf("catalog body mismatch: got=%s want=%s", response.Body.Bytes(), manifestBytes)
	}
}

func TestBridgePreflightOptsIntoExactOriginPrivateNetworkRead(t *testing.T) {
	upstream, _ := url.Parse("http://127.0.0.1:8111")
	gateway := newRelay(upstream, testOrigin)
	request := httptest.NewRequest(http.MethodOptions, "/api/v1/8111/state", nil)
	request.Header.Set("Origin", testOrigin)
	request.Header.Set("Access-Control-Request-Private-Network", "true")
	response := httptest.NewRecorder()
	gateway.ServeHTTP(response, request)
	if response.Code != http.StatusNoContent {
		t.Fatalf("preflight status = %d", response.Code)
	}
	if response.Header().Get("Access-Control-Allow-Private-Network") != "true" {
		t.Fatal("private-network read preflight was not explicitly allowed")
	}
}

type memoryRoundTrip func(*http.Request) (*http.Response, error)

func (f memoryRoundTrip) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }
func memoryResponse() *http.Response {
	return &http.Response{StatusCode: 200, Header: http.Header{"Content-Type": []string{"application/json"}}, Body: io.NopCloser(strings.NewReader(`{"valid":true}`))}
}
func memoryFingerprint(path string) ([]byte, string, error) {
	if path == "/icons.ttf" {
		return []byte{0, 1, 0, 0, 0, 1, 0, 16, 0, 0, 0, 0, 'g', 'l', 'y', 'f', 0, 0, 0, 0, 0, 0, 0, 28, 0, 0, 0, 1, 0}, "font/ttf", nil
	}
	return []byte(`{"valid":false}`), "application/json", nil
}
func memoryResolver(t *testing.T, read extui.ReadFunc, now func() time.Time) *extui.Resolver {
	t.Helper()
	r, e := extui.NewResolver(extui.Options{Candidates: extui.DefaultCandidates(), Read: read, Now: now})
	if e != nil {
		t.Fatal(e)
	}
	return r
}

func TestMemoryBothStartupOrdersRecover(t *testing.T) {
	for _, first := range []bool{true, false} {
		name := "game-first"
		if first {
			name = "bridge-first"
		}
		t.Run(name, func(t *testing.T) {
			now := time.Unix(0, 0)
			available := !first
			probes := 0
			resolver := memoryResolver(t, func(ctx context.Context, u *url.URL, _ int64) ([]byte, string, error) {
				probes++
				if !available {
					return nil, "", errors.New("synthetic connection refused")
				}
				return memoryFingerprint(u.Path)
			}, func() time.Time { return now })
			if first {
				if _, e := resolver.Resolve(context.Background()); e == nil {
					t.Fatal("absent game accepted")
				}
				available = true
				if _, e := resolver.Resolve(context.Background()); e == nil {
					t.Fatal("backoff unexpectedly absent")
				}
				if probes != 3 {
					t.Fatalf("negative cache reprobed: %d", probes)
				}
				now = now.Add(time.Second)
			}
			selected, e := resolver.Resolve(context.Background())
			if e != nil || selected.Port() != "8111" {
				t.Fatalf("resolve: %v %v", selected, e)
			}
			before := probes
			if _, e = resolver.Resolve(context.Background()); e != nil || probes != before {
				t.Fatal("warm resolver not cached")
			}
			t.Logf("order=%s ready=true probes=%d; no order-only permanent failure", name, probes)
		})
	}
}

func TestMemoryCancelledBrowserRequestPreservesHealthySelection(t *testing.T) {
	probes := 0
	resolver := memoryResolver(t, func(ctx context.Context, u *url.URL, _ int64) ([]byte, string, error) {
		if e := ctx.Err(); e != nil {
			return nil, "", e
		}
		probes++
		return memoryFingerprint(u.Path)
	}, nil)
	if _, e := resolver.Resolve(context.Background()); e != nil {
		t.Fatal(e)
	}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	relay := newRelayWithExtUI(resolver, "https://bomana.ruikang.wang", nil)
	relay.client.Transport = memoryRoundTrip(func(r *http.Request) (*http.Response, error) { cancel(); return nil, r.Context().Err() })
	request := httptest.NewRequest("GET", "http://127.0.0.1:8878/api/v1/8111/state", nil).WithContext(ctx)
	request.Header.Set("Origin", "https://bomana.ruikang.wang")
	recorder := httptest.NewRecorder()
	relay.ServeHTTP(recorder, request)
	if resolver.Snapshot().State != extui.StateReady {
		t.Fatal("caller cancellation evicted the healthy selection")
	}
	before := probes
	relay.client.Transport = memoryRoundTrip(func(*http.Request) (*http.Response, error) { return memoryResponse(), nil })
	request = httptest.NewRequest("GET", "http://127.0.0.1:8878/api/v1/8111/state", nil)
	request.Header.Set("Origin", "https://bomana.ruikang.wang")
	recorder = httptest.NewRecorder()
	relay.ServeHTTP(recorder, request)
	if recorder.Code != 200 || probes-before != 0 {
		t.Fatalf("recovery code=%d probes=%d", recorder.Code, probes-before)
	}
	t.Log("caller cancellation preserved the selected upstream; next request did not repeat fingerprint probes")
}

func memoryRequest(path string, ctx context.Context) *http.Request {
	r := httptest.NewRequest("GET", "http://127.0.0.1:8878/api/v1/8111/"+path, nil).WithContext(ctx)
	r.Header.Set("Origin", "https://bomana.ruikang.wang")
	return r
}

func memoryWait(t *testing.T, signal <-chan struct{}) {
	t.Helper()
	select {
	case <-signal:
	case <-time.After(3 * time.Second):
		t.Fatal("memory fixture did not reach its synchronization point")
	}
}

func TestMemoryConcurrentLateFailureDoesNotReprobeNewSelection(t *testing.T) {
	var probes, stateCalls, indicatorCalls atomic.Int32
	r := memoryResolver(t, func(ctx context.Context, u *url.URL, _ int64) ([]byte, string, error) {
		probes.Add(1)
		return memoryFingerprint(u.Path)
	}, nil)
	if _, err := r.Resolve(context.Background()); err != nil {
		t.Fatal(err)
	}
	oldInFlight, releaseOld, done := make(chan struct{}), make(chan struct{}), make(chan struct{})
	var release sync.Once
	defer release.Do(func() { close(releaseOld) })
	gateway := newRelayWithExtUI(r, "https://bomana.ruikang.wang", nil)
	gateway.client.Transport = memoryRoundTrip(func(req *http.Request) (*http.Response, error) {
		if req.URL.Path == "/state" && stateCalls.Add(1) == 1 {
			close(oldInFlight)
			<-releaseOld
			return nil, errors.New("synthetic late transport failure")
		}
		if req.URL.Path == "/indicators" && indicatorCalls.Add(1) == 1 {
			return nil, errors.New("synthetic current transport failure")
		}
		return memoryResponse(), nil
	})
	oldResponse := httptest.NewRecorder()
	go func() {
		defer close(done)
		gateway.ServeHTTP(oldResponse, memoryRequest("state", context.Background()))
	}()
	memoryWait(t, oldInFlight)
	currentResponse := httptest.NewRecorder()
	gateway.ServeHTTP(currentResponse, memoryRequest("indicators", context.Background()))
	if currentResponse.Code != 200 || probes.Load() != 6 {
		t.Fatalf("current failure must rediscover: code=%d probes=%d", currentResponse.Code, probes.Load())
	}
	release.Do(func() { close(releaseOld) })
	memoryWait(t, done)
	if oldResponse.Code != 200 || probes.Load() != 6 {
		t.Fatalf("late failure reprobed the new same-address selection: code=%d probes=%d", oldResponse.Code, probes.Load())
	}
	if stateCalls.Load() != 2 || indicatorCalls.Load() != 2 {
		t.Fatal("both requests must recover in their second attempt")
	}
}

func TestMemoryConcurrentCancellationKeepsOtherReaderReady(t *testing.T) {
	var probes atomic.Int32
	r := memoryResolver(t, func(ctx context.Context, u *url.URL, _ int64) ([]byte, string, error) {
		probes.Add(1)
		return memoryFingerprint(u.Path)
	}, nil)
	if _, err := r.Resolve(context.Background()); err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	held, done := make(chan struct{}), make(chan struct{})
	var signalHeld sync.Once
	var canceledCalls atomic.Int32
	gateway := newRelayWithExtUI(r, "https://bomana.ruikang.wang", nil)
	gateway.client.Transport = memoryRoundTrip(func(req *http.Request) (*http.Response, error) {
		if req.URL.Path == "/state" {
			canceledCalls.Add(1)
			signalHeld.Do(func() { close(held) })
			<-req.Context().Done()
			return nil, req.Context().Err()
		}
		return memoryResponse(), nil
	})
	go func() { defer close(done); gateway.ServeHTTP(httptest.NewRecorder(), memoryRequest("state", ctx)) }()
	memoryWait(t, held)
	before := httptest.NewRecorder()
	gateway.ServeHTTP(before, memoryRequest("indicators", context.Background()))
	cancel()
	memoryWait(t, done)
	after := httptest.NewRecorder()
	gateway.ServeHTTP(after, memoryRequest("indicators", context.Background()))
	if before.Code != 200 || after.Code != 200 || probes.Load() != 3 || canceledCalls.Load() != 1 {
		t.Fatalf("canceled reader disrupted its peer: codes=%d/%d probes=%d attempts=%d", before.Code, after.Code, probes.Load(), canceledCalls.Load())
	}
}

func TestMemoryConcurrentColdDiscoverySharesOneSelection(t *testing.T) {
	var probes atomic.Int32
	entered, release := make(chan struct{}), make(chan struct{})
	var unblock sync.Once
	defer unblock.Do(func() { close(release) })
	r := memoryResolver(t, func(ctx context.Context, u *url.URL, _ int64) ([]byte, string, error) {
		if probes.Add(1) == 1 {
			close(entered)
			<-release
		}
		return memoryFingerprint(u.Path)
	}, nil)
	results := make(chan error, 16)
	for i := 0; i < 16; i++ {
		go func() {
			selection, err := r.Resolve(context.Background())
			if err == nil && selection.Port() != "8111" {
				err = errors.New("wrong selected port")
			}
			results <- err
		}()
	}
	memoryWait(t, entered)
	unblock.Do(func() { close(release) })
	for i := 0; i < 16; i++ {
		select {
		case err := <-results:
			if err != nil {
				t.Fatal(err)
			}
		case <-time.After(3 * time.Second):
			t.Fatal("discovery waiter stuck")
		}
	}
	if probes.Load() != 3 {
		t.Fatalf("parallel readers repeated discovery %d times", probes.Load())
	}
}

func TestMemoryCurrentFailureFindsFallbackPort(t *testing.T) {
	port := "8111"
	r := memoryResolver(t, func(ctx context.Context, u *url.URL, _ int64) ([]byte, string, error) {
		if u.Port() != port {
			return nil, "", errors.New("synthetic refused")
		}
		return memoryFingerprint(u.Path)
	}, nil)
	old, err := r.Resolve(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	port = "9222"
	r.Invalidate(old)
	fresh, err := r.Resolve(context.Background())
	if err != nil || fresh.Port() != port {
		t.Fatalf("fallback: %v %v", fresh, err)
	}
	r.Invalidate(old)
	if r.Snapshot().Port != port {
		t.Fatal("old port's failure evicted fallback")
	}
}

func TestMemoryColdDiscoveryCanExceedBrowserBudget(t *testing.T) {
	// Virtual latency only: each probe takes 600 ms, below the 750 ms per-probe limit.
	// A browser cancels its request after 1500 ms, before three probes can finish.
	elapsed := 0
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	resolver := memoryResolver(t, func(ctx context.Context, u *url.URL, _ int64) ([]byte, string, error) {
		if e := ctx.Err(); e != nil {
			return nil, "", e
		}
		elapsed += 600
		if elapsed >= 1500 {
			cancel()
			return nil, "", context.Canceled
		}
		return memoryFingerprint(u.Path)
	}, nil)
	if _, e := resolver.Resolve(ctx); !errors.Is(e, context.Canceled) {
		t.Fatalf("expected cancellation, got %v", e)
	}
	if resolver.Snapshot().State != extui.StateIdle {
		t.Fatal("canceled probe should not negative-cache")
	}
	t.Log("cold discovery needs 1800 ms at 600 ms/probe and cannot fit the 1500 ms Web deadline; input is synthetic")
}

func TestMemoryLateFailurePreservesRevalidatedSameOrigin(t *testing.T) {
	probes := 0
	resolver := memoryResolver(t, func(ctx context.Context, u *url.URL, _ int64) ([]byte, string, error) {
		probes++
		return memoryFingerprint(u.Path)
	}, nil)
	old, e := resolver.Resolve(context.Background())
	if e != nil {
		t.Fatal(e)
	}
	resolver.Invalidate(old)
	fresh, e := resolver.Resolve(context.Background())
	if e != nil {
		t.Fatal(e)
	}
	if probes != 6 {
		t.Fatalf("expected revalidation: %d", probes)
	}
	resolver.Invalidate(old) // A second request from the old generation finishes late.
	if resolver.Snapshot().State != extui.StateReady {
		t.Fatal("late failure evicted the newly verified selection")
	}
	if fresh.Host != old.Host {
		t.Fatal("test did not use same origin")
	}
	resolver.Invalidate(fresh)
	if resolver.Snapshot().State == extui.StateReady {
		t.Fatal("current selection failure must still invalidate")
	}
}

type countedSelection struct {
	gameUpstream
	resolves, invalidations int
}

// Expire a deadline at the transport seam, without scheduler-dependent sleeps.
type memoryDeadlineContext struct {
	context.Context
	done chan struct{}
}

func (ctx memoryDeadlineContext) Done() <-chan struct{} { return ctx.done }
func (ctx memoryDeadlineContext) Err() error {
	select {
	case <-ctx.done:
		return context.DeadlineExceeded
	default:
		return nil
	}
}

func (c *countedSelection) Resolve(ctx context.Context) (*extui.Selection, error) {
	c.resolves++
	return c.gameUpstream.Resolve(ctx)
}
func (c *countedSelection) Invalidate(s *extui.Selection) bool {
	c.invalidations++
	return c.gameUpstream.Invalidate(s)
}

func TestMemoryCallerAbortDoesNotRetryOrInvalidate(t *testing.T) {
	for _, deadline := range []bool{false, true} {
		name := "cancel"
		if deadline {
			name = "deadline"
		}
		t.Run(name, func(t *testing.T) {
			r := memoryResolver(t, func(ctx context.Context, u *url.URL, _ int64) ([]byte, string, error) {
				return memoryFingerprint(u.Path)
			}, nil)
			if _, err := r.Resolve(context.Background()); err != nil {
				t.Fatal(err)
			}
			upstream := &countedSelection{gameUpstream: r}
			gateway := newRelayWithExtUI(upstream, "https://bomana.ruikang.wang", nil)
			var logs bytes.Buffer
			gateway.diagnostics.logger = slog.New(slog.NewJSONHandler(&logs, nil))
			var ctx context.Context
			ctx, cancel := context.WithCancel(context.Background())
			expire := cancel
			if deadline {
				cancel()
				deadlineContext := memoryDeadlineContext{Context: context.Background(), done: make(chan struct{})}
				ctx = deadlineContext
				expire = func() { close(deadlineContext.done) }
			}
			defer cancel()
			calls := 0
			gateway.client.Transport = memoryRoundTrip(func(req *http.Request) (*http.Response, error) {
				calls++
				expire()
				<-req.Context().Done()
				return nil, req.Context().Err()
			})
			gateway.ServeHTTP(httptest.NewRecorder(), memoryRequest("state", ctx))
			if calls != 1 || upstream.resolves != 1 || upstream.invalidations != 0 || r.Snapshot().State != extui.StateReady {
				t.Fatalf("abandoned request retried/invalidated: transport=%d resolve=%d invalidate=%d", calls, upstream.resolves, upstream.invalidations)
			}
			kind := "caller_canceled"
			if deadline {
				kind = "caller_deadline"
			}
			if !strings.Contains(logs.String(), kind) {
				t.Fatalf("missing bounded classification: %s", logs.String())
			}
		})
	}
}

func TestMemoryUpstreamTimeoutStillInvalidatesAndRetries(t *testing.T) {
	for _, stage := range []string{"transport", "body"} {
		t.Run(stage, func(t *testing.T) {
			probes, calls := 0, 0
			r := memoryResolver(t, func(ctx context.Context, u *url.URL, _ int64) ([]byte, string, error) {
				probes++
				return memoryFingerprint(u.Path)
			}, nil)
			if _, err := r.Resolve(context.Background()); err != nil {
				t.Fatal(err)
			}
			gateway := newRelayWithExtUI(r, "https://bomana.ruikang.wang", nil)
			var logs bytes.Buffer
			gateway.diagnostics.logger = slog.New(slog.NewJSONHandler(&logs, nil))
			gateway.client.Transport = memoryRoundTrip(func(req *http.Request) (*http.Response, error) {
				calls++
				if calls == 1 {
					if stage == "body" {
						response := memoryResponse()
						response.Body = io.NopCloser(memoryTimedOutBody{})
						return response, nil
					}
					return nil, context.DeadlineExceeded
				}
				return memoryResponse(), nil
			})
			response := httptest.NewRecorder()
			gateway.ServeHTTP(response, memoryRequest("state", context.Background()))
			if response.Code != 200 || calls != 2 || probes != 6 {
				t.Fatalf("real upstream timeout lost recovery: status=%d calls=%d probes=%d", response.Code, calls, probes)
			}
			if !strings.Contains(logs.String(), "upstream_timeout") {
				t.Fatalf("timeout classification lost at %s: %s", stage, logs.String())
			}
		})
	}
}

type memoryTimedOutBody struct{}

func (memoryTimedOutBody) Read([]byte) (int, error) { return 0, context.DeadlineExceeded }

func TestMemoryDiagnosticsBoundedAndExcludeRawErrors(t *testing.T) {
	now := time.Unix(1000, 0)
	var logs bytes.Buffer
	d := relayDiagnostics{now: func() time.Time { return now }, logger: slog.New(slog.NewJSONHandler(&logs, nil))}
	r := memoryResolver(t, func(ctx context.Context, u *url.URL, _ int64) ([]byte, string, error) {
		return memoryFingerprint(u.Path)
	}, nil)
	s, err := r.Resolve(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	secretError := &url.Error{Op: "GET", URL: "http://secret.example/private?token=PRIVATE", Err: errors.New("personal-data")}
	for i := 0; i < 1000; i++ {
		d.failed("/state", s, 1250*time.Millisecond, relayErrorKind(secretError, false), false)
		d.recovered("/state", s, time.Millisecond)
	}
	decoder := json.NewDecoder(&logs)
	events := []map[string]any{}
	for {
		var e map[string]any
		err := decoder.Decode(&e)
		if err == io.EOF {
			break
		}
		if err != nil {
			t.Fatal(err)
		}
		events = append(events, e)
	}
	if len(events) != 2 {
		t.Fatalf("1000 repeated failures/recoveries wrote %d events", len(events))
	}
	allowed := map[string]bool{"time": true, "level": true, "msg": true, "route": true, "upstream_port": true, "generation": true, "elapsed_ms": true, "kind": true, "invalidated": true}
	for _, e := range events {
		for key := range e {
			if !allowed[key] {
				t.Fatalf("unexpected diagnostic data: %s", key)
			}
		}
		if e["generation"] != float64(1) || e["upstream_port"] != "8111" {
			t.Fatalf("missing selection identity: %v", e)
		}
	}
	encoded, _ := json.Marshal(events)
	for _, secret := range []string{"PRIVATE", "personal-data", "secret.example"} {
		if bytes.Contains(encoded, []byte(secret)) {
			t.Fatalf("diagnostic leaked %s", secret)
		}
	}
	now = now.Add(30 * time.Second)
	logs.Reset()
	d.failed("/state", s, time.Millisecond, "upstream_timeout", true)
	if !strings.Contains(logs.String(), "upstream_timeout") {
		t.Fatal("next bounded interval did not log")
	}
}
