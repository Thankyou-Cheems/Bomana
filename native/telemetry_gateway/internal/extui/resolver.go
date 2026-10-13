package extui

import (
	"context"
	"encoding/binary"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"mime"
	"net/netip"
	"net/url"
	"strings"
	"sync"
	"time"
)

const (
	maxProbeJSONBytes = 64 * 1024
	maxProbeFontBytes = 2 * 1024 * 1024
	// Three ordered ports, each with at most three 750 ms fingerprint reads.
	defaultDiscoveryTimeout = 3 * 3 * 750 * time.Millisecond
)

var defaultPorts = [...]string{"8111", "9222", "10333"}
var ErrClosed = errors.New("ExtUI resolver is closed")

// ReadFunc performs one bounded GET, rejects non-200 responses, and returns the
// body and Content-Type. Keeping transport outside the resolver lets the small
// native surface use system HTTP without linking Go's HTTP/TLS implementation.
// Read must honor context cancellation; discovery never starts parallel probes.
type ReadFunc func(context.Context, *url.URL, int64) ([]byte, string, error)

type Options struct {
	Candidates       []*url.URL
	Read             ReadFunc
	Now              func() time.Time
	RetryDelay       time.Duration
	DiscoveryTimeout time.Duration
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

// Selection identifies one verified upstream lifetime, even when its address is
// reused after recovery. Resolve returns a copy; callers retain it until their
// request completes and may invalidate only that lifetime.
type Selection struct {
	url.URL
	generation uint64
}

func (selection *Selection) Generation() uint64 { return selection.generation }

type Resolver struct {
	candidates       []*url.URL
	read             ReadFunc
	now              func() time.Time
	retryDelay       time.Duration
	discoveryTimeout time.Duration
	discovery        *discovery
	closed           bool
	mu               sync.Mutex
	selected         *Selection
	generation       uint64
	nextProbe        time.Time
	lastError        error
}

type discovery struct {
	done      chan struct{}
	selection *Selection
	err       error
	cancel    context.CancelFunc
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
	if options.Read == nil {
		return nil, errors.New("ExtUI bounded reader is required")
	}
	now := options.Now
	if now == nil {
		now = time.Now
	}
	retryDelay := options.RetryDelay
	if retryDelay <= 0 {
		retryDelay = time.Second
	}
	discoveryTimeout := options.DiscoveryTimeout
	if discoveryTimeout <= 0 {
		discoveryTimeout = defaultDiscoveryTimeout
	}
	return &Resolver{candidates: candidates, read: options.Read, now: now, retryDelay: retryDelay, discoveryTimeout: discoveryTimeout}, nil
}

func (resolver *Resolver) Resolve(ctx context.Context) (*Selection, error) {
	resolver.mu.Lock()
	if err := ctx.Err(); err != nil {
		resolver.mu.Unlock()
		return nil, err
	}
	if resolver.closed {
		resolver.mu.Unlock()
		return nil, ErrClosed
	}
	if resolver.selected != nil {
		copy := *resolver.selected
		resolver.mu.Unlock()
		return &copy, nil
	}
	if resolver.lastError != nil && resolver.now().Before(resolver.nextProbe) {
		err := resolver.lastError
		resolver.mu.Unlock()
		return nil, err
	}
	flight := resolver.discovery
	if flight == nil {
		flight = &discovery{done: make(chan struct{})}
		resolver.discovery = flight
		// Discovery belongs to the resolver, not to its first browser request.
		// It can finish with no waiters, but only within this one total deadline.
		discoveryContext, cancel := context.WithTimeout(context.Background(), resolver.discoveryTimeout)
		flight.cancel = cancel
		go resolver.discover(discoveryContext, cancel, flight)
	}
	resolver.mu.Unlock()
	select {
	case <-ctx.Done():
		return nil, ctx.Err()
	case <-flight.done:
		if err := ctx.Err(); err != nil {
			return nil, err
		}
		resolver.mu.Lock()
		defer resolver.mu.Unlock()
		if resolver.closed {
			return nil, ErrClosed
		}
		if flight.selection != nil {
			copy := *flight.selection
			return &copy, nil
		}
		return nil, flight.err
	}
}

// Close cancels owner work and joins it before its transport may be released.
// Caller cancellation remains independent; only the owner closes the resolver.
func (resolver *Resolver) Close() {
	resolver.mu.Lock()
	resolver.closed = true
	resolver.selected = nil
	resolver.lastError = ErrClosed
	flight := resolver.discovery
	resolver.mu.Unlock()
	if flight != nil {
		flight.cancel()
		<-flight.done // Never wait while holding the resolver mutex.
	}
}

func (resolver *Resolver) discover(ctx context.Context, cancel context.CancelFunc, flight *discovery) {
	defer cancel()
	var selected *url.URL
	for _, candidate := range resolver.candidates {
		if ctx.Err() != nil {
			break
		}
		if err := resolver.verify(ctx, candidate); err == nil {
			if ctx.Err() == nil {
				selected = candidate
			}
			break
		}
	}
	resolver.mu.Lock()
	defer resolver.mu.Unlock()
	if resolver.closed {
		flight.err = ErrClosed
	} else if selected != nil && ctx.Err() == nil {
		resolver.generation++
		flight.selection = &Selection{URL: *selected, generation: resolver.generation}
		resolver.selected = flight.selection
		resolver.nextProbe = time.Time{}
		resolver.lastError = nil
	} else {
		flight.err = errors.New("War Thunder ExtUI is unavailable")
		if ctx.Err() != nil {
			flight.err = fmt.Errorf("War Thunder ExtUI discovery deadline: %w", ctx.Err())
		}
		resolver.lastError = flight.err
		resolver.nextProbe = resolver.now().Add(resolver.retryDelay)
	}
	resolver.discovery = nil
	close(flight.done)
}

func (resolver *Resolver) Invalidate(candidate *Selection) bool {
	if candidate == nil {
		return false
	}
	resolver.mu.Lock()
	defer resolver.mu.Unlock()
	if resolver.selected != nil && resolver.selected.generation == candidate.generation && resolver.selected.Scheme == candidate.Scheme && resolver.selected.Host == candidate.Host {
		resolver.selected = nil
		resolver.nextProbe = time.Time{}
		resolver.lastError = nil
		return true
	}
	return false
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
		if err := ctx.Err(); err != nil {
			return err
		}
		if err := resolver.verifyJSON(ctx, candidate, path); err != nil {
			return err
		}
	}
	if err := ctx.Err(); err != nil {
		return err
	}
	return resolver.verifyFont(ctx, candidate)
}

func (resolver *Resolver) verifyJSON(ctx context.Context, candidate *url.URL, path string) error {
	probeURL := *candidate
	probeURL.Path = path
	body, contentType, err := resolver.read(ctx, &probeURL, maxProbeJSONBytes)
	if err != nil {
		return err
	}
	if !contentTypeIs(contentType, "application/json") {
		return fmt.Errorf("%s did not return ExtUI JSON", path)
	}
	if len(body) > maxProbeJSONBytes {
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
	body, _, err := resolver.read(ctx, &probeURL, maxProbeFontBytes)
	if err != nil {
		return err
	}
	if len(body) > maxProbeFontBytes || !validSFNT(body) {
		return errors.New("icons.ttf is not a bounded sfnt font")
	}
	return nil
}

func validateCandidate(candidate *url.URL) error {
	if candidate == nil || candidate.Scheme != "http" || candidate.User != nil || candidate.RawQuery != "" || candidate.Fragment != "" {
		return errors.New("ExtUI candidate must be an uncredentialed loopback HTTP origin")
	}
	host := candidate.Hostname()
	ip, err := netip.ParseAddr(host)
	if host != "localhost" && (err != nil || !ip.IsLoopback()) {
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
