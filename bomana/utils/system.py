"""System/Windows helpers."""

import contextlib
import ctypes
import locale
import os
import sys
import threading
import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import font as tkfont
from tkinter import messagebox
from typing import Any

from bomana.config import FileConfig, HotkeyConfig

_WIN32_ACCESS_ERRORS = (OSError, AttributeError)
_MUTEX_HANDLE = None
_PREFERRED_LATIN_FONTS = [
    "Bomana UI Sans",
    "Segoe UI Variable",
    "Segoe UI",
    "Arial",
    "Helvetica",
]
_PREFERRED_CJK_FONTS = [
    "Bomana UI Sans",
    "Microsoft YaHei UI",
    "Microsoft YaHei",
    "Noto Sans CJK SC",
    "PingFang SC",
    "Source Han Sans SC",
    "WenQuanYi Micro Hei",
]
_PREFERRED_MONOSPACE_FONTS = [
    "Cascadia Mono",
    "Consolas",
    "Courier New",
    "Menlo",
    "Monaco",
    "DejaVu Sans Mono",
    "Liberation Mono",
    "Courier",
]
_UI_FONT_REQUESTS = {
    "",
    "TkDefaultFont",
    "Bomana UI Sans",
    "Segoe UI Variable",
    "Segoe UI",
    "Arial",
    "Helvetica",
    "Microsoft YaHei UI",
    "Microsoft YaHei",
    "Noto Sans CJK SC",
    "PingFang SC",
    "Source Han Sans SC",
    "WenQuanYi Micro Hei",
}
_MONOSPACE_FONT_REQUESTS = {
    "TkFixedFont",
    "monospace",
    *_PREFERRED_MONOSPACE_FONTS,
}
_BUNDLED_FONT_FAMILY = "Bomana UI Sans"
_BUNDLED_FONT_FILES = (
    "BomanaUiSans-Regular.ttf",
    "BomanaUiSans-Bold.ttf",
)
_BUNDLED_FONTS_LOADED = False


def _win32_dll(name: str) -> Any | None:
    windll = getattr(ctypes, "windll", None)
    if windll is None:
        return None
    return getattr(windll, name, None)


def _candidate_resource_roots() -> list[Path]:
    roots: list[Path] = []
    runtime_root = os.environ.get("BOMANA_RUNTIME_ROOT", "").strip()
    if runtime_root:
        roots.append(Path(runtime_root))
    roots.append(Path(__file__).resolve().parents[2])
    roots.append(Path.cwd())
    if hasattr(sys, "_MEIPASS"):
        roots.append(Path(str(sys._MEIPASS)))
    return roots


def _resolve_resource(rel_path: str) -> Path | None:
    seen: set[Path] = set()
    for root in _candidate_resource_roots():
        path = root / rel_path
        if path in seen:
            continue
        seen.add(path)
        if path.exists():
            return path
    return None


def load_bundled_ui_fonts() -> bool:
    """Privately load Bomana's bundled UI fonts when available."""
    global _BUNDLED_FONTS_LOADED
    if _BUNDLED_FONTS_LOADED:
        return True
    if os.name != "nt":
        return False

    gdi32 = _win32_dll("gdi32")
    if gdi32 is None:
        return False
    add_font = getattr(gdi32, "AddFontResourceExW", None)
    if add_font is None:
        return False

    loaded_any = False
    for filename in _BUNDLED_FONT_FILES:
        font_path = _resolve_resource(f"bomana/assets/fonts/{filename}")
        if font_path is None:
            continue
        try:
            # FR_PRIVATE keeps the bundled font scoped to this process.
            loaded_any = bool(add_font(str(font_path), 0x10, 0)) or loaded_any
        except OSError:
            continue

    _BUNDLED_FONTS_LOADED = loaded_any
    return loaded_any


def select_ui_font_family(root: tk.Misc) -> str:
    """Pick a readable UI font family shared by app and launcher."""
    load_bundled_ui_fonts()
    try:
        families = set(tkfont.families(root))
    except Exception:
        return ""

    if _BUNDLED_FONT_FAMILY in families:
        return _BUNDLED_FONT_FAMILY

    try:
        loc = locale.getlocale()[0] or ""
    except Exception:
        loc = ""

    if os.name == "nt":
        for fam in _PREFERRED_CJK_FONTS:
            if fam in families:
                return fam
        for fam in _PREFERRED_LATIN_FONTS:
            if fam in families:
                return fam
        return ""

    if loc.startswith(("zh", "ja", "ko")):
        for fam in _PREFERRED_CJK_FONTS:
            if fam in families:
                return fam
    for fam in _PREFERRED_LATIN_FONTS:
        if fam in families:
            return fam
    for fam in _PREFERRED_CJK_FONTS:
        if fam in families:
            return fam
    return ""


