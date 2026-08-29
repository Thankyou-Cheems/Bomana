//go:build windows

package main

import (
	"encoding/base64"
	"encoding/binary"
	"fmt"
	"log/slog"
	"runtime"
	"sync"
	"syscall"
	"time"
	"unsafe"
)

const (
	wmDestroy       = 0x0002
	wmClose         = 0x0010
	wmNull          = 0x0000
	wmContextMenu   = 0x007B
	wmRButtonUp     = 0x0205
	wmLButtonDblClk = 0x0203
	wmApp           = 0x8000
	trayMessage     = wmApp + 1

	nimAdd        = 0x00000000
	nimDelete     = 0x00000002
	nimSetVersion = 0x00000004
	nifMessage    = 0x00000001
	nifIcon       = 0x00000002
	nifTip        = 0x00000004
	nifInfo       = 0x00000010
	niifInfo      = 0x00000001
	notifyVersion = 4

	mfString    = 0x0000
	mfDisabled  = 0x0002
	mfGrayed    = 0x0001
	mfSeparator = 0x0800

	tpmRightButton = 0x0002
	tpmBottomAlign = 0x0020
	tpmReturnCmd   = 0x0100

	menuOpenWeb       = 1001
	menuMobilePairing = 1002
	menuOpenLauncher  = 1003
	menuStarProject   = 1004
	menuSponsor       = 1005
	menuAbout         = 1006
	menuExit          = 1007
	swShowNormal      = 1
	idiApplication    = 32512
	mbOK              = 0x00000000
	mbIconInformation = 0x00000040

	tdfEnableHyperlinks  = 0x0001
	tdfAllowDialogCancel = 0x0008
	tdfExpandedByDefault = 0x0080
	tdfSizeToContent     = 0x01000000
	tdcbfCloseButton     = 0x0020
	tdnCreated           = 0
	tdnHyperlinkClicked  = 3
	tdInformationIcon    = 0xFFFD
	tdmClickButton       = 0x0400 + 102
	idClose              = 8
)

type point struct {
	x int32
	y int32
}

type message struct {
	hWnd    uintptr
	message uint32
	wParam  uintptr
	lParam  uintptr
	time    uint32
	pt      point
	private uint32
}

type windowClassEx struct {
	cbSize     uint32
	style      uint32
	wndProc    uintptr
	clsExtra   int32
	wndExtra   int32
	instance   uintptr
	icon       uintptr
	cursor     uintptr
	background uintptr
	menuName   *uint16
	className  *uint16
	iconSmall  uintptr
}

type notifyIconData struct {
	cbSize           uint32
	hWnd             uintptr
	id               uint32
	flags            uint32
	callbackMessage  uint32
	icon             uintptr
	tip              [128]uint16
	state            uint32
	stateMask        uint32
	info             [256]uint16
	timeoutOrVersion uint32
	infoTitle        [64]uint16
	infoFlags        uint32
	guidItem         [16]byte
	balloonIcon      uintptr
}

const taskDialogConfigSize = 160

type taskDialogConfig [taskDialogConfigSize]byte

func (config *taskDialogConfig) setUint32(offset int, value uint32) {
	binary.LittleEndian.PutUint32(config[offset:offset+4], value)
}

func (config *taskDialogConfig) setPointer(offset int, value uintptr) {
	binary.LittleEndian.PutUint64(config[offset:offset+8], uint64(value))
}

type trayController struct {
	hWnd uintptr
	done <-chan struct{}
	once sync.Once
}

type trayStartResult struct {
	controller *trayController
	err        error
}

type windowsTray struct {
	config         trayConfig
	hWnd           uintptr
	icon           uintptr
	iconOwned      bool
	data           notifyIconData
	taskbarCreated uint32
}

