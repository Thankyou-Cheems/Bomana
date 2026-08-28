package main

import (
	"bytes"
	"context"
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"
)

const (
	defaultTerrainManifestURL = "https://bomanaupdate.ruikang.wang/downloads/terrain/terrain_manifest.json"
	maxCacheObjectBytes       = 256 * 1024 * 1024
	cacheSyncInterval         = 6 * time.Hour
	cacheDownloadWorkers      = 4
	terrainSelectionFileName  = "terrain-selection.json"
	terrainCatalogFileName    = "terrain-catalog.json"
	terrainReadmeFileName     = "README_请勿删除_DO_NOT_DELETE.txt"
)

const terrainReadmeText = "" +
	"BomanaTerrain 本机地形数据 / Local Terrain Data\r\n" +
	"=====================================================\r\n\r\n" +
	"此目录由 Bomana Bridge 自动管理，用于保存用户选择的签名地形数据。\r\n" +
	"这些文件供地形高度、投放解算和机场模块定位使用。\r\n" +
	"所有地形对象都会按签名目录、文件大小和 SHA256 校验。\r\n\r\n" +
	"请勿删除、移动、重命名或修改此目录及其中的文件。\r\n" +
	"删除不会影响游戏文件，但会使相关地图不可用，并需要重新下载。\r\n\r\n" +
	"This folder is managed automatically by Bomana Bridge and stores the signed terrain maps selected by the user.\r\n" +
	"The files are used for terrain elevation, release calculations, and airfield-module positioning.\r\n" +
	"Every terrain object is verified against its signed catalog, exact size, and SHA256 digest.\r\n\r\n" +
	"DO NOT delete, move, rename, edit, or replace this folder or its contents.\r\n" +
	"Deleting it does not change the game, but terrain features will become unavailable and the data must be downloaded again.\r\n"

var terrainManifestPublicKeys = map[string]string{
	"bomana-offline-2026-v1":    "zSMo0z0dAKYP2j0pV68vJ0NvtonEV1CVyMWz/f5Rd6s=",
	"bomana-release-2026-08":    "e7rY61GzljHbvmENVUkGfo82UNS8hUkDnr6kANG6J6o=",
	"bomana-release-2026-08-v2": "zSMo0z0dAKYP2j0pV68vJ0NvtonEV1CVyMWz/f5Rd6s=",
}

type terrainManifestFile struct {
	Path      string `json:"path"`
	Asset     string `json:"asset"`
	SHA256    string `json:"sha256"`
	SizeBytes int64  `json:"size_bytes"`
}

type terrainManifestSignature struct {
	Algorithm string `json:"algorithm"`
	KeyID     string `json:"key_id"`
	Signature string `json:"signature"`
}

type terrainManifest struct {
	SchemaVersion   int                      `json:"schema_version"`
	TerrainPackID   string                   `json:"terrain_pack_id"`
	TerrainRevision string                   `json:"terrain_revision"`
	MapCount        int                      `json:"map_count"`
	TotalSizeBytes  int64                    `json:"total_size_bytes"`
	Files           []terrainManifestFile    `json:"files"`
	Signature       terrainManifestSignature `json:"manifest_signature"`
}

type mapCacheStatus struct {
	ID          string `json:"id"`
	State       string `json:"state"`
	CachedBytes int64  `json:"cached_bytes"`
	TotalBytes  int64  `json:"total_bytes"`
	Error       string `json:"error,omitempty"`
	Selected    bool   `json:"selected"`
}

type localCacheStatus struct {
	SchemaVersion          int              `json:"schema_version"`
	State                  string           `json:"state"`
	Revision               string           `json:"revision,omitempty"`
	MapCount               int              `json:"map_count"`
	CachedMapCount         int              `json:"cached_map_count"`
	SelectedMapCount       int              `json:"selected_map_count"`
	SelectedCachedMapCount int              `json:"selected_cached_map_count"`
	ObjectCount            int              `json:"object_count"`
	CachedObjects          int              `json:"cached_object_count"`
	TotalBytes             int64            `json:"total_bytes"`
	CachedBytes            int64            `json:"cached_bytes"`
	Maps                   []mapCacheStatus `json:"maps"`
	LastCheckedAt          string           `json:"last_checked_at,omitempty"`
	Error                  string           `json:"error,omitempty"`
}

type cacheFileProgress struct {
	file        terrainManifestFile
	cachedBytes int64
	state       string
	err         string
	selected    bool
}

type terrainSelection struct {
	SchemaVersion int      `json:"schema_version"`
	MapIDs        []string `json:"map_ids"`
}

type terrainIndex struct {
	SchemaVersion int               `json:"schema_version"`
	Maps          []terrainIndexMap `json:"maps"`
}

type terrainIndexMap struct {
	ID   string `json:"id"`
	File string `json:"file"`
}