def select_monospace_font_family(root: tk.Misc) -> str:
    """Pick an available monospace font family for debug and numeric readouts."""
    try:
        families = set(tkfont.families(root))
    except Exception:
        return ""

    for fam in _PREFERRED_MONOSPACE_FONTS:
        if fam in families:
            return fam
    return ""


def resolve_tk_font_family(root: tk.Misc, requested_family: str | None) -> str:
    """Resolve legacy font requests to an available UI or monospace family."""
    requested = str(requested_family or "").strip()
    try:
        families = set(tkfont.families(root))
    except Exception:
        families = set()

    if requested in _MONOSPACE_FONT_REQUESTS:
        return select_monospace_font_family(root) or requested

    if requested in _UI_FONT_REQUESTS:
        return select_ui_font_family(root) or requested

    if requested and requested in families:
        return requested

    return requested or select_ui_font_family(root)


def resolve_tk_font_tuple(root: tk.Misc, font_def: tuple | list | str) -> tuple | str:
    """Resolve the family component of a Tk font tuple while preserving size/style."""
    if not isinstance(font_def, (tuple, list)) or len(font_def) < 2:
        return font_def
    family = resolve_tk_font_family(root, str(font_def[0]))
    if not family:
        return tuple(font_def)
    return (family, *tuple(font_def)[1:])


# ============================================================================
# Windows API封装
# ============================================================================


