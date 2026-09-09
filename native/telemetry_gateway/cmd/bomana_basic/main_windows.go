package main

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"time"
	"unsafe"
)

var version = "dev"
var sourceCommit = "unknown"
var builtAt = "unknown"

const appClass = "Bomana.BasicDesktop.Overlay.v1"

func main() {
	runtime.LockOSThread()
	defer runtime.UnlockOSThread()
	if len(os.Args) > 1 && os.Args[1] == "--build-info" {
		_ = json.NewEncoder(os.Stdout).Encode(map[string]string{"version": version, "source": sourceCommit, "builtAt": builtAt, "surface": "basic-desktop"})
		return
	}
	check := len(os.Args) > 1 && os.Args[1] == "--check-package"
	if !check {
		if hwnd, _, _ := findWindow.Call(uintptr(unsafe.Pointer(wide(appClass))), 0); hwnd != 0 {
			postMessage.Call(hwnd, wmSettings, 0, 0)
			return
		}
	}
	if proc := user32.NewProc("SetProcessDpiAwarenessContext"); proc.Find() == nil {
		proc.Call(signed(-4))
	}
	path := ""
	s := defaults()
	if !check {
		root, err := os.UserConfigDir()
		if err != nil {
			nativeError(0, "无法定位本地设置目录："+err.Error())
			return
		}
		// UserConfigDir is Roaming on Windows; keep these machine-specific settings
		// in LocalAppData when Windows provides it.
		if local := os.Getenv("LOCALAPPDATA"); local != "" {
			root = local
		}
		path = filepath.Join(root, "Bomana", "BasicDesktop", "settings.json")
		s = loadSettings(path)
	}
	frames := make(chan frame, 1)
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	if !check {
		src, err := newSource(nil)
		if err != nil {
			nativeError(0, err.Error())
			return
		}
		go func() {
			defer src.client.CloseIdleConnections()
			ticker := time.NewTicker(200 * time.Millisecond)
			defer ticker.Stop()
			for {
				select {
				case <-ctx.Done():
					return
				case <-ticker.C:
					f := src.read(ctx, time.Now().UnixMilli())
					select {
					case frames <- f:
					default:
						select {
						case <-frames:
						default:
						}
						select {
						case frames <- f:
						case <-ctx.Done():
							return
						}
					}
				}
			}
		}()
	}
	app, err := newApp(s, path, frames, appClass)
	if err != nil {
		if check {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
		nativeError(0, err.Error())
		return
	}
	if check {
		app.paint()
		ok := app.paintError == nil
		trayAvailable := app.trayOK
		app.close()
		_ = json.NewEncoder(os.Stdout).Encode(map[string]any{"surface": "basic-desktop", "nativeWindow": ok, "trayAvailable": trayAvailable, "version": version})
		if !ok {
			os.Exit(1)
		}
		return
	}
	showWindow.Call(app.hwnd, 4)
	app.loop()
}

func loadSettings(path string) settings {
	s := defaults()
	if data, err := os.ReadFile(path); err == nil {
		candidate := s
		if json.Unmarshal(data, &candidate) == nil {
			s = candidate
		}
	}
	s.normalize()
	return s
}
func saveSettings(path string, s settings) error {
	if path == "" {
		return nil
	}
	s.normalize()
	data, err := json.MarshalIndent(s, "", "  ")
	if err != nil {
		return err
	}
	if err = os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		return err
	}
	f, err := os.CreateTemp(filepath.Dir(path), "settings-*.tmp")
	if err != nil {
		return err
	}
	name := f.Name()
	defer os.Remove(name)
	if _, err = f.Write(data); err != nil {
		f.Close()
		return err
	}
	if err = f.Close(); err != nil {
		return err
	}
	ok, _, err := moveFileEx.Call(uintptr(unsafe.Pointer(wide(name))), uintptr(unsafe.Pointer(wide(path))), 1|8)
	if ok == 0 {
		return err
	}
	return nil
}
