package main

import (
	"bytes"
	"encoding/json"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"net/url"
	"path/filepath"
	"strings"
	"testing"
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
	for _, expected := range []string{`"bridge_protocol":1`, `"cache_protocol":4`, `"mobile_pairing_protocol":6`, `"bridge_version":"development"`, `"app_web_version":"development"`, `"input":"official-8111-only"`, `"write_commands":false`, `"authenticode":false`} {
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
