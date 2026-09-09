package main

import (
	"bytes"
	"fmt"
	"image"
	"image/png"
	"os"
	"path/filepath"
	"runtime"
	"testing"
	"time"
	"unsafe"
)

func preview(t *testing.T, r *renderer, name string) {
	t.Helper()
	root := os.Getenv("BOMANA_BASIC_PREVIEW_DIR")
	if root == "" {
		return
	}
	if err := os.MkdirAll(root, 0700); err != nil {
		t.Fatal(err)
	}
	im := image.NewRGBA(image.Rect(0, 0, r.output.width, r.output.height))
	for i := 0; i < len(im.Pix); i += 4 {
		p := r.output.pixels[i : i+4]
		im.Pix[i], im.Pix[i+1], im.Pix[i+2], im.Pix[i+3] = p[2], p[1], p[0], p[3]
	}
	f, err := os.Create(filepath.Join(root, name+".png"))
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	if err = png.Encode(f, im); err != nil {
		t.Fatal(err)
	}
}
func TestNativeRenderingHasIndependentZeroToFullOpacity(t *testing.T) {
	runtime.LockOSThread()
	defer runtime.UnlockOSThread()
	r, err := newRenderer(560, 1)
	if err != nil {
		t.Fatal(err)
	}
	defer r.close()
	m := running()
	v := m.snapshot(2100)
	s := defaults()
	r.render(v, s)
	preview(t, r, "default")
	if r.output.pixels[3] != byte(35*255/100) {
		t.Fatal("background opacity does not match")
	}
	s.Background = 0
	r.render(v, s)
	preview(t, r, "transparent")
	if r.output.pixels[3] != 0 {
		t.Fatal("background zero is not transparent")
	}
	for i := 0; i < len(r.output.pixels); i += 4 {
		p := r.output.pixels[i : i+4]
		if p[0] > p[3] || p[1] > p[3] || p[2] > p[3] {
			t.Fatal("layer is not premultiplied")
		}
	}
	s.Text = 0
	r.render(v, s)
	icons := bytes.Clone(r.output.pixels)
	preview(t, r, "icons-only")
	if bytes.Equal(icons, make([]byte, len(icons))) {
		t.Fatal("text opacity hid icons")
	}
	for y := 8; y < 46; y++ {
		for x := 16; x < 120; x++ {
			if icons[(y*r.output.width+x)*4+3] != 0 {
				t.Fatal("timer text remained at zero text opacity")
			}
		}
	}
	s.Text = 100
	s.Icons = 0
	r.render(v, s)
	preview(t, r, "text-only")
	if bytes.Equal(icons, r.output.pixels) {
		t.Fatal("independent layers did not change")
	}
	s.Text = 0
	r.render(v, s)
	if !bytes.Equal(r.output.pixels, make([]byte, len(icons))) {
		t.Fatal("all zero opacity left visible pixels")
	}
	r2, err := newRenderer(360, 1.5)
	if err != nil {
		t.Fatal(err)
	}
	defer r2.close()
	r2.render(v, defaults())
	preview(t, r2, "compact-150dpi")
	if r2.output.width != 540 || r2.output.height != 189 {
		t.Fatal("DPI dimensions")
	}
}
func TestNativeWindowSettingsRecoveryAndPersistence(t *testing.T) {
	runtime.LockOSThread()
	defer runtime.UnlockOSThread()
	path := filepath.Join(t.TempDir(), "settings.json")
	frames := make(chan frame, 1)
	frames <- flight(time.Now().UnixMilli())
	a, err := newApp(defaults(), path, frames, fmt.Sprintf("Bomana.BasicDesktop.Test.%d", time.Now().UnixNano()))
	if err != nil {
		t.Fatal(err)
	}
	defer a.close()
	style, _, _ := getWindowLong.Call(a.hwnd, signed(-20))
	if style&wsExLayered == 0 || style&wsExTopmost == 0 {
		t.Fatal("not a topmost layered window")
	}
	if a.paintError != nil {
		t.Fatal(a.paintError)
	}
	a.openSettings()
	if a.settingsWindow == 0 {
		t.Fatal("missing settings")
	}
	for i := 10; i <= 12; i++ {
		h := a.controls[i]
		if h == 0 {
			t.Fatal("missing slider")
		}
		sendMessage.Call(h, 0x405, 1, 0)
		sendMessage.Call(a.settingsWindow, wmHScroll, 0, h)
	}
	if a.model.Settings.Background != 0 || a.model.Settings.Text != 0 || a.model.Settings.Icons != 0 {
		t.Fatal("sliders did not reach zero")
	}
	a.setClickThrough(true)
	style, _, _ = getWindowLong.Call(a.hwnd, signed(-20))
	if style&wsExTransparent == 0 {
		t.Fatal("click through not applied")
	}
	setTitle(a.controls[13], "10")
	sendMessage.Call(a.settingsWindow, wmCommand, 18, 0)
	if a.settingsWindow != 0 {
		t.Fatal("settings close failed")
	}
	s := loadSettings(path)
	if s.Background != 0 || s.Text != 0 || s.Icons != 0 || s.Minutes != 10 {
		t.Fatal("zero values lost on reload", s)
	}
	sendMessage.Call(a.hwnd, wmSettings, 0, 0)
	if a.settingsWindow == 0 {
		t.Fatal("invisible click-through window could not recover settings")
	}
	sendMessage.Call(a.settingsWindow, wmCommand, 17, 0)
	if a.clickThrough || a.model.Settings.Text != 100 || a.model.Settings.Background != 35 || a.settingsWindow == 0 {
		t.Fatal("restore defaults failed")
	}
	if a.paintError != nil {
		t.Fatal(a.paintError)
	}
	var client, button winRect
	user32.NewProc("GetClientRect").Call(a.settingsWindow, uintptr(unsafe.Pointer(&client)))
	getWindowRect.Call(a.controls[18], uintptr(unsafe.Pointer(&button)))
	p := winPoint{button.Right, button.Bottom}
	user32.NewProc("ScreenToClient").Call(a.settingsWindow, uintptr(unsafe.Pointer(&p)))
	if p.X > client.Right || p.Y > client.Bottom {
		t.Fatal("settings button clipped", p, client)
	}
}
func TestSettingsCorruptionDefaultsAndAtomicReplacement(t *testing.T) {
	path := filepath.Join(t.TempDir(), "settings.json")
	if err := os.WriteFile(path, []byte("{\"Text\":0,garbled"), 0600); err != nil {
		t.Fatal(err)
	}
	if s := loadSettings(path); s.Text != 100 {
		t.Fatal("partially decoded corrupt settings were used")
	}
	s := defaults()
	s.Background = 0
	s.Minutes = 10
	if err := saveSettings(path, s); err != nil {
		t.Fatal(err)
	}
	s.Icons = 0
	if err := saveSettings(path, s); err != nil {
		t.Fatal(err)
	}
	if got := loadSettings(path); got.Background != 0 || got.Icons != 0 || got.Minutes != 10 {
		t.Fatal(got)
	}
}

