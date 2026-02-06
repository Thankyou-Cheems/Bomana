# Bomana 🍌

**战雷全真模式收益计时器** | War Thunder SB Timer

A powerful War Thunder timer made for the "Space Monkeys" who love dropping bombs and eating bananas

<p align="center">
  <img src="app.png" width="320" alt="Bomana promotional art">
</p>

[![Version](https://img.shields.io/badge/version-6.7.0-blue.svg)](https://github.com/Thankyou-Cheems/Bomana/releases)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.8+-yellow.svg)](https://www.python.org/)
[![DAU](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fbomanaupdate.ruikang.wang%2Fapi%2Fv1%2Fstats%2Fdaily&query=%24.metrics.dau_unique_device&label=DAU&color=brightgreen)](https://bomanaupdate.ruikang.wang/api/v1/stats/daily)
[![Launches](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fbomanaupdate.ruikang.wang%2Fapi%2Fv1%2Fstats%2Fdaily&query=%24.metrics.launcher_start_total&label=Launches&color=blue)](https://bomanaupdate.ruikang.wang/api/v1/stats/daily)

---

## ⚠️ 重要：合规性声明 | Compliance Statement
> ⚠️ 本合规性声明存在前发布的版本已经移除，下载新版默认为同意此声明 ⚠️
### 官方立场引用 | Official Statement Reference

根据 War Thunder 论坛中社区经理 **Stona_WT** 于 2024年5月13日的[官方回复](https://forum.warthunder.com/t/tools-using-data-provided-on-port-8111/106664/16)：

> Generally speaking, using localhost data to display overlays is considered fine and not a bannable offense. However, displaying enemy markers in a markerless mode incorporated into a compass-heading-style UI overlay, which our map tool doesn't do, gives advantage over others players. This is clearly demonstrated in the video — this is where there's a fine line as it can be considered an ESP overlay. While we won't permanently suspend any account without a preceding temporary ban or a warning, we do not approve using this data in such way even if it is publicly available.

**中文译文：**

> 一般来说，使用 localhost 数据来显示覆盖层是被允许的，不会导致封禁。但是，在无标记模式下以罗盘样式的 UI 覆盖层显示敌人标记——而我们官方的地图工具不会这样做——会让用户相对其他玩家获得优势。这是有明确案例可以证明的——这就是可能被视为 ESP 覆盖层的临界点。虽然我们不会在没有事先临时封禁或警告的情况下永久封禁任何账户，但即使这些数据是公开可用的，**我们也不认可以这种方式使用它**。

### 合规边界辨析 | Compliance Analysis

| 使用方式 | 官方态度 | 说明 |
|---------|---------|------|
| ✅ 显示本机飞行数据（速度、高度、燃油等） | **允许** | 类似 WTRTI 等工具，获官方认可 |
| ✅ 使用 8111 端口数据作为辅助参考 | **允许** | 本地数据本身是官方提供的 |
| ⚠️ 在无标记模式下显示敌人位置叠加层 | **不认可** | 可能被视为 ESP，存在封禁风险 |
| ❌ 任何获取超出 8111 端口提供信息的行为 | **禁止** | 违反用户协议 |

### Bomana 的设计原则

Bomana 严格遵循以下原则，确保合规使用：

1. **仅使用官方 8111 接口** - 所有数据来源于 War Thunder 官方提供的 `localhost:8111` API
2. **不读取游戏内存** - 不注入代码，不修改游戏文件
3. **不提供游戏内不可见的信息** - 不显示敌机位置、敌方数据等
4. **只展示玩家可见信息** - 战区、己方机场位置等地图上本就可见的信息
5. **信息辅助而非游戏干预** - 计时器基于玩家自身出生时间，不涉及服务器数据操纵

### ⚡ 关键结论 | Key Takeaway

**Bomana 作为基于 8111 端口数据的计时器工具，其核心功能（复活计时、飞行数据显示、投弹预测）属于官方认可的使用范畴。** 但用户应当：

1. **了解**即使某些功能技术上可行，也不代表官方认可其使用
2. **承担**因使用方式不当可能导致的任何后果

---

## 🎯 功能特性 | Features

### 核心功能：15分钟复活周期计时器

War Thunder 全真模式（SB）中，每次出生后有 15 分钟的收益周期。Bomana 自动追踪这一周期：

- ⏱️ **自动计时** - 检测出生、着陆、死亡事件，自动开始/重置计时
- 🔢 **复活计数** - 显示当前是第几条命
- 💾 **状态恢复** - 支持应用重启后继续计时
- 🔔 **倒计时警告** - 30秒、20秒、10秒...语音/蜂鸣提醒

### 投弹预测系统（CCRP v3.0）

基于真实弹道物理的投弹辅助计算：

- 🎯 **弹道计算** - 考虑空气阻力、大气密度、温度修正
- 💣 **多型号支持** - 内置多国炸弹参数数据库（苏联、美国、德国、英国等）
- 📐 **实时预测** - 根据当前高度、速度、俯仰角计算投弹距离和时间
- 🪂 **减速伞支持** - 支持带减速伞炸弹的特殊弹道计算

### 战区导航系统

精确引导你飞向目标：

- 🧭 **航向带（Heading Tape）** - 图形化显示目标方位
- 📍 **CDI 指示器** - 航道偏差指示，精度随距离动态调整
- 📏 **距离显示** - 到目标的距离（km）
- ⏱️ **ETE 预估** - 按当前速度到达目标的预计时间
- 🔄 **智能目标切换** - 持续对准某目标 3 秒后自动锁定

### 机场导航

- ✈️ **友方机场** - 显示返航方向和距离
- 🎯 **敌方机场** - 显示敌方机场位置（可选）

### 燃油管理

- ⛽ **油量显示** - 当前燃油量（kg）
- 📉 **油耗率** - 实时燃油消耗速率
- ⚠️ **低油量警告** - 黄色（30%）、红色（15%）警告
- 🏠 **返航估算** - 预估返回机场所需燃油

### 出击检查清单

可自定义的起飞前检查项目：

- ✅ 按 I 启动发动机
- ✅ 等待发动机转速稳定
- ✅ 收起落架
- ✅ 开增稳系统
- ✅ 设定打击目标
- ✅ ...（可自定义）

### 界面特性

| 特性 | 说明 |
|------|------|
| 🪟 透明覆盖 | 不遮挡游戏视野 |
| 📌 窗口置顶 | 始终显示在游戏上方 |
| 🔒 锁定/解锁 | 锁定后点击穿透，不影响游戏操作 |
| 🖱️ 拖动定位 | 自由拖动到任意位置 |
| 📐 边缘吸附 | 自动吸附到屏幕边缘 |
| 🖥️ 多显示器 | 支持多显示器环境 |
| 🎨 主题切换 | 暗色/亮色/高对比度 |
| ⌨️ 全局热键 | F7-F11 快捷操作 |
| 📱 系统托盘 | 最小化到托盘 |

---

## 📥 安装与使用 | Installation & Usage

### 方式一：下载预编译版本（推荐）

1. 前往 [Releases](https://github.com/Thankyou-Cheems/Bomana/releases) 页面
2. 下载通用启动器：`Bomana_launcher_vX.X.X.exe`

启动器内可选版本通道：

| 通道 | 包含功能 | 适合人群 |
|------|----------|----------|
| **Enhanced** | 计时器 + 战区/机场导航 + 燃油管理 + CCRP投弹预测 | 需要完整功能的玩家（推荐） |
| **Standard** | 计时器 + 战区/机场导航 + 燃油管理（无CCRP） | 不用投弹预测但需要导航/燃油信息 |
| **Lite** | 仅核心计时器 | 只想要极简界面和最低占用 |

3. 下载后双击运行（绿色版，无需安装）
4. 启动器打开后会自动检查当前通道版本（优先国内更新服务，必要时回退 GitHub），并在界面展示来源与下载总大小
5. 仅“下载更新”操作需要用户确认；首次运行通常需联网下载应用包，后续可离线启动本地已下载版本
6. 可用 `checksums_launcher.txt` 与 `checksums_app_*.txt` 校验文件完整性
7. 程序显示名为 `Bomana香焦`

### 方式二：从源码运行

#### 环境要求

- Python 3.8+
- Windows 操作系统

#### 安装依赖

```bash
pip install -r requirements.txt
```

> 打包绿色版（启动器+应用包）可执行：`build_portable.bat <Enhanced|Standard|Lite> <all|app|launcher> [version]`

开发者区分打包目标：

- 仅打包应用包（用于自动更新）：`build_app_package.bat Enhanced|Standard|Lite`
- 仅打包通用启动器（绿色入口）：`build_launcher.bat [version]`
- 一次性全打：`build_portable.bat Enhanced all`

GitHub 云端自动打包发布：

- 推送标签 `vX.Y.Z`：构建并发布 启动器 + 三通道应用包
- 推送标签 `vX.Y.Z-app`：仅构建并发布三通道应用包
- 推送标签 `vX.Y.Z-launcher`：仅构建并发布启动器
- `workflow_dispatch` 手动触发时也可通过 `build_target` 选择 `all` / `app` / `launcher`
- 不需要本地打包后手工上传文件


#### 运行

```bash
python Bomana.pyw
```

### 开启 War Thunder 本地服务器

**重要：** 必须在 War Thunder 中启用本地网页服务器，Bomana 才能获取数据。

```
设置 → 主要 → 在浏览器中显示战斗界面 → 启用
```

启用后，可通过 `http://localhost:8111` 访问游戏数据。

---

## ⌨️ 快捷键 | Hotkeys

| 按键 | 功能 | 说明 |
|------|------|------|
| `F7` | 重置计时器 | 手动重置15分钟周期 |
| `F8` | 锁定/解锁 | 切换窗口点击穿透状态 |
| `F9` | 切换角落 | 在四个屏幕角落间切换位置 |
| `F10` | 声音开关 | 开启/关闭提示音 |
| `F11` | 战区提示音 | 开启/关闭战区被摧毁提示 |

*快捷键可在设置中自定义*

---

## 🔧 高级配置 | Advanced Configuration

### 编译开关

编译开关在 `bomana/config.py` 中，用于打包不同功能版本：

```python
ENABLE_CCRP = True              # CCRP投弹预测功能
ENABLE_ZONES = True             # 战区导航功能
ENABLE_AIRFIELDS = True         # 机场导航功能
ENABLE_FUEL = True              # 燃油管理功能
ENABLE_CHECKLIST = True         # 出击检查清单功能
ENABLE_ADVANCED_SETTINGS = True # 高级设置（面板/快捷键自定义等）
```

### 更新 CCRP 炸弹参数（开发者）

`ccrp_bomb_params.json` 由 War Thunder datamine 中的 `.blkx` 文件生成。仓库内集成了提取脚本，流程如下：

```bash
# 1) 准备 datamine 仓库（或直接指向已解包的 .blkx 目录）
git clone https://github.com/gszabi99/War-Thunder-Datamine.git

# 2) 运行提取脚本
python tools/blkx_extractor.py ^
  .\War-Thunder-Datamine\aces.vromfs.bin_u\gamedata\weapons\bombguns ^
  -o ccrp_bomb_params.json
```

生成后的 `ccrp_bomb_params.json` 放在仓库根目录，Enhanced 版本会自动打包该文件。


---

## 🔌 技术原理 | Technical Details

### 数据来源

Bomana 通过 War Thunder 官方提供的本地 HTTP 服务器获取数据：

| 端点 | 数据内容 |
|------|---------|
| `/indicators` | 飞机仪表数据（速度、油量、有效性） |
| `/state` | 飞机状态数据（空速、垂直速度、高度等） |
| `/map_obj.json` | 地图对象（战区、机场、玩家位置） |
| `/map_info.json` | 地图元数据（格子坐标系统参数） |

### 轮询频率

- 正常状态：50ms（20Hz）
- API 断线：1.25s（降低 CPU 占用）

### 状态机

```
[等待] ──检测到玩家──→ [飞行中] ──速度<40km/h持续3秒──→ [已着陆]
   ↑                      │                              │
   │                      ↓                              │
   └───无玩家1.2秒───[死亡/返回机库]←────10秒后──────────┘
```

---

## ❓ 常见问题 | FAQ

### Q: 窗口不显示/显示异常？

1. 确认 War Thunder 已启动并进入战斗
2. 确认已启用"在浏览器中显示战斗界面"
3. 尝试访问 `http://localhost:8111` 确认服务正常
4. 按 `F9` 切换窗口位置

### Q: 计时器不自动开始？

1. 确认已出生在战场中
2. 检查 8111 端口是否可访问
3. 等待 1-2 秒让程序检测到玩家

### Q: 投弹预测不准确？

1. 确认选择了正确的炸弹型号
2. 高空投弹时注意风速影响（游戏内未提供风速数据）
3. 减速伞炸弹需要额外的展开时间

### Q: 与 WTRTI 有什么区别？

| 特性 | Bomana | WTRTI |
|------|--------|-------|
| 主要用途 | SB 模式计时+投弹 | 通用飞行数据显示 |
| 15分钟计时 | ✅ 核心功能 | ❌ |
| 投弹预测 | ✅ 内置 | ❌ |
| 战区导航 | ✅ 内置 | ❌ |
| 自定义指标 | ❌ | ✅ 高度自定义 |
| 平台 | Windows | 跨平台 |

两者可以同时使用，功能互补。

---

## 🔒 隐私与数据收集 | Privacy & Data Collection

### 📊 匿名使用数据收集

为了改进产品质量并统计真实用户活跃度（DAU），**本应用会收集匿名化的使用数据**，包括：

- **设备标识符** (device_id) - 通过SHA256单向加密生成，不可逆向追溯到个人
- **安装标识符** (install_id) - 本地随机UUID，用于区分多次安装
- **应用版本、功能通道、事件类型** - 用于统计分析和问题定位

### ✅ 我们的承诺

- ✅ **完全匿名** - 不收集任何可识别个人的信息（IP、账号、邮箱等）
- ✅ **数据最小化** - 仅收集统计必需的字段
- ✅ **透明公开** - 代码开源，数据收集逻辑可审查
- ✅ **用户可控** - 提供禁用方法（见隐私政策）
- ✅ **不用于商业** - 不出售数据，不用于广告

### 📖 详细信息

请查看完整的 **[隐私政策 (PRIVACY.md)](PRIVACY.md)**，了解：
- 收集哪些数据及其用途
- 数据安全与匿名化技术细节
- 如何禁用数据收集
- 您的权利与联系方式

**法律依据：** 通过下载并运行本应用，您同意本隐私政策。我们的数据处理符合GDPR、PIPL等国际隐私法规要求。

---

## 📜 许可证与免责声明 | License & Disclaimer

### 许可证 | License

**MIT License**

Copyright (c) 2024-2026 Cheems

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

本软件根据 MIT 许可证授权，任何人均可免费获取本软件及相关文档文件的副本，并不受限制地处理本软件，包括但不限于使用、复制、修改、合并、发布、分发、再许可和/或销售本软件的副本。

---

### 免责声明 | Disclaimer

#### 商标声明 | Trademark Notice

War Thunder® and all related trademarks, logos, and materials are the property of Gaijin Entertainment AG and its subsidiaries. This software is an independent project and is NOT affiliated with, endorsed by, or sponsored by Gaijin Entertainment AG.

《战争雷霆》®及所有相关商标、标识和素材归 Gaijin Entertainment AG 及其子公司所有。本软件为独立项目，与 Gaijin Entertainment AG 无任何关联、授权或赞助关系。

#### 使用警告 | Usage Warning

⚠️ **IMPORTANT:** Misuse or abuse of this software may violate the Gaijin Entertainment User Agreement. Users are solely responsible for ensuring their usage complies with all applicable terms of service and game rules.

⚠️ **重要提示：** 滥用或不当使用本软件可能违反 Gaijin Entertainment 用户协议。用户需自行确保其使用行为符合所有适用的服务条款和游戏规则。

#### 用户协议相关条款 | Relevant EULA Terms

根据 Gaijin Entertainment 用户协议第 6.1 条：

> **6.1.3.** 禁止安装或使用未经授权的游戏客户端修改、作弊或其他修改游戏进程和/或游戏产生的原始图像（包括修改游戏界面）以获取优势的软件或设备，除非获得 Gaijin 的明确授权。
>
> **6.1.4.** 其他违反公平竞争原则的行为。

#### 责任限制 | Liability

This software is provided "AS IS" without warranty of any kind. The author(s) shall not be held liable for any damages, account suspensions, or consequences arising from the use of this software. **Use at your own risk.**

本软件按"现状"提供，不提供任何形式的保证。作者不对因使用本软件而产生的任何损害、账号封禁或其他后果承担责任。**使用风险由用户自行承担。**

---

## 📚 参考资料 | References

- [War Thunder 官方论坛 - 关于 8111 端口工具的讨论](https://forum.warthunder.com/t/tools-using-data-provided-on-port-8111/106664)
- [Stona_WT 官方回复 (Post #16)](https://forum.warthunder.com/t/tools-using-data-provided-on-port-8111/106664/16)
- [Gaijin Entertainment 用户协议](https://legal.gaijin.net/termsofservice)
- [WTRTI - 另一款官方认可的 8111 端口工具](https://mesofthorny.github.io/WTRTI/)
- [War Thunder localhost:8111 API 文档](https://github.com/lucasvmx/WarThunder-localhost-documentation)

---

## 🙏 赞助支持 | Sponsor

如果 Bomana 对你有帮助，欢迎通过微信赞助支持开发！

<img src="sponsor_wechat.png" width="200" alt="微信赞赏二维码">

---

## 📝 更新日志 | Changelog

详见 `CHANGELOG.md`（最新版本：v6.7.0）。

---

*Made with ❤️ by 猹Cheems for the Space Monkeys community* ❤️ by 猹Cheems for the Space Monkeys community*
