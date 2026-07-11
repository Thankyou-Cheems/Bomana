# 快速入门指南 | Quick Start Guide

[中文](#中文快速入门) | [English](#english-quick-start)

---

## 中文快速入门

### 0. 运行前提

- 平台：Windows
- 游戏：War Thunder 已启动并进入战斗（机库状态不会产生飞行数据）
- 数据来源：`http://localhost:8111`
- 说明：无需额外“开启本地服务器”开关
- 相关文档：更完整的功能与架构说明见 [README](../README.md)、[ARCHITECTURE](./ARCHITECTURE.md) 与 [specs](./specs/)

### 1. 获取程序

#### 方式 A：下载启动器（推荐）

1. 打开 [Releases](https://github.com/Thankyou-Cheems/Bomana/releases)
2. 下载 `Bomana_launcher_vX.X.X.exe`
3. 启动器会优先从腾讯云/EdgeOne 获取对应通道的 app 包，失败时自动回退 GitHub；启动器本体也支持独立自更新
4. 新版启动器会保留一个上一版本应用，可在出现坏版本时直接回退

App 8.0.0+ 只与 Launcher 3.0.0+ 兼容。Launcher 会在启动、在线安装、本地导入、回退和异常恢复前拒绝版本格式无效或低于 8.0.0 的 App，并在替换现有有效目录前核对签名清单版本与包内版本完全一致。

可选通道：

| 通道 | 功能 | 适合人群 |
|------|------|----------|
| **Enhanced** | 计时 + 导航 + 燃油 + CCRP | 完整功能 |
| **Standard** | 计时 + 导航 + 燃油 | 不使用 CCRP |
| **Lite** | 计时 | 最低占用 |

启动器与 app 包：

- `Bomana_launcher_vX.Y.Z.exe`：更新检查、下载、校验、启动器自更新、启动入口，并保留一个上一版回退槽
- `Bomana_app_<Variant>_vX.Y.Z.zip`：实际运行包，内置零安装的最小热键 Broker
- `manifest_<Variant>.json`：版本、应用包文件名、SHA256、`min_launcher_version`、Ed25519 发布签名元数据
- `launcher_manifest.json`：启动器版本、文件名、SHA256、文件大小、Ed25519 发布签名元数据

启动器会先校验发布清单签名，再校验下载文件 SHA256。腾讯云/EdgeOne 服务只补下载 URL、来源和大小等派生字段，签名本身来自 GitHub Release 产物。

#### 方式 B：源码运行（已安装 uv）

```powershell
git clone https://github.com/Thankyou-Cheems/Bomana.git
cd Bomana
uv sync --python 3.14.5
$env:BOMANA_SOURCE_DEVELOPMENT = "1"
uv run python Bomana.pyw
```

如果你已经有 uv 环境，可以直接使用方式 B，不需要下载启动器；仓库 `.python-version` 默认 pin 到 Python 3.14.5。
显式 `BOMANA_SOURCE_DEVELOPMENT=1` 只用于非冻结源码开发；打包 App 始终需要有效的 Launcher 3.0.0+ 身份。
源码调试若要测试可选管理员热键，可先运行 `uv run python tools/build_hotkey_broker.py --mode dev --output bomana/bin`；这只在仓库内生成被忽略的 native 文件，不会安装程序或修改系统。

### 2. 启动流程

1. 启动 War Thunder 并进入战斗
2. 运行 Bomana（推荐 Launcher 3.0.0+；源码运行使用上面的显式开发标记）
3. 首次通过启动器运行时会下载 app 包；后续可离线启动本地版本
4. 检查过程中如果切换通道/下载来源/代理，启动器会在当前检查结束后自动按新条件重查
5. 下载新版本后会保留一个 `app_previous/` 目录，必要时可直接用启动器按钮回退
6. 启动器可保存“随 App 启动本机 Web 服务”（默认开启）和“启动成功后自动打开本机页面”（默认关闭）；端口、配对和 LAN 权限由 App 管理且不会保存
7. 默认窗口在右上角，可通过 `F9` 或网页驾驶舱按钮切换角落

#### 游戏前台热键权限

- Launcher 与 Bomana App 始终以普通权限运行；启动时先启用普通热键，不会自动弹 UAC。
- Bomana 只检查可见 War Thunder 窗口对应的进程名和管理员状态，不读取游戏内存、模块或文件。确认游戏普通运行时不会显示提权建议。
- 游戏以管理员运行、尚未启动或权限无法判断时，App 会显示“授权管理员热键”。点击后先阅读确认说明，再由你在 Windows UAC 中手动批准随 App 包携带的最小 Broker；无需安装任何额外 EXE、服务或计划任务。
- 项目没有商业 Authenticode 证书，因此 UAC 会显示“未知发布者”。可用 `gh attestation verify <下载文件> --repo Thankyou-Cheems/Bomana` 验证 GitHub Actions 构建来源。
- 拒绝 UAC 不会阻止 Bomana 启动；窗口按钮、托盘、计时、导航和官方 8111 数据保持可用，只是游戏获得焦点时的全局 F7-F11 可能失效。
- Broker 只注册当前启用的固定动作，不使用键盘钩子、轮询、Raw Input、游戏内存读取、服务或计划任务。

#### 网页驾驶舱（本机 / 手机）

1. 启动器默认让 Bomana 自动提供网页驾驶舱；若关闭了自动启动，也可随时从系统托盘选择“网页驾驶舱 -> 打开本机页面”按需启动。无需油猴或浏览器插件。
2. 本机服务默认使用 `127.0.0.1:8777`，端口占用时会在有限范围内自动选择相邻端口，因此请优先使用托盘入口。
3. 手机与电脑连接同一个可信局域网后，在托盘中选择“允许局域网访问（本次运行）”并确认。Bomana 会复制带本次配对码的手机链接。
4. 在手机浏览器打开该链接。每次成功配对都会创建独立会话；局域网会话默认只有查看权限。
5. 如需从手机操作 Bomana，在电脑端托盘中再开启“允许局域网控制（本次运行）”，并使用轮换后的新链接重新配对。已有只读会话不会自动升级；撤销会立即使已有 LAN 控制会话失效。
6. 局域网访问与控制都不会保存到下次启动。Bomana 不会自动修改 Windows 防火墙；若手机无法连接，请允许 Bomana 的“专用网络”访问。

网页以地图为主要信息入口，并集中显示计时、飞行、燃油、导航、武器/投弹参考、检查清单和告警。获得控制权限后，可用实体按钮重置计时、切换角落、设定窗口锁定与提示音、显示/隐藏可用面板，并在 Enhanced 中选择当前武器与弹道模型。页面不会模拟 F7-F11，也不会控制游戏或扩展热键 Broker。所有通道都包含网页资源，卡片与控制会按当前 `ENABLE_*` 功能显示。

### 3. 核心功能速览

| 功能 | 说明 |
|------|------|
| 15 分钟计时器 | 自动识别出生/着陆/死亡并重置周期 |
| 导航（战区/机场） | 方位、距离、ETE，目标切换 |
| 燃油管理 | 油量、油耗率、返航估算 |
| 武器解算 | 自由落体 CCRP + AAM/AGM/制导与滑翔武器参考 |
| 超速提醒 | IAS/Mach 双通道分级告警（safe/caution/warning/critical） |
| HUD 叠加层 | 可选开启，提供目标与航向参考 |
| 网页驾驶舱 | 本机/手机响应式地图与关键信息面板 |
| 界面个性化 | 独立文字缩放、主题切换、自定义提示音 |

武器解算说明：

- 该功能是工程化估计，不是游戏内部真实投弹算法，存在误差是正常现象。
- 普通/高阻炸弹使用 CCRP；AAM/AGM 优先使用 Datamine 条件表。
- 无表滑翔武器默认使用明确标为实验参考的 FoxThree 兼容临时模型，也可在武器选择器切到严格模式停用临时模型。
- 当前 Mach >= 1.0 时按多数炸弹无法投放处理，面板会提示超出投放限制。
- 可在 `设置 -> 投弹` 中手动校准：`距离修正倍率`、`时间修正倍率`。
- 静态炸弹库来源：War Thunder datamine `aces.vromfs.bin_u/gamedata/weapons/bombguns/*.blkx` -> `tools/update_datamine_assets.py` -> `tools/blkx_extractor.py` -> `bomana/data/ccrp_bomb_params.json`

超速提醒说明：

- 数据库：`bomana/data/fm_speed_limits.json`
- 静态限速库来源：War Thunder datamine `aces.vromfs.bin_u/gamedata/flightmodels/**` -> `tools/update_datamine_assets.py` -> `tools/fm_speed_extractor.py`
- 参考实现：会对照 [KaerMorh/WTSpeeder](https://github.com/KaerMorh/WTSpeeder) 核验旧版 `Vne` / `VneMach` 字段和告警阈值
- 识别链路：`/indicators.type -> unit_to_fm -> fm_speed_limits`
- 告警输出：紧凑速度条 + warning/critical 声音节奏

### 4. 常见问题

**Q: 显示“8111不可用”？**  
A: 确认游戏正在战斗中；再访问 `http://localhost:8111` 检查是否可达；必要时重启战雷。

**Q: 看不到导航或燃油面板？**  
A: 检查当前通道（Lite 不含这些面板），并确认在多人全真战斗中。

**Q: 看不到超速提醒？**  
A: 需要匹配到机型 FM 限速库；若当前机型未匹配，会保持 `unknown/safe`。

**Q: CCRP 预测有偏差？**  
A: 这是估计算法，不是游戏内真实算法。可在 `设置 -> 投弹` 中调整 `距离修正倍率` 和 `时间修正倍率`。

**Q: 计时器不准？**  
A: 使用当前配置的重置热键连续按两次，手动重置周期；默认是 `F7`。

**Q: 手机打不开网页驾驶舱？**

A: 确认已从托盘为本次运行开启局域网访问，手机与电脑位于同一局域网，并在 Windows 防火墙中允许 Bomana 的专用网络访问。VPN、访客 Wi-Fi 或 AP 隔离也可能阻止设备互访。

### 5. 开发者：更新数据文件

统一更新炸弹参数与机型超速限速库：

- 输入：War Thunder datamine 仓库根目录
- 输出：`ccrp_bomb_params.json` + `fm_speed_limits.json`
- 元数据：自动记录 datamine `source_version` / `source_commit`

```bash
uv run python tools/update_datamine_assets.py ^
  <path-to-datamine-root> ^
  --no-bomb-report
```

### 6. 开发者：打包与发布核对

需要为离线回放采集一场真实对局时，运行
`uv run python tools/record_8111_session.py --label "full-sortie-1" --mode SB`，
进入战斗并在出击结束后按一次 `Ctrl+C`。完整步骤和隐私边界见
[8111 对局录制指南](./guides/8111-session-recording.md)。
录制完成后可运行
`uv run python tools/replay_8111_session.py <recording.jsonl.gz> --speed max --profile full-sortie`
在数秒内校验完整核心链路，无需再次打开游戏。

- 发布构建使用 Python 3.14 + uv；本地打包前运行 `uv sync --extra build --frozen`。
- 生成 `manifest_<Variant>.json` 或 `launcher_manifest.json` 必须设置 `BOMANA_RELEASE_ED25519_PRIVATE_KEY`、`BOMANA_RELEASE_ED25519_PUBLIC_KEY` 和 `BOMANA_RELEASE_SIGNING_KEY_ID`（默认 `bomana-release-2026-06`）。
- App 发布构建会自动编译并内置 native 热键 Broker；Actions 使用 `actions/attest@v4` 为最终包、清单与校验文件生成来源证明。
- 本地发布命令入口是 `uv run --frozen python tools/build_portable.py --variant Enhanced|Standard|Lite --target app|launcher|all`；`--version` 只是可选一致性校验，app 目标必须匹配 `bomana/metadata.py` 的 `__version__`，launcher 目标必须匹配 `launcher/metadata.py` 的 `LAUNCHER_VERSION`。
- 当前源码边界为 App `8.0.0` / Launcher `3.0.0`。App ZIP 必须包含共享版本边界与网页控制 schemas；不要用旧 Launcher 或旧 App 目录代替真实打包烟测。
- 部署前先确认 `gh secret list --repo Thankyou-Cheems/Bomana`；GitHub Release 完成后在本机运行 `gh release download vX.Y.Z --dir dist`，再运行 `uv run python tools/deploy_update_assets.py --target app|launcher|all --version X.Y.Z`。不要用 GitHub Actions 直连腾讯云主机部署，公开端点验证必须调用 `verify_release_manifest_signature`。
- 发布签名字段、密钥处理和部署边界以 [release-signing spec](./specs/release-signing.md) 为准。

---

## English Quick Start

### 0. Prerequisites

- Platform: Windows
- Game state: War Thunder must be in battle (hangar provides no live flight data)
- Data source: `http://localhost:8111`
- Note: no extra in-game "local server" toggle is required
- Further reading: see [README](../README.md), [ARCHITECTURE](./ARCHITECTURE.md), and [specs](./specs/) for the full feature and implementation overview

### 1. Get the App

#### Option A: Launcher (Recommended)

1. Open [Releases](https://github.com/Thankyou-Cheems/Bomana/releases)
2. Download `Bomana_launcher_vX.X.X.exe`
3. Let launcher fetch and verify the app package for your channel
4. New launcher builds retain one previous app version so you can roll back quickly if a bad app package ships

App 8.0.0+ requires Launcher 3.0.0+. Launcher 3 validates the same strict App version boundary before launch, online install, local import, rollback, or incomplete-install recovery, and preserves a valid install when a candidate is malformed or older.

Channels:

| Channel | Features |
|---------|----------|
| **Enhanced** | Timer + navigation + fuel + CCRP |
| **Standard** | Timer + navigation + fuel |
| **Lite** | Timer only |

Launcher/package roles:

- `Bomana_launcher_vX.Y.Z.exe`: update check/download/verify/start entry, plus one-version rollback retention
- `Bomana_app_<Variant>_vX.Y.Z.zip`: runnable app package with the zero-install native hotkey broker bundled inside
- `manifest_<Variant>.json`: version/package asset/SHA256/`min_launcher_version`/Ed25519 release-signature metadata
- `launcher_manifest.json`: launcher version/asset/SHA256/size/Ed25519 release-signature metadata

The launcher validates Ed25519 manifest signatures before trusting version, asset, or SHA256 fields. The Tencent/EdgeOne service only adds derived fields such as package URL, source name, and size.

#### Option B: Run from Source (uv)

```powershell
git clone https://github.com/Thankyou-Cheems/Bomana.git
cd Bomana
uv sync --python 3.14.5
$env:BOMANA_SOURCE_DEVELOPMENT = "1"
uv run python Bomana.pyw
```

If you already use uv, Option B is enough; the repo `.python-version` pins Python 3.14.5.
The explicit marker is accepted only for a non-frozen source/development run. A packaged App always requires a valid Launcher 3.0.0+ identity.
For source-mode admin-hotkey testing, first run `uv run python tools/build_hotkey_broker.py --mode dev --output bomana/bin`; this creates an ignored native file inside the checkout and does not install or modify the system.

### 2. Start Flow

1. Launch War Thunder and enter battle
2. Start Bomana (launcher or source run)
3. First launcher run usually downloads app package; later runs can be offline
4. Changing channel/source during a check queues an automatic follow-up re-check
5. After an app update, launcher keeps one previous version for rollback
6. Launcher can persist only loopback Web autostart (on by default) and local-page auto-open (off by default); the App owns ports, pairing, and every LAN permission
7. Use `F9` or the Web Cockpit action button to cycle the window corner

#### Game-foreground hotkey permission

- Launcher and the Python App always stay at ordinary integrity; ordinary hotkeys start first and UAC is never automatic.
- Bomana queries only the executable name and elevation token for visible War Thunder windows. If the game is confirmed ordinary, no privilege recommendation is shown.
- If the game is elevated, closed, or its token cannot be queried, the App offers “Authorize admin hotkeys”. After an explanatory confirmation, you can manually approve the bundled native broker in UAC; no helper installer, service, or scheduled task is created.
- Without a commercial Authenticode certificate, UAC shows “Unknown publisher”. Run `gh attestation verify <download> --repo Thankyou-Cheems/Bomana` to verify GitHub build provenance.
- Denying UAC keeps buttons, tray actions, timer/navigation, and official 8111 data available; only global F7-F11 delivery while the game has focus may be unavailable.
- The broker registers only enabled fixed actions and does not use hooks, polling, Raw Input, game-memory access, a service, or a scheduled task.

#### Web Cockpit (Local / Mobile)

1. Bomana starts the Web Cockpit automatically by default. If autostart is disabled in Launcher, `Web Cockpit -> Open local page` starts it on demand; no userscript manager or browser extension is required.
2. The local listener prefers `127.0.0.1:8777` and uses a bounded nearby-port fallback if that port is occupied, so use the tray entry instead of a hard-coded bookmark.
3. Put the phone and PC on the same trusted LAN, then choose `Allow LAN access (this run)` from the tray and confirm. Bomana copies a phone link containing the current pairing code.
4. Open that link on the phone. Every successful pairing creates a distinct session, and LAN sessions are view-only by default.
5. To control Bomana from the phone, explicitly enable `Allow LAN control (this run)` on the PC and pair again with the rotated link. Existing view sessions are not upgraded; revocation immediately invalidates existing LAN control sessions.
6. LAN access and control are never persisted. Bomana does not change Windows Firewall; if the phone cannot connect, allow Bomana on private networks.

The responsive page is map-first and combines timer, flight, fuel, navigation, weapon/bombing references, checklist, and alerts. A control session can reset the timer, cycle the window corner, set lock and sound targets, select visible panels, and—when CCRP is enabled—choose the current weapon and ballistic model. These are explicit Bomana actions, not synthesized F-keys or game controls. All channels package the dashboard; cards and controls follow the active `ENABLE_*` capabilities.

### 3. Feature Snapshot

| Feature | Description |
|---------|-------------|
| 15-min timer | Tracks spawn/landing/death cycle automatically |
| Navigation | Zone/airfield bearing, distance and ETE |
| Fuel | Fuel amount, burn rate, return estimate |
| Weapon solution | Free-fall CCRP plus AAM/AGM/guided/glide references |
| Overspeed | IAS/Mach dual-channel alerts (`safe/caution/warning/critical`) |
| HUD overlay | Optional in-game navigation overlay |
| Web Cockpit | Responsive local/mobile map and key information panels |
| UI personalization | Independent text scale, theme switching, custom alert sounds |

Weapon-solution note:

- This feature is an engineering estimate and not War Thunder's internal bombing algorithm.
- Free-fall/high-drag bombs use CCRP; AAM/AGM references prefer Datamine condition tables.
- Glide stores without a usable table default to an explicitly experimental FoxThree-compatible temporary model; strict mode disables that temporary fallback.
- Mach >= 1.0 is treated as above the release limit for normal bomb prediction.
- Prediction error is expected; calibrate in `Settings -> Bombing` using `range correction` and `time correction`.
- Static bomb DB provenance: War Thunder datamine `aces.vromfs.bin_u/gamedata/weapons/bombguns/*.blkx` -> `tools/update_datamine_assets.py` -> `tools/blkx_extractor.py` -> `bomana/data/ccrp_bomb_params.json`

Overspeed specifics:

- DB: `bomana/data/fm_speed_limits.json`
- Static speed-limit DB provenance: War Thunder datamine `aces.vromfs.bin_u/gamedata/flightmodels/**` -> `tools/update_datamine_assets.py` -> `tools/fm_speed_extractor.py`
- Matching path: `/indicators.type -> unit_to_fm -> fm_speed_limits`
- Output: badge state + warning/critical sound cadence

### 4. FAQ

**Q: "8111 Unavailable"?**  
A: Ensure you are in battle, then test `http://localhost:8111`; restart game if needed.

**Q: No navigation/fuel panels?**  
A: Check your channel (Lite does not include them) and battle mode.

**Q: No overspeed alert?**  
A: Aircraft FM may not be matched in the current speed-limit database.

**Q: CCRP prediction is off?**  
A: Expected for an estimate-based model. Tune `range correction` and `time correction` in `Settings -> Bombing`.

**Q: The phone cannot open Web Cockpit?**

A: Enable LAN access for this run from the tray, keep both devices on the same LAN, and allow Bomana on Windows private networks. VPNs, guest Wi-Fi, or AP isolation can also block device-to-device access.

### 5. Developer: Build/Release Checks

To capture one real sortie for offline replay, run
`uv run python tools/record_8111_session.py --label "full-sortie-1" --mode SB`,
enter battle, then press `Ctrl+C` once after the sortie. See the
[8111 session recording guide](./guides/8111-session-recording.md) for the full
workflow and privacy boundary.
After capture, run
`uv run python tools/replay_8111_session.py <recording.jsonl.gz> --speed max --profile full-sortie`
to validate the complete core path in seconds without reopening the game.

- Release builds use Python 3.14 + uv; run `uv sync --extra build --frozen` before local packaging.
- Signed manifests require `BOMANA_RELEASE_ED25519_PRIVATE_KEY`, `BOMANA_RELEASE_ED25519_PUBLIC_KEY`, and `BOMANA_RELEASE_SIGNING_KEY_ID` (default `bomana-release-2026-06`).
- App builds compile and bundle the native broker automatically. GitHub release jobs attest final packages, manifests, and checksum files with `actions/attest@v4`; Authenticode secrets are not required.
- Local package entry: `uv run --frozen python tools/build_portable.py --variant Enhanced|Standard|Lite --target app|launcher|all`; `--version` is an optional consistency check and must match `bomana/metadata.py __version__` for app builds or `launcher/metadata.py LAUNCHER_VERSION` for launcher builds.
- The current source boundary is App `8.0.0` / Launcher `3.0.0`. App ZIPs must include the shared version boundary and Web control schemas; use real packaged artifacts for compatibility and DPI smoke.
- Before deploy, check `gh secret list --repo Thankyou-Cheems/Bomana`; after GitHub finishes the Release, run `gh release download vX.Y.Z --dir dist` and then `uv run python tools/deploy_update_assets.py --target app|launcher|all --version X.Y.Z` on the maintainer workstation. Do not deploy to Tencent from Actions. Public endpoint checks must call `verify_release_manifest_signature`.
- Release signing fields, key handling, and deployment boundaries are canonical in [release-signing spec](./specs/release-signing.md).

---
