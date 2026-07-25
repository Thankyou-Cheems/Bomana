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

App 8 / Launcher 3 的协议基线是 `8.0.0` / `3.0.0`，但每个 App 发布还会声明自己的最低 Launcher 版本；当前 App 8.6.2 要求 Launcher 3.3.0+。旧启动器会根据签名清单在下载前阻止更新；Launcher 在启动、在线安装、本地导入、回退和异常恢复前也会读取包内最低版本，并在替换现有有效目录前核对签名清单版本与包内版本完全一致。

可选通道：

| 通道 | 功能 | 适合人群 |
|------|------|----------|
| **超级爆弹版**（内部通道 `Enhanced`） | 深度学习的高精度打击模型与地形数据 | 最高精度投弹预测与离线地形参考 |
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
显式 `BOMANA_SOURCE_DEVELOPMENT=1` 只用于非冻结源码开发；打包 App 始终需要有效的 Launcher 身份。当前 App 8.6.2 要求 Launcher 3.3.0+，旧启动器会在下载前阻止更新，App 本身也会在业务模块加载前拒绝旧版本。
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
- Bomana 不枚举游戏窗口或进程，不查询游戏进程名、令牌、模块或内存，也不会根据游戏状态显示提权建议。
- 普通热键仅使用 Windows `RegisterHotKey`，不使用键盘钩子、轮询、Raw Input 或游戏输入模拟。
- 若游戏前台权限边界使全局 F6-F11 失效，请使用投弹栏、主窗或托盘里的等价按钮；计时、导航和官方 8111 数据保持可用。

#### 网页驾驶舱（本机 / 手机）

1. 启动器默认让 Bomana 自动提供网页驾驶舱；若关闭了自动启动，也可从托盘按需启动。App 主窗口底部会显示当前配对码、监听地址与实体控制。
2. 本机服务默认使用 `127.0.0.1:8777`，端口占用时会在有限范围内自动选择相邻端口，因此请优先使用 App 或托盘入口。
3. 手机与电脑连接同一个可信局域网后，在 App 主窗口或托盘选择“开启局域网访问与控制”并确认；也可以在 Launcher 中保存下次启动时自动开启的布尔偏好。Bomana 每次都会自动发现当前网卡，为所有可绑定的 RFC1918 地址建立精确监听并复制对应链接。
4. 在手机浏览器打开新链接。每次成功配对都会创建独立控制会话；网页写入仍需要同源 Origin、会话 CSRF、幂等键、共享 schema 和 App 主线程复核。
5. 关闭 LAN 会立即撤销全部已有 LAN 会话、轮换配对码并回收所有监听。Launcher 只保存是否自动开启，不保存地址、端口、配对或实时授权。
6. Bomana 不会自动修改 Windows 防火墙；若手机无法连接，请允许 Bomana 的“专用网络”访问。

网页以官方地图缩略图为半透明底图，并叠加筛选后的标记和当前武器射程；同时集中显示计时、飞行、燃油、导航、武器/投弹参考、检查清单和告警。获得控制权限后，可用实体按钮重置计时、切换角落、设定窗口锁定与提示音、显示/隐藏可用面板，并在超级爆弹版中选择当前武器。页面不会模拟 F6-F11，也不会控制游戏或扩展热键 Broker。

### 3. 核心功能速览

| 功能 | 说明 |
|------|------|
| 可配置计时器 | 1–180 分钟周期，自动识别出生/着陆/死亡 |
| 导航（战区/机场） | 方位、距离、ETE，目标切换 |
| 燃油管理 | 油量、油耗率、返航估算 |
| 武器解算 | 自由落体 CCRP + AAM/AGM/制导与滑翔武器参考 |
| 超速提醒 | IAS/Mach 双通道分级告警（safe/caution/warning/critical） |
| 网页驾驶舱 | 本机/手机响应式地图与关键信息面板 |
| 界面个性化 | 独立文字缩放、主题切换、自定义提示音 |

武器解算说明：

