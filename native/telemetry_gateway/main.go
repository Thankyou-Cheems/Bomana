// BomanaBridge exposes a fixed, read-only loopback relay for the
// official War Thunder 8111 HTTP interface. It performs no game-state
// derivation and has no process or memory access capability.
package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"log/slog"
	"net"
	"net/http"
	"net/url"
	"os"
	"os/signal"
	"strconv"
	"strings"
	"syscall"
	"time"
)

const (
	defaultListenAddress = "auto"
	defaultUpstream      = "http://127.0.0.1:8111"
	maxResponseBytes     = 2 * 1024 * 1024
	bridgePortStart      = 8878
	bridgePortEnd        = 8897
)

const (
	cacheProtocol         = 4
	mobilePairingProtocol = 6
)

var (
	bridgeVersion    = "development"
	appWebVersion    = "development"
	bridgeProvenance = "local-unattested"
)

const bridgeStatusHTML = `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Bomana Bridge</title><style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:#07151c;color:#dcecf8;font:600 16px/1.6 "Microsoft YaHei",sans-serif}.card{width:min(520px,calc(100% - 48px));padding:32px;border:1px solid #45677a;background:#0c202b}.brand{display:flex;align-items:center;gap:14px}.mark{display:grid;place-items:center;width:48px;height:48px;background:#ffd65a;color:#10202a;font-size:24px}h1{margin:0;font-size:24px}.ok{color:#62dda5}p{color:#9eb8c7}nav{display:flex;gap:12px;flex-wrap:wrap;margin-top:24px}a{padding:10px 16px;border:1px solid #6c8fa3;color:#dcecf8;text-decoration:none}a.primary{background:#ffd65a;border-color:#ffd65a;color:#10202a}</style></head><body><main class="card"><div class="brand"><div class="mark" aria-hidden="true">B</div><div><h1>Bomana Bridge</h1><span class="ok">● 正在运行</span></div></div><p>只读转发官方 localhost:8111，并管理签名地形缓存。计算与 Enhanced 权益不保存在 Bridge 中。</p><nav><a class="primary" href="https://bomana.ruikang.wang/launcher/">返回 Launcher</a><a href="https://bomana.ruikang.wang/app/Enhanced/">打开 Bomana</a></nav></main></body></html>`

type routeDefinition struct {
	upstreamPath       string
	allowedContentType []string
	maxBytes           int64
	accept             string
	upstreamQuery      string
}

var fixedRoutes = map[string]routeDefinition{
	"/api/v1/8111/state":       {"/state", []string{"application/json"}, maxResponseBytes, "application/json", ""},
	"/api/v1/8111/indicators":  {"/indicators", []string{"application/json"}, maxResponseBytes, "application/json", ""},
	"/api/v1/8111/map-objects": {"/map_obj.json", []string{"application/json"}, maxResponseBytes, "application/json", ""},
	"/api/v1/8111/map-info":    {"/map_info.json", []string{"application/json"}, maxResponseBytes, "application/json", ""},
	"/api/v1/8111/map-image":   {"/map.img", []string{"image/png", "image/jpeg"}, 8 * 1024 * 1024, "image/png, image/jpeg", ""},
	"/api/v1/8111/icons-font":  {"/icons.ttf", []string{"font/ttf", "application/x-font-ttf", "application/octet-stream"}, 2 * 1024 * 1024, "font/ttf, application/octet-stream", ""},
	"/api/v1/8111/gamechat":    {"/gamechat", []string{"application/json"}, maxResponseBytes, "application/json", "lastId=0"},
}

type relay struct {
	upstream         *url.URL
	allowedOrigin    string
	client           *http.Client
	mobilePageClient *http.Client
	cache            *localDataStore
	mobile           *mobilePairingManager
	presentation     *presentationState
}