var (
	user32   = syscall.NewLazyDLL("user32.dll")
	shell32  = syscall.NewLazyDLL("shell32.dll")
	kernel32 = syscall.NewLazyDLL("kernel32.dll")
	comctl32 = syscall.NewLazyDLL("comctl32.dll")

	procRegisterClassExW         = user32.NewProc("RegisterClassExW")
	procCreateWindowExW          = user32.NewProc("CreateWindowExW")
	procDestroyWindow            = user32.NewProc("DestroyWindow")
	procDefWindowProcW           = user32.NewProc("DefWindowProcW")
	procGetMessageW              = user32.NewProc("GetMessageW")
	procTranslateMessage         = user32.NewProc("TranslateMessage")
	procDispatchMessageW         = user32.NewProc("DispatchMessageW")
	procPostMessageW             = user32.NewProc("PostMessageW")
	procPostQuitMessage          = user32.NewProc("PostQuitMessage")
	procRegisterWindowMessageW   = user32.NewProc("RegisterWindowMessageW")
	procCreatePopupMenu          = user32.NewProc("CreatePopupMenu")
	procAppendMenuW              = user32.NewProc("AppendMenuW")
	procDestroyMenu              = user32.NewProc("DestroyMenu")
	procTrackPopupMenu           = user32.NewProc("TrackPopupMenu")
	procSetForegroundWindow      = user32.NewProc("SetForegroundWindow")
	procSendMessageW             = user32.NewProc("SendMessageW")
	procGetCursorPos             = user32.NewProc("GetCursorPos")
	procSetMenuDefaultItem       = user32.NewProc("SetMenuDefaultItem")
	procMessageBoxW              = user32.NewProc("MessageBoxW")
	procCreateIconFromResourceEx = user32.NewProc("CreateIconFromResourceEx")
	procDestroyIcon              = user32.NewProc("DestroyIcon")
	procLoadIconW                = user32.NewProc("LoadIconW")
	procShellNotifyIconW         = shell32.NewProc("Shell_NotifyIconW")
	procShellExecuteW            = shell32.NewProc("ShellExecuteW")
	procGetModuleHandleW         = kernel32.NewProc("GetModuleHandleW")
	procTaskDialogIndirect       = comctl32.NewProc("TaskDialogIndirect")

	trayWindowProcCallback = syscall.NewCallback(trayWindowProc)
	taskDialogCallback     = syscall.NewCallback(taskDialogProc)
	activeTrayMu           sync.Mutex
	activeTray             *windowsTray
)

func startTray(config trayConfig) (*trayController, error) {
	ready := make(chan trayStartResult, 1)
	done := make(chan struct{})
	go func() {
		runtime.LockOSThread()
		defer runtime.UnlockOSThread()
		defer close(done)
		runTray(config, done, ready)
	}()
	created := <-ready
	return created.controller, created.err
}

func (controller *trayController) Close() {
	if controller == nil {
		return
	}
	controller.once.Do(func() {
		_, _, _ = procPostMessageW.Call(controller.hWnd, wmClose, 0, 0)
		select {
		case <-controller.done:
		case <-time.After(2 * time.Second):
		}
	})
}

