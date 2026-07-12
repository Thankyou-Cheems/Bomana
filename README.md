# Bomana

**战雷全真模式收益计时器** | War Thunder SB Timer

War Thunder 是一款载具对战电子游戏；Bomana 是一个面向 War Thunder 全真模式的多功能计时器。
本文档中的“炸弹”“投弹”“CCRP”等词均指代游戏内的虚拟概念，不对应任何现实内容。祝你玩得开心！

War Thunder is a vehicle-combat video game; Bomana is a multifunction timer for War Thunder simulator battles.
In this README, terms like "bomb", "bombing", and "CCRP" refer only to virtual in-game concepts, not anything in the real world. Have fun!

<p align="center">
  <img src="bomana/assets/branding/app.png" width="320" alt="Bomana promotional art">
</p>

[![App Release](https://img.shields.io/github/v/release/Thankyou-Cheems/Bomana?label=app%20release)](https://github.com/Thankyou-Cheems/Bomana/releases/latest)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.14%2B-yellow.svg)](https://www.python.org/)
[![DAU](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fbomanaupdate.ruikang.wang%2Fapi%2Fv1%2Fstats%2Fdaily&query=%24.metrics.dau_unique_device&label=DAU&color=brightgreen)](https://bomanaupdate.ruikang.wang/api/v1/stats/daily)
[![Launches](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fbomanaupdate.ruikang.wang%2Fapi%2Fv1%2Fstats%2Fdaily&query=%24.metrics.launcher_start_total&label=Launches&color=blue)](https://bomanaupdate.ruikang.wang/api/v1/stats/daily)

[Bomana website / 下载入口](https://thankyou-cheems.github.io/Bomana/) | [GitHub Releases](https://github.com/Thankyou-Cheems/Bomana/releases)

---

## 重要：合规性声明 | Compliance Statement
> 本合规性声明存在前发布的版本已经移除，下载新版默认为同意此声明。
### 官方立场引用 | Official Statement Reference

根据 War Thunder 论坛中社区经理 **Stona_WT** 于 2024年5月13日的[官方回复](https://forum.warthunder.com/t/tools-using-data-provided-on-port-8111/106664/16)：

> Generally speaking, using localhost data to display overlays is considered fine and not a bannable offense. However, displaying enemy markers in a markerless mode incorporated into a compass-heading-style UI overlay, which our map tool doesn't do, gives advantage over others players. This is clearly demonstrated in the video — this is where there's a fine line as it can be considered an ESP overlay. While we won't permanently suspend any account without a preceding temporary ban or a warning, we do not approve using this data in such way even if it is publicly available.

**中文译文：**

> 一般来说，使用 localhost 数据来显示覆盖层是被允许的，不会导致封禁。但是，在无标记模式下以罗盘样式的 UI 覆盖层显示敌人标记——而我们官方的地图工具不会这样做——会让用户相对其他玩家获得优势。这是有明确案例可以证明的——这就是可能被视为 ESP 覆盖层的临界点。虽然我们不会在没有事先临时封禁或警告的情况下永久封禁任何账户，但即使这些数据是公开可用的，**我们也不认可以这种方式使用它**。

### 合规边界辨析 | Compliance Analysis

| 使用方式 | 官方态度 | 说明 |
|---------|---------|------|
| 显示本机飞行数据（速度、高度、燃油等） | **允许** | 类似 WTRTI 等工具，获官方认可 |
| 使用 8111 端口数据作为辅助参考 | **允许** | 本地数据本身是官方提供的 |
| 在无标记模式下显示敌人位置叠加层 | **不认可** | 可能被视为 ESP，存在封禁风险 |
| 在独立配对网页中镜像当前 8111 战术地图敌方对象 | **未明确表态** | 不投射到游戏 HUD/罗盘，但用户仍应理解官方未明确认可此具体形式 |
| 任何获取超出 8111 端口提供信息的行为 | **禁止** | 违反用户协议 |

### Bomana 的设计原则

Bomana 严格遵循以下原则，确保合规使用：

1. **仅使用官方 8111 接口** - 所有数据来源于 War Thunder 官方提供的 `localhost:8111` API
2. **不读取游戏内存** - 不注入代码，不修改游戏文件
3. **不推断或重建敌方信息** - 独立 Web 战术地图只镜像 `/map_obj.json` 当前样本明确返回的敌方单位，下一原始样本失败或不再返回时立即移除
4. **只展示官方当前返回的信息** - 不从历史位置推算轨迹、补齐缺失目标或读取其它来源
5. **信息辅助而非游戏干预** - 计时器基于玩家自身出生时间，不涉及服务器数据操纵
6. **HUD 叠加层仅用于目标导航参考** - 敌方单位仅进入独立 Web 战术地图，不进入桌面 HUD 或航向带

### 关键结论 | Key Takeaway

**Bomana 作为基于 8111 端口数据的计时器工具，其核心功能（复活计时、飞行数据显示、武器解算、超速提醒）属于官方认可的使用范畴。** 但用户应当：

1. **了解**即使某些功能技术上可行，也不代表官方认可其使用
2. **承担**因使用方式不当可能导致的任何后果

---

## 功能特性 | Features

### 核心功能：15分钟复活周期计时器

War Thunder 全真模式（SB）中，每次出生后有 15 分钟的收益周期。Bomana 自动追踪这一周期：

- **自动计时** - 检测出生、着陆、死亡事件，自动开始/重置计时
- **复活计数** - 显示当前是第几条命
- **状态恢复** - 支持应用重启后继续计时
- **倒计时警告** - 30秒、20秒、10秒...语音/蜂鸣提醒

### 武器解算（CCRP + 空地/空空估算）

在原有 CCRP 卡片中提供紧凑的投放距离与窗口提示：

- **自由落体/高阻炸弹** - 继续使用 CCRP 弹道计算，考虑空气阻力、大气密度与减速构型
- **空地导弹与制导/滑翔炸弹** - 按当前高度、速度和前方 POI/战区给出距离、飞行时间与对准提示；官方条件表始终优先，无表滑翔武器可选择是否使用推测替代
- **空空导弹** - 按 Datamine 高度、载机速度与迎尾条件表显示二维参考，只使用 8111 当前返回的可见敌机，不声称雷达锁定、NEZ 或发射授权
- **Datamine 武器目录** - 从 War Thunder Datamine 生成物理参数、中文名称与机型挂载关系，选择器按当前机型过滤
- **明确手选** - 当前 8111 实测只有武器按键/投放脉冲，没有可靠的所选挂载字段，因此不做自动猜测

重要说明：

- **解算均为估计值** - 当前算法基于 Datamine 参数与独立物理模型，不是 War Thunder 的游戏内真实算法。
- **模型来源可见** - 卡片会用简短标签区分官方包线、推测替代或无替代模型；推测滑翔结果始终是黄色参考。
- **复杂模型会停用** - 没有可用条件表时，尚未建模的条件点火、变推力或离散质量变化仍显示“数据不足”。
- **存在误差** - 地图、飞行状态、环境因素和游戏内部实现差异都会带来偏差。
- **CCRP 可手动校准** - 自由落体路径可在 `设置 -> 投弹` 中调整 `距离修正倍率` 与 `时间修正倍率`。

### 战区导航系统

精确引导你飞向目标：

- **航向带（Heading Tape）** - 图形化显示目标方位
- **CDI 指示器** - 航道偏差指示，精度随距离动态调整
- **距离显示** - 到目标的距离（km）
- **ETE 预估** - 按当前速度到达目标的预计时间
- **智能目标切换** - 持续对准某目标 3 秒后自动锁定
- **POI 四角标记** - 使用与游戏一致的红色开放四角形状
- **Trace back** - 同一战局复活后显示上次确认损失位置的方位与距离

### HUD 导航叠加层

- **主目标靶子** - 基于相对方位与距离显示 HUD 目标提示
- **2.5D/2D 自动降级** - 姿态可靠时用 2.5D，缺失或抖动时自动回退 2D
- **顶部简化罗盘条** - 显示航向与目标方位偏移
- **抖动与断连守护** - 8111 短时抖动保持最后有效目标，断连进入待机提示
- **HUD 设置与持久化** - 支持开关、透明度、缩放、平滑、显示器策略、配色与罗盘开关

### 机场导航

- **友方机场** - 显示返航方向和距离
- **敌方机场** - 显示敌方机场位置（可选）

### 燃油管理

- **油量显示** - 当前燃油量（kg）
- **油耗率** - 实时燃油消耗速率
- **低油量警告** - 黄色（30%）、红色（15%）警告
- **返航估算** - 预估返回机场所需燃油

### 超速提醒（IAS/Mach 双通道）

- **机型匹配** - 基于 `/indicators.type` 映射到 flight model（FM）
- **双指标判定** - 同时考虑 IAS 限速与 Mach 限速
- **分级告警** - `safe / caution / warning / critical`
- **提示方式** - 紧凑速度条 + 节奏化告警音（warning/critical）
- **静态限速库来源** - 从 War Thunder datamine 的 `aces.vromfs.bin_u/gamedata/flightmodels/` 提取生成，产物为 `bomana/data/fm_speed_limits.json`
- **参考实现** - 数据提取字段与分级阈值会对照 [KaerMorh/WTSpeeder](https://github.com/KaerMorh/WTSpeeder) 交叉核验；`Bomana` 仍独立生成并维护自己的 `fm_speed_limits.json`

### 出击检查清单

可自定义的起飞前检查项目：

- 按 I 启动发动机
- 等待发动机转速稳定
- 收起落架
- 开增稳系统
- 设定打击目标
- ...（可自定义）

### 界面特性

| 特性 | 说明 |
|------|------|
| 透明覆盖 | 不遮挡游戏视野 |
| 窗口置顶 | 始终显示在游戏上方 |
| 锁定/解锁 | 锁定后点击穿透，不影响游戏操作 |
| 拖动定位 | 自由拖动到任意位置 |
| 边缘吸附 | 自动吸附到屏幕边缘 |
| 多显示器 | 支持多显示器环境 |
| 主题切换 | 暗色/亮色/高对比度 |
| 全局热键 | F7-F11 可自定义快捷操作 |
| 系统托盘 | 最小化到托盘 |

补充说明：

- **独立文字缩放** - 可单独调大字体而不放大整个窗口布局
- **自定义提示音** - 可按“计时/导航/空速”分类导入本地音频文件
- **历史速度模式** - 可切换为仅保留速度提醒的极简飞行界面

### 网页驾驶舱（本机与手机） | Local & Mobile Web Cockpit

- **App / 托盘直达** - 主窗口直接显示配对码、监听地址与实体控制，也可从托盘打开本机页面
- **移动端地图优先** - 响应式地图以官方 8111 地图缩略图为半透明底图，叠加己机、战区、机场、POI、Trace back 与当前武器射程
- **一页关键信息** - 同步计时、速度/高度/航向、燃油、导航、武器/投弹参考、检查清单与告警
- **实体化控制** - 页面可重置计时、切换角落、设定锁定/提示音/面板显示，并在可用通道中选择武器与弹道模型；不模拟 F7-F11 按键
- **分级授权** - 本机会话可控制；开启 LAN 会同时允许后来配对的局域网会话控制固定功能，关闭 LAN 会立即撤销全部 LAN 会话
- **多网卡共享** - 默认仅本机可用；显式允许本次运行的 LAN 后，会同时监听可绑定的 Wi-Fi/以太网/EasyTier 等私网地址
- **通道一致** - Enhanced、Standard、Lite 都包含网页驾驶舱，页面卡片随当前通道功能自动调整

The Web Cockpit combines a filtered dashboard with a small allowlist of Bomana semantic controls. It runs independently from port 8111 and never synthesizes keys. Enabling LAN also grants fixed-function control to later LAN pairings; disabling LAN immediately invalidates every LAN session.

---

## 安装与使用 | Installation & Usage

### 运行前提

- Bomana 通过 `http://localhost:8111` 读取战斗数据。
- 无需额外“开启本地服务器”开关；通常只需启动 War Thunder 并进入战斗。
- 启动器默认让网页驾驶舱随 App 启动，也可关闭或选择启动成功后自动打开本机页面；手机访问与控制可在 App 主窗口或托盘中为本次运行单独开启。

### 安装路径选择

- 启动器路径（推荐普通用户）：下载 `Bomana_launcher_vX.X.X.exe`，由启动器自动检查更新并按通道下载对应 app 包；新版会保留一个上一版本供回退。App 8.0.0+ 需要 Launcher 3.0.0+。
- uv 直运行路径（适合开发者/已有 Python 环境）：如果本机已经有 uv 环境，可直接同步依赖，并用显式开发标记启动源码，无需下载启动器。

### 方式一：下载预编译版本（推荐）

1. 前往 [Releases](https://github.com/Thankyou-Cheems/Bomana/releases) 页面
2. 下载通用启动器：`Bomana_launcher_vX.X.X.exe`

启动器内可选版本通道：

| 通道 | 包含功能 | 适合人群 |
|------|----------|----------|
| **Enhanced** | 计时器 + 战区/机场导航 + 燃油管理 + 武器解算 | 需要完整功能的玩家（推荐） |
| **Standard** | 计时器 + 战区/机场导航 + 燃油管理（无武器解算） | 不用武器解算但需要导航/燃油信息 |
| **Lite** | 仅核心计时器 | 只想要极简界面和最低占用 |

启动器与 app 包的关系：

- `Bomana_launcher_vX.Y.Z.exe`：固定入口，负责版本检查、下载/校验 app 包、启动器自更新、离线启动本地版本，并保留一个可回退的上一版应用目录。
- `launcher_manifest.json`：记录启动器版本、启动器文件名、SHA256 和 Ed25519 发布签名等元数据。
- `Bomana_app_<Variant>_vX.Y.Z.zip`：实际运行程序包（Enhanced / Standard / Lite），已内置零安装的最小原生热键 Broker。
- `manifest_<Variant>.json`：记录版本、应用包文件名、SHA256、`min_launcher_version` 和 Ed25519 发布签名等元数据。

3. 下载后双击运行（绿色版，无需安装）
4. 启动器打开后会后台自动检查当前通道版本与启动器版本（优先腾讯云/EdgeOne 更新服务，必要时回退 GitHub），并在界面展示来源与下载总大小
5. 检查进行中仍可切换通道、下载来源和代理设置；当前检查结束后会自动按新条件重查
6. 可配置“随 App 启动本机 Web 服务”、“启动成功后自动打开本机页面”和“启动时开启局域网访问与控制”；启动器只保存这三个布尔偏好，不保存地址、端口、配对或会话
7. Launcher 3.0.0 会拒绝启动、导入、安装、回退或恢复版本格式无效或低于 8.0.0 的 App；App 8.0.0 也会在运行时初始化前拒绝缺失、无效或低于 3.0.0 的启动器身份
8. 点击“下载更新”后，启动器会先验证发布清单签名，再校验 app 包及包内精确版本，最后原子替换本地 `app/` 目录，同时把旧版保留到 `app_previous/`
9. 如新版本有问题，可直接通过启动器“回退 vX.Y.Z”按钮把当前版和上一版互换
10. 仅“下载更新”操作需要用户确认；首次运行通常需联网下载应用包，后续可离线启动本地已下载版本
11. 可用 `checksums_launcher.txt` 与 `checksums_app_*.txt` 校验文件完整性
12. 程序显示名为 `Bomana香焦`

### 方式二：从源码运行

#### 环境要求

- Python 3.14+（仓库通过 `.python-version` 默认 pin 到 3.14.5）
- uv（Python 包管理器）
- Windows 操作系统

#### 安装依赖

```bash
# 首次使用请先安装 uv: https://docs.astral.sh/uv/getting-started/installation/
uv sync --python 3.14.5
```

> 打包绿色版（启动器+应用包）可执行：`tools\scripts\build_portable.bat <Enhanced|Standard|Lite> <all|app|launcher> [version]`。`version` 是一致性校验值，必须匹配源码版本；`all` 同时包含 app 和 launcher，通常应省略单一 `version`。

开发者区分打包目标：

- 仅打包应用包（用于自动更新）：`tools\scripts\build_app_package.bat Enhanced|Standard|Lite`
- 仅打包通用启动器（绿色入口）：`tools\scripts\build_launcher.bat [version]`
- 一次性构建当前通道 app + 通用启动器：`tools\scripts\build_portable.bat Enhanced all`
- 若要本地 `deploy_update_assets.py --target all`，需要先为 Enhanced / Standard / Lite 三个通道各构建 app 包，并构建一次通用启动器。
- 本地发布构建同样必须先设置 `BOMANA_RELEASE_ED25519_PRIVATE_KEY`、`BOMANA_RELEASE_ED25519_PUBLIC_KEY` 和 `BOMANA_RELEASE_SIGNING_KEY_ID`（默认 `bomana-release-2026-06`）；`tools/build_portable.py` 会拒绝未签名清单和不匹配的公私钥。
- App 打包会从 `native/hotkey_broker/` 构建最小 Broker 并连同 SHA256 放入 App ZIP，不需要证书或单独安装器。

GitHub 云端自动打包发布：

- 推送标签 `vX.Y.Z`：构建并发布 启动器 + 三通道应用包
- 推送标签 `vX.Y.Z-app`：仅构建并发布三通道应用包
- 推送标签 `vX.Y.Z-launcher`：仅构建并发布启动器
- `workflow_dispatch` 手动触发时也可通过 `build_target` 选择 `all` / `app` / `launcher`
- 不需要本地打包后手工上传文件
- 发布构建必须提供 Ed25519 manifest 签名 Secrets；Actions 会用 GitHub Artifact Attestations 为最终 App/Launcher 产物记录构建来源，无需 Authenticode PFX。
- 签名字段、信任边界和腾讯云/EdgeOne 本地部署规则以 [docs/specs/release-signing.md](docs/specs/release-signing.md) 为准。
- 发布或部署更新资产前，先核对 `gh secret list --repo Thankyou-Cheems/Bomana`。GitHub Release 构建完成后，在本机用 `gh release download vX.Y.Z --dir dist` 取回产物，再运行 `uv run python tools/deploy_update_assets.py --target app|launcher|all --version X.Y.Z`；Actions 不直连腾讯云，公开端点验证必须调用 `verify_release_manifest_signature`。


#### 运行

```powershell
$env:BOMANA_SOURCE_DEVELOPMENT = "1"
uv run python Bomana.pyw
```

`BOMANA_SOURCE_DEVELOPMENT=1` 只允许明确的非冻结源码开发运行跳过启动器身份；打包 App 不接受该例外。

---

## 文档导航 | Documentation Map

- [docs/QUICKSTART.md](docs/QUICKSTART.md) - 面向玩家的快速上手说明
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) - 当前代码结构、运行数据流与构建发布链路
- [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md) - 基于 `bd` 的协作、提交流程与发布约定
- [docs/specs/](docs/specs/) - 8111、发布签名、UI 线程、配置变体和质量门禁的 canonical specs
- [docs/specs/version-compatibility.md](docs/specs/version-compatibility.md) - App 8 / Launcher 3 严格版本与交接边界
- [docs/PRIVACY.md](docs/PRIVACY.md) - 启动器匿名统计与网页驾驶舱本机/LAN 数据边界
- [docs/CHANGELOG.md](docs/CHANGELOG.md) - 版本变更记录
- [docs/PITFALLS.md](docs/PITFALLS.md) - 维护过程中的已知坑点与排障记录
- [docs/guides/8111-session-recording.md](docs/guides/8111-session-recording.md) - 录制真实 8111 对局数据用于离线回放
- [docs/guides/web-cockpit-smoke.md](docs/guides/web-cockpit-smoke.md) - 网页驾驶舱的真实浏览器、手机/LAN 与打包产物人工核对
- [tests/README.md](tests/README.md) - 测试分层、放置规则与规范映射

---

## 项目目录结构（关键路径） | Project Layout

```text
.
├─ Bomana.pyw
├─ launcher.pyw
├─ bomana/
│  ├─ config/
│  ├─ core/
│  ├─ data/
│  │  ├─ ccrp_bomb_params.json
│  │  └─ fm_speed_limits.json
│  ├─ assets/web/
│  ├─ ui/
│  ├─ web/
│  └─ utils/
├─ tools/
│  ├─ blkx_extractor.py
│  ├─ fm_speed_extractor.py
│  ├─ update_datamine_assets.py
│  └─ build_portable.py
└─ docs/
```

- `Bomana.pyw` 现在主要负责单实例、DPI、窗口创建和启动 `bomana.ui.app.App`；主要业务逻辑已拆分到 `bomana/`。
- `launcher.pyw` 是绿色版启动器，负责通道选择、更新检查、下载校验、回退与普通权限离线启动。Launcher 与 Python App 不再整体提权；仅当用户点击并确认时，App 包内固定动作的原生热键 Broker 才请求 UAC。
- 超速限速数据库文件是 `bomana/data/fm_speed_limits.json`（不是仓库根目录）。
- CCRP 炸弹参数文件是 `bomana/data/ccrp_bomb_params.json`（与限速库统一放在 `bomana/data/`）。

---

## 快捷键 | Hotkeys

| 按键 | 功能 | 说明 |
|------|------|------|
| `F7` | 重置计时器 | 需在短时间内连续按两次才会手动重置15分钟周期 |
| `F8` | 锁定/解锁 | 切换窗口点击穿透状态 |
| `F9` | 切换角落 | 在四个屏幕角落间切换位置 |
| `F10` | 声音开关 | 开启/关闭提示音 |
| `F11` | 战区提示音 | 开启/关闭战区被摧毁提示 |

*快捷键可在设置中自定义；HUD 叠加层仅可在设置中启用/关闭（默认关闭）。Bomana 默认先使用普通热键；确认游戏普通运行时不会请求 UAC。游戏为管理员、未启动或权限未知时会显示“授权管理员热键”，由用户手动批准随 App 携带的零安装 Broker。无商业证书时 UAC 会显示“未知发布者”；拒绝授权不会影响按钮、托盘、计时、导航或 8111 数据。*

---

## 高级配置 | Advanced Configuration

### 编译开关

编译开关在 `bomana/config/feature_profile.py` 中，用于打包不同功能版本：

```python
ENABLE_CCRP = True              # CCRP投弹预测功能
ENABLE_ZONES = True             # 战区导航功能
ENABLE_AIRFIELDS = True         # 机场导航功能
ENABLE_FUEL = True              # 燃油管理功能
ENABLE_CHECKLIST = True         # 出击检查清单功能
ENABLE_ADVANCED_SETTINGS = True # 高级设置（面板/快捷键自定义等）
```

### 更新 datamine 静态数据（开发者）

炸弹参数、武器/挂载目录与机型超速限速库都来自同一份干净的 War Thunder datamine checkout。维护者优先使用统一更新入口，它会同时刷新：

- `bomana/data/ccrp_bomb_params.json`
- `bomana/data/weapon_fire_control.json`
- `bomana/data/fm_speed_limits.json`
- JSON `meta` 中的 datamine `source_version` / `source_commit`

```bash
# 1) 准备或更新 datamine 仓库
git clone https://github.com/gszabi99/War-Thunder-Datamine.git
git -C .\War-Thunder-Datamine pull --ff-only

# 2) 一次性刷新三份数据；默认输出适合提交前快速审阅
uv run python tools/update_datamine_assets.py ^
  .\War-Thunder-Datamine ^
  --no-bomb-report
```

仅调试单项提取时，也可以直接调用底层脚本：

```bash
uv run python tools/blkx_extractor.py ^
  --datamine-root .\War-Thunder-Datamine ^
  -o bomana\data\ccrp_bomb_params.json

uv run python tools/fm_speed_extractor.py ^
  .\War-Thunder-Datamine ^
  -o bomana\data\fm_speed_limits.json

uv run python tools/weapon_fire_control_extractor.py ^
  .\War-Thunder-Datamine ^
  --output bomana\data\weapon_fire_control.json
```

`Bomana` 运行时读取生成后的静态 JSON：炸弹库供 CCRP 使用，武器目录供挂载筛选和导弹/制导武器估算，限速库按 `/indicators.type -> unit_to_fm -> fm_speed_limits` 结合 `/state` IAS/Mach 数据做超速分级提醒。


---

## 技术原理 | Technical Details

### 数据来源

Bomana 通过 War Thunder 官方提供的本地 HTTP 服务器获取数据：

| 端点 | 数据内容 |
|------|---------|
| `/indicators` | 飞机仪表数据（速度、油量、有效性） |
| `/state` | 飞机状态数据（空速、垂直速度、高度等） |
| `/map_obj.json` | 地图对象（战区、机场、玩家位置） |
| `/map_info.json` | 地图元数据（格子坐标系统参数） |
| `/map.img` | 官方战术地图缩略图（仅 App 低频、有界读取） |

### 静态数据文件来源

除 8111 实时端点外，Bomana 还会随对应功能通道携带以下静态数据文件：

| 数据文件 | 原始来源 | 生成脚本 | 运行时用途 |
|------|------|------|------|
| `bomana/data/ccrp_bomb_params.json` | War Thunder datamine: `aces.vromfs.bin_u/gamedata/weapons/bombguns/*.blkx` | `tools/update_datamine_assets.py` -> `tools/blkx_extractor.py` | `BombConfig` 读取炸弹质量、口径、阻力、减速伞参数，用于 CCRP 弹道估算 |
| `bomana/data/weapon_fire_control.json` | War Thunder datamine: 武器、挂载容器、机型预设与 `units_weaponry.csv` | `tools/update_datamine_assets.py` -> `tools/weapon_fire_control_extractor.py` | `WeaponCatalog` 读取分类、物理参数、本地化与机型兼容关系，供手选和保守武器窗口估算 |
| `bomana/data/fm_speed_limits.json` | War Thunder datamine: `aces.vromfs.bin_u/gamedata/flightmodels/**` | `tools/update_datamine_assets.py` -> `tools/fm_speed_extractor.py` | `OverspeedAnalyzer` 按 `/indicators.type -> unit_to_fm -> fm_speed_limits` 做 IAS/Mach 超速分级 |

### 轮询频率

- 正常状态：50ms（20Hz）
- API 断线：1.25s（降低 CPU 占用）

### 网页驾驶舱数据流

Bomana 仍是唯一的 8111 读取方。App 向独立 HTTP 服务发布筛选后的 `UISnapshot`、有界地图图片内存快照和 Tk 主线程拥有的控制状态；网页不会请求或代理任何 8111 路由。Web 战术地图会镜像原始 `/map_obj.json` 当前样本中的敌方飞机、地面、海上及未知类型单位，但不发布原始响应、不保留或推算历史位置，也不把敌方单位投射到桌面 HUD/航向带。每次成功配对都会创建独立会话，写入还需要控制权限、同源 `Origin`、会话 CSRF 和幂等键；HTTP 只返回“已排队”，最终成功或拒绝由页面轮询控制状态获得。所有动作都会回到 Tk 主线程再次检查授权、`ENABLE_*` 与目标有效性，只能执行固定的 Bomana 语义功能，不能模拟按键、调用任意回调或扩展热键 Broker。服务默认监听 `127.0.0.1:8777`，端口被占用时在有限范围内回退；App 可为本次运行同时绑定所有可用的精确 RFC1918 地址而不使用 `0.0.0.0`。页面资源全部随应用打包，不依赖 CDN、远程字体或分析脚本。完整边界见 [Web Dashboard Spec](docs/specs/web-dashboard.md)。

### 状态机

```
[等待] ──检测到玩家──→ [飞行中] ──速度<40km/h持续3秒──→ [已着陆]
   ↑                      │                              │
   │                      ↓                              │
   └───无玩家1.2秒───[死亡/返回机库]←────10秒后──────────┘
```

---

## 常见问题 | FAQ

### Q: 窗口不显示/显示异常？

1. 确认 War Thunder 已启动并进入战斗
2. 尝试访问 `http://localhost:8111` 确认服务正常
3. 如果返回为空或超时，先重启战雷并重新进入战斗
4. 按 `F9` 切换窗口位置

### Q: 计时器不自动开始？

1. 确认已出生在战场中
2. 检查 8111 端口是否可访问
3. 等待 1-2 秒让程序检测到玩家

### Q: 如何在手机上打开网页驾驶舱？

1. 让手机和电脑连接同一个可信局域网
2. 在 Bomana 主窗口底部或托盘选择“开启局域网访问与控制”，也可在 Launcher 中保存启动偏好
3. 从主窗口查看配对码与实际监听地址，或使用自动复制的一个或多个手机链接
4. 如果无法连接，在 Windows 防火墙提示中允许 Bomana 的专用网络访问；Bomana 不会自动修改防火墙

每次成功配对都会创建独立会话。LAN 已开启时，新配对会话可操作 Bomana 的固定功能；关闭 LAN 会立即失效全部已有 LAN 会话并轮换配对码。网页按钮只操作 Bomana 自身的计时、窗口、声音、面板和可用的武器设置，不会模拟热键或控制游戏。

### Q: 武器解算或投弹提示不准确？

1. 点击武器卡右侧的“选择武器”，确认手选武器和当前机型一致
2. AAM 显示 Datamine 条件表的二维参考；滑翔武器可选实验临时模型或严格不可用模式，它们都不是完整发射包线
3. 自由落体/高阻炸弹还会受游戏未提供的风速与减速构型展开时机影响
4. `设置 -> 投弹` 的距离/时间倍率只校准 CCRP，不会修正导弹或制导武器模型

### Q: 与 WTRTI 有什么区别？

| 特性 | Bomana | WTRTI |
|------|--------|-------|
| 主要用途 | SB 模式计时+武器解算 | 通用飞行数据显示 |
| 15分钟计时 | 核心功能 | 不提供 |
| 武器解算 | Enhanced 内置 | 不提供 |
| 战区导航 | 内置 | 不提供 |
| 自定义指标 | 不提供 | 高度自定义 |
| 平台 | Windows | 跨平台 |

两者可以同时使用，功能互补。

---

## 隐私与数据收集 | Privacy & Data Collection

### 匿名使用数据收集

为了改进产品质量并统计真实用户活跃度（DAU），**本应用会收集匿名化的使用数据**，包括：

- **设备标识符** (device_id) - 通过SHA256单向加密生成，不可逆向追溯到个人
- **安装标识符** (install_id) - 本地随机UUID，用于区分多次安装
- **应用版本、功能通道、事件类型** - 用于统计分析和问题定位

### 我们的承诺

- **完全匿名** - 不收集任何可识别个人的信息（IP、账号、邮箱等）
- **数据最小化** - 仅收集统计必需的字段
- **透明公开** - 代码开源，数据收集逻辑可审查
- **用户可控** - 提供禁用方法（见隐私政策）
- **不用于商业** - 不出售数据，不用于广告

### 详细信息

请查看完整的 **[隐私政策 (docs/PRIVACY.md)](docs/PRIVACY.md)**，了解：
- 收集哪些数据及其用途
- 数据安全与匿名化技术细节
- 如何禁用数据收集
- 您的权利与联系方式

**法律依据：** 通过下载并运行本应用，您同意本隐私政策。我们的数据处理符合GDPR、PIPL等国际隐私法规要求。

---

## 许可证与免责声明 | License & Disclaimer

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

**IMPORTANT:** Misuse or abuse of this software may violate the Gaijin Entertainment User Agreement. Users are solely responsible for ensuring their usage complies with all applicable terms of service and game rules.

**重要提示：** 滥用或不当使用本软件可能违反 Gaijin Entertainment 用户协议。用户需自行确保其使用行为符合所有适用的服务条款和游戏规则。

#### 用户协议相关条款 | Relevant EULA Terms

根据 Gaijin Entertainment 用户协议第 6.1 条：

> **6.1.3.** 禁止安装或使用未经授权的游戏客户端修改、作弊或其他修改游戏进程和/或游戏产生的原始图像（包括修改游戏界面）以获取优势的软件或设备，除非获得 Gaijin 的明确授权。
>
> **6.1.4.** 其他违反公平竞争原则的行为。

#### 责任限制 | Liability

This software is provided "AS IS" without warranty of any kind. The author(s) shall not be held liable for any damages, account suspensions, or consequences arising from the use of this software. **Use at your own risk.**

本软件按"现状"提供，不提供任何形式的保证。作者不对因使用本软件而产生的任何损害、账号封禁或其他后果承担责任。**使用风险由用户自行承担。**

---

## 参考资料 | References

- [War Thunder 官方论坛 - 关于 8111 端口工具的讨论](https://forum.warthunder.com/t/tools-using-data-provided-on-port-8111/106664)
- [Stona_WT 官方回复 (Post #16)](https://forum.warthunder.com/t/tools-using-data-provided-on-port-8111/106664/16)
- [Gaijin Entertainment 用户协议](https://legal.gaijin.net/termsofservice)
- [WTRTI - 另一款官方认可的 8111 端口工具](https://mesofthorny.github.io/WTRTI/)
- [KaerMorh/WTSpeeder - 战雷 IAS 防超速参考项目](https://github.com/KaerMorh/WTSpeeder)
- [War Thunder localhost:8111 API 文档](https://github.com/lucasvmx/WarThunder-localhost-documentation)

---

## 赞助支持 | Sponsor

如果 Bomana 对你有帮助，欢迎通过微信赞助支持开发！

<img src="bomana/assets/branding/sponsor_wechat.png" width="200" alt="微信赞赏二维码">

---

## 更新日志 | Changelog

详见 `docs/CHANGELOG.md`（源码版本以 `bomana/metadata.py` 中 `__version__` 为准；已发布版本见顶部 `app release` 徽章）。

---

*Made by 猹Cheems for the Space Monkeys community*

## 更新服务仓库说明

Bomana 的独立更新统计服务（Docker/FastAPI）已迁移到以下仓库维护：

- https://github.com/Thankyou-Cheems/bomana-worker
- 路径：`services/bomana-update-service/`

本仓库继续维护主程序与启动器；更新服务相关部署文档与迭代以 `bomana-worker` 为准。

签名发布流程由本仓库生成带 Ed25519 `manifest_signature` 的 `manifest_<Variant>.json` 与 `launcher_manifest.json`，再由 `bomana-worker`/TencentCloudPublic 服务按当前部署路径暴露给启动器。服务端不重新签名，也不需要发布私钥；部署后应使用本仓库的 `tools/deploy_update_assets.py` 校验公开接口返回体签名。
