package main

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
)

func TestLocalDataStoreDownloadsOnlyMapsSelectedByWeb(t *testing.T) {
	objects := map[string][]byte{
		"index.json":    []byte(`{"schema_version":1,"maps":[{"id":"air_alpha","file":"air_alpha.bth"},{"id":"air_bravo","file":"air_bravo.bth"}]}`),
		"air_alpha.bth": []byte("alpha terrain"),
		"air_bravo.bth": []byte("bravo terrain"),
	}
	manifest := terrainManifest{
		SchemaVersion: 1, TerrainPackID: "terrain-v1", TerrainRevision: strings.Repeat("a", 64), MapCount: 2,
		Signature: terrainManifestSignature{Algorithm: "ed25519", KeyID: "test", Signature: "test"},
	}
	for path, payload := range objects {
		digest := digestBytes(payload)
		manifest.Files = append(manifest.Files, terrainManifestFile{Path: path, Asset: "Bomana_terrain_object_" + digest + extension(path), SHA256: digest, SizeBytes: int64(len(payload))})
		manifest.TotalSizeBytes += int64(len(payload))
	}
	redundant := []byte("signed manifest self-copy")
	redundantDigest := digestBytes(redundant)
	manifest.Files = append(manifest.Files, terrainManifestFile{Path: "manifest.json", Asset: "Bomana_terrain_object_" + redundantDigest + ".json", SHA256: redundantDigest, SizeBytes: int64(len(redundant))})
	manifest.TotalSizeBytes += int64(len(redundant))
	manifestBytes, _ := json.Marshal(manifest)
	var objectRequests atomic.Int32
	var rangeRequests atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		if request.URL.Path == "/terrain_manifest.json" {
			response.Header().Set("Content-Type", "application/json")
			_, _ = response.Write(manifestBytes)
			return
		}
		for path, payload := range objects {
			file := manifestFile(manifest, path)
			if request.URL.Path == "/objects/"+file.Asset {
				objectRequests.Add(1)
				if path == "air_alpha.bth" && request.Header.Get("Range") == "bytes=5-" {
					rangeRequests.Add(1)
					response.WriteHeader(http.StatusPartialContent)
					_, _ = response.Write(payload[5:])
					return
				}
				_, _ = response.Write(payload)
				return
			}
		}
		http.NotFound(response, request)
	}))
	defer server.Close()
	manifestURL, _ := url.Parse(server.URL + "/terrain_manifest.json")
	root := t.TempDir()
	store, err := newLocalDataStore(root, manifestURL, server.Client(), func(terrainManifest) error { return nil })
	if err != nil {
		t.Fatal(err)
	}
	rogueDigest := strings.Repeat("f", 64)
	if err := os.WriteFile(store.objectPath(rogueDigest), []byte("not terrain"), 0o600); err != nil {
		t.Fatal(err)
	}
	alpha := manifestFile(manifest, "air_alpha.bth")
	if err := os.WriteFile(store.objectPath(alpha.SHA256)+".part", objects["air_alpha.bth"][:5], 0o600); err != nil {
		t.Fatal(err)
	}
	store.syncOnce(context.Background())
	status := store.Status()
	if status.State != "ready" || status.MapCount != 2 || status.SelectedMapCount != 0 || status.CachedMapCount != 0 || status.CachedObjects != 1 {
		t.Fatalf("unexpected cache status: %#v", status)
	}
	if objectRequests.Load() != 1 {
		t.Fatalf("Bridge downloaded terrain before Web selection: requests=%d", objectRequests.Load())
	}
	if err := store.SetSelectedMaps([]string{"air_alpha"}); err != nil {
		t.Fatal(err)
	}
	store.syncOnce(context.Background())
	status = store.Status()
	if status.State != "ready" || status.SelectedMapCount != 1 || status.CachedMapCount != 1 {
		t.Fatalf("selected terrain was not cached: %#v", status)
	}
	firstRequests := objectRequests.Load()
	store.syncOnce(context.Background())
	if objectRequests.Load() != firstRequests {
		t.Fatalf("verified objects were downloaded again: before=%d after=%d", firstRequests, objectRequests.Load())
	}
	if rangeRequests.Load() != 1 {
		t.Fatalf("partial object was not resumed: range requests=%d", rangeRequests.Load())
	}
	if requests := objectRequests.Load(); requests != 2 {
		t.Fatalf("unselected terrain was downloaded: requests=%d", requests)
	}
	if _, err := os.Stat(store.objectPath(rogueDigest)); !os.IsNotExist(err) {
		t.Fatalf("non-terrain Bridge object was not pruned: %v", err)
	}
	server.Close()
	offline, err := newLocalDataStore(root, manifestURL, server.Client(), func(terrainManifest) error { return nil })
	if err != nil {
		t.Fatal(err)
	}
	offlineStatus := offline.Status()
	if offlineStatus.SelectedMapCount != 1 || offlineStatus.SelectedCachedMapCount != 1 {
		t.Fatalf("persisted terrain selection was not restored: %#v", offlineStatus)
	}
	file, _, err := offline.ReadObject(alpha.SHA256)
	if err != nil {
		t.Fatalf("verified cached terrain was unavailable offline: %v", err)
	}
	file.Close()
	offline.syncOnce(context.Background())
	if offline.Status().State != "degraded" {
		t.Fatalf("offline refresh did not report degraded state: %#v", offline.Status())
	}
	file, _, err = offline.ReadObject(alpha.SHA256)
	if err != nil {
		t.Fatalf("offline refresh discarded the restored allowlist: %v", err)
	}
	file.Close()
}