func runTray(config trayConfig, done <-chan struct{}, ready chan<- trayStartResult) {
	instance, _, _ := procGetModuleHandleW.Call(0)
	className, _ := syscall.UTF16PtrFromString("BomanaBridgeNotificationWindow")
	class := windowClassEx{
		cbSize:    uint32(unsafe.Sizeof(windowClassEx{})),
		wndProc:   trayWindowProcCallback,
		instance:  instance,
		className: className,
	}
	registered, _, registerErr := procRegisterClassExW.Call(uintptr(unsafe.Pointer(&class)))
	if registered == 0 && registerErr != syscall.Errno(1410) {
		ready <- trayStartResult{err: fmt.Errorf("register tray window: %w", registerErr)}
		return
	}

	hWnd, _, createErr := procCreateWindowExW.Call(0, uintptr(unsafe.Pointer(className)), uintptr(unsafe.Pointer(className)), 0, 0, 0, 0, 0, 0, 0, instance, 0)
	if hWnd == 0 {
		ready <- trayStartResult{err: fmt.Errorf("create tray window: %w", createErr)}
		return
	}
	icon, owned := createBomanaIcon()
	taskbarName, _ := syscall.UTF16PtrFromString("TaskbarCreated")
	taskbarCreated, _, _ := procRegisterWindowMessageW.Call(uintptr(unsafe.Pointer(taskbarName)))
	tray := &windowsTray{config: config, hWnd: hWnd, icon: icon, iconOwned: owned, taskbarCreated: uint32(taskbarCreated)}
	tray.data = notifyIconData{
		cbSize:          uint32(unsafe.Sizeof(notifyIconData{})),
		hWnd:            hWnd,
		id:              1,
		flags:           nifMessage | nifIcon | nifTip | nifInfo,
		callbackMessage: trayMessage,
		icon:            icon,
		infoFlags:       niifInfo,
	}
	copyUTF16(tray.data.tip[:], fmt.Sprintf("Bomana Bridge v%s · 只读 8111", config.bridgeVersion))
	copyUTF16(tray.data.infoTitle[:], "Bomana Bridge 正在运行")
	copyUTF16(tray.data.info[:], "仅连接官方 localhost:8111。右键图标可打开 Web、查看关于与支持作者或退出。")

	activeTrayMu.Lock()
	activeTray = tray
	activeTrayMu.Unlock()
	if err := tray.addIcon(true); err != nil {
		activeTrayMu.Lock()
		activeTray = nil
		activeTrayMu.Unlock()
		_, _, _ = procDestroyWindow.Call(hWnd)
		if owned {
			_, _, _ = procDestroyIcon.Call(icon)
		}
		ready <- trayStartResult{err: err}
		return
	}
	ready <- trayStartResult{controller: &trayController{hWnd: hWnd, done: done}}

	var msg message
	for {
		status, _, messageErr := procGetMessageW.Call(uintptr(unsafe.Pointer(&msg)), 0, 0, 0)
		if int32(status) == -1 {
			slog.Warn("notification area message loop failed", "error", messageErr)
			break
		}
		if status == 0 {
			break
		}
		_, _, _ = procTranslateMessage.Call(uintptr(unsafe.Pointer(&msg)))
		_, _, _ = procDispatchMessageW.Call(uintptr(unsafe.Pointer(&msg)))
	}

	_, _, _ = procShellNotifyIconW.Call(nimDelete, uintptr(unsafe.Pointer(&tray.data)))
	if tray.iconOwned {
		_, _, _ = procDestroyIcon.Call(tray.icon)
	}
	activeTrayMu.Lock()
	if activeTray == tray {
		activeTray = nil
	}
	activeTrayMu.Unlock()
}

func (tray *windowsTray) addIcon(showStartup bool) error {
	data := tray.data
	if !showStartup {
		data.flags &^= nifInfo
	}
	added, _, addErr := procShellNotifyIconW.Call(nimAdd, uintptr(unsafe.Pointer(&data)))
	if added == 0 {
		return fmt.Errorf("add notification area icon: %w", addErr)
	}
	data.flags &^= nifInfo
	data.timeoutOrVersion = notifyVersion
	_, _, _ = procShellNotifyIconW.Call(nimSetVersion, uintptr(unsafe.Pointer(&data)))
	return nil
}

func trayWindowProc(hWnd uintptr, msg uint32, wParam, lParam uintptr) uintptr {
	activeTrayMu.Lock()
	tray := activeTray
	activeTrayMu.Unlock()
	if tray != nil && msg == tray.taskbarCreated {
		if err := tray.addIcon(false); err != nil {
			slog.Warn("failed to restore notification area icon", "error", err)
		}
		return 0
	}
	if msg == trayMessage && tray != nil {
		switch uint32(lParam & 0xffff) {
		case wmContextMenu, wmRButtonUp:
			tray.showMenu()
		case wmLButtonDblClk:
			tray.openURL(tray.config.webURL)
		}
		return 0
	}
	switch msg {
	case wmClose:
		_, _, _ = procDestroyWindow.Call(hWnd)
		return 0
	case wmDestroy:
		_, _, _ = procPostQuitMessage.Call(0)
		return 0
	}
	result, _, _ := procDefWindowProcW.Call(hWnd, uintptr(msg), wParam, lParam)
	return result
}

