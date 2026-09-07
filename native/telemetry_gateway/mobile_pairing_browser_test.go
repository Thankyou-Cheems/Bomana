//go:build mobile_browser

package main

import (
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"testing"
	"time"
)

func TestStandardMobilePairingBrowser(t *testing.T) {
	assetRoot := os.Getenv("BOMANA_MOBILE_ASSET_ROOT")
	if assetRoot == "" {
		t.Fatal("run tools/smoke_mobile_pairing.ps1 after building App Web")
	}
	if _, err := os.Stat(filepath.Join(assetRoot, "Standard", "index.html")); err != nil {
		t.Fatal(err)
	}
	cdn := httptest.NewServer(http.StripPrefix("/mobile/", http.FileServer(http.Dir(assetRoot))))
	t.Cleanup(cdn.Close)
	originalBase := mobileAppBase
	mobileAppBase = cdn.URL + "/mobile/"
	t.Cleanup(func() { mobileAppBase = originalBase })
	upstream := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		http.Error(response, "offline", http.StatusServiceUnavailable)
	}))
	t.Cleanup(upstream.Close)
	gateway := newRelay(mustURL(upstream.URL), testOrigin)
	t.Cleanup(func() { _ = gateway.mobile.Close() })
	control := httptest.NewServer(gateway)
	t.Cleanup(control.Close)
	descriptor, err := gateway.mobile.StartEdition(gateway, time.Now(), mobileEditionStandard, false)
	if err != nil {
		t.Fatal(err)
	}
	command := exec.Command("node", "../../frontend/scripts/mobile-pairing-smoke.mjs")
	command.Env = append(os.Environ(), "BOMANA_PAIRING_REPRO_URL="+trayPairingHandoffURL(descriptor, 0), "BOMANA_PAIRING_CONTROL="+control.URL, "BOMANA_PAIRING_ORIGIN="+testOrigin)
	output, err := command.CombinedOutput()
	t.Log(string(output))
	if err != nil {
		t.Fatalf("Standard mobile browser feedback failed: %v", err)
	}
}
