#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
===============================================================================
War Thunder SB Timer - 战雷全真模式收益计时器
软件名：Bomana
===============================================================================

项目说明：
---------
本软件是一个用于战雷全真模式的辅助计时工具，帮助玩家管理15分钟的复活周期。
设计理念是提供合法的信息展示，不涉及任何作弊行为。

核心原则：
---------
1. **仅使用官方8111接口**
   - 所有数据来源于战雷官方的localhost:8111 API
   - 不读取游戏内存，不注入代码，不修改游戏文件
   - 8111接口是战雷官方提供给玩家的合法数据接口

2. **避免反作弊风险**
   - 不提供任何游戏内不可见的信息（如敌机位置、敌方数据等）
   - 只展示玩家自己可见的地图信息（战区、机场位置）
   - 计时器基于玩家自身的出生时间，不涉及服务器数据
   - 所有功能都是"信息辅助"而非"游戏干预"

3. **开发规范**
   - 保持代码清晰可读，便于审计
   - 使用合理的数据结构和设计模式
   - 避免过度优化导致的可读性下降
   - 所有网络请求都有超时保护

4. **用户体验**
   - 界面透明覆盖，不遮挡游戏视野
   - 支持拖动、锁定、热键控制
   - 配置自动保存，支持状态恢复
   - 低性能开销，不影响游戏帧率

5. **VibeCoding助手或ChatBot应该遵循的原则**
   - 始终维护核心原则部分注释，永远不要在输出中擅自删除开头的注释块
   - 不要随意删除代码部分的注释，应当在代码中保留注释，只针对每次修改的部分添加/删除注释

数据来源说明：
-------------
- /indicators: 飞机仪表数据（速度、油量、有效性）
- /state: 飞机状态数据（空速、垂直速度等）
- /map_obj.json: 地图对象（战区、机场、玩家位置）
- /map_info.json: 地图元数据（格子坐标系统参数）

技术栈：
-------
- Python 3.7+
- tkinter: GUI框架
- requests: HTTP请求
- ctypes: Windows API调用
- PIL/pystray: 系统托盘（可选）

