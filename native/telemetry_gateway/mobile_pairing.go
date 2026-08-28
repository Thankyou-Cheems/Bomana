package main

import (
	"crypto/rand"
	"crypto/subtle"
	"crypto/tls"
	"encoding/base64"
	"errors"
	"fmt"
	"net"
	"net/http"
	"net/url"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"
)

const (
	mobilePairingSessionDuration = 8 * time.Hour
	mobilePairingCodeDuration    = 5 * time.Minute
	mobilePairingAttemptLimit    = 8
	mobilePairingAttemptWindow   = time.Minute
	mobilePairingCodeAlphabet    = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
)

type mobileNetworkCandidate struct {
	Interface   string `json:"interface"`
	Address     string `json:"address"`
	Endpoint    string `json:"endpoint"`
	TLSEndpoint string `json:"tls_endpoint"`
}

type mobilePairingDescriptor struct {
	SchemaVersion    int                      `json:"schema_version"`
	BridgePairingID  string                   `json:"bridge_pairing_id"`
	PairingToken     string                   `json:"pairing_token"`
	PairingCode      string                   `json:"pairing_code"`
	PairingExpiresAt string                   `json:"pairing_expires_at"`
	ExpiresAt        string                   `json:"expires_at"`
	Networks         []mobileNetworkCandidate `json:"networks"`
}

type mobilePairingSession struct {
	id                string
	token             string
	code              string
	codeExpiresAt     time.Time
	expiresAt         time.Time
	mobileLease       string
	mobileLeaseExpiry time.Time
	prepared          bool
	claimed           bool
	failures          map[string][]time.Time
}

type mobilePairingCompletion struct {
	SchemaVersion        int    `json:"schema_version"`
	BridgePairingID      string `json:"bridge_pairing_id"`
	PairingToken         string `json:"pairing_token"`
	MobileLease          string `json:"mobile_lease"`
	MobileLeaseExpiresAt string `json:"mobile_lease_expires_at"`
	ExpiresAt            string `json:"expires_at"`
}

type mobilePairingCompleteResult uint8

const (
	mobilePairingCompleteOK mobilePairingCompleteResult = iota
	mobilePairingCompleteInvalid
	mobilePairingCompleteRateLimited
	mobilePairingCompleteGone
	mobilePairingCompleteUnavailable
)

type mobilePairingManager struct {
	mu          sync.RWMutex
	listener    net.Listener
	tlsListener net.Listener
	server      *http.Server
	port        int
	tlsPort     int
	session     *mobilePairingSession
	listen      func(network, address string) (net.Listener, error)
	networks    func(httpPort, tlsPort int) ([]mobileNetworkCandidate, error)
}

func newMobilePairingManager() *mobilePairingManager {
	return &mobilePairingManager{
		listen:   net.Listen,
		networks: privateIPv4Candidates,
	}
}

func (manager *mobilePairingManager) Start(handler http.Handler, now time.Time) (mobilePairingDescriptor, error) {
	manager.mu.Lock()
	defer manager.mu.Unlock()
	if manager.listener == nil {
		listener, err := manager.listen("tcp", "0.0.0.0:0")
		if err != nil {
			return mobilePairingDescriptor{}, fmt.Errorf("mobile listener failed: %w", err)
		}
		httpPort, err := listenerPort(listener)
		if err != nil {
			_ = listener.Close()
			return mobilePairingDescriptor{}, err
		}
		tlsTCP, err := manager.listen("tcp", "0.0.0.0:0")
		if err != nil {
			_ = listener.Close()
			return mobilePairingDescriptor{}, fmt.Errorf("mobile TLS listener failed: %w", err)
		}
		tlsPort, err := listenerPort(tlsTCP)
		if err != nil {
			_ = listener.Close()
			_ = tlsTCP.Close()
			return mobilePairingDescriptor{}, err
		}
		networks, err := manager.networks(httpPort, tlsPort)
		if err != nil || len(networks) == 0 {
			_ = listener.Close()
			_ = tlsTCP.Close()
			if err != nil {
				return mobilePairingDescriptor{}, err
			}
			return mobilePairingDescriptor{}, errors.New("no private IPv4 network is available")
		}
		ips := pairingCertificateIPs(networks)
		certificate, err := generatePairingCertificate(ips)
		if err != nil {
			_ = listener.Close()
			_ = tlsTCP.Close()
			return mobilePairingDescriptor{}, fmt.Errorf("mobile TLS certificate failed: %w", err)
		}
		tlsListener := tls.NewListener(tlsTCP, &tls.Config{
			MinVersion:   tls.VersionTLS12,
			Certificates: []tls.Certificate{certificate},
		})
		manager.listener = listener
		manager.tlsListener = tlsListener
		manager.port = httpPort
		manager.tlsPort = tlsPort
		manager.server = &http.Server{
			Handler:           handler,
			ReadHeaderTimeout: 2 * time.Second,
			ReadTimeout:       15 * time.Second,
			WriteTimeout:      15 * time.Second,
			IdleTimeout:       15 * time.Second,
			MaxHeaderBytes:    16 * 1024,
		}
		go func() { _ = manager.server.Serve(listener) }()
		go func() { _ = manager.server.Serve(tlsListener) }()
	}
	networks, err := manager.networks(manager.port, manager.tlsPort)
	if err != nil || len(networks) == 0 {
		return mobilePairingDescriptor{}, errors.New("no private IPv4 network is available")
	}
	id, err := randomBase64URL(24)
	if err != nil {
		return mobilePairingDescriptor{}, err
	}
	token, err := randomBase64URL(32)
	if err != nil {
		return mobilePairingDescriptor{}, err
	}
	code, err := randomPairingCode()
	if err != nil {
		return mobilePairingDescriptor{}, err
	}
	expiresAt := now.Add(mobilePairingSessionDuration)
	codeExpiresAt := now.Add(mobilePairingCodeDuration)
	manager.session = &mobilePairingSession{
		id: id, token: token, code: normalizePairingCode(code),
		codeExpiresAt: codeExpiresAt, expiresAt: expiresAt,
		failures: make(map[string][]time.Time),
	}
	return mobilePairingDescriptor{
		SchemaVersion:    1,
		BridgePairingID:  id,
		PairingToken:     token,
		PairingCode:      code,
		PairingExpiresAt: codeExpiresAt.UTC().Format(time.RFC3339),
		ExpiresAt:        expiresAt.UTC().Format(time.RFC3339),
		Networks:         networks,
	}, nil
}

