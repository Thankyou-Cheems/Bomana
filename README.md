# 🍌 Bomana - 战雷全真模式收益计时器

<div align="center">

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.7+-blue.svg)](https://www.python.org/downloads/)
[![Platform](https://img.shields.io/badge/platform-Windows-lightgrey.svg)](https://github.com/Thankyou-Cheems/Bomana)
[![Version](https://img.shields.io/badge/version-5.9-green.svg)](https://github.com/Thankyou-Cheems/Bomana/releases)

**A powerful War Thunder timer made for the "Space Monkeys" who love dropping bombs and eating bananas**

[English](#english) | [中文](#中文)

</div>

---

## 中文

### 📖 项目简介

Bomana 是一个专为《战争雷霆》全真模式（Simulator Battles）设计的辅助计时工具，帮助玩家精确管理 15 分钟的复活周期。本软件仅使用官方 8111 接口获取数据，**完全合法合规**，不涉及任何作弊行为。

### ✨ 核心特性

#### 🎯 智能计时系统
- **自动状态检测**：自动识别出生、死亡、着陆状态
- **精确周期管理**：15 分钟复活周期倒计时，声音和视觉双重提醒
- **状态恢复**：应用重启后可恢复计时状态，不丢失进度
- **补给检测**：自动识别地面补给站，重置"出击检查"

#### 🗺️ 战区导航
- **实时战区定位**：显示所有战区的方位、距离和格子坐标
- **智能目标选择**：自动锁定前方最佳战区（45° 角度门内优先级最高）
- **精确对准切换**：持续对准某目标 3 秒后自动切换
- **抵达时间估算**：基于地速计算到达战区的预计时间（ETE）
- **偏航警告**：超过 ±60° 时显示偏航提示
- **战区摧毁提醒**：战区被摧毁时声音+视觉警告（持续 30 秒）

#### 🛫 机场导航
- **友方机场**：显示最近的友方机场位置和距离
- **敌方机场**：列出所有敌方机场，自动标记 45° 内的目标
- **返航 ETE**：实时显示返回友方机场的预计时间

#### ⛽ 燃油管理（v5.8 新增）
- **油量监控**：显示当前油量（kg）和百分比
- **油耗率计算**：基于 60 秒采样窗口计算平均油耗（kg/min）
- **剩余飞行时间**：估算当前油量可飞行的时间
- **返航估算**：计算返回友方机场所需油量，提供三级警告
  - ✅ **充足**：油量 > 返航需求 × 1.5
  - ⚠️ **注意**：油量在返航需求 × 1.0~1.5 之间
  - 🔴 **不足**：油量 < 返航需求
- **高度显示**：实时显示飞行高度
- **智能补给检测**：识别油量突增（补给），自动清空历史数据重新计算

#### ✅ 出击检查清单
- **自定义检查项**：最多 8 个检查项，可自由编辑
- **智能显示**：仅在着陆或"就绪"状态时显示
- **纯展示模式**：简洁的 ○ 符号标记

#### 🎨 界面特性
- **多主题支持**：暗色、亮色、高对比度三种主题
- **透明置顶窗口**：半透明、始终置顶，不遮挡游戏视野
- **多显示器支持**：自动识别显示器，智能吸附边缘
- **四角落切换**：快速切换窗口位置（F9）
- **拖动自由定位**：解锁后可拖动到任意位置
- **DPI 自适应**：支持高 DPI 显示器

#### ⚙️ 高级功能
- **全局热键**：即使游戏在前台也能操作
- **系统托盘**：最小化到托盘，右键菜单控制
- **面板开关**：可独立显示/隐藏战区、机场、燃油、检查清单面板
- **音效系统**：可自定义的提示音（基于 Windows Beep API）
- **Debug 模式**：查看详细的 API 状态和数据流

### 🚀 安装说明

#### 方法一：直接运行（开发者）

1. **安装 Python 3.7+**
   ```bash
   # 检查 Python 版本
   python --version
   ```

2. **克隆仓库**
   ```bash
   git clone https://github.com/Thankyou-Cheems/Bomana.git
   cd Bomana
   ```

3. **安装依赖**
   ```bash
   pip install -r requirements.txt
   ```

4. **运行程序**
   ```bash
   python Bomana.pyw
   # 或双击 Bomana.pyw
   ```

#### 方法二：使用打包版本（推荐）

1. 前往 [Releases 页面](https://github.com/Thankyou-Cheems/Bomana/releases)
2. 下载最新的 `Bomana-v5.9.exe`
3. 双击运行即可（无需安装 Python）

### 📦 打包说明

如果你想自己打包成 .exe：

```bash
# 安装 PyInstaller
pip install pyinstaller

# 打包命令
pyinstaller --onefile --windowed --icon=app.ico --name=Bomana ^
  --add-data "app.png;." ^
  --add-data "sponsor_wechat.png;." ^
  Bomana.pyw
```

打包后的文件在 `dist/` 目录下。

### 🎮 使用方法

#### 初次启动

1. **启动战雷**：进入全真模式战斗
2. **运行 Bomana**：程序会自动检测 8111 接口
3. **等待出生**：程序自动识别出生状态并开始计时

#### 快捷键操作

| 快捷键 | 功能 | 说明 |
|--------|------|------|
| **F7** | 重置计时器 | 手动重置当前周期为 15 分钟 |
| **F8** | 锁定/解锁窗口 | 锁定后窗口点击穿透，解锁后可拖动 |
| **F9** | 切换角落 | 在四个屏幕角落间循环切换位置 |
| **F10** | 声音开关 | 开启/关闭所有提示音 |
| **F11** | 战区提示音 | 开启/关闭战区被摧毁的提示音 |
| **Ctrl+滚轮** | 调整透明度 | 仅在解锁状态下有效 |
| **Esc** | 退出程序 | 关闭应用 |

> 💡 **提示**：快捷键可在设置中自定义（右键托盘图标 → 设置）

#### 系统托盘菜单

右键点击托盘图标可以：
- ⚙️ 打开设置对话框
- 📊 控制各面板显示
- 🔊 调整音效设置
- 📝 编辑出击检查清单
- ℹ️ 查看关于信息

### ⚙️ 配置说明

#### 配置文件位置

所有配置保存在用户主目录：
- **配置文件**：`~/.wttimer_config.json`
- **状态文件**：`~/.wttimer_state.json`（计时状态）

#### 主要配置项

```json
{
  "alpha": 210,              // 窗口不透明度 (100-255)
  "scale": 0.85,             // UI 缩放倍数
  "theme": "dark",           // 主题 (dark/light/high_contrast)
  "global_hotkeys": true,    // 全局热键开关
  "snap_enabled": true,      // 窗口吸附开关
  "snap_distance": 20,       // 吸附距离（像素）
  "beep_enabled": false,     // 提示音开关
  "zone_sound_enabled": true,// 战区提示音开关
  "panels": {
    "show_zones": true,      // 显示战区导航
    "show_airfields": true,  // 显示机场导航
    "show_fuel": true,       // 显示燃油管理
    "show_checklist": true   // 显示出击检查
  },
  "checklist_items": [       // 自定义检查清单
    "按I启动发动机",
    "收起落架",
    "开增稳系统"
  ]
}
```

### 🔧 高级配置

程序内部有大量可调参数（代码中的 `Config` 类），包括：

- **游戏逻辑**：复活周期、着陆判断、补给检测参数
- **战区导航**：航向容差、偏航警告角度、目标锁定参数
- **燃油管理**：采样间隔、警告阈值、返航安全系数
- **网络请求**：超时时间、轮询间隔
- **UI 样式**：字体、颜色、间距、进度条样式
- **音效设置**：频率、持续时间、警告时间点

如需修改，请直接编辑 `Bomana.pyw` 中对应的 `Config` 类。

### 📊 性能优化

程序已进行多项性能优化：

1. **Label 复用池**：避免频繁创建/销毁 UI 组件
2. **字体缓存**：预计算所有字体，避免重复计算
3. **智能刷新**：只在数据变化时重算窗口尺寸
4. **deque 采样**：燃油采样使用 O(1) 的 deque 而非 list
5. **独立线程**：网络请求在独立线程，不阻塞 UI
6. **预算管理**：限制单次 tick 的网络耗时（≤300ms）

### 🛡️ 安全说明

#### 合规性

✅ **完全合法**：仅使用官方 8111 接口（`http://127.0.0.1:8111`）  
✅ **不读取内存**：不涉及任何游戏内存修改或注入  
✅ **不提供作弊信息**：只显示玩家可见的地图信息  
✅ **信息辅助**：所有功能都是"信息展示"而非"游戏干预"

#### 官方 8111 接口说明

战雷官方提供的本地 API，用于获取：
- `/indicators`：飞机仪表数据（速度、油量等）
- `/state`：飞机状态数据（真空速、高度等）
- `/map_obj.json`：地图对象（战区、机场、玩家位置）
- `/map_info.json`：地图元数据（格子坐标系统）

这些接口是官方合法提供的，许多第三方工具（如 SteelSeries GameSense）都在使用。

### 🐛 已知问题

1. **首次启动可能需要手动调整位置**（多显示器环境）
2. **主题更改需要重启才能完全生效**（tkinter 限制）
3. **系统托盘图标在某些 Windows 10 主题下可能显示异常**

### 🤝 贡献指南

欢迎任何形式的贡献！

1. **Fork 本仓库**
2. **创建新分支**：`git checkout -b feature/your-feature`
3. **提交更改**：`git commit -m 'Add some feature'`
4. **推送到分支**：`git push origin feature/your-feature`
5. **提交 Pull Request**

#### 代码规范

- 遵循 PEP 8 规范
- 保持注释清晰（中文注释）
- 新增功能请更新文档

### 📝 待办事项

- [ ] 添加单元测试
- [ ] 支持多语言界面（英文）
- [ ] 添加数据统计功能（成功率、平均时间）
- [ ] 支持自定义音效文件
- [ ] Linux/macOS 兼容性支持
- [ ] 添加自动更新检查

### 📜 更新日志

#### v5.9 (2026-01-12)
- ✨ 新增燃油管理系统（油耗率、剩余时间、返航估算）
- 🎯 改进战区目标选择算法（角度优先于距离）
- 🔧 优化窗口吸附逻辑（多显示器支持）
- 🐛 修复底部提示文字可能被截断的问题

#### v5.7
- ✨ 新增目标锁定系统（精确对准自动切换）
- 🛫 敌方机场 ETE 仅在朝向时显示（<45°）

#### v5.6
- 🔧 战区目标选择改为飞行中且航向内才选择
- 🎨 优化 UI 渲染性能（Label 复用池）

### 💖 支持作者

如果这个工具对你有帮助，欢迎请作者喝杯咖啡~

<div align="center">
<img src="sponsor_wechat.png" width="200" alt="微信赞赏码" />
<p>微信赞赏</p>
</div>

### 📄 许可证

本项目采用 [MIT 许可证](LICENSE)。

### ⚠️ 免责声明

**商标声明**  
War Thunder® 及所有相关商标、标识和素材归 Gaijin Entertainment AG 及其子公司所有。本软件为独立项目，与 Gaijin Entertainment AG 无任何关联、授权或赞助关系。

**使用警告**  
⚠️ 滥用或不当使用本软件可能违反 Gaijin Entertainment 用户协议。用户需自行确保其使用行为符合所有适用的服务条款和游戏规则。

**责任限制**  
本软件按"现状"提供，不提供任何形式的保证。作者不对因使用本软件而产生的任何损害、账号封禁或其他后果承担责任。使用风险由用户自行承担。

---

## English

### 📖 About

Bomana is an auxiliary timer tool designed for War Thunder Simulator Battles, helping players accurately manage the 15-minute respawn cycle. This software **only uses the official 8111 API** and is completely legal and compliant, without any cheating behavior.

### ✨ Key Features

#### 🎯 Smart Timer System
- **Auto State Detection**: Automatically recognizes spawn, death, and landing states
- **Precise Cycle Management**: 15-minute respawn countdown with audio and visual alerts
- **State Recovery**: Restores timer state after app restart
- **Refuel Detection**: Auto-detects ground resupply stations

#### 🗺️ Zone Navigation
- **Real-time Zone Location**: Shows bearing, distance, and grid coordinates
- **Smart Target Selection**: Auto-locks optimal zone within 45° heading tolerance
- **Precise Aim Switching**: Auto-switches after 3 seconds of precise aim (<5°)
- **ETE Calculation**: Ground speed-based Estimated Time En-route
- **Deviation Warning**: Alert when off-heading >±60°
- **Zone Destroyed Alert**: Audio + visual warning for destroyed zones (30s duration)

#### 🛫 Airfield Navigation
- **Friendly Airfield**: Shows nearest friendly airfield position and distance
- **Enemy Airfields**: Lists all enemy airfields, marks target within 45°
- **Return ETE**: Real-time estimated time to friendly airfield

#### ⛽ Fuel Management (v5.8)
- **Fuel Monitoring**: Current fuel (kg) and percentage
- **Consumption Rate**: Average fuel consumption (kg/min) based on 60s sampling
- **Remaining Flight Time**: Estimated flight time with current fuel
- **Return Fuel Estimation**: Three-level warnings
  - ✅ **Safe**: Fuel > Return needed × 1.5
  - ⚠️ **Warning**: Fuel between Return needed × 1.0~1.5
  - 🔴 **Danger**: Fuel < Return needed
- **Altitude Display**: Real-time flight altitude
- **Smart Refuel Detection**: Detects fuel jump, resets history data

#### ✅ Takeoff Checklist
- **Customizable Items**: Up to 8 checklist items, freely editable
- **Smart Display**: Only shows when landed or "Ready"
- **Pure Display Mode**: Simple ○ symbol markers

#### 🎨 UI Features
- **Multi-theme Support**: Dark, Light, High Contrast
- **Transparent Overlay**: Semi-transparent, always on top
- **Multi-monitor Support**: Auto-detects monitors, smart edge snapping
- **Corner Switching**: Quick position switch (F9)
- **Free Dragging**: Drag to any position when unlocked
- **DPI Adaptive**: Supports high DPI displays

#### ⚙️ Advanced Features
- **Global Hotkeys**: Operable even when game is foreground
- **System Tray**: Minimize to tray, right-click menu control
- **Panel Toggles**: Show/hide zones, airfields, fuel, checklist independently
- **Sound System**: Customizable alerts (Windows Beep API)
- **Debug Mode**: View detailed API status and data flow

### 🚀 Installation

#### Method 1: Direct Run (Developers)

1. **Install Python 3.7+**
   ```bash
   python --version
   ```

2. **Clone Repository**
   ```bash
   git clone https://github.com/Thankyou-Cheems/Bomana.git
   cd Bomana
   ```

3. **Install Dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Run Program**
   ```bash
   python Bomana.pyw
   ```

#### Method 2: Packaged Version (Recommended)

1. Go to [Releases page](https://github.com/Thankyou-Cheems/Bomana/releases)
2. Download latest `Bomana-v5.9.exe`
3. Double-click to run (no Python installation required)

### 🎮 Usage

#### Hotkeys

| Key | Function | Description |
|-----|----------|-------------|
| **F7** | Reset Timer | Manually reset current cycle to 15 min |
| **F8** | Lock/Unlock | Lock = click-through, Unlock = draggable |
| **F9** | Switch Corner | Cycle through 4 screen corners |
| **F10** | Sound Toggle | Enable/disable all sounds |
| **F11** | Zone Sound | Enable/disable zone destroyed sound |
| **Ctrl+Wheel** | Adjust Alpha | Only when unlocked |
| **Esc** | Exit | Close application |

> 💡 **Tip**: Hotkeys can be customized in Settings (right-click tray icon → Settings)

### 🛡️ Safety & Compliance

✅ **Fully Legal**: Uses only official 8111 API (`http://127.0.0.1:8111`)  
✅ **No Memory Access**: No game memory modification or injection  
✅ **No Cheating Info**: Only displays map info visible to player  
✅ **Information Aid**: All features are "information display", not "game intervention"

### 📜 License

This project is licensed under the [MIT License](LICENSE).

### ⚠️ Disclaimer

**Trademark Notice**  
War Thunder® and all related trademarks, logos, and materials are the property of Gaijin Entertainment AG and its subsidiaries. This software is an independent project and is NOT affiliated with, endorsed by, or sponsored by Gaijin Entertainment AG.

**Usage Warning**  
⚠️ Misuse or abuse of this software may violate the Gaijin Entertainment User Agreement. Users are solely responsible for ensuring their usage complies with all applicable terms of service and game rules.

**Liability**  
This software is provided "AS IS" without warranty of any kind. The author(s) shall not be held liable for any damages, account suspensions, or consequences arising from the use of this software. Use at your own risk.

---

<div align="center">

**Made with ❤️ by [猹Cheems](https://github.com/Thankyou-Cheems)**

⭐ 如果这个项目对你有帮助，请给个 Star！  
⭐ If this project helps you, please give it a Star!

</div>

