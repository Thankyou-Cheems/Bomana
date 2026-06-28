# 快速入门指南 | Quick Start Guide

[中文](#中文快速入门) | [English](#english-quick-start)

---

## 中文快速入门

### 0. 运行前提

- 平台：Windows
- 游戏：War Thunder 已启动并进入战斗（机库状态不会产生飞行数据）
- 数据来源：`http://localhost:8111`
- 说明：无需额外“开启本地服务器”开关
- 相关文档：更完整的功能与架构说明见 [README](../README.md) 与 [ARCHITECTURE](./ARCHITECTURE.md)

### 1. 获取程序

#### 方式 A：下载启动器（推荐）

1. 打开 [Releases](https://github.com/Thankyou-Cheems/Bomana/releases)
2. 下载 `Bomana_launcher_vX.X.X.exe`
3. 启动器会优先从腾讯云/EdgeOne 获取对应通道的 app 包，失败时自动回退 GitHub；启动器本体也支持独立自更新
4. 新版启动器会保留一个上一版本应用，可在出现坏版本时直接回退

可选通道：

| 通道 | 功能 | 适合人群 |
|------|------|----------|
| **Enhanced** | 计时 + 导航 + 燃油 + CCRP | 完整功能 |
| **Standard** | 计时 + 导航 + 燃油 | 不使用 CCRP |
| **Lite** | 计时 | 最低占用 |

启动器与 app 包：

- `Bomana_launcher_vX.Y.Z.exe`：更新检查、下载、校验、启动器自更新、启动入口，并保留一个上一版回退槽
- `Bomana_app_<Variant>_vX.Y.Z.zip`：实际运行包
- `manifest_<Variant>.json`：版本、地址、SHA256、`min_launcher_version`、Ed25519 发布签名元数据
- `launcher_manifest.json`：启动器版本、文件名、SHA256、文件大小、Ed25519 发布签名元数据

启动器会先校验发布清单签名，再校验下载文件 SHA256。腾讯云/EdgeOne 服务只补下载 URL、来源和大小等派生字段，签名本身来自 GitHub Release 产物。

#### 方式 B：源码运行（已安装 uv）

```bash
git clone https://github.com/Thankyou-Cheems/Bomana.git
cd Bomana
uv sync
uv run python Bomana.pyw
```

如果你已经有 uv 环境，可以直接使用方式 B，不需要下载启动器。

### 2. 启动流程

1. 启动 War Thunder 并进入战斗
2. 运行 Bomana（启动器或 `uv run python Bomana.pyw`）
3. 首次通过启动器运行时会下载 app 包；后续可离线启动本地版本
4. 检查过程中如果切换通道/下载来源/代理，启动器会在当前检查结束后自动按新条件重查
5. 下载新版本后会保留一个 `app_previous/` 目录，必要时可直接用启动器按钮回退
6. 默认窗口在右上角，可通过 `F9` 切换角落

### 3. 核心功能速览

| 功能 | 说明 |
|------|------|
| 15 分钟计时器 | 自动识别出生/着陆/死亡并重置周期 |
| 导航（战区/机场） | 方位、距离、ETE，目标切换 |
| 燃油管理 | 油量、油耗率、返航估算 |
| CCRP 投弹预测 | 基于弹道参数的估算值，不是游戏内真实算法 |
| 超速提醒 | IAS/Mach 双通道分级告警（safe/caution/warning/critical） |
| HUD 叠加层 | 可选开启，提供目标与航向参考 |
| 界面个性化 | 独立文字缩放、主题切换、自定义提示音 |

CCRP 说明：

- 该功能是工程化估计，不是游戏内部真实投弹算法，存在误差是正常现象。
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

---

## English Quick Start

### 0. Prerequisites

- Platform: Windows
- Game state: War Thunder must be in battle (hangar provides no live flight data)
- Data source: `http://localhost:8111`
- Note: no extra in-game "local server" toggle is required
- Further reading: see [README](../README.md) and [ARCHITECTURE](./ARCHITECTURE.md) for the full feature and implementation overview

### 1. Get the App

#### Option A: Launcher (Recommended)

1. Open [Releases](https://github.com/Thankyou-Cheems/Bomana/releases)
2. Download `Bomana_launcher_vX.X.X.exe`
3. Let launcher fetch and verify the app package for your channel
4. New launcher builds retain one previous app version so you can roll back quickly if a bad app package ships

Channels:

| Channel | Features |
|---------|----------|
| **Enhanced** | Timer + navigation + fuel + CCRP |
| **Standard** | Timer + navigation + fuel |
| **Lite** | Timer only |

Launcher/package roles:

- `Bomana_launcher_vX.Y.Z.exe`: update check/download/verify/start entry, plus one-version rollback retention
- `Bomana_app_<Variant>_vX.Y.Z.zip`: runnable app package
- `manifest_<Variant>.json`: version/url/SHA256/`min_launcher_version`/Ed25519 release-signature metadata

#### Option B: Run from Source (uv)

```bash
git clone https://github.com/Thankyou-Cheems/Bomana.git
cd Bomana
uv sync
uv run python Bomana.pyw
```

If you already use uv, Option B is enough.

### 2. Start Flow

1. Launch War Thunder and enter battle
2. Start Bomana (launcher or source run)
3. First launcher run usually downloads app package; later runs can be offline
4. Changing channel/source during a check queues an automatic follow-up re-check
5. After an app update, launcher keeps one previous version for rollback
6. Use `F9` to cycle window corner if needed

### 3. Feature Snapshot

| Feature | Description |
|---------|-------------|
| 15-min timer | Tracks spawn/landing/death cycle automatically |
| Navigation | Zone/airfield bearing, distance and ETE |
| Fuel | Fuel amount, burn rate, return estimate |
| CCRP | Ballistic-based estimate, not the in-game internal algorithm |
| Overspeed | IAS/Mach dual-channel alerts (`safe/caution/warning/critical`) |
| HUD overlay | Optional in-game navigation overlay |
| UI personalization | Independent text scale, theme switching, custom alert sounds |

CCRP note:

- This feature is an engineering estimate and not War Thunder's internal bombing algorithm.
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

---