func (manager *mobilePairingManager) Prepare(
	id string,
	token string,
	mobileLease string,
	mobileLeaseExpiry time.Time,
	pairingExpiry time.Time,
	now time.Time,
) error {
	manager.mu.Lock()
	defer manager.mu.Unlock()
	session := manager.session
	if session == nil || !now.Before(session.expiresAt) || session.claimed {
		return errors.New("mobile pairing unavailable")
	}
	if subtle.ConstantTimeCompare([]byte(id), []byte(session.id)) != 1 ||
		subtle.ConstantTimeCompare([]byte(token), []byte(session.token)) != 1 {
		return errors.New("mobile pairing identity mismatch")
	}
	if mobileLease == "" || len(mobileLease) > 8192 || !now.Before(mobileLeaseExpiry) || !now.Before(pairingExpiry) {
		return errors.New("mobile pairing authorization invalid")
	}
	if mobileLeaseExpiry.Before(session.expiresAt) {
		session.expiresAt = mobileLeaseExpiry
	}
	if pairingExpiry.Before(session.codeExpiresAt) {
		session.codeExpiresAt = pairingExpiry
	}
	if !now.Before(session.expiresAt) || !now.Before(session.codeExpiresAt) {
		return errors.New("mobile pairing authorization expired")
	}
	session.mobileLease = mobileLease
	session.mobileLeaseExpiry = mobileLeaseExpiry
	session.prepared = true
	return nil
}

func (manager *mobilePairingManager) Complete(client string, candidate string, now time.Time) (mobilePairingCompletion, mobilePairingCompleteResult) {
	manager.mu.Lock()
	defer manager.mu.Unlock()
	session := manager.session
	if session == nil || !now.Before(session.expiresAt) || !session.prepared || !now.Before(session.codeExpiresAt) {
		return mobilePairingCompletion{}, mobilePairingCompleteUnavailable
	}
	if session.claimed {
		return mobilePairingCompletion{}, mobilePairingCompleteGone
	}
	recent := session.failures[client][:0]
	for _, seen := range session.failures[client] {
		if now.Sub(seen) < mobilePairingAttemptWindow {
			recent = append(recent, seen)
		}
	}
	if len(recent) >= mobilePairingAttemptLimit {
		session.failures[client] = recent
		return mobilePairingCompletion{}, mobilePairingCompleteRateLimited
	}
	if subtle.ConstantTimeCompare([]byte(normalizePairingCode(candidate)), []byte(session.code)) != 1 {
		session.failures[client] = append(recent, now)
		return mobilePairingCompletion{}, mobilePairingCompleteInvalid
	}
	session.claimed = true
	delete(session.failures, client)
	expiresAt := session.expiresAt
	completion := mobilePairingCompletion{
		SchemaVersion:        1,
		BridgePairingID:      session.id,
		PairingToken:         session.token,
		MobileLease:          session.mobileLease,
		MobileLeaseExpiresAt: session.mobileLeaseExpiry.UTC().Format(time.RFC3339),
		ExpiresAt:            expiresAt.UTC().Format(time.RFC3339),
	}
	session.code = ""
	session.mobileLease = ""
	return completion, mobilePairingCompleteOK
}