func TestDefaultTerrainRootMigratesLegacyCacheAndWritesBilingualReadme(t *testing.T) {
	cacheRoot := t.TempDir()
	legacyRoot := filepath.Join(cacheRoot, "Bomana", "BridgeCache", "v1")
	if err := os.MkdirAll(filepath.Join(legacyRoot, "objects"), 0o700); err != nil {
		t.Fatal(err)
	}
	marker := filepath.Join(legacyRoot, "objects", strings.Repeat("a", 64))
	if err := os.WriteFile(marker, []byte("cached terrain"), 0o600); err != nil {
		t.Fatal(err)
	}

	terrainRoot, err := prepareDefaultTerrainRoot(cacheRoot)
	if err != nil {
		t.Fatal(err)
	}
	expectedRoot := filepath.Join(cacheRoot, "Bomana", "BomanaTerrain")
	if terrainRoot != expectedRoot {
		t.Fatalf("terrain root=%q want %q", terrainRoot, expectedRoot)
	}
	if _, err := os.Stat(filepath.Join(terrainRoot, "objects", strings.Repeat("a", 64))); err != nil {
		t.Fatalf("legacy cached object was not migrated: %v", err)
	}
	if _, err := os.Stat(legacyRoot); !os.IsNotExist(err) {
		t.Fatalf("legacy terrain root remains after migration: %v", err)
	}
	readmePath := filepath.Join(terrainRoot, terrainReadmeFileName)
	readme, err := os.ReadFile(readmePath)
	if err != nil {
		t.Fatal(err)
	}
	for _, expected := range []string{"请勿删除", "DO NOT delete", "签名地形数据", "signed terrain maps", "SHA256", "不会影响游戏文件", "does not change the game"} {
		if !strings.Contains(string(readme), expected) {
			t.Fatalf("terrain README missing %q: %s", expected, readme)
		}
	}
	if err := os.WriteFile(readmePath, []byte("user note"), 0o644); err != nil {
		t.Fatal(err)
	}
	if _, err := prepareDefaultTerrainRoot(cacheRoot); err != nil {
		t.Fatal(err)
	}
	preserved, err := os.ReadFile(readmePath)
	if err != nil || string(preserved) != "user note" {
		t.Fatalf("existing terrain README was overwritten: data=%q err=%v", preserved, err)
	}
}

