package main

import (
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/tls"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/pem"
	"io"
	"math/big"
	"net"
	"net/http"
	"net/url"
	"path"
	"strconv"
	"strings"
	"time"
)

var mobileAppBase = "https://bomana.ruikang.wang/mobile/Enhanced/"

const (
	mobileAppHTMLLimit  = 512 << 10
	mobileAppAssetLimit = 8 << 20
	mobileAppFetchLimit = 15 * time.Second
)

const pairingPageCSP = "default-src 'none'; base-uri 'self'; script-src 'self' 'wasm-unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self' https://pay.ruikang.wang https://bomana.ruikang.wang https://bomanaupdate.ruikang.wang; worker-src 'self' blob:; frame-ancestors 'none'; form-action 'none'"

func listenerPort(listener net.Listener) (int, error) {
	_, rawPort, err := net.SplitHostPort(listener.Addr().String())
	if err != nil {
		return 0, err
	}
	return strconv.Atoi(rawPort)
}

func pairingCertificateIPs(networks []mobileNetworkCandidate) []net.IP {
	seen := map[string]struct{}{"127.0.0.1": {}}
	ips := []net.IP{net.ParseIP("127.0.0.1")}
	for _, network := range networks {
		ip := net.ParseIP(network.Address)
		if ip == nil || ip.To4() == nil {
			continue
		}
		value := ip.To4().String()
		if _, exists := seen[value]; exists {
			continue
		}
		seen[value] = struct{}{}
		ips = append(ips, ip.To4())
	}
	return ips
}

func generatePairingCertificate(ips []net.IP) (tls.Certificate, error) {
	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		return tls.Certificate{}, err
	}
	serial, err := rand.Int(rand.Reader, new(big.Int).Lsh(big.NewInt(1), 128))
	if err != nil {
		return tls.Certificate{}, err
	}
	template := x509.Certificate{
		SerialNumber:          serial,
		Subject:               pkix.Name{Organization: []string{"Bomana Bridge"}, CommonName: "Bomana Bridge"},
		NotBefore:             time.Now().Add(-time.Minute),
		NotAfter:              time.Now().Add(mobilePairingSessionDuration + time.Hour),
		KeyUsage:              x509.KeyUsageDigitalSignature,
		ExtKeyUsage:           []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth},
		BasicConstraintsValid: true,
		IPAddresses:           ips,
	}
	der, err := x509.CreateCertificate(rand.Reader, &template, &template, &key.PublicKey, key)
	if err != nil {
		return tls.Certificate{}, err
	}
	keyBytes, err := x509.MarshalPKCS8PrivateKey(key)
	if err != nil {
		return tls.Certificate{}, err
	}
	return tls.X509KeyPair(
		pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: der}),
		pem.EncodeToMemory(&pem.Block{Type: "PRIVATE KEY", Bytes: keyBytes}),
	)
}

func isPublicPairingAsset(request *http.Request) bool {
	if request.Method != http.MethodGet && request.Method != http.MethodHead {
		return false
	}
	if request.URL.RawQuery != "" {
		return false
	}
	_, ok := pairingAssetUpstream(request.URL.Path)
	return ok
}

func pairingAssetUpstream(requestPath string) (string, bool) {
	if requestPath == "" || strings.Contains(requestPath, "\\") || strings.Contains(requestPath, "\x00") {
		return "", false
	}
	cleaned := path.Clean(requestPath)
	if cleaned != "/mobile/Enhanced" && !strings.HasPrefix(cleaned, "/mobile/Enhanced/") {
		return "", false
	}
	base, err := url.Parse(mobileAppBase)
	if err != nil || (base.Scheme != "https" && base.Scheme != "http") || base.Host == "" || base.User != nil {
		return "", false
	}
	if !strings.HasPrefix(path.Clean(base.Path), "/mobile/Enhanced") {
		return "", false
	}
	resolved := &url.URL{Scheme: base.Scheme, Host: base.Host, Path: cleaned}
	if cleaned == "/mobile/Enhanced" {
		resolved.Path = "/mobile/Enhanced/"
	}
	if resolved.User != nil || resolved.RawQuery != "" || resolved.Fragment != "" {
		return "", false
	}
	if resolved.Host != base.Host || resolved.Scheme != base.Scheme {
		return "", false
	}
	return resolved.String(), true
}

func pairingAssetLimit(requestPath string) int64 {
	switch strings.ToLower(path.Ext(requestPath)) {
	case ".html", "":
		return mobileAppHTMLLimit
	default:
		return mobileAppAssetLimit
	}
}

func pairingAssetTypeAllowed(value string) bool {
	resolved := strings.ToLower(strings.TrimSpace(strings.SplitN(value, ";", 2)[0]))
	switch resolved {
	case "",
		"text/html",
		"text/css",
		"text/javascript",
		"application/javascript",
		"application/wasm",
		"application/json",
		"image/svg+xml",
		"image/png",
		"application/octet-stream",
		"text/plain":
		return true
	default:
		return false
	}
}

func (gateway *relay) serveMobileAppAsset(response http.ResponseWriter, request *http.Request) {
	setSecurityHeaders(response)
	if !gateway.mobile.Active(time.Now()) {
		http.Error(response, "mobile pairing unavailable", http.StatusUnauthorized)
		return
	}
	upstreamURL, ok := pairingAssetUpstream(request.URL.Path)
	if !ok {
		http.Error(response, "not found", http.StatusNotFound)
		return
	}
	client := gateway.mobilePageClient
	if client == nil {
		transport := http.DefaultTransport.(*http.Transport).Clone()
		transport.Proxy = nil
		client = &http.Client{
			Transport: transport,
			Timeout:   mobileAppFetchLimit,
			CheckRedirect: func(_ *http.Request, _ []*http.Request) error {
				return http.ErrUseLastResponse
			},
		}
	}
	upstream, err := http.NewRequestWithContext(request.Context(), http.MethodGet, upstreamURL, nil)
	if err != nil {
		http.Error(response, "mobile app unavailable", http.StatusBadGateway)
		return
	}
	if strings.HasSuffix(strings.TrimSuffix(request.URL.Path, "/"), "/mobile/Enhanced") {
		upstream.Header.Set("Accept", "text/html")
	}
	upstreamResponse, err := client.Do(upstream)
	if err != nil {
		http.Error(response, "mobile app unavailable", http.StatusBadGateway)
		return
	}
	defer upstreamResponse.Body.Close()
	if upstreamResponse.StatusCode != http.StatusOK {
		http.Error(response, "mobile app unavailable", http.StatusBadGateway)
		return
	}
	limit := pairingAssetLimit(request.URL.Path)
	body, err := io.ReadAll(io.LimitReader(upstreamResponse.Body, limit+1))
	if err != nil || int64(len(body)) > limit {
		http.Error(response, "mobile app rejected", http.StatusBadGateway)
		return
	}
	contentType := upstreamResponse.Header.Get("Content-Type")
	if !pairingAssetTypeAllowed(contentType) {
		http.Error(response, "mobile app rejected", http.StatusBadGateway)
		return
	}
	if strings.EqualFold(path.Ext(request.URL.Path), ".wasm") {
		response.Header().Set("Content-Type", "application/wasm")
	} else if contentType != "" {
		response.Header().Set("Content-Type", contentType)
	}
	response.Header().Set("Cache-Control", "no-store")
	if strings.Contains(strings.ToLower(contentType), "text/html") {
		response.Header().Set("Content-Security-Policy", pairingPageCSP)
	}
	response.WriteHeader(http.StatusOK)
	if request.Method != http.MethodHead {
		_, _ = response.Write(body)
	}
}