type localDataStore struct {
	root        string
	manifestURL *url.URL
	client      *http.Client
	verify      func(terrainManifest) error

	mu            sync.RWMutex
	selectionMu   sync.Mutex
	state         string
	revision      string
	mapCount      int
	totalBytes    int64
	lastCheckedAt time.Time
	lastError     string
	files         map[string]*cacheFileProgress
	selectedMaps  map[string]struct{}
	mapFiles      map[string]string
	syncRequests  chan struct{}
}

type localCatalogSnapshot struct {
	revision   string
	mapCount   int
	totalBytes int64
	files      map[string]*cacheFileProgress
	mapFiles   map[string]string
}

func openDefaultLocalDataStore() (*localDataStore, error) {
	cacheRoot, err := os.UserCacheDir()
	if err != nil {
		return nil, err
	}
	terrainRoot, err := prepareDefaultTerrainRoot(cacheRoot)
	if err != nil {
		return nil, err
	}
	manifestURL, _ := url.Parse(defaultTerrainManifestURL)
	transport := http.DefaultTransport.(*http.Transport).Clone()
	return newLocalDataStore(
		terrainRoot,
		manifestURL,
		&http.Client{
			Transport: transport,
			Timeout:   30 * time.Minute,
			CheckRedirect: func(_ *http.Request, _ []*http.Request) error {
				return http.ErrUseLastResponse
			},
		},
		verifyTerrainManifestSignature,
	)
}

func prepareDefaultTerrainRoot(cacheRoot string) (string, error) {
	bomanaRoot := filepath.Join(cacheRoot, "Bomana")
	terrainRoot := filepath.Join(bomanaRoot, "BomanaTerrain")
	legacyRoot := filepath.Join(bomanaRoot, "BridgeCache", "v1")
	if _, err := os.Stat(terrainRoot); errors.Is(err, os.ErrNotExist) {
		if legacyInfo, legacyErr := os.Stat(legacyRoot); legacyErr == nil && legacyInfo.IsDir() {
			if err := os.MkdirAll(bomanaRoot, 0o700); err != nil {
				return "", err
			}
			if err := os.Rename(legacyRoot, terrainRoot); err != nil {
				return "", fmt.Errorf("migrate legacy terrain cache: %w", err)
			}
			_ = os.Remove(filepath.Dir(legacyRoot))
		} else if legacyErr != nil && !errors.Is(legacyErr, os.ErrNotExist) {
			return "", legacyErr
		}
	} else if err != nil {
		return "", err
	}
	if err := os.MkdirAll(terrainRoot, 0o700); err != nil {
		return "", err
	}
	if err := ensureTerrainReadme(filepath.Join(terrainRoot, terrainReadmeFileName)); err != nil {
		return "", err
	}
	return terrainRoot, nil
}

func ensureTerrainReadme(path string) error {
	file, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o644)
	if errors.Is(err, os.ErrExist) {
		return nil
	}
	if err != nil {
		return err
	}
	if _, err := file.WriteString(terrainReadmeText); err != nil {
		file.Close()
		return err
	}
	if err := file.Sync(); err != nil {
		file.Close()
		return err
	}
	return file.Close()
}

func newLocalDataStore(root string, manifestURL *url.URL, client *http.Client, verify func(terrainManifest) error) (*localDataStore, error) {
	if manifestURL == nil || manifestURL.Scheme != "https" && !isLoopbackHost(manifestURL.Hostname()) {
		return nil, errors.New("cache manifest URL must use HTTPS or loopback HTTP")
	}
	if client == nil || verify == nil {
		return nil, errors.New("cache dependencies are required")
	}
	resolvedRoot, err := filepath.Abs(root)
	if err != nil {
		return nil, err
	}
	if err := os.MkdirAll(filepath.Join(resolvedRoot, "objects"), 0o700); err != nil {
		return nil, err
	}
	store := &localDataStore{
		root: resolvedRoot, manifestURL: manifestURL, client: client, verify: verify,
		state: "checking", files: make(map[string]*cacheFileProgress),
		selectedMaps: make(map[string]struct{}), mapFiles: make(map[string]string), syncRequests: make(chan struct{}, 1),
	}
	selected, err := loadTerrainSelection(filepath.Join(resolvedRoot, terrainSelectionFileName))
	if err != nil {
		return nil, err
	}
	store.selectedMaps = selected
	store.restoreCachedCatalog()
	return store, nil
}

func (store *localDataStore) Start(ctx context.Context) {
	go func() {
		store.syncOnce(ctx)
		ticker := time.NewTicker(cacheSyncInterval)
		defer ticker.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-ticker.C:
				store.syncOnce(ctx)
			case <-store.syncRequests:
				store.syncOnce(ctx)
			}
		}
	}()
}