func main() {
	listenAddress := flag.String("listen", defaultListenAddress, "loopback listener address")
	allowedOrigin := flag.String("allowed-origin", "https://bomana.ruikang.wang", "exact browser Origin")
	flag.Parse()

	if *listenAddress != "auto" {
		if err := validateLoopbackListener(*listenAddress); err != nil {
			slog.Error("invalid listener configuration", "error", err)
			os.Exit(2)
		}
	}
	origin, err := validateOrigin(*allowedOrigin)
	if err != nil {
		slog.Error("invalid browser origin", "error", err)
		os.Exit(2)
	}
	upstream, _ := url.Parse(defaultUpstream)
	cacheStore, cacheErr := openDefaultLocalDataStore()
	if cacheErr != nil {
		slog.Warn("local data store unavailable", "error", cacheErr)
	}
	handler := newRelayWithCache(upstream, origin, cacheStore)
	defer handler.mobile.Close()
	server := &http.Server{
		Addr:              *listenAddress,
		Handler:           handler,
		ReadHeaderTimeout: 2 * time.Second,
		ReadTimeout:       10 * time.Minute,
		WriteTimeout:      10 * time.Minute,
		IdleTimeout:       15 * time.Second,
		MaxHeaderBytes:    16 * 1024,
	}

	listener, err := listenBridge(server.Addr)
	if err != nil {
		slog.Error("gateway listener failed", "error", err)
		os.Exit(1)
	}
	slog.Info("Bomana Bridge ready", "address", listener.Addr().String())
	cacheContext, stopCache := context.WithCancel(context.Background())
	defer stopCache()
	if cacheStore != nil {
		cacheStore.Start(cacheContext)
	}

	shutdownSignals := make(chan os.Signal, 1)
	trayExit := make(chan struct{}, 1)
	signal.Notify(shutdownSignals, os.Interrupt, syscall.SIGTERM)
	mobilePairingURL := "http://" + listener.Addr().String() + "/mobile-pairing"
	tray, trayErr := startTray(defaultTrayConfig(mobilePairingURL, func() {
		select {
		case trayExit <- struct{}{}:
		default:
		}
	}))
	if trayErr != nil {
		slog.Warn("notification area icon unavailable", "error", trayErr)
	}
	if tray != nil {
		defer tray.Close()
	}
	go func() {
		select {
		case <-shutdownSignals:
		case <-trayExit:
		}
		ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
		defer cancel()
		_ = server.Shutdown(ctx)
	}()
	if err := server.Serve(listener); err != nil && !errors.Is(err, http.ErrServerClosed) {
		slog.Error("gateway stopped unexpectedly", "error", err)
		os.Exit(1)
	}
}

func listenBridge(address string) (net.Listener, error) {
	if address != "auto" {
		if err := validateLoopbackListener(address); err != nil {
			return nil, err
		}
		return net.Listen("tcp", address)
	}
	var lastErr error
	for port := bridgePortStart; port <= bridgePortEnd; port++ {
		listener, err := net.Listen("tcp", net.JoinHostPort("127.0.0.1", strconv.Itoa(port)))
		if err == nil {
			return listener, nil
		}
		lastErr = err
	}
	return nil, fmt.Errorf("no Bridge port available in %d-%d: %w", bridgePortStart, bridgePortEnd, lastErr)
}

func newRelay(upstream *url.URL, allowedOrigin string) *relay {
	return newRelayWithCache(upstream, allowedOrigin, nil)
}

func newRelayWithCache(upstream *url.URL, allowedOrigin string, cache *localDataStore) *relay {
	transport := http.DefaultTransport.(*http.Transport).Clone()
	transport.Proxy = nil
	return &relay{
		upstream:      upstream,
		allowedOrigin: allowedOrigin,
		cache:         cache,
		mobile:        newMobilePairingManager(),
		presentation:  newPresentationState(),
		client: &http.Client{
			Transport: transport,
			Timeout:   1250 * time.Millisecond,
			CheckRedirect: func(_ *http.Request, _ []*http.Request) error {
				return http.ErrUseLastResponse
			},
		},
	}
}