===============================================================================
"""

import os
import sys
import json
import time
import math
import ctypes
import threading
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Tuple, Any, List, Dict
from enum import Enum, auto

import tkinter as tk
from tkinter import messagebox
import requests

# 可选依赖：系统托盘支持
try:
    from PIL import Image
    import pystray
    HAS_TRAY = True
except ImportError:
    HAS_TRAY = False


# ============================================================================
# 配置类 - 所有可调参数集中管理
# ============================================================================

class GameConfig:
    """游戏逻辑相关配置
    
    这些参数直接影响游戏状态判断的准确性，修改时需谨慎测试。
    """
    # 复活周期：15分钟（战雷SB标准）
    CYCLE_SECONDS = 15 * 60
    
    # 最后警告时间：30秒（进入黄色/红色警告区）
    FINAL_WARNING_SEC = 30
    
    # 着陆判断参数
    LAND_SPEED_KMH = 40          # 低于此速度视为可能着陆
    LAND_CONFIRM_SEC = 3.0       # 持续低速3秒确认着陆
    LANDED_FLASH_SEC = 10.0      # 着陆后"就绪"状态闪烁10秒
    
    # 状态确认时间（防止误判）
    SPAWN_CONFIRM_SEC = 1.0      # 出生确认：连续1秒有实体数据
    DEAD_CONFIRM_SEC = 1.2       # 死亡确认：连续1.2秒无玩家
    HANGAR_CONFIRM_SEC = 1.2     # 机库确认：连续1.2秒无地图数据
    API_DOWN_CONFIRM_SEC = 5.0   # API断线确认：连续5秒无响应
    
    # 补给判断参数（检测地面补给站）
    REFIT_FUEL_JUMP_KG = 50.0    # 油量突增50kg以上
    REFIT_MIN_GAP_SEC = 8.0      # 两次补给最小间隔
    REFIT_SPEED_KMH = 12.0       # 补给时速度很低
    REFIT_VSPEED_MS = 1.2        # 补给时垂直速度很小


class ZoneConfig:
    """战区导航相关配置
    
    这些参数影响战区目标选择和偏航判断。
    """
    # 航向容差：±45°内视为正对目标
    HEADING_TOLERANCE = 45
    
    # 偏航警告：超过±60°显示偏航提示
    DEVIATION_WARNING = 60
    
    # 战区被摧毁警告持续时间：30秒
    DESTROYED_ALERT_SEC = 30.0
    
    # 最多显示战区数量：6个（避免UI过长）
    MAX_DISPLAY_ZONES = 6
    
    # 距离缩放系数：归一化距离 × 100 = km
    # （战雷地图归一化为0-1，实际约100km）
    DISTANCE_SCALE = 100.0
    
    # 地图信息缓存时间：30秒（减少API请求）
    MAP_INFO_CACHE_SEC = 30.0


class NetworkConfig:
    """网络请求相关配置
    
    8111接口的超时和轮询参数，影响响应速度和资源占用。
    """
    # 8111接口基础URL（本地回环地址）
    API_BASE = "http://127.0.0.1:8111"
    
    # 连接超时：80ms（快速失败）
    API_CONNECT_TIMEOUT = 0.08
    
    # 读取超时：160ms（等待响应）
    API_READ_TIMEOUT = 0.16
    
    # 单次tick最大网络耗时：300ms
    MAX_TICK_NET_BUDGET = 0.30
    
    # API断线时的轮询间隔：1.25秒（降低CPU占用）
    BACKOFF_MAX = 1.25
    
    # 正常轮询间隔：250ms（4次/秒，平衡响应与性能）
    POLL_INTERVAL = 0.25


class UIConfig:
    """UI界面相关配置
    
    所有视觉元素的尺寸、颜色、字体都在这里定义。
    """
    # UI缩放倍数：0.85（相对于系统DPI的额外缩放）
    UI_SCALE_MULT = 0.85
    
    # 窗口不透明度：210/255（约82%）
    WINDOW_ALPHA = 210
    
    # UI刷新频率：50ms（20fps，流畅且省资源）
    UI_REFRESH_MS = 50
    
    # 字体定义（字体名, 大小, 样式）
    FONT_TIMER = ("Segoe UI", 44, "bold")           # 主计时器
    FONT_LIFE = ("Segoe UI", 13, "bold")            # 复活次数
    FONT_CYCLE = ("Segoe UI", 12)                   # 当前轮次
    FONT_PILL = ("Segoe UI", 10, "bold")            # 状态徽章
    FONT_STATUS = ("Segoe UI", 11)                  # 状态文本
    FONT_CHECKLIST_TITLE = ("Segoe UI", 9, "bold")  # 检查清单标题
    FONT_CHECKLIST_ITEM = ("Segoe UI", 8)           # 检查清单项目
    FONT_ZONE_TITLE = ("Segoe UI", 9, "bold")       # 战区标题
    FONT_ZONE_ITEM = ("Segoe UI", 8)                # 战区项目
    FONT_DEBUG = ("Consolas", 9)                    # 调试信息
    FONT_HINT = ("Segoe UI", 8)                     # 底部提示
    
    # 内边距定义（水平, 垂直）
    PADDING_MAIN = (14, 10)      # 主容器
    PADDING_ROW2 = (8, 4)        # 第二行（徽章行）
    PADDING_PROGRESS = (4, 6)    # 进度条
    
    # 间距定义
    SPACING_BADGE = 6            # 徽章间距
    SPACING_DEBUG = 8            # 调试信息间距
    
    # 窗口定位参数
    WINDOW_MARGIN = 20           # 屏幕边缘留白
    WINDOW_PADDING = 6           # 窗口内部留白
    
    # 进度条样式
    PROGRESS_BAR_HEIGHT = 6      # 进度条容器高度
    PROGRESS_BAR_THICKNESS = 3   # 进度条实际粗细
    
    # 调试文本换行宽度
    DEBUG_WRAP_LENGTH = 600


class HotkeyConfig:
    """热键配置
    
    全局热键使用F7-F11，避免与游戏冲突。
    """
    # 虚拟键码定义（Windows VK codes）
    VK_F7 = 0x76   # 重置计时器
    VK_F8 = 0x77   # 锁定/解锁
    VK_F9 = 0x78   # 切换角落
    VK_F10 = 0x79  # 声音开关
    VK_F11 = 0x7A  # 战区提示音
    
    # 热键ID（用于注册/注销）
    HK_ID_RESET = 7007
    HK_ID_LOCK = 7008
    HK_ID_CORNER = 7009
    HK_ID_BEEP = 7010
    HK_ID_ZONES = 7011
    
    # 全局热键开关（用户可配置）
    GLOBAL_HOTKEYS = True


class SoundConfig:
    """声音配置
    
    使用Windows Beep API，频率和持续时间定义音效。
    """
    # 音效定义：(频率Hz, 持续时间ms)
    BEEP_TICK = (784, 28)              # 常规提示音
    BEEP_WARNING_1 = (784, 35)         # 警告音1
    BEEP_WARNING_2 = (988, 35)         # 警告音2
    BEEP_MANUAL_RESET = (1000, 80)     # 手动重置
    BEEP_ON_1 = (988, 40)              # 功能开启1
    BEEP_ON_2 = (1319, 70)             # 功能开启2
    BEEP_ZONE_DESTROYED = (440, 100)   # 战区被摧毁
    
    # 音效间隔
    WARNING_GAP_MS = 20   # 警告双音间隔
    ON_GAP_MS = 25        # 开启双音间隔
    
    # 警告触发时间点（秒）
    WARNING_SECONDS = [30, 20, 10, 5, 4, 3, 2, 1]
    MAJOR_WARNINGS = [30, 20, 10]  # 重要警告点（双音）


class FileConfig:
    """文件路径配置
    
    所有配置文件都存储在用户主目录下。
    """
    # 配置文件（JSON格式）
    CONFIG_FILE = Path.home() / ".wttimer_config.json"
    
    # 状态文件（保存当前计时状态）
    STATE_FILE = Path.home() / ".wttimer_state.json"
    
    # 图标文件（用于托盘和窗口）
    ICON_FILE = "app.png"
    
    # 互斥锁名称（防止多开）
    MUTEX_NAME = r"Global\WTtimer_SingleInstance"


class ChecklistConfig:
    """检查清单配置
    
    用户可以自定义起飞前的检查项目。
    """
    # 最多允许的检查项数量
    MAX_ITEMS = 8
    
    # 默认检查清单
    DEFAULT_ITEMS = [
        "收起落架",
        "开增稳系统", 
        "设定打击目标",
        "取消武器选择模式",
        "火控Y67炸弹自动",
        "调整雷达Y11"
    ]


class Theme:
    """颜色主题（GitHub Dark风格）
    
    所有颜色使用十六进制表示，便于调整整体风格。
    """
    BG = "#0a0e13"           # 背景色（深黑）
    BORDER = "#30363d"       # 边框色
    TEXT = "#e6edf3"         # 主文本色
    TEXT_DIM = "#8b949e"     # 次要文本色
    TEXT_MUTED = "#484f58"   # 弱化文本色
    GREEN = "#3fb950"        # 成功/正常状态
    YELLOW = "#d29922"       # 警告状态
    RED = "#f85149"          # 危险状态
    BLUE = "#58a6ff"         # 进度/信息状态
    ORANGE = "#f0883e"       # 偏航/次要警告
    GRAYPILL = "#161b22"     # 徽章背景
    SEPARATOR = "#21262d"    # 分隔线


# ============================================================================
# 工具函数和辅助类
# ============================================================================

def resource_path(rel_path: str) -> str:
    """获取资源文件的绝对路径
    
    支持PyInstaller打包，打包后资源在_MEIPASS临时目录。
    
    Args:
        rel_path: 相对路径（如 "app.png"）
    
    Returns:
        绝对路径字符串
    """
    base = getattr(sys, "_MEIPASS", os.path.abspath("."))
    return os.path.join(base, rel_path)


def fmt_time(sec: Optional[float]) -> str:
    """格式化时间为 MM:SS 格式
    
    Args:
        sec: 秒数（可以为None）
    
    Returns:
        格式化字符串，如 "03:45" 或 "--:--"
    """
    if sec is None:
        return "--:--"
    sec = max(0, int(sec))
    m, s = divmod(sec, 60)
    return f"{m:02d}:{s:02d}"


class ConfigManager:
    """配置文件管理器
    
    负责从JSON文件读写用户配置，如窗口位置、透明度等。
    """
    
    @staticmethod
    def load() -> Dict[str, Any]:
        """加载配置文件
        
        Returns:
            配置字典，加载失败返回空字典
        """
        if FileConfig.CONFIG_FILE.exists():
            try:
                with open(FileConfig.CONFIG_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        return {}
    
    @staticmethod
    def save(config: Dict[str, Any]) -> None:
        """保存配置文件
        
        Args:
            config: 配置字典
        """
        try:
            with open(FileConfig.CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
        except IOError:
            pass


class StateManager:
    """状态文件管理器
    
    保存/恢复当前计时状态，支持应用重启后继续计时。
    原理：记录剩余时间和保存时刻，重启后计算实际流逝时间。
    """
    
    @staticmethod
    def save(remaining_sec: float, life_index: int, sortie_id: int) -> None:
        """保存当前状态
        
        Args:
            remaining_sec: 剩余秒数
            life_index: 复活次数
            sortie_id: 出击次数（补给计数器）
        """
        state_data = {
            'remaining_sec': remaining_sec,
            'save_timestamp': time.time(),
            'life_index': life_index,
            'sortie_id': sortie_id
        }
        try:
            with open(FileConfig.STATE_FILE, 'w', encoding='utf-8') as f:
                json.dump(state_data, f, indent=2)
        except (IOError, OSError):
            pass
    
    @staticmethod
    def load() -> Optional[Dict[str, Any]]:
        """加载并计算恢复后的状态
        
        Returns:
            包含计算后状态的字典，或None（如果无法恢复）
        """
        if not FileConfig.STATE_FILE.exists():
            return None
        try:
            with open(FileConfig.STATE_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # 提取保存时的剩余时间和时间戳
            saved_remaining = data.get('remaining_sec', 0)
            save_time = data.get('save_timestamp', 0)
            
            # 计算实际流逝的时间
            now = time.time()
            elapsed_since_save = now - save_time
            new_remaining = saved_remaining - elapsed_since_save
            
            # 如果过期太久（超过一个完整周期），放弃恢复
            if new_remaining < -GameConfig.CYCLE_SECONDS:
                StateManager.clear()
                return None
            
            # 如果时间为负（已进入下一周期），计算新周期的剩余时间
            if new_remaining < 0:
                overshoot = abs(new_remaining)
                new_remaining = GameConfig.CYCLE_SECONDS - overshoot
            
            # 反推出生时间
            data['computed_remaining'] = new_remaining
            data['computed_spawn_time'] = now - (GameConfig.CYCLE_SECONDS - new_remaining)
            
            return data
        except (json.JSONDecodeError, IOError, KeyError, OSError):
            StateManager.clear()
            return None
    
    @staticmethod
    def clear() -> None:
        """清除状态文件"""
        try:
            if FileConfig.STATE_FILE.exists():
                FileConfig.STATE_FILE.unlink()
        except (IOError, OSError):
            pass


# ============================================================================
# Windows API封装
# ============================================================================

class Win32:
    """Windows API封装类
    
    提供DPI感知、窗口样式设置等Windows特有功能。
    使用ctypes调用user32.dll和kernel32.dll。
    """
    
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

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
        except (OSError, AttributeError):
            try:
                # 方法2: Per-Monitor DPI感知
                ctypes.windll.shcore.SetProcessDpiAwareness(2)
            except (OSError, AttributeError):
                try:
                    # 方法3: System DPI感知（后备）
                    cls.user32.SetProcessDPIAware()
                except (OSError, AttributeError):
                    pass

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
        except (OSError, AttributeError):
            return 1.0

    @classmethod
    def screen_size(cls) -> Tuple[int, int]:
        """获取主屏幕尺寸
        
        Returns:
            (宽度, 高度) 元组
        """
        return cls.user32.GetSystemMetrics(0), cls.user32.GetSystemMetrics(1)

    @classmethod
    def setup_window(cls, hwnd: int, click_through: bool, alpha: int = 210):
        """设置窗口样式（透明、置顶、穿透）
        
        Args:
            hwnd: 窗口句柄
            click_through: 是否允许点击穿透
            alpha: 不透明度 (0-255)
        """
        # 窗口扩展样式标志
        GWL_EXSTYLE = -20
        WS_EX_LAYERED = 0x00080000      # 分层窗口（支持透明度）
        WS_EX_TRANSPARENT = 0x00000020   # 点击穿透
        WS_EX_TOPMOST = 0x00000008       # 窗口置顶
        WS_EX_TOOLWINDOW = 0x00000080    # 工具窗口（不显示在任务栏）
        LWA_ALPHA = 0x2                  # 透明度标志

        try:
            # 获取当前样式
            style = cls.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            
            # 添加必要样式
            style |= (WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_TOOLWINDOW)

            # 根据锁定状态切换点击穿透
            if click_through:
                style |= WS_EX_TRANSPARENT
            else:
                style &= ~WS_EX_TRANSPARENT

            # 应用样式和透明度
            cls.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
            cls.user32.SetLayeredWindowAttributes(hwnd, 0, int(alpha), LWA_ALPHA)
        except (OSError, AttributeError):
            pass

    @classmethod
    def hide_console(cls):
        """隐藏控制台窗口
        
        用于.pyw脚本，确保没有黑窗口显示。
        """
        try:
            hwnd = cls.kernel32.GetConsoleWindow()
            if hwnd:
                cls.user32.ShowWindow(hwnd, 0)
        except (OSError, AttributeError):
            pass


# 全局互斥锁句柄（防止多开）
_MUTEX_HANDLE = None


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
        except (OSError, AttributeError):
            pass
    
    @staticmethod
    def release():
        """释放互斥锁"""
        global _MUTEX_HANDLE
        if _MUTEX_HANDLE:
            try:
                ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(_MUTEX_HANDLE))
            except (OSError, AttributeError):
                pass
            _MUTEX_HANDLE = None


class GlobalHotkeys:
    """全局热键管理器
    
    在独立线程中监听Windows消息队列，响应热键事件。
    使用RegisterHotKey API注册全局热键。
    """
    
    # Windows消息常量
    WM_HOTKEY = 0x0312      # 热键消息
    WM_QUIT = 0x0012        # 退出消息
    MOD_NOREPEAT = 0x4000   # 禁止重复触发

    def __init__(self, root: tk.Tk, hotkeys: List[Tuple[int, int, callable]]):
        """初始化热键管理器
        
        Args:
            root: tkinter主窗口
            hotkeys: 热键列表 [(ID, VK码, 回调函数), ...]
        """
        self.root = root
        self.hotkeys = hotkeys
        self._thread = None
        self._tid = None
        self._stop_event = threading.Event()

    def start(self):
        """启动热键监听线程"""
        if not os.name == "nt" or not HotkeyConfig.GLOBAL_HOTKEYS:
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        """停止热键监听"""
        if not os.name == "nt" or not self._tid:
            return
        try:
            # 向监听线程发送退出消息
            self._stop_event.set()
            Win32.user32.PostThreadMessageW(int(self._tid), int(self.WM_QUIT), 0, 0)
        except (OSError, AttributeError):
            pass
        if self._thread:
            self._thread.join(timeout=1.0)

    def _run(self):
        """热键监听主循环（运行在独立线程）"""
        try:
            # 获取线程ID（用于发送消息）
            kernel32 = ctypes.windll.kernel32
            kernel32.GetCurrentThreadId.restype = ctypes.c_uint
            self._tid = int(kernel32.GetCurrentThreadId())
        except (OSError, AttributeError):
            self._tid = None
            return

        # 注册所有热键
        for hk_id, vk, _cb in self.hotkeys:
            try:
                Win32.user32.RegisterHotKey(None, int(hk_id), int(self.MOD_NOREPEAT), int(vk))
            except (OSError, AttributeError):
                pass

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
                    for _id, _vk, cb in self.hotkeys:
                        if _id == hk_id:
                            try:
                                # 在主线程执行回调
                                self.root.after(0, cb)
                            except tk.TclError:
                                pass
                            break
            except (OSError, AttributeError):
                break

        # 注销所有热键
        for hk_id, _vk, _cb in self.hotkeys:
            try:
                Win32.user32.UnregisterHotKey(None, int(hk_id))
            except (OSError, AttributeError):
                pass


# ============================================================================
# 导航数学函数
# ============================================================================

def calculate_heading_from_vector(dx: float, dy: float) -> Optional[float]:
    """从方向向量计算航向角度
    
    战雷8111地图坐标系：Y轴向下（屏幕坐标系），需要翻转。
    
    Args:
        dx: X方向分量
        dy: Y方向分量
    
    Returns:
        航向角度（0°=北，90°=东，顺时针），或None（如果向量为零）
    """
    if abs(dx) < 1e-9 and abs(dy) < 1e-9:
        return None
    # atan2(x, -y) 因为地图Y轴向下
    angle = math.degrees(math.atan2(dx, -dy))
    return (angle + 360) % 360


def calculate_bearing(x1: float, y1: float, x2: float, y2: float) -> float:
    """计算从点1到点2的方位角
    
    Args:
        x1, y1: 起点坐标
        x2, y2: 终点坐标
    
    Returns:
        方位角（0°=北，90°=东，顺时针）
    """
    dx = x2 - x1
    dy = y2 - y1
    angle = math.degrees(math.atan2(dx, -dy))
    return (angle + 360) % 360


def calculate_distance(x1: float, y1: float, x2: float, y2: float) -> float:
    """计算两点间的欧几里得距离
    
    Args:
        x1, y1: 点1坐标
        x2, y2: 点2坐标
    
    Returns:
        距离（归一化单位，乘以DISTANCE_SCALE得到km）
    """
    return math.sqrt((x2 - x1)**2 + (y2 - y1)**2)


def normalize_angle(angle: float) -> float:
    """将角度规范化到 [-180, 180] 区间
    
    Args:
        angle: 任意角度
    
    Returns:
        规范化后的角度
    """
    while angle > 180:
        angle -= 360
    while angle < -180:
        angle += 360
    return angle


def calculate_relative_bearing(player_heading: float, target_bearing: float) -> float:
    """计算相对方位角
    
    Args:
        player_heading: 玩家当前航向
        target_bearing: 目标绝对方位
    
    Returns:
        相对方位（-180到180，负数=左，正数=右）
    """
    relative = target_bearing - player_heading
    return normalize_angle(relative)


def get_direction_text(relative: float) -> str:
    """将相对方位转换为方向文字
    
    Args:
        relative: 相对方位角
    
    Returns:
        方向文字："前"、"后"、"左"、"右"
    """
    abs_rel = abs(relative)
    if abs_rel <= 30:
        return "前"
    elif abs_rel >= 150:
        return "后"
    elif relative > 0:
        return "右"
    else:
        return "左"


def normalized_to_grid(x: float, y: float, map_info: Optional[Dict]) -> str:
    """将归一化坐标转换为格子坐标（如"C5"）
    
    战雷地图使用字母+数字表示格子，需要map_info提供转换参数。
    
    Args:
        x, y: 归一化坐标 (0-1)
        map_info: 地图元数据字典
    
    Returns:
        格子坐标字符串，如"C5"，失败返回"?"
    """
    if not map_info or not map_info.get('valid'):
        return "?"
    
    try:
        # 提取地图参数
        map_min = map_info.get('map_min', [-65536.0, -65536.0])
        map_max = map_info.get('map_max', [65536.0, 65536.0])
        grid_zero = map_info.get('grid_zero', [0.0, 0.0])
        grid_steps = map_info.get('grid_steps', [5500.0, 5500.0])
        grid_size = map_info.get('grid_size', [52719.0, 55385.0])
        
        # 归一化坐标 → 世界坐标（米）
        world_x = map_min[0] + x * (map_max[0] - map_min[0])
        world_y = map_min[1] + y * (map_max[1] - map_min[1])
        
        # 世界坐标 → 格子索引
        grid_col = int((world_x - grid_zero[0]) / grid_steps[0])
        grid_row = int((world_y - grid_zero[1]) / grid_steps[1])
        
        # 计算总行数
        num_rows = max(1, int(grid_size[1] / grid_steps[1]))
        
        # 列号（从1开始）
        col_num = grid_col + 1
        
        # 行字母索引（从底部向上）
        row_letter_idx = num_rows - 1 - grid_row
        
        # 边界保护
        col_num = max(1, col_num)
        row_letter_idx = max(0, row_letter_idx)
        
        # 转换为字母
        row_letter = chr(ord('A') + row_letter_idx)
        
        return f"{row_letter}{col_num}"
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return "?"


# ============================================================================
# 数据结构定义
# ============================================================================

@dataclass
class TelemetryData:
    """遥测数据（来自8111接口）
    
    包含飞机的基本状态信息，用于判断出生/死亡/着陆等状态。
    """
    ind_ok: bool = False          # /indicators 请求成功
    state_resp_ok: bool = False   # /state 请求成功
    valid: bool = False           # 数据有效性标志
    type_name: str = ""           # 飞机型号名称
    ias_kmh: float = 0            # 指示空速 (km/h)
    vy_ms: float = 0              # 垂直速度 (m/s)
    fuel_kg: float = 0            # 燃油量 (kg)
    compass: float = 0            # 罗盘航向 (度)

    @property
    def entity_like(self) -> bool:
        """判断是否像一个"实体"（有燃油或速度）
        
        用于区分真正的飞机和无效数据。
        """
        if not (self.ind_ok and self.state_resp_ok and self.valid and self.type_name):
            return False
        return (self.fuel_kg > 0.1) or (abs(self.ias_kmh) > 0.1) or (abs(self.vy_ms) > 0.1)

    @property
    def is_on_ground(self) -> bool:
        """判断是否在地面
        
        低速 + 小垂直速度 = 可能着陆
        """
        return (self.ias_kmh < GameConfig.LAND_SPEED_KMH and abs(self.vy_ms) < 2.0)


@dataclass
class Zone:
    """战区数据结构
    
    存储单个战区的位置、导航信息。
    """
    id: str                    # 唯一标识（基于坐标生成）
    index: int                 # 战区编号（1开始）
    x: float                   # X坐标（归一化）
    y: float                   # Y坐标（归一化）
    grid: str = "?"            # 格子坐标（如"C5"）
    color: str = ""            # 颜色标识（API返回）
    distance: float = 0.0      # 距离玩家的距离
    bearing: float = 0.0       # 绝对方位角
    relative: float = 0.0      # 相对方位角
    is_target: bool = False    # 是否为当前目标


@dataclass
class Airfield:
    """机场数据结构
    
    存储机场位置、归属、导航信息。
    """
    id: str                    # 唯一标识
    index: int                 # 机场编号
    x: float                   # X坐标（归一化）
    y: float                   # Y坐标（归一化）
    grid: str = "?"            # 格子坐标
    color: str = ""            # 颜色标识
    is_friendly: bool = False  # 是否为友方机场
    distance: float = 0.0      # 距离
    bearing: float = 0.0       # 绝对方位
    relative: float = 0.0      # 相对方位
    is_target: bool = False    # 是否为目标


@dataclass
class MapObjData:
    """地图对象数据（来自/map_obj.json）
    
    包含玩家、战区、机场的所有信息。
    """
    ok: bool = False                                # 请求成功
    player_aircraft_present: bool = False           # 玩家飞机存在
    player_pos: Optional[Tuple[float, float]] = None  # 玩家位置
    player_dx: float = 0.0                          # 玩家速度向量X
    player_dy: float = 0.0                          # 玩家速度向量Y
    obj_count: int = 0                              # 对象总数
    zones: List[Zone] = field(default_factory=list)           # 战区列表
    airfields: List[Airfield] = field(default_factory=list)   # 机场列表


@dataclass
class MapInfo:
    """地图元数据（来自/map_info.json）
    
    提供格子坐标系统的转换参数，缓存30秒避免频繁请求。
    """
    valid: bool = False
    grid_size: List[float] = field(default_factory=lambda: [52719.0, 55385.0])
    grid_steps: List[float] = field(default_factory=lambda: [5500.0, 5500.0])
    grid_zero: List[float] = field(default_factory=lambda: [0.0, 0.0])
    map_min: List[float] = field(default_factory=lambda: [-65536.0, -65536.0])
    map_max: List[float] = field(default_factory=lambda: [65536.0, 65536.0])
    fetch_time: float = 0.0    # 获取时间（用于判断是否过期）


class Phase(Enum):
    """游戏阶段枚举
    
    定义计时器的所有可能状态。
    """
    IDLE = auto()          # 空闲（未开始）
    HANGAR = auto()        # 机库中
    ARMING = auto()        # 准备出生（检测到飞机但未确认）
    ALIVE = auto()         # 存活中（正在计时）
    LOSS_PENDING = auto()  # 可能死亡（玩家消失但未确认）
    WAIT_NEXT = auto()     # 等待下次复活


@dataclass
class LifeState:
    """单次生命状态
    
    记录一次出生的时间和编号，用于计算当前周期。
    """
    spawn_time: float      # 出生时间戳（秒）
    life_index: int        # 复活次数（1开始）

    def elapsed_seconds(self, now: float) -> float:
        """计算已存活秒数"""
        return now - self.spawn_time

    def current_cycle(self, now: float) -> int:
        """计算当前是第几轮（1开始）"""
        return int(self.elapsed_seconds(now) // GameConfig.CYCLE_SECONDS) + 1

    def cycle_remaining(self, now: float) -> float:
        """计算当前周期剩余秒数"""
        elapsed = self.elapsed_seconds(now)
        return GameConfig.CYCLE_SECONDS - (elapsed % GameConfig.CYCLE_SECONDS)

    def cycle_progress(self, now: float) -> float:
        """计算当前周期进度（0.0-1.0）"""
        elapsed = self.elapsed_seconds(now)
        return (elapsed % GameConfig.CYCLE_SECONDS) / GameConfig.CYCLE_SECONDS


@dataclass
class ZoneNavigationState:
    """战区导航状态
    
    管理战区列表、目标选择、被摧毁战区追踪、地速计算。
    """
    zones: List[Zone] = field(default_factory=list)              # 当前战区列表
    target_zone: Optional[Zone] = None                           # 当前目标战区
    previous_zone_ids: set = field(default_factory=set)          # 上一帧战区ID集合
    destroyed_zones: List[Zone] = field(default_factory=list)    # 被摧毁的战区
    destroyed_alert_until: float = 0.0                           # 摧毁警告持续到的时间戳
    is_deviating: bool = False                                   # 是否偏航
    player_heading: float = 0.0                                  # 玩家航向
    
    # 地速计算相关（v5.2新增）
    last_pos: Optional[Tuple[float, float]] = None  # 上次位置
    last_pos_ts: float = 0.0                        # 上次位置时间戳
    ground_speed: float = 0.0                       # 地速（归一化单位/秒）


@dataclass
class GameState:
    """游戏总体状态
    
    所有游戏逻辑状态的集合，由GameLogic类管理。
    """
    phase: Phase = Phase.IDLE                                    # 当前阶段
    current_life: Optional[LifeState] = None                     # 当前生命
    sortie_id: int = 0                                           # 出击计数（补给时递增）
    last_refit_ts: float = 0.0                                   # 上次补给时间
    
    # 状态确认相关（防止误判）
    spawn_candidate_since: Optional[float] = None                # 出生候选开始时间
    missing_player_since: Optional[float] = None                 # 玩家消失开始时间
    landing_start_time: Optional[float] = None                   # 着陆开始时间
    landed_flash_until: float = 0.0                              # 着陆闪烁持续到
    hangar_candidate_since: Optional[float] = None               # 机库候选开始时间
    
    # API状态
    api_down: bool = False                                       # API是否断线
    api_down_candidate_since: Optional[float] = None             # API断线候选时间
    
    # 缓存的数据
    last_tel: Optional[TelemetryData] = None                     # 上一帧遥测数据
    last_map: Optional[MapObjData] = None                        # 上一帧地图数据
    map_info: Optional[MapInfo] = None                           # 地图元数据（缓存）
    
    # 导航状态
    zone_nav: ZoneNavigationState = field(default_factory=ZoneNavigationState)


@dataclass(frozen=True)
class ZoneDisplayInfo:
    """战区显示信息（UI层数据）
    
    不可变数据类，用于快照传递给UI。
    """
    id: str
    grid: str
    distance_km: float
    direction: str
    relative: float
    is_target: bool
    ete_str: str = ""      # 预计抵达时间字符串


@dataclass(frozen=True)
class AirfieldDisplayInfo:
    """机场显示信息（UI层数据）"""
    id: str
    side: str              # "friendly" 或 "enemy"
    grid: str
    distance_km: float
    direction: str
    relative: float
    is_target: bool
    ete_str: str = ""


@dataclass(frozen=True)
class UISnapshot:
    """UI快照（逻辑层 → UI层的数据传递）
    
    不可变快照，包含UI渲染所需的所有信息。
    每帧生成一次，避免线程安全问题。
    """
    phase: Phase
    life_index: Optional[int]
    cycle: Optional[int]
    remaining_sec: Optional[float]
    progress: float
    sortie_id: int
    main_badge: Tuple[str, str, str]      # (文本, 前景色, 背景色)
    flight_badge: Tuple[str, str, str]
    status_text: str
    diag_text: str
    api_down: bool
    api_down_pending: bool
    on_ground: bool
    landed_flash: bool
    
    # 导航相关
    zones: List[ZoneDisplayInfo] = field(default_factory=list)
    friendly_airfield: Optional[AirfieldDisplayInfo] = None
    enemy_airfields: List[AirfieldDisplayInfo] = field(default_factory=list)
    has_airfield_target: bool = False
    has_target: bool = False
    is_deviating: bool = False
    deviation_angle: float = 0.0
    
    # 战区被摧毁警告
    zone_destroyed_alert: bool = False
    destroyed_zone_count: int = 0
    destroyed_zone_text: str = ""
    
    player_heading: float = 0.0


# ============================================================================
# 网络请求层
# ============================================================================

class Budget:
    """时间预算管理
    
    限制单次tick的总网络耗时，避免阻塞主循环。
    """
    def __init__(self, seconds: float):
        self.deadline = time.monotonic() + max(0.0, seconds)
    
    def remaining(self) -> float:
        """返回剩余时间（秒）"""
        return self.deadline - time.monotonic()


class HttpJson:
    """HTTP JSON请求封装
    
    使用requests库，支持超时和预算管理。
    """
    def __init__(self, session: requests.Session):
        self.session = session
    
    def get_json(self, url: str, budget: Budget) -> Tuple[bool, Optional[Any]]:
        """发起GET请求并解析JSON
        
        Args:
            url: 目标URL
            budget: 时间预算
        
        Returns:
            (成功标志, JSON数据或None)
        """
        rem = budget.remaining()
        if rem <= 0.0:
            return False, None
        
        # 计算超时时间
        connect_t = min(NetworkConfig.API_CONNECT_TIMEOUT, max(0.01, rem))
        read_t = min(NetworkConfig.API_READ_TIMEOUT, max(0.01, rem))
        
        try:
            r = self.session.get(url, timeout=(connect_t, read_t))
            if not r.ok:
                return False, None
            return True, r.json()
        except (requests.RequestException, ValueError):
            return False, None


class TelemetryFetcher:
    """遥测数据获取器
    
    负责从8111接口获取飞机状态数据。
    同时请求/indicators和/state两个端点。
    """
    def __init__(self, http: HttpJson):
        self.http = http
    
    def fetch(self, budget: Budget) -> TelemetryData:
        """获取遥测数据
        
        Args:
            budget: 时间预算
        
        Returns:
            TelemetryData对象（即使失败也返回默认值）
        """
        data = TelemetryData()
        
        # 请求 /indicators (飞机基本信息)
        ok, j = self.http.get_json(f"{NetworkConfig.API_BASE}/indicators", budget)
        data.ind_ok = ok
        if ok and isinstance(j, dict):
            data.valid = bool(j.get("valid", False))
            data.type_name = str(j.get("type", "") or "").strip()
            data.compass = float(j.get("compass1") or j.get("compass") or 0)
        
        if not data.ind_ok:
            return data
        
        # 请求 /state (飞机状态)
        ok, j = self.http.get_json(f"{NetworkConfig.API_BASE}/state", budget)
        data.state_resp_ok = ok
        if ok and isinstance(j, dict):
            data.ias_kmh = float(j.get("IAS, km/h", 0) or 0)
            data.vy_ms = float(j.get("Vy, m/s", 0) or 0)
            data.fuel_kg = float(j.get("Mfuel, kg", 0) or 0)
        
        return data


class MapInfoFetcher:
    """地图元数据获取器
    
    获取格子坐标系统的转换参数，结果会缓存30秒。
    """
    def __init__(self, http: HttpJson):
        self.http = http
    
    def fetch(self, budget: Budget) -> Optional[MapInfo]:
        """获取地图元数据
        
        Args:
            budget: 时间预算
        
        Returns:
            MapInfo对象或None
        """
        ok, j = self.http.get_json(f"{NetworkConfig.API_BASE}/map_info.json", budget)
        if not ok or not isinstance(j, dict) or not j.get("valid", False):
            return None
        
        return MapInfo(
            valid=True,
            grid_size=j.get("grid_size", [52719.0, 55385.0]),
            grid_steps=j.get("grid_steps", [5500.0, 5500.0]),
            grid_zero=j.get("grid_zero", [0.0, 0.0]),
            map_min=j.get("map_min", [-65536.0, -65536.0]),
            map_max=j.get("map_max", [65536.0, 65536.0]),
            fetch_time=time.time()
        )


class MapObjectsFetcher:
    """地图对象获取器
    
    解析/map_obj.json，提取玩家、战区、机场信息。
    """
    def __init__(self, http: HttpJson):
        self.http = http
    
    def fetch(self, budget: Budget, map_info: Optional[MapInfo] = None) -> MapObjData:
        """获取地图对象
        
        Args:
            budget: 时间预算
            map_info: 地图元数据（用于坐标转换）
        
        Returns:
            MapObjData对象
        """
        out = MapObjData()
        ok, j = self.http.get_json(f"{NetworkConfig.API_BASE}/map_obj.json", budget)
        if not ok:
            return out
        
        out.ok = True
        
        # 提取对象列表
        objs = j if isinstance(j, list) else j.get("objects", []) if isinstance(j, dict) else []
        out.obj_count = len(objs)
        
        # 准备map_info字典（用于坐标转换）
        map_info_dict = None
        if map_info and map_info.valid:
            map_info_dict = {
                'valid': True,
                'grid_size': map_info.grid_size,
                'grid_steps': map_info.grid_steps,
                'grid_zero': map_info.grid_zero,
                'map_min': map_info.map_min,
                'map_max': map_info.map_max
            }
        
        zone_index = 1
        airfield_index = 1
        
        # 遍历对象
        for o in objs:
            if not isinstance(o, dict):
                continue
            
            obj_type = o.get("type", "")
            icon = o.get("icon", "")
            
            if obj_type == "aircraft" and icon == "Player":
                # 玩家飞机
                out.player_aircraft_present = True
                out.player_pos = (o.get("x", 0), o.get("y", 0))
                out.player_dx = float(o.get("dx", 0) or 0)
                out.player_dy = float(o.get("dy", 0) or 0)
                
            elif obj_type == "airfield":
                # 机场：使用跑道起止点的中心
                sx = o.get("sx")
                sy = o.get("sy")
                ex = o.get("ex")
                ey = o.get("ey")
                
                if sx is None or sy is None or ex is None or ey is None:
                    continue
                
                # 计算跑道中心点
                cx = (float(sx) + float(ex)) / 2.0
                cy = (float(sy) + float(ey)) / 2.0

                # 坐标转换（保持归一化坐标系统）
                if map_info_dict and map_info_dict.get('valid'):
                    wx, wy = cx, cy
                    grid = normalized_to_grid(cx, cy, map_info_dict)
                else:
                    wx, wy = 0.0, 0.0
                    grid = "?"

                # 判断归属：蓝色通道高 = 友方
                rgb = o.get("color[]", [0, 0, 0])
                is_friendly = False
                if isinstance(rgb, list) and len(rgb) >= 3:
                    r, g, b = rgb[:3]
                    is_friendly = (b > 200 and b > r)

                out.airfields.append(Airfield(
                    id=f"airfield_{airfield_index}",
                    index=airfield_index,
                    x=wx, y=wy,
                    grid=grid,
                    color=o.get("color", ""),
                    is_friendly=is_friendly
                ))
                airfield_index += 1

            elif obj_type == "bombing_point":
                # 战区
                zone_x = o.get("x", 0)
                zone_y = o.get("y", 0)
                out.zones.append(Zone(
                    id=f"zone_{zone_x:.4f}_{zone_y:.4f}",
                    index=zone_index,
                    x=zone_x, y=zone_y,
                    grid=normalized_to_grid(zone_x, zone_y, map_info_dict),
                    color=o.get("color", "")
                ))
                zone_index += 1
        
        return out


# ============================================================================
# 游戏逻辑核心
# ============================================================================

class GameLogic:
    """游戏逻辑核心类
    
    职责：
    1. 轮询8111接口获取数据
    2. 状态机管理（IDLE → HANGAR → ARMING → ALIVE → ...）
    3. 导航计算（战区目标选择、地速计算）
    4. 生成UI快照（线程安全的数据传递）
    
    设计模式：
    - 使用锁保护共享状态
    - 独立线程执行tick循环
    - 通过snapshot()传递数据给UI
    """
    
    def __init__(self):
        self._lock = threading.Lock()
        self.session = requests.Session()
        self.http = HttpJson(self.session)
        self.tel = TelemetryFetcher(self.http)
        self.map_info_fetcher = MapInfoFetcher(self.http)
        self.map = MapObjectsFetcher(self.http)
        self.state = GameState()

    def tick(self) -> None:
        """主逻辑循环（每250ms执行一次）
        
        流程：
        1. 获取遥测数据
        2. 获取/缓存地图元数据
        3. 获取地图对象
        4. 更新游戏状态（状态机）
        5. 更新导航信息
        """
        now = time.time()
        budget = Budget(NetworkConfig.MAX_TICK_NET_BUDGET)
        
        # 1. 获取遥测数据
        tel = self.tel.fetch(budget)
        
        # 2. 检查是否需要更新地图元数据（30秒缓存）
        with self._lock:
            map_info = self.state.map_info
            need_map_info = (
                map_info is None or 
                not map_info.valid or 
                (now - map_info.fetch_time) > ZoneConfig.MAP_INFO_CACHE_SEC
            )
        
        if need_map_info and budget.remaining() > 0.05:
            new_map_info = self.map_info_fetcher.fetch(budget)
            if new_map_info:
                with self._lock:
                    self.state.map_info = new_map_info
                    map_info = new_map_info
        
        # 3. 获取地图对象
        mp = self.map.fetch(budget, map_info)
        
        # 4. 判断API状态
        api_up = bool(tel.ind_ok or tel.state_resp_ok or mp.ok)

        # 5. 更新游戏状态（线程安全）
        with self._lock:
            s = self.state
            prev_tel = s.last_tel
            s.last_tel = tel
            s.last_map = mp

            # API状态管理
            if api_up:
                s.api_down = False
                s.api_down_candidate_since = None
            else:
                # API断线确认（5秒）
                if s.api_down_candidate_since is None:
                    s.api_down_candidate_since = now
                if (now - s.api_down_candidate_since) >= GameConfig.API_DOWN_CONFIRM_SEC:
                    s.api_down = True
            
            if s.api_down:
                if s.phase != Phase.HANGAR:
                    s.phase = Phase.IDLE
                return

            # 判断玩家是否存在
            player_present = bool(mp.ok and mp.player_aircraft_present)
            spawn_candidate = player_present and tel.entity_like

            # 更新导航信息（战区、地速）
            self._update_zone_navigation_locked(mp, tel, now)

            # === 状态机逻辑 ===
            
            # 机库检测：无地图数据或对象为空
            hangar_like = (not mp.ok) or (mp.obj_count == 0)
            if hangar_like and (not player_present) and s.phase != Phase.ALIVE:
                if s.hangar_candidate_since is None:
                    s.hangar_candidate_since = now
                elif (now - s.hangar_candidate_since) >= GameConfig.HANGAR_CONFIRM_SEC:
                    s.phase = Phase.HANGAR
                    self._reset_life_state_locked()
            else:
                s.hangar_candidate_since = None

            # 各阶段处理
            if s.phase == Phase.HANGAR:
                # 机库 → 准备出生
                if spawn_candidate:
                    s.phase = Phase.ARMING
                    s.spawn_candidate_since = now
                return

            if s.phase == Phase.IDLE:
                # 空闲 → 准备出生
                if spawn_candidate:
                    s.phase = Phase.ARMING
                    s.spawn_candidate_since = now

            elif s.phase == Phase.ARMING:
                # 准备出生 → 确认出生（1秒）
                if spawn_candidate:
                    if s.spawn_candidate_since is None:
                        s.spawn_candidate_since = now
                    if (now - s.spawn_candidate_since) >= GameConfig.SPAWN_CONFIRM_SEC:
                        self._start_new_life_locked(now)
                        s.phase = Phase.ALIVE
                        self._clear_transient_state_locked()
                else:
                    s.spawn_candidate_since = None
                    s.phase = Phase.IDLE

            elif s.phase == Phase.ALIVE:
                # 存活中：检测补给、着陆、死亡
                
                # 补给检测：燃油突增
                if prev_tel and prev_tel.state_resp_ok and tel.state_resp_ok:
                    fuel_jump = tel.fuel_kg - prev_tel.fuel_kg
                    if (fuel_jump >= GameConfig.REFIT_FUEL_JUMP_KG and
                        tel.ias_kmh <= GameConfig.REFIT_SPEED_KMH and
                        abs(tel.vy_ms) <= GameConfig.REFIT_VSPEED_MS and
                        (now - s.last_refit_ts) >= GameConfig.REFIT_MIN_GAP_SEC):
                        s.sortie_id += 1
                        s.last_refit_ts = now
                        s.landing_start_time = None
                        s.landed_flash_until = 0.0

                # 着陆检测
                self._update_landing_locked(tel, now)
                
                # 死亡检测：玩家消失
                if not player_present:
                    s.phase = Phase.LOSS_PENDING
                    s.missing_player_since = now
                    s.spawn_candidate_since = None
                else:
                    s.missing_player_since = None

            elif s.phase == Phase.LOSS_PENDING:
                # 可能死亡 → 确认死亡（1.2秒）
                if player_present:
                    s.phase = Phase.ALIVE
                    s.missing_player_since = None
                else:
                    if s.missing_player_since is None:
                        s.missing_player_since = now
                    if (now - s.missing_player_since) >= GameConfig.DEAD_CONFIRM_SEC:
                        s.phase = Phase.WAIT_NEXT
                        s.spawn_candidate_since = None

            elif s.phase == Phase.WAIT_NEXT:
                # 等待复活 → 下次出生
                if spawn_candidate:
                    if s.spawn_candidate_since is None:
                        s.spawn_candidate_since = now
                    if (now - s.spawn_candidate_since) >= GameConfig.SPAWN_CONFIRM_SEC:
                        self._start_new_life_locked(now)
                        s.phase = Phase.ALIVE
                        self._clear_transient_state_locked()
                else:
                    s.spawn_candidate_since = None

    def _update_zone_navigation_locked(self, mp: MapObjData, tel: TelemetryData, now: float):
        """更新战区导航状态（必须在锁内调用）
        
        功能：
        1. 计算地速（基于位置微分）
        2. 检测战区被摧毁
        3. 计算所有战区的导航信息
        4. 选择目标战区
        
        Args:
            mp: 地图对象数据
            tel: 遥测数据
            now: 当前时间戳
        """
        nav = self.state.zone_nav
        
        if not mp.ok or not mp.player_pos:
            # 无数据时重置
            nav.zones = []
            nav.target_zone = None
            nav.is_deviating = False
            nav.last_pos = None
            nav.ground_speed = 0.0
            return
        
        px, py = mp.player_pos
        
        # 计算航向：优先使用速度向量，后备使用罗盘
        heading = calculate_heading_from_vector(mp.player_dx, mp.player_dy)
        if heading is None:
            heading = tel.compass
        nav.player_heading = heading
        
        # === 地速(SOG)计算 ===
        # 原理：通过位置微分计算真实地速，不受风速影响
        if nav.last_pos and tel.ias_kmh > 40:
            dt = now - nav.last_pos_ts
            
            # 限制计算频率（>0.4s），避免除法震荡
            if dt >= 0.4:
                dx = px - nav.last_pos[0]
                dy = py - nav.last_pos[1]
                dist_moved = math.sqrt(dx*dx + dy*dy)
                
                if dist_moved > 0:
                    current_speed = dist_moved / dt
                    
                    # 指数平滑滤波（EMA）
                    alpha = 0.2
                    if nav.ground_speed == 0:
                        nav.ground_speed = current_speed
                    else:
                        nav.ground_speed = (nav.ground_speed * (1 - alpha)) + (current_speed * alpha)
                
                nav.last_pos = (px, py)
                nav.last_pos_ts = now
        else:
            # 初始化或低速时
            if not nav.last_pos or (now - nav.last_pos_ts > 2.0):
                nav.last_pos = (px, py)
                nav.last_pos_ts = now
                if tel.ias_kmh <= 40:
                    nav.ground_speed = 0.0

        # === 战区被摧毁检测 ===
        current_zone_ids = {z.id for z in mp.zones}
        if nav.previous_zone_ids and current_zone_ids:
            destroyed_ids = nav.previous_zone_ids - current_zone_ids
            if destroyed_ids:
                # 找到被摧毁的战区
                destroyed = [z for z in nav.zones if z.id in destroyed_ids]
                if destroyed:
                    nav.destroyed_zones = destroyed
                    nav.destroyed_alert_until = now + ZoneConfig.DESTROYED_ALERT_SEC
        nav.previous_zone_ids = current_zone_ids
        
        # === 计算所有战区的导航信息 ===
        zones_with_nav = []
        for zone in mp.zones:
            bearing = calculate_bearing(px, py, zone.x, zone.y)
            relative = calculate_relative_bearing(heading, bearing)
            distance = calculate_distance(px, py, zone.x, zone.y)
            zones_with_nav.append(Zone(
                id=zone.id, index=zone.index, x=zone.x, y=zone.y,
                grid=zone.grid, color=zone.color, distance=distance,
                bearing=bearing, relative=relative, is_target=False
            ))
        
        # 按距离排序
        zones_with_nav.sort(key=lambda z: z.distance)
        
        # === 选择目标战区 ===
        # 策略：优先选择航向容差内的，否则选最近的
        target = None
        for zone in zones_with_nav:
            if abs(zone.relative) <= ZoneConfig.HEADING_TOLERANCE:
                target = zone
                break
        if not target and zones_with_nav:
            target = zones_with_nav[0]
        
        # 标记目标
        if target:
            for i, zone in enumerate(zones_with_nav):
                if zone.id == target.id:
                    zones_with_nav[i] = Zone(
                        id=zone.id, index=zone.index, x=zone.x, y=zone.y,
                        grid=zone.grid, color=zone.color, distance=zone.distance,
                        bearing=zone.bearing, relative=zone.relative, is_target=True
                    )
                    target = zones_with_nav[i]
                    break
        
        nav.zones = zones_with_nav
        nav.target_zone = target
        nav.is_deviating = (abs(target.relative) > ZoneConfig.DEVIATION_WARNING) if target else False

    def manual_reset(self):
        """手动重置计时器（F7热键）
        
        将当前生命的出生时间设为现在，重启15分钟周期。
        """
        with self._lock:
            if self.state.phase == Phase.ALIVE and self.state.current_life:
                self.state.current_life.spawn_time = time.time()
                self.state.landing_start_time = None
                self.state.landed_flash_until = 0.0

    def save_timer_state(self):
        """保存计时器状态到文件
        
        用于应用退出时保存进度。
        """
        with self._lock:
            if self.state.phase != Phase.ALIVE or not self.state.current_life:
                StateManager.clear()
                return
            now = time.time()
            remaining = self.state.current_life.cycle_remaining(now)
            StateManager.save(remaining, self.state.current_life.life_index, self.state.sortie_id)

    def restore_timer_state(self) -> bool:
        """从文件恢复计时器状态
        
        Returns:
            是否成功恢复
        """
        data = StateManager.load()
        if not data:
            return False
        
        with self._lock:
            self.state.current_life = LifeState(
                spawn_time=data['computed_spawn_time'],
                life_index=data.get('life_index', 1)
            )
            self.state.sortie_id = data.get('sortie_id', 0)
            self.state.phase = Phase.ALIVE
            self.state.last_refit_ts = data['computed_spawn_time']
        return True

    def snapshot(self) -> UISnapshot:
        """生成UI快照（线程安全）
        
        将当前游戏状态转换为不可变的UISnapshot对象。
        这是逻辑层与UI层的唯一数据通道。
        
        Returns:
            UISnapshot对象
        """
        now = time.time()
        with self._lock:
            s = self.state
            tel = s.last_tel or TelemetryData()
            mp = s.last_map or MapObjData()
            life = s.current_life
            
            # 计算时间相关
            remaining = None
            cycle = None
            progress = 0.0
            life_index = life.life_index if life else None

            if s.phase == Phase.ALIVE and life:
                remaining = life.cycle_remaining(now)
                cycle = life.current_cycle(now)
                progress = life.cycle_progress(now)

            # 确定主徽章和状态文字
            api_down_pending = (s.api_down_candidate_since is not None) and (not s.api_down)

            if s.api_down:
                main_badge = ("❌8111不可用", Theme.TEXT, Theme.RED)
                status_text = "未检测到 8111"
            elif api_down_pending:
                main_badge = ("⏳加入战斗中", Theme.TEXT, Theme.BLUE)
                status_text = "加入战斗中"
            else:
                if s.phase == Phase.ALIVE:
                    main_badge = ("战斗中", Theme.TEXT, Theme.GREEN)
                    status_text = "计时中"
                elif s.phase == Phase.WAIT_NEXT:
                    main_badge = ("等待复活", Theme.TEXT, Theme.YELLOW)
                    status_text = "等待复活"
                elif s.phase == Phase.LOSS_PENDING:
                    main_badge = ("坠毁/弹射", Theme.TEXT, Theme.YELLOW)
                    status_text = "坠毁/弹射"
                elif s.phase == Phase.ARMING:
                    main_badge = ("部署中", Theme.TEXT, Theme.BLUE)
                    status_text = "部署中"
                elif s.phase == Phase.HANGAR:
                    main_badge = ("🏠机库", Theme.TEXT, Theme.GRAYPILL)
                    status_text = "等待游戏开始"
                else:
                    main_badge = ("IDLE", Theme.TEXT, Theme.GRAYPILL)
                    status_text = "等待中"

            # 飞行徽章
            landed_flash = s.landed_flash_until > now
            on_ground = tel.is_on_ground

            if s.phase != Phase.ALIVE or not life:
                flight_badge = ("—", Theme.TEXT_DIM, Theme.GRAYPILL)
            else:
                if landed_flash:
                    flight_badge = ("就绪✓", Theme.TEXT, Theme.GREEN)
                else:
                    flight_badge = ("着陆中", Theme.TEXT_DIM, Theme.GRAYPILL) if on_ground else ("飞行中", Theme.TEXT_DIM, Theme.GRAYPILL)

            # 调试信息
            player_present = bool(mp.ok and mp.player_aircraft_present)
            diag_lines = [
                f"MAP: ok={int(mp.ok)} | objs={mp.obj_count} | player={int(player_present)}",
                f"IND: ok={int(tel.ind_ok)} | valid={int(tel.valid)} | type={'✓' if tel.type_name else '✗'}",
                f"STATE: ok={int(tel.state_resp_ok)} | fuel={tel.fuel_kg:.0f}kg | ias={tel.ias_kmh:.0f}km/h"
            ]
            diag = "\n".join(diag_lines)

            # 战区导航信息
            nav = s.zone_nav
            zone_display_list = []
            gs = nav.ground_speed

            for zone in nav.zones[:ZoneConfig.MAX_DISPLAY_ZONES]:
                # ETE计算
                ete_text = ""
                if zone.is_target and gs > 1e-7:
                    seconds_left = zone.distance / gs
                    if seconds_left < 5999:
                        m, s_time = divmod(int(seconds_left), 60)
                        ete_text = f"{m:02d}:{s_time:02d}"

                zone_display_list.append(ZoneDisplayInfo(
                    id=zone.id, grid=zone.grid, 
                    distance_km=zone.distance * ZoneConfig.DISTANCE_SCALE,
                    direction=get_direction_text(zone.relative), 
                    relative=zone.relative, is_target=zone.is_target,
                    ete_str=ete_text
                ))
            
            # 机场导航信息
            friendly_airfield_display = None
            enemy_airfields_display: List[AirfieldDisplayInfo] = []
            has_airfield_target = False

            if mp.ok and mp.player_pos and getattr(mp, "airfields", None):
                px, py = mp.player_pos
                heading = nav.player_heading

                friendly_infos: List[Tuple[float, AirfieldDisplayInfo]] = []
                enemy_infos: List[Tuple[float, AirfieldDisplayInfo]] = []

                for af in mp.airfields:
                    if af.x == 0.0 and af.y == 0.0 and af.grid == "?":
                        continue

                    bearing = calculate_bearing(px, py, af.x, af.y)
                    relative = calculate_relative_bearing(heading, bearing)
                    distance = calculate_distance(px, py, af.x, af.y)
                    info = AirfieldDisplayInfo(
                        id=af.id,
                        side="friendly" if af.is_friendly else "enemy",
                        grid=af.grid,
                        distance_km=distance * ZoneConfig.DISTANCE_SCALE,
                        direction=get_direction_text(relative),
                        relative=relative,
                        is_target=False,
                        ete_str=""
                    )
                    if af.is_friendly:
                        friendly_infos.append((distance, info))
                    else:
                        enemy_infos.append((distance, info))

                # 友方机场：只显示最近的
                if friendly_infos:
                    friendly_infos.sort(key=lambda t: t[0])
                    dist, info = friendly_infos[0]
                    ete_text = ""
                    # 只在航向前方（±90°）显示ETE
                    if abs(info.relative) <= 90 and nav.ground_speed > 1e-7:
                        seconds_left = dist / nav.ground_speed
                        if seconds_left < 3600:
                            mm, ss = divmod(int(seconds_left), 60)
                            ete_text = f"{mm:02d}:{ss:02d}"
                    friendly_airfield_display = AirfieldDisplayInfo(
                        id=info.id, side=info.side, grid=info.grid,
                        distance_km=info.distance_km, direction=info.direction, 
                        relative=info.relative,
                        is_target=True, ete_str=ete_text
                    )

                # 敌方机场：显示所有
                if enemy_infos:
                    enemy_infos.sort(key=lambda t: t[0])
                    target_idx = 0
                    for i, (dist, info) in enumerate(enemy_infos):
                        if abs(info.relative) <= ZoneConfig.HEADING_TOLERANCE:
                            target_idx = i
                            break

                    for i, (dist, info) in enumerate(enemy_infos):
                        is_target = (i == target_idx)
                        ete_text = ""
                        if is_target and nav.ground_speed > 1e-7:
                            seconds_left = dist / nav.ground_speed
                            if seconds_left < 3600:
                                mm, ss = divmod(int(seconds_left), 60)
                                ete_text = f"{mm:02d}:{ss:02d}"
                        enemy_airfields_display.append(AirfieldDisplayInfo(
                            id=info.id, side=info.side, grid=info.grid,
                            distance_km=info.distance_km, direction=info.direction, 
                            relative=info.relative,
                            is_target=is_target, ete_str=ete_text
                        ))
                    has_airfield_target = True
            
            has_target = nav.target_zone is not None
            deviation_angle = nav.target_zone.relative if nav.target_zone else 0.0
            
            # 战区被摧毁警告
            zone_destroyed_alert = nav.destroyed_alert_until > now
            destroyed_count = len(nav.destroyed_zones) if zone_destroyed_alert else 0
            destroyed_zone_text = ""
            
            # v5.4.2: 实时计算被摧毁战区的位置信息（不显示格子坐标）
            if zone_destroyed_alert and nav.destroyed_zones:
                items = []
                has_pos = mp.player_pos is not None
                if has_pos:
                    px, py = mp.player_pos
                    for dz in nav.destroyed_zones:
                        try:
                            if nav.player_heading is not None:
                                bearing = calculate_bearing(px, py, dz.x, dz.y)
                                rel = calculate_relative_bearing(nav.player_heading, bearing)
                                dir_text = get_direction_text(rel)
                                dist_km = calculate_distance(px, py, dz.x, dz.y) * ZoneConfig.DISTANCE_SCALE
                                items.append(f"#{dz.index} {dir_text} {dist_km:.1f}km")
                            else:
                                dist_km = calculate_distance(px, py, dz.x, dz.y) * ZoneConfig.DISTANCE_SCALE
                                items.append(f"#{dz.index} {dist_km:.1f}km")
                        except Exception:
                            items.append(f"#{dz.index}")
                else:
                    for dz in nav.destroyed_zones:
                        items.append(f"#{dz.index}")
                destroyed_zone_text = "  |  ".join(items)

            return UISnapshot(
                phase=s.phase, life_index=life_index, cycle=cycle, 
                remaining_sec=remaining, progress=progress, sortie_id=s.sortie_id, 
                main_badge=main_badge, flight_badge=flight_badge,
                status_text=status_text, diag_text=diag, 
                api_down=s.api_down, api_down_pending=api_down_pending,
                on_ground=on_ground, landed_flash=landed_flash, 
                zones=zone_display_list, 
                friendly_airfield=friendly_airfield_display, 
                enemy_airfields=enemy_airfields_display, 
                has_airfield_target=has_airfield_target, 
                has_target=has_target,
                is_deviating=nav.is_deviating, 
                deviation_angle=deviation_angle, 
                zone_destroyed_alert=zone_destroyed_alert,
                destroyed_zone_count=destroyed_count, 
                destroyed_zone_text=destroyed_zone_text, 
                player_heading=nav.player_heading,
            )

    def _start_new_life_locked(self, now: float):
        """开始新的生命（必须在锁内调用）"""
        s = self.state
        next_index = 1 if not s.current_life else (s.current_life.life_index + 1)
        s.current_life = LifeState(spawn_time=now, life_index=next_index)
        s.sortie_id += 1
        s.last_refit_ts = now

    def _reset_life_state_locked(self):
        """重置生命状态（必须在锁内调用）"""
        s = self.state
        s.current_life = None
        s.sortie_id = 0
        s.last_refit_ts = 0.0
        s.spawn_candidate_since = None
        s.missing_player_since = None
        s.landing_start_time = None
        s.landed_flash_until = 0.0
        s.zone_nav = ZoneNavigationState()
        s.map_info = None

    def _clear_transient_state_locked(self):
        """清除瞬态状态（必须在锁内调用）"""
        s = self.state
        s.spawn_candidate_since = None
        s.missing_player_since = None
        s.landing_start_time = None
        s.landed_flash_until = 0.0

    def _update_landing_locked(self, tel: TelemetryData, now: float):
        """更新着陆状态（必须在锁内调用）
        
        着陆判断：低速3秒 → 触发"就绪"闪烁10秒
        """
        s = self.state
        if not s.current_life:
            return
        
        if tel.is_on_ground:
            if s.landing_start_time is None:
                s.landing_start_time = now
            elif (now - s.landing_start_time) >= GameConfig.LAND_CONFIRM_SEC:
                if s.landed_flash_until <= now:
                    s.landed_flash_until = now + GameConfig.LANDED_FLASH_SEC
        else:
            s.landing_start_time = None


# ============================================================================
# UI组件
# ============================================================================

class Corner(Enum):
    """窗口角落位置枚举"""
    TOP_RIGHT = 0
    TOP_LEFT = 1
    BOTTOM_RIGHT = 2
    BOTTOM_LEFT = 3


class Pill(tk.Label):
    """徽章组件（圆角矩形标签）
    
    用于显示状态徽章，如"战斗中"、"就绪✓"等。
    """
    def __init__(self, parent, text="", fg=Theme.TEXT, bg=Theme.GRAYPILL, font=None):
        super().__init__(parent, text=text, fg=fg, bg=bg, bd=0, highlightthickness=0)
        if font:
            self.configure(font=font)
        self._apply_padding(text)
    
    def _apply_padding(self, text: str):
        """添加内边距（通过空格）"""
        self.configure(text=f"  {text}  ")
    
    def set(self, text: str, fg: str, bg: str):
        """更新徽章内容和颜色"""
        self.configure(fg=fg, bg=bg)
        self._apply_padding(text)


class SettingsDialog(tk.Toplevel):
    """设置对话框
    
    提供透明度、缩放、热键等配置选项。
    """
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.title("设置")
        self.resizable(False, False)
        self.configure(bg=Theme.BG)
        self.transient(parent)
        self.grab_set()
        self._build_ui()
        self._center_on_parent(parent)
    
    def _build_ui(self):
        main = tk.Frame(self, bg=Theme.BG)
        main.pack(padx=20, pady=15)
        
        # 透明度滑块
        tk.Label(main, text="窗口透明度:", bg=Theme.BG, fg=Theme.TEXT).grid(row=0, column=0, sticky="w", pady=5)
        self.alpha_var = tk.IntVar(value=UIConfig.WINDOW_ALPHA)
        tk.Scale(main, from_=100, to=255, orient="horizontal", length=200, variable=self.alpha_var, 
                 bg=Theme.BG, fg=Theme.TEXT, highlightthickness=0, 
                 troughcolor=Theme.BORDER, activebackground=Theme.BLUE).grid(row=0, column=1, padx=10, pady=5)
        
        # 缩放滑块
        tk.Label(main, text="UI缩放:", bg=Theme.BG, fg=Theme.TEXT).grid(row=1, column=0, sticky="w", pady=5)
        self.scale_var = tk.DoubleVar(value=UIConfig.UI_SCALE_MULT)
        tk.Scale(main, from_=0.6, to=1.2, resolution=0.05, orient="horizontal", length=200, 
                 variable=self.scale_var, bg=Theme.BG, fg=Theme.TEXT, highlightthickness=0, 
                 troughcolor=Theme.BORDER, activebackground=Theme.BLUE).grid(row=1, column=1, padx=10, pady=5)
        
        # 热键开关
        tk.Label(main, text="全局热键:", bg=Theme.BG, fg=Theme.TEXT).grid(row=2, column=0, sticky="w", pady=5)
        self.hotkeys_var = tk.BooleanVar(value=HotkeyConfig.GLOBAL_HOTKEYS)
        tk.Checkbutton(main, text="启用", variable=self.hotkeys_var, 
                      bg=Theme.BG, fg=Theme.TEXT, selectcolor=Theme.GRAYPILL, 
                      activebackground=Theme.BG, activeforeground=Theme.TEXT, 
                      highlightthickness=0).grid(row=2, column=1, sticky="w", padx=10, pady=5)
        
        # 按钮行
        btn_frame = tk.Frame(main, bg=Theme.BG)
        btn_frame.grid(row=3, column=0, columnspan=2, pady=(15, 0))
        tk.Button(btn_frame, text="保存", command=self._save, 
                 bg=Theme.BLUE, fg=Theme.TEXT, bd=0, padx=20, pady=5).pack(side="left", padx=5)
        tk.Button(btn_frame, text="取消", command=self.destroy, 
                 bg=Theme.GRAYPILL, fg=Theme.TEXT, bd=0, padx=20, pady=5).pack(side="left", padx=5)
    
    def _center_on_parent(self, parent):
        """居中显示"""
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_y() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")
    
    def _save(self):
        """保存设置"""
        UIConfig.WINDOW_ALPHA = self.alpha_var.get()
        UIConfig.UI_SCALE_MULT = self.scale_var.get()
        old_hotkeys = HotkeyConfig.GLOBAL_HOTKEYS
        HotkeyConfig.GLOBAL_HOTKEYS = self.hotkeys_var.get()
        
        config = ConfigManager.load()
        config['alpha'] = UIConfig.WINDOW_ALPHA
        config['scale'] = UIConfig.UI_SCALE_MULT
        config['global_hotkeys'] = HotkeyConfig.GLOBAL_HOTKEYS
        ConfigManager.save(config)
        
        # 应用透明度
        Win32.setup_window(self.app.hwnd, self.app._locked, UIConfig.WINDOW_ALPHA)
        
        # 重启热键（如果设置改变）
        if old_hotkeys != HotkeyConfig.GLOBAL_HOTKEYS:
            if hasattr(self.app, '_ghk') and self.app._ghk:
                self.app._ghk.stop()
            if HotkeyConfig.GLOBAL_HOTKEYS:
                self.app._init_global_hotkeys()
                if hasattr(self.app, '_ghk') and self.app._ghk:
                    self.app._ghk.start()
        
        messagebox.showinfo("设置", "设置已保存\n部分更改需要重启生效", parent=self)
        self.destroy()


class ChecklistEditor(tk.Toplevel):
    """检查清单编辑器
    
    允许用户自定义起飞前的检查项目。
    """
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.title("编辑检查清单")
        self.resizable(False, False)
        self.configure(bg=Theme.BG)
        self.transient(parent)
        self.grab_set()
        self._build_ui()
        self._center_on_parent(parent)
    
    def _build_ui(self):
        main = tk.Frame(self, bg=Theme.BG)
        main.pack(padx=20, pady=15, fill="both", expand=True)
        
        tk.Label(main, text=f"每行一个检查项（最多{ChecklistConfig.MAX_ITEMS}项）:", 
                bg=Theme.BG, fg=Theme.TEXT, anchor="w").pack(fill="x", pady=(0, 5))
        
        self.text = tk.Text(main, width=40, height=10, bg=Theme.GRAYPILL, fg=Theme.TEXT, 
                           insertbackground=Theme.TEXT, bd=0, highlightthickness=1, 
                           highlightbackground=Theme.BORDER)
        self.text.pack(fill="both", expand=True)
        
        current_items = "\n".join(self.app.chk_items)
        self.text.insert("1.0", current_items)
        
        btn_frame = tk.Frame(main, bg=Theme.BG)
        btn_frame.pack(pady=(10, 0))
        tk.Button(btn_frame, text="保存", command=self._save, 
                 bg=Theme.BLUE, fg=Theme.TEXT, bd=0, padx=20, pady=5).pack(side="left", padx=5)
        tk.Button(btn_frame, text="恢复默认", command=self._restore_default, 
                 bg=Theme.YELLOW, fg=Theme.TEXT, bd=0, padx=15, pady=5).pack(side="left", padx=5)
        tk.Button(btn_frame, text="取消", command=self.destroy, 
                 bg=Theme.GRAYPILL, fg=Theme.TEXT, bd=0, padx=20, pady=5).pack(side="left", padx=5)
    
    def _center_on_parent(self, parent):
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_y() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")
    
    def _save(self):
        """保存检查清单"""
        content = self.text.get("1.0", "end-1c")
        items = [line.strip() for line in content.split("\n") if line.strip()]
        
        if not items:
            messagebox.showwarning("警告", "检查清单不能为空", parent=self)
            return
        if len(items) > ChecklistConfig.MAX_ITEMS:
            messagebox.showwarning("警告", f"检查项数量不能超过{ChecklistConfig.MAX_ITEMS}个", parent=self)
            return
        
        config = ConfigManager.load()
        config['checklist_items'] = items
        ConfigManager.save(config)
        self.app.chk_items = items
        self.app._rebuild_checklist()
        
        messagebox.showinfo("成功", "检查清单已保存", parent=self)
        self.destroy()
    
    def _restore_default(self):
        """恢复默认清单"""
        self.text.delete("1.0", "end")
        self.text.insert("1.0", "\n".join(ChecklistConfig.DEFAULT_ITEMS))


# ============================================================================
# 音效管理
# ============================================================================

class SoundManager:
    """音效管理器
    
    使用Windows Beep API播放提示音。
    在独立线程播放，避免阻塞UI。
    """
    def __init__(self):
        self._lock = threading.Lock()
        self._enabled = False
    
    def set_enabled(self, enabled: bool):
        self._enabled = enabled
    
    def is_enabled(self) -> bool:
        return self._enabled
    
    def play(self, pattern: str = "tick", freq: int = None, duration: int = None):
        """播放音效
        
        Args:
            pattern: 音效模式（"tick", "warning", "on", "zone_destroyed"）
            freq: 直接指定频率（Hz）
            duration: 直接指定持续时间（ms）
        """
        # "on"模式总是播放（用于功能开启反馈）
        if not self._enabled and pattern != "on":
            return
        
        # 防止多个音效重叠
        if not self._lock.acquire(blocking=False):
            return
        
        try:
            if freq is not None and duration is not None:
                # 单音播放
                def _play_single():
                    try:
                        ctypes.windll.kernel32.Beep(int(freq), int(duration))
                    except:
                        pass
                    finally:
                        self._lock.release()
                threading.Thread(target=_play_single, daemon=True).start()
                return
            
            # 序列播放
            seq = self._get_pattern_sequence(pattern)
            def _play():
                try:
                    for (f, ms, gap) in seq:
                        try:
                            ctypes.windll.kernel32.Beep(int(f), int(ms))
                        except:
                            pass
                        if gap:
                            time.sleep(gap / 1000.0)
                finally:
                    self._lock.release()
            threading.Thread(target=_play, daemon=True).start()
        except Exception:
            self._lock.release()
            raise
    
    @staticmethod
    def _get_pattern_sequence(pattern: str) -> List[Tuple[int, int, int]]:
        """获取音效序列
        
        Returns:
            [(频率, 持续时间, 间隔), ...]
        """
        if pattern == "on":
            return [(*SoundConfig.BEEP_ON_1, SoundConfig.ON_GAP_MS), 
                   (*SoundConfig.BEEP_ON_2, 0)]
        elif pattern == "warning":
            return [(*SoundConfig.BEEP_WARNING_1, SoundConfig.WARNING_GAP_MS), 
                   (*SoundConfig.BEEP_WARNING_2, 0)]
        elif pattern == "zone_destroyed":
            return [(*SoundConfig.BEEP_ZONE_DESTROYED, 50), 
                   (*SoundConfig.BEEP_ZONE_DESTROYED, 0)]
        else:  # "tick"
            return [(*SoundConfig.BEEP_TICK, 0)]


# ============================================================================
# 主应用类
# ============================================================================

class App:
    """主应用类
    
    职责：
    1. 创建和管理UI窗口
    2. 启动游戏逻辑线程
    3. 处理用户交互（热键、拖动、菜单）
    4. 刷新UI显示（20fps）
    
    架构：
    - UI线程：tkinter主循环
    - 逻辑线程：GameLogic.tick()循环（250ms）
    - 通过UISnapshot传递数据（无锁读取）
    """
    
    def __init__(self, root: tk.Tk):
        self.root = root
        self.game = GameLogic()
        self.sound = SoundManager()
        
        # 控制标志
        self._stop = False
        self._corner = Corner.TOP_RIGHT
        self._locked = True
        self._debug = False
        self._last_beep_sec = -1
        self._zone_sound_enabled = True

        # 窗口状态
        self._user_moved = False
        self._manual_pos = None
        self._last_sortie_id = -1
        self._restored_state = False
        self._last_zone_destroyed_alert = False
        
        # 布局可见性
        self._zone_panel_visible = False
        self._checklist_panel_visible = False

        # 初始化流程
        self._load_config()
        self._init_window_base()
        self._init_ui()
        self._finalize_window_geometry_and_styles()
        self._init_bindings()
        self._init_global_hotkeys()

        # 恢复状态并启动
        self._restored_state = self.game.restore_timer_state()
        threading.Thread(target=self._poll_loop, daemon=True).start()
        self._update_ui()

        if HAS_TRAY:
            self._init_tray()

    def _load_config(self):
        """加载用户配置"""
        config = ConfigManager.load()
        UIConfig.WINDOW_ALPHA = config.get('alpha', UIConfig.WINDOW_ALPHA)
        UIConfig.UI_SCALE_MULT = config.get('scale', UIConfig.UI_SCALE_MULT)
        HotkeyConfig.GLOBAL_HOTKEYS = config.get('global_hotkeys', HotkeyConfig.GLOBAL_HOTKEYS)
        self.chk_items = config.get('checklist_items', ChecklistConfig.DEFAULT_ITEMS.copy())
        self._zone_sound_enabled = config.get('zone_sound_enabled', True)
        
        # 恢复窗口位置
        saved_pos = config.get('window_position')
        if saved_pos and isinstance(saved_pos, dict):
            corner_name = saved_pos.get('corner')
            if corner_name:
                try:
                    self._corner = Corner[corner_name]
                except KeyError:
                    pass
            manual_pos = saved_pos.get('manual_pos')
            if manual_pos and isinstance(manual_pos, list) and len(manual_pos) == 2:
                self._manual_pos = tuple(manual_pos)
                self._user_moved = saved_pos.get('user_moved', False)
        
        beep_enabled = config.get('beep_enabled', False)
        self.sound.set_enabled(beep_enabled)

    def _save_config(self):
        """保存用户配置"""
        config = ConfigManager.load()
        config['alpha'] = UIConfig.WINDOW_ALPHA
        config['scale'] = UIConfig.UI_SCALE_MULT
        config['global_hotkeys'] = HotkeyConfig.GLOBAL_HOTKEYS
        config['checklist_items'] = self.chk_items
        config['beep_enabled'] = self.sound.is_enabled()
        config['zone_sound_enabled'] = self._zone_sound_enabled
        config['window_position'] = {
            'corner': self._corner.name,
            'manual_pos': list(self._manual_pos) if self._manual_pos else None,
            'user_moved': self._user_moved
        }
        ConfigManager.save(config)

    def _init_window_base(self):
        """初始化窗口基础设置"""
        self.root.title("WT Timer")
        
        # 加载图标
        try:
            p = resource_path(FileConfig.ICON_FILE)
            self._tk_icon = tk.PhotoImage(file=p)
            self.root.iconphoto(True, self._tk_icon)
        except (tk.TclError, FileNotFoundError):
            pass
        
        # 无边框窗口
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg=Theme.BG)
        
        # 临时几何（真实尺寸在UI创建后计算）
        self.root.geometry("10x10+0+0")
        self.root.update_idletasks()
        
        # 获取窗口句柄和DPI缩放
        self.hwnd = int(self.root.winfo_id())
        self.scale = Win32.get_dpi_scale(self.hwnd) * float(UIConfig.UI_SCALE_MULT)
        
        try:
            self.root.tk.call("tk", "scaling", float(self.scale))
        except tk.TclError:
            pass

    def _finalize_window_geometry_and_styles(self):
        """最终确定窗口几何和样式"""
        self.root.update_idletasks()
        req_w = self.root.winfo_reqwidth()
        req_h = self.root.winfo_reqheight()
        pad = int(UIConfig.WINDOW_PADDING * self.scale)
        self.W = req_w + pad
        self.H = req_h + pad
        self._position()
        self.root.update_idletasks()
        Win32.setup_window(self.hwnd, click_through=True, alpha=UIConfig.WINDOW_ALPHA)

    def _init_ui(self):
        """初始化UI布局
        
        结构：
        - main_frame: 主容器
          - bottom_frame: 底部（提示/调试）
          - top_frame: 顶部（计时器/徽章/进度条）
          - mid_frame: 中部（战区/检查清单）
        """
        s = self.scale
        self.main_frame = tk.Frame(self.root, bg=Theme.BG)
        pad_x, pad_y = UIConfig.PADDING_MAIN
        self.main_frame.pack(fill="both", expand=True, padx=int(pad_x*s), pady=int(pad_y*s))

        # === 底部区域 ===
        bottom_frame = tk.Frame(self.main_frame, bg=Theme.BG)
        bottom_frame.pack(side="bottom", fill="x")

        font_hint = (UIConfig.FONT_HINT[0], int(UIConfig.FONT_HINT[1]*s))
        self.hint_lbl = tk.Label(
            bottom_frame, text=self._hint_text(),
            font=font_hint, fg=Theme.TEXT_MUTED, bg=Theme.BG
        )
        self.hint_lbl.pack(side="bottom", fill="x")

        font_debug = (UIConfig.FONT_DEBUG[0], int(UIConfig.FONT_DEBUG[1]*s))
        self.diag_lbl = tk.Label(
            bottom_frame, text="",
            font=font_debug, fg=Theme.TEXT_MUTED, bg=Theme.BG, 
            anchor="w", justify="left",
            wraplength=int(UIConfig.DEBUG_WRAP_LENGTH*s)
        )

        # === 顶部区域 ===
        self.top_frame = tk.Frame(self.main_frame, bg=Theme.BG)
        self.top_frame.pack(side="top", fill="x")

        # 第一行：计时器
        row1 = tk.Frame(self.top_frame, bg=Theme.BG)
        row1.pack(fill="x")
        font_timer = (UIConfig.FONT_TIMER[0], int(UIConfig.FONT_TIMER[1]*s), UIConfig.FONT_TIMER[2])
        self.timer_lbl = tk.Label(row1, text="--:--", font=font_timer, fg=Theme.TEXT_MUTED, bg=Theme.BG, anchor="w")
        self.timer_lbl.pack(side="left")
        
        # 右侧信息
        right = tk.Frame(row1, bg=Theme.BG)
        right.pack(side="right", padx=(int(14*s), 0))
        font_life = (UIConfig.FONT_LIFE[0], int(UIConfig.FONT_LIFE[1]*s), UIConfig.FONT_LIFE[2])
        self.life_lbl = tk.Label(right, text="未复活", font=font_life, fg=Theme.BLUE, bg=Theme.BG, anchor="e")
        self.life_lbl.pack(anchor="e")
        font_cycle = (UIConfig.FONT_CYCLE[0], int(UIConfig.FONT_CYCLE[1]*s))
        self.cycle_lbl = tk.Label(right, text="未开始", font=font_cycle, fg=Theme.TEXT_DIM, bg=Theme.BG, anchor="e")
        self.cycle_lbl.pack(anchor="e", pady=(int(2*s), 0))

        # 第二行：徽章
        row2 = tk.Frame(self.top_frame, bg=Theme.BG)
        pad_top, pad_bot = UIConfig.PADDING_ROW2
        row2.pack(fill="x", pady=(int(pad_top*s), int(pad_bot*s)))
        pill_font = (UIConfig.FONT_PILL[0], int(UIConfig.FONT_PILL[1]*s), UIConfig.FONT_PILL[2])
        self.badge_main = Pill(row2, text="IDLE", fg=Theme.TEXT, bg=Theme.GRAYPILL, font=pill_font)
        self.badge_main.pack(side="left")
        self.badge_flight = Pill(row2, text="—", fg=Theme.TEXT_DIM, bg=Theme.GRAYPILL, font=pill_font)
        self.badge_flight.pack(side="left", padx=(int(UIConfig.SPACING_BADGE*s), 0))
        font_status = (UIConfig.FONT_STATUS[0], int(UIConfig.FONT_STATUS[1]*s))
        self.status_txt = tk.Label(row2, text="等待中", font=font_status, fg=Theme.TEXT_DIM, bg=Theme.BG, anchor="e")
        self.status_txt.pack(side="right")

        # 进度条
        bar_height = int(UIConfig.PROGRESS_BAR_HEIGHT * s)
        bar_frame = tk.Frame(self.top_frame, bg=Theme.BG, height=bar_height)
        pad_top, pad_bot = UIConfig.PADDING_PROGRESS
        bar_frame.pack(fill="x", pady=(int(pad_top*s), int(pad_bot*s)))
        bar_frame.pack_propagate(False)
        bar_thickness = int(UIConfig.PROGRESS_BAR_THICKNESS * s)
        self.bar_bg = tk.Frame(bar_frame, bg=Theme.BORDER, height=bar_thickness)
        self.bar_bg.place(relx=0, rely=0.5, relwidth=1, anchor="w")
        self.bar_fill = tk.Frame(self.bar_bg, bg=Theme.BLUE, height=bar_thickness)
        self.bar_fill.place(relx=0, rely=0, relwidth=0, relheight=1)

        # === 中间内容区域 ===
        self.mid_frame = tk.Frame(self.main_frame, bg=Theme.BG)
        self.mid_frame.pack(side="top", fill="x", pady=(0, int(8*s)))
        self.mid_frame.columnconfigure(0, weight=1)
        self.mid_frame.columnconfigure(1, weight=1)

        # 战区导航框架
        self.zone_frame = tk.Frame(self.mid_frame, bg=Theme.GRAYPILL, bd=0, highlightthickness=0)
        self._init_zone_ui()

        # 检查清单框架
        self.chk_frame = tk.Frame(self.mid_frame, bg=Theme.GRAYPILL, bd=0, highlightthickness=0)
        self.chk_border_frame = tk.Frame(self.chk_frame, bg=Theme.SEPARATOR, width=1)
        self.chk_content_frame = tk.Frame(self.chk_frame, bg=Theme.GRAYPILL)
        self._rebuild_checklist()

    def _init_zone_ui(self):
        """初始化战区导航UI"""
        s = self.scale
        
        # 标题栏
        title_frame = tk.Frame(self.zone_frame, bg=Theme.GRAYPILL)
        title_frame.pack(fill="x", padx=int(8*s), pady=(int(6*s), int(2*s)))
        
        font_title = (UIConfig.FONT_ZONE_TITLE[0], int(UIConfig.FONT_ZONE_TITLE[1]*s), UIConfig.FONT_ZONE_TITLE[2])
        self.zone_title = tk.Label(title_frame, text="🎯 战区导航", font=font_title, fg=Theme.TEXT, bg=Theme.GRAYPILL, anchor="w")
        self.zone_title.pack(side="left")
        
        font_heading = (UIConfig.FONT_ZONE_ITEM[0], int(UIConfig.FONT_ZONE_ITEM[1]*s))
        self.heading_lbl = tk.Label(title_frame, text="HDG: ---", font=font_heading, fg=Theme.TEXT_DIM, bg=Theme.GRAYPILL, anchor="e")
        self.heading_lbl.pack(side="right")
        
        # 被摧毁警告标签
        font_alert = (UIConfig.FONT_ZONE_TITLE[0], int(UIConfig.FONT_ZONE_TITLE[1]*s), UIConfig.FONT_ZONE_TITLE[2])
        self.zone_alert_lbl = tk.Label(self.zone_frame, text="", font=font_alert, fg=Theme.RED, bg=Theme.GRAYPILL, anchor="w")
        
        # 战区列表容器
        self.zone_list_frame = tk.Frame(self.zone_frame, bg=Theme.GRAYPILL)
        self.zone_list_frame.pack(fill="x", padx=int(8*s), pady=(0, int(10*s)))
        self.zone_labels: List[tk.Label] = []

        # 机场导航
        self.airport_title_lbl = tk.Label(self.zone_frame, text="🛫 机场导航", font=font_title, fg=Theme.TEXT, bg=Theme.GRAYPILL, anchor="w")
        self.airport_title_lbl.pack(fill="x", padx=int(8*s), pady=(0, int(2*s)))

        self.airport_list_frame = tk.Frame(self.zone_frame, bg=Theme.GRAYPILL)
        self.airport_list_frame.pack(fill="x", padx=int(8*s), pady=(0, int(10*s)))
        self.airport_labels: List[tk.Label] = []

    def _rebuild_checklist(self):
        """重建检查清单UI（纯展示模式）"""
        for widget in self.chk_content_frame.winfo_children(): 
            widget.destroy()
        
        s = self.scale
        
        self.chk_border_frame.pack(side="left", fill="y", padx=(0, 2))
        self.chk_content_frame.pack(side="left", fill="both", expand=True)

        font_title = (UIConfig.FONT_CHECKLIST_TITLE[0], int(UIConfig.FONT_CHECKLIST_TITLE[1]*s), UIConfig.FONT_CHECKLIST_TITLE[2])
        self.chk_title = tk.Label(self.chk_content_frame, text="✅ 出击检查", font=font_title, fg=Theme.TEXT, bg=Theme.GRAYPILL, anchor="w")
        self.chk_title.pack(fill="x", padx=int(6*s), pady=(int(6*s), int(2*s)))

        font_item = (UIConfig.FONT_CHECKLIST_ITEM[0], int(UIConfig.FONT_CHECKLIST_ITEM[1]*s))
        pad_x = int(6*s)
        wrap_width = int(140*s)
        
        # 使用 Label + ○ 符号（纯展示，无交互）
        for item in self.chk_items:
            lbl = tk.Label(
                self.chk_content_frame, 
                text=f"○ {item}",
                font=font_item, 
                fg=Theme.TEXT_DIM, 
                bg=Theme.GRAYPILL, 
                anchor="w", 
                justify="left",
                wraplength=wrap_width
            )
            lbl.pack(fill="x", padx=(pad_x, pad_x), pady=1, anchor="w")

    def _init_bindings(self):
        """初始化键盘/鼠标绑定"""
        # 键盘快捷键
        self.root.bind("<Escape>", lambda e: self._quit())
        self.root.bind("<F7>", lambda e: self._manual_reset())
        self.root.bind("<F8>", lambda e: self._toggle_lock())
        self.root.bind("<F9>", lambda e: self._next_corner())
        self.root.bind("<F10>", lambda e: self._toggle_beep())
        self.root.bind("<F11>", lambda e: self._toggle_zone_sound())
        self.root.bind("<Control-MouseWheel>", self._adjust_alpha)
        
        # 拖动相关
        self._drag = {"x": 0, "y": 0}
        self.root.bind("<Button-1>", self._start_drag)
        self.root.bind("<B1-Motion>", self._do_drag)
        self.root.bind("<ButtonRelease-1>", self._end_drag)
        
        # 右键菜单
        self.root.bind("<Button-3>", self._show_context_menu)
        self.context_menu = tk.Menu(self.root, tearoff=0, bg=Theme.GRAYPILL, fg=Theme.TEXT)
        self.context_menu.add_command(label="🔄 重置计时器 (F7)", command=self._manual_reset)
        self.context_menu.add_command(label="🔓 锁定/解锁 (F8)", command=self._toggle_lock)
        self.context_menu.add_command(label="📍 切换角落 (F9)", command=self._next_corner)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="🔔 战区提示音 (F11)", command=self._toggle_zone_sound)
        self.context_menu.add_command(label="📝 编辑检查清单", command=self._edit_checklist)
        self.context_menu.add_command(label="⚙️ 设置", command=self._show_settings)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="❌ 退出", command=self._quit)

    def _init_global_hotkeys(self):
        """初始化全局热键"""
        self._ghk = None
        if not os.name == "nt" or not HotkeyConfig.GLOBAL_HOTKEYS:
            return
        
        hotkeys = [
            (HotkeyConfig.HK_ID_RESET, HotkeyConfig.VK_F7, self._manual_reset),
            (HotkeyConfig.HK_ID_LOCK, HotkeyConfig.VK_F8, self._toggle_lock),
            (HotkeyConfig.HK_ID_CORNER, HotkeyConfig.VK_F9, self._next_corner),
            (HotkeyConfig.HK_ID_BEEP, HotkeyConfig.VK_F10, self._toggle_beep),
            (HotkeyConfig.HK_ID_ZONES, HotkeyConfig.VK_F11, self._toggle_zone_sound),
        ]
        self._ghk = GlobalHotkeys(self.root, hotkeys)
        self._ghk.start()

    def _init_tray(self):
        """初始化系统托盘"""
        def icon():
            try:
                return Image.open(resource_path(FileConfig.ICON_FILE)).convert("RGBA")
            except:
                return Image.new('RGBA', (64, 64), Theme.BLUE)
        
        def toggle_debug(icon, item):
            self.root.after(0, self._toggle_debug)
        
        def is_debug_checked(item):
            return self._debug
        
        menu = pystray.Menu(
            pystray.MenuItem("Debug模式", toggle_debug, checked=is_debug_checked),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("显示", lambda: self.root.after(0, self._show)),
            pystray.MenuItem("退出", lambda: self.root.after(0, self._quit)),
        )
        self.tray = pystray.Icon("WTTimer", icon(), "WT Timer", menu)
        threading.Thread(target=self.tray.run, daemon=True).start()

    def _toggle_debug(self):
        """切换调试模式"""
        self._debug = not self._debug
        if self._debug:
            self.diag_lbl.pack(side="bottom", fill="x", pady=(0, int(UIConfig.SPACING_DEBUG*self.scale)), before=self.hint_lbl)
        else:
            self.diag_lbl.pack_forget()
        self._recalc_size()

    def _toggle_zone_sound(self):
        """切换战区提示音"""
        self._zone_sound_enabled = not self._zone_sound_enabled
        self._update_hint()
        self._save_config()
        if self._zone_sound_enabled:
            self.sound.play(pattern="on")

    def _recalc_size(self, keep_pos: bool = True, force_shrink: bool = False):
        """重新计算窗口尺寸
        
        策略：
        - 扩展：立即响应
        - 收缩：保守处理（避免抖动）
        
        Args:
            keep_pos: 保持窗口位置
            force_shrink: 强制收缩（隐藏面板时）
        """
        try:
            old_x = self.root.winfo_x()
            old_y = self.root.winfo_y()
            old_w = self.root.winfo_width()
            old_h = self.root.winfo_height()
        except tk.TclError:
            old_x, old_y, old_w, old_h = 0, 0, 0, 0
        
        # 强制刷新布局
        self.root.update_idletasks()
        
        # 读取实际需要的尺寸
        req_w = self.main_frame.winfo_reqwidth()
        req_h = self.main_frame.winfo_reqheight()
        
        pad = int(UIConfig.WINDOW_PADDING * self.scale)
        
        # 根据面板可见性设置最小宽度
        if self._zone_panel_visible and self._checklist_panel_visible:
            min_width = int(480 * self.scale)
        else:
            min_width = int(280 * self.scale)
        
        new_w = max(min_width, req_w + pad)
        new_h = req_h + pad + int(8 * self.scale)
        
        # 高度收缩策略：避免频繁抖动
        if new_h < old_h:
            if not force_shrink and (old_h - new_h) < 30:
                new_h = old_h
        
        if new_w == old_w and new_h == old_h:
            return
        
        self.W = new_w
        self.H = new_h

        if keep_pos:
            if self._user_moved and self._manual_pos:
                x, y = self._manual_pos
            elif (old_x, old_y) != (0, 0):
                x, y = old_x, old_y
            else:
                self._position()
                return
            self.root.geometry(f"{self.W}x{self.H}+{x}+{y}")
        else:
            self._position()

    def _show(self):
        """显示窗口"""
        try:
            self.root.deiconify()
            self.root.lift()
        except tk.TclError:
            pass

    def _position(self):
        """定位窗口到指定角落"""
        sw, sh = Win32.screen_size()
        m = int(UIConfig.WINDOW_MARGIN * self.scale)
        pos = {
            Corner.TOP_RIGHT: (sw - self.W - m, m),
            Corner.TOP_LEFT: (m, m),
            Corner.BOTTOM_RIGHT: (sw - self.W - m, sh - self.H - m),
            Corner.BOTTOM_LEFT: (m, sh - self.H - m),
        }
        if self._user_moved and self._manual_pos:
            x, y = self._manual_pos
        else:
            x, y = pos[self._corner]
        self.root.geometry(f"{self.W}x{self.H}+{x}+{y}")

    def _toggle_lock(self):
        """切换锁定/解锁"""
        self._locked = not self._locked
        Win32.setup_window(self.hwnd, click_through=self._locked, alpha=UIConfig.WINDOW_ALPHA)
        self._update_hint()

    def _hint_text(self) -> str:
        """生成提示文本"""
        sound = "🔊开" if self.sound.is_enabled() else "🔇关"
        zone_sound = "🔔开" if self._zone_sound_enabled else "🔕关"
        if self._locked:
            return f"F7重置 │ F8解锁 │ F9角落 │ F10声音({sound}) │ F11战区({zone_sound})"
        else:
            return f"拖动移动 │ F8锁定 │ F10声音({sound}) │ F11战区({zone_sound}) │ 右键菜单"

    def _update_hint(self) -> None:
        """更新提示文本"""
        if hasattr(self, "hint_lbl") and self.hint_lbl:
            self.hint_lbl.config(text=self._hint_text())

    def _next_corner(self):
        """切换到下一个角落"""
        corners = list(Corner)
        i = (corners.index(self._corner) + 1) % len(corners)
        self._corner = corners[i]
        self._user_moved = False
        self._manual_pos = None
        self._position()
        self._save_config()

    def _toggle_beep(self):
        """切换提示音"""
        enabled = not self.sound.is_enabled()
        self.sound.set_enabled(enabled)
        self._update_hint()
        self._save_config()
        if enabled:
            self.sound.play(pattern="on")

    def _manual_reset(self):
        """手动重置计时器（F7）"""
        self.game.manual_reset()
        self.sound.play(*SoundConfig.BEEP_MANUAL_RESET)

    def _show_settings(self):
        """显示设置对话框"""
        if not self._locked:
            SettingsDialog(self.root, self)

    def _edit_checklist(self):
        """编辑检查清单"""
        if not self._locked:
            ChecklistEditor(self.root, self)

    def _show_context_menu(self, event):
        """显示右键菜单"""
        if not self._locked:
            try:
                self.context_menu.tk_popup(event.x_root, event.y_root)
            finally:
                self.context_menu.grab_release()

    def _adjust_alpha(self, event):
        """Ctrl+滚轮调整透明度"""
        if not self._locked:
            delta = 10 if event.delta > 0 else -10
            UIConfig.WINDOW_ALPHA = max(100, min(255, UIConfig.WINDOW_ALPHA + delta))
            Win32.setup_window(self.hwnd, click_through=False, alpha=UIConfig.WINDOW_ALPHA)
            self._save_config()

    def _quit(self):
        """退出应用"""
        self._stop = True
        self.game.save_timer_state()
        self._save_config()
        
        try:
            if getattr(self, "_ghk", None):
                self._ghk.stop()
        except:
            pass
        
        if HAS_TRAY and hasattr(self, "tray"):
            try:
                self.tray.stop()
            except:
                pass
        
        SingleInstanceManager.release()
        self.root.destroy()

    def _start_drag(self, e):
        """开始拖动"""
        if self._locked:
            return
        self._drag["x"] = e.x
        self._drag["y"] = e.y

    def _do_drag(self, e):
        """拖动中"""
        if self._locked:
            return
        x = self.root.winfo_pointerx() - self._drag["x"]
        y = self.root.winfo_pointery() - self._drag["y"]
        self.root.geometry(f"+{x}+{y}")

    def _end_drag(self, e=None):
        """结束拖动"""
        if self._locked:
            return
        try:
            self._manual_pos = (int(self.root.winfo_x()), int(self.root.winfo_y()))
            self._user_moved = True
            self._save_config()
        except tk.TclError:
            pass

    def _poll_loop(self):
        """逻辑轮询循环（独立线程）"""
        while not self._stop:
            loop_start = time.monotonic()
            self.game.tick()
            snap = self.game.snapshot()
            interval = NetworkConfig.BACKOFF_MAX if snap.api_down else NetworkConfig.POLL_INTERVAL
            elapsed = time.monotonic() - loop_start
            time.sleep(max(0.0, interval - elapsed))

    def _update_mid_panel_layout(self):
        """更新中间面板布局（战区/检查清单）"""
        self.zone_frame.grid_forget()
        self.chk_frame.grid_forget()
        
        self.mid_frame.rowconfigure(0, weight=1)
        
        if self._zone_panel_visible and self._checklist_panel_visible:
            if not self.mid_frame.winfo_ismapped():
                self.mid_frame.pack(side="top", fill="x", pady=(0, int(8*self.scale)), after=self.top_frame)
            self.zone_frame.grid(row=0, column=0, sticky="new", padx=(0, int(2*self.scale)))
            self.chk_frame.grid(row=0, column=1, sticky="new", padx=(int(2*self.scale), 0))
            if not self.chk_border_frame.winfo_ismapped():
                self.chk_border_frame.pack(side="left", fill="y", padx=(0, 2), before=self.chk_content_frame)
            self._recalc_size()
        elif self._zone_panel_visible:
            if not self.mid_frame.winfo_ismapped():
                self.mid_frame.pack(side="top", fill="x", pady=(0, int(8*self.scale)), after=self.top_frame)
            self.zone_frame.grid(row=0, column=0, columnspan=2, sticky="new")
            self._recalc_size()
        elif self._checklist_panel_visible:
            if not self.mid_frame.winfo_ismapped():
                self.mid_frame.pack(side="top", fill="x", pady=(0, int(8*self.scale)), after=self.top_frame)
            self.chk_frame.grid(row=0, column=0, columnspan=2, sticky="new")
            self.chk_border_frame.pack_forget()
            self._recalc_size()
        else:
            self.mid_frame.pack_forget()
            self._recalc_size(force_shrink=True)

    def _set_zone_panel_visible(self, visible: bool):
        """设置战区面板可见性"""
        if self._zone_panel_visible != visible:
            self._zone_panel_visible = visible
            self._update_mid_panel_layout()

    def _set_checklist_visible(self, visible: bool):
        """设置检查清单可见性"""
        if self._checklist_panel_visible != visible:
            self._checklist_panel_visible = visible
            self._update_mid_panel_layout()

    def _update_zone_display(self, snap: UISnapshot):
        """更新战区显示（根据UISnapshot）"""
        s = self.scale
        
        # 更新航向显示
        if snap.player_heading > 0:
            self.heading_lbl.config(text=f"HDG: {int(snap.player_heading):03d}°")
        else:
            self.heading_lbl.config(text="HDG: ---")
        
        # 战区被摧毁警告
        if snap.zone_destroyed_alert:
            alert_text = "💥 战区被摧毁："
            if getattr(snap, "destroyed_zone_text", ""):
                alert_text += snap.destroyed_zone_text
            else:
                alert_text = "💥 战区已摧毁!"
            wrap = max(int(220*s), self.zone_frame.winfo_width() - int(16*s))
            self.zone_alert_lbl.config(text=alert_text, wraplength=wrap, justify="left")
            if not self.zone_alert_lbl.winfo_ismapped():
                self.zone_alert_lbl.pack(fill="x", padx=int(8*s), pady=(0, int(4*s)), after=self.zone_title.master)
            if not self._last_zone_destroyed_alert and self._zone_sound_enabled:
                self.sound.play(pattern="zone_destroyed")
            self._last_zone_destroyed_alert = True
        else:
            if self.zone_alert_lbl.winfo_ismapped():
                self.zone_alert_lbl.pack_forget()
            self._last_zone_destroyed_alert = False
        
        # 清除旧战区标签
        for lbl in self.zone_labels:
            lbl.destroy()
        self.zone_labels.clear()
        
        font_item = (UIConfig.FONT_ZONE_ITEM[0], int(UIConfig.FONT_ZONE_ITEM[1]*s))
        
        # 无战区时显示提示
        if not snap.zones:
            empty_lbl = tk.Label(self.zone_list_frame, text="无战区", font=font_item, fg=Theme.TEXT_MUTED, bg=Theme.GRAYPILL, anchor="w")
            empty_lbl.pack(fill="x")
            self.zone_labels.append(empty_lbl)
        
        # 显示战区列表
        for zone in snap.zones:
            marker = "➤" if zone.is_target else "○"
            dist_text = f"{zone.distance_km:.1f}km" if zone.distance_km < 10 else f"{int(zone.distance_km)}km"
            rel_sign = "+" if zone.relative > 0 else ""
            rel_text = f"{rel_sign}{int(zone.relative)}°"
            
            text = f"{marker} {zone.direction} {dist_text}  ({rel_text})"
            
            if zone.ete_str:
                text += f"   ⏱️{zone.ete_str}"
            
            fg = Theme.GREEN if zone.is_target and not snap.is_deviating else Theme.ORANGE if zone.is_target else Theme.TEXT_DIM
            
            lbl = tk.Label(self.zone_list_frame, text=text, font=font_item, fg=fg, bg=Theme.GRAYPILL, anchor="w")
            lbl.pack(fill="x")
            self.zone_labels.append(lbl)
        
        # 偏航警告
        if snap.is_deviating and snap.has_target:
            warn_text = f"⚠️ 偏航 ({int(snap.deviation_angle):+d}°)"
            warn_lbl = tk.Label(self.zone_list_frame, text=warn_text, font=font_item, fg=Theme.ORANGE, bg=Theme.GRAYPILL, anchor="w")
            warn_lbl.pack(fill="x", pady=(int(4*s), 0))
            self.zone_labels.append(warn_lbl)

        # === 机场导航显示 ===
        for lbl in getattr(self, "airport_labels", []):
            lbl.destroy()
        if hasattr(self, "airport_labels"):
            self.airport_labels.clear()

        # 友方机场（最近的）
        if snap.friendly_airfield:
            af = snap.friendly_airfield
            dist_text = f"{af.distance_km:.1f}km" if af.distance_km < 10 else f"{int(af.distance_km)}km"
            rel_sign = "+" if af.relative > 0 else ""
            rel_text = f"{rel_sign}{int(af.relative)}°"
            text = f"🟢 ➤ {af.direction} {dist_text}  ({rel_text})"
            if af.ete_str:
                text += f"   ⏱️{af.ete_str}"
            lbl = tk.Label(self.airport_list_frame, text=text, font=font_item, fg=Theme.GREEN, bg=Theme.GRAYPILL, anchor="w")
            lbl.pack(fill="x")
            self.airport_labels.append(lbl)

        # 敌方机场（所有）
        if snap.enemy_airfields:
            for af in snap.enemy_airfields:
                marker = "➤" if af.is_target else "○"
                dist_text = f"{af.distance_km:.1f}km" if af.distance_km < 10 else f"{int(af.distance_km)}km"
                rel_sign = "+" if af.relative > 0 else ""
                rel_text = f"{rel_sign}{int(af.relative)}°"
                text = f"🔴 {marker} {af.direction} {dist_text}  ({rel_text})"
                if af.ete_str:
                    text += f"   ⏱️{af.ete_str}"
                fg = Theme.ORANGE if af.is_target else Theme.TEXT_DIM
                lbl = tk.Label(self.airport_list_frame, text=text, font=font_item, fg=fg, bg=Theme.GRAYPILL, anchor="w")
                lbl.pack(fill="x")
                self.airport_labels.append(lbl)

        if (not snap.friendly_airfield) and (not snap.enemy_airfields):
            empty_lbl = tk.Label(self.airport_list_frame, text="无机场数据", font=font_item, fg=Theme.TEXT_MUTED, bg=Theme.GRAYPILL, anchor="w")
            empty_lbl.pack(fill="x")
            self.airport_labels.append(empty_lbl)

    def _update_ui(self):
        """UI更新循环（20fps）"""
        if self._stop:
            return
        
        snap = self.game.snapshot()

        # 控制面板可见性
        show_zones = (snap.phase == Phase.ALIVE) and (not snap.api_down) and (
            len(snap.zones) > 0 or 
            snap.friendly_airfield is not None or 
            len(snap.enemy_airfields) > 0
        )
        self._set_zone_panel_visible(show_zones)
        if show_zones: 
            self._update_zone_display(snap)
            self._recalc_size()

        show_chk = (snap.phase == Phase.ALIVE) and (snap.on_ground or snap.landed_flash) and (not snap.api_down)
        self._set_checklist_visible(show_chk)

        # 更新计时器显示
        self.timer_lbl.config(text=fmt_time(snap.remaining_sec))
        if snap.remaining_sec is None:
            self.timer_lbl.config(fg=Theme.TEXT_MUTED)
            self.bar_fill.place(relwidth=0)
            self.bar_fill.config(bg=Theme.BLUE)
        else:
            remain = snap.remaining_sec
            color = Theme.RED if remain <= 10 else Theme.YELLOW if remain <= GameConfig.FINAL_WARNING_SEC else Theme.TEXT
            bar = Theme.RED if remain <= 10 else Theme.YELLOW if remain <= GameConfig.FINAL_WARNING_SEC else Theme.BLUE
            self.timer_lbl.config(fg=color)
            self.bar_fill.place(relwidth=snap.progress)
            self.bar_fill.config(bg=bar)
            
            # 播放警告音
            remain_int = int(remain)
            if remain <= GameConfig.FINAL_WARNING_SEC:
                if remain_int in SoundConfig.WARNING_SECONDS and remain_int != self._last_beep_sec:
                    pattern = "warning" if remain_int in SoundConfig.MAJOR_WARNINGS else "tick"
                    self.sound.play(pattern=pattern)
                    self._last_beep_sec = remain_int
            else:
                self._last_beep_sec = -1

        # 更新生命/周期信息
        self.life_lbl.config(text=(f"第{snap.life_index}次复活" if snap.life_index is not None else "未复活"))
        self.cycle_lbl.config(text=(f"第{snap.cycle}轮" if snap.cycle is not None else "未开始"))
        
        # 更新徽章
        self.badge_main.set(*snap.main_badge)
        self.badge_flight.set(*snap.flight_badge)
        self.status_txt.config(text=snap.status_text, fg=(Theme.YELLOW if snap.api_down else Theme.TEXT_DIM))

        # 调试信息
        if self._debug:
            debug_text = snap.diag_text
            if self._restored_state and snap.phase == Phase.ALIVE:
                debug_text += "\n🔄 已从保存状态恢复计时"
            debug_text += f"\n战区: {len(snap.zones)}个"
            if snap.has_target:
                debug_text += f" | 目标偏离: {int(snap.deviation_angle)}°"
            self.diag_lbl.config(text=debug_text)

        # 继续下一帧
        self.root.after(UIConfig.UI_REFRESH_MS, self._update_ui)


# ============================================================================
# 程序入口
# ============================================================================

def main():
    """主函数"""
    # 确保单实例运行
    SingleInstanceManager.ensure_single_instance_or_exit()
    
    # 启用DPI感知
    Win32.enable_dpi()
    
    # 隐藏控制台窗口
    Win32.hide_console()
    
    # 创建主窗口和应用
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()