func (store *localDataStore) SetSelectedMaps(mapIDs []string) error {
	store.selectionMu.Lock()
	defer store.selectionMu.Unlock()
	selected := make(map[string]struct{}, len(mapIDs))
	store.mu.RLock()
	known := make(map[string]string, len(store.mapFiles))
	for mapID, path := range store.mapFiles {
		known[mapID] = path
	}
	store.mu.RUnlock()
	if len(known) == 0 {
		return errors.New("terrain manifest is not ready")
	}
	for _, mapID := range mapIDs {
		if !validTerrainMapID(mapID) {
			return fmt.Errorf("terrain map id is invalid: %s", mapID)
		}
		if _, exists := known[mapID]; !exists {
			return fmt.Errorf("terrain map is not in the signed manifest: %s", mapID)
		}
		selected[mapID] = struct{}{}
	}
	ordered := make([]string, 0, len(selected))
	for mapID := range selected {
		ordered = append(ordered, mapID)
	}
	sort.Strings(ordered)
	if err := saveTerrainSelection(filepath.Join(store.root, terrainSelectionFileName), ordered); err != nil {
		return err
	}
	store.mu.Lock()
	store.selectedMaps = selected
	for mapID, path := range store.mapFiles {
		progress := store.files[path]
		if progress == nil {
			continue
		}
		_, progress.selected = selected[mapID]
		if !progress.selected && progress.state != "cached" {
			progress.state, progress.cachedBytes, progress.err = "not-selected", 0, ""
		}
		if progress.selected && progress.state == "not-selected" {
			progress.state = "pending"
		}
	}
	store.totalBytes = 0
	for _, progress := range store.files {
		if progress.selected {
			store.totalBytes += progress.file.SizeBytes
		}
	}
	store.mu.Unlock()
	select {
	case store.syncRequests <- struct{}{}:
	default:
	}
	return nil
}

func (store *localDataStore) filesToDownload(files []terrainManifestFile) []terrainManifestFile {
	store.mu.RLock()
	defer store.mu.RUnlock()
	result := make([]terrainManifestFile, 0, len(files))
	for _, file := range files {
		progress := store.files[file.Path]
		if progress != nil && progress.selected {
			result = append(result, file)
		}
	}
	return result
}

func (store *localDataStore) syncOnce(ctx context.Context) {
	store.setChecking()
	manifest, manifestBytes, err := store.fetchManifest(ctx)
	if err != nil {
		store.setSyncError(err)
		return
	}
	files := cacheableManifestFiles(manifest.Files)
	previous := store.catalogSnapshot()
	store.beginManifest(manifest, files)
	indexFile, exists := manifestFileByPath(files, "index.json")
	if !exists {
		store.restoreCatalogAfterFailure(previous, errors.New("terrain manifest is missing index.json"))
		return
	}
	if err := store.ensureManifestFile(ctx, indexFile); err != nil {
		store.updateFile(indexFile.Path, 0, "error", err.Error())
		store.restoreCatalogAfterFailure(previous, err)
		return
	}
	mapFiles, err := store.readVerifiedTerrainIndex(indexFile, manifest.MapCount, files)
	if err != nil {
		store.restoreCatalogAfterFailure(previous, err)
		return
	}
	store.applyTerrainIndex(mapFiles)
	if err := saveVerifiedCatalog(filepath.Join(store.root, terrainCatalogFileName), manifestBytes); err != nil {
		store.restoreCatalogAfterFailure(previous, err)
		return
	}
	store.pruneUnknownObjects()
	jobs := make(chan terrainManifestFile)
	var workers sync.WaitGroup
	for range cacheDownloadWorkers {
		workers.Add(1)
		go func() {
			defer workers.Done()
			for file := range jobs {
				if err := store.ensureManifestFile(ctx, file); err != nil {
					store.updateFile(file.Path, 0, "error", err.Error())
				}
			}
		}()
	}
	for _, file := range store.filesToDownload(files) {
		select {
		case jobs <- file:
		case <-ctx.Done():
			close(jobs)
			workers.Wait()
			store.setSyncError(ctx.Err())
			return
		}
	}
	close(jobs)
	workers.Wait()
	store.finishSync()
}

func (store *localDataStore) Status() localCacheStatus {
	store.mu.RLock()
	defer store.mu.RUnlock()
	status := localCacheStatus{
		SchemaVersion: 1, State: store.state, Revision: store.revision, MapCount: store.mapCount,
		ObjectCount: len(store.files), TotalBytes: store.totalBytes, Error: store.lastError,
		Maps: make([]mapCacheStatus, 0, store.mapCount),
	}
	if !store.lastCheckedAt.IsZero() {
		status.LastCheckedAt = store.lastCheckedAt.UTC().Format(time.RFC3339)
	}
	for _, progress := range store.files {
		if progress.selected {
			status.CachedBytes += min(progress.cachedBytes, progress.file.SizeBytes)
		}
		if progress.state == "cached" {
			status.CachedObjects++
		}
	}
	for mapID, path := range store.mapFiles {
		progress := store.files[path]
		if progress == nil {
			continue
		}
		mapStatus := mapCacheStatus{
			ID: mapID, State: progress.state,
			CachedBytes: min(progress.cachedBytes, progress.file.SizeBytes), TotalBytes: progress.file.SizeBytes, Error: progress.err,
			Selected: progress.selected,
		}
		status.Maps = append(status.Maps, mapStatus)
		if progress.state == "cached" {
			status.CachedMapCount++
		}
		if progress.selected {
			status.SelectedMapCount++
			if progress.state == "cached" {
				status.SelectedCachedMapCount++
			}
		}
	}
	sort.Slice(status.Maps, func(i, j int) bool { return status.Maps[i].ID < status.Maps[j].ID })
	return status
}

