<div align="center">

<img src="bomana/assets/branding/app.png" width="200" alt="Bomana">

# Bomana

**战雷全真模式收益计时器** · War Thunder SB Timer

War Thunder 是一款载具对战电子游戏；Bomana 是面向全真模式的多功能计时器。<br>
文中的「炸弹 / 投弹 / CCRP」等均指**游戏内虚拟概念**，与现实无关。祝你玩得开心！

War Thunder is a vehicle-combat video game; Bomana is a multifunction timer for simulator battles.<br>
Terms like “bomb / bombing / CCRP” here mean **in-game virtual concepts only**, not anything in the real world. Have fun!

<!-- Versions from EdgeOne CDN (what players actually get). GitHub "latest" is often a launcher-only tag. -->
[![App](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fbomanaupdate.ruikang.wang%2Fapi%2Fv1%2Fversion%3Fchannel%3DEnhanced&query=%24.app_version&label=app&prefix=v&color=0ea5e9)](https://bomana.ruikang.wang/)
[![Launcher](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fbomanaupdate.ruikang.wang%2Fapi%2Fv1%2Flauncher&query=%24.launcher_version&label=launcher&prefix=v&color=6366f1)](https://bomana.ruikang.wang/)
[![License](https://img.shields.io/badge/license-MIT-22c55e)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.14%2B-eab308)](https://www.python.org/)
[![DAU](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fbomanaupdate.ruikang.wang%2Fapi%2Fv1%2Fstats%2Fdaily&query=%24.metrics.dau_unique_device&label=DAU&color=22c55e)](https://bomanaupdate.ruikang.wang/api/v1/stats/daily)
[![Launches](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fbomanaupdate.ruikang.wang%2Fapi%2Fv1%2Fstats%2Fdaily&query=%24.metrics.launcher_start_total&label=launches&color=3b82f6)](https://bomanaupdate.ruikang.wang/api/v1/stats/daily)

**[官网 / CDN 下载](https://bomana.ruikang.wang/)** ·
[GitHub Pages](https://thankyou-cheems.github.io/Bomana/) ·
[Releases 备用](https://github.com/Thankyou-Cheems/Bomana/releases)

**[中文文档](#中文文档)** · **[English](README.en.md)**

</div>

---

# 中文文档

## 目录

### 普通用户

- [当前实现与使用提醒](#当前实现与使用提醒)
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
- [Windows 集成与热键 Broker](#windows-集成与热键-broker)
- [构建与发布](#构建与发布)
- [参考资料](#参考资料)
- [更新服务仓库](#更新服务仓库)

---

# 普通用户

面向日常游玩：如何下载、怎么用、有哪些功能。尽量少用术语。

## 当前实现与使用提醒

### 当前实现

当前版本的 Bomana **不会**读游戏内存、注入代码、改游戏文件，也**不会**替你按游戏里的键或自动操作对局。
它在自己的窗口 / 网页里读取游戏当前提供的本机数据，帮你计时和做参考。

### 官方怎么说

社区经理 **Stona_WT** 在 2024 年 5 月 13 日的[官方回复](https://forum.warthunder.com/t/tools-using-data-provided-on-port-8111/106664/16)中大致表示：

- 用游戏本机提供的数据显示飞行信息、覆盖层，一般可以，不会因此直接封禁。
- 但在无标记模式下，把敌人位置做成罗盘式叠加层、获得相对其他玩家的优势，官方**不认可**，可能被视为不当辅助。

### 允许 / 不认可 / 请自行判断

| 做法 | 态度 |
|------|------|
| 显示自己的速度、高度、油量、收益计时 | 官方表态偏允许 |
| 用本机公开数据做导航、燃油、超速等参考 | 官方表态偏允许（同类工具如 WTRTI 亦属此类） |
| 在无标记模式把敌人画进**游戏画面式**罗盘 / HUD 叠层 | **不认可** |
| 在**独立网页地图**里，仅镜像当前官方本机数据里已经返回的敌方单位 | **官方未明确表态**，请自行判断是否使用 |
| 读内存、注入、改客户端文件、宏连点、替你操作游戏 | 当前 Bomana 版本未提供 |

### Bomana 实际怎么做（玩家可读版）

| 项目 | 说明 |
|------|------|
| 数据从哪来 | 当前版本读取游戏在本机开放的信息页（浏览器也可打开 `http://localhost:8111` 核对），并使用随包的版本化静态数据。 |
| 和游戏进程的关系 | Bomana 是**独立程序**、独立窗口；不嵌进游戏、不注入 DLL、不改游戏文件。 |
| 热键做什么 | F6–F11 只控制 **Bomana 自己**（目标来源、重置计时、锁窗、角落、声音）。**不会**往游戏里模拟按键。 |
| 游戏前台热键 | 使用 Windows `RegisterHotKey`；不会为判断权限而枚举或打开游戏进程，也不会自动弹 UAC。若权限边界导致热键失效，可直接使用投弹栏、主窗或托盘按钮。 |
| 桌面显示 | 主窗、独立导航栏与独立 CCRP 提示栏；不提供全屏游戏画面 HUD。 |
| 网页地图上的敌方 | 若出现，只来自当前这一帧官方本机地图数据；断线或下一帧没有就去掉。**不**根据历史推轨迹，也**不**补齐未见过的目标。 |
| 网页按钮 | 只改 Bomana（计时、角落、声音、面板、可选武器设置等），**不**遥控游戏客户端。 |

### 你需要知道的

1. **“技术上安全的实现”≠“官方书面担保永不处罚”**。请自行遵守用户协议与对局规则。  
2. 若你希望更保守：可不开启网页局域网，也可不使用网页地图上的敌方显示相关能力。
**请你自行了解规则，并为自己的使用方式负责。**

---

## 功能介绍

### 15 分钟收益计时

全真模式每次出生后有约 15 分钟收益周期。Bomana 会：

- 自动识别出生、着陆、阵亡并开始/重置计时
- 显示当前是第几条命
- 程序重启后尽量接着计
- 临近结束时用语音或提示音提醒

### 武器投放参考

超级爆弹版提供自由落体炸弹与其他受支持武器的投放参考。自由落体解算只组合官方 8111 飞行数据、用户手选武器的离线参数和启动器维护的离线高程图。

请注意：

- 投弹栏可在主窗中集成显示，也可单独分离；若导航栏也处于独立模式，投弹栏会挂在导航栏下方
- 点击蓝色弹药文本框即可选择当前机型已确认兼容的炸弹；程序不会读取或猜测游戏挂载
- `F6` 或栏内按钮显式切换“战区 / 兴趣点”目标来源，重合时不会再由程序自动猜目标类型
- 目标、高程和释放状态合并在标题区，默认 CCRP 卡片更紧凑；对称收束指示器随预计释放时间平滑内收，到点闪绿，越点后显示红色越界线
- 所有结果仍是外部参考，不代表游戏内部投弹计算或投放许可

### 战区与机场导航

- 图形化航向、距离、预计到达时间
- 航向带内置非线性精确对准区：接近目标时直接显示左右偏差、捕获门与平滑游标，不再占用两行额外提示
- 对准目标一段时间后可自动锁定
- 返航机场方向与距离；友方 / 敌方机场继续保留在主刻度上，避免精确对准时丢失全局方位
- 同一战局复活后，可提示上次损失位置方向

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
| 主题与热键 | 明暗主题；F6–F11 可改 |
| 系统托盘 | 可最小化到托盘 |
| 独立文字大小 | 只放大字，不硬撑整窗 |
| 自定义提示音 | 可按类别导入本地音频 |

### 手机 / 本机网页面板

可在电脑浏览器或同一可信局域网的手机上查看计时、地图、油量、导航等信息，并操作部分 **Bomana 自身**功能（如重置计时、切换角落、开关声音等）。

- 默认先本机可用；要给手机用时，在程序里开启「局域网访问与控制」
- 开启局域网后，之后配对的设备可控制这些固定功能；关闭后立即失效全部局域网会话
- 网页**不会**代替你按游戏热键，也**不会**操控游戏客户端
- 网页地图若显示敌方单位，仅镜像当前官方本机数据；是否使用请结合上方合规说明自行判断

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
| **超级爆弹版**（内部通道 `Enhanced`） | 深度学习的高精度打击模型与地形数据 | 需要最高投弹预测精度与离线地形参考 |
| **Standard** | 计时 + 导航 + 燃油（无武器参考、无网页驾驶舱） | 不需要武器参考与网页控制台 |
| **Lite** | 仅计时（无网页驾驶舱） | 只要极简界面 |

Standard / Lite **不会打包**网页驾驶舱代码；若启动器勾选了网页相关选项，启动时会提示并忽略这些选项（偏好仍可保存，切回超级爆弹版后生效）。

补充说明：

- 首次通常需要联网下载程序包；之后可离线启动已下载版本
- 新版启动器会保留一个上一版本，出问题时可一键回退
- 当前 App 8.6.2 需要启动器 3.3.0 及以上
- 超级爆弹版的地形数据由启动器单独维护；启动器直接显示当前地图包状态、地图数量与修订号，版本未变化时零下载，变化时只下载改变的地图对象
- 程序显示名：`Bomana香焦`
- 也可从 [Bomana 官网](https://bomana.ruikang.wang/)（国内 CDN）或 [GitHub Pages](https://thankyou-cheems.github.io/Bomana/) 进入下载；旧的 `/bomana` 地址只作为兼容重定向保留

### 源码运行（可选）

若本机已有 Python / uv 环境，也可直接从源码启动。步骤见下方 [从源码运行](#从源码运行)。

---

## 快捷键

| 按键 | 作用 |
|------|------|
| `F6` | 切换投弹目标来源：战区 / 兴趣点 |
| `F7` | 手动重置计时（需短时间连按两次） |
| `F8` | 锁定 / 解锁窗口（锁定后点击穿透） |
| `F9` | 在四个屏幕角落间切换位置 |
| `F10` | 总提示音开关 |
| `F11` | 战区被摧毁提示音开关 |

快捷键可在设置中修改。

**关于「管理员热键」：**

- Bomana 与启动器始终以普通权限运行，启动时只注册 Windows 系统热键，**不会自动弹 UAC**。
- 当前 App 不枚举游戏窗口、不打开游戏进程，也不查询游戏进程权限来决定是否显示热键提示。
- 若游戏以前台高权限运行导致 F6–F11 失效，请使用投弹栏、主窗或托盘里的等价按钮；计时、导航与官方 8111 数据不受影响。

---

## 常见问题

### 会不会读内存、注入或替我操作游戏？

当前版本不会。界面是独立窗口；快捷键和网页按钮只改 Bomana 自己。当前实现不读内存、不注入、不改游戏文件、不做宏、不模拟游戏按键。

### 会不会被当成作弊？

- 计时、己方飞行数据、导航参考等，与官方曾表态「可用本机数据显示覆盖层」的方向一致。  
- **不**提供把敌人画进游戏式 HUD / 罗盘叠层的能力。  
- 独立网页地图上的敌方显示属于**官方未明确表态**的灰区，请自行决定是否使用。  
- 任何第三方工具都无法保证「永不处罚」。请以用户协议与自身风险判断为准。

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

### 武器 / CCRP 提示不准？

1. 点击 CCRP 内的蓝色弹药框，手动选对当前挂载
2. 提示仅为估算；大坡度侧飞或明显转弯时会暂时停止，陡俯冲或拉起仍会继续计算
3. 若显示“等待目标高程”，请确认超级爆弹版的独立地形数据已经安装完成

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

`BOMANA_SOURCE_DEVELOPMENT=1` 仅允许**非冻结源码开发**跳过启动器身份校验；打包 App 不接受该例外。协议基线仍为 Launcher 3.0.0+，当前 App 8.6.2 会在加载业务模块前强制要求 Launcher 3.3.0+；旧启动器也会依据签名清单在下载前阻止本次 App 更新。

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
│  ├─ data/                   # CCRP / 武器 / 限速等静态资产
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
- 限速库：`bomana/data/fm_speed_limits.json`；离线刚体目录：`bomana/data/offline_rigidbody_catalog.bin`；公开曲线窄域参考：`bomana/data/visible_trajectory_references.json`

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

- `bomana/data/offline_rigidbody_catalog.bin`
- `bomana/data/weapon_fire_control.json`
- `bomana/data/fm_speed_limits.json`
- 武器与限速 JSON `meta` 中的 datamine 来源版本 / commit

`visible_trajectory_references.json` 不由 datamine 更新器生成；它只保存带游戏版本、输入条件和显示精度的玩家可见 UI 数值转录。
离线刚体目录采用确定性压缩容器和 SHA-256 完整性校验，不携带逐条文件路径、网格名或生成提交元数据。

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
| `/map_obj.json` | 地图对象（战区、机场、玩家、当前样本中的单位等） |
| `/map_info.json` | 地图元数据 |
| `/map.img` | 官方战术地图缩略图（App 低频、有界、类型校验） |
| `/icons.ttf` | 官方战术图标字体（有界、一次性/低频，签名校验） |

- 基址固定：`http://127.0.0.1:8111`（或等价 localhost）
- JSON 拉取当前集中在 `bomana/core/telemetry.py`

### 随包静态数据

| 文件 | 用途 |
|------|------|
| `offline_rigidbody_catalog.bin` | CCRP 离线刚体目录（压缩且完整性校验） |
| `weapon_fire_control.json` | 武器目录、挂载与条件表 |
| `visible_trajectory_references.json` | 带条件的玩家可见曲线参考（非最大包线） |
| `fm_speed_limits.json` | 机型 IAS / Mach 限速 |

武器、炸弹与限速库来自公开 datamine 的**构建期**提取；可见曲线文件是公开 UI 数值的本地转录。运行时只读随包静态资产，不在对局中打开游戏安装目录或解密客户端包。

### 轮询

- 正常：约 50 ms（20 Hz）
- API 断线：约 1.25 s

### 网页驾驶舱数据流

- Bomana 是唯一的 8111 读取方；网页**不**代理、不转发任何 8111 路由
- App 发布筛选后的快照、有界地图位图与 Tk 拥有的控制状态
- 敌方单位仅镜像当前 `/map_obj.json` 样本；不进入独立导航栏或 CCRP 提示栏
- 写入经会话 CSRF、幂等键与主线程再授权，仅固定语义动作（见 `bomana/web/control.py` 白名单）
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

## Windows 集成与热键 Broker

本节记录当前版本的窗口与可选热键实现；它不再定义 8111-only 数据源安全边界。

### 架构隔离

```text
War Thunder  ──本机 HTTP :8111──►  Bomana App（普通完整性）
                                            ├─ 独立 Tk 面板窗口（非游戏子窗口）
                                            ├─ 可选 Web 驾驶舱（独立端口，不代理 8111）
                                            └─ 可选 Hotkey Broker（用户确认 UAC 后）
                                                 └─ 命名管道：仅 Bomana 动作 ID
```

| 边界 | 实现要点 |
|------|----------|
| 窗口 | 独立置顶分层窗；不 `SetParent` 进游戏 HWND |
| 热键 | `RegisterHotKey` → 回调只改 Bomana；Broker 同样只 `RegisterHotKey`，无键盘钩子 / 轮询 |

### 不探测游戏进程

App 直接注册普通权限的 Windows 系统热键，不枚举游戏窗口或进程，不查询游戏可执行文件名、令牌、模块或内存，也不会因为游戏状态自动请求 UAC。规范：`docs/specs/startup-elevation.md`。

### 可选热键 Broker

| 项 | 约束 |
|----|------|
| 何时出现 | 用户点击并确认后才可能 `runas`；启动从不自动 UAC |
| 路径 | 仅包内 `bomana/bin/BomanaHotkeyBroker.exe` + 旁路 SHA256 |
| 动作 | 固定：`bomb_target` / `reset` / `lock` / `corner` / `beep` / 可选 `zones`；键位限 F1–F12 |
| IPC | 本机命名管道，帧内仅状态与动作 ID |
| 对 App 进程 | 可用 `SYNCHRONIZE \| PROCESS_QUERY_LIMITED_INFORMATION` 等待退出——目标是 **Bomana**，不是游戏 |
| 不做的事 | 不钩键盘、不查游戏、不联网、不装服务/计划任务/开机项 |

### 相关合同测试

```bash
uv run --extra dev python -m pytest ^
  tests/contracts/test_startup_elevation_contract.py ^
  tests/contracts/test_web_dashboard_contract.py -q
```

| 测试 | 覆盖 |
|------|------|
| `test_startup_elevation_contract` | 普通完整性、探测收窄、Broker 路径/哈希/禁止项 |
| `test_web_dashboard_contract` | 不代理 8111、语义命令矩阵、禁止输入合成 |

开发工具注意：`tools/` 下 datamine / 会话录制 / 打包 smoke（含 `keybd_event` 的 PowerShell）**不进入**玩家对局运行时；录制默认本机 `recordings/` 且不上传。

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
- 三种 App ZIP 都不再携带地形包；启动器只为 `Enhanced` 单独安装、校验并维护 `terrain-v1`
- 地形对象按 SHA256 内容寻址；更新时复用未变化地图并原子切换，普通 App 发布不包含也不上传这约 118 MB 数据
- 发布构建须设置 `BOMANA_RELEASE_ED25519_PRIVATE_KEY`、`BOMANA_RELEASE_ED25519_PUBLIC_KEY`、`BOMANA_RELEASE_SIGNING_KEY_ID`（默认 `bomana-release-2026-06`）
- 未签名清单或不匹配公私钥会被拒绝

### GitHub Actions

| 触发 | 产物 |
|------|------|
| 标签 `vX.Y.Z` | 启动器 + 三通道 App |
| 标签 `vX.Y.Z-app` | 仅三通道 App |
| 标签 `vX.Y.Z-launcher` | 仅启动器 |
| `workflow_dispatch` | 可选 `all` / `app` / `launcher` |
| 手动运行 `build-terrain.yml` | 独立签名地形清单与内容寻址对象（不设自动触发） |

构建使用 GitHub Artifact Attestations 记录来源；无需 Authenticode PFX。签名字段与信任边界见 [docs/specs/release-signing.md](docs/specs/release-signing.md)。

### 腾讯云 / EdgeOne 部署

**不要用 GitHub Actions 直连腾讯云主机部署。** 在本机：

```bash
gh secret list --repo Thankyou-Cheems/Bomana
gh release download vX.Y.Z --dir dist
uv run python tools/deploy_update_assets.py --target app|launcher|all --version X.Y.Z
# 仅当地形数据确实变化时：
uv run python tools/deploy_update_assets.py --target terrain
```

公开端点验证必须走 `verify_release_manifest_signature`。

### 产物关系（开发者）

| 文件 | 作用 |
|------|------|
| `Bomana_launcher_vX.Y.Z.exe` | 固定入口：检查更新、下载校验、自更新、回退 |
| `launcher_manifest.json` | 启动器版本、文件名、SHA256、Ed25519 签名 |
| `Bomana_app_<Variant>_vX.Y.Z.zip` | 实际运行包 |
| `manifest_<Variant>.json` | App 版本、`min_launcher_version`、SHA256、签名 |
| `terrain-release/terrain_manifest.json` | 独立地形版本、逐文件 SHA256、大小与 Ed25519 签名 |
| `terrain-release/objects/*` | 按内容哈希命名的地图/元数据对象，只下载变化部分 |
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