func (tray *windowsTray) showMenu() {
	menu, _, _ := procCreatePopupMenu.Call()
	if menu == 0 {
		return
	}
	defer func() { _, _, _ = procDestroyMenu.Call(menu) }()
	appendMenu(menu, mfString|mfDisabled|mfGrayed, 0, fmt.Sprintf("Bomana Bridge v%s · 只读 8111", tray.config.bridgeVersion))
	appendMenu(menu, mfSeparator, 0, "")
	appendMenu(menu, mfString, menuOpenWeb, "打开 Web 控制台")
	appendMenu(menu, mfString, menuMobilePairing, "连接手机…")
	appendMenu(menu, mfString, menuOpenLauncher, "打开 Launcher")
	appendMenu(menu, mfSeparator, 0, "")
	appendMenu(menu, mfString, menuStarProject, "给作者点个 Star")
	appendMenu(menu, mfString, menuSponsor, "支持作者（微信赞赏）…")
	appendMenu(menu, mfString, menuAbout, "关于 Bomana…")
	appendMenu(menu, mfSeparator, 0, "")
	appendMenu(menu, mfString, menuExit, "退出 Bridge")
	_, _, _ = procSetMenuDefaultItem.Call(menu, menuOpenWeb, 0)
	var cursor point
	if ok, _, _ := procGetCursorPos.Call(uintptr(unsafe.Pointer(&cursor))); ok == 0 {
		return
	}
	_, _, _ = procSetForegroundWindow.Call(tray.hWnd)
	command, _, _ := procTrackPopupMenu.Call(menu, tpmRightButton|tpmBottomAlign|tpmReturnCmd, uintptr(cursor.x), uintptr(cursor.y), 0, tray.hWnd, 0)
	_, _, _ = procPostMessageW.Call(tray.hWnd, wmNull, 0, 0)
	switch command {
	case menuOpenWeb:
		performTrayAction(tray.config, trayActionOpenWeb, tray.openURL, tray.showAbout)
	case menuMobilePairing:
		performTrayAction(tray.config, trayActionMobilePairing, tray.openURL, tray.showAbout)
	case menuOpenLauncher:
		performTrayAction(tray.config, trayActionOpenLauncher, tray.openURL, tray.showAbout)
	case menuStarProject:
		performTrayAction(tray.config, trayActionStarProject, tray.openURL, tray.showAbout)
	case menuSponsor:
		performTrayAction(tray.config, trayActionSponsor, tray.openURL, tray.showAbout)
	case menuAbout:
		performTrayAction(tray.config, trayActionAbout, tray.openURL, tray.showAbout)
	case menuExit:
		performTrayAction(tray.config, trayActionExit, tray.openURL, tray.showAbout)
	}
}

func (tray *windowsTray) showAbout(details trayAboutDetails) {
	result := showModernAbout(details, tray.hWnd, taskDialogCallback)
	if int32(result) >= 0 {
		return
	}
	slog.Warn("modern About dialog unavailable; using fallback", "hresult", fmt.Sprintf("0x%08X", uint32(result)))
	message, _ := syscall.UTF16PtrFromString(formatTrayAboutPlain(details))
	title, _ := syscall.UTF16PtrFromString(details.windowTitle)
	_, _, _ = procMessageBoxW.Call(
		tray.hWnd,
		uintptr(unsafe.Pointer(message)),
		uintptr(unsafe.Pointer(title)),
		mbOK|mbIconInformation,
	)
}

