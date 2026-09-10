package extui

import (
	"context"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"testing"
	"time"

	"bomana/native/telemetry_gateway/internal/extuihttp"
)

func TestResolverPrefersTheFirstVerifiedExtUI(t *testing.T) {
	first := newVerifiedExtUIServer(t)
	second := newVerifiedExtUIServer(t)
	resolver, err := NewResolver(Options{
		Candidates: []*url.URL{mustURL(t, first.URL), mustURL(t, second.URL)},
		Read:       extuihttp.NewReader(&http.Client{Timeout: time.Second}),
		RetryDelay: time.Second,
	})
	if err != nil {
		t.Fatal(err)
	}

	resolved, err := resolver.Resolve(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if resolved.Host != mustURL(t, first.URL).Host {
		t.Fatalf("resolved %s, want first candidate %s", resolved, first.URL)
	}
}

func TestResolverKeepsTheSelectedExtUIUntilInvalidated(t *testing.T) {
	rejectFirst := false
	first := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		if rejectFirst {
			http.Error(response, "probe must not repeat", http.StatusServiceUnavailable)
			return
		}
		serveVerifiedExtUI(response, request)
	}))
	t.Cleanup(first.Close)
	second := newVerifiedExtUIServer(t)
	resolver, err := NewResolver(Options{
		Candidates: []*url.URL{mustURL(t, first.URL), mustURL(t, second.URL)},
		Read:       extuihttp.NewReader(&http.Client{Timeout: time.Second}),
		RetryDelay: time.Second,
	})
	if err != nil {
		t.Fatal(err)
	}

	selected, err := resolver.Resolve(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	rejectFirst = true
	cached, err := resolver.Resolve(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if cached.Host != selected.Host {
		t.Fatalf("cached resolver switched from %s to %s without invalidation", selected, cached)
	}
}

func TestResolverRediscoversAfterTheSelectedExtUIFails(t *testing.T) {
	rejectFirst := false
	first := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		if rejectFirst {
			http.Error(response, "stopped", http.StatusServiceUnavailable)
			return
		}
		serveVerifiedExtUI(response, request)
	}))
	t.Cleanup(first.Close)
	second := newVerifiedExtUIServer(t)
	resolver, err := NewResolver(Options{
		Candidates: []*url.URL{mustURL(t, first.URL), mustURL(t, second.URL)},
		Read:       extuihttp.NewReader(&http.Client{Timeout: time.Second}),
		RetryDelay: time.Second,
	})
	if err != nil {
		t.Fatal(err)
	}

	selected, err := resolver.Resolve(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	rejectFirst = true
	resolver.Invalidate(selected)
	recovered, err := resolver.Resolve(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if recovered.Host != mustURL(t, second.URL).Host {
		t.Fatalf("resolved %s after invalidation, want %s", recovered, second.URL)
	}
}

func TestResolverBacksOffAfterNoExtUIIsAvailable(t *testing.T) {
	available := false
	server := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		if !available {
			http.Error(response, "game is not running", http.StatusServiceUnavailable)
			return
		}
		serveVerifiedExtUI(response, request)
	}))
	t.Cleanup(server.Close)
	now := time.Unix(1_000, 0)
	resolver, err := NewResolver(Options{
		Candidates: []*url.URL{mustURL(t, server.URL)},
		Read:       extuihttp.NewReader(&http.Client{Timeout: time.Second}),
		Now:        func() time.Time { return now },
		RetryDelay: time.Second,
	})
	if err != nil {
		t.Fatal(err)
	}

	if _, err := resolver.Resolve(context.Background()); err == nil {
		t.Fatal("missing game unexpectedly resolved")
	}
	available = true
	if _, err := resolver.Resolve(context.Background()); err == nil {
		t.Fatal("resolver ignored the negative retry window")
	}
	now = now.Add(time.Second)
	if _, err := resolver.Resolve(context.Background()); err != nil {
		t.Fatalf("resolver did not retry after the backoff: %v", err)
	}
}

func TestResolverDoesNotNegativeCacheACancelledDiscovery(t *testing.T) {
	server := newVerifiedExtUIServer(t)
	resolver, err := NewResolver(Options{
		Candidates: []*url.URL{mustURL(t, server.URL)},
		Read:       extuihttp.NewReader(&http.Client{Timeout: time.Second}),
		RetryDelay: time.Minute,
	})
	if err != nil {
		t.Fatal(err)
	}

	cancelled, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := resolver.Resolve(cancelled); err == nil {
		t.Fatal("cancelled discovery unexpectedly resolved")
	}
	if _, err := resolver.Resolve(context.Background()); err != nil {
		t.Fatalf("cancelled discovery poisoned the negative cache: %v", err)
	}
}

func TestResolverSnapshotReportsTheSelectedExtUIPort(t *testing.T) {
	server := newVerifiedExtUIServer(t)
	resolver, err := NewResolver(Options{
		Candidates: []*url.URL{mustURL(t, server.URL)},
		Read:       extuihttp.NewReader(&http.Client{Timeout: time.Second}),
		RetryDelay: time.Second,
	})
	if err != nil {
		t.Fatal(err)
	}
	if _, err := resolver.Resolve(context.Background()); err != nil {
		t.Fatal(err)
	}

	wantPort := mustURL(t, server.URL).Port()
	snapshot := resolver.Snapshot()
	if snapshot.State != StateReady || snapshot.Port != wantPort {
		t.Fatalf("snapshot = %#v, want state=%q port=%q", snapshot, StateReady, wantPort)
	}
}

