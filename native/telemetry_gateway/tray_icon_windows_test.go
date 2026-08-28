//go:build windows

package main

import (
	"os"
	"runtime"
	"strings"
	"syscall"
	"testing"
	"unsafe"
)

var autoCloseTaskDialogCallback = syscall.NewCallback(func(hWnd uintptr, notification uint32, _ uintptr, _ *uint16, _ uintptr) uintptr {
	if notification == tdnCreated {
		_, _, _ = procSendMessageW.Call(hWnd, tdmClickButton, idClose, 0)
	}
	return 0
})

func TestClassicBomanaTrayIconLoads(t *testing.T) {
	icon, owned := createBomanaIcon()
	if icon == 0 || !owned {
		t.Fatal("classic Bomana tray icon did not load")
	}
	_, _, _ = procDestroyIcon.Call(icon)
}

func TestModernAboutDialogHasCommonControlsManifest(t *testing.T) {
	if err := procTaskDialogIndirect.Find(); err != nil {
		t.Fatalf("TaskDialogIndirect is unavailable: %v", err)
	}
	manifest, err := os.ReadFile("bridge_windows.manifest")
	if err != nil {
		t.Fatal(err)
	}
	text := string(manifest)
	for _, expected := range []string{"Microsoft.Windows.Common-Controls", "version=\"6.0.0.0\"", "level=\"asInvoker\"", "PerMonitorV2"} {
		if !strings.Contains(text, expected) {
			t.Fatalf("Bridge manifest missing %q: %s", expected, text)
		}
	}
	if runtime.GOARCH == "amd64" && unsafe.Sizeof(taskDialogConfig{}) != taskDialogConfigSize {
		t.Fatalf("unexpected TASKDIALOGCONFIG size: %d", unsafe.Sizeof(taskDialogConfig{}))
	}
	details := buildTrayAbout(trayConfig{
		projectURL:         projectURL,
		sponsorURL:         sponsorURL,
		enhancedSupportURL: enhancedSupportURL,
		privacyURL:         privacyURL,
		bridgeVersion:      "test",
		appWebVersion:      "test",
		buildProvenance:    "github-actions-sigstore",
	})
	if result := showModernAbout(details, 0, autoCloseTaskDialogCallback); int32(result) < 0 {
		t.Fatalf("modern About TaskDialog failed: 0x%08X", uint32(result))
	}
	if strings.Count(details.contentHTML+details.footerHTML, "<A HREF=") != 5 {
		t.Fatalf("modern About links are not encoded as TaskDialog hyperlinks: %s", details.contentHTML+details.footerHTML)
	}
	if strings.Contains(formatTrayAboutPlain(details), "<A HREF=") {
		t.Fatal("fallback About copy retained hyperlink markup")
	}
}