func (gateway *relay) ServeHTTP(response http.ResponseWriter, request *http.Request) {
	if request.URL.RawQuery == "" && (request.URL.Path == "/api/v1/mobile/pairing/start" || request.URL.Path == "/api/v1/mobile/pairing/rotate") {
		gateway.serveMobilePairingStart(response, request, request.URL.Path == "/api/v1/mobile/pairing/rotate")
		return
	}
	if request.URL.Path == "/mobile-pairing" {
		gateway.serveTrayMobilePairing(response, request)
		return
	}
	if request.URL.RawQuery == "" && request.URL.Path == "/api/v1/mobile/pairing/prepare" {
		gateway.serveMobilePairingPrepare(response, request)
		return
	}
	if request.URL.RawQuery == "" && request.URL.Path == "/api/v1/mobile/pairing/complete" && gateway.usesPairingListener(request) {
		gateway.serveMobilePairingComplete(response, request)
		return
	}
	if gateway.usesPairingListener(request) && isPublicPairingAsset(request) {
		gateway.serveMobileAppAsset(response, request)
		return
	}
	if gateway.usesPairingListener(request) {
		if request.Method == http.MethodOptions {
			if !gateway.mobile.Active(time.Now()) {
				http.Error(response, "mobile pairing unavailable", http.StatusUnauthorized)
				return
			}
		} else if !gateway.mobile.Authorize(request.Header.Get("X-Bomana-Mobile-Pairing"), time.Now()) {
			http.Error(response, "mobile pairing unavailable", http.StatusUnauthorized)
			return
		}
	}
	if request.URL.RawQuery == "" && request.URL.Path == "/" {
		gateway.serveBridgeStatus(response, request)
		return
	}
	setSecurityHeaders(response)
	if request.URL.RawQuery == "" && request.URL.Path == "/api/v1/presentation/weapon-selection" {
		gateway.serveWeaponSelection(response, request)
		return
	}
	if strings.HasPrefix(request.URL.Path, "/api/v1/cache/") {
		gateway.serveCache(response, request)
		return
	}
	if request.URL.RawQuery == "" && (request.URL.Path == "/healthz" || request.URL.Path == "/api/v1/capabilities") {
		gateway.serveLocalState(response, request)
		return
	}
	definition, exists := fixedRoutes[request.URL.Path]
	if !exists || request.URL.RawQuery != "" {
		http.Error(response, "not found", http.StatusNotFound)
		return
	}
	if request.Method == http.MethodOptions {
		if !gateway.allowOrigin(response, request) {
			http.Error(response, "origin forbidden", http.StatusForbidden)
			return
		}
		response.Header().Set("Access-Control-Allow-Methods", "GET, OPTIONS")
		response.Header().Set("Access-Control-Allow-Headers", "Accept, X-Bomana-Mobile-Pairing")
		gateway.allowPrivateNetwork(response, request)
		response.WriteHeader(http.StatusNoContent)
		return
	}
	if request.Method != http.MethodGet {
		response.Header().Set("Allow", "GET, OPTIONS")
		http.Error(response, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	if !gateway.allowOrigin(response, request) {
		http.Error(response, "origin forbidden", http.StatusForbidden)
		return
	}

	upstreamURL := *gateway.upstream
	upstreamURL.Path = definition.upstreamPath
	upstreamURL.RawQuery = definition.upstreamQuery
	upstreamRequest, err := http.NewRequestWithContext(request.Context(), http.MethodGet, upstreamURL.String(), nil)
	if err != nil {
		http.Error(response, "relay unavailable", http.StatusBadGateway)
		return
	}
	upstreamRequest.Header.Set("Accept", definition.accept)
	upstreamResponse, err := gateway.client.Do(upstreamRequest)
	if err != nil {
		http.Error(response, "8111 unavailable", http.StatusBadGateway)
		return
	}
	defer upstreamResponse.Body.Close()
	if upstreamResponse.StatusCode != http.StatusOK {
		http.Error(response, "8111 unavailable", http.StatusBadGateway)
		return
	}
	contentType := upstreamResponse.Header.Get("Content-Type")
	if !contentTypeAllowed(contentType, definition.allowedContentType) {
		http.Error(response, "8111 response type rejected", http.StatusBadGateway)
		return
	}
	body, err := io.ReadAll(io.LimitReader(upstreamResponse.Body, definition.maxBytes+1))
	if err != nil || int64(len(body)) > definition.maxBytes {
		http.Error(response, "8111 response rejected", http.StatusBadGateway)
		return
	}
	response.Header().Set("Content-Type", contentType)
	response.WriteHeader(http.StatusOK)
	_, _ = response.Write(body)
}

type mobilePairingPrepareRequest struct {
	SchemaVersion        int    `json:"schema_version"`
	BridgePairingID      string `json:"bridge_pairing_id"`
	PairingToken         string `json:"pairing_token"`
	MobileLease          string `json:"mobile_lease"`
	MobileLeaseExpiresAt string `json:"mobile_lease_expires_at"`
	PairingExpiresAt     string `json:"pairing_expires_at"`
}

type mobilePairingCompleteRequest struct {
	SchemaVersion int    `json:"schema_version"`
	PairingCode   string `json:"pairing_code"`
	PairingToken  string `json:"pairing_token"`
}

func requestUsesLANListener(request *http.Request) bool {
	localAddress, ok := request.Context().Value(http.LocalAddrContextKey).(net.Addr)
	if !ok || localAddress == nil {
		return false
	}
	host, _, err := net.SplitHostPort(localAddress.String())
	return err == nil && !isLoopbackHost(host)
}

func (gateway *relay) usesPairingListener(request *http.Request) bool {
	if requestUsesLANListener(request) {
		return true
	}
	localAddress, ok := request.Context().Value(http.LocalAddrContextKey).(net.Addr)
	if !ok || localAddress == nil {
		return false
	}
	_, port, err := net.SplitHostPort(localAddress.String())
	if err != nil {
		return false
	}
	return gateway.mobile.isPairingPort(port)
}

func (gateway *relay) serveMobilePairingStart(response http.ResponseWriter, request *http.Request, forceNew bool) {
	setSecurityHeaders(response)
	if request.RemoteAddr != "" && !isLoopbackRemote(request.RemoteAddr) {
		http.Error(response, "loopback required", http.StatusForbidden)
		return
	}
	if request.Method == http.MethodOptions {
		if !gateway.allowOrigin(response, request) {
			http.Error(response, "origin forbidden", http.StatusForbidden)
			return
		}
		response.Header().Set("Access-Control-Allow-Methods", "POST, OPTIONS")
		response.Header().Set("Access-Control-Allow-Headers", "Content-Type")
		gateway.allowPrivateNetwork(response, request)
		response.WriteHeader(http.StatusNoContent)
		return
	}
	if request.Method != http.MethodPost {
		response.Header().Set("Allow", "POST, OPTIONS")
		http.Error(response, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	if !gateway.allowOrigin(response, request) {
		http.Error(response, "origin forbidden", http.StatusForbidden)
		return
	}
	descriptor, err := gateway.mobile.Start(gateway, time.Now(), forceNew)
	if err != nil {
		http.Error(response, "mobile pairing unavailable", http.StatusServiceUnavailable)
		return
	}
	response.Header().Set("Content-Type", "application/json")
	response.WriteHeader(http.StatusCreated)
	_ = json.NewEncoder(response).Encode(descriptor)
}

func (gateway *relay) serveMobilePairingPrepare(response http.ResponseWriter, request *http.Request) {
	setSecurityHeaders(response)
	if request.Method == http.MethodOptions {
		if !gateway.authorizeMobilePairingPrepareOrigin(response, request) {
			http.Error(response, "origin forbidden", http.StatusForbidden)
			return
		}
		response.Header().Set("Access-Control-Allow-Methods", "POST, OPTIONS")
		response.Header().Set("Access-Control-Allow-Headers", "Content-Type")
		gateway.allowPrivateNetwork(response, request)
		response.WriteHeader(http.StatusNoContent)
		return
	}
	if request.Method != http.MethodPost {
		response.Header().Set("Allow", "POST, OPTIONS")
		http.Error(response, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	if !gateway.authorizeMobilePairingPrepareOrigin(response, request) {
		http.Error(response, "origin forbidden", http.StatusForbidden)
		return
	}
	var payload mobilePairingPrepareRequest
	decoder := json.NewDecoder(http.MaxBytesReader(response, request.Body, 12<<10))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&payload); err != nil || payload.SchemaVersion != 1 {
		http.Error(response, "invalid pairing preparation", http.StatusBadRequest)
		return
	}
	leaseExpiresAt, leaseErr := time.Parse(time.RFC3339, payload.MobileLeaseExpiresAt)
	pairingExpiresAt, pairingErr := time.Parse(time.RFC3339, payload.PairingExpiresAt)
	if leaseErr != nil || pairingErr != nil || gateway.mobile.Prepare(
		payload.BridgePairingID,
		payload.PairingToken,
		payload.MobileLease,
		leaseExpiresAt,
		pairingExpiresAt,
		time.Now(),
	) != nil {
		http.Error(response, "mobile pairing unavailable", http.StatusConflict)
		return
	}
	response.WriteHeader(http.StatusNoContent)
}

func (gateway *relay) authorizeMobilePairingPrepareOrigin(response http.ResponseWriter, request *http.Request) bool {
	if gateway.usesPairingListener(request) {
		return gateway.requirePairingListenerOrigin(response, request)
	}
	if request.RemoteAddr == "" || isLoopbackRemote(request.RemoteAddr) {
		return gateway.allowOrigin(response, request)
	}
	return false
}

func (gateway *relay) serveMobilePairingComplete(response http.ResponseWriter, request *http.Request) {
	setSecurityHeaders(response)
	if request.Method == http.MethodOptions {
		if !gateway.requirePairingListenerOrigin(response, request) {
			http.Error(response, "origin forbidden", http.StatusForbidden)
			return
		}
		response.Header().Set("Access-Control-Allow-Methods", "POST, OPTIONS")
		response.Header().Set("Access-Control-Allow-Headers", "Content-Type")
		response.WriteHeader(http.StatusNoContent)
		return
	}
	if request.Method != http.MethodPost {
		response.Header().Set("Allow", "POST, OPTIONS")
		http.Error(response, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	var payload mobilePairingCompleteRequest
	decoder := json.NewDecoder(http.MaxBytesReader(response, request.Body, 2<<10))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&payload); err != nil || payload.SchemaVersion != 1 {
		http.Error(response, "invalid pairing request", http.StatusBadRequest)
		return
	}
	hasCode := payload.PairingCode != ""
	hasToken := payload.PairingToken != ""
	if hasCode == hasToken {
		http.Error(response, "invalid pairing request", http.StatusBadRequest)
		return
	}
	if hasCode && !gateway.requirePairingListenerOrigin(response, request) {
		http.Error(response, "origin forbidden", http.StatusForbidden)
		return
	}
	client, _, err := net.SplitHostPort(request.RemoteAddr)
	if err != nil || client == "" {
		client = request.RemoteAddr
	}
	var completed mobilePairingCompletion
	var result mobilePairingCompleteResult
	if hasToken {
		completed, result = gateway.mobile.Claim(payload.PairingToken, time.Now())
	} else {
		completed, result = gateway.mobile.Complete(client, payload.PairingCode, time.Now())
	}
	switch result {
	case mobilePairingCompleteOK:
		response.Header().Set("Content-Type", "application/json")
		response.WriteHeader(http.StatusOK)
		_ = json.NewEncoder(response).Encode(completed)
	case mobilePairingCompleteInvalid:
		if hasToken {
			http.Error(response, "invalid pairing claim", http.StatusForbidden)
		} else {
			http.Error(response, "invalid pairing code", http.StatusForbidden)
		}
	case mobilePairingCompleteRateLimited:
		response.Header().Set("Retry-After", strconv.Itoa(int(mobilePairingAttemptWindow/time.Second)))
		http.Error(response, "too many pairing attempts", http.StatusTooManyRequests)
	case mobilePairingCompleteGone:
		http.Error(response, "pairing code already used", http.StatusGone)
	default:
		http.Error(response, "mobile pairing unavailable", http.StatusUnauthorized)
	}
}

func (gateway *relay) requirePairingListenerOrigin(response http.ResponseWriter, request *http.Request) bool {
	origin := request.Header.Get("Origin")
	parsed, err := url.Parse(origin)
	if err != nil || parsed.User != nil || parsed.Path != "" || parsed.RawQuery != "" || parsed.Fragment != "" {
		return false
	}
	expectedScheme := "http"
	if request.TLS != nil {
		expectedScheme = "https"
	}
	if parsed.Scheme != expectedScheme || !strings.EqualFold(parsed.Host, request.Host) || !gateway.mobile.AllowPairingOrigin(origin) {
		return false
	}
	response.Header().Set("Access-Control-Allow-Origin", origin)
	response.Header().Set("Vary", "Origin")
	return true
}

func (gateway *relay) serveBridgeStatus(response http.ResponseWriter, request *http.Request) {
	if request.Method != http.MethodGet && request.Method != http.MethodHead {
		response.Header().Set("Allow", "GET, HEAD")
		http.Error(response, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	response.Header().Set("Cache-Control", "no-store")
	response.Header().Set("Content-Security-Policy", "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'")
	response.Header().Set("Referrer-Policy", "no-referrer")
	response.Header().Set("X-Content-Type-Options", "nosniff")
	response.Header().Set("Content-Type", "text/html; charset=utf-8")
	response.WriteHeader(http.StatusOK)
	if request.Method == http.MethodGet {
		_, _ = io.WriteString(response, bridgeStatusHTML)
	}
}

func (gateway *relay) serveLocalState(response http.ResponseWriter, request *http.Request) {
	if request.Method == http.MethodOptions {
		if !gateway.allowOrigin(response, request) {
			http.Error(response, "origin forbidden", http.StatusForbidden)
			return
		}
		response.Header().Set("Access-Control-Allow-Methods", "GET, OPTIONS")
		response.Header().Set("Access-Control-Allow-Headers", "Accept, X-Bomana-Mobile-Pairing")
		gateway.allowPrivateNetwork(response, request)
		response.WriteHeader(http.StatusNoContent)
		return
	}
	if request.Method != http.MethodGet {
		response.Header().Set("Allow", "GET, OPTIONS")
		http.Error(response, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	if !gateway.allowOrigin(response, request) {
		http.Error(response, "origin forbidden", http.StatusForbidden)
		return
	}
	response.Header().Set("Content-Type", "application/json")
	response.WriteHeader(http.StatusOK)
	if request.URL.Path == "/healthz" {
		_, _ = io.WriteString(response, `{"status":"ok","input":"official-8111-only"}`)
		return
	}
	_, _ = fmt.Fprintf(response, `{"schema_version":1,"bridge_protocol":1,"cache_protocol":%d,"mobile_pairing_protocol":%d,"bridge_version":%q,"app_web_version":%q,"build_provenance":%q,"authenticode":false,"input":"official-8111-only","write_commands":false,"routes":["state","indicators","map-objects","map-info","map-image","icons-font","gamechat","cache-catalog","cache-status","cache-selection","cache-objects","mobile-pairing","presentation-weapon-selection"]}`, cacheProtocol, mobilePairingProtocol, bridgeVersion, appWebVersion, bridgeProvenance)
}

func (gateway *relay) serveWeaponSelection(response http.ResponseWriter, request *http.Request) {
	response.Header().Set("Cache-Control", "no-store")
	if request.Method == http.MethodOptions {
		if !gateway.allowOrigin(response, request) {
			http.Error(response, "origin forbidden", http.StatusForbidden)
			return
		}
		response.Header().Set("Access-Control-Allow-Methods", "GET, PUT, OPTIONS")
		response.Header().Set("Access-Control-Allow-Headers", "Accept, Content-Type, X-Bomana-Mobile-Pairing")
		gateway.allowPrivateNetwork(response, request)
		response.WriteHeader(http.StatusNoContent)
		return
	}
	if request.Method == http.MethodGet {
		if !gateway.allowOrigin(response, request) {
			http.Error(response, "origin forbidden", http.StatusForbidden)
			return
		}
		response.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(response).Encode(gateway.presentation.WeaponSelection())
		return
	}
	if request.Method != http.MethodPut {
		response.Header().Set("Allow", "GET, PUT, OPTIONS")
		http.Error(response, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	if !gateway.requireBrowserOrigin(response, request) {
		http.Error(response, "origin forbidden", http.StatusForbidden)
		return
	}
	var payload struct {
		SchemaVersion    int    `json:"schema_version"`
		SelectedWeaponID string `json:"selected_weapon_id"`
	}
	decoder := json.NewDecoder(http.MaxBytesReader(response, request.Body, 1024))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&payload); err != nil || payload.SchemaVersion != 1 {
		http.Error(response, "weapon selection rejected", http.StatusBadRequest)
		return
	}
	state, err := gateway.presentation.SelectWeapon(payload.SelectedWeaponID)
	if err != nil {
		http.Error(response, "weapon selection rejected", http.StatusBadRequest)
		return
	}
	response.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(response).Encode(state)
}

func (gateway *relay) serveCache(response http.ResponseWriter, request *http.Request) {
	if request.Method == http.MethodOptions {
		if !gateway.allowOrigin(response, request) {
			http.Error(response, "origin forbidden", http.StatusForbidden)
			return
		}
		response.Header().Set("Access-Control-Allow-Methods", "GET, PUT, DELETE, OPTIONS")
		response.Header().Set("Access-Control-Allow-Headers", "Content-Type, X-Bomana-Mobile-Pairing")
		gateway.allowPrivateNetwork(response, request)
		response.WriteHeader(http.StatusNoContent)
		return
	}
	mutating := request.Method == http.MethodPut || request.Method == http.MethodDelete
	if mutating {
		if !gateway.requireBrowserOrigin(response, request) {
			http.Error(response, "origin forbidden", http.StatusForbidden)
			return
		}
	} else if !gateway.allowOrigin(response, request) {
		http.Error(response, "origin forbidden", http.StatusForbidden)
		return
	}
	if gateway.cache == nil {
		http.Error(response, "local data store unavailable", http.StatusServiceUnavailable)
		return
	}
	if request.URL.Path == "/api/v1/cache/selection" && request.URL.RawQuery == "" {
		if request.Method != http.MethodPut {
			response.Header().Set("Allow", "PUT, OPTIONS")
			http.Error(response, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		var selection struct {
			MapIDs []string `json:"map_ids"`
		}
		decoder := json.NewDecoder(io.LimitReader(request.Body, 64*1024))
		decoder.DisallowUnknownFields()
		if err := decoder.Decode(&selection); err != nil || len(selection.MapIDs) > 512 {
			http.Error(response, "terrain selection rejected", http.StatusBadRequest)
			return
		}
		if err := gateway.cache.SetSelectedMaps(selection.MapIDs); err != nil {
			http.Error(response, "terrain selection rejected", http.StatusUnprocessableEntity)
			return
		}
		response.Header().Set("Content-Type", "application/json")
		response.WriteHeader(http.StatusAccepted)
		_ = json.NewEncoder(response).Encode(gateway.cache.Status())
		return
	}
	if request.URL.Path == "/api/v1/cache/status" && request.URL.RawQuery == "" {
		if request.Method != http.MethodGet {
			response.Header().Set("Allow", "GET, OPTIONS")
			http.Error(response, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		response.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(response).Encode(gateway.cache.Status())
		return
	}
	if request.URL.Path == "/api/v1/cache/catalog" && request.URL.RawQuery == "" {
		if request.Method != http.MethodGet {
			response.Header().Set("Allow", "GET, OPTIONS")
			http.Error(response, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		catalog, err := gateway.cache.ReadCatalog()
		if errors.Is(err, os.ErrNotExist) {
			http.Error(response, "terrain catalog not ready", http.StatusServiceUnavailable)
			return
		}
		if err != nil {
			http.Error(response, "terrain catalog unavailable", http.StatusServiceUnavailable)
			return
		}
		response.Header().Set("Content-Type", "application/json")
		response.Header().Set("Cache-Control", "no-store")
		response.WriteHeader(http.StatusOK)
		_, _ = response.Write(catalog)
		return
	}
	const objectPrefix = "/api/v1/cache/objects/"
	if !strings.HasPrefix(request.URL.Path, objectPrefix) || request.URL.RawQuery != "" {
		http.Error(response, "not found", http.StatusNotFound)
		return
	}
	digest := strings.TrimPrefix(request.URL.Path, objectPrefix)
	if !validSHA256(digest) {
		http.Error(response, "not found", http.StatusNotFound)
		return
	}
	switch request.Method {
	case http.MethodGet:
		file, info, err := gateway.cache.ReadObject(digest)
		if errors.Is(err, os.ErrNotExist) {
			http.Error(response, "not found", http.StatusNotFound)
			return
		}
		if err != nil {
			http.Error(response, "cache read failed", http.StatusInternalServerError)
			return
		}
		defer file.Close()
		response.Header().Set("Content-Type", "application/octet-stream")
		response.Header().Set("Content-Length", strconv.FormatInt(info.Size(), 10))
		_, _ = io.Copy(response, file)
	case http.MethodPut:
		if request.ContentLength > maxCacheObjectBytes {
			http.Error(response, "cache object too large", http.StatusRequestEntityTooLarge)
			return
		}
		if err := gateway.cache.PutObject(request.Context(), digest, request.Body); err != nil {
			http.Error(response, "cache object rejected", http.StatusUnprocessableEntity)
			return
		}
		response.WriteHeader(http.StatusNoContent)
	case http.MethodDelete:
		if err := gateway.cache.RemoveObject(digest); err != nil {
			if errors.Is(err, os.ErrNotExist) {
				http.Error(response, "not found", http.StatusNotFound)
				return
			}
			http.Error(response, "cache remove failed", http.StatusInternalServerError)
			return
		}
		response.WriteHeader(http.StatusNoContent)
	default:
		response.Header().Set("Allow", "GET, PUT, DELETE, OPTIONS")
		http.Error(response, "method not allowed", http.StatusMethodNotAllowed)
	}
}

func (gateway *relay) allowPrivateNetwork(response http.ResponseWriter, request *http.Request) {
	if strings.EqualFold(request.Header.Get("Access-Control-Request-Private-Network"), "true") {
		response.Header().Set("Access-Control-Allow-Private-Network", "true")
	}
}

func contentTypeAllowed(value string, allowed []string) bool {
	resolved := strings.ToLower(strings.TrimSpace(strings.SplitN(value, ";", 2)[0]))
	for _, expected := range allowed {
		if resolved == expected {
			return true
		}
	}
	return false
}

func (gateway *relay) allowOrigin(response http.ResponseWriter, request *http.Request) bool {
	return gateway.authorizeOrigin(response, request, true)
}

func (gateway *relay) requireBrowserOrigin(response http.ResponseWriter, request *http.Request) bool {
	return gateway.authorizeOrigin(response, request, false)
}

func (gateway *relay) authorizeOrigin(response http.ResponseWriter, request *http.Request, allowLoopbackWithoutOrigin bool) bool {
	origin := request.Header.Get("Origin")
	if origin == "" {
		if allowLoopbackWithoutOrigin && (request.RemoteAddr == "" || isLoopbackRemote(request.RemoteAddr)) {
			return true
		}
		return gateway.usesPairingListener(request)
	}
	if origin != gateway.allowedOrigin && !gateway.mobile.AllowPairingOrigin(origin) {
		return false
	}
	response.Header().Set("Access-Control-Allow-Origin", origin)
	response.Header().Set("Vary", "Origin")
	return true
}

func validateLoopbackListener(address string) error {
	host, _, err := net.SplitHostPort(address)
	if err != nil {
		return err
	}
	ip := net.ParseIP(host)
	if ip == nil || !ip.IsLoopback() {
		return fmt.Errorf("listener must use an explicit loopback IP")
	}
	return nil
}

func validateOrigin(raw string) (string, error) {
	parsed, err := url.Parse(raw)
	if err != nil || parsed.Scheme == "" || parsed.Host == "" || parsed.User != nil || parsed.RawQuery != "" || parsed.Fragment != "" || parsed.Path != "" {
		return "", fmt.Errorf("origin must be an exact HTTP(S) origin")
	}
	if parsed.Scheme != "https" && !(parsed.Scheme == "http" && isLoopbackHost(parsed.Hostname())) {
		return "", fmt.Errorf("origin must use HTTPS except for loopback development")
	}
	return parsed.String(), nil
}

func isLoopbackRemote(address string) bool {
	host, _, err := net.SplitHostPort(address)
	return err == nil && isLoopbackHost(host)
}

func isLoopbackHost(host string) bool {
	ip := net.ParseIP(host)
	return strings.EqualFold(host, "localhost") || (ip != nil && ip.IsLoopback())
}

func setSecurityHeaders(response http.ResponseWriter) {
	response.Header().Set("Cache-Control", "no-store")
	response.Header().Set("Content-Security-Policy", "default-src 'none'")
	response.Header().Set("Referrer-Policy", "no-referrer")
	response.Header().Set("X-Content-Type-Options", "nosniff")
}