class Win32:
    """Windows API封装类

    提供DPI感知、窗口样式设置等Windows特有功能。
    使用ctypes调用user32.dll和kernel32.dll。
    """

    user32 = _win32_dll("user32")
    kernel32 = _win32_dll("kernel32")

    @classmethod
    def enable_dpi(cls):
        """启用DPI感知

        确保在高DPI显示器上正确渲染，按优先级尝试三种方法：
        1. SetProcessDpiAwarenessContext (Windows 10 1703+)
        2. SetProcessDpiAwareness (Windows 8.1+)
        3. SetProcessDPIAware (Windows Vista+)
        """
        try:
            # 方法1: Per-Monitor V2 DPI感知（最佳）
            cls.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        except _WIN32_ACCESS_ERRORS:
            try:
                # 方法2: Per-Monitor DPI感知
                ctypes.windll.shcore.SetProcessDpiAwareness(2)
            except _WIN32_ACCESS_ERRORS:
                with contextlib.suppress(OSError, AttributeError):
                    # 方法3: System DPI感知（后备）
                    cls.user32.SetProcessDPIAware()

    @classmethod
    def get_dpi_scale(cls, hwnd: int) -> float:
        """获取窗口的DPI缩放比例

        Args:
            hwnd: 窗口句柄

        Returns:
            DPI缩放倍数（1.0 = 96 DPI, 1.5 = 144 DPI等）
        """
        try:
            dpi = cls.user32.GetDpiForWindow(hwnd)
            return (dpi / 96.0) if dpi else 1.0
        except _WIN32_ACCESS_ERRORS:
            return 1.0

    @classmethod
    def screen_size(cls) -> tuple[int, int]:
        """获取主屏幕尺寸

        Returns:
            (宽度, 高度) 元组
        """
        try:
            return cls.user32.GetSystemMetrics(0), cls.user32.GetSystemMetrics(1)
        except _WIN32_ACCESS_ERRORS:
            return 1920, 1080

    @classmethod
    def setup_window(
        cls, hwnd: int, click_through: bool, alpha: int = 210, color_key: int | None = None
    ) -> bool:
        """设置窗口样式（透明、置顶、穿透）

        Args:
            hwnd: 窗口句柄
            click_through: 是否允许点击穿透
            alpha: 不透明度 (0-255)
            color_key: 颜色键透明（COLORREF, 0x00bbggrr）。传入后背景色匹配像素将被完全透明。

        v6.6.3: 添加 WS_EX_NOACTIVATE 标志，解决窗口被激活后点击穿透失效的问题
        """
        # 窗口扩展样式标志
        GWL_EXSTYLE = -20
        WS_EX_LAYERED = 0x00080000  # 分层窗口（支持透明度）
        WS_EX_TRANSPARENT = 0x00000020  # 点击穿透（使窗口在点击测试中透明）
        WS_EX_NOACTIVATE = 0x08000000  # 防止窗口被激活（关键：防止点击后窗口获得焦点）
        WS_EX_TOPMOST = 0x00000008  # 窗口置顶
        WS_EX_TOOLWINDOW = 0x00000080  # 工具窗口（不显示在任务栏）
        LWA_COLORKEY = 0x1  # 颜色键透明标志
        LWA_ALPHA = 0x2  # 透明度标志

        try:
            user32 = cls.user32
            kernel32 = cls.kernel32
            with contextlib.suppress(Exception):
                user32.GetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int]
                user32.GetWindowLongW.restype = ctypes.c_long
                user32.SetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_long]
                user32.SetWindowLongW.restype = ctypes.c_long
                user32.SetLayeredWindowAttributes.argtypes = [
                    ctypes.c_void_p,
                    ctypes.c_uint,
                    ctypes.c_ubyte,
                    ctypes.c_uint,
                ]
                user32.SetLayeredWindowAttributes.restype = ctypes.c_bool

            def _last_error() -> int:
                try:
                    return int(kernel32.GetLastError())
                except _WIN32_ACCESS_ERRORS:
                    return 0

            def _clear_last_error() -> None:
                with contextlib.suppress(_WIN32_ACCESS_ERRORS):
                    kernel32.SetLastError(0)

            # 获取当前样式
            _clear_last_error()
            style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            if style == 0 and _last_error() != 0:
                return False

            # 添加必要样式
            style |= WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_TOOLWINDOW

            # 根据锁定状态切换点击穿透
            # 关键：同时设置 WS_EX_TRANSPARENT 和 WS_EX_NOACTIVATE
            # - WS_EX_TRANSPARENT: 让点击穿透到下层窗口
            # - WS_EX_NOACTIVATE: 防止窗口被激活，确保持续穿透
            if click_through:
                style |= WS_EX_TRANSPARENT | WS_EX_NOACTIVATE
            else:
                style &= ~(WS_EX_TRANSPARENT | WS_EX_NOACTIVATE)

            # 应用样式和透明度/颜色键
            _clear_last_error()
            previous_style = user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
            if previous_style == 0 and _last_error() != 0:
                return False
            target_alpha = max(0, min(255, int(alpha)))
            flags = LWA_ALPHA
            key = 0
            if color_key is not None:
                flags |= LWA_COLORKEY
                key = int(color_key) & 0x00FFFFFF
            return bool(user32.SetLayeredWindowAttributes(hwnd, key, target_alpha, flags))
        except _WIN32_ACCESS_ERRORS:
            return False

    @classmethod
    def hide_console(cls):
        """隐藏控制台窗口

        用于.pyw脚本，确保没有黑窗口显示。
        """
        try:
            hwnd = cls.kernel32.GetConsoleWindow()
            if hwnd:
                cls.user32.ShowWindow(hwnd, 0)
        except _WIN32_ACCESS_ERRORS:
            pass

    @classmethod
    def get_all_monitors(cls) -> list[dict[str, Any]]:
        """获取所有显示器信息

        返回所有显示器的工作区域(排除任务栏),用于:
        - 记忆窗口所在显示器
        - 窗口边缘吸附
        - 边界检查

        Returns:
            显示器信息列表, 每项包含index/x/y/width/height/is_primary
        """
        monitors = []

        try:
            # 定义回调函数类型
            MONITORENUMPROC = ctypes.WINFUNCTYPE(
                ctypes.c_int,
                ctypes.c_void_p,  # hMonitor
                ctypes.c_void_p,  # hdcMonitor
                ctypes.POINTER(ctypes.c_long * 4),  # lprcMonitor (RECT)
                ctypes.c_void_p,  # dwData
            )

            # MONITORINFO 结构体
            class MONITORINFO(ctypes.Structure):
                _fields_ = [
                    ("cbSize", ctypes.c_uint),
                    ("rcMonitor", ctypes.c_long * 4),  # 显示器完整区域
                    ("rcWork", ctypes.c_long * 4),  # 工作区域（排除任务栏）
                    ("dwFlags", ctypes.c_uint),
                ]

            monitor_list = []

            def callback(hMonitor, hdcMonitor, lprcMonitor, dwData):
                info = MONITORINFO()
                info.cbSize = ctypes.sizeof(MONITORINFO)
                cls.user32.GetMonitorInfoW(hMonitor, ctypes.byref(info))

                # 使用工作区域（排除任务栏）
                work = info.rcWork
                monitor_list.append(
                    {
                        "index": len(monitor_list),
                        "x": work[0],
                        "y": work[1],
                        "width": work[2] - work[0],
                        "height": work[3] - work[1],
                        "is_primary": bool(info.dwFlags & 1),
                    }
                )
                return 1  # 继续枚举

            # 枚举所有显示器
            enum_proc = MONITORENUMPROC(callback)
            cls.user32.EnumDisplayMonitors(None, None, enum_proc, 0)

            monitors = monitor_list
        except Exception:
            # 失败时返回主屏幕
            w, h = cls.screen_size()
            monitors = [{"index": 0, "x": 0, "y": 0, "width": w, "height": h, "is_primary": True}]

        return (
            monitors
            if monitors
            else [{"index": 0, "x": 0, "y": 0, "width": 1920, "height": 1080, "is_primary": True}]
        )

    @classmethod
    def get_monitor_at(cls, x: int, y: int) -> dict[str, Any] | None:
        """获取指定坐标所在的显示器

        Args:
            x, y: 屏幕坐标

        Returns:
            显示器信息字典，或None
        """
        monitors = cls.get_all_monitors()
        for mon in monitors:
            if mon["x"] <= x < mon["x"] + mon["width"] and mon["y"] <= y < mon["y"] + mon["height"]:
                return mon
        # 默认返回主显示器
        for mon in monitors:
            if mon.get("is_primary"):
                return mon
        return monitors[0] if monitors else None

    @classmethod
    def snap_to_edges(cls, x: int, y: int, w: int, h: int, snap_dist: int = 20) -> tuple[int, int]:
        """计算窗口吸附后的位置

        Args:
            x, y: 窗口左上角坐标
            w, h: 窗口尺寸
            snap_dist: 吸附距离

        Returns:
            吸附后的 (x, y) 坐标
        """
        # 获取窗口所在的显示器
        center_x = x + w // 2
        center_y = y + h // 2
        monitor = cls.get_monitor_at(center_x, center_y)

        if not monitor:
            return x, y

        mon_x = monitor["x"]
        mon_y = monitor["y"]
        mon_w = monitor["width"]
        mon_h = monitor["height"]

        new_x, new_y = x, y

        # 左边缘吸附
        if abs(x - mon_x) < snap_dist:
            new_x = mon_x
        # 右边缘吸附
        elif abs((x + w) - (mon_x + mon_w)) < snap_dist:
            new_x = mon_x + mon_w - w

        # 上边缘吸附
        if abs(y - mon_y) < snap_dist:
            new_y = mon_y
        # 下边缘吸附
        elif abs((y + h) - (mon_y + mon_h)) < snap_dist:
            new_y = mon_y + mon_h - h

        return new_x, new_y


