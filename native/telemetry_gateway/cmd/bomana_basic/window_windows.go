package main

import (
	"fmt"
	"math"
	"strconv"
	"syscall"
	"time"
	"unsafe"
)

type application struct {
	hwnd, settingsWindow  uintptr
	model                 *model
	renderer              *renderer
	frames                <-chan frame
	path, class, hotkey   string
	scale, displayHeading float64
	headingReady          bool
	lastPaint             int64
	clickThrough, trayOK  bool
	paintError            error
	controls              map[int]uintptr
	settingsFont          uintptr
	tray                  iconData
}

var windows = map[uintptr]*application{}
var overlayCallback = syscall.NewCallback(overlayProc)
var settingsCallback = syscall.NewCallback(settingsProc)
var taskbarCreated, _, _ = user32.NewProc("RegisterWindowMessageW").Call(uintptr(unsafe.Pointer(wide("TaskbarCreated"))))

func register(name string, callback uintptr, background uintptr) error {
	instance, _, _ := getModuleHandle.Call(0)
	cursor, _, _ := loadCursor.Call(0, 32512)
	icon, _, _ := loadIcon.Call(instance, 1) // First icon group in the generated EXE resource.
	wc := windowClass{Proc: callback, Instance: instance, Icon: icon, Cursor: cursor, Name: wide(name), Background: background}
	wc.Size = uint32(unsafe.Sizeof(wc))
	ok, _, err := registerClass.Call(uintptr(unsafe.Pointer(&wc)))
	if ok == 0 && err != syscall.Errno(1410) {
		return fmt.Errorf("注册窗口失败: %w", err)
	}
	return nil
}
func newApp(s settings, path string, frames <-chan frame, class string) (*application, error) {
	a := &application{model: newModel(s), path: path, frames: frames, class: class, scale: 1}
	if err := register(class, overlayCallback, 0); err != nil {
		return nil, err
	}
	bg, _, _ := getSysColorBrush.Call(15)
	if err := register(class+".Settings", settingsCallback, bg); err != nil {
		return nil, err
	}
	instance, _, _ := getModuleHandle.Call(0)
	a.hwnd, _, _ = createWindow.Call(wsExLayered|wsExTopmost|wsExToolWindow|wsExNoActivate, uintptr(unsafe.Pointer(wide(class))), uintptr(unsafe.Pointer(wide("Bomana 精简版"))), wsPopup, 100, 70, uintptr(s.Width), hudHeight, 0, 0, instance, 0)
	if a.hwnd == 0 {
		return nil, fmt.Errorf("无法创建导航窗口")
	}
	windows[a.hwnd] = a
	if proc := user32.NewProc("GetDpiForWindow"); proc.Find() == nil {
		dpi, _, _ := proc.Call(a.hwnd)
		if dpi > 0 {
			a.scale = float64(dpi) / 96
		}
	}
	var err error
	a.renderer, err = newRenderer(s.Width, a.scale)
	if err != nil {
		a.close()
		return nil, err
	}
	a.place(s.X, s.Y, s.Positioned)
	a.addTray()
	for _, binding := range []struct {
		mod   uintptr
		label string
	}{{3, "Ctrl + Alt + M"}, {7, "Ctrl + Alt + Shift + M"}} {
		if ok, _, _ := registerHotKey.Call(a.hwnd, 1, binding.mod|0x4000, 'M'); ok != 0 {
			a.hotkey = binding.label
			break
		}
	}
	// Relaunching the EXE opens these settings even when Explorer is restarting
	// and both shortcut combinations are owned by other applications.
	if ok, _, _ := setTimer.Call(a.hwnd, 1, 33, 0); ok == 0 {
		a.close()
		return nil, fmt.Errorf("无法启动显示计时器")
	}
	a.paint()
	if a.paintError != nil {
		err = a.paintError
		a.close()
		return nil, err
	}
	return a, nil
}
func (a *application) addTray() {
	instance, _, _ := getModuleHandle.Call(0)
	icon, _, _ := loadIcon.Call(instance, 1)
	a.tray = iconData{HWND: a.hwnd, ID: 1, Flags: 1 | 2 | 4, Callback: wmTray, Icon: icon}
	a.tray.Size = uint32(unsafe.Sizeof(a.tray))
	copy(a.tray.Tip[:], syscall.StringToUTF16("Bomana 精简版 · 左键设置 / 右键菜单"))
	ok, _, _ := notifyIcon.Call(0, uintptr(unsafe.Pointer(&a.tray)))
	a.trayOK = ok != 0
}
func (a *application) place(x, y int, positioned bool) {
	var work winRect
	user32.NewProc("SystemParametersInfoW").Call(0x30, 0, uintptr(unsafe.Pointer(&work)), 0)
	if positioned {
		// MonitorFromPoint packs the two signed LONG coordinates into one value.
		packed := uintptr(uint64(uint32(x)) | uint64(uint32(y))<<32)
		monitor, _, _ := user32.NewProc("MonitorFromPoint").Call(packed, 2)
		info := struct {
			Size          uint32
			Monitor, Work winRect
			Flags         uint32
		}{Size: 40}
		if ok, _, _ := user32.NewProc("GetMonitorInfoW").Call(monitor, uintptr(unsafe.Pointer(&info))); ok != 0 {
			work = info.Work
		}
	} else {
		x = int(work.Left) + (int(work.Right-work.Left)-a.renderer.output.width)/2
		y = int(work.Top) + 36
	}
	x = max(int(work.Left), min(int(work.Right)-a.renderer.output.width, x))
	y = max(int(work.Top), min(int(work.Bottom)-a.renderer.output.height, y))
	setWindowPos.Call(a.hwnd, ^uintptr(0), signed(int32(x)), signed(int32(y)), uintptr(a.renderer.output.width), uintptr(a.renderer.output.height), 0x10)
}
func (a *application) loop() {
	var msg winMsg
	for {
		ok, _, _ := getMessage.Call(uintptr(unsafe.Pointer(&msg)), 0, 0, 0)
		if int32(ok) <= 0 {
			break
		}
		if a.settingsWindow != 0 {
			if handled, _, _ := user32.NewProc("IsDialogMessageW").Call(a.settingsWindow, uintptr(unsafe.Pointer(&msg))); handled != 0 {
				continue
			}
		}
		translateMessage.Call(uintptr(unsafe.Pointer(&msg)))
		dispatchMessage.Call(uintptr(unsafe.Pointer(&msg)))
	}
}
func (a *application) persist() {
	var rect winRect
	getWindowRect.Call(a.hwnd, uintptr(unsafe.Pointer(&rect)))
	a.model.Settings.X, a.model.Settings.Y, a.model.Settings.Positioned = int(rect.Left), int(rect.Top), true
	if err := saveSettings(a.path, a.model.Settings); err != nil {
		nativeError(a.settingsWindow, "设置未能保存："+err.Error())
	}
}
func (a *application) close() {
	if a.hwnd != 0 {
		destroyWindow.Call(a.hwnd)
	}
}
func (a *application) paint() {
	if a.renderer == nil {
		return
	}
	for {
		select {
		case f, ok := <-a.frames:
			if !ok {
				a.frames = nil
				break
			}
			a.model.ingest(f)
		default:
			goto drained
		}
	}
drained:
	now := time.Now().UnixMilli()
	v := a.model.snapshot(now)
	if v.HasHeading {
		if !a.headingReady || now-a.lastPaint > 1000 {
			a.displayHeading = v.Heading
		} else {
			a.displayHeading = heading(a.displayHeading + angle(v.Heading-a.displayHeading)*(1-math.Exp(-float64(now-a.lastPaint)/85)))
		}
		v.Heading = a.displayHeading
	}
	a.headingReady, a.lastPaint = v.HasHeading, now
	a.renderer.render(v, a.model.Settings)
	a.paintError = a.renderer.present(a.hwnd)
}
func (a *application) setClickThrough(enabled bool) {
	a.clickThrough = enabled
	index := signed(-20)
	style, _, _ := getWindowLong.Call(a.hwnd, index)
	if enabled {
		style |= wsExTransparent
	} else {
		style &^= wsExTransparent
	}
	setWindowLong.Call(a.hwnd, index, style)
}
func overlayProc(hwnd uintptr, msg uint32, w, l uintptr) uintptr {
	a := windows[hwnd]
	if a != nil {
		if msg == uint32(taskbarCreated) {
			a.addTray()
			return 0
		}
		switch msg {
		case wmTimer:
			a.paint()
			return 0
		case wmSettings, wmHotKey:
			a.openSettings()
			return 0
		case wmLButtonDown:
			sendMessage.Call(hwnd, 0xa1, 2, 0)
			return 0
		case 0x232:
			a.persist()
			return 0 // exit move/size
		case wmRButtonUp, wmContextMenu:
			a.menu()
			return 0
		case wmTray:
			if uint32(l) == wmLButtonUp {
				a.openSettings()
			}
			if uint32(l) == wmRButtonUp {
				a.menu()
			}
			return 0
		case wmDPIChanged:
			scale := float64(w&0xffff) / 96
			if scale > 0 {
				replacement, err := newRenderer(a.model.Settings.Width, scale)
				if err == nil {
					a.renderer.close()
					a.renderer = replacement
					a.scale = scale
					var rect winRect
					getWindowRect.Call(hwnd, uintptr(unsafe.Pointer(&rect)))
					a.place(int(rect.Left), int(rect.Top), true)
					a.paint()
				}
			}
			return 0
		case wmClose:
			a.persist()
			a.close()
			return 0
		case wmDestroy:
			if a.settingsWindow != 0 {
				destroyWindow.Call(a.settingsWindow)
			}
			killTimer.Call(hwnd, 1)
			unregisterHotKey.Call(hwnd, 1)
			notifyIcon.Call(2, uintptr(unsafe.Pointer(&a.tray)))
			if a.renderer != nil {
				a.renderer.close()
				a.renderer = nil
			}
			delete(windows, hwnd)
			a.hwnd = 0
			postQuitMessage.Call(0)
			return 0
		}
	}
	r, _, _ := defWindowProc.Call(hwnd, uintptr(msg), w, l)
	return r
}
func (a *application) menu() {
	menu, _, _ := createPopupMenu.Call()
	defer destroyMenu.Call(menu)
	item := func(id uintptr, label string, checked bool) {
		flags := uintptr(0)
		if checked {
			flags = 8
		}
		appendMenu.Call(menu, flags, id, uintptr(unsafe.Pointer(wide(label))))
	}
	item(1, "设置 / 恢复窗口…", false)
	item(2, "重新计时", false)
	item(3, "鼠标穿透", a.clickThrough)
	item(4, "显示边框", a.model.Settings.Border)
	appendMenu.Call(menu, 0x800, 0, 0)
	item(5, "自动选择前方目标", a.model.selectedID == "")
	v := a.model.snapshot(time.Now().UnixMilli())
	targets := v.Targets
	for i, t := range targets {
		item(uintptr(100+i), fmt.Sprintf("%s · %.1f km", t.Label, t.Distance), a.model.selectedID == t.ID)
	}
	appendMenu.Call(menu, 0x800, 0, 0)
	item(6, "退出", false)
	var p winPoint
	getCursorPos.Call(uintptr(unsafe.Pointer(&p)))
	setForegroundWindow.Call(a.hwnd)
	id, _, _ := trackPopupMenu.Call(menu, 0x100|2, signed(p.X), signed(p.Y), 0, a.hwnd, 0)
	postMessage.Call(a.hwnd, 0, 0, 0)
	switch id {
	case 1:
		a.openSettings()
	case 2:
		a.model.reset(time.Now().UnixMilli())
	case 3:
		a.setClickThrough(!a.clickThrough)
	case 4:
		a.model.Settings.Border = !a.model.Settings.Border
		a.persist()
	case 5:
		a.model.selectedID = ""
	case 6:
		a.persist()
		a.close()
	default:
		if id >= 100 && int(id-100) < len(targets) {
			a.model.selectedID = targets[id-100].ID
		}
	}
	if a.hwnd != 0 {
		a.paint()
	}
}
func (a *application) openSettings() {
	if a.settingsWindow != 0 {
		showWindow.Call(a.settingsWindow, 5)
		setForegroundWindow.Call(a.settingsWindow)
		return
	}
	a.controls = map[int]uintptr{}
	instance, _, _ := getModuleHandle.Call(0)
	var rect winRect
	getWindowRect.Call(a.hwnd, uintptr(unsafe.Pointer(&rect)))
	scale := a.scale
	px := func(n int) uintptr { return uintptr(math.Round(float64(n) * scale)) }
	hwnd, _, _ := createWindow.Call(wsExTopmost|wsExToolWindow, uintptr(unsafe.Pointer(wide(a.class+".Settings"))), uintptr(unsafe.Pointer(wide("Bomana 精简版 · 设置"))), 0x00c80000, signed(rect.Left), signed(rect.Top), px(440), px(454), a.hwnd, 0, instance, 0)
	if hwnd == 0 {
		nativeError(a.hwnd, "无法打开设置")
		return
	}
	a.settingsWindow = hwnd
	windows[hwnd] = a
	a.settingsFont, _, _ = createFont.Call(signed(-int32(px(14))), 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 4, 0, uintptr(unsafe.Pointer(wide("Segoe UI"))))
	cc := struct{ Size, Classes uint32 }{8, 4}
	syscall.NewLazyDLL("comctl32.dll").NewProc("InitCommonControlsEx").Call(uintptr(unsafe.Pointer(&cc)))
	control := func(kind, label string, id, x, y, width, height int, style uintptr) uintptr {
		h, _, _ := createWindow.Call(0, uintptr(unsafe.Pointer(wide(kind))), uintptr(unsafe.Pointer(wide(label))), wsChild|wsVisible|style, px(x), px(y), px(width), px(height), hwnd, uintptr(id), instance, 0)
		a.controls[id] = h
		sendMessage.Call(h, wmSetFont, a.settingsFont, 1)
		return h
	}
	s := a.model.Settings
	for i, row := range []struct {
		label string
		value int
	}{{"背景", s.Background}, {"文字", s.Text}, {"航向带图标", s.Icons}} {
		y := 18 + i*55
		control("STATIC", row.label, 20+i, 18, y, 104, 22, 0)
		control("STATIC", fmt.Sprintf("%d%%", row.value), 30+i, 363, y, 54, 22, 0)
		h := control("msctls_trackbar32", "", 10+i, 124, y-2, 232, 32, 0x10000|0x10)
		sendMessage.Call(h, 0x406, 1, 100<<16)
		sendMessage.Call(h, 0x405, 1, uintptr(row.value))
	}
	control("STATIC", "计时周期（分钟）", 23, 18, 190, 140, 24, 0)
	control("EDIT", strconv.Itoa(s.Minutes), 13, 166, 187, 66, 28, 0x10000|0x800000|0x2000)
	control("STATIC", "1 – 180", 24, 244, 190, 112, 24, 0)
	control("STATIC", "窗口宽度", 25, 18, 230, 100, 24, 0)
	h := control("msctls_trackbar32", "", 14, 124, 225, 232, 32, 0x10000|0x10)
	sendMessage.Call(h, 0x406, 1, 360|(1200<<16))
	sendMessage.Call(h, 0x405, 1, uintptr(s.Width))
	control("BUTTON", "显示边框", 15, 18, 267, 148, 25, 3|0x10000)
	sendMessage.Call(a.controls[15], 0xf1, boolValue(s.Border), 0)
	control("BUTTON", "鼠标穿透", 16, 190, 267, 148, 25, 3|0x10000)
	sendMessage.Call(a.controls[16], 0xf1, boolValue(a.clickThrough), 0)
	note := "右键导航窗选择目标；拖动窗口移动。\n托盘左键或再次运行 EXE 可打开此设置。"
	if a.hotkey != "" {
		note += "\n恢复快捷键：" + a.hotkey
	}
	control("STATIC", note, 26, 18, 305, 394, 58, 0)
	control("BUTTON", "恢复默认外观", 17, 18, 367, 140, 30, 0x10000)
	control("BUTTON", "完成", 18, 312, 367, 102, 30, 1|0x10000)
	showWindow.Call(hwnd, 5)
	setForegroundWindow.Call(hwnd)
}
func boolValue(v bool) uintptr {
	if v {
		return 1
	}
	return 0
}
func (a *application) applySettings() bool {
	var input [16]uint16
	getWindowText.Call(a.controls[13], uintptr(unsafe.Pointer(&input[0])), 16)
	minutes, err := strconv.Atoi(syscall.UTF16ToString(input[:]))
	if err != nil || minutes < 1 || minutes > 180 {
		nativeError(a.settingsWindow, "计时周期请输入 1 到 180 的整数。")
		return false
	}
	a.model.Settings.Minutes = minutes
	a.persist()
	return true
}
func settingsProc(hwnd uintptr, msg uint32, w, l uintptr) uintptr {
	a := windows[hwnd]
	if a != nil {
		switch msg {
		case wmHScroll:
			for i, value := range []*int{&a.model.Settings.Background, &a.model.Settings.Text, &a.model.Settings.Icons} {
				if l == a.controls[10+i] {
					v, _, _ := sendMessage.Call(l, 0x400, 0, 0)
					*value = int(v)
					setTitle(a.controls[30+i], fmt.Sprintf("%d%%", v))
				}
			}
			if l == a.controls[14] {
				width, _, _ := sendMessage.Call(l, 0x400, 0, 0)
				replacement, err := newRenderer(int(width), a.scale)
				if err == nil {
					a.renderer.close()
					a.renderer = replacement
					a.model.Settings.Width = int(width)
					var r winRect
					getWindowRect.Call(a.hwnd, uintptr(unsafe.Pointer(&r)))
					a.place(int(r.Left), int(r.Top), true)
				}
			}
			a.paint()
			return 0
		case wmCommand:
			switch int(w & 0xffff) {
			case 15:
				v, _, _ := sendMessage.Call(a.controls[15], 0xf0, 0, 0)
				a.model.Settings.Border = v == 1
				a.paint()
			case 16:
				v, _, _ := sendMessage.Call(a.controls[16], 0xf0, 0, 0)
				a.setClickThrough(v == 1)
			case 17:
				s := defaults()
				a.model.Settings.Background, a.model.Settings.Text, a.model.Settings.Icons, a.model.Settings.Border = s.Background, s.Text, s.Icons, s.Border
				a.setClickThrough(false)
				a.place(0, 0, false)
				destroyWindow.Call(hwnd)
				a.openSettings()
				a.paint()
				a.persist()
			case 18:
				if a.applySettings() {
					destroyWindow.Call(hwnd)
				}
			}
			return 0
		case wmClose:
			if a.applySettings() {
				destroyWindow.Call(hwnd)
			}
			return 0
		case wmDestroy:
			delete(windows, hwnd)
			a.settingsWindow = 0
			if a.settingsFont != 0 {
				deleteObject.Call(a.settingsFont)
				a.settingsFont = 0
			}
			return 0
		}
	}
	r, _, _ := defWindowProc.Call(hwnd, uintptr(msg), w, l)
	return r
}
