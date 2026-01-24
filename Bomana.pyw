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

打包命令：
-------
1. 完整版（所有功能开启）

pyinstaller --noconsole --onefile `
    --name "Bomana" `
    --icon "app.ico" `
    --add-data "app.png;." `
    --add-data "sponsor_wechat.png;." `
    --add-data "ccrp_bomb_params.py;." `
    --hidden-import "pystray._win32" `
    --collect-submodules "PIL" `
    --clean `
    Bomana.pyw

2. Lite精简版（关闭扩展功能）
   修改编译开关:
   ENABLE_CCRP = False
   ENABLE_ZONES = False
   ENABLE_AIRFIELDS = False
   ENABLE_FUEL = False
   ENABLE_CHECKLIST = False

pyinstaller --noconsole --onefile `
    --name "BomanaLite" `
    --icon "app.ico" `
    --add-data "app.png;." `
    --add-data "sponsor_wechat.png;." `
    --hidden-import "pystray._win32" `
    --collect-submodules "PIL" `
    --clean `
    Bomana.pyw

3. 自定义版（按需开启功能）
   根据需要修改编译开关组合，然后打包

===============================================================================
"""

import os
import sys
import json
import time
import math
import ctypes
import threading
import webbrowser
from pathlib import Path
from dataclasses import dataclass, field
from collections import deque
from typing import Optional, Tuple, Any, List, Dict
from enum import Enum, auto

# 尝试导入外部炸弹参数模块（仅在CCRP启用时）
# 注意：ENABLE_CCRP 在后面定义，这里先尝试导入，后续根据开关决定是否使用
try:
    from ccrp_bomb_params import BALLISTIC_PARAMS as CCRP_BOMB_PARAMS
    _CCRP_PARAMS_AVAILABLE = True
except ImportError:
    CCRP_BOMB_PARAMS = {}
    _CCRP_PARAMS_AVAILABLE = False

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
# 编译开关 - 功能模块启用控制
# ============================================================================
# 设置为 False 可在打包时完全移除对应功能，减小体积并简化界面
# 修改后需要重新打包才能生效

ENABLE_CCRP = True           # CCRP投弹预测功能开关
ENABLE_ZONES = True          # 战区导航功能开关
ENABLE_AIRFIELDS = True      # 机场导航功能开关
ENABLE_FUEL = True           # 燃油管理功能开关
ENABLE_CHECKLIST = True      # 出击检查清单功能开关
ENABLE_ADVANCED_SETTINGS = True  # 高级设置功能开关（面板选择、快捷键自定义等）



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
    """战区导航相关配置"""
    
    # CDI(航道偏差指示器)配置
    CDI_WIDTH = 31  # 指示器宽度(字符数,奇数确保中心点) - v6. v6.1提升精度
    
    # 动态容差: (距离上限km, 容差角度°) - 距离越近要求越精确
    # v6.1优化: 针对高空投弹场景，在12km处就开始收紧阈值
    CDI_TOLERANCE_THRESHOLDS = [
        (2.0, 0.5),     # <2km: ±0.5° 极限精准（投弹瞬间）
        (5.0, 1.0),     # <5km: ±1.0° 投弹窗口
        (8.0, 2.0),     # <8km: ±2.0° 精确瞄准
        (12.0, 3.0),    # <12km: ±3.0° 投弹准备（高空投弹关键区间）
        (20.0, 5.0),    # <20km: ±5.0° 接近目标
        (35.0, 8.0),    # <35km: ±8.0° 中距离
        (float('inf'), 12.0)  # >35km: ±12.0° 远距离巡航
    ]
    
    # v6.1新增: 航向带(Heading Tape)配置
    HEADING_TAPE_ENABLED = True           # 是否启用航向带
    HEADING_TAPE_WIDTH = 280              # 航向带宽度(像素)
    HEADING_TAPE_HEIGHT = 32              # 航向带高度(像素)
    HEADING_TAPE_PIXELS_PER_DEG = 8       # 基础缩放: 每度8像素
    HEADING_TAPE_MAX_SCALE = 4.0          # 最大缩放倍数(近距离时)
    HEADING_TAPE_SCALE_START_KM = 15.0    # 开始缩放的距离(km)
    HEADING_TAPE_SCALE_END_KM = 3.0       # 达到最大缩放的距离(km)
    
    # CDI符号定义
    CDI_CENTER = "●"      # 中心指示点
    CDI_TRACK = "━"       # 轨道线
    CDI_LEFT = "◁"        # 左边界
    CDI_RIGHT = "▷"       # 右边界
    CDI_OVERFLOW_LEFT = "◀◀"   # 严重偏左指示
    CDI_OVERFLOW_RIGHT = "▶▶"  # 严重偏右指示
    
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
    
    # v5.7: 目标锁定相关配置
    # 精确对准角度阈值：<5°视为精确对准
    PRECISE_AIM_THRESHOLD = 5
    
    # 精确对准确认时间：持续3秒后切换目标
    PRECISE_AIM_CONFIRM_SEC = 3.0
    
    # 目标保持角度：超过90°视为目标丢失
    TARGET_HOLD_ANGLE = 90
    
    # 敌方机场ETE显示角度：只在<45°时显示ETE
    ENEMY_AIRFIELD_ETE_ANGLE = 45


class FuelConfig:
    """燃油管理相关配置
    
    燃油采样、警告阈值、返航估算参数。
    """
    # 采样参数
    SAMPLE_INTERVAL_SEC = 1.0        # 采样间隔缩短至1秒，使燃油流速计算更灵敏
    SAMPLE_WINDOW_SEC = 60.0         # 历史窗口（秒）
    MIN_STABLE_SAMPLES = 5           # 最少稳定样本数
    
    # 补给检测（油量突增）
    REFUEL_JUMP_KG = 30.0            # 油量增加超过此值视为补给
    
    # 警告阈值（基于百分比）
    WARNING_PERCENT = 30             # 黄色警告阈值
    DANGER_PERCENT = 15              # 红色警告阈值
    
    # 返航安全系数
    RETURN_SAFETY_FACTOR = 1.3       # 返航油量估算的安全系数（30%余量）
    RETURN_WARNING_FACTOR = 1.5      # 低于此倍数时提醒返航
    
    # 显示开关
    SHOW_FUEL_PANEL = True           # 是否显示燃油面板
    SHOW_CONSUMPTION_RATE = True     # 是否显示油耗率
    SHOW_ALTITUDE = True             # 是否显示高度
    
    # 最小飞行速度（低于此速度不计算油耗率）
    MIN_FLIGHT_SPEED_KMH = 50.0


class NetworkConfig:
    """网络请求相关配置
    
    8111接口的超时和轮询参数，影响响应速度和资源占用。
    """
    # 8111接口基础URL（本地回环地址）
    API_BASE = "http://127.0.0.1:8111"
    
    # 连接超时：30ms（针对localhost优化，快速失败防止阻塞）
    API_CONNECT_TIMEOUT = 0.03
    
    # 读取超时：45ms（配合50ms轮询，确保不会跨周期堆积）
    API_READ_TIMEOUT = 0.045
    
    # 单次tick最大网络耗时：300ms
    MAX_TICK_NET_BUDGET = 0.30
    
    # API断线时的轮询间隔：1.25秒（降低CPU占用）
    BACKOFF_MAX = 1.25
    
    # 正常轮询间隔：50ms（20次/秒，与UI刷新频率一致，大幅提升仪表平滑度）
    POLL_INTERVAL = 0.05


class UIConfig:
    """UI显示相关配置
    
    [UI缩放机制]
    - 基础缩放: UI_SCALE_MULT (默认1.0)
    - DPI缩放: 自动根据系统DPI调整
    - 智能缩放: 首次启动时根据屏幕分辨率自动调整
      * 1080p及以下: 1.5x
      * 1440p: 1.2x  
      * 4K及以上: 0.9x
    - 用户可调范围: 0.6-1.5
    
    最终缩放 = DPI缩放 × UI_SCALE_MULT
    """
    # UI缩放倍数：1.0（相对于系统DPI的额外缩放）
    # v5.9.3: 从0.85提升到1.0，让界面在1080p/2k下更清晰
    # 注意：此值可能被智能缩放逻辑覆盖（首次启动时）
    UI_SCALE_MULT = 1.0
    
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
    
    [快捷键自定义]
    - 支持功能键: F1-F12
    - 默认绑定: F7=重置, F8=锁定, F9=角落, F10=声音, F11=战区
    - 可在设置对话框中自定义
    - 注意: 避免与游戏快捷键冲突(F1-F4通常被游戏占用)
    """
    # 功能键VK码映射表
    VK_CODES = {
        "F1": 0x70, "F2": 0x71, "F3": 0x72, "F4": 0x73,
        "F5": 0x74, "F6": 0x75, "F7": 0x76, "F8": 0x77,
        "F9": 0x78, "F10": 0x79, "F11": 0x7A, "F12": 0x7B,
    }
    
    # 可用功能键列表（供UI选择）
    AVAILABLE_KEYS = ["F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10", "F11", "F12"]
    
    # 当前绑定（可运行时修改）
    KEY_RESET = "F7"     # 重置计时器
    KEY_LOCK = "F8"      # 锁定/解锁
    KEY_CORNER = "F9"    # 切换角落
    KEY_BEEP = "F10"     # 声音开关
    KEY_ZONES = "F11"    # 战区提示音
    
    # 热键ID（用于注册/注销）
    HK_ID_RESET = 7007
    HK_ID_LOCK = 7008
    HK_ID_CORNER = 7009
    HK_ID_BEEP = 7010
    HK_ID_ZONES = 7011
    
    # 全局热键开关（用户可配置）
    GLOBAL_HOTKEYS = True
    
    @classmethod
    def get_vk(cls, key_name: str) -> int:
        """获取功能键的VK码"""
        return cls.VK_CODES.get(key_name, 0)
    
    @classmethod
    def get_bindings(cls) -> dict:
        """获取当前所有绑定"""
        return {
            "reset": cls.KEY_RESET,
            "lock": cls.KEY_LOCK,
            "corner": cls.KEY_CORNER,
            "beep": cls.KEY_BEEP,
            "zones": cls.KEY_ZONES,
        }
    
    @classmethod
    def set_bindings(cls, bindings: dict) -> None:
        """设置绑定"""
        if "reset" in bindings:
            cls.KEY_RESET = bindings["reset"]
        if "lock" in bindings:
            cls.KEY_LOCK = bindings["lock"]
        if "corner" in bindings:
            cls.KEY_CORNER = bindings["corner"]
        if "beep" in bindings:
            cls.KEY_BEEP = bindings["beep"]
        if "zones" in bindings:
            cls.KEY_ZONES = bindings["zones"]


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
    
    # 配置文件版本（用于迁移旧配置）
    # v3: 添加编译开关状态记录，解决精简版/完整版配置冲突
    CONFIG_VERSION = 3


# ============================================================================
# 弹道物理计算参数（用于公式校准）
# ============================================================================

class BallisticPhysicsParams:
    """弹道物理计算参数 (CCRP v3.0)
    
    基于War Thunder大气模型:
    - 空气密度: rho(h) = 1.225 * exp(-h/14426) kg/m^3
    - 标高H = 14426m (源自Wiki "10km约一半密度")
    - 支持地图温度修正(冷图+12%, 热图-6%)
    """
    
    # ==================== 基础物理常量 ====================
    GRAVITY = 9.8
    AIR_DENSITY_SEA = 1.225
    AIR_DENSITY_SCALE_HEIGHT = 14426.0
    
    # ==================== 地图温度修正 ====================
    TEMP_REFERENCE_K = 288.15
    MAP_TEMPERATURE_K = 288.0
    USE_TEMPERATURE_CORRECTION = True
    
    # ==================== 阻力模型配置 ====================
    DRAG_MODEL = "advanced"
    DRAG_COEFFICIENT_MULT = 0.5
    DRAG_REFERENCE_AREA_MULT = 0.8
    
    # ==================== 减速伞参数 ====================
    BRAKE_DRAG_MULT = 1.0
    BRAKE_DEPLOY_DELAY = 0.5
    
    # ==================== 数值计算精度 ====================
    TIME_STEP = 0.005
    MAX_FLIGHT_TIME = 120.0
    GROUND_MARGIN = 1.0
    
    # ==================== 校准修正参数 ====================
    RANGE_CORRECTION_MULT = 1.0
    TIME_CORRECTION_MULT = 1.0
    ALTITUDE_CORRECTION_OFFSET = 0.0
    
    # ==================== 飞机状态参数 ====================
    USE_AIRCRAFT_VY = True
    DEFAULT_TARGET_ALT = 0.0
    
    # ==================== 投弹提示配置 ====================
    RELEASE_WARNING_SEC = 5.0
    RELEASE_READY_SEC = 0.5


def _wt_get_air_density(altitude_m: float, temp_k: float = None) -> float:
    """计算War Thunder指数衰减大气密度
    
    公式：ρ(h) = 1.225 × exp(-h/14426) × (288.15/T)
    """
    if altitude_m < 0:
        altitude_m = 0
    
    rho_sea = BallisticPhysicsParams.AIR_DENSITY_SEA
    scale_h = BallisticPhysicsParams.AIR_DENSITY_SCALE_HEIGHT
    
    density = rho_sea * math.exp(-altitude_m / scale_h)
    
    if temp_k is not None and temp_k > 0 and BallisticPhysicsParams.USE_TEMPERATURE_CORRECTION:
        density *= BallisticPhysicsParams.TEMP_REFERENCE_K / temp_k
    
    return density


class AboutConfig:
    """关于对话框配置"""
    # 软件信息
    APP_NAME = "Bomana"
    APP_NAME_CN = "战雷全真模式收益计时器"
    VERSION = "6.6.0"  # v6.6.0: UX/Visual improvements - 距离标签重构 + 起落架进度指示器
    AUTHOR = "猹Cheems"
    # 链接配置
    GITHUB_URL = "https://github.com/Thankyou-Cheems/Bomana"
    
    # 赞助链接配置（可以添加多个）
    SPONSOR_LINKS = [
        # ("显示名称", "链接URL", "图片文件名"),
        ("微信赞赏", "", "sponsor_wechat.png"),  # 空链接表示只显示图片
    ]
    
    # 赞助图片尺寸
    SPONSOR_IMAGE_WIDTH = 400

class ChecklistConfig:
    """检查清单配置
    
    用户可以自定义起飞前的检查项目。
    """
    # 最多允许的检查项数量
    MAX_ITEMS = 8
    
    # 默认检查清单
    DEFAULT_ITEMS = [
        "按I启动发动机",
        "等待发动机转速稳定",
        "收起落架",
        "开增稳系统", 
        "Y66或地图设定打击目标",
        "取消武器选择模式",
        "火控系统Y67调节炸弹自动",
        "降落后Y65关闭座舱盖防噪音"
    ]


class BombConfig:
    """投弹预测配置（CCRP v2.0 - 外部参数加载版）
    
    ╔══════════════════════════════════════════════════════════════════════════╗
    ║ 投弹系统说明 (CCRP v2.0)                                                   ║
    ╠══════════════════════════════════════════════════════════════════════════╣
    ║ 炸弹参数从外部ccrp_bomb_params.py模块加载                                   ║
    ║ 弹道计算参数集中到BallisticPhysicsParams配置块                              ║
    ║ 支持动态切换阻力模型（none/simple/advanced）                                ║
    ╚══════════════════════════════════════════════════════════════════════════╝
    """
    
    selected_bomb = "su_fab100sv"
    BOMB_DATABASE = {}
    _database_loaded = False
    
    @classmethod
    def _ensure_database_loaded(cls):
        """确保炸弹数据库已加载"""
        if cls._database_loaded:
            return
        
        try:
            from ccrp_bomb_params import BALLISTIC_PARAMS as external_params
            
            for bomb_id, params in external_params.items():
                cls.BOMB_DATABASE[bomb_id] = {
                    'mass': params.get('mass', 100.0),
                    'drag_cx': params.get('dragCx', 0.04),
                    'caliber': params.get('caliber', 0.2),
                    'distFromCmToStab': params.get('distFromCmToStab', 0.5),
                    'brakeTime': params.get('brakeTime', [0.0, 0.0]),
                    'brakeCxK': params.get('brakeCxK', 0.0),
                    'brakeArm': params.get('brakeArm', 0.0),
                    'stab_enabled': params.get('stab_enabled', False),
                    'category': cls._infer_category(bomb_id),
                }
            
            cls._database_loaded = True
            print(f"[BombConfig] 已从ccrp_bomb_params加载 {len(cls.BOMB_DATABASE)} 种炸弹参数")
            
        except ImportError as e:
            print(f"[BombConfig] 警告: 无法加载ccrp_bomb_params模块: {e}")
            cls._database_loaded = True
        except Exception as e:
            print(f"[BombConfig] 加载炸弹参数时出错: {e}")
            cls._database_loaded = True
    
    @classmethod
    def _infer_category(cls, bomb_id: str) -> str:
        """根据炸弹ID推断国家/分类"""
        bomb_id_lower = bomb_id.lower()
        
        category_prefixes = {
            'us_': '美国', 'su_': '苏联', 'uk_': '英国', 'de_': '德国',
            'jp_': '日本', 'it_': '意大利', 'fr_': '法国', 'cn_': '中国',
            'swd_': '瑞典', 'sws_': '瑞典', 'il_': '以色列',
        }
        
        for prefix, category in category_prefixes.items():
            if bomb_id_lower.startswith(prefix):
                return category
        
        if 'fab' in bomb_id_lower or 'ofab' in bomb_id_lower:
            return '苏联'
        if 'mk_' in bomb_id_lower or 'gbu' in bomb_id_lower:
            return '美国'
        
        return '通用'
    
    @classmethod
    def get_categories(cls) -> list:
        """获取所有炸弹分类"""
        cls._ensure_database_loaded()
        categories = set(bomb.get("category", "通用") for bomb in cls.BOMB_DATABASE.values())
        priority = ['苏联', '美国', '德国', '英国', '日本', '中国']
        result = [p for p in priority if p in categories]
        result.extend(sorted(categories - set(priority)))
        return result
    
    @classmethod
    def get_bombs_by_category(cls, category: str) -> list:
        """获取指定分类的所有炸弹"""
        cls._ensure_database_loaded()
        bombs = [name for name, data in cls.BOMB_DATABASE.items() if data.get("category") == category]
        return sorted(bombs, key=lambda x: cls.BOMB_DATABASE[x].get('mass', 0))
    
    @classmethod
    def get_all_bomb_names(cls) -> list:
        """获取所有炸弹名称"""
        cls._ensure_database_loaded()
        return sorted(list(cls.BOMB_DATABASE.keys()))
    
    @classmethod
    def get_bomb_data(cls, name: str):
        """获取指定炸弹的数据"""
        cls._ensure_database_loaded()
        return cls.BOMB_DATABASE.get(name)
    
    @classmethod
    def get_selected_bomb_data(cls) -> dict:
        """获取当前选中炸弹的数据"""
        cls._ensure_database_loaded()
        data = cls.BOMB_DATABASE.get(cls.selected_bomb)
        return data if data else {"mass": 100.0, "drag_cx": 0.04, "caliber": 0.2, "category": "苏联"}
    
    @classmethod
    def search_bombs(cls, query: str, limit: int = 100) -> list:
        """搜索炸弹"""
        cls._ensure_database_loaded()
        if not query:
            return list(cls.BOMB_DATABASE.keys())[:limit]
        
        def normalize(s):
            return s.lower().replace('_', '').replace('-', '').replace(' ', '')
        
        query_norm = normalize(query)
        results = []
        
        for bomb_id, data in cls.BOMB_DATABASE.items():
            keywords = bomb_id + ' ' + data.get('category', '') + ' ' + str(int(data.get('mass', 0)))
            if query_norm in normalize(keywords) or query.lower() in keywords.lower():
                results.append(bomb_id)
                if len(results) >= limit:
                    break
        return results
    
    @classmethod
    def format_bomb_name(cls, bomb_id: str) -> str:
        """格式化炸弹名称用于显示"""
        cls._ensure_database_loaded()
        data = cls.get_bomb_data(bomb_id)
        if data is None:
            return bomb_id
        mass = data.get('mass', 0)
        mass_str = f"{mass/1000:.1f}t" if mass >= 1000 else f"{int(mass)}kg"
        name = bomb_id.replace('_', ' ').replace(' default', '')
        return f"{name} ({mass_str})"
    
    @classmethod
    def get_bomb_physics_params(cls, name: str = None) -> dict:
        """获取炸弹的完整物理参数"""
        cls._ensure_database_loaded()
        data = cls.get_selected_bomb_data() if name is None else (cls.get_bomb_data(name) or {})
        return {
            'mass': data.get('mass', 100.0),
            'caliber': data.get('caliber', 0.2),
            'drag_cx': data.get('drag_cx', 0.04),
            'distFromCmToStab': data.get('distFromCmToStab', 0.5),
            'brakeTime': data.get('brakeTime', [0.0, 0.0]),
            'brakeCxK': data.get('brakeCxK', 0.0),
            'brakeArm': data.get('brakeArm', 0.0),
            'stab_enabled': data.get('stab_enabled', False),
            'reference_area': 3.14159 * (data.get('caliber', 0.2) / 2) ** 2,
        }


class Theme:
    """颜色主题配置
    
    预设主题: Dark(默认), Light, HighContrast
    
    添加新主题:
    1. 在THEMES字典中添加定义
    2. 确保包含所有必要颜色键
    3. 调用Theme.apply(name)应用
    
    注意: 主题切换需重启应用生效(tkinter限制)
    """
    # 当前活动主题名称
    _current = "dark"
    
    # 预设主题定义
    THEMES = {
        "dark": {
            "name": "暗色 (Dark)",
            "BG": "#0a0e13",
            "BORDER": "#30363d",
            "TEXT": "#e6edf3",
            "TEXT_DIM": "#8b949e",
            "TEXT_MUTED": "#484f58",
            "GREEN": "#3fb950",
            "YELLOW": "#d29922",
            "RED": "#f85149",
            "BLUE": "#58a6ff",
            "ORANGE": "#f0883e",
            "GRAYPILL": "#161b22",
            "SEPARATOR": "#21262d",
        },
        "light": {
            "name": "亮色 (Light)",
            "BG": "#ffffff",
            "BORDER": "#d0d7de",
            "TEXT": "#1f2328",
            "TEXT_DIM": "#656d76",
            "TEXT_MUTED": "#8c959f",
            "GREEN": "#1a7f37",
            "YELLOW": "#9a6700",
            "RED": "#cf222e",
            "BLUE": "#0969da",
            "ORANGE": "#bc4c00",
            "GRAYPILL": "#f6f8fa",
            "SEPARATOR": "#d8dee4",
        },
        "high_contrast": {
            "name": "高对比度",
            "BG": "#000000",
            "BORDER": "#ffffff",
            "TEXT": "#ffffff",
            "TEXT_DIM": "#ffff00",
            "TEXT_MUTED": "#808080",
            "GREEN": "#00ff00",
            "YELLOW": "#ffff00",
            "RED": "#ff0000",
            "BLUE": "#00ffff",
            "ORANGE": "#ffa500",
            "GRAYPILL": "#1a1a1a",
            "SEPARATOR": "#404040",
        },
    }
    
    # 默认颜色值（使用暗色主题）
    BG = "#0a0e13"
    BORDER = "#30363d"
    TEXT = "#e6edf3"
    TEXT_DIM = "#8b949e"
    TEXT_MUTED = "#484f58"
    GREEN = "#3fb950"
    YELLOW = "#d29922"
    RED = "#f85149"
    BLUE = "#58a6ff"
    ORANGE = "#f0883e"
    GRAYPILL = "#161b22"
    SEPARATOR = "#21262d"
    
    @classmethod
    def apply(cls, theme_name: str) -> bool:
        """应用指定主题
        
        Args:
            theme_name: 主题名称 ("dark", "light", "high_contrast")
        
        Returns:
            是否成功应用
        """
        if theme_name not in cls.THEMES:
            return False
        
        theme = cls.THEMES[theme_name]
        cls._current = theme_name
        
        # 更新类属性
        cls.BG = theme["BG"]
        cls.BORDER = theme["BORDER"]
        cls.TEXT = theme["TEXT"]
        cls.TEXT_DIM = theme["TEXT_DIM"]
        cls.TEXT_MUTED = theme["TEXT_MUTED"]
        cls.GREEN = theme["GREEN"]
        cls.YELLOW = theme["YELLOW"]
        cls.RED = theme["RED"]
        cls.BLUE = theme["BLUE"]
        cls.ORANGE = theme["ORANGE"]
        cls.GRAYPILL = theme["GRAYPILL"]
        cls.SEPARATOR = theme["SEPARATOR"]
        
        return True
    
    @classmethod
    def get_current(cls) -> str:
        """获取当前主题名称"""
        return cls._current
    
    @classmethod
    def get_theme_names(cls) -> list:
        """获取所有主题名称列表"""
        return list(cls.THEMES.keys())
    
    @classmethod
    def get_theme_display_name(cls, theme_name: str) -> str:
        """获取主题的显示名称"""
        if theme_name in cls.THEMES:
            return cls.THEMES[theme_name]["name"]
        return theme_name


class PanelConfig:
    """面板显示配置
    
    控制各个信息面板的显示/隐藏状态。
    受编译开关控制：如果编译开关禁用某功能，则对应面板强制隐藏。
    """
    # 默认全部显示
    show_zones = True        # 战区导航
    show_airfields = True    # 机场导航
    show_fuel = True         # 燃油管理
    show_checklist = True    # 检查清单
    show_bombing = True      # v6.0新增：投弹预测（受ENABLE_CCRP开关控制）
    # v6.2.1: 导航条模式 - "integrated"(集成) / "standalone"(独立窗口)
    navigation_mode = "integrated"
    navigation_window_pos = None  # 独立窗口位置 (x, y)
    navigation_bar_width = 1.0    # 独立导航栏宽度倍率（0.5-2.0）
    
    @classmethod
    def init_from_compile_switches(cls):
        """根据编译开关初始化面板状态
        
        编译开关优先级高于用户配置：
        如果编译开关禁用某功能，则该面板强制隐藏且用户无法开启
        """
        if not ENABLE_CCRP:
            cls.show_bombing = False
        if not ENABLE_ZONES:
            cls.show_zones = False
        if not ENABLE_AIRFIELDS:
            cls.show_airfields = False
        if not ENABLE_FUEL:
            cls.show_fuel = False
        if not ENABLE_CHECKLIST:
            cls.show_checklist = False
    
    @classmethod
    def is_feature_enabled(cls, feature: str) -> bool:
        """检查某功能是否被编译开关启用
        
        用于UI判断是否显示相关设置选项
        """
        feature_map = {
            'zones': ENABLE_ZONES,
            'airfields': ENABLE_AIRFIELDS,
            'fuel': ENABLE_FUEL,
            'checklist': ENABLE_CHECKLIST,
            'bombing': ENABLE_CCRP,
        }
        return feature_map.get(feature, True)


class SnapConfig:
    """窗口吸附配置"""
    # 吸附距离（像素）：窗口边缘距离屏幕边缘小于此值时自动吸附
    SNAP_DISTANCE = 20
    # 是否启用吸附
    enabled = True


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

def calculate_smart_scale(screen_width: int, screen_height: int, base_dpi_scale: float) -> float:
    """根据屏幕分辨率智能计算UI缩放倍数（v5.9.3新增）
    
    ╔══════════════════════════════════════════════════════════════════════╗
    ║ 智能缩放逻辑说明                                                      ║
    ╠══════════════════════════════════════════════════════════════════════╣
    ║ 目标：让界面在不同分辨率下都有合适的大小                               ║
    ║                                                                      ║
    ║ 缩放策略：                                                            ║
    ║ 1. 1080p及以下（≤1920x1080）：1.5x - 更大字体，提高可读性             ║
    ║ 2. 1440p（2560x1440）：1.2x - 120%大小                               ║
    ║ 3. 4K及以上（≥3840x2160）：0.9x - 更紧凑，充分利用屏幕空间           ║
    ║                                                                      ║
    ║ 特殊情况：                                                            ║
    ║ - 如果Windows DPI缩放已经>1.25，说明用户自己已经设置了大字体，       ║
    ║   此时不再额外放大，使用1.0x                                          ║
    ╚══════════════════════════════════════════════════════════════════════╝
    
    Args:
        screen_width: 屏幕宽度（像素）
        screen_height: 屏幕高度（像素）
        base_dpi_scale: Windows DPI缩放倍数
    
    Returns:
        推荐的UI缩放倍数
    """
    # 如果Windows DPI已经很大（>125%），说明用户希望大字体
    # 此时不再额外放大
    if base_dpi_scale > 1.25:
        return 1.0
    
    # 根据分辨率决定缩放
    # 1080p及以下：放大50%
    if screen_width <= 1920 and screen_height <= 1080:
        return 1.5
    # 1440p：放大20%
    elif screen_width <= 2560 and screen_height <= 1440:
        return 1.2
    # 4K及以上：缩小10%（利用高分辨率显示更多内容）
    else:
        return 0.9




class ConfigManager:
    """配置文件管理器
    
    负责从JSON文件读写用户配置，如窗口位置、透明度等。
    v6.0.1: 新增配置版本管理，自动迁移旧配置
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
                    config = json.load(f)
                # 配置版本迁移
                config = ConfigManager._migrate_config(config)
                return config
            except (json.JSONDecodeError, IOError):
                pass
        return {}
    
    @staticmethod
    def _migrate_config(config: Dict[str, Any]) -> Dict[str, Any]:
        """配置版本迁移
        
        处理旧版本配置的兼容性问题，自动升级配置结构
        v6.1.1: 添加编译开关状态记简版/完整版配置冲突
        """
        version = config.get('config_version', 1)
        
        # v1 -> v2: 添加投弹面板配置
        if version < 2:
            panels = config.get('panels', {})
            if 'show_bombing' not in panels:
                panels['show_bombing'] = True
            config['panels'] = panels
            config['config_version'] = 2
        
        # v2 -> v3: 添加编译开关状态记录
        if version < 3:
            config['config_version'] = 3
        
        # 检查编译开关是否变化（精简版 <-> 完整版切换）
        saved_switches = config.get('compile_switches', {})
        current_switches = {
            'ENABLE_CCRP': ENABLE_CCRP,
            'ENABLE_ZONES': ENABLE_ZONES,
            'ENABLE_AIRFIELDS': ENABLE_AIRFIELDS,
            'ENABLE_FUEL': ENABLE_FUEL,
            'ENABLE_CHECKLIST': ENABLE_CHECKLIST,
        }
        
        # 如果某个功能从禁用变为启用，重置该面板为默认显示
        panels = config.get('panels', {})
        switches_changed = False
        
        for switch_name, current_enabled in current_switches.items():
            was_enabled = saved_switches.get(switch_name, False)
            if current_enabled and not was_enabled:
                # 功能从禁用变为启用，重置对应面板为显示
                panel_key = {
                    'ENABLE_CCRP': 'show_bombing',
                    'ENABLE_ZONES': 'show_zones',
                    'ENABLE_AIRFIELDS': 'show_airfields',
                    'ENABLE_FUEL': 'show_fuel',
                    'ENABLE_CHECKLIST': 'show_checklist',
                }.get(switch_name)
                if panel_key:
                    panels[panel_key] = True
                    switches_changed = True
        
        if switches_changed:
            config['panels'] = panels
        
        # 更新保存的编译开关状态
        config['compile_switches'] = current_switches
        
        # 自动保存迁移后的配置
        try:
            ConfigManager.save(config)
        except:
            pass
        
        return config
    
    @staticmethod
    def save(config: Dict[str, Any]) -> None:
        """保存配置文件
        
        Args:
            config: 配置字典
        """
        try:
            # 确保保存时带有版本号
            config['config_version'] = FileConfig.CONFIG_VERSION
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

    @classmethod
    def get_all_monitors(cls) -> List[Dict[str, Any]]:
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
                ctypes.c_void_p   # dwData
            )
            
            # MONITORINFO 结构体
            class MONITORINFO(ctypes.Structure):
                _fields_ = [
                    ("cbSize", ctypes.c_uint),
                    ("rcMonitor", ctypes.c_long * 4),  # 显示器完整区域
                    ("rcWork", ctypes.c_long * 4),     # 工作区域（排除任务栏）
                    ("dwFlags", ctypes.c_uint),
                ]
            
            monitor_list = []
            
            def callback(hMonitor, hdcMonitor, lprcMonitor, dwData):
                info = MONITORINFO()
                info.cbSize = ctypes.sizeof(MONITORINFO)
                cls.user32.GetMonitorInfoW(hMonitor, ctypes.byref(info))
                
                # 使用工作区域（排除任务栏）
                work = info.rcWork
                monitor_list.append({
                    "index": len(monitor_list),
                    "x": work[0],
                    "y": work[1],
                    "width": work[2] - work[0],
                    "height": work[3] - work[1],
                    "is_primary": bool(info.dwFlags & 1),
                })
                return 1  # 继续枚举
            
            # 枚举所有显示器
            enum_proc = MONITORENUMPROC(callback)
            cls.user32.EnumDisplayMonitors(None, None, enum_proc, 0)
            
            monitors = monitor_list
        except (OSError, AttributeError, Exception):
            # 失败时返回主屏幕
            w, h = cls.screen_size()
            monitors = [{"index": 0, "x": 0, "y": 0, "width": w, "height": h, "is_primary": True}]
        
        return monitors if monitors else [{"index": 0, "x": 0, "y": 0, "width": 1920, "height": 1080, "is_primary": True}]
    
    @classmethod
    def get_monitor_at(cls, x: int, y: int) -> Optional[Dict[str, Any]]:
        """获取指定坐标所在的显示器
        
        Args:
            x, y: 屏幕坐标
        
        Returns:
            显示器信息字典，或None
        """
        monitors = cls.get_all_monitors()
        for mon in monitors:
            if (mon["x"] <= x < mon["x"] + mon["width"] and
                mon["y"] <= y < mon["y"] + mon["height"]):
                return mon
        # 默认返回主显示器
        for mon in monitors:
            if mon.get("is_primary"):
                return mon
        return monitors[0] if monitors else None
    
    @classmethod
    def snap_to_edges(cls, x: int, y: int, w: int, h: int, snap_dist: int = 20) -> Tuple[int, int]:
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
def calculate_heading_tape_scale(distance_km: float) -> float:
    """计算航向带的动态缩放系数
    
    v6.1新增: 针对高空投弹优化
    - 远距离(>15km): 基础缩放1.0x，方便大航向调整
    - 中距离(5-15km): 线性增加缩放
    - 近距离(<5km): 最大缩放4.0x，精确微调
    
    Args:
        distance_km: 到目标距离(公里)
    
    Returns:
        缩放系数(1.0-4.0)
    """
    start_km = ZoneConfig.HEADING_TAPE_SCALE_START_KM
    end_km = ZoneConfig.HEADING_TAPE_SCALE_END_KM
    max_scale = ZoneConfig.HEADING_TAPE_MAX_SCALE
    
    if distance_km >= start_km:
        return 1.0
    elif distance_km <= end_km:
        return max_scale
    else:
        # 线性插值
        ratio = (start_km - distance_km) / (start_km - end_km)
        return 1.0 + ratio * (max_scale - 1.0)
def get_cdi_tolerance(distance_km: float) -> float:
    """根据距离获取动态容差角度
    
    距离越近精度要求越高: >30km±15° / 15-30km±10° / 8-15km±5° / 3-8km±3° / <3km±1.5°
    
    Args:
        distance_km: 到目标的距离(公里)
    
    Returns:
        容差角度(度)
    """
    for threshold_km, tolerance_deg in ZoneConfig.CDI_TOLERANCE_THRESHOLDS:
        if distance_km < threshold_km:
            return tolerance_deg
    return 15.0  # 默认


# ============================================================================
# 导航显示工具函数 - v6.5 重构：复用导航条显示逻辑
# ============================================================================

def calculate_zone_turn_indicator(rel: float, tolerance: float) -> Tuple[str, str]:
    """计算战区转向指示文本和颜色
    
    根据相对方位角计算需要显示的转向指示（左转/右转/保持）
    独立导航条和集成导航条共用此逻辑。
    
    Args:
        rel: 相对方位角（正值=目标在右侧）
        tolerance: 当前距离对应的容差角度
    
    Returns:
        (指示文本, 颜色代码)
    """
    abs_rel = abs(rel)
    
    if abs_rel < 0.1:
        return "▶▶ 保持 ◀◀", Theme.GREEN
    elif abs_rel < 0.5:
        direction = "◀" if rel < 0 else "▶"
        return f"{direction} {abs_rel:.2f}° {direction}", Theme.GREEN
    elif abs_rel < tolerance * 0.3:
        if rel < 0:
            return f"◀ 左修 {abs_rel:.1f}°", Theme.GREEN
        else:
            return f"右修 {abs_rel:.1f}° ▶", Theme.GREEN
    elif rel < 0:
        color = Theme.YELLOW if abs_rel < tolerance else Theme.ORANGE
        return f"◀ 左转 {abs_rel:.1f}°", color
    else:
        color = Theme.YELLOW if abs_rel < tolerance else Theme.ORANGE
        return f"右转 {abs_rel:.1f}° ▶", color


def calculate_zone_status(abs_rel: float, tolerance: float) -> Tuple[str, str]:
    """计算战区状态描述文本和颜色
    
    根据相对方位角计算当前对准状态。
    独立导航条和集成导航条共用此逻辑。
    
    Args:
        abs_rel: 相对方位角的绝对值
        tolerance: 当前距离对应的容差角度
    
    Returns:
        (状态文本, 颜色代码)
    """
    if abs_rel < 0.1:
        return "★ 锁定", Theme.GREEN
    elif abs_rel < 0.3:
        return "精确对准", Theme.GREEN
    elif abs_rel < tolerance * 0.3:
        return "高精度", Theme.GREEN
    elif abs_rel < tolerance * 0.6:
        return "航线内", Theme.BLUE
    elif abs_rel < tolerance:
        return "边缘", Theme.YELLOW
    else:
        return "⚠ 偏航", Theme.ORANGE


def calculate_airfield_turn_indicator(rel: float) -> Tuple[str, str]:
    """计算机场转向指示文本和颜色
    
    独立导航条和集成导航条共用此逻辑。
    
    Args:
        rel: 相对方位角（正值=目标在右侧）
    
    Returns:
        (指示文本, 颜色代码)
    """
    abs_rel = abs(rel)
    
    if abs_rel < 0.1:
        return "▶▶ 保持 ◀◀", Theme.GREEN
    elif abs_rel < 0.5:
        direction = "◀" if rel < 0 else "▶"
        return f"{direction} {abs_rel:.2f}° {direction}", Theme.GREEN
    elif abs_rel < 5:
        if rel < 0:
            return f"◀ 左修 {abs_rel:.1f}°", Theme.BLUE
        else:
            return f"右修 {abs_rel:.1f}° ▶", Theme.BLUE
    elif rel < 0:
        return f"◀ 左转 {abs_rel:.1f}°", Theme.BLUE
    else:
        return f"右转 {abs_rel:.1f}° ▶", Theme.BLUE


def calculate_airfield_status(abs_rel: float) -> Tuple[str, str]:
    """计算机场状态描述文本和颜色
    
    独立导航条和集成导航条共用此逻辑。
    
    Args:
        abs_rel: 相对方位角的绝对值
    
    Returns:
        (状态文本, 颜色代码)
    """
    if abs_rel < 0.1:
        return "★ 锁定", Theme.GREEN
    elif abs_rel < 0.5:
        return "精确对准", Theme.GREEN
    elif abs_rel < 5:
        return "高精度", Theme.GREEN
    elif abs_rel < 15:
        return "航线内", Theme.BLUE
    elif abs_rel < 45:
        return "接近", Theme.BLUE
    else:
        return "偏离", Theme.TEXT_DIM


def format_distance_ete(dist_km: float, ete_str: Optional[str] = None) -> str:
    """格式化距离和预计到达时间
    
    独立导航条和集成导航条共用此逻辑。
    
    Args:
        dist_km: 距离（公里）
        ete_str: 预计到达时间字符串（可选）
    
    Returns:
        格式化后的字符串，如 "12.3km ⏱2:30"
    """
    dist_str = f"{dist_km:.1f}km" if dist_km < 100 else f"{int(dist_km)}km"
    if ete_str:
        return f"{dist_str} ⏱{ete_str}"
    return dist_str


def format_distance_dynamic(distance_km: float) -> str:
    """v6.6.0: 动态精度距离格式化
    
    根据距离自动选择显示精度：
    - Distance > 20 km: 整数 (e.g., 25)
    - Distance 5 - 20 km: 1位小数 (e.g., 8.4)
    - Distance < 5 km: 1位小数或米 (e.g., 1.2 或 800m)
    
    Args:
        distance_km: 距离（公里）
    
    Returns:
        格式化后的距离字符串（不含单位）
    """
    if distance_km > 20:
        return f"{int(distance_km)}"
    elif distance_km >= 1:
        return f"{distance_km:.1f}"
    else:
        # 小于1km时显示米
        meters = int(distance_km * 1000)
        return f"{meters}m"


def get_deviation_color(relative_angle: float, distance_km: float) -> str:
    """v6.6.0: 根据偏差计算语义颜色
    
    距离标签颜色应继承当前航道偏差颜色。
    
    Args:
        relative_angle: 相对角度
        distance_km: 距离（公里）
    
    Returns:
        颜色代码
    """
    tolerance = get_cdi_tolerance(distance_km)
    abs_rel = abs(relative_angle)
    
    if abs_rel < 0.2:
        # 极精准
        return "#00FF00"  # 亮绿
    elif abs_rel <= tolerance * 0.3:
        return Theme.GREEN
    elif abs_rel <= tolerance * 0.6:
        return Theme.BLUE
    elif abs_rel <= tolerance:
        return Theme.YELLOW
    elif abs_rel <= tolerance * 1.5:
        return Theme.ORANGE
    else:
        return Theme.RED


def generate_cdi_indicator(relative_angle: float, distance_km: float) -> Tuple[str, str]:
    """生成高精度航道偏差指示器(CDI)字符串
    
    v6.1升级: 精度从10-20阶梯提升到30阶梯
    
    指示器显示航向与目标方位的偏差:
    - 中心●=完美对准
    - 指示点偏右=目标在右边=需右转
    - 指示点偏左=目标在左边=需左转
    - 超出范围显示溢出箭头◀◀/▶▶
    
    Args:
        relative_angle: 相对方位角(-180~180, 正=目标在右)
        distance_km: 到目标距离(公里)
    
    Returns:
        (指示器字符串, 颜色代码)
    """
    width = ZoneConfig.CDI_WIDTH
    tolerance = get_cdi_tolerance(distance_km)
    
    # 计算偏差比例：relative_angle / tolerance
    # 正值 = 目标在右 = 指示点显示在右边
    if tolerance > 0:
        deviation_ratio = relative_angle / tolerance
    else:
        deviation_ratio = 0.0
    
    # 限制在 -1.5 到 1.5 范围（超出1.0表示溢出）
    clamped_ratio = max(-1.5, min(1.5, deviation_ratio))
    
    # 计算指示点位置（0 = 最左，width-1 = 最右）
    center = (width - 1) // 2
    # 偏差比例映射到位置：ratio=0 -> center, ratio=1 -> 右边界附近
    track_width = center - 1  # 可用的偏移范围
    offset = int(clamped_ratio * track_width)
    pos = center + offset
    pos = max(1, min(width - 2, pos))  # 确保不覆盖边界符号
    
    # 判断是否溢出
    is_overflow_left = deviation_ratio < -1.0
    is_overflow_right = deviation_ratio > 1.0
    
    # 构建指示器字符串
    indicator = [ZoneConfig.CDI_TRACK] * width
    
    # 设置边界
    if is_overflow_left:
        indicator[0] = ZoneConfig.CDI_OVERFLOW_LEFT[0]
        indicator[1] = ZoneConfig.CDI_OVERFLOW_LEFT[1] if len(ZoneConfig.CDI_OVERFLOW_LEFT) > 1 else ZoneConfig.CDI_TRACK
    else:
        indicator[0] = ZoneConfig.CDI_LEFT
    
    if is_overflow_right:
        indicator[-1] = ZoneConfig.CDI_OVERFLOW_RIGHT[-1] if len(ZoneConfig.CDI_OVERFLOW_RIGHT) > 1 else ZoneConfig.CDI_OVERFLOW_RIGHT[0]
        indicator[-2] = ZoneConfig.CDI_OVERFLOW_RIGHT[0]
    else:
        indicator[-1] = ZoneConfig.CDI_RIGHT
    
    # 设置中心指示点
    indicator[pos] = ZoneConfig.CDI_CENTER
    
    # v6.1改进: 更细腻的颜色分级
    abs_ratio = abs(deviation_ratio)
    abs_angle = abs(relative_angle)
    
    if abs_angle < 0.2:
        # 极准（<0.2°），亮绿色
        color = "#00FF00"
    elif abs_ratio <= 0.2:
        # 接近中心（<20%容差），绿色
        color = Theme.GREEN
    elif abs_ratio <= 0.5:
        # 轻微偏差（20-50%容差），蓝色
        color = Theme.BLUE
    elif abs_ratio <= 0.8:
        # 中等偏差（50-80%容差），黄色
        color = Theme.YELLOW
    elif abs_ratio <= 1.0:
        # 接近边界（80-100%容差），橙色
        color = Theme.ORANGE
    else:
        # 严重偏差（超出容差），红色
        color = Theme.RED
    
    return "".join(indicator), color


def generate_cdi_indicator_extended(relative_angle: float, distance_km: float) -> dict:
    """生成扩展CDI信息（包含数值精度）
    
    v6.1新增: 提供更详细的CDI数据用于UI显示
    
    Args:
        relative_angle: 相对方位角(-180~180)
        distance_km: 到目标距离(公里)
    
    Returns:
        dict: {
            'indicator': 字符串指示器,
            'color': 颜色代码,
            'tolerance': 当前容差角度,
            'deviation_ratio': 偏差比例(-1.5~1.5),
            'precision_class': 精度等级(extreme/high/medium/low),
            'pointer_percent': 指针位置百分比(0-100, 50=中心)
        }
    """
    tolerance = get_cdi_tolerance(distance_km)
    indicator_str, color = generate_cdi_indicator(relative_angle, distance_km)
    
    # 计算偏差比例
    deviation_ratio = relative_angle / tolerance if tolerance > 0 else 0.0
    clamped_ratio = max(-1.5, min(1.5, deviation_ratio))
    
    # 指针位置百分比（50=中心，0=最左，100=最右）
    pointer_percent = 50 + (clamped_ratio * 50 / 1.5)
    pointer_percent = max(0, min(100, pointer_percent))
    
    # 精度等级
    abs_angle = abs(relative_angle)
    if abs_angle < 0.5:
        precision_class = "extreme"  # 极精准
    elif abs_angle < tolerance * 0.3:
        precision_class = "high"     # 高精度
    elif abs_angle < tolerance:
        precision_class = "medium"   # 中等
    else:
        precision_class = "low"      # 需要修正
    
    return {
        'indicator': indicator_str,
        'color': color,
        'tolerance': tolerance,
        'deviation_ratio': deviation_ratio,
        'precision_class': precision_class,
        'pointer_percent': pointer_percent,
    }


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
# 弹道计算模块（CCRP v3.0）
# ============================================================================

def calculate_bomb_trajectory(
    release_alt_m: float,
    release_speed_ms: float,
    bomb_mass_kg: float = 0.0,
    bomb_bc: float = 0.0,
    target_alt_m: float = 0.0,
    dive_angle_deg: float = 0.0,
    initial_vz_ms = None,
    bomb_params: dict = None
) -> tuple:
    """计算炸弹弹道（支持多种阻力模型）
    
    Args:
        release_alt_m: 投弹高度（米）
        release_speed_ms: 投弹时水平速度（m/s）
        target_alt_m: 目标高度（米）
        dive_angle_deg: 俯冲角度（度）
        initial_vz_ms: 初始垂直速度（m/s）
        bomb_params: 炸弹物理参数字典
    
    Returns:
        (飞行时间秒, 水平飞行距离米, 落地速度m/s)
    """
    g = BallisticPhysicsParams.GRAVITY
    drag_model = BallisticPhysicsParams.DRAG_MODEL
    
    alt_offset = BallisticPhysicsParams.ALTITUDE_CORRECTION_OFFSET
    range_mult = BallisticPhysicsParams.RANGE_CORRECTION_MULT
    time_mult = BallisticPhysicsParams.TIME_CORRECTION_MULT
    
    h = (release_alt_m + alt_offset) - target_alt_m
    if h <= 0:
        return 0.0, 0.0, 0.0
    
    dive_rad = math.radians(dive_angle_deg)
    vx = release_speed_ms * math.cos(dive_rad)
    vz0 = float(initial_vz_ms) if initial_vz_ms is not None else -release_speed_ms * math.sin(dive_rad)
    
    if drag_model == "none":
        discriminant = vz0 * vz0 + 2.0 * g * h
        if discriminant < 0:
            return 0.0, 0.0, 0.0
        t = (vz0 + math.sqrt(discriminant)) / g
        x = vx * t
        vz_final = vz0 - g * t
        impact_speed = math.sqrt(vx * vx + vz_final * vz_final)
        return t * time_mult, x * range_mult, impact_speed
    
    elif drag_model == "simple":
        return _calculate_trajectory_with_drag(h, vx, vz0, g, bomb_params, range_mult, time_mult)
    
    elif drag_model == "advanced":
        return _calculate_trajectory_advanced(h, vx, vz0, g, bomb_params, range_mult, time_mult)
    
    else:
        discriminant = vz0 * vz0 + 2.0 * g * h
        if discriminant < 0:
            return 0.0, 0.0, 0.0
        t = (vz0 + math.sqrt(discriminant)) / g
        x = vx * t
        vz_final = vz0 - g * t
        impact_speed = math.sqrt(vx * vx + vz_final * vz_final)
        return t * time_mult, x * range_mult, impact_speed


def _calculate_trajectory_with_drag(h, vx, vz0, g, bomb_params, range_mult, time_mult):
    """简化阻力模型"""
    if bomb_params is None:
        bomb_params = BombConfig.get_bomb_physics_params()
    
    mass = bomb_params.get('mass', 100.0)
    drag_cx = bomb_params.get('drag_cx', 0.04)
    caliber = bomb_params.get('caliber', 0.2)
    
    area = math.pi * (caliber / 2) ** 2 * BallisticPhysicsParams.DRAG_REFERENCE_AREA_MULT
    drag_cx *= BallisticPhysicsParams.DRAG_COEFFICIENT_MULT
    
    dt = BallisticPhysicsParams.TIME_STEP
    max_time = BallisticPhysicsParams.MAX_FLIGHT_TIME
    temp_k = BallisticPhysicsParams.MAP_TEMPERATURE_K
    temp_factor = BallisticPhysicsParams.TEMP_REFERENCE_K / temp_k if temp_k > 0 else 1.0
    
    x, z = 0.0, h
    vx_curr, vz_curr = vx, vz0
    t = 0.0
    
    while t < max_time and z > 0:
        current_altitude = max(0, z + BallisticPhysicsParams.DEFAULT_TARGET_ALT)
        rho = _wt_get_air_density(current_altitude) * temp_factor
        
        v = max(0.1, math.sqrt(vx_curr**2 + vz_curr**2))
        drag_coeff = 0.5 * rho * drag_cx * area / mass
        ax = -drag_coeff * vx_curr * v
        az = -g - drag_coeff * vz_curr * v
        
        vx_curr += ax * dt
        vz_curr += az * dt
        x += vx_curr * dt
        z += vz_curr * dt
        t += dt
    
    impact_speed = math.sqrt(vx_curr**2 + vz_curr**2)
    return t * time_mult, x * range_mult, impact_speed


def _calculate_trajectory_advanced(h, vx, vz0, g, bomb_params, range_mult, time_mult):
    """完整物理模型弹道计算 v3.0（使用RK4积分）"""
    if bomb_params is None:
        bomb_params = BombConfig.get_bomb_physics_params()
    
    mass = bomb_params.get('mass', 100.0)
    drag_cx = bomb_params.get('dragCx', bomb_params.get('drag_cx', 0.04))
    caliber = bomb_params.get('caliber', 0.2)
    brake_time = bomb_params.get('brakeTime', [0.0, 0.0])
    brake_cx_k = bomb_params.get('brakeCxK', 0.0)
    stab_enabled = bomb_params.get('stab_enabled', False)
    
    area = math.pi * (caliber / 2) ** 2 * BallisticPhysicsParams.DRAG_REFERENCE_AREA_MULT
    drag_cx *= BallisticPhysicsParams.DRAG_COEFFICIENT_MULT
    
    dt = BallisticPhysicsParams.TIME_STEP
    max_time = BallisticPhysicsParams.MAX_FLIGHT_TIME
    temp_k = BallisticPhysicsParams.MAP_TEMPERATURE_K
    temp_factor = BallisticPhysicsParams.TEMP_REFERENCE_K / temp_k if temp_k > 0 else 1.0
    
    x, z = 0.0, h
    vx_curr, vz_curr = vx, vz0
    t = 0.0
    prev_z, prev_vz, prev_vx, prev_x = h, vz0, vx, 0.0
    
    while t < max_time and z > BallisticPhysicsParams.GROUND_MARGIN:
        prev_z, prev_vz, prev_vx, prev_x = z, vz_curr, vx_curr, x
        
        current_altitude = max(0, z + BallisticPhysicsParams.DEFAULT_TARGET_ALT)
        rho = _wt_get_air_density(current_altitude) * temp_factor
        
        current_drag_cx = drag_cx
        if stab_enabled and len(brake_time) >= 2:
            brake_start = brake_time[0] + BallisticPhysicsParams.BRAKE_DEPLOY_DELAY
            brake_end = brake_time[1] + BallisticPhysicsParams.BRAKE_DEPLOY_DELAY
            if brake_start <= t <= brake_end and brake_cx_k > 0:
                brake_drag = brake_cx_k / (caliber ** 2) * BallisticPhysicsParams.BRAKE_DRAG_MULT
                current_drag_cx += brake_drag
        
        v = max(0.1, math.sqrt(vx_curr**2 + vz_curr**2))
        drag_factor = 0.5 * rho * current_drag_cx * area / mass
        
        # RK4积分
        ax1 = -drag_factor * vx_curr * v
        az1 = -g - drag_factor * vz_curr * v
        
        vx2, vz2 = vx_curr + ax1 * dt/2, vz_curr + az1 * dt/2
        v2 = max(0.1, math.sqrt(vx2**2 + vz2**2))
        ax2 = -drag_factor * vx2 * v2
        az2 = -g - drag_factor * vz2 * v2
        
        vx3, vz3 = vx_curr + ax2 * dt/2, vz_curr + az2 * dt/2
        v3 = max(0.1, math.sqrt(vx3**2 + vz3**2))
        ax3 = -drag_factor * vx3 * v3
        az3 = -g - drag_factor * vz3 * v3
        
        vx4, vz4 = vx_curr + ax3 * dt, vz_curr + az3 * dt
        v4 = max(0.1, math.sqrt(vx4**2 + vz4**2))
        ax4 = -drag_factor * vx4 * v4
        az4 = -g - drag_factor * vz4 * v4
        
        vx_curr += (ax1 + 2*ax2 + 2*ax3 + ax4) * dt / 6
        vz_curr += (az1 + 2*az2 + 2*az3 + az4) * dt / 6
        x += vx_curr * dt
        z += vz_curr * dt
        t += dt
    
    # 线性插值精确落地点
    if z < BallisticPhysicsParams.GROUND_MARGIN and prev_vz < 0:
        dz = prev_z - z
        if dz > 0.01:
            ratio = max(0.0, min(1.0, (prev_z - BallisticPhysicsParams.GROUND_MARGIN) / dz))
            t -= dt * (1 - ratio)
            x = prev_x + (x - prev_x) * ratio
            vx_curr = prev_vx + (vx_curr - prev_vx) * ratio
            vz_curr = prev_vz + (vz_curr - prev_vz) * ratio
    
    impact_speed = math.sqrt(vx_curr**2 + vz_curr**2)
    return t * time_mult, x * range_mult, impact_speed


def calculate_release_timing(
    current_distance_m: float,
    current_alt_m: float,
    ground_speed_ms: float,
    bomb_mass_kg: float = 0.0,
    bomb_bc: float = 0.0,
    target_alt_m: float = 0.0,
    dive_angle_deg: float = 0.0,
    initial_vz_ms: Optional[float] = None
) -> Tuple[float, float, str]:
    """计算投弹时机
    
    Returns:
        (距离投弹距离米, 距离投弹时间秒, 状态字符串)
        状态: "ready" / "approaching" / "too_far" / "passed" / "invalid"
    """
    if ground_speed_ms < 10.0 or current_alt_m <= target_alt_m:
        return 0.0, 0.0, "invalid"
    
    flight_time, bomb_range_m, _ = calculate_bomb_trajectory(
        release_alt_m=current_alt_m,
        release_speed_ms=ground_speed_ms,
        bomb_mass_kg=bomb_mass_kg,
        bomb_bc=bomb_bc,
        target_alt_m=target_alt_m,
        dive_angle_deg=dive_angle_deg,
        initial_vz_ms=initial_vz_ms
    )
    
    if bomb_range_m <= 0:
        return 0.0, 0.0, "invalid"
    
    release_distance_m = current_distance_m - bomb_range_m
    
    if release_distance_m < 0:
        return abs(release_distance_m), 0.0, "passed"
    
    time_to_release = release_distance_m / ground_speed_ms
    
    if time_to_release <= BallisticPhysicsParams.RELEASE_READY_SEC:
        return release_distance_m, time_to_release, "ready"
    elif time_to_release <= BallisticPhysicsParams.RELEASE_WARNING_SEC:
        return release_distance_m, time_to_release, "approaching"
    else:
        return release_distance_m, time_to_release, "too_far"


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
    
    # v5.8 新增：燃油管理相关字段
    fuel0_kg: float = 0           # 起飞油量 (kg) - 来自 Mfuel0
    altitude_m: float = 0         # 飞行高度 (m)
    tas_kmh: float = 0            # 真空速 (km/h)
    throttle_pct: float = 0       # 油门百分比 (%)
    
    # v5.9.6 新增：起落架状态
    gear_down: bool = False       # 起落架是否放下 (True=放下, False=收起)
    
    # v6.6.0 新增：起落架百分比（用于进度指示器）
    gear_pct: float = 0.0         # 起落架位置百分比 (0=收起, 100=放下)

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
class FuelSample:
    """燃油采样点
    
    记录某一时刻的燃油量，用于计算油耗率。
    """
    timestamp: float    # 时间戳
    fuel_kg: float      # 油量
    altitude_m: float   # 高度（用于分析，可选）


@dataclass
class FuelState:
    """燃油状态管理
    
    采样燃油变化,计算油耗率,估算剩余飞行时间和返航油量。
    
    性能优化: 使用deque管理采样数据
    - deque.popleft()是O(1), list.pop(0)是O(n)
    - maxlen自动限制大小(60秒窗口/2秒间隔=30样本)
    """
    current_kg: float = 0.0           # 当前油量
    initial_kg: float = 0.0           # 起飞油量（来自Mfuel0）
    
    # 采样缓冲（使用deque，maxlen=30对应60秒窗口/2秒间隔）
    samples: deque = field(default_factory=lambda: deque(maxlen=30))
    last_sample_time: float = 0.0     # 上次采样时间
    
    # 计算结果
    consumption_rate: float = 0.0     # 油耗率 (kg/min)
    rate_stable: bool = False         # 油耗率是否稳定
    
    def update(self, fuel_kg: float, fuel0_kg: float, altitude_m: float, 
               ias_kmh: float, now: float) -> None:
        """更新燃油状态
        
        Args:
            fuel_kg: 当前油量
            fuel0_kg: 起飞油量（API提供）
            altitude_m: 当前高度
            ias_kmh: 指示空速
            now: 当前时间戳
        """
        self.current_kg = fuel_kg
        
        # 更新起飞油量（只在有效时更新）
        if fuel0_kg > 0:
            self.initial_kg = fuel0_kg
        
        # 检测补给（油量突增）→ 清空历史
        if self.samples and fuel_kg > self.samples[-1].fuel_kg + FuelConfig.REFUEL_JUMP_KG:
            self.samples.clear()
            self.rate_stable = False
            self.consumption_rate = 0.0
            # 补给后更新起飞油量
            if fuel0_kg > 0:
                self.initial_kg = fuel0_kg
            self.last_sample_time = now
            return
        
        # 低速时不采样（地面或悬停）
        if ias_kmh < FuelConfig.MIN_FLIGHT_SPEED_KMH:
            return
        
        # 控制采样频率
        if (now - self.last_sample_time) < FuelConfig.SAMPLE_INTERVAL_SEC:
            return
        
        # 添加新样本（deque自动丢弃超出maxlen的旧样本）
        self.samples.append(FuelSample(now, fuel_kg, altitude_m))
        self.last_sample_time = now
        
        # 清理过期样本（补充清理，处理时间间隔不均匀的情况）
        cutoff = now - FuelConfig.SAMPLE_WINDOW_SEC
        while self.samples and self.samples[0].timestamp < cutoff:
            self.samples.popleft()  # O(1) 操作
        
        # 计算油耗率
        self._calculate_consumption_rate()
    
    def _calculate_consumption_rate(self) -> None:
        """计算油耗率（kg/min）"""
        if len(self.samples) < FuelConfig.MIN_STABLE_SAMPLES:
            self.rate_stable = False
            return
        
        oldest = self.samples[0]
        newest = self.samples[-1]
        dt_min = (newest.timestamp - oldest.timestamp) / 60.0
        
        if dt_min < 0.1:  # 至少6秒数据
            self.rate_stable = False
            return
        
        fuel_used = oldest.fuel_kg - newest.fuel_kg
        if fuel_used < 0:
            # 油量增加了（可能是数据抖动），忽略
            self.rate_stable = False
            return
        
        self.consumption_rate = fuel_used / dt_min
        self.rate_stable = True
    
    def reset(self) -> None:
        """重置燃油状态"""
        self.current_kg = 0.0
        self.initial_kg = 0.0
        self.samples.clear()
        self.last_sample_time = 0.0
        self.consumption_rate = 0.0
        self.rate_stable = False
    
    @property
    def fuel_percent(self) -> float:
        """剩余油量百分比"""
        if self.initial_kg <= 0:
            return 0.0
        return min(100.0, (self.current_kg / self.initial_kg) * 100)
    
    @property
    def remaining_time_min(self) -> Optional[float]:
        """剩余飞行时间（分钟）"""
        if not self.rate_stable or self.consumption_rate <= 0:
            return None
        return self.current_kg / self.consumption_rate
    
    def estimate_return_fuel(self, distance_km: float, ground_speed_kmh: float) -> Optional[float]:
        """估算返航所需油量（kg）
        
        Args:
            distance_km: 到友方机场距离（km）
            ground_speed_kmh: 地速（km/h）
        
        Returns:
            返航所需油量（kg），无法估算时返回None
        """
        if not self.rate_stable or ground_speed_kmh < 50 or distance_km <= 0:
            return None
        
        time_hours = distance_km / ground_speed_kmh
        time_min = time_hours * 60
        return self.consumption_rate * time_min * FuelConfig.RETURN_SAFETY_FACTOR
    
    def get_return_status(self, return_fuel_needed: Optional[float]) -> str:
        """获取返航状态
        
        Args:
            return_fuel_needed: 返航所需油量
        
        Returns:
            "safe" / "warning" / "danger" / "unknown"
        """
        if return_fuel_needed is None or return_fuel_needed <= 0:
            return "unknown"
        
        if self.current_kg >= return_fuel_needed * FuelConfig.RETURN_WARNING_FACTOR:
            return "safe"
        elif self.current_kg >= return_fuel_needed:
            return "warning"
        else:
            return "danger"


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
    should_play_destroyed_sound: bool = False                    # 是否应该播放摧毁音效（v5.5新增）
    
    # 地速计算相关（v5.2新增）
    last_pos: Optional[Tuple[float, float]] = None  # 上次位置
    last_pos_ts: float = 0.0                        # 上次位置时间戳
    ground_speed: float = 0.0                       # 地速（归一化单位/秒）
    
    # v5.7: 目标锁定相关（智能目标切换）
    locked_target_id: Optional[str] = None          # 当前锁定的目标ID（粘性）
    precise_aim_candidate_id: Optional[str] = None  # 精确对准候选目标ID
    precise_aim_since: float = 0.0                  # 开始精确对准的时间戳


@dataclass
class GameState:
    """游戏总体状态
    
    所有游戏逻辑状态的集合，由GameLogic类管理。
    """
    phase: Phase = Phase.IDLE                                    # 当前阶段
    # v6.0.1 新增：弹道计算缓存（在tick线程计算，减少UI线程负载）
    cached_bomb_flight_time: float = 0.0
    cached_bomb_range_m: float = 0.0
    cached_release_distance_m: float = 0.0
    cached_time_to_release: float = 0.0
    cached_release_status: str = "invalid"
    cached_target_distance_m: float = 0.0
    bombing_calc_valid: bool = False
    last_bombing_calc_time: float = 0.0
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
    
    # v5.8 新增：燃油状态
    fuel_state: FuelState = field(default_factory=FuelState)
    
    # v6.6.0 新增：起落架进度追踪
    last_gear_pct: float = 0.0                                   # 上一帧起落架百分比（用于判断方向）


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
    cdi_indicator: str = ""  # 航道偏差指示器字符串
    cdi_color: str = ""      # 指示器颜色


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
    cdi_indicator: str = ""  # 航道偏差指示器字符串
    cdi_color: str = ""      # 指示器颜色


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
    should_play_destroyed_sound: bool = False  # v5.5新增：是否应该播放摧毁音效
    
    player_heading: float = 0.0
    
    # v5.8 新增：燃油管理
    fuel_kg: float = 0.0                       # 当前油量
    fuel_initial_kg: float = 0.0               # 起飞油量
    fuel_percent: float = 0.0                  # 油量百分比
    fuel_rate_kg_min: float = 0.0              # 油耗率 (kg/min)
    fuel_rate_stable: bool = False             # 油耗率是否稳定
    fuel_time_remaining_str: str = ""          # 剩余飞行时间字符串
    altitude_m: float = 0.0                    # 高度
    
    # 返航估算
    return_fuel_needed_kg: float = 0.0         # 返航所需油量
    return_status: str = "unknown"             # "safe"/"warning"/"danger"/"unknown"
    friendly_distance_km: float = 0.0          # 到友方机场距离
    
    # v5.9.6 新增：起落架警告
    gear_warning: bool = False                 # 起落架未收起警告
    
    # v6.6.0 新增：起落架进度指示器
    gear_pct: float = 0.0                      # 起落架位置百分比 (0-100)
    gear_moving: bool = False                  # 起落架是否正在移动
    gear_retracting: bool = False              # 是否正在收起（True=收起/蓝色，False=放下/黄色）
    
    # v6.0 新增：投弹预测
    bombing_valid: bool = False                # 投弹预测是否有效
    bomb_name: str = ""                        # 当前炸弹名称
    bomb_range_m: float = 0.0                  # 炸弹水平飞行距离 (米)
    bomb_flight_time: float = 0.0              # 炸弹飞行时间 (秒)
    release_distance_m: float = 0.0            # 投弹距离 (米)
    time_to_release: float = 0.0               # 到投弹点时间 (秒)
    release_status: str = "invalid"            # ready/approaching/too_far/passed/invalid
    target_zone_distance_m: float = 0.0        # 目标战区距离 (米)
    ground_speed_kmh: float = 0.0              # 地速 (km/h)


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
            
            # v5.8 新增：解析燃油管理相关字段
            data.fuel0_kg = float(j.get("Mfuel0, kg", 0) or 0)
            data.altitude_m = float(j.get("H, m", 0) or 0)
            data.tas_kmh = float(j.get("TAS, km/h", 0) or 0)
            data.throttle_pct = float(j.get("throttle 1, %", 0) or 0)
            
            # v5.9.6 + v6.6.0：解析起落架状态和百分比
            gear_pct = float(j.get("gear, %", 0) or 0)
            data.gear_pct = gear_pct  # v6.6.0: 保存原始百分比
            data.gear_down = (gear_pct > 50)  # 超过50%视为放下状态
        
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
    
    v6.0.1 优化：
    - Session禁用代理检查，减少网络延迟
    - 弹道计算移至tick线程，降低UI线程负载
    """
    
    def __init__(self):
        self._lock = threading.Lock()
        self.session = requests.Session()
        # 性能优化：禁用代理环境检查，减少每次请求的开销
        self.session.trust_env = False
        self.http = HttpJson(self.session)
        self.tel = TelemetryFetcher(self.http)
        self.map_info_fetcher = MapInfoFetcher(self.http)
        self.map = MapObjectsFetcher(self.http)
        self.state = GameState()
    
    @property
    def is_api_down(self) -> bool:
        """轻量级API状态检查（用于轮询间隔控制）
        
        避免在_poll_loop中生成完整snapshot只为检查api_down状态。
        """
        with self._lock:
            return self.state.api_down

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

            # v6.0.1 优化：弹道计算移至tick线程（每250ms计算一次，而非每50ms）
            self._update_bombing_calculation_locked(tel, now)
            
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
                
                # v5.8 新增：更新燃油状态
                if tel.state_resp_ok:
                    s.fuel_state.update(
                        fuel_kg=tel.fuel_kg,
                        fuel0_kg=tel.fuel0_kg,
                        altitude_m=tel.altitude_m,
                        ias_kmh=tel.ias_kmh,
                        now=now
                    )
                
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
        """更新战区导航状态(须在锁内调用)
        
        功能: 计算地速/检测战区摧毁/计算导航信息/选择目标战区
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
                    
                    # v5.5: 判断是否有感兴趣的战区被摧毁
                    has_interesting = any(
                        self._is_zone_of_interest(z, nav.target_zone)
                        for z in destroyed
                    )
                    nav.should_play_destroyed_sound = has_interesting
                else:
                    nav.should_play_destroyed_sound = False
            else:
                nav.should_play_destroyed_sound = False
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
        
        # [目标选择算法]
        # 核心原则:
        # 1. 目标粘性: 锁定后在90°内保持,避免频繁切换
        # 2. 精确对准优先: 持续对准(<5°)3秒后切换
        # 3. 角度优先于距离: ±45°内选角度最小的
        # 
        # 关键配置(ZoneConfig):
        # - HEADING_TOLERANCE=45 (角度门)
        # - TARGET_HOLD_ANGLE=90 (保持角度)
        # - PRECISE_AIM_THRESHOLD=5 (精确对准阈值)
        # - PRECISE_AIM_CONFIRM_SEC=3 (确认时间)
        
        # === 选择目标战区（v5.7改进：目标粘性 + 精确对准切换）===
        # === v5.9改进：角度门内优先选择角度最小的目标 ===
        target = None
        is_airborne = not tel.is_on_ground  # 判断是否在空中
        
        if is_airborne and zones_with_nav:
            # 创建ID到Zone的映射，方便查找
            zone_by_id = {z.id: z for z in zones_with_nav}
            
            # Step 1: 检查当前锁定目标是否仍然有效
            locked_zone = None
            if nav.locked_target_id and nav.locked_target_id in zone_by_id:
                locked_zone = zone_by_id[nav.locked_target_id]
                # 目标仍在前方（<90°）则保持
                if abs(locked_zone.relative) <= ZoneConfig.TARGET_HOLD_ANGLE:
                    target = locked_zone
                else:
                    # 目标超出视野，清除锁定
                    nav.locked_target_id = None
                    locked_zone = None
            else:
                # 目标消失，清除锁定
                nav.locked_target_id = None
            
            # Step 2: 检测精确对准（<5°）的候选目标
            # ⚠️ 从精确对准范围内选择角度最小的目标（不是距离最近的）
            precise_candidates = [z for z in zones_with_nav 
                                  if abs(z.relative) <= ZoneConfig.PRECISE_AIM_THRESHOLD]
            precise_candidate = None
            if precise_candidates:
                # 按角度排序，选择角度最小的
                precise_candidate = min(precise_candidates, key=lambda z: abs(z.relative))
            
            if precise_candidate:
                # 检查是否是新的候选目标
                if nav.precise_aim_candidate_id != precise_candidate.id:
                    # 新候选，重置计时
                    nav.precise_aim_candidate_id = precise_candidate.id
                    nav.precise_aim_since = now
                else:
                    # 相同候选，检查是否超过确认时间
                    aim_duration = now - nav.precise_aim_since
                    if aim_duration >= ZoneConfig.PRECISE_AIM_CONFIRM_SEC:
                        # 确认切换到新目标
                        if nav.locked_target_id != precise_candidate.id:
                            nav.locked_target_id = precise_candidate.id
                            target = precise_candidate
            else:
                # 没有精确对准的目标，清除候选
                nav.precise_aim_candidate_id = None
                nav.precise_aim_since = 0.0
            
            # Step 3: 如果还没有目标，从45°角度门内选择角度最小的
            # ⚠️ 优先角度最小，而不是距离最近
            if target is None:
                candidates_in_gate = [z for z in zones_with_nav 
                                      if abs(z.relative) <= ZoneConfig.HEADING_TOLERANCE]
                if candidates_in_gate:
                    # 按角度排序，选择角度最小的
                    best_candidate = min(candidates_in_gate, key=lambda z: abs(z.relative))
                    target = best_candidate
                    nav.locked_target_id = best_candidate.id
        else:
            # 在地面或无战区时，清除所有锁定状态
            nav.locked_target_id = None
            nav.precise_aim_candidate_id = None
            nav.precise_aim_since = 0.0
        
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

    def _is_zone_of_interest(self, zone: Zone, target_zone: Optional[Zone]) -> bool:
        """判断战区是否是玩家感兴趣的（v5.5新增）
        
        判断标准：
        1. 是当前目标战区 → 关注
        2. 后方战区（>90°）→ 不关注
        3. 前方近距离战区：≤75° 且 <35km → 关注
        4. 正前方中距离战区：≤45° 且 <60km → 关注
        
        Args:
            zone: 待判断的战区
            target_zone: 当前目标战区
        
        Returns:
            True 表示该战区是感兴趣的
        """
        # 1. 是当前目标战区
        if target_zone and zone.id == target_zone.id:
            return True
        
        abs_relative = abs(zone.relative)
        
        # 2. 后方战区（>90°）不关注
        if abs_relative > 90:
            return False
        
        # 3. 前方战区需要结合距离判断
        distance_km = zone.distance * ZoneConfig.DISTANCE_SCALE
        
        # 前方近距离：≤75° 且 <35km
        if abs_relative <= 75 and distance_km < 35:
            return True
        
        # 正前方中距离：≤45° 且 <60km
        if abs_relative <= 45 and distance_km < 60:
            return True
        
        # 其他情况（前方远距离或大角度）不关注
        return False

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
                # ETE计算（仅目标战区）
                ete_text = ""
                if zone.is_target and gs > 1e-7:
                    seconds_left = zone.distance / gs
                    if seconds_left < 5999:
                        m, s_time = divmod(int(seconds_left), 60)
                        ete_text = f"{m:02d}:{s_time:02d}"
                
                # CDI指示器（仅目标战区显示）
                cdi_str = ""
                cdi_clr = ""
                if zone.is_target:
                    # 转换距离单位为公里
                    dist_km = zone.distance * ZoneConfig.DISTANCE_SCALE
                    # 接收函数返回的两个值：指示器字符串和颜色
                    cdi_str, cdi_clr = generate_cdi_indicator(zone.relative, dist_km)

                # 所有战区都添加到显示列表（CDI仅目标战区有值）
                zone_display_list.append(ZoneDisplayInfo(
                    id=zone.id, grid=zone.grid, 
                    distance_km=zone.distance * ZoneConfig.DISTANCE_SCALE,
                    direction=get_direction_text(zone.relative), 
                    relative=zone.relative, is_target=zone.is_target,
                    ete_str=ete_text,
                    cdi_indicator=cdi_str,
                    cdi_color=cdi_clr
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
                    # CDI指示器（友方机场始终显示）
                    cdi_str, cdi_clr = generate_cdi_indicator(info.relative, info.distance_km)
                    friendly_airfield_display = AirfieldDisplayInfo(
                        id=info.id, side=info.side, grid=info.grid,
                        distance_km=info.distance_km, direction=info.direction, 
                        relative=info.relative,
                        is_target=True, ete_str=ete_text,
                        cdi_indicator=cdi_str, cdi_color=cdi_clr
                    )

                # 敌方机场：显示所有，但只在朝向时显示ETE（v5.7改进）
                if enemy_infos:
                    enemy_infos.sort(key=lambda t: t[0])
                    # 查找45°内最近的敌方机场作为目标
                    target_idx = -1  # -1表示没有目标
                    for i, (dist, info) in enumerate(enemy_infos):
                        if abs(info.relative) <= ZoneConfig.ENEMY_AIRFIELD_ETE_ANGLE:
                            target_idx = i
                            break

                    for i, (dist, info) in enumerate(enemy_infos):
                        is_target = (i == target_idx)
                        ete_text = ""
                        cdi_str = ""
                        cdi_clr = ""
                        # 只在目标机场且在航向前方（<45°）时显示ETE和CDI
                        if is_target and abs(info.relative) <= ZoneConfig.ENEMY_AIRFIELD_ETE_ANGLE and nav.ground_speed > 1e-7:
                            seconds_left = dist / nav.ground_speed
                            if seconds_left < 3600:
                                mm, ss = divmod(int(seconds_left), 60)
                                ete_text = f"{mm:02d}:{ss:02d}"
                            cdi_str, cdi_clr = generate_cdi_indicator(info.relative, info.distance_km)
                        enemy_airfields_display.append(AirfieldDisplayInfo(
                            id=info.id, side=info.side, grid=info.grid,
                            distance_km=info.distance_km, direction=info.direction, 
                            relative=info.relative,
                            is_target=is_target, ete_str=ete_text,
                            cdi_indicator=cdi_str, cdi_color=cdi_clr
                        ))
                    has_airfield_target = (target_idx >= 0)
            
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

            # v5.8 新增：燃油管理数据
            fuel = s.fuel_state
            fuel_kg = fuel.current_kg
            fuel_initial_kg = fuel.initial_kg
            fuel_percent = fuel.fuel_percent
            fuel_rate_kg_min = fuel.consumption_rate if fuel.rate_stable else 0.0
            fuel_rate_stable = fuel.rate_stable
            altitude_m = tel.altitude_m
            
            # 剩余飞行时间字符串
            fuel_time_remaining_str = ""
            remaining_min = fuel.remaining_time_min
            if remaining_min is not None:
                if remaining_min > 60:
                    fuel_time_remaining_str = ">60:00"
                else:
                    rm, rs = divmod(int(remaining_min * 60), 60)
                    fuel_time_remaining_str = f"{rm:02d}:{rs:02d}"
            
            # 返航估算
            return_fuel_needed_kg = 0.0
            return_status = "unknown"
            friendly_distance_km = 0.0
            
            if friendly_airfield_display and nav.ground_speed > 0:
                friendly_distance_km = friendly_airfield_display.distance_km
                # 将地速转换为 km/h
                ground_speed_kmh = nav.ground_speed * ZoneConfig.DISTANCE_SCALE * 3600
                return_fuel_needed = fuel.estimate_return_fuel(friendly_distance_km, ground_speed_kmh)
                if return_fuel_needed is not None:
                    return_fuel_needed_kg = return_fuel_needed
                    return_status = fuel.get_return_status(return_fuel_needed)
            
            # v5.9.6 新增：起落架警告判断
            # 判断条件：在空中（速度>80km/h 或 高度>50m）且起落架未收起
            gear_warning = False
            if s.phase == Phase.ALIVE and tel.state_resp_ok:
                is_airborne = (tel.ias_kmh > 80) or (tel.altitude_m > 50)
                # gear_down=True 表示起落架放下（未收起）
                if is_airborne and tel.gear_down:
                    gear_warning = True
            
            # v6.6.0 新增：起落架进度指示器
            gear_pct = tel.gear_pct
            gear_moving = (0 < gear_pct < 100)  # 正在移动 = 不在两端
            gear_retracting = False
            if gear_moving:
                # 判断方向：当前百分比 < 上一帧百分比 = 正在收起
                gear_retracting = (gear_pct < s.last_gear_pct)
            # 更新上一帧百分比用于下次判断
            s.last_gear_pct = gear_pct

            # v6.0.1 优化：从缓存读取弹道计算结果（计算已移至tick线程）
            bombing_valid = False
            bomb_name = BombConfig.selected_bomb if ENABLE_CCRP else ""
            bomb_range_m = 0.0
            bomb_flight_time = 0.0
            release_distance_m = 0.0
            time_to_release = 0.0
            release_status = "invalid"
            target_zone_distance_m = 0.0
            ground_speed_kmh_for_bombing = nav.ground_speed * ZoneConfig.DISTANCE_SCALE * 3600
            
            # 从缓存读取弹道计算结果（避免在UI线程重复计算）
            if ENABLE_CCRP and s.bombing_calc_valid:
                bombing_valid = True
                bomb_flight_time = s.cached_bomb_flight_time
                bomb_range_m = s.cached_bomb_range_m
                release_distance_m = s.cached_release_distance_m
                time_to_release = s.cached_time_to_release
                release_status = s.cached_release_status
                target_zone_distance_m = s.cached_target_distance_m

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
                should_play_destroyed_sound=nav.should_play_destroyed_sound,
                player_heading=nav.player_heading,
                # v5.8 新增：燃油管理字段
                fuel_kg=fuel_kg,
                fuel_initial_kg=fuel_initial_kg,
                fuel_percent=fuel_percent,
                fuel_rate_kg_min=fuel_rate_kg_min,
                fuel_rate_stable=fuel_rate_stable,
                fuel_time_remaining_str=fuel_time_remaining_str,
                altitude_m=altitude_m,
                return_fuel_needed_kg=return_fuel_needed_kg,
                return_status=return_status,
                friendly_distance_km=friendly_distance_km,
                # v5.9.6 新增：起落架警告
                gear_warning=gear_warning,
                # v6.6.0 新增：起落架进度指示器
                gear_pct=gear_pct,
                gear_moving=gear_moving,
                gear_retracting=gear_retracting,
                # v6.0 新增：投弹预测
                bombing_valid=bombing_valid,
                bomb_name=bomb_name,
                bomb_range_m=bomb_range_m,
                bomb_flight_time=bomb_flight_time,
                release_distance_m=release_distance_m,
                time_to_release=time_to_release,
                release_status=release_status,
                target_zone_distance_m=target_zone_distance_m,
                ground_speed_kmh=ground_speed_kmh_for_bombing,
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
        s.fuel_state.reset()  # v5.8 新增：重置燃油状态

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
    def _update_bombing_calculation_locked(self, tel: TelemetryData, now: float):
        """更新弹道计算缓存（必须在锁内调用）
        
        v6.0.1 优化：将弹道计算从UI线程(50ms)移至tick线程(250ms)
        减少UI线程的计算负载，提高界面流畅度
        """
        s = self.state
        nav = s.zone_nav
        
        # 检查是否需要计算
        if not ENABLE_CCRP:
            s.bombing_calc_valid = False
            return
        
        # 计算频率控制：至少间隔200ms
        if (now - s.last_bombing_calc_time) < 0.2:
            return
        
        s.last_bombing_calc_time = now
        
        # 检查计算条件
        has_target = nav.target_zone is not None
        on_ground = tel.is_on_ground
        altitude_m = tel.altitude_m
        
        if not (has_target and s.phase == Phase.ALIVE and 
                not on_ground and altitude_m > 50 and 
                nav.ground_speed > 0.0002):
            s.bombing_calc_valid = False
            return
        
        # 执行弹道计算
        target_zone = nav.target_zone
        target_distance_m = target_zone.distance * ZoneConfig.DISTANCE_SCALE * 1000
        ground_speed_ms = nav.ground_speed * ZoneConfig.DISTANCE_SCALE * 1000
        
        bomb_params = BombConfig.get_bomb_physics_params()
        
        flight_time, bomb_range_m, _ = calculate_bomb_trajectory(
            release_alt_m=altitude_m,
            release_speed_ms=ground_speed_ms,
            target_alt_m=0.0,
            dive_angle_deg=0.0,
            initial_vz_ms=None,
            bomb_params=bomb_params
        )
        
        if bomb_range_m > 0:
            release_distance_m, time_to_release, release_status = calculate_release_timing(
                current_distance_m=target_distance_m,
                current_alt_m=altitude_m,
                ground_speed_ms=ground_speed_ms,
                target_alt_m=0.0,
                dive_angle_deg=0.0,
                initial_vz_ms=None
            )
            
            # 缓存结果
            s.cached_bomb_flight_time = flight_time
            s.cached_bomb_range_m = bomb_range_m
            s.cached_release_distance_m = release_distance_m
            s.cached_time_to_release = time_to_release
            s.cached_release_status = release_status
            s.cached_target_distance_m = target_distance_m
            s.bombing_calc_valid = True
        else:
            s.bombing_calc_valid = False


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
class HeadingTape(tk.Canvas):
    """统一航向带指示器 (Heading Tape)
    
    v6.2重构: 合并战区/机场到同一航向带，支持多目标显示
    
    目标类型及标记:
    - zone: 战区目标 - 红色标靶 ⊚
    - friendly: 友方机场 - 蓝色飞机 ✈
    - enemy: 敌方机场 - 橙色飞机 ✈
    - destroyed: 被摧毁战区 - 灰色X ✕
    
    特性:
    - 同时显示多个不同类型的目标
    - 主目标（战区）有偏航提示
    - 被摧毁的战区用特殊标记显示
    """
    
    def __init__(self, parent, width: int = 280, height: int = 36, **kwargs):
        """初始化航向带
        
        Args:
            parent: 父容器
            width: 宽度(像素)
            height: 高度(像素)
        """
        super().__init__(parent, width=width, height=height, 
                        bg=Theme.GRAYPILL, highlightthickness=0, **kwargs)
        self.tape_width = width
        self.tape_height = height
        self.pixels_per_degree = ZoneConfig.HEADING_TAPE_PIXELS_PER_DEG
        self._current_hdg = 0.0
        self._primary_target = None
        
        # 目标类型颜色配置
        self._target_colors = {
            "zone": Theme.RED,
            "friendly": Theme.BLUE,
            "enemy": Theme.ORANGE,
            "destroyed": Theme.TEXT_MUTED,
        }
    
    def update_tape_multi(self, current_hdg: float, targets: list = None,
                          primary_distance_km: float = 0.0):
        """更新航向带显示（多目标版本）
        
        Args:
            current_hdg: 当前航向(0-360°)
            targets: 目标列表，每个目标为dict:
                {
                    'type': 'zone'/'friendly'/'enemy'/'destroyed',
                    'relative': 相对角度(-180~180),
                    'distance_km': 距离(公里),
                    'is_primary': 是否主目标(用于偏航提示),
                    'name': 目标名称(可选)
                }
            primary_distance_km: 主目标距离(用于计算缩放)
        """
        self.delete("all")
        self._current_hdg = current_hdg
        
        if targets is None:
            targets = []
        
        # 找出主目标（用于偏航提示和缩放计算）
        primary = next((t for t in targets if t.get('is_primary')), None)
        self._primary_target = primary
        
        # 1. 动态计算缩放系数（基于主目标距离）
        dist_for_scale = primary_distance_km if primary_distance_km > 0 else (
            primary['distance_km'] if primary else 10.0
        )
        scale_factor = calculate_heading_tape_scale(dist_for_scale)
        ppd = self.pixels_per_degree * scale_factor
        
        center_x = self.tape_width / 2
        
        # 2. 检查主目标是否在视野外（用于偏航提示）
        primary_diff = 0.0
        primary_in_view = True
        if primary:
            primary_diff = primary['relative']
            primary_x = center_x + primary_diff * ppd
            primary_in_view = (0 <= primary_x <= self.tape_width)
            
            # 主目标在视野外时，绘制偏航背景
            if not primary_in_view:
                if primary_diff < 0:
                    self.create_rectangle(0, 0, 50, self.tape_height, 
                                         fill=Theme.RED, stipple="gray50", outline="")
                else:
                    self.create_rectangle(self.tape_width - 50, 0, self.tape_width, self.tape_height,
                                         fill=Theme.RED, stipple="gray50", outline="")
        
        # 3. 绘制背景分割线
        self.create_line(0, self.tape_height - 1, self.tape_width, self.tape_height - 1, 
                        fill=Theme.BORDER, width=1)
        
        # 4. 绘制刻度
        visible_degrees = self.tape_width / ppd
        start_deg = current_hdg - visible_degrees / 2 - 5
        end_deg = current_hdg + visible_degrees / 2 + 5
        
        for d in range(int(start_deg) - 1, int(end_deg) + 2):
            display_d = d % 360
            if display_d < 0:
                display_d += 360
            
            diff = d - current_hdg
            while diff > 180:
                diff -= 360
            while diff < -180:
                diff += 360
            
            x = center_x + diff * ppd
            
            if x < -20 or x > self.tape_width + 20:
                continue
            
            if display_d % 10 == 0:
                self.create_line(x, 2, x, 14, fill=Theme.TEXT, width=2)
                self.create_text(x, 22, text=f"{display_d:03d}", fill=Theme.TEXT, 
                               font=("Consolas", 8), anchor="n")
            elif display_d % 5 == 0:
                self.create_line(x, 4, x, 12, fill=Theme.TEXT_DIM, width=1)
            elif scale_factor >= 2.0:
                self.create_line(x, 6, x, 10, fill=Theme.TEXT_MUTED, width=1)
        
        # 5. 绘制所有目标标记（按优先级：destroyed < enemy < friendly < zone）
        sorted_targets = sorted(targets, key=lambda t: {
            'destroyed': 0, 'enemy': 1, 'friendly': 2, 'zone': 3
        }.get(t.get('type', 'zone'), 2))
        
        for target in sorted_targets:
            t_type = target.get('type', 'zone')
            t_rel = target.get('relative', 0)
            t_is_primary = target.get('is_primary', False)
            t_is_target = target.get('is_target', True)  # v6.3: 是否为活动目标
            t_distance = target.get('distance_km', 0)  # v6.4.1: 获取目标自身距离
            
            t_x = center_x + t_rel * ppd
            in_view = (0 <= t_x <= self.tape_width)
            
            if in_view:
                self._draw_target_marker(t_x, t_type, t_is_primary, t_rel, 
                                        primary['distance_km'] if primary else 10.0,
                                        is_target=t_is_target,
                                        show_distance=t_distance)
            else:
                # 视野外目标显示小箭头（只显示活动目标）
                if t_is_target:
                    self._draw_overflow_indicator(t_rel, t_type, t_distance)
        
        # 6. 主目标在视野外时的大箭头提示
        if primary and not primary_in_view:
            self._draw_primary_overflow(primary_diff)
        
        # 7. 绘制中心基准线（机头指向）
        self.create_line(center_x, 0, center_x, self.tape_height, 
                        fill=Theme.GREEN, width=2, dash=(3, 2))
        tri_size = 5
        self.create_polygon(
            center_x, 0,
            center_x - tri_size, tri_size + 2,
            center_x + tri_size, tri_size + 2,
            fill=Theme.GREEN, outline=""
        )
    
    def _draw_target_marker(self, x: float, t_type: str, is_primary: bool, 
                           relative: float, distance_km: float, is_target: bool = True,
                           show_distance: float = 0):
        """绘制目标标记
        
        Args:
            x: X坐标
            t_type: 目标类型
            is_primary: 是否主目标
            relative: 相对角度
            distance_km: 距离（用于颜色计算）
            is_target: 是否为活动目标（v6.3新增）
            show_distance: 显示的距离值（v6.4.1新增，0表示不显示）
        """
        # v6.3: 根据是否为目标调整颜色和透明度
        base_color = self._target_colors.get(t_type, Theme.TEXT)
        
        if not is_target:
            # 非目标：使用暗淡颜色
            color_map = {
                Theme.RED: "#8B4545",      # 暗红
                Theme.BLUE: "#4A5A8B",     # 暗蓝
                Theme.ORANGE: "#B8774A",   # 暗橙
            }
            color = color_map.get(base_color, Theme.TEXT_MUTED)
        else:
            color = base_color
        # 根据高度计算图标缩放（基于32px基准高度）
        icon_scale = self.tape_height / 32.0
        # v6.5.2: 图标偏上，给底部距离标签留空间
        y_center = int(self.tape_height * 0.42)
        
        # v6.6.0: 重构距离显示 - 位置调整到图标下方，颜色继承偏差色
        if show_distance > 0 and is_target:
            self._draw_distance_label(x, show_distance, t_type, is_primary, icon_scale, y_center, relative)
        
        if t_type == 'zone':
            # v6.3: 战区标靶 - 区分目标和非目标
            # v6.5.2: 调小尺寸，给距离标签腾空间
            if is_primary:
                size = int(8 * icon_scale)
                # 主目标根据精度调整颜色
                tolerance = get_cdi_tolerance(distance_km)
                abs_rel = abs(relative)
                if abs_rel < 0.2:
                    color = "#FF4444"  # 亮红
                elif abs_rel < tolerance * 0.5:
                    color = Theme.RED
                elif abs_rel < tolerance:
                    color = "#CC3333"  # 暗红
                else:
                    color = Theme.ORANGE  # 偏航时变橙
                # 绘制实心标靶（外圈+内圈）
                self.create_oval(x - size, y_center - size, x + size, y_center + size,
                               outline=color, width=2, fill="")
                inner_size = size * 0.5
                self.create_oval(x - inner_size, y_center - inner_size, 
                               x + inner_size, y_center + inner_size,
                               fill=color, outline="")
            elif is_target:
                # 活动目标但非主目标：中等大小，实心
                size = int(6 * icon_scale)
                self.create_oval(x - size, y_center - size, x + size, y_center + size,
                               outline=color, width=2, fill="")
                inner_size = size * 0.5
                self.create_oval(x - inner_size, y_center - inner_size, 
                               x + inner_size, y_center + inner_size,
                               fill=color, outline="")
            else:
                # 非目标战区：空心虚线圈（v6.4: 更明显的虚线样式）
                size = int(6 * icon_scale)
                self.create_oval(x - size, y_center - size, x + size, y_center + size,
                               outline=color, width=2, fill="", dash=(4, 3))
                # 添加小中心点提高可见度
                dot_size = 2
                self.create_oval(x - dot_size, y_center - dot_size, 
                               x + dot_size, y_center + dot_size,
                               fill=color, outline="")
            
        elif t_type == 'friendly':
            # v6.3: 友方机场 - 根据是否为目标调整大小
            # v6.5.2: 调小尺寸
            size = int((7 if is_target else 5) * icon_scale)
            width = 2 if is_target else 1
            self._draw_aircraft_icon(x, y_center, color, size=size, width=width)
            
        elif t_type == 'enemy':
            # v6.3: 敌方机场 - 根据是否为目标调整大小
            # v6.5.2: 调小尺寸
            size = int((7 if is_target else 5) * icon_scale)
            width = 2 if is_target else 1
            self._draw_aircraft_icon(x, y_center, color, size=size, width=width)
            
        elif t_type == 'destroyed':
            # 被摧毁：灰色X标记（v6.4: 更大更粗更易识别）
            size = int(6 * icon_scale)
            line_width = 2
            self.create_line(x - size, y_center - size, x + size, y_center + size,
                           fill=color, width=line_width)
            self.create_line(x - size, y_center + size, x + size, y_center - size,
                           fill=color, width=line_width)
    
    def _draw_aircraft_icon(self, x: float, y: float, color: str, size: int = 7, width: int = 2):
        """绘制飞机图标（v6.4: 更粗更易识别）"""
        base_width = max(2, width)
        # 机身（垂直线，加粗）
        self.create_line(x, y - size, x, y + size * 0.7, fill=color, width=base_width + 1)
        # 主翼（水平线，加粗）
        wing_y = y - size * 0.15
        self.create_line(x - size * 1.1, wing_y, x + size * 1.1, wing_y, fill=color, width=base_width)
        # 尾翼
        tail_y = y + size * 0.55
        self.create_line(x - size * 0.55, tail_y, x + size * 0.55, tail_y, fill=color, width=base_width)
        # 机头标记（小三角形）
        head_size = size * 0.25
        self.create_polygon(
            x, y - size - head_size,
            x - head_size, y - size + head_size * 0.5,
            x + head_size, y - size + head_size * 0.5,
            fill=color, outline=""
        )
    
    def _draw_distance_label(self, x: float, distance: float, t_type: str, 
                             is_primary: bool, icon_scale: float, y_center: int,
                             relative_angle: float = 0.0):
        """v6.6.0 重构：绘制距离标签（图标下方，继承偏差颜色）
        
        根据目标类型和距离显示不同样式的标签：
        - 位置：图标下方（航向带底部）
        - 颜色：继承当前航道偏差颜色
        - 精度：动态精度（>20km整数，5-20km一位小数，<5km一位小数或米）
        
        Args:
            x: X坐标
            distance: 距离（公里）
            t_type: 目标类型
            is_primary: 是否主目标
            icon_scale: 图标缩放系数
            y_center: 图标中心Y坐标
            relative_angle: 相对角度（用于计算偏差颜色）
        """
        # v6.6.0: 距离标签放在图标下方（航向带底部）
        dist_y = self.tape_height - 2
        
        # v6.6.0: 使用动态精度格式化距离
        dist_text = format_distance_dynamic(distance)
        
        # v6.6.0: 获取基于偏差的语义颜色
        deviation_color = get_deviation_color(relative_angle, distance)
        
        # 根据目标类型和距离确定样式
        font_size = max(7, int(9 * icon_scale))
        
        if t_type == 'zone':
            # v6.6.0: 战区距离标签 - 使用偏差颜色
            if is_primary:
                # 主目标：带底色的标签，底色基于偏差颜色
                # 计算底色（偏差颜色的暗化版本）
                bg_color = self._darken_color(deviation_color, 0.4)
                text_color = "#FFFFFF"
                
                # 绘制带底色的标签
                text_width = len(dist_text) * font_size * 0.6
                pad = 2
                self.create_rectangle(
                    x - text_width/2 - pad, dist_y - font_size,
                    x + text_width/2 + pad, dist_y + pad,
                    fill=bg_color, outline=""
                )
                self.create_text(x, dist_y, text=dist_text, fill=text_color,
                               font=("Consolas", font_size, "bold"), anchor="s")
            else:
                # 非主目标战区：直接使用偏差颜色
                self.create_text(x, dist_y, text=dist_text, fill=deviation_color,
                               font=("Consolas", font_size), anchor="s")
        
        elif t_type == 'friendly':
            # 友方机场：蓝色系 + ⌂ 标记
            bg_color = self._get_urgency_blue(distance)
            text_color = "#FFFFFF"
            
            # 友方机场添加"⌂"标记
            label_text = f"⌂{dist_text}"
            text_width = len(label_text) * font_size * 0.55
            pad = 2
            self.create_rectangle(
                x - text_width/2 - pad, dist_y - font_size,
                x + text_width/2 + pad, dist_y + pad,
                fill=bg_color, outline=""
            )
            self.create_text(x, dist_y, text=label_text, fill=text_color,
                           font=("Consolas", font_size, "bold"), anchor="s")
        
        elif t_type == 'enemy':
            # 敌方机场：橙色系，带"✖"标记
            urgency_color = self._get_urgency_orange(distance)
            label_text = f"✖{dist_text}"
            self.create_text(x, dist_y, text=label_text, fill=urgency_color,
                           font=("Consolas", font_size), anchor="s")
        
        else:
            # 其他类型：普通显示
            self.create_text(x, dist_y, text=dist_text, fill=Theme.TEXT_DIM,
                           font=("Consolas", font_size), anchor="s")
    
    def _darken_color(self, hex_color: str, factor: float) -> str:
        """v6.6.0: 暗化颜色
        
        Args:
            hex_color: 十六进制颜色 (如 "#FF0000")
            factor: 暗化系数 (0-1, 越小越暗)
        
        Returns:
            暗化后的颜色
        """
        try:
            hex_color = hex_color.lstrip('#')
            r = int(int(hex_color[0:2], 16) * factor)
            g = int(int(hex_color[2:4], 16) * factor)
            b = int(int(hex_color[4:6], 16) * factor)
            return f"#{r:02x}{g:02x}{b:02x}"
        except:
            return "#333333"
    
    def _get_urgency_blue(self, distance: float) -> str:
        """v6.6.0: 根据距离获取蓝色系紧急程度颜色"""
        if distance < 5:
            return "#3399FF"  # 亮蓝
        elif distance < 15:
            return "#2277CC"  # 蓝
        elif distance < 30:
            return "#225599"  # 暗蓝
        else:
            return "#224466"  # 很暗蓝
    
    def _get_urgency_orange(self, distance: float) -> str:
        """v6.6.0: 根据距离获取橙色系紧急程度颜色"""
        if distance < 5:
            return Theme.ORANGE
        elif distance < 15:
            return "#CC8844"
        elif distance < 30:
            return "#996633"
        else:
            return "#664422"
    
    def _draw_overflow_indicator(self, relative: float, t_type: str, distance: float = 0):
        """绘制视野外目标的小指示器（v6.5优化：增强区分度）
        
        Args:
            relative: 相对角度
            t_type: 目标类型
            distance: 目标距离（公里）
        """
        color = self._target_colors.get(t_type, Theme.TEXT_DIM)
        icon_scale = self.tape_height / 32.0
        # v6.5.2: 与图标位置保持一致
        y = int(self.tape_height * 0.42)
        tri_size = int(6 * icon_scale)
        
        # v6.5: 根据类型添加前缀标记
        prefix = ""
        if t_type == 'friendly':
            prefix = "⌂"
        elif t_type == 'enemy':
            prefix = "✖"
        elif t_type == 'zone':
            prefix = "●"
        
        # v6.5: 格式化距离文本
        dist_text = ""
        if distance > 0:
            if distance < 10:
                dist_text = f"{prefix}{distance:.1f}"
            else:
                dist_text = f"{prefix}{int(distance)}"
        elif prefix:
            dist_text = prefix
        
        font_size = max(6, int(7 * icon_scale))
        
        if relative < 0:
            # 左侧小三角
            self.create_polygon(2, y, 2 + tri_size, y - tri_size * 0.7, 
                              2 + tri_size, y + tri_size * 0.7, 
                              fill=color, outline="")
            # v6.5: 显示带前缀的距离
            if dist_text:
                self.create_text(2 + tri_size + 2, y, text=dist_text, fill=color,
                               font=("Consolas", font_size, "bold"), anchor="w")
        else:
            # 右侧小三角
            self.create_polygon(self.tape_width - 2, y, 
                              self.tape_width - 2 - tri_size, y - tri_size * 0.7, 
                              self.tape_width - 2 - tri_size, y + tri_size * 0.7,
                              fill=color, outline="")
            # v6.5: 显示带前缀的距离
            if dist_text:
                self.create_text(self.tape_width - 2 - tri_size - 2, y, text=dist_text, fill=color,
                               font=("Consolas", font_size, "bold"), anchor="e")
    
    def _draw_primary_overflow(self, diff: float):
        """绘制主目标的大偏航箭头"""
        # v6.5.2: 与图标位置保持一致
        y = int(self.tape_height * 0.42)
        
        if diff < 0:
            # 左侧大箭头
            arrow_points = [5, y, 25, y - 10, 20, y, 25, y + 10]
            self.create_polygon(arrow_points, fill=Theme.RED, outline=Theme.BG)
            self.create_text(40, y, text=f"◀ {abs(int(diff))}°",
                           fill=Theme.RED, font=("Arial", 10, "bold"), anchor="w")
        else:
            # 右侧大箭头
            arrow_points = [self.tape_width - 5, y, self.tape_width - 25, y - 10,
                          self.tape_width - 20, y, self.tape_width - 25, y + 10]
            self.create_polygon(arrow_points, fill=Theme.RED, outline=Theme.BG)
            self.create_text(self.tape_width - 40, y, text=f"{abs(int(diff))}° ▶",
                           fill=Theme.RED, font=("Arial", 10, "bold"), anchor="e")
    
    def update_tape(self, current_hdg: float, target_hdg: float = None, 
                    distance_km: float = 0.0, tolerance: float = 5.0,
                    target_name: str = ""):
        """兼容旧接口：单目标更新"""
        if target_hdg is None:
            self.update_tape_multi(current_hdg, [], distance_km)
        else:
            rel = target_hdg - current_hdg
            while rel > 180:
                rel -= 360
            while rel < -180:
                rel += 360
            targets = [{
                'type': 'zone',
                'relative': rel,
                'distance_km': distance_km,
                'is_primary': True
            }]
            self.update_tape_multi(current_hdg, targets, distance_km)
    
    def clear(self):
        """清除航向带"""
        self.delete("all")
        self._primary_target = None


class SettingsDialog(tk.Toplevel):
    """设置对话框
    
    使用选项卡组织设置项：
    - 显示：透明度、缩放、主题
    - 面板：各信息面板的显示开关
    - 快捷键：自定义热键绑定
    - 其他：吸附、全局热键等
    """
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.title("⚙️ 设置")
        self.resizable(False, False)
        self.configure(bg=Theme.BG)
        self.transient(parent)
        self.grab_set()
        self._build_ui()
        self._center_on_parent(parent)
    
    def _build_ui(self):
        # 主容器
        main = tk.Frame(self, bg=Theme.BG)
        main.pack(padx=15, pady=10, fill="both", expand=True)
        
        # 创建选项卡（使用Frame模拟，因为ttk样式在透明窗口中有问题）
        self.tab_buttons_frame = tk.Frame(main, bg=Theme.BG)
        self.tab_buttons_frame.pack(fill="x", pady=(0, 10))
        
        self.tabs = ["显示", "面板", "快捷键", "其他"]
        self.tab_frames = {}
        self.tab_btns = {}
        self.current_tab = "显示"
        
        # 选项卡按钮
        for tab in self.tabs:
            btn = tk.Button(
                self.tab_buttons_frame, text=tab, 
                bg=Theme.GRAYPILL, fg=Theme.TEXT, bd=0, padx=12, pady=4,
                command=lambda t=tab: self._switch_tab(t)
            )
            btn.pack(side="left", padx=2)
            self.tab_btns[tab] = btn
        
        # 选项卡内容容器
        self.content_frame = tk.Frame(main, bg=Theme.BG)
        self.content_frame.pack(fill="both", expand=True)
        
        # 创建各选项卡页面
        self._build_display_tab()
        self._build_panel_tab()
        self._build_hotkey_tab()
        self._build_other_tab()
        
        # 按钮行
        btn_frame = tk.Frame(main, bg=Theme.BG)
        btn_frame.pack(fill="x", pady=(15, 0))
        tk.Button(btn_frame, text="保存", command=self._save, 
                 bg=Theme.BLUE, fg=Theme.TEXT, bd=0, padx=20, pady=5).pack(side="right", padx=5)
        tk.Button(btn_frame, text="取消", command=self.destroy, 
                 bg=Theme.GRAYPILL, fg=Theme.TEXT, bd=0, padx=20, pady=5).pack(side="right", padx=5)
        
        # 显示第一个选项卡
        self._switch_tab("显示")
    
    def _switch_tab(self, tab_name: str):
        """切换选项卡"""
        # 隐藏所有页面
        for frame in self.tab_frames.values():
            frame.pack_forget()
        
        # 更新按钮样式
        for name, btn in self.tab_btns.items():
            if name == tab_name:
                btn.config(bg=Theme.BLUE)
            else:
                btn.config(bg=Theme.GRAYPILL)
        
        # 显示当前页面
        if tab_name in self.tab_frames:
            self.tab_frames[tab_name].pack(fill="both", expand=True)
        
        self.current_tab = tab_name
    
    def _build_display_tab(self):
        """构建显示设置页"""
        frame = tk.Frame(self.content_frame, bg=Theme.BG)
        self.tab_frames["显示"] = frame
        
        row = 0
        
        # 透明度
        tk.Label(frame, text="窗口透明度:", bg=Theme.BG, fg=Theme.TEXT).grid(
            row=row, column=0, sticky="w", pady=5)
        self.alpha_var = tk.IntVar(value=UIConfig.WINDOW_ALPHA)
        tk.Scale(frame, from_=100, to=255, orient="horizontal", length=180, 
                variable=self.alpha_var, bg=Theme.BG, fg=Theme.TEXT, 
                highlightthickness=0, troughcolor=Theme.BORDER, 
                activebackground=Theme.BLUE).grid(row=row, column=1, padx=10, pady=5)
        row += 1
        
        # 独立导航栏宽度
        tk.Label(frame, text="导航栏宽度:", bg=Theme.BG, fg=Theme.TEXT).grid(
            row=row, column=0, sticky="w", pady=5)
        self.nav_width_var = tk.DoubleVar(value=PanelConfig.navigation_bar_width)
        tk.Scale(frame, from_=0.5, to=2.0, resolution=0.1, orient="horizontal", 
                length=180, variable=self.nav_width_var, bg=Theme.BG, fg=Theme.TEXT, 
                highlightthickness=0, troughcolor=Theme.BORDER, 
                activebackground=Theme.BLUE).grid(row=row, column=1, padx=10, pady=5)
        row += 1
        
        # 缩放
        tk.Label(frame, text="UI缩放:", bg=Theme.BG, fg=Theme.TEXT).grid(
            row=row, column=0, sticky="w", pady=5)
        self.scale_var = tk.DoubleVar(value=UIConfig.UI_SCALE_MULT)
        tk.Scale(frame, from_=0.6, to=1.5, resolution=0.05, orient="horizontal", 
                length=180, variable=self.scale_var, bg=Theme.BG, fg=Theme.TEXT, 
                highlightthickness=0, troughcolor=Theme.BORDER, 
                activebackground=Theme.BLUE).grid(row=row, column=1, padx=10, pady=5)
        row += 1
        
        # 主题选择
        tk.Label(frame, text="颜色主题:", bg=Theme.BG, fg=Theme.TEXT).grid(
            row=row, column=0, sticky="w", pady=5)
        theme_frame = tk.Frame(frame, bg=Theme.BG)
        theme_frame.grid(row=row, column=1, sticky="w", padx=10, pady=5)
        
        self.theme_var = tk.StringVar(value=Theme.get_current())
        for theme_name in Theme.get_theme_names():
            display_name = Theme.get_theme_display_name(theme_name)
            tk.Radiobutton(
                theme_frame, text=display_name, variable=self.theme_var, value=theme_name,
                bg=Theme.BG, fg=Theme.TEXT, selectcolor=Theme.GRAYPILL,
                activebackground=Theme.BG, activeforeground=Theme.TEXT,
                highlightthickness=0
            ).pack(anchor="w")
        row += 1
        
        # 主题提示
        tk.Label(frame, text="* 主题更改需要重启生效", bg=Theme.BG, fg=Theme.TEXT_MUTED,
                font=("Segoe UI", 8)).grid(row=row, column=0, columnspan=2, sticky="w", pady=(10, 0))
    
    def _build_panel_tab(self):
        """构建面板设置页"""
        frame = tk.Frame(self.content_frame, bg=Theme.BG)
        self.tab_frames["面板"] = frame
        
        # 如果高级设置被禁用，显示简化提示
        if not ENABLE_ADVANCED_SETTINGS:
            tk.Label(frame, text="面板设置在精简模式下不可用", 
                    bg=Theme.BG, fg=Theme.TEXT_MUTED).pack(anchor="w", pady=10)
            return
        
        tk.Label(frame, text="选择显示的信息面板:", bg=Theme.BG, fg=Theme.TEXT).pack(
            anchor="w", pady=(0, 10))
        
        # 面板开关（根据编译开关动态生成）
        self.panel_vars = {}
        panels = []
        
        if ENABLE_ZONES:
            panels.append(("show_zones", "🎯 战区导航", "显示战区位置和距离"))
        if ENABLE_AIRFIELDS:
            panels.append(("show_airfields", "🛫 机场导航", "显示友方/敌方机场"))
        if ENABLE_FUEL:
            panels.append(("show_fuel", "⛽ 燃油管理", "显示油量和返航估算"))
        if ENABLE_CHECKLIST:
            panels.append(("show_checklist", "✅ 出击检查", "显示起飞前检查清单"))
        
        if not panels:
            tk.Label(frame, text="所有扩展面板已在编译时禁用", 
                    bg=Theme.BG, fg=Theme.TEXT_MUTED).pack(anchor="w")
            return
        
        for key, label, desc in panels:
            var = tk.BooleanVar(value=getattr(PanelConfig, key))
            self.panel_vars[key] = var
            
            item_frame = tk.Frame(frame, bg=Theme.BG)
            item_frame.pack(fill="x", pady=3)
            
            tk.Checkbutton(
                item_frame, text=label, variable=var,
                bg=Theme.BG, fg=Theme.TEXT, selectcolor=Theme.GRAYPILL,
                activebackground=Theme.BG, activeforeground=Theme.TEXT,
                highlightthickness=0, anchor="w"
            ).pack(side="left")
            
            tk.Label(item_frame, text=f"  - {desc}", bg=Theme.BG, fg=Theme.TEXT_DIM,
                    font=("Segoe UI", 8)).pack(side="left")
    
    def _build_hotkey_tab(self):
        """构建快捷键设置页"""
        frame = tk.Frame(self.content_frame, bg=Theme.BG)
        self.tab_frames["快捷键"] = frame
        
        tk.Label(frame, text="自定义快捷键绑定:", bg=Theme.BG, fg=Theme.TEXT).pack(
            anchor="w", pady=(0, 10))
        
        # 快捷键配置
        self.hotkey_vars = {}
        hotkeys = [
            ("reset", "重置计时器", HotkeyConfig.KEY_RESET),
            ("lock", "锁定/解锁", HotkeyConfig.KEY_LOCK),
            ("corner", "切换角落", HotkeyConfig.KEY_CORNER),
            ("beep", "声音开关", HotkeyConfig.KEY_BEEP),
            ("zones", "战区提示音", HotkeyConfig.KEY_ZONES),
        ]
        
        for key, label, current in hotkeys:
            row_frame = tk.Frame(frame, bg=Theme.BG)
            row_frame.pack(fill="x", pady=3)
            
            tk.Label(row_frame, text=f"{label}:", bg=Theme.BG, fg=Theme.TEXT, 
                    width=12, anchor="w").pack(side="left")
            
            var = tk.StringVar(value=current)
            self.hotkey_vars[key] = var
            
            # 下拉选择框
            menu_btn = tk.Menubutton(
                row_frame, textvariable=var, bg=Theme.GRAYPILL, fg=Theme.TEXT,
                bd=0, padx=10, pady=2, highlightthickness=1, 
                highlightbackground=Theme.BORDER, relief="flat"
            )
            menu_btn.pack(side="left", padx=(10, 0))
            
            menu = tk.Menu(menu_btn, tearoff=0, bg=Theme.GRAYPILL, fg=Theme.TEXT)
            for fkey in HotkeyConfig.AVAILABLE_KEYS:
                menu.add_command(label=fkey, command=lambda v=var, k=fkey: v.set(k))
            menu_btn["menu"] = menu
        
        # 提示
        tk.Label(frame, text="* 避免与游戏快捷键冲突\n* 更改后需要重启热键服务", 
                bg=Theme.BG, fg=Theme.TEXT_MUTED, font=("Segoe UI", 8),
                justify="left").pack(anchor="w", pady=(15, 0))
    
    def _build_other_tab(self):
        """构建其他设置页"""
        frame = tk.Frame(self.content_frame, bg=Theme.BG)
        self.tab_frames["其他"] = frame
        
        row = 0
        
        # 全局热键开关
        tk.Label(frame, text="全局热键:", bg=Theme.BG, fg=Theme.TEXT).grid(
            row=row, column=0, sticky="w", pady=5)
        self.hotkeys_enabled_var = tk.BooleanVar(value=HotkeyConfig.GLOBAL_HOTKEYS)
        tk.Checkbutton(
            frame, text="启用全局热键", variable=self.hotkeys_enabled_var,
            bg=Theme.BG, fg=Theme.TEXT, selectcolor=Theme.GRAYPILL,
            activebackground=Theme.BG, activeforeground=Theme.TEXT,
            highlightthickness=0
        ).grid(row=row, column=1, sticky="w", padx=10, pady=5)
        row += 1
        
        # 窗口吸附
        tk.Label(frame, text="窗口吸附:", bg=Theme.BG, fg=Theme.TEXT).grid(
            row=row, column=0, sticky="w", pady=5)
        self.snap_var = tk.BooleanVar(value=SnapConfig.enabled)
        tk.Checkbutton(
            frame, text="拖动时吸附到屏幕边缘", variable=self.snap_var,
            bg=Theme.BG, fg=Theme.TEXT, selectcolor=Theme.GRAYPILL,
            activebackground=Theme.BG, activeforeground=Theme.TEXT,
            highlightthickness=0
        ).grid(row=row, column=1, sticky="w", padx=10, pady=5)
        row += 1
        
        # 吸附距离
        tk.Label(frame, text="吸附距离:", bg=Theme.BG, fg=Theme.TEXT).grid(
            row=row, column=0, sticky="w", pady=5)
        self.snap_dist_var = tk.IntVar(value=SnapConfig.SNAP_DISTANCE)
        tk.Scale(frame, from_=5, to=50, orient="horizontal", length=150, 
                variable=self.snap_dist_var, bg=Theme.BG, fg=Theme.TEXT, 
                highlightthickness=0, troughcolor=Theme.BORDER, 
                activebackground=Theme.BLUE).grid(row=row, column=1, padx=10, pady=5, sticky="w")
        row += 1
        
        # 分隔线
        tk.Frame(frame, bg=Theme.SEPARATOR, height=1).grid(
            row=row, column=0, columnspan=2, sticky="ew", pady=10)
        row += 1
        
        # 重置按钮
        tk.Button(frame, text="重置所有设置为默认", command=self._reset_defaults,
                 bg=Theme.YELLOW, fg=Theme.BG, bd=0, padx=15, pady=5).grid(
            row=row, column=0, columnspan=2, pady=10)
    
    def _reset_defaults(self):
        """重置为默认设置"""
        if messagebox.askyesno("确认", "确定要重置所有设置为默认值吗？", parent=self):
            # 重置显示设置
            self.alpha_var.set(210)
            self.nav_width_var.set(1.0)
            self.scale_var.set(0.85)
            self.theme_var.set("dark")
            
            # 重置面板设置
            for key in self.panel_vars:
                self.panel_vars[key].set(True)
            
            # 重置快捷键
            defaults = {"reset": "F7", "lock": "F8", "corner": "F9", "beep": "F10", "zones": "F11"}
            for key, val in defaults.items():
                self.hotkey_vars[key].set(val)
            
            # 重置其他设置
            self.hotkeys_enabled_var.set(True)
            self.snap_var.set(True)
            self.snap_dist_var.set(20)
    
    def _center_on_parent(self, parent):
        """居中显示"""
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_y() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")
    
    def _save(self):
        """保存所有设置"""
        # 收集设置值
        config = ConfigManager.load()
        
        # 显示设置
        UIConfig.WINDOW_ALPHA = self.alpha_var.get()
        PanelConfig.navigation_bar_width = self.nav_width_var.get()
        UIConfig.UI_SCALE_MULT = self.scale_var.get()
        new_theme = self.theme_var.get()
        old_theme = Theme.get_current()
        
        config['alpha'] = UIConfig.WINDOW_ALPHA
        config['scale'] = UIConfig.UI_SCALE_MULT
        config['theme'] = new_theme
        
        # 面板设置
        panel_config = {}
        for key, var in self.panel_vars.items():
            setattr(PanelConfig, key, var.get())
            panel_config[key] = var.get()
        config['panels'] = panel_config
        
        # 快捷键设置
        old_hotkeys_enabled = HotkeyConfig.GLOBAL_HOTKEYS
        HotkeyConfig.GLOBAL_HOTKEYS = self.hotkeys_enabled_var.get()
        
        hotkey_bindings = {}
        for key, var in self.hotkey_vars.items():
            hotkey_bindings[key] = var.get()
        HotkeyConfig.set_bindings(hotkey_bindings)
        
        config['global_hotkeys'] = HotkeyConfig.GLOBAL_HOTKEYS
        config['hotkey_bindings'] = hotkey_bindings
        
        # 吸附设置
        SnapConfig.enabled = self.snap_var.get()
        SnapConfig.SNAP_DISTANCE = self.snap_dist_var.get()
        config['snap_enabled'] = SnapConfig.enabled
        config['snap_distance'] = SnapConfig.SNAP_DISTANCE
        
        # 保存配置
        ConfigManager.save(config)
        
        # 应用透明度
        Win32.setup_window(self.app.hwnd, self.app._locked, UIConfig.WINDOW_ALPHA)
        
        # 重启热键服务（如果需要）
        need_restart_hotkeys = (
            old_hotkeys_enabled != HotkeyConfig.GLOBAL_HOTKEYS or
            hotkey_bindings != HotkeyConfig.get_bindings()
        )
        if need_restart_hotkeys:
            if hasattr(self.app, '_ghk') and self.app._ghk:
                self.app._ghk.stop()
            if HotkeyConfig.GLOBAL_HOTKEYS:
                self.app._init_global_hotkeys()
                if hasattr(self.app, '_ghk') and self.app._ghk:
                    self.app._ghk.start()
        
        # 应用主题（需要重启）
        theme_changed = new_theme != old_theme
        Theme.apply(new_theme)
        
        if theme_changed:
            messagebox.showinfo("设置", "设置已保存\n主题更改需要重启应用生效", parent=self)
        else:
            messagebox.showinfo("设置", "设置已保存", parent=self)
        
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


class BombSelectorDialog(tk.Toplevel):
    """炸弹选择对话框"""
    
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.selected_bomb = BombConfig.selected_bomb
        self._current_category = None
        
        self.title("选择炸弹")
        self.configure(bg=Theme.BG)
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        
        main = tk.Frame(self, bg=Theme.BG, padx=15, pady=15)
        main.pack(fill="both", expand=True)
        
        # 搜索框
        search_frame = tk.Frame(main, bg=Theme.BG)
        search_frame.pack(fill="x", pady=(0, 10))
        
        self.search_var = tk.StringVar()
        self.search_var.trace("w", lambda *args: self._on_search())
        self.search_entry = tk.Entry(
            search_frame, textvariable=self.search_var,
            bg=Theme.GRAYPILL, fg=Theme.TEXT_MUTED, bd=0, highlightthickness=1,
            highlightbackground=Theme.BORDER, font=("Segoe UI", 10)
        )
        self.search_entry.pack(fill="x", ipady=5)
        self.search_entry.insert(0, "搜索...")
        self.search_entry.bind("<FocusIn>", self._on_search_focus_in)
        self.search_entry.bind("<FocusOut>", self._on_search_focus_out)
        
        # 分类按钮
        cat_frame = tk.Frame(main, bg=Theme.BG)
        cat_frame.pack(fill="x", pady=(0, 10))
        
        self.cat_buttons = {}
        categories = ['全部'] + BombConfig.get_categories()
        for cat in categories:
            btn = tk.Button(
                cat_frame, text=cat, 
                bg=Theme.GRAYPILL if cat != '全部' else Theme.BLUE,
                fg=Theme.TEXT, bd=0, padx=8, pady=4, font=("Segoe UI", 9),
                command=lambda c=cat: self._filter_category(c)
            )
            btn.pack(side="left", padx=2)
            self.cat_buttons[cat] = btn
        
        # 列表区域
        list_frame = tk.Frame(main, bg=Theme.GRAYPILL)
        list_frame.pack(fill="both", expand=True)
        
        scrollbar = tk.Scrollbar(list_frame)
        scrollbar.pack(side="right", fill="y")
        
        self.listbox = tk.Listbox(
            list_frame, width=55, height=20,
            bg=Theme.GRAYPILL, fg=Theme.TEXT, selectbackground=Theme.BLUE,
            selectforeground=Theme.TEXT, bd=0, highlightthickness=1,
            highlightbackground=Theme.BORDER, yscrollcommand=scrollbar.set, 
            font=("Consolas", 9)
        )
        self.listbox.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self.listbox.yview)
        self.listbox.bind("<Double-Button-1>", lambda e: self._select())
        
        # 统计
        self.stats_lbl = tk.Label(
            main, text="", bg=Theme.BG, fg=Theme.TEXT_DIM, 
            font=("Segoe UI", 9), anchor="w"
        )
        self.stats_lbl.pack(fill="x", pady=(5, 0))
        
        # 按钮
        btn_frame = tk.Frame(main, bg=Theme.BG)
        btn_frame.pack(fill="x", pady=(10, 0))
        tk.Button(
            btn_frame, text="确定", command=self._select, 
            bg=Theme.BLUE, fg=Theme.TEXT, bd=0, padx=20, pady=5
        ).pack(side="right", padx=5)
        tk.Button(
            btn_frame, text="取消", command=self.destroy, 
            bg=Theme.GRAYPILL, fg=Theme.TEXT, bd=0, padx=20, pady=5
        ).pack(side="right", padx=5)
        
        self._populate_list()
        self._center_on_parent(parent)
    
    def _on_search_focus_in(self, event):
        if self.search_entry.get() == "搜索...":
            self.search_entry.delete(0, "end")
            self.search_entry.config(fg=Theme.TEXT)
    
    def _on_search_focus_out(self, event):
        if not self.search_entry.get():
            self.search_entry.insert(0, "搜索...")
            self.search_entry.config(fg=Theme.TEXT_MUTED)
    
    def _on_search(self):
        if not hasattr(self, "listbox"):
            return
        query = self.search_var.get()
        if query == "搜索...":
            query = ""
        self._populate_list(query)
    
    def _filter_category(self, category):
        self._current_category = None if category == '全部' else category
        self.search_var.set("")
        for cat, btn in self.cat_buttons.items():
            btn.config(bg=Theme.BLUE if cat == category else Theme.GRAYPILL)
        self._populate_list()
    
    def _populate_list(self, search_query: str = ""):
        if not hasattr(self, "listbox"):
            return
        self.listbox.delete(0, "end")
        
        if search_query and search_query != "搜索...":
            bombs = BombConfig.search_bombs(search_query, limit=100)
            show_categories = False
        elif self._current_category:
            bombs = BombConfig.get_bombs_by_category(self._current_category)
            show_categories = False
        else:
            bombs = None
            show_categories = True
        
        current_index, select_index, total_count = 0, 0, 0
        
        if show_categories:
            for category in BombConfig.get_categories():
                cat_bombs = BombConfig.get_bombs_by_category(category)
                if not cat_bombs:
                    continue
                self.listbox.insert("end", f"━━━ {category} ({len(cat_bombs)}种) ━━━")
                self.listbox.itemconfig(current_index, fg=Theme.YELLOW)
                current_index += 1
                
                for bomb_id in cat_bombs:
                    bomb_data = BombConfig.get_bomb_data(bomb_id)
                    if bomb_data:
                        mass = bomb_data['mass']
                        mass_str = f"{mass/1000:.1f}t" if mass >= 1000 else f"{int(mass)}kg"
                        text = f"  {bomb_id} ({mass_str}, Cx={bomb_data.get('drag_cx', 0.04):.4f})"
                    else:
                        text = f"  {bomb_id}"
                    
                    self.listbox.insert("end", text)
                    if bomb_id == self.selected_bomb:
                        select_index = current_index
                        self.listbox.itemconfig(current_index, fg=Theme.GREEN)
                    current_index += 1
                    total_count += 1
        else:
            for bomb_id in bombs:
                bomb_data = BombConfig.get_bomb_data(bomb_id)
                if bomb_data:
                    mass = bomb_data['mass']
                    mass_str = f"{mass/1000:.1f}t" if mass >= 1000 else f"{int(mass)}kg"
                    cat = bomb_data.get('category', '?')
                    text = f"{bomb_id} ({mass_str}, Cx={bomb_data.get('drag_cx', 0.04):.4f}) [{cat}]"
                else:
                    text = bomb_id
                
                self.listbox.insert("end", text)
                if bomb_id == self.selected_bomb:
                    select_index = current_index
                    self.listbox.itemconfig(current_index, fg=Theme.GREEN)
                current_index += 1
                total_count += 1
        
        if select_index > 0:
            self.listbox.selection_set(select_index)
            self.listbox.see(select_index)
        
        self.stats_lbl.config(text=f"显示 {total_count} / {len(BombConfig.BOMB_DATABASE)} 种炸弹")
    
    def _center_on_parent(self, parent):
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_y() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")
    
    def _select(self):
        selection = self.listbox.curselection()
        if not selection:
            return
        
        text = self.listbox.get(selection[0]).strip()
        if text.startswith("━━"):
            return
        
        bomb_id = text.split(" (")[0].strip()
        
        if BombConfig.get_bomb_data(bomb_id):
            BombConfig.selected_bomb = bomb_id
            config = ConfigManager.load()
            config['selected_bomb'] = bomb_id
            ConfigManager.save(config)
            
            if hasattr(self.app, 'bomb_select_lbl'):
                self.app.bomb_select_lbl.config(
                    text=f"炸弹: {BombConfig.format_bomb_name(bomb_id)} (点击更换)"
                )
            
            self.destroy()


class AboutDialog(tk.Toplevel):
    """关于对话框"""
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.title("关于 Bomana")
        self.configure(bg=Theme.BG)
        self.transient(parent)
        self.grab_set()
        self._images = []
        
        self._build_ui()
        
        # 让窗口自适应内容大小
        self.update_idletasks()
        
        # 获取内容实际需要的尺寸
        req_width = self.winfo_reqwidth()
        req_height = self.winfo_reqheight()
        
        # 设置最小尺寸，确保不会太小
        min_width = max(800, req_width)
        min_height = max(1200, req_height)
        
        # 限制最大尺寸不超过屏幕
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        final_width = min(min_width, screen_w - 100)
        final_height = min(min_height, screen_h - 100)
        
        self.geometry(f"{final_width}x{final_height}")
        self.minsize(400, 500)
        self.resizable(True, True)  # 允许用户调整大小
        
        self._center_on_parent(parent)
    
    def _build_ui(self):
        # 创建可滚动的画布（内容太多时可以滚动）
        canvas = tk.Canvas(self, bg=Theme.BG, highlightthickness=0)
        scrollbar = tk.Scrollbar(self, orient="vertical", command=canvas.yview)
        
        main = tk.Frame(canvas, bg=Theme.BG)
        
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        
        canvas_frame = canvas.create_window((0, 0), window=main, anchor="nw")
        
        def configure_scroll(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
            # 让内容宽度跟随窗口
            canvas.itemconfig(canvas_frame, width=event.width)
        
        def configure_canvas(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
        
        canvas.bind("<Configure>", configure_scroll)
        main.bind("<Configure>", configure_canvas)
        
        # 鼠标滚轮支持
        def on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        canvas.bind_all("<MouseWheel>", on_mousewheel)
        
        # 内容区域，增大padding
        content = tk.Frame(main, bg=Theme.BG)
        content.pack(fill="both", expand=True, padx=30, pady=25)
        
        # === 软件标题 ===
        title_frame = tk.Frame(content, bg=Theme.BG)
        title_frame.pack(fill="x", pady=(0, 15))
        
        try:
            icon_path = resource_path(FileConfig.ICON_FILE)
            if HAS_TRAY:
                from PIL import Image, ImageTk
                img = Image.open(icon_path).convert("RGBA")
                img = img.resize((64, 64), Image.Resampling.LANCZOS)  # 更大的图标
                self._app_icon = ImageTk.PhotoImage(img)
                icon_lbl = tk.Label(title_frame, image=self._app_icon, bg=Theme.BG)
                icon_lbl.pack(side="left", padx=(0, 15))
        except Exception:
            pass
        
        title_text_frame = tk.Frame(title_frame, bg=Theme.BG)
        title_text_frame.pack(side="left", fill="both", expand=True)
        
        tk.Label(
            title_text_frame,
            text=f"{AboutConfig.APP_NAME} v{AboutConfig.VERSION}",
            font=("Segoe UI", 20, "bold"),  # 更大字体
            fg=Theme.TEXT, bg=Theme.BG, anchor="w"
        ).pack(anchor="w")
        
        tk.Label(
            title_text_frame,
            text=AboutConfig.APP_NAME_CN,
            font=("Segoe UI", 12),  # 更大字体
            fg=Theme.TEXT_DIM, bg=Theme.BG, anchor="w"
        ).pack(anchor="w", pady=(5, 0))
        
        # === 分隔线 ===
        tk.Frame(content, bg=Theme.SEPARATOR, height=1).pack(fill="x", pady=15)
        
        # === 项目说明 ===
        description = """本软件是一个用于战雷全真模式的辅助计时工具，
帮助玩家管理15分钟的复活周期。

核心特性：
• 仅使用官方8111接口，安全合规
• 自动检测出生/死亡/着陆状态
• 战区导航和燃油管理
• 可自定义的起飞检查清单

本软件完全开源免费，欢迎贡献代码！"""
        
        tk.Label(
            content, text=description,
            font=("Segoe UI", 11),  # 更大字体
            fg=Theme.TEXT_DIM, bg=Theme.BG,
            justify="left", anchor="w"
        ).pack(anchor="w")
        
        # === GitHub 链接 ===
        if AboutConfig.GITHUB_URL:
            link_frame = tk.Frame(content, bg=Theme.BG)
            link_frame.pack(fill="x", pady=(15, 0))
            
            tk.Label(
                link_frame, text="📦 项目主页：",
                font=("Segoe UI", 11),
                fg=Theme.TEXT_DIM, bg=Theme.BG
            ).pack(side="left")
            
            github_btn = tk.Label(
                link_frame, text=AboutConfig.GITHUB_URL,
                font=("Segoe UI", 11, "underline"),
                fg=Theme.BLUE, bg=Theme.BG, cursor="hand2"
            )
            github_btn.pack(side="left")
            github_btn.bind("<Button-1>", lambda e: self._open_url(AboutConfig.GITHUB_URL))
        
        # === 分隔线 ===
        tk.Frame(content, bg=Theme.SEPARATOR, height=1).pack(fill="x", pady=15)
        
        # === 赞助区域 ===
        tk.Label(
            content, text="❤️ 支持作者",
            font=("Segoe UI", 14, "bold"),  # 更大字体
            fg=Theme.TEXT, bg=Theme.BG, anchor="w"
        ).pack(anchor="w", pady=(0, 10))
        
        tk.Label(
            content, text="如果这个工具对你有帮助，欢迎请作者喝杯咖啡~",
            font=("Segoe UI", 11),
            fg=Theme.TEXT_DIM, bg=Theme.BG, anchor="w"
        ).pack(anchor="w", pady=(0, 15))
        
        # 赞助图片/链接区域
        sponsor_frame = tk.Frame(content, bg=Theme.BG)
        sponsor_frame.pack(fill="x", pady=(0, 15))
        
        for name, url, img_file in AboutConfig.SPONSOR_LINKS:
            self._add_sponsor_item(sponsor_frame, name, url, img_file)
        
        # === 分隔线 ===
        tk.Frame(content, bg=Theme.SEPARATOR, height=1).pack(fill="x", pady=15)
        
        # === 版权声明 ===
        copyright_text = f"""作者：{AboutConfig.AUTHOR}

MIT License
Copyright © 2024-2026 {AboutConfig.AUTHOR}

Gaijin Entertainment AG及其子公司拥有《战争雷霆》及相关商标的所有权
本软件与Gaijin Entertainment AG无任何关联
注意！滥用本软件可能违反Gaijin用户守则
使用本软件的风险由用户自行承担"""
        
        tk.Label(
            content, text=copyright_text,
            font=("Segoe UI", 10),  # 更大字体
            fg=Theme.TEXT_MUTED, bg=Theme.BG,
            justify="left", anchor="w"
        ).pack(anchor="w", pady=(0, 15))
        
        # === 关闭按钮 ===
        tk.Button(
            content, text="关闭", command=self._close,
            font=("Segoe UI", 11),
            bg=Theme.GRAYPILL, fg=Theme.TEXT, bd=0, padx=40, pady=8
        ).pack(pady=(10, 0))
    
    def _add_sponsor_item(self, parent, name: str, url: str, img_file: str):
        item_frame = tk.Frame(parent, bg=Theme.BG)
        item_frame.pack(side="left", padx=(0, 20), pady=10)
        
        img_loaded = False
        if img_file and HAS_TRAY:
            try:
                from PIL import Image, ImageTk
                img_path = resource_path(img_file)
                img = Image.open(img_path).convert("RGBA")
                
                # 更大的图片尺寸
                target_width = AboutConfig.SPONSOR_IMAGE_WIDTH
                ratio = target_width / img.width
                new_height = int(img.height * ratio)
                img = img.resize((target_width, new_height), Image.Resampling.LANCZOS)
                photo = ImageTk.PhotoImage(img)
                self._images.append(photo)
                
                img_lbl = tk.Label(item_frame, image=photo, bg=Theme.BG, cursor="hand2" if url else "")
                img_lbl.pack()
                if url:
                    img_lbl.bind("<Button-1>", lambda e, u=url: self._open_url(u))
                
                tk.Label(
                    item_frame, text=name,
                    font=("Segoe UI", 10),
                    fg=Theme.TEXT_DIM, bg=Theme.BG
                ).pack(pady=(5, 0))
                img_loaded = True
            except Exception:
                pass
        
        if not img_loaded:
            btn = tk.Button(
                item_frame, text=f"💝 {name}",
                font=("Segoe UI", 11),
                bg=Theme.GRAYPILL, fg=Theme.TEXT, bd=0, padx=20, pady=10,
                cursor="hand2" if url else ""
            )
            btn.pack()
            if url:
                btn.config(command=lambda u=url: self._open_url(u))
    
    def _open_url(self, url: str):
        if url:
            try:
                webbrowser.open(url)
            except Exception:
                pass
    
    def _close(self):
        # 解绑鼠标滚轮事件，防止关闭后影响其他窗口
        try:
            self.unbind_all("<MouseWheel>")
        except:
            pass
        self.destroy()
    
    def _center_on_parent(self, parent):
        self.update_idletasks()
        pw = parent.winfo_width()
        ph = parent.winfo_height()
        px = parent.winfo_x()
        py = parent.winfo_y()
        w = self.winfo_width()
        h = self.winfo_height()
        x = px + (pw - w) // 2
        y = py + (ph - h) // 2
        # 确保不超出屏幕
        x = max(0, x)
        y = max(0, y)
        self.geometry(f"+{x}+{y}")


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
        
        # 性能优化: 字体缓存和Label复用池
        self._cached_fonts: Dict[str, tuple] = {}
        self._zone_label_pool: List[tk.Label] = []
        self._airport_label_pool: List[tk.Label] = []
        self._last_zone_count = 0
        self._last_airport_count = 0

        # 初始化流程
        self._load_config()
        self._init_window_base()
        self._init_ui()
        self._finalize_window_geometry_and_styles()
        self._init_bindings()
        self._init_global_hotkeys()
        
        # v6.2.1: 初始化独立导航窗口
        self.nav_window = NavigationWindow(self)
        if PanelConfig.navigation_mode == "standalone":
            self.nav_window.show()

        # 恢复状态并启动
        self._restored_state = self.game.restore_timer_state()
        threading.Thread(target=self._poll_loop, daemon=True).start()
        self._update_ui()

        if HAS_TRAY:
            self._init_tray()

    def _load_config(self):
        """加载用户配置
        
        加载顺序: 主题必须在UI创建前应用
        配置项: alpha/scale/theme/panels/hotkey_bindings/snap/window_position
        """
        config = ConfigManager.load()
        
        # 显示设置
        UIConfig.WINDOW_ALPHA = config.get('alpha', UIConfig.WINDOW_ALPHA)
        # v5.9.3: 智能缩放逻辑
        # 检查是否是首次启动（没有保存的缩放配置）
        if 'scale' in config:
            # 用户已经设置过缩放，使用保存的值
            UIConfig.UI_SCALE_MULT = config.get('scale')
        else:
            # 首次启动，根据屏幕分辨率智能设置
            try:
                sw, sh = Win32.screen_size()
                # 临时获取DPI缩放（此时窗口还未创建，使用默认值1.2）
                smart_scale = calculate_smart_scale(sw, sh, 1.2)
                UIConfig.UI_SCALE_MULT = smart_scale
                print(f"[智能缩放] 检测到屏幕分辨率 {sw}x{sh}，设置缩放为 {smart_scale:.2f}x")
            except Exception as e:
                # 出错时使用默认值1.2
                UIConfig.UI_SCALE_MULT = 1.2
                print(f"[智能缩放] 检测失败，使用默认缩放1.2x: {e}")
        
        # 主题设置（必须在UI创建前应用）
        theme_name = config.get('theme', 'dark')
        Theme.apply(theme_name)
        
        # 面板显示设置
        panels = config.get('panels', {})
        PanelConfig.show_zones = panels.get('show_zones', True)
        PanelConfig.show_airfields = panels.get('show_airfields', True)
        PanelConfig.show_fuel = panels.get('show_fuel', True)
        PanelConfig.show_checklist = panels.get('show_checklist', True)
        PanelConfig.show_bombing = panels.get('show_bombing', True)  # v6.0 新增
        
        # v6.2.1: 导航条模式
        PanelConfig.navigation_mode = config.get('navigation_mode', 'integrated')
        nav_pos = config.get('navigation_window_pos')
        if nav_pos and isinstance(nav_pos, list) and len(nav_pos) == 2:
            PanelConfig.navigation_window_pos = tuple(nav_pos)
        # 独立导航栏宽度
        nav_width = config.get('navigation_bar_width')
        if nav_width and isinstance(nav_width, (int, float)):
            PanelConfig.navigation_bar_width = max(0.5, min(2.0, float(nav_width)))
        
        # v6.0 新增：炸弹选择（仅在CCRP启用时）
        if ENABLE_CCRP:
            selected_bomb = config.get('selected_bomb', 'su_fab100sv')
            if BombConfig.get_bomb_data(selected_bomb):
                BombConfig.selected_bomb = selected_bomb
        
        # 根据编译开关初始化面板状态
        PanelConfig.init_from_compile_switches()
        
        # 快捷键设置
        HotkeyConfig.GLOBAL_HOTKEYS = config.get('global_hotkeys', HotkeyConfig.GLOBAL_HOTKEYS)
        hotkey_bindings = config.get('hotkey_bindings', {})
        if hotkey_bindings:
            HotkeyConfig.set_bindings(hotkey_bindings)
        
        # 吸附设置
        SnapConfig.enabled = config.get('snap_enabled', True)
        SnapConfig.SNAP_DISTANCE = config.get('snap_distance', 20)
        
        # 检查清单
        self.chk_items = config.get('checklist_items', ChecklistConfig.DEFAULT_ITEMS.copy())
        self._zone_sound_enabled = config.get('zone_sound_enabled', True)
        
        # 恢复窗口位置（支持多显示器）
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
            # 记录显示器索引（用于多显示器支持）
            self._saved_monitor_index = saved_pos.get('monitor_index', 0)
        else:
            self._saved_monitor_index = 0
        
        beep_enabled = config.get('beep_enabled', False)
        self.sound.set_enabled(beep_enabled)

    def _save_config(self):
        """保存用户配置"""
        config = ConfigManager.load()
        
        # 显示设置
        config['alpha'] = UIConfig.WINDOW_ALPHA
        config['scale'] = UIConfig.UI_SCALE_MULT
        config['theme'] = Theme.get_current()
        
        # 面板设置
        panels_config = {
            'show_zones': PanelConfig.show_zones,
            'show_airfields': PanelConfig.show_airfields,
            'show_fuel': PanelConfig.show_fuel,
            'show_checklist': PanelConfig.show_checklist,
        }
        # v6.0 新增：投弹预测面板（仅在CCRP启用时保存）
        if ENABLE_CCRP:
            panels_config['show_bombing'] = PanelConfig.show_bombing
        config['panels'] = panels_config
        
        # v6.2.1: 导航条模式
        config['navigation_mode'] = PanelConfig.navigation_mode
        if PanelConfig.navigation_window_pos:
            config['navigation_window_pos'] = list(PanelConfig.navigation_window_pos)
        config['navigation_bar_width'] = PanelConfig.navigation_bar_width
        
        # v6.0 新增：炸弹选择（仅在CCRP启用时保存）
        if ENABLE_CCRP:
            config['selected_bomb'] = BombConfig.selected_bomb
        
        # 快捷键设置
        config['global_hotkeys'] = HotkeyConfig.GLOBAL_HOTKEYS
        config['hotkey_bindings'] = HotkeyConfig.get_bindings()
        
        # 吸附设置
        config['snap_enabled'] = SnapConfig.enabled
        config['snap_distance'] = SnapConfig.SNAP_DISTANCE
        
        # 其他设置
        config['checklist_items'] = self.chk_items
        config['beep_enabled'] = self.sound.is_enabled()
        config['zone_sound_enabled'] = self._zone_sound_enabled
        
        # 窗口位置（包含多显示器信息）
        monitor_index = 0
        if self._manual_pos:
            monitor = Win32.get_monitor_at(self._manual_pos[0], self._manual_pos[1])
            if monitor:
                monitor_index = monitor.get('index', 0)
        
        config['window_position'] = {
            'corner': self._corner.name,
            'manual_pos': list(self._manual_pos) if self._manual_pos else None,
            'user_moved': self._user_moved,
            'monitor_index': monitor_index,
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
        
        # 缓存常用字体（避免每帧重新计算）
        self._cache_fonts()
    
    def _cache_fonts(self):
        """缓存所有常用字体元组
        
        性能优化: 预计算字体避免每帧重复计算
        添加新字体时需在此方法中添加缓存项
        """
        s = self.scale
        self._cached_fonts = {
            'timer': (UIConfig.FONT_TIMER[0], int(UIConfig.FONT_TIMER[1]*s), UIConfig.FONT_TIMER[2]),
            'life': (UIConfig.FONT_LIFE[0], int(UIConfig.FONT_LIFE[1]*s), UIConfig.FONT_LIFE[2]),
            'cycle': (UIConfig.FONT_CYCLE[0], int(UIConfig.FONT_CYCLE[1]*s)),
            'pill': (UIConfig.FONT_PILL[0], int(UIConfig.FONT_PILL[1]*s), UIConfig.FONT_PILL[2]),
            'status': (UIConfig.FONT_STATUS[0], int(UIConfig.FONT_STATUS[1]*s)),
            'checklist_title': (UIConfig.FONT_CHECKLIST_TITLE[0], int(UIConfig.FONT_CHECKLIST_TITLE[1]*s), UIConfig.FONT_CHECKLIST_TITLE[2]),
            'checklist_item': (UIConfig.FONT_CHECKLIST_ITEM[0], int(UIConfig.FONT_CHECKLIST_ITEM[1]*s)),
            'zone_title': (UIConfig.FONT_ZONE_TITLE[0], int(UIConfig.FONT_ZONE_TITLE[1]*s), UIConfig.FONT_ZONE_TITLE[2]),
            'zone_item': (UIConfig.FONT_ZONE_ITEM[0], int(UIConfig.FONT_ZONE_ITEM[1]*s)),
            'debug': (UIConfig.FONT_DEBUG[0], int(UIConfig.FONT_DEBUG[1]*s)),
            'hint': (UIConfig.FONT_HINT[0], int(UIConfig.FONT_HINT[1]*s)),
        }
    
    def _get_font(self, name: str) -> tuple:
        """获取缓存的字体"""
        return self._cached_fonts.get(name, ('Segoe UI', 10))

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
        # v5.9.6 新增：起落架警告徽章
        self.badge_gear = Pill(row2, text="", fg=Theme.TEXT, bg=Theme.ORANGE, font=pill_font)
        # 初始隐藏
        
        # v6.6.0 新增：起落架进度条框架
        self.gear_progress_frame = tk.Frame(row2, bg=Theme.BG, height=int(6*s))
        # 起落架进度条背景
        self.gear_progress_bg = tk.Frame(self.gear_progress_frame, bg=Theme.BORDER, height=int(4*s), width=int(60*s))
        self.gear_progress_bg.pack(pady=int(1*s))
        self.gear_progress_bg.pack_propagate(False)
        # 起落架进度条填充
        self.gear_progress_fill = tk.Frame(self.gear_progress_bg, bg=Theme.BLUE, height=int(4*s))
        self.gear_progress_fill.place(relx=0, rely=0, relwidth=0, relheight=1)
        # 初始隐藏进度条
        
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
        """初始化战区导航UI
        
        v6.1更新: 新增航向带(Heading Tape)组件
        
        使用Grid布局确保区块顺序固定:
        Row 0: zone_header_frame (标题+HDG)
        Row 1: heading_tape_frame (航向带) - v6.1新增
        Row 2: zone_alert_lbl (摧毁警告)
        Row 3: zone_list_frame (战区列表)
        Row 4: airport_title_lbl (机场标题)
        Row 5: airport_list_frame (机场列表)
        Row 6: fuel_title_lbl (燃油标题)
        Row 7: fuel_info_frame (燃油信息)
        Row 8: bombing_title_lbl (投弹标题)
        Row 9: bombing_info_frame (投弹信息)
        
        使用grid_remove()/grid()切换可见性,保持行号不变
        """
        s = self.scale
        pad_x = int(8*s)
        
        # 配置grid列宽
        self.zone_frame.columnconfigure(0, weight=1)
        
        # Row 0: 标题栏（始终显示）
        self.zone_header_frame = tk.Frame(self.zone_frame, bg=Theme.GRAYPILL)
        self.zone_header_frame.grid(row=0, column=0, sticky="ew", padx=pad_x, pady=(int(6*s), int(2*s)))
        
        font_title = (UIConfig.FONT_ZONE_TITLE[0], int(UIConfig.FONT_ZONE_TITLE[1]*s), UIConfig.FONT_ZONE_TITLE[2])
        self.zone_title = tk.Label(self.zone_header_frame, text="🎯 战区导航", font=font_title, fg=Theme.TEXT, bg=Theme.GRAYPILL, anchor="w")
        self.zone_title.pack(side="left")
        
        # 独立导航条模式按钮
        font_btn = (UIConfig.FONT_ZONE_ITEM[0], int(UIConfig.FONT_ZONE_ITEM[1]*s))
        self.standalone_btn = tk.Label(
            self.zone_header_frame, text="⧉独立导航条", font=font_btn,
            fg=Theme.TEXT_MUTED, bg=Theme.GRAYPILL, cursor="hand2"
        )
        self.standalone_btn.pack(side="left", padx=(int(10*s), 0))
        self.standalone_btn.bind("<Button-1>", lambda e: self._toggle_navigation_mode())
        self.standalone_btn.bind("<Enter>", lambda e: self.standalone_btn.config(fg=Theme.BLUE))
        self.standalone_btn.bind("<Leave>", lambda e: self.standalone_btn.config(fg=Theme.TEXT_MUTED))
        
        font_heading = (UIConfig.FONT_ZONE_ITEM[0], int(UIConfig.FONT_ZONE_ITEM[1]*s))
        font_item = font_heading
        self.heading_lbl = tk.Label(self.zone_header_frame, text="HDG: ---", font=font_heading, fg=Theme.TEXT_DIM, bg=Theme.GRAYPILL, anchor="e")
        self.heading_lbl.pack(side="right")
        
        # Row 1: v6.2重构 - 统一航向带(显示战区+机场+被摧毁目标)
        if ZoneConfig.HEADING_TAPE_ENABLED:
            self.heading_tape_frame = tk.Frame(self.zone_frame, bg=Theme.GRAYPILL)
            self.heading_tape_frame.grid(row=1, column=0, sticky="ew", padx=pad_x, pady=(int(2*s), int(4*s)))
            
            tape_width = int(ZoneConfig.HEADING_TAPE_WIDTH * s)
            tape_height = int(ZoneConfig.HEADING_TAPE_HEIGHT * s)
            self.heading_tape = HeadingTape(
                self.heading_tape_frame, 
                width=tape_width, 
                height=tape_height
            )
            self.heading_tape.pack(fill="x", expand=True)
            
            # 图例行 - v6.2.2: 优化为紧凑单行布局
            self.tape_legend_row = tk.Frame(self.heading_tape_frame, bg=Theme.GRAYPILL)
            self.tape_legend_row.pack(fill="x", pady=(int(1*s), 0))
            
            # 使用更小字体和紧凑间距
            legend_font = (UIConfig.FONT_ZONE_ITEM[0], int(UIConfig.FONT_ZONE_ITEM[1]*s*0.85))
            legend_text = "⊚战区  ✈友方  ✈敌方  ✕摧毁"
            
            # v6.4: 图例行分为左侧图例和右侧阈值显示
            legend_left = tk.Label(
                self.tape_legend_row, text=legend_text, font=legend_font,
                fg=Theme.TEXT_MUTED, bg=Theme.GRAYPILL, anchor="w"
            )
            legend_left.pack(side="left", fill="x", expand=True)
            
            # 角度阈值显示（移至图例行右侧）
            self.tape_tolerance_legend = tk.Label(
                self.tape_legend_row, text="", font=legend_font,
                fg=Theme.TEXT_MUTED, bg=Theme.GRAYPILL, anchor="e"
            )
            self.tape_tolerance_legend.pack(side="right", padx=(0, int(4*s)))
            
            # v6.2.1: 战区状态提示行
            self.tape_zone_row = tk.Frame(self.heading_tape_frame, bg=Theme.GRAYPILL)
            self.tape_zone_row.pack(fill="x", pady=(int(2*s), 0))
            
            status_font = (UIConfig.FONT_ZONE_ITEM[0], int(UIConfig.FONT_ZONE_ITEM[1]*s*0.95))
            
            # 战区标签
            self.tape_zone_label = tk.Label(
                self.tape_zone_row, text="⊚战区:", font=status_font,
                fg=Theme.RED, bg=Theme.GRAYPILL, anchor="w"
            )
            self.tape_zone_label.pack(side="left")
            
            # 战区转向指示
            self.tape_zone_turn = tk.Label(
                self.tape_zone_row, text="", font=status_font,
                fg=Theme.TEXT_DIM, bg=Theme.GRAYPILL, anchor="w"
            )
            self.tape_zone_turn.pack(side="left", padx=(int(6*s), 0))
            
            # 战区状态描述
            self.tape_zone_status = tk.Label(
                self.tape_zone_row, text="", font=status_font,
                fg=Theme.TEXT_DIM, bg=Theme.GRAYPILL, anchor="w"
            )
            self.tape_zone_status.pack(side="left", padx=(int(8*s), 0))
            
            # 战区距离/ETE信息
            self.tape_zone_info = tk.Label(
                self.tape_zone_row, text="", font=status_font,
                fg=Theme.TEXT_DIM, bg=Theme.GRAYPILL, anchor="w"
            )
            self.tape_zone_info.pack(side="left", padx=(int(8*s), 0))
            
            # v6.4: 战区容差已移至图例行，保留变量引用
            self.tape_zone_tolerance = tk.Label(
                self.tape_zone_row, text="", font=status_font,
                fg=Theme.TEXT_MUTED, bg=Theme.GRAYPILL, anchor="e"
            )
            # 不再pack，让状态行布局更居中
            
            # v6.2.1: 友方机场状态提示行
            self.tape_friendly_row = tk.Frame(self.heading_tape_frame, bg=Theme.GRAYPILL)
            self.tape_friendly_row.pack(fill="x", pady=(int(1*s), 0))
            
            # 友方机场标签
            self.tape_friendly_label = tk.Label(
                self.tape_friendly_row, text="✈友方:", font=status_font,
                fg=Theme.BLUE, bg=Theme.GRAYPILL, anchor="w"
            )
            self.tape_friendly_label.pack(side="left")
            
            # 友方机场转向指示
            self.tape_friendly_turn = tk.Label(
                self.tape_friendly_row, text="", font=status_font,
                fg=Theme.TEXT_DIM, bg=Theme.GRAYPILL, anchor="w"
            )
            self.tape_friendly_turn.pack(side="left", padx=(int(6*s), 0))
            
            # 友方机场状态
            self.tape_friendly_status = tk.Label(
                self.tape_friendly_row, text="", font=status_font,
                fg=Theme.TEXT_DIM, bg=Theme.GRAYPILL, anchor="w"
            )
            self.tape_friendly_status.pack(side="left", padx=(int(8*s), 0))
            
            # 友方机场距离/ETE
            self.tape_friendly_info = tk.Label(
                self.tape_friendly_row, text="", font=status_font,
                fg=Theme.TEXT_DIM, bg=Theme.GRAYPILL, anchor="w"
            )
            self.tape_friendly_info.pack(side="left", padx=(int(8*s), 0))
            
            # 保留旧变量兼容
            self.tape_turn_lbl = self.tape_zone_turn
            self.tape_deviation_lbl = self.tape_zone_status
            self.tape_tolerance_lbl = self.tape_zone_tolerance
            self.tape_info_container = None
            self._tape_info_labels = []
        else:
            self.heading_tape = None
            self.tape_info_container = None
            self._tape_info_labels = []
            self.tape_turn_lbl = None
            self.tape_deviation_lbl = None
            self.tape_tolerance_lbl = None
            self.tape_zone_row = None
            self.tape_friendly_row = None
            self.tape_friendly_turn = None
            self.tape_friendly_info = None
            self.tape_friendly_status = None
            self.tape_zone_info = None
        
        # Row 2: 被摧毁警告标签（动态显示）
        font_alert = (UIConfig.FONT_ZONE_TITLE[0], int(UIConfig.FONT_ZONE_TITLE[1]*s), UIConfig.FONT_ZONE_TITLE[2])
        self.zone_alert_lbl = tk.Label(self.zone_frame, text="", font=font_alert, fg=Theme.RED, bg=Theme.GRAYPILL, anchor="w")
        # 初始不显示，由_update_zone_display控制
        
        # Row 3: 战区列表容器
        self.zone_list_frame = tk.Frame(self.zone_frame, bg=Theme.GRAYPILL)
        self.zone_list_frame.grid(row=3, column=0, sticky="ew", padx=pad_x, pady=(0, int(10*s)))

        # Row 4: 机场标题
        self.airport_title_lbl = tk.Label(self.zone_frame, text="🛫 机场导航", font=font_title, fg=Theme.TEXT, bg=Theme.GRAYPILL, anchor="w")
        self.airport_title_lbl.grid(row=4, column=0, sticky="ew", padx=pad_x, pady=(0, int(2*s)))

        # v6.2: 移除独立的机场航向带（已合并到主航向带）
        # 保留变量引用以兼容
        self.airport_tape_frame = None
        self.friendly_heading_tape = None
        self.enemy_heading_tape = None

        # Row 6: 机场列表容器
        self.airport_list_frame = tk.Frame(self.zone_frame, bg=Theme.GRAYPILL)
        self.airport_list_frame.grid(row=6, column=0, sticky="ew", padx=pad_x, pady=(0, int(10*s)))

        # Row 7: 燃油标题
        self.fuel_title_lbl = tk.Label(self.zone_frame, text="⛽ 燃油管理", font=font_title, fg=Theme.TEXT, bg=Theme.GRAYPILL, anchor="w")
        self.fuel_title_lbl.grid(row=7, column=0, sticky="ew", padx=pad_x, pady=(0, int(2*s)))
        
        # Row 8: 燃油信息容器
        self.fuel_info_frame = tk.Frame(self.zone_frame, bg=Theme.GRAYPILL)
        self.fuel_info_frame.grid(row=8, column=0, sticky="ew", padx=pad_x, pady=(0, int(6*s)))
        # v6.1.1: 移除旧的CDI字符指示器（已被航向带替代）
        # 保留变量引用以兼容旧代码，但不再使用
        self.zone_cdi_lbl = None
        self.friendly_cdi_lbl = None
        self.enemy_cdi_lbl = None
        
        # 燃油主信息行
        self.fuel_main_lbl = tk.Label(
            self.fuel_info_frame, 
            text="-- kg (--%)  ⏱️ --:--",
            font=font_item, fg=Theme.TEXT_DIM, bg=Theme.GRAYPILL, anchor="w"
        )
        self.fuel_main_lbl.pack(fill="x")
        
        # 油耗率和高度行
        self.fuel_detail_lbl = tk.Label(
            self.fuel_info_frame,
            text="油耗 --kg/min │ 高度 --m",
            font=font_item, fg=Theme.TEXT_MUTED, bg=Theme.GRAYPILL, anchor="w"
        )
        self.fuel_detail_lbl.pack(fill="x")
        
        # 返航估算行
        self.fuel_return_lbl = tk.Label(
            self.fuel_info_frame,
            text="🏠 返航: --",
            font=font_item, fg=Theme.TEXT_DIM, bg=Theme.GRAYPILL, anchor="w"
        )
        self.fuel_return_lbl.pack(fill="x")
        
        # === v6.0 新增：投弹预测区域（仅在ENABLE_CCRP启用时创建）===
        if ENABLE_CCRP:
            # Row 9: 投弹预测标题 (v6.1.1: 行号调整)
            self.bombing_title_lbl = tk.Label(
                self.zone_frame, 
                text="💣 投弹预测", 
                font=font_title, 
                fg=Theme.TEXT, 
                bg=Theme.GRAYPILL, 
                anchor="w"
            )
            self.bombing_title_lbl.grid(row=9, column=0, sticky="ew", padx=pad_x, pady=(0, int(2*s)))
            
            # Row 10: 投弹预测信息容器
            self.bombing_info_frame = tk.Frame(self.zone_frame, bg=Theme.GRAYPILL)
            self.bombing_info_frame.grid(row=10, column=0, sticky="ew", padx=pad_x, pady=(0, int(6*s)))
            
            # 当前炸弹行（可点击选择）
            self.bomb_select_lbl = tk.Label(
                self.bombing_info_frame,
                text=f"炸弹: {BombConfig.format_bomb_name(BombConfig.selected_bomb)} (点击更换)",
                font=font_item, fg=Theme.BLUE, bg=Theme.GRAYPILL, anchor="w", cursor="hand2"
            )
            self.bomb_select_lbl.pack(fill="x")
            self.bomb_select_lbl.bind("<Button-1>", lambda e: self._show_bomb_selector())
            
            # 弹道信息行
            self.bomb_trajectory_lbl = tk.Label(
                self.bombing_info_frame,
                text="弹道: -- m │ 飞行: -- s",
                font=font_item, fg=Theme.TEXT_DIM, bg=Theme.GRAYPILL, anchor="w"
            )
            self.bomb_trajectory_lbl.pack(fill="x")
            
            # 投弹时机行（大号显示）
            font_release = (UIConfig.FONT_ZONE_TITLE[0], int(UIConfig.FONT_ZONE_TITLE[1]*s*1.2), UIConfig.FONT_ZONE_TITLE[2])
            self.bomb_release_lbl = tk.Label(
                self.bombing_info_frame,
                text="⏱️ 等待目标",
                font=font_release, fg=Theme.TEXT_MUTED, bg=Theme.GRAYPILL, anchor="w"
            )
            self.bomb_release_lbl.pack(fill="x", pady=(int(4*s), 0))

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
        """初始化键盘/鼠标绑定
        
        ╔══════════════════════════════════════════════════════════════════════╗
        ║ 说明：右键菜单已移至系统托盘，窗口不再响应右键                         ║
        ╚══════════════════════════════════════════════════════════════════════╝
        """

        self.root.bind(f"<{HotkeyConfig.KEY_LOCK}>", lambda e: self._toggle_lock())
        self.root.bind(f"<{HotkeyConfig.KEY_CORNER}>", lambda e: self._next_corner())
        self.root.bind(f"<{HotkeyConfig.KEY_BEEP}>", lambda e: self._toggle_beep())
        self.root.bind(f"<{HotkeyConfig.KEY_ZONES}>", lambda e: self._toggle_zone_sound())
        self.root.bind("<Control-MouseWheel>", self._adjust_alpha)
        
        # 拖动相关
        self._drag = {"x": 0, "y": 0}
        self.root.bind("<Button-1>", self._start_drag)
        self.root.bind("<B1-Motion>", self._do_drag)
        self.root.bind("<ButtonRelease-1>", self._end_drag)
        
        # 不再绑定窗口右键菜单（功能移至系统托盘）

    def _toggle_panel(self, panel_key: str):
        """切换面板显示状态"""
        current = getattr(PanelConfig, panel_key)
        setattr(PanelConfig, panel_key, not current)
        self._save_config()
        self._refresh_tray()
    
    def _refresh_tray(self):
        """刷新系统托盘菜单状态
        
        调用此方法以确保托盘菜单的勾选状态与实际状态同步。
        """
        if HAS_TRAY and hasattr(self, 'tray') and self.tray:
            try:
                self.tray.update_menu()
            except Exception:
                pass

    def _init_global_hotkeys(self):
        """初始化全局热键
        
        使用HotkeyConfig中配置的快捷键，支持运行时自定义。
        """
        self._ghk = None
        if not os.name == "nt" or not HotkeyConfig.GLOBAL_HOTKEYS:
            return
        
        # 使用配置的快捷键
        hotkeys = [
            (HotkeyConfig.HK_ID_RESET, HotkeyConfig.get_vk(HotkeyConfig.KEY_RESET), self._manual_reset),
            (HotkeyConfig.HK_ID_LOCK, HotkeyConfig.get_vk(HotkeyConfig.KEY_LOCK), self._toggle_lock),
            (HotkeyConfig.HK_ID_CORNER, HotkeyConfig.get_vk(HotkeyConfig.KEY_CORNER), self._next_corner),
            (HotkeyConfig.HK_ID_BEEP, HotkeyConfig.get_vk(HotkeyConfig.KEY_BEEP), self._toggle_beep),
            (HotkeyConfig.HK_ID_ZONES, HotkeyConfig.get_vk(HotkeyConfig.KEY_ZONES), self._toggle_zone_sound),
        ]
        self._ghk = GlobalHotkeys(self.root, hotkeys)
        self._ghk.start()

    def _init_tray(self):
        """初始化系统托盘
        
        托盘菜单根据编译开关动态生成:
        - Lite模式: 仅保留基本功能（重置/锁定/声音/退出）
        - 完整模式: 包含所有功能
        """
        # 保存self引用供嵌套函数使用
        app = self
        
        def icon():
            try:
                return Image.open(resource_path(FileConfig.ICON_FILE)).convert("RGBA")
            except:
                return Image.new('RGBA', (64, 64), Theme.BLUE)
        
        # 回调函数（需要在主线程执行）
        def do_reset(icon, item):
            app.root.after(0, app._manual_reset)
        
        def do_lock(icon, item):
            app.root.after(0, app._toggle_lock)
        
        def do_corner(icon, item):
            app.root.after(0, app._next_corner)
        
        def do_beep(icon, item):
            app.root.after(0, app._toggle_beep)
        
        def do_zone_sound(icon, item):
            app.root.after(0, app._toggle_zone_sound)
        
        def do_edit_checklist(icon, item):
            app.root.after(0, app._edit_checklist)
        
        def do_settings(icon, item):
            app.root.after(0, app._show_settings)
        
        def do_debug(icon, item):
            app.root.after(0, app._toggle_debug)
        
        def do_quit(icon, item):
            app.root.after(0, app._quit)

        def do_about(icon, item):
            app.root.after(0, app._show_about)

        # 状态检查函数
        def is_locked(item):
            return app._locked
        
        def is_beep_on(item):
            return app.sound.is_enabled()
        
        def is_zone_sound_on(item):
            return app._zone_sound_enabled
        
        def is_debug_on(item):
            return app._debug
        
        # 构建菜单项列表
        menu_items = [
            pystray.MenuItem(f"🔄 重置计时器 ({HotkeyConfig.KEY_RESET})", do_reset),
            pystray.MenuItem(f"🔓 锁定/解锁 ({HotkeyConfig.KEY_LOCK})", do_lock, checked=is_locked),
            pystray.MenuItem(f"📍 切换角落 ({HotkeyConfig.KEY_CORNER})", do_corner),
            pystray.Menu.SEPARATOR,
        ]
        
        # 面板子菜单（仅在有可配置面板时显示）
        if ENABLE_ADVANCED_SETTINGS:
            # 面板开关回调
            def toggle_zone(icon, item):
                app.root.after(0, lambda: app._toggle_panel('show_zones'))
            
            def toggle_airfield(icon, item):
                app.root.after(0, lambda: app._toggle_panel('show_airfields'))
            
            def toggle_fuel(icon, item):
                app.root.after(0, lambda: app._toggle_panel('show_fuel'))
            
            def toggle_checklist(icon, item):
                app.root.after(0, lambda: app._toggle_panel('show_checklist'))
            
            def toggle_bombing(icon, item):
                app.root.after(0, lambda: app._toggle_panel('show_bombing'))
            
            def is_zone_panel(item):
                return PanelConfig.show_zones
            
            def is_airfield_panel(item):
                return PanelConfig.show_airfields
            
            def is_fuel_panel(item):
                return PanelConfig.show_fuel
            
            def is_checklist_panel(item):
                return PanelConfig.show_checklist
            
            def is_bombing_panel(item):
                return PanelConfig.show_bombing
            
            panel_items = []
            if ENABLE_ZONES:
                panel_items.append(pystray.MenuItem("🎯 战区导航", toggle_zone, checked=is_zone_panel))
            if ENABLE_AIRFIELDS:
                panel_items.append(pystray.MenuItem("🛫 机场导航", toggle_airfield, checked=is_airfield_panel))
            if ENABLE_FUEL:
                panel_items.append(pystray.MenuItem("⛽ 燃油管理", toggle_fuel, checked=is_fuel_panel))
            if ENABLE_CCRP:
                panel_items.append(pystray.MenuItem("💣 投弹预测", toggle_bombing, checked=is_bombing_panel))
            if ENABLE_CHECKLIST:
                panel_items.append(pystray.MenuItem("✅ 出击检查", toggle_checklist, checked=is_checklist_panel))
            
            if panel_items:
                panel_menu = pystray.Menu(*panel_items)
                menu_items.append(pystray.MenuItem("📊 显示面板", panel_menu))
            
            # v6.2.1: 导航条模式切换
            if ENABLE_ZONES:
                def toggle_nav_mode(icon, item):
                    app.root.after(0, app._toggle_navigation_mode)
                
                def is_standalone_nav(item):
                    return PanelConfig.navigation_mode == "standalone"
                
                menu_items.append(pystray.MenuItem("🧭 独立导航窗口", toggle_nav_mode, checked=is_standalone_nav))
            
            menu_items.append(pystray.Menu.SEPARATOR)
        
        # 声音设置
        menu_items.append(pystray.MenuItem(f"🔊 声音 ({HotkeyConfig.KEY_BEEP})", do_beep, checked=is_beep_on))
        
        # 战区提示音（仅在战区功能启用时显示）
        if ENABLE_ZONES:
            menu_items.append(pystray.MenuItem(f"🔔 战区提示音 ({HotkeyConfig.KEY_ZONES})", do_zone_sound, checked=is_zone_sound_on))
        
        # 检查清单编辑（仅在检查清单功能启用时显示）
        if ENABLE_CHECKLIST:
            menu_items.append(pystray.MenuItem("📝 编辑检查清单", do_edit_checklist))
        
        # 设置（仅在高级设置启用时显示）
        if ENABLE_ADVANCED_SETTINGS:
            menu_items.append(pystray.MenuItem("⚙️ 设置", do_settings))
        
        menu_items.append(pystray.Menu.SEPARATOR)
        menu_items.append(pystray.MenuItem("🐛 Debug模式", do_debug, checked=is_debug_on))
        menu_items.append(pystray.MenuItem("ℹ️ 关于", do_about))
        menu_items.append(pystray.MenuItem("❌ 退出", do_quit))
        
        # 主菜单
        menu = pystray.Menu(*menu_items)
        
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
        self._refresh_tray()

    def _toggle_zone_sound(self):
        """切换战区提示音"""
        self._zone_sound_enabled = not self._zone_sound_enabled
        self._update_hint()
        self._save_config()
        self._refresh_tray()
        if self._zone_sound_enabled:
            self.sound.play(pattern="on")
    def _toggle_navigation_mode(self):
        """切换导航条模式（集成/独立）"""
        if PanelConfig.navigation_mode == "integrated":
            PanelConfig.navigation_mode = "standalone"
            self.nav_window.show()
        else:
            PanelConfig.navigation_mode = "integrated"
            self.nav_window.hide()
        self._save_config()
        self._refresh_tray()

    def _recalc_size(self, keep_pos: bool = True, force_shrink: bool = False):
        """重新计算窗口尺寸
        
        策略: 扩展立即响应, 收缩保守处理(避免抖动), 边界检查
        
        注意:
        - badge_min_width: 徽章行最小宽度(约320px)，确保起落架徽章等能完整显示
        - hint_min_width: 提示文字最小宽度，根据编译开关动态计算
        - 双面板480px, 单面板取max(badge_min_width, hint_min_width)
        - _clamp_to_screen()确保不超出屏幕
        
        Args:
            keep_pos: 保持窗口位置
            force_shrink: 强制收缩
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
        
        # ⚠️ 徽章行最小宽度（确保起落架徽章等能完整显示）
        # 徽章行包含: badge_main + badge_flight + badge_gear(可选) + status_txt
        # 估算: 80 + 80 + 100 + 60 = 320px 基础宽度
        badge_min_width = int(320 * self.scale)
        
        # ⚠️ 提示文字最小宽度（根据编译开关动态计算）
        # 完整版: "F7重置 │ F8解锁 │ F9角落 │ F10声音(🔊开) │ F11战区(🔔开)" ≈ 400px
        # 精简版: "F7重置 │ F8解锁 │ F9角落 │ F10声音(🔊开)" ≈ 320px
        if ENABLE_ZONES:
            hint_min_width = int(400 * self.scale)
        else:
            hint_min_width = int(320 * self.scale)
        
        # 基础最小宽度：取徽章行和提示行中较大的
        base_min_width = max(badge_min_width, hint_min_width)
        
        # 根据面板可见性设置最小宽度
        if self._zone_panel_visible and self._checklist_panel_visible:
            min_width = max(int(480 * self.scale), base_min_width)
        else:
            min_width = base_min_width
        
        new_w = max(min_width, req_w + pad)
        new_h = req_h + pad + int(8 * self.scale)
        
        # 高度收缩策略：避免频繁抖动
        if new_h < old_h:
            if not force_shrink and (old_h - new_h) < 30:
                new_h = old_h
        
        if new_w == old_w and new_h == old_h:
            # 尺寸未变，但仍需检查边界（窗口可能需要重新定位）
            if keep_pos and (old_x, old_y) != (0, 0):
                x, y = self._clamp_to_screen(old_x, old_y)
                if (x, y) != (old_x, old_y):
                    self.root.geometry(f"{self.W}x{self.H}+{x}+{y}")
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
            # 边界检查：确保窗口不超出屏幕
            x, y = self._clamp_to_screen(x, y)
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
        """定位窗口到指定角落(支持多显示器)"""
        m = int(UIConfig.WINDOW_MARGIN * self.scale)
        
        # 获取当前窗口所在的显示器
        try:
            current_x = self.root.winfo_x()
            current_y = self.root.winfo_y()
        except tk.TclError:
            current_x, current_y = 0, 0
        
        # 如果窗口位置有效，获取该位置所在的显示器
        if (current_x, current_y) != (0, 0):
            monitor = Win32.get_monitor_at(current_x, current_y)
        else:
            # 否则使用主显示器
            monitors = Win32.get_all_monitors()
            monitor = next((m for m in monitors if m.get("is_primary")), monitors[0] if monitors else None)
        
        # 如果无法获取显示器信息，回退到主屏幕
        if not monitor:
            sw, sh = Win32.screen_size()
            monitor = {"x": 0, "y": 0, "width": sw, "height": sh}
        
        # 计算在当前显示器上的角落位置
        mon_x = monitor["x"]
        mon_y = monitor["y"]
        mon_w = monitor["width"]
        mon_h = monitor["height"]
        
        pos = {
            Corner.TOP_RIGHT: (mon_x + mon_w - self.W - m, mon_y + m),
            Corner.TOP_LEFT: (mon_x + m, mon_y + m),
            Corner.BOTTOM_RIGHT: (mon_x + mon_w - self.W - m, mon_y + mon_h - self.H - m),
            Corner.BOTTOM_LEFT: (mon_x + m, mon_y + mon_h - self.H - m),
        }
        
        if self._user_moved and self._manual_pos:
            x, y = self._manual_pos
        else:
            x, y = pos[self._corner]
        
        # 边界检查（基于当前显示器）
        x, y = self._clamp_to_screen(x, y)
        self.root.geometry(f"{self.W}x{self.H}+{x}+{y}")

    def _clamp_to_screen(self, x: int, y: int) -> Tuple[int, int]:
        """确保窗口位置不超出屏幕边界(支持多显示器)
        
        Args:
            x, y: 窗口左上角坐标
        
        Returns:
            调整后的(x, y)坐标
        """
        m = int(UIConfig.WINDOW_MARGIN * self.scale)
        
        # 获取窗口中心点所在的显示器
        center_x = x + self.W // 2
        center_y = y + self.H // 2
        monitor = Win32.get_monitor_at(center_x, center_y)
        
        # 如果无法获取显示器信息，回退到主屏幕
        if not monitor:
            sw, sh = Win32.screen_size()
            monitor = {"x": 0, "y": 0, "width": sw, "height": sh}
        
        mon_x = monitor["x"]
        mon_y = monitor["y"]
        mon_w = monitor["width"]
        mon_h = monitor["height"]
        
        # 确保右边界不超出（优先保证窗口在屏幕内）
        if x + self.W > mon_x + mon_w - m:
            x = mon_x + mon_w - self.W - m
        # 确保左边界不超出
        if x < mon_x + m:
            x = mon_x + m
        # 确保下边界不超出
        if y + self.H > mon_y + mon_h - m:
            y = mon_y + mon_h - self.H - m
        # 确保上边界不超出
        if y < mon_y + m:
            y = mon_y + m
        
        return x, y

    def _toggle_lock(self):
        """切换锁定/解锁
        
        v6.0.1 优化：锁定/解锁时使用不同透明度，提供明确的视觉反馈
        - 锁定状态：使用配置的透明度（默认210）
        - 解锁状态：提高透明度到240，让窗口更明显便于拖动
        """
        self._locked = not self._locked
        # 解锁时提高不透明度，让用户更容易看到可拖动区域
        alpha = UIConfig.WINDOW_ALPHA if self._locked else min(240, UIConfig.WINDOW_ALPHA + 30)
        Win32.setup_window(self.hwnd, click_through=self._locked, alpha=alpha)
        self._update_hint()
        self._refresh_tray()

    def _hint_text(self) -> str:
        """生成提示文本
        
        注意: 修改提示文字长度时需同步修改_recalc_size()中的hint_min_width
        根据编译开关动态生成提示内容
        """
        sound = "🔊开" if self.sound.is_enabled() else "🔇关"
        
        # 使用配置的快捷键
        k_reset = HotkeyConfig.KEY_RESET
        k_lock = HotkeyConfig.KEY_LOCK
        k_corner = HotkeyConfig.KEY_CORNER
        k_beep = HotkeyConfig.KEY_BEEP
        
        if self._locked:
            parts = [f"{k_reset}重置", f"{k_lock}解锁", f"{k_corner}角落", f"{k_beep}声音({sound})"]
            # 战区提示音仅在战区功能启用时显示
            if ENABLE_ZONES:
                zone_sound = "🔔开" if self._zone_sound_enabled else "🔕关"
                k_zones = HotkeyConfig.KEY_ZONES
                parts.append(f"{k_zones}战区({zone_sound})")
            return " │ ".join(parts)
        else:
            parts = ["拖动移动", f"{k_lock}锁定", f"{k_beep}声音({sound})"]
            if ENABLE_ZONES:
                zone_sound = "🔔开" if self._zone_sound_enabled else "🔕关"
                k_zones = HotkeyConfig.KEY_ZONES
                parts.append(f"{k_zones}战区({zone_sound})")
            return " │ ".join(parts)

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
        self._refresh_tray()
        if enabled:
            self.sound.play(pattern="on")

    def _manual_reset(self):
        """手动重置计时器（F7）"""
        self.game.manual_reset()
        self.sound.play(*SoundConfig.BEEP_MANUAL_RESET)

    def _show_settings(self):
        """显示设置对话框
        
        从托盘菜单调用，不受窗口锁定状态影响。
        """
        SettingsDialog(self.root, self)

    def _edit_checklist(self):
        """编辑检查清单
        
        从托盘菜单调用，不受窗口锁定状态影响。
        """
        ChecklistEditor(self.root, self)

    def _show_about(self):
        """显示关于对话框"""
        AboutDialog(self.root, self)

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
        """结束拖动
        
        窗口吸附: 边缘距屏幕<SNAP_DISTANCE时自动吸附(支持多显示器)
        """
        if self._locked:
            return
        try:
            x = int(self.root.winfo_x())
            y = int(self.root.winfo_y())
            
            # 应用窗口吸附
            if SnapConfig.enabled:
                w = self.root.winfo_width()
                h = self.root.winfo_height()
                new_x, new_y = Win32.snap_to_edges(x, y, w, h, SnapConfig.SNAP_DISTANCE)
                
                # 如果位置变化，更新窗口位置
                if (new_x, new_y) != (x, y):
                    self.root.geometry(f"+{new_x}+{new_y}")
                    x, y = new_x, new_y
            
            self._manual_pos = (x, y)
            self._user_moved = True
            self._save_config()
        except tk.TclError:
            pass

    def _poll_loop(self):
        """逻辑轮询循环(独立线程)
        
        优化: 使用轻量级is_api_down属性而非完整snapshot()决定轮询间隔
        """
        while not self._stop:
            loop_start = time.monotonic()
            self.game.tick()
            # 使用轻量级属性替代完整snapshot
            interval = NetworkConfig.BACKOFF_MAX if self.game.is_api_down else NetworkConfig.POLL_INTERVAL
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
    def _update_tape_info_labels(self, targets_info: list, primary_zone):
        """更新航向带下方的状态提示（战区+友方机场）
        
        v6.2.1: 分两行显示战区和友方机场的状态
        v6.2.2: 统一格式，战区添加距离/ETE，机场添加状态描述
        v6.5: 重构 - 使用工具函数复用导航逻辑
        
        Args:
            targets_info: 目标信息列表
            primary_zone: 主目标战区（用于计算容差）
        """
        # === 更新战区状态提示 ===
        zone_info = next((t for t in targets_info if t['type'] == 'zone'), None)
        if primary_zone and self.tape_turn_lbl and self.tape_deviation_lbl and self.tape_tolerance_lbl:
            tolerance = get_cdi_tolerance(primary_zone.distance_km)
            scale = calculate_heading_tape_scale(primary_zone.distance_km)
            rel = primary_zone.relative
            abs_rel = abs(rel)
            
            # v6.5: 使用工具函数计算转向指示和状态
            turn_text, turn_color = calculate_zone_turn_indicator(rel, tolerance)
            dev_text, dev_color = calculate_zone_status(abs_rel, tolerance)
            
            # 距离和ETE
            ete_str = zone_info.get('ete_str') if zone_info else None
            info_text = format_distance_ete(primary_zone.distance_km, ete_str)
            
            # v6.4: 容差移至图例行
            tol_text = f"±{tolerance:.1f}° {scale:.1f}x"
            
            self.tape_turn_lbl.config(text=turn_text, fg=turn_color)
            self.tape_deviation_lbl.config(text=dev_text, fg=dev_color)
            if hasattr(self, 'tape_zone_info') and self.tape_zone_info:
                self.tape_zone_info.config(text=info_text, fg=Theme.RED)
            # 更新图例行的容差显示
            if hasattr(self, 'tape_tolerance_legend') and self.tape_tolerance_legend:
                self.tape_tolerance_legend.config(text=tol_text)
            self.tape_tolerance_lbl.config(text="")
            
            if self.tape_zone_row:
                self.tape_zone_row.pack(fill="x", pady=(int(2*self.scale), 0))
        elif self.tape_turn_lbl and self.tape_deviation_lbl and self.tape_tolerance_lbl:
            # 无战区目标时隐藏战区行
            self.tape_turn_lbl.config(text="", fg=Theme.TEXT_MUTED)
            self.tape_deviation_lbl.config(text="无目标", fg=Theme.TEXT_MUTED)
            if hasattr(self, 'tape_zone_info') and self.tape_zone_info:
                self.tape_zone_info.config(text="")
            self.tape_tolerance_lbl.config(text="")
            if self.tape_zone_row:
                self.tape_zone_row.pack_forget()
        
        # === 更新友方机场状态提示 ===
        friendly_info = next((t for t in targets_info if t['type'] == 'friendly'), None)
        if friendly_info and self.tape_friendly_turn and self.tape_friendly_info:
            rel = friendly_info['relative']
            abs_rel = abs(rel)
            dist = friendly_info['distance_km']
            
            # v6.5: 使用工具函数计算转向指示和状态
            turn_text, turn_color = calculate_airfield_turn_indicator(rel)
            status_text, status_color = calculate_airfield_status(abs_rel)
            
            # 距离和ETE
            info_text = format_distance_ete(dist, friendly_info.get('ete_str'))
            
            self.tape_friendly_turn.config(text=turn_text, fg=turn_color)
            if hasattr(self, 'tape_friendly_status') and self.tape_friendly_status:
                self.tape_friendly_status.config(text=status_text, fg=status_color)
            self.tape_friendly_info.config(text=info_text, fg=Theme.BLUE)
            
            if self.tape_friendly_row:
                self.tape_friendly_row.pack(fill="x", pady=(int(1*self.scale), 0))
        elif self.tape_friendly_row:
            # 无友方机场时隐藏该行
            self.tape_friendly_row.pack_forget()

    def _set_checklist_visible(self, visible: bool):
        """设置检查清单可见性"""
        if self._checklist_panel_visible != visible:
            self._checklist_panel_visible = visible
            self._update_mid_panel_layout()

    def _update_zone_display(self, snap: UISnapshot):
        """更新战区显示
        
        性能优化(每50ms调用):
        - 使用pack_forget()而非destroy()
        - Label复用池避免频繁创建
        - 字体缓存(_get_font)
        - 只在数量变化时调用_recalc_size()
        """
        s = self.scale
        font_item = self._get_font('zone_item')
        pad_x = int(8*s)
        
        # 更新航向显示
        if snap.player_heading > 0:
            self.heading_lbl.config(text=f"HDG: {int(snap.player_heading):03d}°")
        else:
            self.heading_lbl.config(text="HDG: ---")
        
        zone_count = 0
        airport_count = 0
        
        # === 战区导航区块（根据编译开关和PanelConfig.show_zones控制）===
        if ENABLE_ZONES and PanelConfig.show_zones:
            # 使用grid显示（行号固定，顺序不会乱）
            self.zone_header_frame.grid(row=0, column=0, sticky="ew", padx=pad_x, pady=(int(6*s), int(2*s)))
            self.zone_list_frame.grid(row=3, column=0, sticky="ew", padx=pad_x, pady=(0, int(10*s)))
            
            # v6.2: 更新统一航向带（战区+机场+被摧毁）
            if self.heading_tape is not None and snap.player_heading > 0:
                targets = []
                active_targets_info = []  # 用于生成文字信息
                
                # v6.3: 添加所有战区（目标和非目标）
                target_zone = next((z for z in snap.zones if z.is_target), None)
                for zone in snap.zones:
                    is_target = zone.is_target
                    targets.append({
                        'type': 'zone',
                        'relative': zone.relative,
                        'distance_km': zone.distance_km,
                        'is_primary': is_target,
                        'is_target': is_target  # 新增字段用于区分目标/非目标
                    })
                    # 只有目标战区才添加到active_targets_info
                    if is_target:
                        active_targets_info.append({
                            'type': 'zone',
                            'name': '战区',
                            'icon': '⊚',
                            'relative': zone.relative,
                            'distance_km': zone.distance_km,
                            'ete_str': zone.ete_str if hasattr(zone, 'ete_str') else '',
                            'color': Theme.RED
                        })
                
                # 添加被摧毁的战区
                if snap.zone_destroyed_alert and hasattr(self.game.state.zone_nav, 'destroyed_zones'):
                    for dz in self.game.state.zone_nav.destroyed_zones:
                        if hasattr(dz, 'relative'):
                            targets.append({
                                'type': 'destroyed',
                                'relative': dz.relative,
                                'distance_km': dz.distance * ZoneConfig.DISTANCE_SCALE,
                                'is_primary': False
                            })
                
                # v6.3: 添加所有友方机场
                if snap.friendly_airfield:
                    af = snap.friendly_airfield
                    is_in_front = abs(af.relative) <= 90
                    targets.append({
                        'type': 'friendly',
                        'relative': af.relative,
                        'distance_km': af.distance_km,
                        'is_primary': False,
                        'is_target': is_in_front  # 前方180°视为活动目标
                    })
                    if is_in_front:
                        active_targets_info.append({
                            'type': 'friendly',
                            'name': '友方',
                            'icon': '✈',
                            'relative': af.relative,
                            'distance_km': af.distance_km,
                            'ete_str': af.ete_str,
                            'color': Theme.BLUE
                        })
                
                # v6.3: 添加所有敌方机场
                if snap.enemy_airfields:
                    for af in snap.enemy_airfields:
                        is_in_front = abs(af.relative) <= 90
                        targets.append({
                            'type': 'enemy',
                            'relative': af.relative,
                            'distance_km': af.distance_km,
                            'is_primary': False,
                            'is_target': is_in_front  # 前方180°视为活动目标
                        })
                        if af.is_target and is_in_front:
                            active_targets_info.append({
                                'type': 'enemy',
                                'name': '敌方',
                                'icon': '✈',
                                'relative': af.relative,
                                'distance_km': af.distance_km,
                                'ete_str': af.ete_str,
                                'color': Theme.ORANGE
                            })
                
                # 更新航向带
                primary_dist = target_zone.distance_km if target_zone else 10.0
                self.heading_tape.update_tape_multi(snap.player_heading, targets, primary_dist)
                
                # 更新目标信息文字（所有前方目标）
                self._update_tape_info_labels(active_targets_info, target_zone)
                
                # v6.2.1: 根据导航模式决定是否显示集成航向带
                if PanelConfig.navigation_mode == "integrated":
                    self.heading_tape_frame.grid(row=1, column=0, sticky="ew", padx=pad_x, pady=(int(2*s), int(4*s)))
                else:
                    self.heading_tape_frame.grid_remove()
                
                # v6.2.1: 更新独立导航窗口
                if hasattr(self, 'nav_window') and self.nav_window.is_visible():
                    self.nav_window.update_display(snap, targets, active_targets_info, target_zone)
            elif self.heading_tape is not None:
                self.heading_tape.clear()
                if self.tape_info_container:
                    for lbl in self._tape_info_labels:
                        lbl.pack_forget()
                if PanelConfig.navigation_mode == "integrated":
                    self.heading_tape_frame.grid_remove()
                
                # v6.2.1: 独立窗口也需要清空
                if hasattr(self, 'nav_window') and self.nav_window.is_visible():
                    self.nav_window.update_display(snap, [], [], None)
            
            # 战区被摧毁警告（row=2）
            if snap.zone_destroyed_alert:
                alert_text = "💥 战区被摧毁："
                if getattr(snap, "destroyed_zone_text", ""):
                    alert_text += snap.destroyed_zone_text
                else:
                    alert_text = "💥 战区已摧毁!"
                wrap = max(int(220*s), self.zone_frame.winfo_width() - int(16*s))
                self.zone_alert_lbl.config(text=alert_text, wraplength=wrap, justify="left")
                self.zone_alert_lbl.grid(row=2, column=0, sticky="ew", padx=pad_x, pady=(0, int(4*s)))
                if snap.should_play_destroyed_sound and not self._last_zone_destroyed_alert and self._zone_sound_enabled:
                    self.sound.play(pattern="zone_destroyed")
                self._last_zone_destroyed_alert = True
            else:
                self.zone_alert_lbl.grid_remove()
                self._last_zone_destroyed_alert = False
            
            # 先隐藏所有现有标签
            for lbl in self._zone_label_pool:
                lbl.pack_forget()
            
            # 计算需要的标签数量（v6.1.1: 移除CDI相关计数）
            zone_count = len(snap.zones) if snap.zones else 1
            
            # 确保池中有足够的标签
            while len(self._zone_label_pool) < zone_count:
                lbl = tk.Label(self.zone_list_frame, text="", font=font_item, 
                              fg=Theme.TEXT_DIM, bg=Theme.GRAYPILL, anchor="w")
                self._zone_label_pool.append(lbl)
            
            # 更新并显示标签
            idx = 0
            
            if not snap.zones:
                lbl = self._zone_label_pool[idx]
                lbl.config(text="无战区", fg=Theme.TEXT_MUTED)
                lbl.pack(fill="x")
                idx += 1
            else:
                for zone in snap.zones:
                    marker = "➤" if zone.is_target else "○"
                    dist_text = f"{zone.distance_km:.1f}km" if zone.distance_km < 10 else f"{int(zone.distance_km)}km"
                    rel_sign = "+" if zone.relative > 0 else ""
                    if zone.is_target:
                        rel_text = f"{rel_sign}{zone.relative:.2f}°"
                    else:
                        rel_text = f"{rel_sign}{int(zone.relative)}°"
                    
                    # v6.2.1: 去掉ETE显示（航向带下方已有）
                    text = f"{marker} {zone.direction} {dist_text}  ({rel_text})"
                    fg = Theme.GREEN if zone.is_target and not snap.is_deviating else Theme.ORANGE if zone.is_target else Theme.TEXT_DIM
                    
                    lbl = self._zone_label_pool[idx]
                    lbl.config(text=text, fg=fg)
                    lbl.pack(fill="x")
                    idx += 1
        else:
            # 隐藏战区区块（使用grid_remove保持行号）
            self.zone_header_frame.grid_remove()
            self.zone_list_frame.grid_remove()
            self.zone_alert_lbl.grid_remove()
            for lbl in self._zone_label_pool:
                lbl.pack_forget()

        # === 机场导航区块（根据编译开关和PanelConfig.show_airfields控制）===
        if ENABLE_AIRFIELDS and PanelConfig.show_airfields:
            # 使用grid显示（行号固定）- v6.1.1: 调整行号
            self.airport_title_lbl.grid(row=4, column=0, sticky="ew", padx=pad_x, pady=(0, int(2*s)))
            
            # v6.2: 机场航向带已合并到主航向带，此处不再需要单独处理
            
            self.airport_list_frame.grid(row=6, column=0, sticky="ew", padx=pad_x, pady=(0, int(10*s)))
            
            for lbl in self._airport_label_pool:
                lbl.pack_forget()
            
            # 计算需要的机场标签数量
            airport_count = 0
            if snap.friendly_airfield:
                airport_count += 1
            if snap.enemy_airfields:
                airport_count += len(snap.enemy_airfields)
            if airport_count == 0:
                airport_count = 1
            
            # 确保池中有足够的标签
            while len(self._airport_label_pool) < airport_count:
                lbl = tk.Label(self.airport_list_frame, text="", font=font_item,
                              fg=Theme.TEXT_DIM, bg=Theme.GRAYPILL, anchor="w")
                self._airport_label_pool.append(lbl)
            
            # 更新并显示机场标签（v6.1.1: 移除CDI相关代码）
            ap_idx = 0
            
            if snap.friendly_airfield:
                af = snap.friendly_airfield
                dist_text = f"{af.distance_km:.1f}km" if af.distance_km < 10 else f"{int(af.distance_km)}km"
                rel_sign = "+" if af.relative > 0 else ""
                rel_text = f"{rel_sign}{int(af.relative)}°"
                # v6.2.1: 去掉ETE显示（航向带下方已有）
                text = f"🟢 ➤ {af.direction} {dist_text}  ({rel_text})"
                lbl = self._airport_label_pool[ap_idx]
                lbl.config(text=text, fg=Theme.GREEN)
                lbl.pack(fill="x")
                ap_idx += 1
            
            if snap.enemy_airfields:
                for af in snap.enemy_airfields:
                    marker = "➤" if af.is_target else "○"
                    dist_text = f"{af.distance_km:.1f}km" if af.distance_km < 10 else f"{int(af.distance_km)}km"
                    rel_sign = "+" if af.relative > 0 else ""
                    rel_text = f"{rel_sign}{int(af.relative)}°"
                    # v6.2.1: 去掉ETE显示（航向带下方已有）
                    text = f"🔴 {marker} {af.direction} {dist_text}  ({rel_text})"
                    fg = Theme.ORANGE if af.is_target else Theme.TEXT_DIM
                    lbl = self._airport_label_pool[ap_idx]
                    lbl.config(text=text, fg=fg)
                    lbl.pack(fill="x")
                    ap_idx += 1
            
            if ap_idx == 0:
                lbl = self._airport_label_pool[0]
                lbl.config(text="无机场数据", fg=Theme.TEXT_MUTED)
                lbl.pack(fill="x")
                ap_idx = 1
        else:
            # 隐藏机场区块（使用grid_remove保持行号）
            self.airport_title_lbl.grid_remove()
            if self.airport_tape_frame:
                self.airport_tape_frame.grid_remove()
            self.airport_list_frame.grid_remove()
            for lbl in self._airport_label_pool:
                lbl.pack_forget()
        
        # === 燃油信息区块（根据编译开关和PanelConfig.show_fuel控制）===
        if ENABLE_FUEL and PanelConfig.show_fuel:
            # 使用grid显示（行号固定）- v6.1.1: 调整行号
            self.fuel_title_lbl.grid(row=7, column=0, sticky="ew", padx=pad_x, pady=(0, int(2*s)))
            self.fuel_info_frame.grid(row=8, column=0, sticky="ew", padx=pad_x, pady=(0, int(6*s)))
            self._update_fuel_display(snap, font_item)
        else:
            # 隐藏燃油区块（使用grid_remove保持行号）
            self.fuel_title_lbl.grid_remove()
            self.fuel_info_frame.grid_remove()
        
        # === v6.0 新增：投弹预测区块（仅在ENABLE_CCRP启用时处理）===
        if ENABLE_CCRP:
            if PanelConfig.show_bombing:
                # v6.1.1: 调整行号
                self.bombing_title_lbl.grid(row=9, column=0, sticky="ew", padx=pad_x, pady=(0, int(2*s)))
                self.bombing_info_frame.grid(row=10, column=0, sticky="ew", padx=pad_x, pady=(0, int(6*s)))
                self._update_bombing_display(snap, font_item)
            else:
                self.bombing_title_lbl.grid_remove()
                self.bombing_info_frame.grid_remove()
        
        # 智能触发尺寸重算（只在数量变化时）
        total_count = zone_count + airport_count
        if total_count != (self._last_zone_count + self._last_airport_count):
            self._last_zone_count = zone_count
            self._last_airport_count = airport_count
            return True  # 需要重算尺寸
        return False  # 不需要重算

    def _update_fuel_display(self, snap: UISnapshot, font_item):
        """更新燃油信息显示（v5.8 新增）"""
        # 燃油主信息：油量、百分比、剩余时间
        if snap.fuel_kg > 0:
            # 油量和百分比
            fuel_text = f"{int(snap.fuel_kg)}kg ({snap.fuel_percent:.0f}%)"
            
            # 剩余飞行时间
            if snap.fuel_time_remaining_str:
                fuel_text += f"  ⏱️ {snap.fuel_time_remaining_str}"
            else:
                fuel_text += "  ⏱️ 计算中..."
            
            # 根据百分比设置颜色
            if snap.fuel_percent <= FuelConfig.DANGER_PERCENT:
                fuel_color = Theme.RED
            elif snap.fuel_percent <= FuelConfig.WARNING_PERCENT:
                fuel_color = Theme.YELLOW
            else:
                fuel_color = Theme.TEXT
            
            self.fuel_main_lbl.config(text=fuel_text, fg=fuel_color)
        else:
            self.fuel_main_lbl.config(text="-- kg (--%)", fg=Theme.TEXT_MUTED)
        
        # 油耗率和高度
        if snap.fuel_rate_stable and snap.fuel_rate_kg_min > 0:
            rate_text = f"油耗 {snap.fuel_rate_kg_min:.0f}kg/min"
        else:
            rate_text = "油耗 --"
        
        if snap.altitude_m > 0:
            alt_text = f"高度 {int(snap.altitude_m)}m"
        else:
            alt_text = "高度 --"
        
        self.fuel_detail_lbl.config(text=f"{rate_text} │ {alt_text}")
        
        # 返航估算
        if snap.return_status != "unknown" and snap.return_fuel_needed_kg > 0:
            needed_text = f"需~{int(snap.return_fuel_needed_kg)}kg"
            
            # 计算返航油量占比
            if snap.fuel_initial_kg > 0:
                return_percent = (snap.return_fuel_needed_kg / snap.fuel_initial_kg) * 100
                needed_text += f" ({return_percent:.0f}%)"
            
            # 状态标识
            if snap.return_status == "safe":
                status_icon = "✅ 充足"
                return_color = Theme.GREEN
            elif snap.return_status == "warning":
                status_icon = "⚠️ 注意"
                return_color = Theme.YELLOW
            else:  # danger
                status_icon = "🔴 不足!"
                return_color = Theme.RED
            
            return_text = f"🏠 返航: {needed_text}  {status_icon}"
            self.fuel_return_lbl.config(text=return_text, fg=return_color)
        elif snap.friendly_distance_km > 0:
            self.fuel_return_lbl.config(
                text=f"🏠 返航: 距离{snap.friendly_distance_km:.0f}km (估算中...)", 
                fg=Theme.TEXT_MUTED
            )
        else:
            self.fuel_return_lbl.config(text="🏠 返航: 无机场数据", fg=Theme.TEXT_MUTED)

    def _update_bombing_display(self, snap: UISnapshot, font_item):
        """更新投弹预测信息显示（v6.0新增）"""
        self.bomb_select_lbl.config(text=f"炸弹: {BombConfig.format_bomb_name(snap.bomb_name)} (点击更换)")
        
        if snap.bombing_valid:
            bomb_range_km = snap.bomb_range_m / 1000.0
            trajectory_text = f"弹道: {bomb_range_km:.2f}km │ 飞行: {snap.bomb_flight_time:.1f}s"
            self.bomb_trajectory_lbl.config(text=trajectory_text, fg=Theme.TEXT_DIM)
            
            status = snap.release_status
            dist_m = snap.release_distance_m
            if dist_m > 1000:
                dist_str = f"{dist_m/1000:.2f}km"
            elif dist_m > 100:
                dist_str = f"{int(dist_m)}m"
            else:
                dist_str = f"{dist_m:.0f}m"
            
            if status == "ready":
                time_str = f"{snap.time_to_release:.2f}s"
                release_text = f"💣 投弹! {time_str} ({dist_str})"
                release_color = Theme.GREEN
            elif status == "approaching":
                time_str = f"{snap.time_to_release:.1f}s"
                release_text = f"⏱️ {time_str} ({dist_str})"
                release_color = Theme.YELLOW
            elif status == "passed":
                release_text = f"❌ 已飞过 {dist_str}"
                release_color = Theme.RED
            elif status == "too_far":
                time_str = f"{snap.time_to_release:.0f}s"
                release_text = f"🎯 {dist_str} ({time_str})"
                release_color = Theme.TEXT_DIM
            else:
                release_text = "⏳ 计算中..."
                release_color = Theme.TEXT_MUTED
            
            self.bomb_release_lbl.config(text=release_text, fg=release_color)
        else:
            self.bomb_trajectory_lbl.config(text="弹道: -- km │ 飞行: -- s", fg=Theme.TEXT_MUTED)
            
            if snap.on_ground:
                release_text = "🛫 请起飞"
            elif snap.altitude_m <= 50:
                release_text = "📈 请爬升"
            elif not snap.has_target:
                release_text = "🎯 无目标战区"
            else:
                release_text = "↻ 请对准目标"
            
            self.bomb_release_lbl.config(text=release_text, fg=Theme.TEXT_MUTED)

    def _show_bomb_selector(self):
        """显示炸弹选择对话框"""
        BombSelectorDialog(self.root, self)

    def _update_ui(self):
        """UI更新循环(20fps)
        
        性能优化:
        - _update_zone_display()返回是否需重算尺寸
        - 仅在可见性/数量变化时调用_recalc_size()
        - 使用缓存字体和Label复用池
        """
        if self._stop:
            return
        
        snap = self.game.snapshot()

        # 控制面板可见性（结合PanelConfig设置和编译开关）
        # 战区/机场/燃油/投弹面板需要任一相关面板启用
        has_zone_data = len(snap.zones) > 0
        has_airfield_data = snap.friendly_airfield is not None or len(snap.enemy_airfields) > 0
        
        show_zone_panel = (
            (snap.phase == Phase.ALIVE) and 
            (not snap.api_down) and 
            (
                (ENABLE_ZONES and PanelConfig.show_zones and has_zone_data) or 
                (ENABLE_AIRFIELDS and PanelConfig.show_airfields and has_airfield_data) or
                (ENABLE_FUEL and PanelConfig.show_fuel) or
                (ENABLE_CCRP and PanelConfig.show_bombing)
            )
        )
        self._set_zone_panel_visible(show_zone_panel)
        if show_zone_panel: 
            # _update_zone_display 返回是否需要重算尺寸
            need_recalc = self._update_zone_display(snap)
            if need_recalc:
                self._recalc_size()

        # 检查清单面板（受编译开关控制）
        show_chk = (
            ENABLE_CHECKLIST and
            (snap.phase == Phase.ALIVE) and 
            (snap.on_ground or snap.landed_flash) and 
            (not snap.api_down) and
            PanelConfig.show_checklist
        )
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
        
        # v5.9.6 新增：起落架警告徽章显示/隐藏
        if snap.gear_warning:
            self.badge_gear.set("⚠️起落架", Theme.TEXT, Theme.ORANGE)
            if not self.badge_gear.winfo_ismapped():
                self.badge_gear.pack(side="left", padx=(int(UIConfig.SPACING_BADGE*self.scale), 0), after=self.badge_flight)
        else:
            if self.badge_gear.winfo_ismapped():
                self.badge_gear.pack_forget()
        
        # v6.6.0 新增：起落架进度条显示/隐藏
        if snap.gear_moving:
            # 显示进度条
            if not self.gear_progress_frame.winfo_ismapped():
                self.gear_progress_frame.pack(side="left", padx=(int(UIConfig.SPACING_BADGE*self.scale), 0), after=self.badge_flight)
            # 更新进度和颜色
            progress = snap.gear_pct / 100.0
            # 收起=蓝色，放下=黄色
            bar_color = Theme.BLUE if snap.gear_retracting else Theme.YELLOW
            self.gear_progress_fill.config(bg=bar_color)
            self.gear_progress_fill.place(relwidth=progress)
        else:
            # 隐藏进度条
            if self.gear_progress_frame.winfo_ismapped():
                self.gear_progress_frame.pack_forget()
        
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
# 独立导航窗口
# ============================================================================

class NavigationWindow:
    """独立导航条窗口
    
    v6.2.1新增：可拖动的独立导航窗口，方便放置在屏幕任意位置
    
    特性:
    - 无边框透明窗口
    - 支持拖动
    - 关闭时隐藏而非退出
    - 位置自动保存
    - 与主窗口数据同步
    """
    
    def __init__(self, parent_app):
        """初始化独立导航窗口
        
        Args:
            parent_app: 主App实例，用于访问游戏数据和配置
        """
        self.app = parent_app
        self.root = parent_app.root
        self.scale = parent_app.scale
        self._visible = False
        self._drag_data = {"x": 0, "y": 0}
        
        # 创建顶层窗口
        # 定义透明键颜色（用于背景透明，内容不透明）
        self._transparent_color = "#010101"  # 接近黑色但不影响正常UI
        
        self.window = tk.Toplevel(self.root)
        self.window.title("导航条")
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        # 窗口背景设置为透明键颜色
        self.window.configure(bg=self._transparent_color)
        
        # 初始隐藏
        self.window.withdraw()
        
        # 获取窗口句柄
        self.window.update_idletasks()  # 确保窗口已创建
        self.hwnd = ctypes.windll.user32.GetParent(self.window.winfo_id())
        
        # 使用Win32 API设置分层窗口：背景透明，内容保持不透明
        self._setup_layered_window()
        
        # 初始化UI
        self._init_ui()
        
        # 绑定事件
        self._init_bindings()
        
        # 恢复位置
        self._restore_position()
    
    def _setup_layered_window(self):
        """设置分层窗口属性
        
        使用透明键颜色实现背景透明、内容不透明的效果，
        同时应用应用程序的整体透明度配置
        """
        GWL_EXSTYLE = -20
        WS_EX_LAYERED = 0x00080000
        WS_EX_TOPMOST = 0x00000008
        WS_EX_TOOLWINDOW = 0x00000080
        LWA_COLORKEY = 0x1
        LWA_ALPHA = 0x2
        
        try:
            user32 = ctypes.windll.user32
            # 获取当前样式并添加分层窗口样式
            style = user32.GetWindowLongW(self.hwnd, GWL_EXSTYLE)
            style |= (WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_TOOLWINDOW)
            user32.SetWindowLongW(self.hwnd, GWL_EXSTYLE, style)
            
            # 将透明键颜色转换为COLORREF (BGR格式)
            color_hex = self._transparent_color.lstrip('#')
            r, g, b = int(color_hex[0:2], 16), int(color_hex[2:4], 16), int(color_hex[4:6], 16)
            colorref = r | (g << 8) | (b << 16)
            
            # 同时应用透明键和整体透明度
            alpha = int(UIConfig.WINDOW_ALPHA)
            user32.SetLayeredWindowAttributes(self.hwnd, colorref, alpha, LWA_COLORKEY | LWA_ALPHA)
        except (OSError, AttributeError):
            # 降级：使用Tkinter的alpha属性
            self.window.attributes("-alpha", UIConfig.WINDOW_ALPHA / 255.0)
    
    def update_transparency(self):
        """更新窗口透明度（响应透明度配置变化）"""
        self._setup_layered_window()
    
    def _init_ui(self):
        """初始化导航条UI"""
        s = self.scale
        pad = int(6 * s)
        
        # 主框架
        self.main_frame = tk.Frame(self.window, bg=Theme.GRAYPILL)
        self.main_frame.pack(fill="both", expand=True, padx=2, pady=2)
        
        # 内容区域（动态内容放这里，确保hint始终在底部）
        self.content_frame = tk.Frame(self.main_frame, bg=Theme.GRAYPILL)
        self.content_frame.pack(fill="both", expand=True)
        
        # 标题栏（用于拖动）
        self.title_bar = tk.Frame(self.content_frame, bg=Theme.GRAYPILL)
        self.title_bar.pack(fill="x", padx=pad, pady=(pad, 0))
        
        font_title = (UIConfig.FONT_ZONE_TITLE[0], int(UIConfig.FONT_ZONE_TITLE[1]*s*0.9))
        self.title_lbl = tk.Label(
            self.title_bar, text="🎯 导航", font=font_title,
            fg=Theme.TEXT, bg=Theme.GRAYPILL, anchor="w"
        )
        self.title_lbl.pack(side="left")
        
        # 航向显示
        font_hdg = (UIConfig.FONT_ZONE_ITEM[0], int(UIConfig.FONT_ZONE_ITEM[1]*s))
        self.heading_lbl = tk.Label(
            self.title_bar, text="HDG: ---", font=font_hdg,
            fg=Theme.TEXT_DIM, bg=Theme.GRAYPILL, anchor="e"
        )
        self.heading_lbl.pack(side="right")
        
        # 关闭按钮（点击后隐藏窗口）
        self.close_btn = tk.Label(
            self.title_bar, text="✕", font=font_title,
            fg=Theme.TEXT_MUTED, bg=Theme.GRAYPILL, cursor="hand2"
        )
        self.close_btn.pack(side="right", padx=(0, int(8*s)))
        self.close_btn.bind("<Button-1>", lambda e: self.hide())
        self.close_btn.bind("<Enter>", lambda e: self.close_btn.config(fg=Theme.RED))
        self.close_btn.bind("<Leave>", lambda e: self.close_btn.config(fg=Theme.TEXT_MUTED))
        
        # 航向带容器
        self.tape_frame = tk.Frame(self.content_frame, bg=Theme.GRAYPILL)
        self.tape_frame.pack(fill="x", padx=pad, pady=(int(2*s), 0))
        
        # 航向带 - 应用导航栏宽度配置
        width_mult = PanelConfig.navigation_bar_width
        tape_width = int(ZoneConfig.HEADING_TAPE_WIDTH * s * 1.2 * width_mult)
        tape_height = int(ZoneConfig.HEADING_TAPE_HEIGHT * s)
        self.heading_tape = HeadingTape(
            self.tape_frame,
            width=tape_width,
            height=tape_height
        )
        self.heading_tape.pack(fill="x", expand=True)
        
        # 图例行 - v6.2.3: 与提示文字共用一行
        self.legend_row = tk.Frame(self.content_frame, bg=Theme.GRAYPILL)
        self.legend_row.pack(fill="x", padx=pad, pady=(int(1*s), 0))
        
        # 左侧：图例
        legend_font = (UIConfig.FONT_ZONE_ITEM[0], int(UIConfig.FONT_ZONE_ITEM[1]*s*0.85))
        legend_text = "⊚战区  ✈友方  ✈敌方  ✕摧毁"
        tk.Label(self.legend_row, text=legend_text, font=legend_font,
                fg=Theme.TEXT_MUTED, bg=Theme.GRAYPILL, anchor="w").pack(side="left")
        
        # v6.4: 角度阈值显示（图例和提示之间）
        self.zone_tolerance_legend = tk.Label(
            self.legend_row, text="", font=legend_font,
            fg=Theme.TEXT_MUTED, bg=Theme.GRAYPILL, anchor="center"
        )
        self.zone_tolerance_legend.pack(side="left", padx=(int(10*s), 0))
        
        # 右侧：提示文字
        hint_font = (UIConfig.FONT_HINT[0], int(UIConfig.FONT_HINT[1]*s*0.85))
        tk.Label(self.legend_row, text="解锁(F8)后可拖动 | 右键菜单", font=hint_font,
                fg=Theme.TEXT_MUTED, bg=Theme.GRAYPILL, anchor="e").pack(side="right")
        
        # 战区状态行
        self.zone_row = tk.Frame(self.content_frame, bg=Theme.GRAYPILL)
        self.zone_row.pack(fill="x", padx=pad, pady=(int(2*s), 0))
        
        status_font = (UIConfig.FONT_ZONE_ITEM[0], int(UIConfig.FONT_ZONE_ITEM[1]*s*0.95))
        
        # v6.2.3: 让战区提示整体居中显示（不再与容差分居两侧）
        self._zone_row_left_spacer = tk.Frame(self.zone_row, bg=Theme.GRAYPILL)
        self._zone_row_left_spacer.pack(side="left", fill="x", expand=True)
        
        self._zone_row_center = tk.Frame(self.zone_row, bg=Theme.GRAYPILL)
        self._zone_row_center.pack(side="left")
        
        self._zone_row_right_spacer = tk.Frame(self.zone_row, bg=Theme.GRAYPILL)
        self._zone_row_right_spacer.pack(side="left", fill="x", expand=True)
        
        self.zone_label = tk.Label(
            self._zone_row_center, text="⊚战区:", font=status_font,
            fg=Theme.RED, bg=Theme.GRAYPILL, anchor="w"
        )
        self.zone_label.pack(side="left")
        
        self.zone_turn = tk.Label(
            self._zone_row_center, text="", font=status_font,
            fg=Theme.TEXT_DIM, bg=Theme.GRAYPILL, anchor="w"
        )
        self.zone_turn.pack(side="left", padx=(int(6*s), 0))
        
        self.zone_status = tk.Label(
            self._zone_row_center, text="", font=status_font,
            fg=Theme.TEXT_DIM, bg=Theme.GRAYPILL, anchor="w"
        )
        self.zone_status.pack(side="left", padx=(int(8*s), 0))
        
        self.zone_info = tk.Label(
            self._zone_row_center, text="", font=status_font,
            fg=Theme.TEXT_DIM, bg=Theme.GRAYPILL, anchor="w"
        )
        self.zone_info.pack(side="left", padx=(int(8*s), 0))
        
        # v6.4: 容差已移至图例行，保留变量引用
        self.zone_tolerance = tk.Label(
            self._zone_row_center, text="", font=status_font,
            fg=Theme.TEXT_MUTED, bg=Theme.GRAYPILL, anchor="w"
        )
        # 不再pack，让状态行布局更居中
        
        # 友方机场状态行
        self.friendly_row = tk.Frame(self.content_frame, bg=Theme.GRAYPILL)
        self.friendly_row.pack(fill="x", padx=pad, pady=(int(1*s), 0))
        
        # v6.2.3: 友方提示同样居中，视觉更一致
        self._friendly_row_left_spacer = tk.Frame(self.friendly_row, bg=Theme.GRAYPILL)
        self._friendly_row_left_spacer.pack(side="left", fill="x", expand=True)
        
        self._friendly_row_center = tk.Frame(self.friendly_row, bg=Theme.GRAYPILL)
        self._friendly_row_center.pack(side="left")
        
        self._friendly_row_right_spacer = tk.Frame(self.friendly_row, bg=Theme.GRAYPILL)
        self._friendly_row_right_spacer.pack(side="left", fill="x", expand=True)
        
        self.friendly_label = tk.Label(
            self._friendly_row_center, text="✈友方:", font=status_font,
            fg=Theme.BLUE, bg=Theme.GRAYPILL, anchor="w"
        )
        self.friendly_label.pack(side="left")
        
        self.friendly_turn = tk.Label(
            self._friendly_row_center, text="", font=status_font,
            fg=Theme.TEXT_DIM, bg=Theme.GRAYPILL, anchor="w"
        )
        self.friendly_turn.pack(side="left", padx=(int(6*s), 0))
        
        self.friendly_status = tk.Label(
            self._friendly_row_center, text="", font=status_font,
            fg=Theme.TEXT_DIM, bg=Theme.GRAYPILL, anchor="w"
        )
        self.friendly_status.pack(side="left", padx=(int(8*s), 0))
        
        self.friendly_info = tk.Label(
            self._friendly_row_center, text="", font=status_font,
            fg=Theme.TEXT_DIM, bg=Theme.GRAYPILL, anchor="w"
        )
        self.friendly_info.pack(side="left", padx=(int(8*s), 0))
        

    
    def _init_bindings(self):
        """初始化事件绑定"""
        # 标题栏拖动
        for widget in [self.title_bar, self.title_lbl]:
            widget.bind("<Button-1>", self._on_drag_start)
            widget.bind("<B1-Motion>", self._on_drag_motion)
        
        # 右键菜单
        self.window.bind("<Button-3>", self._show_context_menu)
        
        # 窗口关闭事件（点X或Alt+F4）
        self.window.protocol("WM_DELETE_WINDOW", self.hide)
    
    def _on_drag_start(self, event):
        """开始拖动（仅在主窗口解锁时允许）"""
        if self.app._locked:
            return
        self._drag_data["x"] = event.x
        self._drag_data["y"] = event.y
    
    def _on_drag_motion(self, event):
        """拖动中（仅在主窗口解锁时允许）"""
        if self.app._locked:
            return
        x = self.window.winfo_x() + (event.x - self._drag_data["x"])
        y = self.window.winfo_y() + (event.y - self._drag_data["y"])
        self.window.geometry(f"+{x}+{y}")
        # 保存位置
        PanelConfig.navigation_window_pos = (x, y)
    
    def _show_context_menu(self, event):
        """显示右键菜单"""
        menu = tk.Menu(self.window, tearoff=0)
        menu.add_command(label="🔄 切换到集成模式", command=self._switch_to_integrated)
        menu.add_separator()
        menu.add_command(label="📍 重置位置", command=self._reset_position)
        
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
    
    def _switch_to_integrated(self):
        """切换到集成模式"""
        PanelConfig.navigation_mode = "integrated"
        self.hide()
        self.app._save_config()
        self.app._refresh_tray()
        # 强制触发UI刷新，确保投弹预测等面板正确显示
        self.app.root.after(50, self.app._recalc_size)
    
    def _reset_position(self):
        """重置窗口位置到屏幕中央"""
        sw, sh = Win32.screen_size()
        w = self.window.winfo_width()
        h = self.window.winfo_height()
        x = (sw - w) // 2
        y = 50  # 靠近顶部
        self.window.geometry(f"+{x}+{y}")
        PanelConfig.navigation_window_pos = (x, y)
    
    def _restore_position(self):
        """恢复保存的窗口位置"""
        if PanelConfig.navigation_window_pos:
            x, y = PanelConfig.navigation_window_pos
            # 确保在屏幕范围内
            sw, sh = Win32.screen_size()
            x = max(0, min(x, sw - 100))
            y = max(0, min(y, sh - 50))
            self.window.geometry(f"+{x}+{y}")
        else:
            self._reset_position()
    
    def show(self):
        """显示窗口"""
        if not self._visible:
            self._visible = True
            self.window.deiconify()
            self.window.lift()
    
    def hide(self):
        """隐藏窗口"""
        if self._visible:
            self._visible = False
            self.window.withdraw()
    
    def is_visible(self):
        """返回窗口是否可见"""
        return self._visible
    
    def update_display(self, snap: 'UISnapshot', targets: list, targets_info: list, primary_zone):
        """更新导航显示
        
        v6.5: 重构 - 使用工具函数复用导航逻辑
        
        Args:
            snap: UI快照
            targets: 航向带目标列表
            targets_info: 目标信息列表
            primary_zone: 主目标战区
        """
        if not self._visible:
            return
        
        # 更新航向
        if snap.player_heading > 0:
            self.heading_lbl.config(text=f"HDG: {int(snap.player_heading):03d}°")
        else:
            self.heading_lbl.config(text="HDG: ---")
        
        # 更新航向带 - v6.2.3: 即使没有目标也保持显示
        if snap.player_heading > 0:
            if targets:
                primary_dist = primary_zone.distance_km if primary_zone else 10.0
                self.heading_tape.update_tape_multi(snap.player_heading, targets, primary_dist)
            else:
                # 没有目标时显示空白航向带（保持常驻）
                self.heading_tape.update_tape_multi(snap.player_heading, [], 10.0)
        else:
            self.heading_tape.clear()
        
        # 更新战区状态
        zone_info = next((t for t in targets_info if t['type'] == 'zone'), None)
        if primary_zone:
            tolerance = get_cdi_tolerance(primary_zone.distance_km)
            scale = calculate_heading_tape_scale(primary_zone.distance_km)
            rel = primary_zone.relative
            abs_rel = abs(rel)
            
            # v6.5: 使用工具函数计算转向指示和状态
            turn_text, turn_color = calculate_zone_turn_indicator(rel, tolerance)
            dev_text, dev_color = calculate_zone_status(abs_rel, tolerance)
            
            # 距离和ETE
            ete_str = zone_info.get('ete_str') if zone_info else None
            info_text = format_distance_ete(primary_zone.distance_km, ete_str)
            
            # v6.4: 容差移至图例行
            tol_text = f"±{tolerance:.1f}° {scale:.1f}x"
            
            self.zone_turn.config(text=turn_text, fg=turn_color)
            self.zone_status.config(text=dev_text, fg=dev_color)
            if hasattr(self, 'zone_info'):
                self.zone_info.config(text=info_text, fg=Theme.RED)
            # 更新图例行的容差显示
            if hasattr(self, 'zone_tolerance_legend') and self.zone_tolerance_legend:
                self.zone_tolerance_legend.config(text=tol_text)
            self.zone_tolerance.config(text="")
            self.zone_row.pack(fill="x", padx=int(6*self.scale), pady=(int(2*self.scale), 0))
        else:
            self.zone_row.pack_forget()
        
        # 更新友方机场状态
        friendly_info = next((t for t in targets_info if t['type'] == 'friendly'), None)
        if friendly_info:
            rel = friendly_info['relative']
            abs_rel = abs(rel)
            dist = friendly_info['distance_km']
            
            # v6.5: 使用工具函数计算转向指示和状态
            turn_text, turn_color = calculate_airfield_turn_indicator(rel)
            status_text, status_color = calculate_airfield_status(abs_rel)
            
            # 距离和ETE
            info_text = format_distance_ete(dist, friendly_info.get('ete_str'))
            
            self.friendly_turn.config(text=turn_text, fg=turn_color)
            if hasattr(self, 'friendly_status'):
                self.friendly_status.config(text=status_text, fg=status_color)
            self.friendly_info.config(text=info_text, fg=Theme.BLUE)
            self.friendly_row.pack(fill="x", padx=int(6*self.scale), pady=(int(1*self.scale), int(6*self.scale)))
        else:
            self.friendly_row.pack_forget()

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

