package extui

import (
	"context"
	"encoding/binary"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math"
	"mime"
	"net"
	"net/http"
	"net/url"
	"strings"
	"sync"
	"time"
)

const (
	maxProbeJSONBytes = 64 * 1024
	maxProbeFontBytes = 2 * 1024 * 1024
)

var defaultPorts = [...]string{"8111", "9222", "10333"}

type Options struct {
	Candidates []*url.URL
	Client     *http.Client
	Now        func() time.Time
	RetryDelay time.Duration
}

type State string

const (
	StateIdle        State = "idle"
	StateReady       State = "ready"
	StateUnavailable State = "unavailable"
)

type Snapshot struct {
	State     State
	Port      string
	LastError string
}

type Resolver struct {
	candidates []*url.URL
	client     *http.Client
	now        func() time.Time
	retryDelay time.Duration
	mu         sync.Mutex
	selected   *url.URL
	nextProbe  time.Time
	lastError  error
}

func DefaultCandidates() []*url.URL {
	candidates := make([]*url.URL, 0, len(defaultPorts))
	for _, port := range defaultPorts {
		candidate, _ := url.Parse("http://127.0.0.1:" + port)
		candidates = append(candidates, candidate)
	}
	return candidates
}

func NewResolver(options Options) (*Resolver, error) {
	if len(options.Candidates) == 0 {
		return nil, errors.New("ExtUI candidates are required")
	}
	candidates := make([]*url.URL, 0, len(options.Candidates))
	for _, candidate := range options.Candidates {
		if err := validateCandidate(candidate); err != nil {
			return nil, err
		}
		copy := *candidate
		copy.Path = "/"
		copy.RawQuery = ""
		copy.Fragment = ""
		candidates = append(candidates, &copy)
	}
	client := options.Client
	if client == nil {
		client = &http.Client{Timeout: 750 * time.Millisecond}
	}
	now := options.Now
	if now == nil {
		now = time.Now
	}
	retryDelay := options.RetryDelay
	if retryDelay <= 0 {
		retryDelay = time.Second
	}
	return &Resolver{candidates: candidates, client: client, now: now, retryDelay: retryDelay}, nil
}

func (resolver *Resolver) Resolve(ctx context.Context) (*url.URL, error) {
	resolver.mu.Lock()
	defer resolver.mu.Unlock()
	if resolver.selected != nil {
		copy := *resolver.selected
		return &copy, nil
	}
	if resolver.lastError != nil && resolver.now().Before(resolver.nextProbe) {
		return nil, resolver.lastError
	}
	for _, candidate := range resolver.candidates {
		if err := resolver.verify(ctx, candidate); err == nil {
			copy := *candidate
			resolver.selected = &copy
			resolver.nextProbe = time.Time{}
			resolver.lastError = nil
			return &copy, nil
		}
		if err := ctx.Err(); err != nil {
			return nil, err
		}
	}
	resolver.lastError = errors.New("War Thunder ExtUI is unavailable")
	resolver.nextProbe = resolver.now().Add(resolver.retryDelay)
	return nil, resolver.lastError
}

func (resolver *Resolver) Invalidate(candidate *url.URL) {
	if candidate == nil {
		return
	}
	resolver.mu.Lock()
	defer resolver.mu.Unlock()
	if resolver.selected != nil && resolver.selected.Scheme == candidate.Scheme && resolver.selected.Host == candidate.Host {
		resolver.selected = nil
		resolver.nextProbe = time.Time{}
		resolver.lastError = nil
	}
}

func (resolver *Resolver) Snapshot() Snapshot {
	resolver.mu.Lock()
	defer resolver.mu.Unlock()
	if resolver.selected != nil {
		return Snapshot{State: StateReady, Port: resolver.selected.Port()}
	}
	if resolver.lastError != nil {
		return Snapshot{State: StateUnavailable, LastError: resolver.lastError.Error()}
	}
	return Snapshot{State: StateIdle}
}

func (resolver *Resolver) verify(ctx context.Context, candidate *url.URL) error {
	for _, path := range []string{"/map_info.json", "/indicators"} {
		if err := resolver.verifyJSON(ctx, candidate, path); err != nil {
			return err
		}
	}
	return resolver.verifyFont(ctx, candidate)
}

