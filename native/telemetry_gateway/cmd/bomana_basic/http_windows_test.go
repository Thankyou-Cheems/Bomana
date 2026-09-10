package main

import (
	"context"
	"fmt"
	"net/http"
	"net/http/httptest"
	"net/url"
	"runtime"
	"sync"
	"testing"
	"time"
)

func TestNativeHTTPReadsChunkedAndRejectsTruncatedResponses(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json; charset=utf-8")
		if r.URL.Path == "/truncated" {
			w.Header().Set("Content-Length", "100")
			fmt.Fprint(w, "{}")
			return
		}
		fmt.Fprint(w, "[1,")
		w.(http.Flusher).Flush()
		fmt.Fprint(w, "2]")
	}))
	defer server.Close()
	client, err := newLocalHTTP()
	if err != nil {
		t.Fatal(err)
	}
	defer client.close()
	u, _ := url.Parse(server.URL)
	body, contentType, err := client.read(context.Background(), u, 5)
	if err != nil || string(body) != "[1,2]" || contentType != "application/json; charset=utf-8" {
		t.Fatalf("chunked exact-limit response: body=%q type=%q err=%v", body, contentType, err)
	}
	u.Path = "/truncated"
	if _, _, err := client.read(context.Background(), u, 1000); err == nil {
		t.Fatal("accepted a body shorter than Content-Length")
	}
}

func TestNativeHTTPBoundsAStalledResponse(t *testing.T) {
	release := make(chan struct{})
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { <-release }))
	defer server.Close()
	defer close(release)
	client, err := newLocalHTTP()
	if err != nil {
		t.Fatal(err)
	}
	defer client.close()
	u, _ := url.Parse(server.URL)
	ctx, cancel := context.WithTimeout(context.Background(), 100*time.Millisecond)
	defer cancel()
	started := time.Now()
	if _, _, err := client.read(ctx, u, 1024); err == nil {
		t.Fatal("stalled response succeeded")
	}
	if elapsed := time.Since(started); elapsed > time.Second {
		t.Fatalf("stalled response exceeded its bounded wait: %v", elapsed)
	}
}

func TestNativeHTTPCancellationReleasesConcurrentReads(t *testing.T) {
	ready := make(chan struct{}, 4)
	release := make(chan struct{})
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		fmt.Fprint(w, "[")
		w.(http.Flusher).Flush()
		ready <- struct{}{}
		<-release
	}))
	defer server.Close()
	defer close(release)
	client, err := newLocalHTTP()
	if err != nil {
		t.Fatal(err)
	}
	defer client.close()
	u, _ := url.Parse(server.URL)
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	var wg sync.WaitGroup
	for range 4 {
		wg.Add(1)
		go func() {
			defer wg.Done()
			if _, _, err := client.read(ctx, u, 1024); err == nil {
				t.Error("cancelled incomplete response succeeded")
			}
		}()
	}
	for range 4 {
		select {
		case <-ready:
		case <-time.After(2 * time.Second):
			t.Fatal("concurrent reads did not start")
		}
	}
	runtime.GC()
	cancel()
	wg.Wait()
	httpRequests.Lock()
	remaining := len(httpRequests.live)
	httpRequests.Unlock()
	if remaining != 0 {
		t.Fatalf("cancelled requests retained callback state: %d", remaining)
	}
}