class SingleInstanceManager:
    """单实例管理器

    确保程序同时只运行一个实例，避免多个计时器冲突。
    使用Windows全局命名互斥锁实现。
    """

    @staticmethod
    def ensure_single_instance_or_exit():
        """检查单实例，如果已运行则退出

        创建全局互斥锁，如果已存在则弹窗提示并退出。
        """
        global _MUTEX_HANDLE
        try:
            kernel32 = ctypes.windll.kernel32

            # 配置API签名
            kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
            kernel32.CreateMutexW.restype = ctypes.c_void_p
            kernel32.GetLastError.restype = ctypes.c_uint

            # 尝试创建互斥锁
            h = kernel32.CreateMutexW(None, True, FileConfig.MUTEX_NAME)
            err = kernel32.GetLastError()
            _MUTEX_HANDLE = h

            # 检查是否已存在
            ERROR_ALREADY_EXISTS = 183
            if not h or err == ERROR_ALREADY_EXISTS:
                # 显示提示窗口
                try:
                    r = tk.Tk()
                    r.withdraw()
                    messagebox.showinfo("WT Timer", "WT Timer 已在运行（仅允许一个实例）。")
                    r.destroy()
                except tk.TclError:
                    pass
                sys.exit(0)
        except _WIN32_ACCESS_ERRORS:
            pass

    @staticmethod
    def release():
        """释放互斥锁"""
        global _MUTEX_HANDLE
        if _MUTEX_HANDLE:
            with contextlib.suppress(OSError, AttributeError):
                ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(_MUTEX_HANDLE))
            _MUTEX_HANDLE = None