func TestNativeMessageLoopConsumesTelemetry(t *testing.T) {
	runtime.LockOSThread()
	defer runtime.UnlockOSThread()
	// Earlier own-window tests close their message loops using WM_QUIT.
	var msg winMsg
	for {
		if ok, _, _ := user32.NewProc("PeekMessageW").Call(uintptr(unsafe.Pointer(&msg)), 0, 0x12, 0x12, 1); ok == 0 {
			break
		}
	}
	frames := make(chan frame, 1)
	a, err := newApp(defaults(), "", frames, fmt.Sprintf("Bomana.BasicDesktop.LoopTest.%d", time.Now().UnixNano()))
	if err != nil {
		t.Fatal(err)
	}
	frames <- flight(time.Now().UnixMilli())
	hwnd := a.hwnd
	go func() { time.Sleep(150 * time.Millisecond); postMessage.Call(hwnd, wmClose, 0, 0) }()
	a.loop()
	v := a.model.snapshot(time.Now().UnixMilli())
	if !v.HasHeading || v.Selected == nil || v.Selected.ID != "zone:a" {
		t.Fatal("message-loop timer did not consume telemetry")
	}
	if a.hwnd != 0 {
		t.Fatal("message loop did not close")
	}
}

func TestUnavailableHotkeysAreNotAdvertised(t *testing.T) {
	runtime.LockOSThread()
	defer runtime.UnlockOSThread()
	for i, mod := range []uintptr{3, 7} {
		registerHotKey.Call(0, uintptr(9800+i), mod|0x4000, 'M')
		defer unregisterHotKey.Call(0, uintptr(9800+i))
	}
	a, err := newApp(defaults(), "", nil, fmt.Sprintf("Bomana.BasicDesktop.HotkeyTest.%d", time.Now().UnixNano()))
	if err != nil {
		t.Fatal(err)
	}
	defer a.close()
	if a.hotkey != "" {
		t.Fatal("unavailable hotkey advertised", a.hotkey)
	}
	sendMessage.Call(a.hwnd, wmSettings, 0, 0)
	if a.settingsWindow == 0 {
		t.Fatal("relaunch recovery requires a registered shortcut")
	}
}

func TestNativeHitRoutingPassesThroughAndRestores(t *testing.T) {
	runtime.LockOSThread()
	defer runtime.UnlockOSThread()
	class := fmt.Sprintf("Bomana.BasicDesktop.HitTest.%d", time.Now().UnixNano())
	s := defaults()
	s.Background = 100
	a, err := newApp(s, "", nil, class)
	if err != nil {
		t.Fatal(err)
	}
	defer a.close()
	var rect winRect
	getWindowRect.Call(a.hwnd, uintptr(unsafe.Pointer(&rect)))
	instance, _, _ := getModuleHandle.Call(0)
	// A separate opaque test window lies immediately behind our real overlay.
	// Forced WM_NCHITTEST messages do not test layered-window input routing.
	under, _, _ := createWindow.Call(wsExTopmost|wsExToolWindow, uintptr(unsafe.Pointer(wide(class))), uintptr(unsafe.Pointer(wide("Bomana input routing test"))), wsPopup|wsVisible, signed(rect.Left), signed(rect.Top), uintptr(rect.Right-rect.Left), uintptr(rect.Bottom-rect.Top), 0, 0, instance, 0)
	if under == 0 {
		t.Fatal("cannot create underlying test window")
	}
	defer destroyWindow.Call(under)
	setWindowPos.Call(a.hwnd, ^uintptr(0), 0, 0, 0, 0, 0x1|0x2|0x10|0x40)
	a.paint()
	x, y := rect.Left+40, rect.Top+40
	packed := uintptr(uint64(uint32(x)) | uint64(uint32(y))<<32)
	lookup := user32.NewProc("WindowFromPoint")
	if got, _, _ := lookup.Call(packed); got != a.hwnd {
		t.Fatalf("opaque overlay not on top: %x != %x", got, a.hwnd)
	}
	a.setClickThrough(true)
	if got, _, _ := lookup.Call(packed); got != under {
		t.Fatalf("input did not reach underlying window: %x != %x", got, under)
	}
	a.setClickThrough(false)
	if got, _, _ := lookup.Call(packed); got != a.hwnd {
		t.Fatalf("normal input was not restored: %x != %x", got, a.hwnd)
	}
}
