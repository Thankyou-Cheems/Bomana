package main

import (
	"context"
	"encoding/binary"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"sync"
	"testing"
)

func TestSourceFixedRoutesHoldoverAndAuthoritativeEmpty(t *testing.T) {
	var mu sync.Mutex
	failObjects, invalid, empty := false, false, false
	paths := map[string]int{}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		defer mu.Unlock()
		paths[r.URL.Path]++
		if r.Method != "GET" {
			t.Error(r.Method)
		}
		w.Header().Set("Content-Type", "application/json")
		f := flight(1000)
		switch r.URL.Path {
		case "/icons.ttf":
			b := make([]byte, 29)
			b[1] = 1
			binary.BigEndian.PutUint16(b[4:6], 1)
			binary.BigEndian.PutUint32(b[20:24], 28)
			binary.BigEndian.PutUint32(b[24:28], 1)
			w.Write(b)
		case "/map_info.json":
			json.NewEncoder(w).Encode(f.MapInfo)
		case "/indicators":
			f.Indicators["valid"] = !invalid
			json.NewEncoder(w).Encode(f.Indicators)
		case "/state":
			json.NewEncoder(w).Encode(f.State)
		case "/map_objects.json":
			if failObjects {
				http.Error(w, "busy", 503)
			} else if empty {
				w.Write([]byte("[]"))
			} else {
				json.NewEncoder(w).Encode(map[string]any{"objects": f.Objects})
			}
		default:
			t.Error("unexpected route", r.URL.Path)
			http.NotFound(w, r)
		}
	}))
	defer server.Close()
	u, _ := url.Parse(server.URL)
	s, err := newSource([]*url.URL{u})
	if err != nil {
		t.Fatal(err)
	}
	defer s.client.CloseIdleConnections()
	f := s.read(context.Background(), 1000)
	if f.ObjectsAt != 1000 || len(f.Objects) != 6 {
		t.Fatalf("%+v", f)
	}
	mu.Lock()
	failObjects = true
	mu.Unlock()
	f = s.read(context.Background(), 2000)
	if f.ObjectsAt != 1000 || f.IndicatorsAt != 2000 {
		t.Fatal("holdover refreshed sample timestamp")
	}
	f = s.read(context.Background(), 4001)
	if f.ObjectsAt != 0 || len(f.Objects) != 0 {
		t.Fatal("stale objects retained")
	}
	mu.Lock()
	failObjects = false
	empty = true
	invalid = true
	mu.Unlock()
	f = s.read(context.Background(), 5000)
	if f.ObjectsAt != 5000 || len(f.Objects) != 0 || f.Indicators["valid"] != false {
		t.Fatal("authoritative empty/invalid masked")
	}
	mu.Lock()
	defer mu.Unlock()
	if paths["/icons.ttf"] != 1 {
		t.Fatal("repeated discovery on partial error")
	}
}
func TestSourceRejectsOffMachineAndRedirectsAndOversizedBodies(t *testing.T) {
	u, _ := url.Parse("https://example.com:8111")
	if _, err := newSource([]*url.URL{u}); err == nil {
		t.Fatal("accepted external source")
	}
	var called bool
	external := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { called = true }))
	defer external.Close()
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/redirect" {
			http.Redirect(w, r, external.URL, 302)
		} else {
			w.Write([]byte(strings.Repeat("x", 1024*1024+1)))
		}
	}))
	defer server.Close()
	u, _ = url.Parse(server.URL)
	s, _ := newSource([]*url.URL{u})
	defer s.client.CloseIdleConnections()
	for _, path := range []string{"/redirect", "/large"} {
		if _, err := s.get(context.Background(), u, path); err == nil {
			t.Fatal("accepted", path)
		}
	}
	if called {
		t.Fatal("followed redirect")
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := s.get(ctx, u, "/large"); err == nil {
		t.Fatal("ignored cancellation")
	}
}
