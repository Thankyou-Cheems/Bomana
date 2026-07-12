# Bomana

> **新用户请先看官网：** [https://thankyou-cheems.github.io/Bomana/](https://thankyou-cheems.github.io/Bomana/) — 功能介绍、下载入口与使用说明都在这里。

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

## 选择语言 | Choose Language

|  |  |
|:--|:--|
| **[中文文档](#中文文档)** | 本页正文（默认） |
| **[English Documentation](README.en.md)** | Separate English page |

---

# 中文文档

## 目录

### 普通用户

- [合规性声明](#合规性声明)
- [功能介绍](#功能介绍)
- [下载与使用](#下载与使用)
- [快捷键](#快捷键)
- [常见问题](#常见问题)
- [隐私说明](#隐私说明)
- [许可证与免责声明](#许可证与免责声明)
- [赞助支持](#赞助支持)

### 开发者

- [文档导航](#文档导航)
- [从源码运行](#从源码运行)
- [项目目录结构](#项目目录结构)
- [高级配置](#高级配置)
- [技术原理](#技术原理)
- [构建与发布](#构建与发布)
- [参考资料](#参考资料)
- [更新服务仓库](#更新服务仓库)

---

# 普通用户

面向日常游玩：如何下载、怎么用、有哪些功能。尽量少用术语。

## 合规性声明

> 本声明发布前的旧版本已下架。下载并使用新版，即视为知悉并同意本声明。

### 官方怎么说

社区经理 **Stona_WT** 在 2024 年 5 月 13 日的[官方回复](https://forum.warthunder.com/t/tools-using-data-provided-on-port-8111/106664/16)中大致表示：

- 用游戏本机提供的数据显示飞行信息、覆盖层，一般可以，不会因此直接封禁。
- 但在无标记模式下，把敌人位置做成罗盘式叠加层、获得相对其他玩家的优势，官方**不认可**，可能被视为不当辅助。

### Bomana 怎么做

| 做法 | 态度 |
|------|------|
| 显示自己的速度、高度、油量等 | 允许 |
| 用官方本机数据做计时、导航参考 | 允许 |
| 在无标记模式把敌人画进游戏画面式叠加层 | 不认可 |
| 用独立网页地图镜像当前官方返回的敌方单位 | 官方未明确表态，请自行判断 |
| 读取内存、注入、改游戏文件等 | 禁止 |

Bomana 的原则：

1. 只读游戏官方在本机提供的数据，不读内存、不注入、不改游戏文件
2. 计时基于你自己的出生时间，不操纵服务器
3. 敌方单位只出现在独立网页地图里，且仅显示当前一帧官方返回的内容；不进入桌面 HUD 或航向带
4. 不根据历史位置推算轨迹，也不补齐缺失目标

**请你自行了解规则，并为自己的使用方式负责。** 功能“能做”不等于官方一定认可。

---

## 功能介绍

### 15 分钟收益计时

全真模式每次出生后有约 15 分钟收益周期。Bomana 会：

- 自动识别出生、着陆、阵亡并开始/重置计时
- 显示当前是第几条命
- 程序重启后尽量接着计
- 临近结束时用语音或提示音提醒

### 武器投放参考

在支持的版本里提供投放距离、时间窗口等**估算**提示（自由落体炸弹、部分导弹与制导武器等）。

请注意：

- 这些都是参考值，不是游戏内部真实算法
- 需要你手动选择当前武器，程序不会自动猜挂载
- 可在设置里对自由落体路径做简单距离/时间修正

### 战区与机场导航

- 图形化航向、距离、预计到达时间
- 对准目标一段时间后可自动锁定
- 返航机场方向与距离；敌方机场可按需显示
- 同一战局复活后，可提示上次损失位置方向

### 画面叠加导航（可选）

- 在游戏画面上给出主目标方位提示（默认关闭，在设置里打开）
- 可调透明度、大小、显示器等

### 燃油与超速提醒

- 油量、油耗与返航油量粗估
- 按机型提示是否接近限速（表速与马赫）

### 出击检查清单

起飞前可勾选的自定义检查项（开引擎、收起落架等）。

### 界面

| 能力 | 说明 |
|------|------|
| 透明、置顶 | 少挡视线，始终可见 |
| 锁定 | 锁定后鼠标点穿，不影响操作游戏 |
| 拖动与贴边 | 自由摆放，可贴屏幕边缘 |
| 主题与热键 | 明暗主题；F7–F11 可改 |
| 系统托盘 | 可最小化到托盘 |
| 独立文字大小 | 只放大字，不硬撑整窗 |
| 自定义提示音 | 可按类别导入本地音频 |

### 手机 / 本机网页面板

可在电脑浏览器或同一可信局域网的手机上查看计时、地图、油量、导航等信息，并操作部分 Bomana 自身功能（如重置计时、切换角落、开关声音等）。

- 默认先本机可用；要给手机用时，在程序里开启「局域网访问与控制」
- 开启局域网后，之后配对的设备可控制这些固定功能；关闭后立即失效全部局域网会话
- 不会代替你按游戏热键，也不会操控游戏本身

更细的上手步骤见 [docs/QUICKSTART.md](docs/QUICKSTART.md)。

---

## 下载与使用

### 使用前

1. 系统：Windows
2. 先启动 War Thunder 并**进入战斗**（机库里通常没有可用的飞行数据）
3. 一般无需额外开关；游戏进入战斗后，本机数据即可被读取

### 推荐：下载启动器

1. 打开 [Releases](https://github.com/Thankyou-Cheems/Bomana/releases)
2. 下载 `Bomana_launcher_vX.X.X.exe` 并双击运行（绿色版，无需安装）
3. 选择功能通道后，启动器会检查并下载对应程序包

| 通道 | 包含什么 | 适合谁 |
|------|----------|--------|
| **Enhanced** | 计时 + 导航 + 燃油 + 武器参考 | 想要完整功能（推荐） |
| **Standard** | 计时 + 导航 + 燃油 | 不需要武器参考 |
| **Lite** | 仅计时 | 只要极简界面 |

补充说明：

- 首次通常需要联网下载程序包；之后可离线启动已下载版本
- 新版启动器会保留一个上一版本，出问题时可一键回退
- App 8.0.0 及以上需要启动器 3.0.0 及以上
- 程序显示名：`Bomana香焦`
- 也可从 [项目网站](https://thankyou-cheems.github.io/Bomana/) 进入下载

### 源码运行（可选）

若本机已有 Python / uv 环境，也可直接从源码启动。步骤见下方 [从源码运行](#从源码运行)。

---

## 快捷键

| 按键 | 作用 |
|------|------|
| `F7` | 手动重置计时（需短时间连按两次） |
| `F8` | 锁定 / 解锁窗口（锁定后点击穿透） |
| `F9` | 在四个屏幕角落间切换位置 |
| `F10` | 总提示音开关 |
| `F11` | 战区被摧毁提示音开关 |

快捷键可在设置中修改。画面叠加导航只能在设置里开关（默认关）。

游戏以管理员运行时，全局热键可能需要你在弹窗里手动授权一次；拒绝授权不影响计时、导航和窗口按钮，只是游戏前台时全局快捷键可能失效。

---

## 常见问题

### 窗口不显示或位置不对？

1. 确认游戏已进入战斗
2. 浏览器访问 `http://localhost:8111`，确认有数据
3. 仍异常时，重启游戏并重新进战斗
4. 按 `F9` 切换角落

### 计时不自动开始？

1. 确认已出生在战场
2. 确认上面的本机地址能打开
3. 稍等 1–2 秒让程序识别

### 如何用手机打开网页面板？

1. 手机和电脑连同一可信局域网（如同一 Wi‑Fi）
2. 在 Bomana 主窗口或托盘开启「局域网访问与控制」
3. 用主窗口显示的配对码 / 链接在手机浏览器打开
4. 若连不上，在 Windows 防火墙提示中允许 Bomana 的专用网络访问（程序不会自动改防火墙）

### 武器 / 投弹提示不准？

1. 在武器卡片上手动选对当前挂载
2. 提示仅为估算，受地图、风速、姿态等影响
3. 自由落体路径可在 `设置 → 投弹` 微调距离/时间倍率（只影响该路径）

### 和 WTRTI 有什么区别？

| | Bomana | WTRTI |
|--|--------|-------|
| 侧重点 | 全真收益计时 + 导航 / 武器参考 | 通用飞行数据展示 |
| 15 分钟计时 | 有 | 无 |
| 战区导航 / 武器参考 | 有（视通道） | 无 |
| 高度自定义仪表 | 无 | 有 |

两者可同时使用。

### 版本更新看哪里？

见 [docs/CHANGELOG.md](docs/CHANGELOG.md)。源码版本以 `bomana/metadata.py` 为准；已发布版本见页面顶部的 release 徽章。

---

## 隐私说明

启动器会收集**匿名**使用统计（如设备哈希、安装 ID、版本、通道、事件类型），用于改进产品和统计活跃度。

- 不收集姓名、邮箱、游戏账号、IP、战绩等
- 开源可审查；可按隐私政策禁用
- 完整说明：[docs/PRIVACY.md](docs/PRIVACY.md)

下载并运行本应用，即表示你知悉上述隐私政策。

---

## 许可证与免责声明

### 许可证

**MIT License** — Copyright (c) 2024-2026 Cheems

可自由使用、复制、修改、分发本软件；须保留版权与许可声明。全文见 [LICENSE](LICENSE)。

### 免责声明

**商标：** War Thunder® 及相关标识归 Gaijin Entertainment AG 所有。本软件为独立项目，与 Gaijin **无**关联、授权或赞助关系。

**使用风险：** 滥用或不当使用可能违反 [Gaijin 用户协议](https://legal.gaijin.net/termsofservice)。请自行确保用法合规。

**责任限制：** 本软件按「现状」提供，作者不对账号处罚、损失或其他后果负责。**风险自负。**

---

## 赞助支持

如果 Bomana 对你有帮助，欢迎微信赞助：

<img src="bomana/assets/branding/sponsor_wechat.png" width="200" alt="微信赞赏二维码">

---

# 开发者

面向贡献者、打包与维护：源码运行、目录、规格、构建与发布。

## 文档导航

| 文档 | 内容 |
|------|------|
| [docs/QUICKSTART.md](docs/QUICKSTART.md) | 玩家向快速上手 |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 代码结构、数据流、构建链路 |
| [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md) | `bd` 协作、提交与发布约定 |
| [docs/specs/](docs/specs/) | 规范正文（8111、签名、线程、配置变体、质量门禁等） |
| [docs/specs/version-compatibility.md](docs/specs/version-compatibility.md) | App 8 / Launcher 3 版本边界 |
| [docs/specs/web-dashboard.md](docs/specs/web-dashboard.md) | 网页驾驶舱边界与语义控制 |
| [docs/specs/release-signing.md](docs/specs/release-signing.md) | 发布签名与部署规则 |
| [docs/PRIVACY.md](docs/PRIVACY.md) | 匿名统计与 Web 本机/LAN 边界 |
| [docs/CHANGELOG.md](docs/CHANGELOG.md) | 版本变更 |
| [docs/PITFALLS.md](docs/PITFALLS.md) | 已知坑与排障 |
| [docs/guides/8111-session-recording.md](docs/guides/8111-session-recording.md) | 录制 8111 对局用于离线回放 |
| [docs/guides/web-cockpit-smoke.md](docs/guides/web-cockpit-smoke.md) | 网页驾驶舱人工冒烟 |
| [tests/README.md](tests/README.md) | 测试分层与规范映射 |
| [Agents.md](Agents.md) | Agent / 贡献者路由与质量门禁 |

---

## 从源码运行

### 环境

- Windows
- Python 3.14+（仓库 `.python-version` 默认 pin 3.14.5）
- [uv](https://docs.astral.sh/uv/getting-started/installation/)

### 依赖与启动

```powershell
uv sync --python 3.14.5
$env:BOMANA_SOURCE_DEVELOPMENT = "1"
uv run python Bomana.pyw
```

`BOMANA_SOURCE_DEVELOPMENT=1` 仅允许**非冻结源码开发**跳过启动器身份校验；打包 App 不接受该例外。App 8.0.0+ 运行时要求 Launcher 3.0.0+ 身份。

调试可选管理员热键时，可先构建开发用 Broker（产物在仓库内且通常被忽略）：

```powershell
uv run python tools/build_hotkey_broker.py --mode dev --output bomana/bin
```

---

## 项目目录结构

```text
.
├─ Bomana.pyw                 # App 入口（单实例 / DPI / 启动 UI）
├─ launcher.pyw               # 绿色版启动器
├─ bomana_version.py          # App / Launcher 共享版本边界
├─ bomana/
│  ├─ config/                 # 功能开关、设置、静态配置
│  ├─ core/                   # 状态、遥测、弹道、导航逻辑
│  ├─ data/                   # CCRP / 武器 / 限速等静态 JSON
│  ├─ assets/web/             # 网页驾驶舱前端
│  ├─ ui/                     # Tk 界面与 presenter
│  ├─ web/                    # 独立 HTTP 服务与语义控制
│  └─ utils/
├─ launcher/                  # 清单、下载缓存、安装事务
├─ native/hotkey_broker/      # 最小特权热键 Broker（Rust）
├─ tools/                     # 打包、datamine、发布部署
├─ tests/
└─ docs/
```

要点：

- 业务逻辑在 `bomana/`；`Bomana.pyw` 负责启动边界
- Launcher 与 Python App 以普通完整性运行；仅用户确认后，包内固定动作原生 Broker 才可提权
- 限速库：`bomana/data/fm_speed_limits.json`；炸弹参数：`bomana/data/ccrp_bomb_params.json`

---

## 高级配置

### 编译期功能开关

见 `bomana/config/feature_profile.py`：

```python
ENABLE_CCRP = True              # 武器 / 投弹参考
ENABLE_ZONES = True             # 战区导航
ENABLE_AIRFIELDS = True         # 机场导航
ENABLE_FUEL = True              # 燃油
ENABLE_CHECKLIST = True         # 出击检查清单
ENABLE_ADVANCED_SETTINGS = True # 高级设置
```

### 更新 datamine 静态数据

统一入口会刷新：

- `bomana/data/ccrp_bomb_params.json`
- `bomana/data/weapon_fire_control.json`
- `bomana/data/fm_speed_limits.json`
- 各 JSON `meta` 中的 datamine 来源版本 / commit

```bash
git clone https://github.com/gszabi99/War-Thunder-Datamine.git
git -C .\War-Thunder-Datamine pull --ff-only

uv run python tools/update_datamine_assets.py ^
  .\War-Thunder-Datamine ^
  --no-bomb-report
```

单项调试可直接调用 `tools/blkx_extractor.py`、`tools/fm_speed_extractor.py`、`tools/weapon_fire_control_extractor.py`。

超速分级实现会对照 [KaerMorh/WTSpeeder](https://github.com/KaerMorh/WTSpeeder) 交叉核验，但 Bomana 独立维护自己的 `fm_speed_limits.json`。

---

## 技术原理

### 运行时数据源（官方本机 HTTP）

| 端点 | 内容 |
|------|------|
| `/indicators` | 仪表（速度、油量、有效性等） |
| `/state` | 状态（空速、高度、垂直速度等） |
| `/map_obj.json` | 地图对象（战区、机场、玩家等） |
| `/map_info.json` | 地图元数据 |
| `/map.img` | 官方战术地图缩略图（App 低频有界读取） |

仅使用官方 8111 接口；边界见 [docs/specs/runtime-8111-boundary.md](docs/specs/runtime-8111-boundary.md)。

### 随包静态数据

| 文件 | 用途 |
|------|------|
| `ccrp_bomb_params.json` | 自由落体 / 高阻炸弹参数 |
| `weapon_fire_control.json` | 武器目录、挂载与条件表 |
| `fm_speed_limits.json` | 机型 IAS / Mach 限速 |

### 轮询

- 正常：约 50 ms（20 Hz）
- API 断线：约 1.25 s

### 网页驾驶舱数据流

- Bomana 是唯一的 8111 读取方；网页不代理 8111
- App 发布筛选后的快照、有界地图位图与 Tk 拥有的控制状态
- 敌方单位仅镜像当前 `/map_obj.json` 样本；不进桌面 HUD / 航向带
- 写入经会话 CSRF、幂等键与主线程再授权，仅固定语义动作
- 默认 `127.0.0.1:8777`；LAN 时绑定可用 RFC1918 地址，不用 `0.0.0.0`
- 完整规格：[docs/specs/web-dashboard.md](docs/specs/web-dashboard.md)

### 计时状态机（概要）

```
[等待] ──检测到玩家──→ [飞行中] ──速度<40km/h 持续约3秒──→ [已着陆]
   ↑                      │                              │
   │                      ↓                              │
   └───无玩家约1.2秒──[死亡/返回机库]←────约10秒后────────┘
```

---

## 构建与发布

### 本地打包

```text
tools\scripts\build_portable.bat <Enhanced|Standard|Lite> <all|app|launcher> [version]
tools\scripts\build_app_package.bat Enhanced|Standard|Lite
tools\scripts\build_launcher.bat [version]
```

- `version` 为一致性校验，须匹配源码版本；`all` 通常省略单一 `version`
- App 包内嵌最小热键 Broker 与 SHA256，无需单独安装器
- 发布构建须设置 `BOMANA_RELEASE_ED25519_PRIVATE_KEY`、`BOMANA_RELEASE_ED25519_PUBLIC_KEY`、`BOMANA_RELEASE_SIGNING_KEY_ID`（默认 `bomana-release-2026-06`）
- 未签名清单或不匹配公私钥会被拒绝

### GitHub Actions

| 触发 | 产物 |
|------|------|
| 标签 `vX.Y.Z` | 启动器 + 三通道 App |
| 标签 `vX.Y.Z-app` | 仅三通道 App |
| 标签 `vX.Y.Z-launcher` | 仅启动器 |
| `workflow_dispatch` | 可选 `all` / `app` / `launcher` |

构建使用 GitHub Artifact Attestations 记录来源；无需 Authenticode PFX。签名字段与信任边界见 [docs/specs/release-signing.md](docs/specs/release-signing.md)。

### 腾讯云 / EdgeOne 部署

**不要用 GitHub Actions 直连腾讯云主机部署。** 在本机：

```bash
gh secret list --repo Thankyou-Cheems/Bomana
gh release download vX.Y.Z --dir dist
uv run python tools/deploy_update_assets.py --target app|launcher|all --version X.Y.Z
```

公开端点验证必须走 `verify_release_manifest_signature`。

### 产物关系（开发者）

| 文件 | 作用 |
|------|------|
| `Bomana_launcher_vX.Y.Z.exe` | 固定入口：检查更新、下载校验、自更新、回退 |
| `launcher_manifest.json` | 启动器版本、文件名、SHA256、Ed25519 签名 |
| `Bomana_app_<Variant>_vX.Y.Z.zip` | 实际运行包 |
| `manifest_<Variant>.json` | App 版本、`min_launcher_version`、SHA256、签名 |
| `checksums_*.txt` | 完整性校验清单 |

---

## 参考资料

- [War Thunder 论坛：8111 工具讨论](https://forum.warthunder.com/t/tools-using-data-provided-on-port-8111/106664)
- [Stona_WT 官方回复（#16）](https://forum.warthunder.com/t/tools-using-data-provided-on-port-8111/106664/16)
- [Gaijin 用户协议](https://legal.gaijin.net/termsofservice)
- [WTRTI](https://mesofthorny.github.io/WTRTI/)
- [KaerMorh/WTSpeeder](https://github.com/KaerMorh/WTSpeeder)
- [War Thunder localhost:8111 文档](https://github.com/lucasvmx/WarThunder-localhost-documentation)

---

## 更新服务仓库

独立更新 / 统计服务（Docker / FastAPI）在：

- https://github.com/Thankyou-Cheems/bomana-worker  
- 路径：`services/bomana-update-service/`

本仓库维护主程序与启动器；部署与迭代文档以 `bomana-worker` 为准。  
本仓库生成带 Ed25519 `manifest_signature` 的清单；服务端不重新签名、不需要发布私钥。部署后用 `tools/deploy_update_assets.py` 校验公开接口签名。

---

*Made by 猹Cheems for the Space Monkeys community*
