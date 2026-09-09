package main

import (
	"syscall"
	"unsafe"
)

// All handles and callbacks belong to the UI thread. No browser or graphics
// runtime is shipped: user32 composites a premultiplied, per-pixel-alpha DIB.
var (
	user32              = syscall.NewLazyDLL("user32.dll")
	gdi32               = syscall.NewLazyDLL("gdi32.dll")
	shell32             = syscall.NewLazyDLL("shell32.dll")
	kernel32            = syscall.NewLazyDLL("kernel32.dll")
	registerClass       = user32.NewProc("RegisterClassExW")
	createWindow        = user32.NewProc("CreateWindowExW")
	defWindowProc       = user32.NewProc("DefWindowProcW")
	destroyWindow       = user32.NewProc("DestroyWindow")
	showWindow          = user32.NewProc("ShowWindow")
	setWindowPos        = user32.NewProc("SetWindowPos")
	getWindowRect       = user32.NewProc("GetWindowRect")
	getMessage          = user32.NewProc("GetMessageW")
	translateMessage    = user32.NewProc("TranslateMessage")
	dispatchMessage     = user32.NewProc("DispatchMessageW")
	postMessage         = user32.NewProc("PostMessageW")
	sendMessage         = user32.NewProc("SendMessageW")
	postQuitMessage     = user32.NewProc("PostQuitMessage")
	setTimer            = user32.NewProc("SetTimer")
	killTimer           = user32.NewProc("KillTimer")
	getCursorPos        = user32.NewProc("GetCursorPos")
	setForegroundWindow = user32.NewProc("SetForegroundWindow")
	getWindowLong       = user32.NewProc("GetWindowLongPtrW")
	setWindowLong       = user32.NewProc("SetWindowLongPtrW")
	getWindowText       = user32.NewProc("GetWindowTextW")
	setWindowText       = user32.NewProc("SetWindowTextW")
	loadCursor          = user32.NewProc("LoadCursorW")
	loadIcon            = user32.NewProc("LoadIconW")
	createPopupMenu     = user32.NewProc("CreatePopupMenu")
	appendMenu          = user32.NewProc("AppendMenuW")
	trackPopupMenu      = user32.NewProc("TrackPopupMenu")
	destroyMenu         = user32.NewProc("DestroyMenu")
	registerHotKey      = user32.NewProc("RegisterHotKey")
	unregisterHotKey    = user32.NewProc("UnregisterHotKey")
	updateLayeredWindow = user32.NewProc("UpdateLayeredWindow")
	getDC               = user32.NewProc("GetDC")
	releaseDC           = user32.NewProc("ReleaseDC")
	messageBox          = user32.NewProc("MessageBoxW")
	findWindow          = user32.NewProc("FindWindowW")
	getSysColorBrush    = user32.NewProc("GetSysColorBrush")
	createCompatibleDC  = gdi32.NewProc("CreateCompatibleDC")
	createDIBSection    = gdi32.NewProc("CreateDIBSection")
	selectObject        = gdi32.NewProc("SelectObject")
	deleteObject        = gdi32.NewProc("DeleteObject")
	deleteDC            = gdi32.NewProc("DeleteDC")
	createFont          = gdi32.NewProc("CreateFontW")
	setBkMode           = gdi32.NewProc("SetBkMode")
	setTextColor        = gdi32.NewProc("SetTextColor")
	drawText            = user32.NewProc("DrawTextW")
	gdiFlush            = gdi32.NewProc("GdiFlush")
	notifyIcon          = shell32.NewProc("Shell_NotifyIconW")
	getModuleHandle     = kernel32.NewProc("GetModuleHandleW")
	moveFileEx          = kernel32.NewProc("MoveFileExW")
)

const (
	wmDestroy       = 2
	wmClose         = 0x10
	wmCommand       = 0x111
	wmTimer         = 0x113
	wmHScroll       = 0x114
	wmLButtonDown   = 0x201
	wmLButtonUp     = 0x202
	wmRButtonUp     = 0x205
	wmContextMenu   = 0x7b
	wmHotKey        = 0x312
	wmSettings      = 0x8001
	wmTray          = 0x8002
	wmDPIChanged    = 0x2e0
	wsPopup         = 0x80000000
	wsChild         = 0x40000000
	wsVisible       = 0x10000000
	wsExLayered     = 0x80000
	wsExTransparent = 0x20
	wsExToolWindow  = 0x80
	wsExTopmost     = 0x8
	wsExNoActivate  = 0x8000000
	wmSetFont       = 0x30
)

type winPoint struct{ X, Y int32 }
type winSize struct{ CX, CY int32 }
type winRect struct{ Left, Top, Right, Bottom int32 }
type winMsg struct {
	HWND           uintptr
	Message        uint32
	WParam, LParam uintptr
	Time           uint32
	Point          winPoint
	Private        uint32
}
type windowClass struct {
	Size, Style                        uint32
	Proc                               uintptr
	ClassExtra, WindowExtra            int32
	Instance, Icon, Cursor, Background uintptr
	Menu, Name                         *uint16
	SmallIcon                          uintptr
}
type bitmapInfo struct {
	Size                   uint32
	Width, Height          int32
	Planes, BitCount       uint16
	Compression, SizeImage uint32
	XPels, YPels           int32
	Used, Important        uint32
}
type iconData struct {
	Size                uint32
	HWND                uintptr
	ID, Flags, Callback uint32
	Icon                uintptr
	Tip                 [128]uint16
	State, StateMask    uint32
	Info                [256]uint16
	Version             uint32
	InfoTitle           [64]uint16
	InfoFlags           uint32
	GUID                [16]byte
	Balloon             uintptr
}

func wide(s string) *uint16  { p, _ := syscall.UTF16PtrFromString(s); return p }
func signed(n int32) uintptr { return uintptr(n) }
func setTitle(hwnd uintptr, text string) {
	setWindowText.Call(hwnd, uintptr(unsafe.Pointer(wide(text))))
}
func nativeError(owner uintptr, text string) {
	messageBox.Call(owner, uintptr(unsafe.Pointer(wide(text))), uintptr(unsafe.Pointer(wide("Bomana 精简版"))), 0x10)
}