func TestDefaultCandidatesAreTheFixedWarThunderFallbackPorts(t *testing.T) {
	candidates := DefaultCandidates()
	wantPorts := []string{"8111", "9222", "10333"}
	if len(candidates) != len(wantPorts) {
		t.Fatalf("default candidate count = %d, want %d", len(candidates), len(wantPorts))
	}
	for index, candidate := range candidates {
		if candidate.Scheme != "http" || candidate.Hostname() != "127.0.0.1" || candidate.Port() != wantPorts[index] {
			t.Fatalf("candidate %d = %s, want 127.0.0.1:%s", index, candidate, wantPorts[index])
		}
	}
}

func TestResolverRejectsAnIncompleteMapInfoFingerprint(t *testing.T) {
	impostor := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		switch request.URL.Path {
		case "/map_info.json":
			response.Header().Set("Content-Type", "application/json")
			_, _ = io.WriteString(response, `{"valid":true}`)
		case "/indicators":
			response.Header().Set("Content-Type", "application/json")
			_, _ = io.WriteString(response, `{"valid":false}`)
		case "/icons.ttf":
			response.Header().Set("Content-Type", "application/octet-stream")
			_, _ = response.Write([]byte{0x00, 0x01, 0x00, 0x00, 0x00, 0x01})
		default:
			http.NotFound(response, request)
		}
	}))
	t.Cleanup(impostor.Close)
	verified := newVerifiedExtUIServer(t)
	resolver, err := NewResolver(Options{
		Candidates: []*url.URL{mustURL(t, impostor.URL), mustURL(t, verified.URL)},
		Read:       extuihttp.NewReader(&http.Client{Timeout: time.Second}),
		RetryDelay: time.Second,
	})
	if err != nil {
		t.Fatal(err)
	}

	resolved, err := resolver.Resolve(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if resolved.Host != mustURL(t, verified.URL).Host {
		t.Fatalf("incomplete map-info service was accepted: %s", resolved)
	}
}

func TestResolverRejectsIndicatorsWithoutAnArmyWhenValid(t *testing.T) {
	impostor := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		switch request.URL.Path {
		case "/map_info.json":
			response.Header().Set("Content-Type", "application/json")
			_, _ = io.WriteString(response, `{"valid":false}`)
		case "/indicators":
			response.Header().Set("Content-Type", "application/json")
			_, _ = io.WriteString(response, `{"valid":true}`)
		case "/icons.ttf":
			response.Header().Set("Content-Type", "application/octet-stream")
			_, _ = response.Write([]byte{0x00, 0x01, 0x00, 0x00, 0x00, 0x01})
		default:
			http.NotFound(response, request)
		}
	}))
	t.Cleanup(impostor.Close)
	verified := newVerifiedExtUIServer(t)
	resolver, err := NewResolver(Options{
		Candidates: []*url.URL{mustURL(t, impostor.URL), mustURL(t, verified.URL)},
		Read:       extuihttp.NewReader(&http.Client{Timeout: time.Second}),
		RetryDelay: time.Second,
	})
	if err != nil {
		t.Fatal(err)
	}

	resolved, err := resolver.Resolve(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if resolved.Host != mustURL(t, verified.URL).Host {
		t.Fatalf("incomplete indicators service was accepted: %s", resolved)
	}
}

func TestResolverRejectsATruncatedSFNTFingerprint(t *testing.T) {
	impostor := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		switch request.URL.Path {
		case "/map_info.json", "/indicators":
			response.Header().Set("Content-Type", "application/json")
			_, _ = io.WriteString(response, `{"valid":false}`)
		case "/icons.ttf":
			response.Header().Set("Content-Type", "application/octet-stream")
			_, _ = response.Write([]byte{0x00, 0x01, 0x00, 0x00, 0x00, 0x01})
		default:
			http.NotFound(response, request)
		}
	}))
	t.Cleanup(impostor.Close)
	verified := newVerifiedExtUIServer(t)
	resolver, err := NewResolver(Options{
		Candidates: []*url.URL{mustURL(t, impostor.URL), mustURL(t, verified.URL)},
		Read:       extuihttp.NewReader(&http.Client{Timeout: time.Second}),
		RetryDelay: time.Second,
	})
	if err != nil {
		t.Fatal(err)
	}

	resolved, err := resolver.Resolve(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if resolved.Host != mustURL(t, verified.URL).Host {
		t.Fatalf("truncated sfnt service was accepted: %s", resolved)
	}
}

func newVerifiedExtUIServer(t *testing.T) *httptest.Server {
	t.Helper()
	server := httptest.NewServer(http.HandlerFunc(serveVerifiedExtUI))
	t.Cleanup(server.Close)
	return server
}

func serveVerifiedExtUI(response http.ResponseWriter, request *http.Request) {
	switch request.URL.Path {
	case "/map_info.json", "/indicators":
		response.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(response, `{"valid":false}`)
	case "/icons.ttf":
		response.Header().Set("Content-Type", "application/octet-stream")
		_, _ = response.Write(testSFNT())
	default:
		http.NotFound(response, request)
	}
}

func testSFNT() []byte {
	return []byte{
		0x00, 0x01, 0x00, 0x00, 0x00, 0x01, 0x00, 0x10, 0x00, 0x00, 0x00, 0x00,
		'g', 'l', 'y', 'f', 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x1c,
		0x00, 0x00, 0x00, 0x01, 0x00,
	}
}

func mustURL(t *testing.T, raw string) *url.URL {
	t.Helper()
	parsed, err := url.Parse(raw)
	if err != nil {
		t.Fatal(err)
	}
	return parsed
}