- 该功能是工程化估计，不是游戏内部真实投弹算法，存在误差是正常现象。
- 普通自由落体炸弹使用 CCRP；高阻炸弹在缺少已验证离线模型时会停用预测；AAM/AGM 优先使用 Datamine 条件表。
- 无官方包线的滑翔武器可选择使用明确标记的推测替代，或不应用替代模型；官方数据在两种策略下始终优先。
- 当前 Mach >= 1.0 时按多数炸弹无法投放处理，面板会提示超出投放限制。
- CCRP 不接受运行时距离、时间或阻力修正；请确保手动选择的弹药与实际挂载一致。
- 静态炸弹库由 `tools/update_datamine_assets.py` / `tools/blkx_extractor.py` 构建为 `bomana/data/offline_rigidbody_catalog.bin`。

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
A: 这是基于 8111 与离线地形/刚体数据的工程化投影。请先核对弹药选择、战区/兴趣点目标模式和地图包状态；运行时不会套用用户阻力或距离修正。

**Q: 计时器不准？**  
A: 使用当前配置的重置热键连续按两次，手动重置周期；默认是 `F7`。

**Q: 手机打不开网页驾驶舱？**

A: 确认已从 App 或托盘为本次运行开启局域网访问，并在主窗口检查手机所在网段或 EasyTier 地址是否已列出。仍无法连接时，确认 Windows 防火墙允许 Bomana 的专用网络访问，并排除访客 Wi-Fi/AP 隔离。

### 5. 开发者：更新数据文件

统一更新炸弹参数与机型超速限速库：

- 输入：War Thunder datamine 仓库根目录
- 输出：`offline_rigidbody_catalog.bin` + `fm_speed_limits.json`
- 元数据：离线刚体目录不写入逐条来源元数据；限速与武器 JSON 仍记录其构建版本

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
- 当前源码版本为 App `8.6.2` / Launcher `3.3.0`，基础兼容下限仍为 App `8.0.0` / Launcher `3.0.0`，当前 App 发布清单要求 Launcher `3.3.0`。仅内部通道 `Enhanced`（超级爆弹版）App ZIP 包含深度学习的高精度打击模型、网页控制 schemas 与驾驶舱资源；`terrain-v1` 由启动器在 App 目录外独立维护，不进入任何 App ZIP。不要用不兼容的 Launcher 或 App 目录代替真实打包烟测。
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

The App 8 / Launcher 3 protocol floor is `8.0.0` / `3.0.0`, but each App release also declares its own Launcher requirement; App 8.6.2 requires Launcher 3.3.0+. An older Launcher blocks the update before downloading package bytes from the signed manifest. Launcher also validates the package-declared floor before launch, online install, local import, rollback, or incomplete-install recovery.

Channels:

| Channel | Features |
|---------|----------|
| **超级爆弹版** (internal channel: `Enhanced`) | Deep-learning high-precision strike model and terrain data |
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
The explicit marker is accepted only for a non-frozen source/development run. A packaged App always requires a valid Launcher identity meeting that App release's floor; App 8.6.2 requires Launcher 3.3.0+.
For source-mode admin-hotkey testing, first run `uv run python tools/build_hotkey_broker.py --mode dev --output bomana/bin`; this creates an ignored native file inside the checkout and does not install or modify the system.

### 2. Start Flow

1. Launch War Thunder and enter battle
2. Start Bomana (launcher or source run)
3. First launcher run usually downloads app package; later runs can be offline
4. Changing channel/source during a check queues an automatic follow-up re-check
5. After an app update, launcher keeps one previous version for rollback
6. Launcher persists only Web autostart (on by default), local-page auto-open (off), and LAN access/control startup (off); the App still owns interface discovery, ports, pairing, sessions, and live authorization
7. Use `F9` or the Web Cockpit action button to cycle the window corner

#### Game-foreground hotkey permission

- Launcher and the Python App always stay at ordinary integrity; ordinary hotkeys start first and UAC is never automatic.
- Bomana does not enumerate game windows or processes, query game executable identities or tokens, inspect modules or memory, or derive a privilege recommendation from game state.
- Ordinary hotkeys use only Windows `RegisterHotKey`, with no hook, polling, Raw Input, or synthesized game input.
- If foreground integrity blocks F6-F11, use the equivalent bombing-bar, main-window, or tray buttons; timer/navigation and official 8111 data remain available.

#### Web Cockpit (Local / Mobile)