func TestLocalDataStoreRejectsIndexOutsideSignedMapClosure(t *testing.T) {
	index := []byte(`{"schema_version":1,"maps":[{"id":"air_alpha","file":"air_unknown.bth"}]}`)
	terrain := []byte("alpha terrain")
	manifest := terrainManifest{
		SchemaVersion: 1, TerrainPackID: "terrain-v1", TerrainRevision: strings.Repeat("a", 64), MapCount: 1,
		Signature: terrainManifestSignature{Algorithm: "ed25519", KeyID: "test", Signature: "test"},
	}
	for path, payload := range map[string][]byte{"index.json": index, "air_alpha.bth": terrain} {
		digest := digestBytes(payload)
		manifest.Files = append(manifest.Files, terrainManifestFile{Path: path, Asset: "Bomana_terrain_object_" + digest + extension(path), SHA256: digest, SizeBytes: int64(len(payload))})
		manifest.TotalSizeBytes += int64(len(payload))
	}
	manifestBytes, _ := json.Marshal(manifest)
	server := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		if request.URL.Path == "/terrain_manifest.json" {
			_, _ = response.Write(manifestBytes)
			return
		}
		file := manifestFile(manifest, "index.json")
		if request.URL.Path == "/objects/"+file.Asset {
			_, _ = response.Write(index)
			return
		}
		http.NotFound(response, request)
	}))
	defer server.Close()
	manifestURL, _ := url.Parse(server.URL + "/terrain_manifest.json")
	store, err := newLocalDataStore(t.TempDir(), manifestURL, server.Client(), func(terrainManifest) error { return nil })
	if err != nil {
		t.Fatal(err)
	}
	store.syncOnce(context.Background())
	if store.Status().State != "degraded" || len(store.mapFiles) != 0 {
		t.Fatalf("invalid terrain index was accepted: %#v", store.Status())
	}
	if _, err := os.Stat(filepath.Join(store.root, terrainCatalogFileName)); !os.IsNotExist(err) {
		t.Fatalf("invalid catalog was persisted: %v", err)
	}
}