func (resolver *Resolver) verifyJSON(ctx context.Context, candidate *url.URL, path string) error {
	probeURL := *candidate
	probeURL.Path = path
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, probeURL.String(), nil)
	if err != nil {
		return err
	}
	request.Header.Set("Accept", "application/json")
	response, err := resolver.client.Do(request)
	if err != nil {
		return err
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK || !contentTypeIs(response.Header.Get("Content-Type"), "application/json") {
		return fmt.Errorf("%s did not return ExtUI JSON", path)
	}
	body, err := io.ReadAll(io.LimitReader(response.Body, maxProbeJSONBytes+1))
	if err != nil || len(body) > maxProbeJSONBytes {
		return fmt.Errorf("%s response exceeded the probe limit", path)
	}
	var object map[string]json.RawMessage
	if err := json.Unmarshal(body, &object); err != nil {
		return fmt.Errorf("%s response is invalid JSON", path)
	}
	var valid bool
	if raw, ok := object["valid"]; !ok || json.Unmarshal(raw, &valid) != nil {
		return fmt.Errorf("%s response lacks a boolean valid field", path)
	}
	if valid && path == "/map_info.json" && !validMapInfo(object) {
		return errors.New("map_info.json lacks the ExtUI map descriptor")
	}
	if valid && path == "/indicators" {
		var army string
		if raw, ok := object["army"]; !ok || json.Unmarshal(raw, &army) != nil || strings.TrimSpace(army) == "" {
			return errors.New("indicators lacks the ExtUI army field")
		}
	}
	return nil
}

func validMapInfo(object map[string]json.RawMessage) bool {
	for _, key := range []string{"map_min", "map_max", "grid_steps"} {
		if !finitePair(object[key]) {
			return false
		}
	}
	var hudType float64
	if raw, ok := object["hud_type"]; !ok || json.Unmarshal(raw, &hudType) != nil || math.IsNaN(hudType) || math.IsInf(hudType, 0) {
		return false
	}
	return true
}

func finitePair(raw json.RawMessage) bool {
	var values []float64
	if len(raw) == 0 || json.Unmarshal(raw, &values) != nil || len(values) != 2 {
		return false
	}
	return !math.IsNaN(values[0]) && !math.IsInf(values[0], 0) && !math.IsNaN(values[1]) && !math.IsInf(values[1], 0)
}

func (resolver *Resolver) verifyFont(ctx context.Context, candidate *url.URL) error {
	probeURL := *candidate
	probeURL.Path = "/icons.ttf"
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, probeURL.String(), nil)
	if err != nil {
		return err
	}
	request.Header.Set("Accept", "font/ttf, application/octet-stream")
	response, err := resolver.client.Do(request)
	if err != nil {
		return err
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return errors.New("icons.ttf is unavailable")
	}
	body, err := io.ReadAll(io.LimitReader(response.Body, maxProbeFontBytes+1))
	if err != nil || len(body) > maxProbeFontBytes || !validSFNT(body) {
		return errors.New("icons.ttf is not a bounded sfnt font")
	}
	return nil
}

func validateCandidate(candidate *url.URL) error {
	if candidate == nil || candidate.Scheme != "http" || candidate.User != nil || candidate.RawQuery != "" || candidate.Fragment != "" {
		return errors.New("ExtUI candidate must be an uncredentialed loopback HTTP origin")
	}
	host := candidate.Hostname()
	ip := net.ParseIP(host)
	if host != "localhost" && (ip == nil || !ip.IsLoopback()) {
		return errors.New("ExtUI candidate must use loopback")
	}
	if candidate.Port() == "" {
		return errors.New("ExtUI candidate port is required")
	}
	return nil
}

func contentTypeIs(value, expected string) bool {
	mediaType, _, err := mime.ParseMediaType(value)
	return err == nil && mediaType == expected
}

func validSFNT(body []byte) bool {
	if len(body) < 12 {
		return false
	}
	signature := string(body[:4])
	if signature != "OTTO" && signature != "true" && signature != "typ1" &&
		!(body[0] == 0x00 && body[1] == 0x01 && body[2] == 0x00 && body[3] == 0x00) {
		return false
	}
	numTables := int(binary.BigEndian.Uint16(body[4:6]))
	if numTables == 0 || numTables > (len(body)-12)/16 {
		return false
	}
	directoryEnd := 12 + numTables*16
	for record := 12; record < directoryEnd; record += 16 {
		tableOffset := uint64(binary.BigEndian.Uint32(body[record+8 : record+12]))
		tableLength := uint64(binary.BigEndian.Uint32(body[record+12 : record+16]))
		if tableLength == 0 || tableOffset < uint64(directoryEnd) || tableOffset+tableLength > uint64(len(body)) {
			return false
		}
	}
	return true
}