1. Bomana starts the Web Cockpit automatically by default. If autostart is disabled, the tray can start it on demand; the App bottom row shows the current pairing code, listener addresses, and physical actions.
2. The local listener prefers `127.0.0.1:8777` and uses a bounded nearby-port fallback if that port is occupied, so use the App or tray entry instead of a hard-coded bookmark.
3. Put the phone and PC on the same trusted LAN, then choose `Enable LAN access and control` in the App or tray, or save the equivalent Launcher startup preference. Bomana rediscovers adapters each run, binds every eligible exact RFC1918 address, and copies the phone links.
4. Open a new link on the phone. Every successful pairing creates a distinct control session; writes still require exact same-origin Origin, per-session CSRF, idempotency, shared-schema validation, and Tk-owner reauthorization.
5. Disabling LAN immediately invalidates every LAN session, rotates the pairing code, and closes all LAN listeners. Launcher persists only the startup boolean, never addresses, ports, pairing material, or live authorization.
6. Bomana does not change Windows Firewall; if the phone cannot connect, allow Bomana on private networks.

The responsive page uses the official tactical-map thumbnail at reduced opacity below filtered markers and the current weapon-range ellipse. Its tactical map also mirrors every hostile aircraft, ground, naval, or unknown unit in the current raw `/map_obj.json` sample and renders it with the official 8111 `/icons.ttf` glyph resource; the over-map legend uses the same glyph mapping. These markers are cleared without history reconstruction and never enter standalone navigation or CCRP bars. It combines timer, flight, fuel, navigation, weapon/bombing references, checklist, and alerts. A control session can reset the timer, set its bounded 1–180 minute cycle, cycle the window corner, set lock and sound targets, select visible panels, and—when CCRP is enabled—choose the current weapon and whether an estimated substitute may be used only when official data is absent. These are explicit Bomana actions, not synthesized F-keys or game controls. The same timer-cycle target is available from the tray; an active sortie keeps its spawn timestamp and immediately recalculates progress against the new period.

### 3. Feature Snapshot

| Feature | Description |
|---------|-------------|
| Configurable timer | Tracks spawn/landing/death cycles automatically with a 1–180 minute period |
| Navigation | Zone/airfield bearing, distance and ETE |
| Fuel | Fuel amount, burn rate, return estimate |
| Weapon solution | Free-fall CCRP plus AAM/AGM/guided/glide references |
| Overspeed | IAS/Mach dual-channel alerts (`safe/caution/warning/critical`) |
| Web Cockpit | Responsive local/mobile map and key information panels |
| UI personalization | Independent text scale, theme switching, custom alert sounds |

Weapon-solution note:

- This feature is an engineering estimate and not War Thunder's internal bombing algorithm.
- Free-fall bombs use CCRP; high-drag prediction stays disabled without a validated offline model. AAM/AGM references prefer Datamine condition tables.
- Glide stores without an official table may use an explicitly marked estimated substitute or no substitute; official data always takes priority.
- Mach >= 1.0 is treated as above the release limit for normal bomb prediction.
- Runtime range, time, and drag corrections are not accepted; make sure the selected store matches the actual loadout.
- The static store catalog is built by `tools/update_datamine_assets.py` / `tools/blkx_extractor.py` as `bomana/data/offline_rigidbody_catalog.bin`.

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

A: Enable LAN access for this run from the App or tray, then confirm the phone subnet or EasyTier address appears in the App row. If it still fails, allow Bomana on Windows private networks and rule out guest Wi-Fi/AP isolation.

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
- The current source versions are App `8.6.2` / Launcher `3.3.0`; base compatibility floors remain App `8.0.0` / Launcher `3.0.0`, while the current App manifest requires Launcher `3.3.0`. Only the internal `Enhanced` channel (超级爆弹版) embeds the deep-learning high-precision strike resources, Web control schemas, and cockpit assets. Launcher maintains `terrain-v1` outside the rotating App directory, and no App ZIP contains it; use real packaged artifacts for compatibility and DPI smoke.
- Before deploy, check `gh secret list --repo Thankyou-Cheems/Bomana`; after GitHub finishes the Release, run `gh release download vX.Y.Z --dir dist` and then `uv run python tools/deploy_update_assets.py --target app|launcher|all --version X.Y.Z` on the maintainer workstation. Do not deploy to Tencent from Actions. Public endpoint checks must call `verify_release_manifest_signature`.
- Release signing fields, key handling, and deployment boundaries are canonical in [release-signing spec](./specs/release-signing.md).

---