func TestReplaceFileOverwritesAnExistingDestination(t *testing.T) {
	root := t.TempDir()
	source := filepath.Join(root, "source.tmp")
	destination := filepath.Join(root, "destination.json")
	if err := os.WriteFile(source, []byte("new"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(destination, []byte("old"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := replaceFile(source, destination); err != nil {
		t.Fatal(err)
	}
	data, err := os.ReadFile(destination)
	if err != nil || string(data) != "new" {
		t.Fatalf("destination was not atomically replaced: data=%q err=%v", data, err)
	}
	if _, err := os.Stat(source); !os.IsNotExist(err) {
		t.Fatalf("replacement source still exists: %v", err)
	}
}

func TestLocalDataStoreKeepsInFlightUploadTempsWhilePruningUnknownObjects(t *testing.T) {
	manifestURL, _ := url.Parse("http://127.0.0.1/terrain_manifest.json")
	store, err := newLocalDataStore(t.TempDir(), manifestURL, http.DefaultClient, func(terrainManifest) error { return nil })
	if err != nil {
		t.Fatal(err)
	}
	payload := []byte("verified terrain object")
	digest := digestBytes(payload)
	allowed := terrainManifestFile{Path: "air_test.bth", Asset: "Bomana_terrain_object_" + digest + ".bth", SHA256: digest, SizeBytes: int64(len(payload))}
	store.beginManifest(terrainManifest{TerrainRevision: strings.Repeat("a", 64), MapCount: 1}, []terrainManifestFile{allowed})
	store.applyTerrainIndex(map[string]string{"air_test": "air_test.bth"})
	if err := store.SetSelectedMaps([]string{"air_test"}); err != nil {
		t.Fatal(err)
	}
	upload := filepath.Join(store.root, "objects", digest+"-123.upload")
	if err := os.WriteFile(upload, []byte("partial-upload"), 0o600); err != nil {
		t.Fatal(err)
	}
	rogue := store.objectPath(strings.Repeat("f", 64))
	if err := os.WriteFile(rogue, []byte("not terrain"), 0o600); err != nil {
		t.Fatal(err)
	}
	store.pruneUnknownObjects()
	if _, err := os.Stat(upload); err != nil {
		t.Fatalf("in-flight upload temp was pruned: %v", err)
	}
	if _, err := os.Stat(rogue); !os.IsNotExist(err) {
		t.Fatalf("unknown cache object was kept: %v", err)
	}
}

func TestLocalDataStoreAcceptsOnlyContentAddressedBrowserObjects(t *testing.T) {
	manifestURL, _ := url.Parse("http://127.0.0.1/terrain_manifest.json")
	store, err := newLocalDataStore(t.TempDir(), manifestURL, http.DefaultClient, func(terrainManifest) error { return nil })
	if err != nil {
		t.Fatal(err)
	}
	payload := []byte("verified browser object")
	digest := digestBytes(payload)
	allowed := terrainManifestFile{Path: "air_test.bth", Asset: "Bomana_terrain_object_" + digest + ".bth", SHA256: digest, SizeBytes: int64(len(payload))}
	store.beginManifest(terrainManifest{TerrainRevision: strings.Repeat("a", 64), MapCount: 1}, []terrainManifestFile{allowed})
	store.applyTerrainIndex(map[string]string{"air_test": "air_test.bth"})
	if err := store.SetSelectedMaps([]string{"air_test"}); err != nil {
		t.Fatal(err)
	}
	if err := store.PutObject(context.Background(), digest, bytes.NewReader(payload)); err != nil {
		t.Fatal(err)
	}
	file, _, err := store.ReadObject(digest)
	if err != nil {
		t.Fatal(err)
	}
	file.Close()
	if err := store.PutObject(context.Background(), strings.Repeat("b", 64), bytes.NewReader(payload)); err == nil {
		t.Fatal("object outside the signed terrain allowlist was accepted")
	}
	if err := store.RemoveObject(digest); err != nil {
		t.Fatal(err)
	}
	if _, _, err := store.ReadObject(digest); !os.IsNotExist(err) {
		t.Fatalf("removed object remains readable: %v", err)
	}
}

func TestLiveTerrainManifestUsesATrustedSignature(t *testing.T) {
	if os.Getenv("BOMANA_LIVE_TERRAIN_MANIFEST") != "1" {
		t.Skip("set BOMANA_LIVE_TERRAIN_MANIFEST=1 for the production manifest check")
	}
	store, err := openDefaultLocalDataStore()
	if err != nil {
		t.Fatal(err)
	}
	manifest, _, err := store.fetchManifest(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if manifest.MapCount < 1 || len(manifest.Files) < manifest.MapCount {
		t.Fatalf("production terrain manifest is incomplete: %#v", manifest)
	}
}

func TestTerrainManifestRejectsEnhancedImplementationObjects(t *testing.T) {
	index := []byte(`{"schema_version":1,"maps":[]}`)
	terrain := []byte("terrain")
	solver := []byte("wasm")
	files := []terrainManifestFile{
		{Path: "index.json", Asset: "Bomana_terrain_object_" + digestBytes(index) + ".json", SHA256: digestBytes(index), SizeBytes: int64(len(index))},
		{Path: "air_test.bth", Asset: "Bomana_terrain_object_" + digestBytes(terrain) + ".bth", SHA256: digestBytes(terrain), SizeBytes: int64(len(terrain))},
		{Path: "solver.wasm", Asset: "Bomana_terrain_object_" + digestBytes(solver) + ".wasm", SHA256: digestBytes(solver), SizeBytes: int64(len(solver))},
	}
	manifest := terrainManifest{
		SchemaVersion: 1, TerrainPackID: "terrain-v1", TerrainRevision: strings.Repeat("a", 64), MapCount: 1,
		Files: files, Signature: terrainManifestSignature{Algorithm: "ed25519", KeyID: "test", Signature: "test"},
	}
	for _, file := range files {
		manifest.TotalSizeBytes += file.SizeBytes
	}
	if err := validateTerrainManifest(manifest); err == nil || !strings.Contains(err.Error(), "non-terrain") {
		t.Fatalf("Enhanced implementation object was admitted: %v", err)
	}
}

func digestBytes(payload []byte) string {
	digest := sha256.Sum256(payload)
	return hex.EncodeToString(digest[:])
}

func extension(path string) string {
	if len(path) >= 4 && path[len(path)-4:] == ".bth" {
		return ".bth"
	}
	return ".json"
}

func manifestFile(manifest terrainManifest, path string) terrainManifestFile {
	for _, file := range manifest.Files {
		if file.Path == path {
			return file
		}
	}
	return terrainManifestFile{}
}