func (store *localDataStore) ReadObject(digest string) (*os.File, os.FileInfo, error) {
	if !validSHA256(digest) || !store.allowsDigest(digest) {
		return nil, nil, os.ErrNotExist
	}
	file, err := os.Open(store.objectPath(digest))
	if err != nil {
		return nil, nil, err
	}
	info, err := file.Stat()
	if err != nil {
		file.Close()
		return nil, nil, err
	}
	return file, info, nil
}

func (store *localDataStore) ReadCatalog() ([]byte, error) {
	data, err := os.ReadFile(filepath.Join(store.root, terrainCatalogFileName))
	if err != nil {
		return nil, err
	}
	if len(data) == 0 || len(data) > 4*1024*1024 {
		return nil, errors.New("terrain catalog is unavailable or oversized")
	}
	var manifest terrainManifest
	if err := json.Unmarshal(data, &manifest); err != nil {
		return nil, errors.New("terrain catalog is invalid")
	}
	if err := validateTerrainManifest(manifest); err != nil {
		return nil, err
	}
	if err := store.verify(manifest); err != nil {
		return nil, err
	}
	return data, nil
}

func (store *localDataStore) PutObject(ctx context.Context, digest string, body io.Reader) error {
	if !validSHA256(digest) || !store.allowsDigest(digest) {
		return errors.New("cache digest is invalid")
	}
	temporary, err := os.CreateTemp(filepath.Join(store.root, "objects"), digest+"-*.upload")
	if err != nil {
		return err
	}
	temporaryPath := temporary.Name()
	defer os.Remove(temporaryPath)
	hash := sha256.New()
	written, copyErr := io.Copy(io.MultiWriter(temporary, hash), io.LimitReader(body, maxCacheObjectBytes+1))
	closeErr := temporary.Close()
	if copyErr != nil || closeErr != nil {
		return errors.Join(copyErr, closeErr)
	}
	if written <= 0 || written > maxCacheObjectBytes || hex.EncodeToString(hash.Sum(nil)) != digest {
		return errors.New("cache object verification failed")
	}
	if err := ctx.Err(); err != nil {
		return err
	}
	return replaceFile(temporaryPath, store.objectPath(digest))
}

func (store *localDataStore) RemoveObject(digest string) error {
	if !validSHA256(digest) || !store.allowsDigest(digest) {
		return os.ErrNotExist
	}
	err := os.Remove(store.objectPath(digest))
	if errors.Is(err, os.ErrNotExist) {
		return nil
	}
	return err
}

func (store *localDataStore) allowsDigest(digest string) bool {
	store.mu.RLock()
	defer store.mu.RUnlock()
	for _, progress := range store.files {
		if progress.file.SHA256 == digest && (progress.selected || !strings.HasSuffix(progress.file.Path, ".bth")) {
			return true
		}
	}
	return false
}

func (store *localDataStore) pruneUnknownObjects() {
	store.mu.RLock()
	allowed := make(map[string]struct{}, len(store.files))
	for _, progress := range store.files {
		allowed[progress.file.SHA256] = struct{}{}
	}
	store.mu.RUnlock()
	entries, err := os.ReadDir(filepath.Join(store.root, "objects"))
	if err != nil {
		return
	}
	for _, entry := range entries {
		if entry.IsDir() {
			continue
		}
		name := entry.Name()
		if strings.HasSuffix(name, ".upload") {
			continue
		}
		digest := strings.TrimSuffix(name, ".part")
		if validSHA256(digest) {
			if _, keep := allowed[digest]; keep {
				continue
			}
		}
		_ = os.Remove(filepath.Join(store.root, "objects", name))
	}
}