func showModernAbout(details trayAboutDetails, owner, callback uintptr) uintptr {
	windowTitle, _ := syscall.UTF16PtrFromString(details.windowTitle)
	mainInstruction, _ := syscall.UTF16PtrFromString(details.mainInstruction)
	content, _ := syscall.UTF16PtrFromString(details.contentHTML)
	expanded, _ := syscall.UTF16PtrFromString(details.expandedHTML)
	expandedControl, _ := syscall.UTF16PtrFromString(details.expandedControlText)
	collapsedControl, _ := syscall.UTF16PtrFromString(details.collapsedControlText)
	footer, _ := syscall.UTF16PtrFromString(details.footerHTML)
	var config taskDialogConfig
	config.setUint32(0, taskDialogConfigSize)
	config.setPointer(4, owner)
	config.setUint32(20, tdfEnableHyperlinks|tdfAllowDialogCancel|tdfExpandedByDefault|tdfSizeToContent)
	config.setUint32(24, tdcbfCloseButton)
	config.setPointer(28, uintptr(unsafe.Pointer(windowTitle)))
	config.setPointer(36, tdInformationIcon)
	config.setPointer(44, uintptr(unsafe.Pointer(mainInstruction)))
	config.setPointer(52, uintptr(unsafe.Pointer(content)))
	config.setPointer(100, uintptr(unsafe.Pointer(expanded)))
	config.setPointer(108, uintptr(unsafe.Pointer(expandedControl)))
	config.setPointer(116, uintptr(unsafe.Pointer(collapsedControl)))
	config.setPointer(132, uintptr(unsafe.Pointer(footer)))
	config.setPointer(140, callback)
	result, _, _ := procTaskDialogIndirect.Call(uintptr(unsafe.Pointer(&config[0])), 0, 0, 0)
	runtime.KeepAlive(windowTitle)
	runtime.KeepAlive(mainInstruction)
	runtime.KeepAlive(content)
	runtime.KeepAlive(expanded)
	runtime.KeepAlive(expandedControl)
	runtime.KeepAlive(collapsedControl)
	runtime.KeepAlive(footer)
	runtime.KeepAlive(config)
	return result
}

func taskDialogProc(_ uintptr, notification uint32, _ uintptr, lParam *uint16, _ uintptr) uintptr {
	if notification != tdnHyperlinkClicked || lParam == nil {
		return 0
	}
	raw := utf16PointerString(lParam, 2048)
	if !isAllowedTrayHyperlink(raw) {
		slog.Warn("blocked unexpected About hyperlink", "destination", raw)
		return 0
	}
	activeTrayMu.Lock()
	tray := activeTray
	activeTrayMu.Unlock()
	if tray != nil {
		tray.openURL(raw)
	}
	return 0
}

func utf16PointerString(pointer *uint16, limit int) string {
	if pointer == nil || limit <= 0 {
		return ""
	}
	values := unsafe.Slice(pointer, limit)
	end := 0
	for end < len(values) && values[end] != 0 {
		end++
	}
	return syscall.UTF16ToString(values[:end])
}

func (tray *windowsTray) openURL(raw string) {
	verb, _ := syscall.UTF16PtrFromString("open")
	target, _ := syscall.UTF16PtrFromString(raw)
	result, _, _ := procShellExecuteW.Call(tray.hWnd, uintptr(unsafe.Pointer(verb)), uintptr(unsafe.Pointer(target)), 0, 0, swShowNormal)
	if result <= 32 {
		slog.Warn("failed to open fixed tray destination", "destination", raw, "code", result)
	}
}

func appendMenu(menu uintptr, flags uint32, command uintptr, label string) {
	var labelPointer uintptr
	if label != "" {
		value, _ := syscall.UTF16PtrFromString(label)
		labelPointer = uintptr(unsafe.Pointer(value))
	}
	_, _, _ = procAppendMenuW.Call(menu, uintptr(flags), command, labelPointer)
}

func copyUTF16(destination []uint16, value string) {
	encoded, _ := syscall.UTF16FromString(value)
	if len(encoded) > len(destination) {
		encoded = encoded[:len(destination)]
		encoded[len(encoded)-1] = 0
	}
	copy(destination, encoded)
}

func createBomanaIcon() (uintptr, bool) {
	payload, err := base64.StdEncoding.DecodeString(classicBomanaIconBase64)
	if err != nil || len(payload) == 0 {
		fallback, _, _ := procLoadIconW.Call(0, idiApplication)
		return fallback, false
	}
	icon, _, _ := procCreateIconFromResourceEx.Call(uintptr(unsafe.Pointer(&payload[0])), uintptr(len(payload)), 1, 0x00030000, 32, 32, 0)
	if icon != 0 {
		return icon, true
	}
	fallback, _, _ := procLoadIconW.Call(0, idiApplication)
	return fallback, false
}