class GlobalHotkeys:
    """全局热键管理器

    在独立线程中监听Windows消息队列，响应热键事件。
    使用RegisterHotKey API注册全局热键。
    """

    # Windows消息常量
    WM_HOTKEY = 0x0312  # 热键消息
    WM_QUIT = 0x0012  # 退出消息
    MOD_NOREPEAT = 0x4000  # 禁止重复触发

    def __init__(
        self,
        root: tk.Tk,
        hotkeys: list[tuple[int, str, Callable[[], None]]],
        error_cb: Callable[[tuple[str, ...]], None] | None = None,
    ):
        """初始化热键管理器

        Args:
            root: tkinter主窗口
            hotkeys: 热键列表 [(ID, 键名, 回调函数), ...]
        """
        self.root = root
        self.hotkeys = hotkeys
        self.error_cb = error_cb
        self._thread = None
        self._tid = None
        self._stop_event = threading.Event()
        self._ready = threading.Event()

    def start(self):
        """启动热键监听线程"""
        if os.name != "nt" or not HotkeyConfig.GLOBAL_HOTKEYS:
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._ready.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        """停止热键监听"""
        self._stop_event.set()
        thread = self._thread
        if os.name != "nt":
            return
        try:
            # 向监听线程发送退出消息
            if self._tid:
                Win32.user32.PostThreadMessageW(int(self._tid), int(self.WM_QUIT), 0, 0)
        except _WIN32_ACCESS_ERRORS:
            pass
        if thread:
            thread.join(timeout=1.0)

    def _run(self):
        """热键监听主循环（运行在独立线程）"""
        try:
            # 获取线程ID（用于发送消息）
            kernel32 = ctypes.windll.kernel32
            kernel32.GetCurrentThreadId.restype = ctypes.c_uint
            self._tid = int(kernel32.GetCurrentThreadId())
            self._ready.set()
        except _WIN32_ACCESS_ERRORS:
            self._tid = None
            self._ready.set()
            return
        if self._stop_event.is_set():
            return

        # 注册所有热键
        failed_keys: list[str] = []
        for hk_id, key_name, _cb in self.hotkeys:
            try:
                vk = HotkeyConfig.get_vk(str(key_name))
                ok = bool(
                    Win32.user32.RegisterHotKey(
                        None,
                        int(hk_id),
                        int(self.MOD_NOREPEAT),
                        int(vk),
                    )
                )
                if not ok:
                    failed_keys.append(str(key_name))
            except _WIN32_ACCESS_ERRORS:
                failed_keys.append(str(key_name))

        if failed_keys and self.error_cb:
            unique_keys = tuple(dict.fromkeys(failed_keys))
            with contextlib.suppress(tk.TclError):
                self.root.after(0, lambda keys=unique_keys: self.error_cb(keys))

        # 定义消息结构体
        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

        class MSG(ctypes.Structure):
            _fields_ = [
                ("hwnd", ctypes.c_void_p),
                ("message", ctypes.c_uint),
                ("wParam", ctypes.c_size_t),
                ("lParam", ctypes.c_size_t),
                ("time", ctypes.c_uint),
                ("pt", POINT),
            ]

        msg = MSG()
        getmsg = Win32.user32.GetMessageW
        getmsg.argtypes = [ctypes.POINTER(MSG), ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint]
        getmsg.restype = ctypes.c_int

        # 消息循环
        while not self._stop_event.is_set():
            try:
                r = getmsg(ctypes.byref(msg), None, 0, 0)
                if r == 0:  # WM_QUIT
                    break
                if msg.message == self.WM_HOTKEY:
                    hk_id = int(msg.wParam)
                    # 查找对应的回调函数
                    for _id, _key_name, cb in self.hotkeys:
                        if _id == hk_id:
                            with contextlib.suppress(tk.TclError):
                                # 在主线程执行回调
                                self.root.after(0, cb)
                            break
            except _WIN32_ACCESS_ERRORS:
                break

        # 注销所有热键
        for hk_id, _key_name, _cb in self.hotkeys:
            with contextlib.suppress(OSError, AttributeError):
                Win32.user32.UnregisterHotKey(None, int(hk_id))