func (store *localDataStore) fetchManifest(ctx context.Context) (terrainManifest, []byte, error) {
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, store.manifestURL.String(), nil)
	if err != nil {
		return terrainManifest{}, nil, err
	}
	request.Header.Set("Accept", "application/json")
	response, err := store.client.Do(request)
	if err != nil {
		return terrainManifest{}, nil, err
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return terrainManifest{}, nil, fmt.Errorf("terrain manifest HTTP %d", response.StatusCode)
	}
	data, err := io.ReadAll(io.LimitReader(response.Body, 4*1024*1024+1))
	if err != nil || len(data) > 4*1024*1024 {
		return terrainManifest{}, nil, errors.New("terrain manifest is unavailable or oversized")
	}
	var manifest terrainManifest
	if err := json.Unmarshal(data, &manifest); err != nil {
		return terrainManifest{}, nil, err
	}
	if err := validateTerrainManifest(manifest); err != nil {
		return terrainManifest{}, nil, err
	}
	if err := store.verify(manifest); err != nil {
		return terrainManifest{}, nil, err
	}
	return manifest, data, nil
}

func (store *localDataStore) ensureManifestFile(ctx context.Context, file terrainManifestFile) error {
	destination := store.objectPath(file.SHA256)
	if valid, _ := verifyDiskObject(destination, file.SizeBytes, file.SHA256); valid {
		store.updateFile(file.Path, file.SizeBytes, "cached", "")
		return nil
	}
	_ = os.Remove(destination)
	partial := destination + ".part"
	offset := int64(0)
	if info, err := os.Stat(partial); err == nil && info.Size() > 0 && info.Size() < file.SizeBytes {
		offset = info.Size()
	} else if err == nil {
		_ = os.Remove(partial)
	}
	store.updateFile(file.Path, offset, "downloading", "")
	assetURL := *store.manifestURL
	assetURL.Path = strings.TrimSuffix(filepath.ToSlash(filepath.Dir(assetURL.Path)), "/") + "/objects/" + file.Asset
	assetURL.RawQuery, assetURL.Fragment = "", ""
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, assetURL.String(), nil)
	if err != nil {
		return err
	}
	if offset > 0 {
		request.Header.Set("Range", fmt.Sprintf("bytes=%d-", offset))
	}
	response, err := store.client.Do(request)
	if err != nil {
		return err
	}
	defer response.Body.Close()
	flags := os.O_CREATE | os.O_WRONLY
	if offset > 0 && response.StatusCode == http.StatusPartialContent {
		flags |= os.O_APPEND
	} else if response.StatusCode == http.StatusOK {
		flags |= os.O_TRUNC
		offset = 0
	} else {
		return fmt.Errorf("cache object HTTP %d", response.StatusCode)
	}
	output, err := os.OpenFile(partial, flags, 0o600)
	if err != nil {
		return err
	}
	buffer := make([]byte, 128*1024)
	received := offset
	for {
		count, readErr := response.Body.Read(buffer)
		if count > 0 {
			received += int64(count)
			if received > file.SizeBytes {
				output.Close()
				return errors.New("cache object exceeded manifest size")
			}
			if _, err := output.Write(buffer[:count]); err != nil {
				output.Close()
				return err
			}
			store.updateFile(file.Path, received, "downloading", "")
		}
		if errors.Is(readErr, io.EOF) {
			break
		}
		if readErr != nil {
			output.Close()
			return readErr
		}
	}
	if err := output.Sync(); err != nil {
		output.Close()
		return err
	}
	if err := output.Close(); err != nil {
		return err
	}
	if valid, err := verifyDiskObject(partial, file.SizeBytes, file.SHA256); !valid {
		return errors.Join(errors.New("cache object verification failed"), err)
	}
	if err := replaceFile(partial, destination); err != nil {
		return err
	}
	store.updateFile(file.Path, file.SizeBytes, "cached", "")
	return nil
}

func (store *localDataStore) objectPath(digest string) string {
	return filepath.Join(store.root, "objects", digest)
}

func (store *localDataStore) setChecking() {
	store.mu.Lock()
	defer store.mu.Unlock()
	store.state, store.lastError = "checking", ""
}

func (store *localDataStore) beginManifest(manifest terrainManifest, files []terrainManifestFile) {
	store.mu.Lock()
	defer store.mu.Unlock()
	store.state, store.revision, store.mapCount = "syncing", manifest.TerrainRevision, manifest.MapCount
	store.totalBytes = 0
	store.files = make(map[string]*cacheFileProgress, len(files))
	store.mapFiles = make(map[string]string)
	for _, file := range files {
		copy := file
		selected := !strings.HasSuffix(file.Path, ".bth")
		state, cachedBytes := "pending", int64(0)
		if info, err := os.Stat(store.objectPath(file.SHA256)); err == nil && info.Size() == file.SizeBytes {
			state, cachedBytes = "cached", file.SizeBytes
		} else if strings.HasSuffix(file.Path, ".bth") && !selected {
			state = "not-selected"
		}
		store.files[file.Path] = &cacheFileProgress{file: copy, state: state, cachedBytes: cachedBytes, selected: selected}
		if selected {
			store.totalBytes += file.SizeBytes
		}
	}
}