func (manager *mobilePairingManager) Active(now time.Time) bool {
	manager.mu.RLock()
	defer manager.mu.RUnlock()
	return manager.session != nil && now.Before(manager.session.expiresAt)
}

func (manager *mobilePairingManager) Authorize(token string, now time.Time) bool {
	manager.mu.RLock()
	defer manager.mu.RUnlock()
	if manager.session == nil || !now.Before(manager.session.expiresAt) {
		return false
	}
	return subtle.ConstantTimeCompare([]byte(token), []byte(manager.session.token)) == 1
}

func (manager *mobilePairingManager) isPairingPort(port string) bool {
	manager.mu.RLock()
	defer manager.mu.RUnlock()
	return port != "" && (port == strconv.Itoa(manager.port) || port == strconv.Itoa(manager.tlsPort))
}

func (manager *mobilePairingManager) AllowPairingOrigin(origin string) bool {
	manager.mu.RLock()
	defer manager.mu.RUnlock()
	if manager.port <= 0 || manager.tlsPort <= 0 || manager.session == nil {
		return false
	}
	parsed, err := url.Parse(origin)
	if err != nil || parsed.User != nil || parsed.Path != "" || parsed.RawQuery != "" || parsed.Fragment != "" {
		return false
	}
	host, port, err := net.SplitHostPort(parsed.Host)
	if err != nil {
		return false
	}
	expectedPort := 0
	switch parsed.Scheme {
	case "http":
		expectedPort = manager.port
	case "https":
		expectedPort = manager.tlsPort
	default:
		return false
	}
	if port != strconv.Itoa(expectedPort) {
		return false
	}
	ip := net.ParseIP(host)
	return ip != nil && ip.To4() != nil && ip.IsPrivate()
}

func (manager *mobilePairingManager) Close() error {
	manager.mu.Lock()
	defer manager.mu.Unlock()
	manager.session = nil
	if manager.server != nil {
		_ = manager.server.Close()
	}
	var first error
	if manager.tlsListener != nil {
		first = manager.tlsListener.Close()
		manager.tlsListener = nil
	}
	if manager.listener != nil {
		err := manager.listener.Close()
		manager.listener = nil
		manager.server = nil
		if first == nil {
			first = err
		}
		return first
	}
	manager.server = nil
	return first
}

func privateIPv4Candidates(httpPort, tlsPort int) ([]mobileNetworkCandidate, error) {
	interfaces, err := net.Interfaces()
	if err != nil {
		return nil, err
	}
	output := make([]mobileNetworkCandidate, 0, 4)
	seen := map[string]struct{}{}
	for _, networkInterface := range interfaces {
		if networkInterface.Flags&net.FlagUp == 0 || networkInterface.Flags&net.FlagLoopback != 0 {
			continue
		}
		addresses, err := networkInterface.Addrs()
		if err != nil {
			continue
		}
		for _, address := range addresses {
			ip, _, err := net.ParseCIDR(address.String())
			if err != nil || ip.To4() == nil || !ip.IsPrivate() {
				continue
			}
			value := ip.String()
			if _, exists := seen[value]; exists {
				continue
			}
			seen[value] = struct{}{}
			output = append(output, mobileNetworkCandidate{
				Interface:   networkInterface.Name,
				Address:     value,
				Endpoint:    "http://" + net.JoinHostPort(value, strconv.Itoa(httpPort)) + "/",
				TLSEndpoint: "https://" + net.JoinHostPort(value, strconv.Itoa(tlsPort)) + "/",
			})
		}
	}
	sort.Slice(output, func(left, right int) bool {
		return output[left].Interface < output[right].Interface ||
			output[left].Interface == output[right].Interface && output[left].Address < output[right].Address
	})
	if len(output) > 8 {
		output = output[:8]
	}
	return output, nil
}

func randomBase64URL(size int) (string, error) {
	value := make([]byte, size)
	if _, err := rand.Read(value); err != nil {
		return "", err
	}
	return base64.RawURLEncoding.EncodeToString(value), nil
}

func randomPairingCode() (string, error) {
	raw := make([]byte, 8)
	if _, err := rand.Read(raw); err != nil {
		return "", err
	}
	for index := range raw {
		raw[index] = mobilePairingCodeAlphabet[int(raw[index])%len(mobilePairingCodeAlphabet)]
	}
	return string(raw[:4]) + "-" + string(raw[4:]), nil
}

func normalizePairingCode(value string) string {
	return strings.ToUpper(strings.NewReplacer("-", "", " ", "").Replace(strings.TrimSpace(value)))
}