func cacheableManifestFiles(files []terrainManifestFile) []terrainManifestFile {
	result := make([]terrainManifestFile, 0, len(files))
	for _, file := range files {
		// The signed top-level manifest is already authoritative. Historical
		// terrain-v1 catalogs also list a self-copy named manifest.json, which is
		// not a runtime object and is absent from the production object tree.
		if file.Path == "manifest.json" {
			continue
		}
		result = append(result, file)
	}
	return result
}

func manifestFileByPath(files []terrainManifestFile, path string) (terrainManifestFile, bool) {
	for _, file := range files {
		if file.Path == path {
			return file, true
		}
	}
	return terrainManifestFile{}, false
}

func (store *localDataStore) readVerifiedTerrainIndex(
	indexFile terrainManifestFile,
	mapCount int,
	files []terrainManifestFile,
) (map[string]string, error) {
	path := store.objectPath(indexFile.SHA256)
	if valid, err := verifyDiskObject(path, indexFile.SizeBytes, indexFile.SHA256); !valid {
		return nil, errors.Join(errors.New("terrain index verification failed"), err)
	}
	data, err := os.ReadFile(path)
	if err != nil || int64(len(data)) != indexFile.SizeBytes || len(data) > 4*1024*1024 {
		return nil, errors.New("terrain index is unavailable or oversized")
	}
	var index terrainIndex
	if err := json.Unmarshal(data, &index); err != nil || index.SchemaVersion != 1 || len(index.Maps) != mapCount {
		return nil, errors.New("terrain index structure is invalid")
	}
	bthFiles := make(map[string]struct{}, mapCount)
	for _, file := range files {
		if strings.HasSuffix(file.Path, ".bth") {
			bthFiles[file.Path] = struct{}{}
		}
	}
	mapFiles := make(map[string]string, mapCount)
	usedFiles := make(map[string]struct{}, mapCount)
	for _, item := range index.Maps {
		if !validTerrainMapID(item.ID) || filepath.Base(item.File) != item.File || !strings.HasSuffix(item.File, ".bth") {
			return nil, errors.New("terrain index map entry is invalid")
		}
		if _, exists := bthFiles[item.File]; !exists {
			return nil, errors.New("terrain index references an unsigned map object")
		}
		if _, duplicate := mapFiles[item.ID]; duplicate {
			return nil, errors.New("terrain index contains a duplicate map id")
		}
		if _, duplicate := usedFiles[item.File]; duplicate {
			return nil, errors.New("terrain index contains a duplicate map file")
		}
		mapFiles[item.ID] = item.File
		usedFiles[item.File] = struct{}{}
	}
	if len(usedFiles) != len(bthFiles) {
		return nil, errors.New("terrain index does not close over the signed map objects")
	}
	return mapFiles, nil
}

func (store *localDataStore) applyTerrainIndex(mapFiles map[string]string) {
	store.mu.Lock()
	defer store.mu.Unlock()
	store.mapFiles = mapFiles
	store.mapCount = len(mapFiles)
	store.totalBytes = 0
	for path, progress := range store.files {
		if !strings.HasSuffix(path, ".bth") {
			progress.selected = true
			store.totalBytes += progress.file.SizeBytes
			continue
		}
		progress.selected = false
		if progress.state != "cached" {
			progress.state, progress.cachedBytes, progress.err = "not-selected", 0, ""
		}
	}
	for mapID, path := range mapFiles {
		progress := store.files[path]
		if progress == nil {
			continue
		}
		if _, selected := store.selectedMaps[mapID]; selected {
			progress.selected = true
			store.totalBytes += progress.file.SizeBytes
			if progress.state == "not-selected" {
				progress.state = "pending"
			}
		}
	}
}

func (store *localDataStore) restoreCachedCatalog() {
	data, err := os.ReadFile(filepath.Join(store.root, terrainCatalogFileName))
	if errors.Is(err, os.ErrNotExist) {
		return
	}
	if err != nil || len(data) == 0 || len(data) > 4*1024*1024 {
		return
	}
	var manifest terrainManifest
	if err := json.Unmarshal(data, &manifest); err != nil || validateTerrainManifest(manifest) != nil || store.verify(manifest) != nil {
		return
	}
	files := cacheableManifestFiles(manifest.Files)
	indexFile, exists := manifestFileByPath(files, "index.json")
	if !exists {
		return
	}
	store.beginManifest(manifest, files)
	mapFiles, err := store.readVerifiedTerrainIndex(indexFile, manifest.MapCount, files)
	if err != nil {
		store.mu.Lock()
		store.files = make(map[string]*cacheFileProgress)
		store.mapFiles = make(map[string]string)
		store.mu.Unlock()
		return
	}
	store.applyTerrainIndex(mapFiles)
	store.mu.Lock()
	store.state = "ready"
	store.mu.Unlock()
}

func saveVerifiedCatalog(path string, data []byte) error {
	if len(data) == 0 || len(data) > 4*1024*1024 {
		return errors.New("terrain catalog is unavailable or oversized")
	}
	temporary, err := os.CreateTemp(filepath.Dir(path), ".terrain-catalog-*.tmp")
	if err != nil {
		return err
	}
	temporaryPath := temporary.Name()
	defer os.Remove(temporaryPath)
	if err := temporary.Chmod(0o600); err != nil {
		temporary.Close()
		return err
	}
	if _, err := temporary.Write(data); err != nil {
		temporary.Close()
		return err
	}
	if err := temporary.Sync(); err != nil {
		temporary.Close()
		return err
	}
	if err := temporary.Close(); err != nil {
		return err
	}
	return replaceFile(temporaryPath, path)
}

func loadTerrainSelection(path string) (map[string]struct{}, error) {
	selected := make(map[string]struct{})
	bytes, err := os.ReadFile(path)
	if errors.Is(err, os.ErrNotExist) {
		return selected, nil
	}
	if err != nil {
		return nil, err
	}
	var value terrainSelection
	if err := json.Unmarshal(bytes, &value); err != nil || value.SchemaVersion != 1 {
		return nil, errors.New("terrain selection is invalid")
	}
	for _, mapID := range value.MapIDs {
		if !validTerrainMapID(mapID) {
			return nil, errors.New("terrain selection contains an invalid map")
		}
		selected[mapID] = struct{}{}
	}
	return selected, nil
}

func saveTerrainSelection(path string, mapIDs []string) error {
	bytes, err := json.Marshal(terrainSelection{SchemaVersion: 1, MapIDs: mapIDs})
	if err != nil {
		return err
	}
	temporary, err := os.CreateTemp(filepath.Dir(path), ".terrain-selection-*.tmp")
	if err != nil {
		return err
	}
	temporaryPath := temporary.Name()
	defer os.Remove(temporaryPath)
	if err := temporary.Chmod(0o600); err != nil {
		temporary.Close()
		return err
	}
	if _, err := temporary.Write(bytes); err != nil {
		temporary.Close()
		return err
	}
	if err := temporary.Sync(); err != nil {
		temporary.Close()
		return err
	}
	if err := temporary.Close(); err != nil {
		return err
	}
	return replaceFile(temporaryPath, path)
}

func validTerrainMapID(value string) bool {
	if value == "" || len(value) > 96 {
		return false
	}
	for _, character := range value {
		if !(character >= 'a' && character <= 'z' || character >= 'A' && character <= 'Z' || character >= '0' && character <= '9' || character == '_' || character == '.' || character == '-') {
			return false
		}
	}
	return true
}

func (store *localDataStore) updateFile(path string, cachedBytes int64, state, message string) {
	store.mu.Lock()
	defer store.mu.Unlock()
	if progress := store.files[path]; progress != nil {
		progress.cachedBytes, progress.state, progress.err = cachedBytes, state, message
	}
}

func (store *localDataStore) finishSync() {
	store.mu.Lock()
	defer store.mu.Unlock()
	store.lastCheckedAt = time.Now()
	store.state, store.lastError = "ready", ""
	for _, progress := range store.files {
		if progress.selected && progress.state != "cached" {
			store.state = "degraded"
			if store.lastError == "" {
				store.lastError = "部分资源尚未完成缓存"
			}
		}
	}
}

func (store *localDataStore) setSyncError(err error) {
	store.mu.Lock()
	defer store.mu.Unlock()
	store.state, store.lastError, store.lastCheckedAt = "degraded", err.Error(), time.Now()
}

func (store *localDataStore) catalogSnapshot() localCatalogSnapshot {
	store.mu.RLock()
	defer store.mu.RUnlock()
	return localCatalogSnapshot{
		revision: store.revision, mapCount: store.mapCount, totalBytes: store.totalBytes,
		files: store.files, mapFiles: store.mapFiles,
	}
}

func (store *localDataStore) restoreCatalogAfterFailure(snapshot localCatalogSnapshot, err error) {
	if len(snapshot.files) == 0 || len(snapshot.mapFiles) == 0 {
		store.setSyncError(err)
		return
	}
	store.mu.Lock()
	defer store.mu.Unlock()
	store.state, store.lastError = "degraded", err.Error()
	store.revision, store.mapCount, store.totalBytes = snapshot.revision, snapshot.mapCount, snapshot.totalBytes
	store.lastCheckedAt = time.Now()
	store.files, store.mapFiles = snapshot.files, snapshot.mapFiles
}

func validateTerrainManifest(manifest terrainManifest) error {
	if manifest.SchemaVersion != 1 || manifest.TerrainPackID == "" || !validSHA256(manifest.TerrainRevision) || manifest.MapCount <= 0 || len(manifest.Files) < manifest.MapCount || manifest.TotalSizeBytes <= 0 {
		return errors.New("terrain manifest structure is invalid")
	}
	seen := make(map[string]struct{}, len(manifest.Files))
	var total int64
	bthCount := 0
	for _, file := range manifest.Files {
		if file.Path == "" || filepath.Base(file.Path) != file.Path || !validSHA256(file.SHA256) || file.SizeBytes <= 0 || file.SizeBytes > maxCacheObjectBytes {
			return errors.New("terrain manifest file is invalid")
		}
		expectedPrefix := "Bomana_terrain_object_" + file.SHA256 + "."
		if !strings.HasPrefix(file.Asset, expectedPrefix) || strings.ContainsAny(file.Asset, `/\\`) {
			return errors.New("terrain manifest asset is invalid")
		}
		switch {
		case file.Path == "index.json" || file.Path == "manifest.json":
			if !strings.HasSuffix(file.Asset, ".json") {
				return errors.New("terrain metadata asset type is invalid")
			}
		case strings.HasSuffix(file.Path, ".bth"):
			if !strings.HasSuffix(file.Asset, ".bth") {
				return errors.New("terrain grid asset type is invalid")
			}
			bthCount++
		default:
			return errors.New("terrain manifest contains a non-terrain object")
		}
		if _, duplicate := seen[file.Path]; duplicate {
			return errors.New("terrain manifest contains duplicate paths")
		}
		seen[file.Path] = struct{}{}
		total += file.SizeBytes
	}
	if total != manifest.TotalSizeBytes || bthCount != manifest.MapCount || manifest.Signature.Algorithm != "ed25519" {
		return errors.New("terrain manifest totals or signature are invalid")
	}
	return nil
}

func verifyTerrainManifestSignature(manifest terrainManifest) error {
	encodedKey := terrainManifestPublicKeys[manifest.Signature.KeyID]
	publicKey, keyErr := base64.StdEncoding.DecodeString(encodedKey)
	signature, signatureErr := base64.StdEncoding.DecodeString(manifest.Signature.Signature)
	if encodedKey == "" || keyErr != nil || signatureErr != nil || len(publicKey) != ed25519.PublicKeySize || len(signature) != ed25519.SignatureSize {
		return errors.New("terrain manifest signing key is not trusted")
	}
	files := make([]any, 0, len(manifest.Files))
	for _, file := range manifest.Files {
		files = append(files, map[string]any{"path": file.Path, "asset": file.Asset, "sha256": file.SHA256, "size_bytes": file.SizeBytes})
	}
	unsigned := map[string]any{
		"schema_version": manifest.SchemaVersion, "terrain_pack_id": manifest.TerrainPackID,
		"terrain_revision": manifest.TerrainRevision, "map_count": manifest.MapCount,
		"total_size_bytes": manifest.TotalSizeBytes, "files": files,
	}
	payload, err := canonicalJSON(unsigned)
	if err != nil || !ed25519.Verify(ed25519.PublicKey(publicKey), payload, signature) {
		return errors.New("terrain manifest signature verification failed")
	}
	return nil
}

func canonicalJSON(value any) ([]byte, error) {
	var output bytes.Buffer
	var write func(any) error
	write = func(item any) error {
		switch typed := item.(type) {
		case nil:
			output.WriteString("null")
		case string:
			encoded, _ := json.Marshal(typed)
			output.Write(encoded)
		case bool:
			output.WriteString(strconv.FormatBool(typed))
		case int:
			output.WriteString(strconv.Itoa(typed))
		case int64:
			output.WriteString(strconv.FormatInt(typed, 10))
		case []any:
			output.WriteByte('[')
			for index, child := range typed {
				if index > 0 {
					output.WriteByte(',')
				}
				if err := write(child); err != nil {
					return err
				}
			}
			output.WriteByte(']')
		case map[string]any:
			keys := make([]string, 0, len(typed))
			for key := range typed {
				keys = append(keys, key)
			}
			sort.Strings(keys)
			output.WriteByte('{')
			for index, key := range keys {
				if index > 0 {
					output.WriteByte(',')
				}
				encoded, _ := json.Marshal(key)
				output.Write(encoded)
				output.WriteByte(':')
				if err := write(typed[key]); err != nil {
					return err
				}
			}
			output.WriteByte('}')
		default:
			return fmt.Errorf("unsupported canonical JSON type %T", item)
		}
		return nil
	}
	if err := write(value); err != nil {
		return nil, err
	}
	return output.Bytes(), nil
}

func verifyDiskObject(path string, size int64, digest string) (bool, error) {
	file, err := os.Open(path)
	if err != nil {
		return false, err
	}
	defer file.Close()
	info, err := file.Stat()
	if err != nil || info.Size() != size {
		return false, err
	}
	hash := sha256.New()
	if _, err := io.Copy(hash, file); err != nil {
		return false, err
	}
	return hex.EncodeToString(hash.Sum(nil)) == digest, nil
}

func validSHA256(value string) bool {
	if len(value) != 64 {
		return false
	}
	_, err := hex.DecodeString(value)
	return err == nil && strings.ToLower(value) == value
}
