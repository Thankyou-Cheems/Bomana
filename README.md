<div align="center">

<img src="bomana/assets/branding/app.png" width="200" alt="Bomana">

# Bomana

**战雷全真模式收益计时器** · War Thunder SB Timer

War Thunder 是一款载具对战电子游戏；Bomana 是面向全真模式的独立桌面工具，
帮助玩家管理收益计时、航行信息和出击准备。文中的「炸弹 / 投弹」等词均指游戏
内虚拟内容，与现实无关。

[![App](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fbomanaupdate.ruikang.wang%2Fapi%2Fv1%2Fversion%3Fchannel%3DStandard&query=%24.app_version&label=Standard&prefix=v&color=0ea5e9)](https://bomana.ruikang.wang/)
[![Launcher](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fbomanaupdate.ruikang.wang%2Fapi%2Fv1%2Flauncher&query=%24.launcher_version&label=launcher&prefix=v&color=6366f1)](https://bomana.ruikang.wang/)
[![Public License](https://img.shields.io/badge/public%20editions-MIT-22c55e)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.14%2B-eab308)](https://www.python.org/)

**[官网 / 下载](https://bomana.ruikang.wang/)** ·
[GitHub Releases](https://github.com/Thankyou-Cheems/Bomana/releases) ·
[English](README.en.md)

</div>

---

## 合规性声明

Bomana 是独立程序，不是游戏修改器。运行时只读取 War Thunder 在本机提供的
`localhost:8111` 信息，用自己的窗口显示计时和参考信息。它不会读取游戏进程内存、
注入代码、修改游戏文件，也不会替玩家按键或自动操作对局。

这只是实现边界说明，不构成任何官方授权或“永不处罚”的保证。请始终遵守
[Gaijin 用户协议](https://legal.gaijin.net/termsofservice)和所在服务器的规则，
并自行判断是否启用任何第三方工具。

## 功能特性

### Standard 标准版

- 15 分钟收益周期计时，可配置计时长度
- 战区、机场和兴趣点导航
- 燃油消耗、返航余量与速度提示
- 出击检查单、托盘控制、窗口锁定和全局热键
- 本机配置与状态恢复

### Lite 轻量版

- 核心收益计时
- 最小窗口和基础托盘控制
- 适合只需要计时功能的玩家

### 超级爆弹版

超级爆弹版是面向订阅用户的独立版本，在公开版之外提供额外的进阶功能和专属
内容。它通过启动器和官网按订阅状态提供，具体能力以官网及当前版本说明为准；
相关实现、数据和发布包不在本公开仓库中。

## 下载与使用

### 使用前

1. 系统：Windows。
2. 启动 War Thunder 并进入战斗；机库状态通常没有完整的飞行数据。
3. 不需要额外的安装器。进入战斗后，Bomana 会读取游戏提供的本机信息。

### 推荐：使用启动器

1. 从 [Bomana 官网](https://bomana.ruikang.wang/)或 [GitHub Releases](https://github.com/Thankyou-Cheems/Bomana/releases)
   下载 Windows 启动器。
2. 启动器会检查版本、校验下载文件并按通道安装应用。
3. 选择需要的版本：

| 通道 | 访问方式 | 适合谁 |
|---|---|---|
| **Standard** | 公开、MIT | 需要计时、导航和燃油信息 |
| **Lite** | 公开、MIT | 只需要极简计时 |
| **Lite 绿色版** | 公开、免启动器 | 想解压即用、无需单独安装 Python |
| **超级爆弹版** | 付费订阅 | 需要公开版之外的订阅功能 |

选择超级爆弹版时，按启动器提示打开官网完成购买或试用，再返回启动器刷新订阅
状态。公开仓库只发布 Lite、Standard 和 Lite 绿色版，不提供订阅版下载地址。

启动器会保留一个上一版本，更新失败时可以回退。绿色版已经内置 Python 运行库，
解压后即可运行 `Bomana.exe`；它会异步上报每日一次的匿名活跃事件，网络失败不会
阻塞启动，也不会影响使用。

## 快捷键

| 按键 | 作用 |
|---|---|
| `F7` | 手动重置计时（需短时间连续按两次） |
| `F8` | 锁定 / 解锁窗口 |
| `F9` | 在四个屏幕角落间切换位置 |
| `F10` | 总提示音开关 |
| `F11` | 战区提示音开关 |

快捷键可在设置中修改。它们只控制 Bomana 自己，不会向游戏发送按键。

## 常见问题

### 窗口不显示或数据为空怎么办？

确认游戏已经进入战斗，然后在浏览器打开 `http://localhost:8111`。如果页面没有
有效数据，请重新进入战斗或稍等片刻；机库状态通常无法提供飞行信息。

### Bomana 会读内存、注入或自动操作游戏吗？

不会。公开版本使用独立窗口和官方本机 HTTP 数据，不读取进程内存、不注入、不改
客户端文件，也不模拟游戏按键。任何第三方工具都无法替用户承担账号和对局风险。

### 如何选择版本？

Standard 适合需要导航、燃油和更多桌面辅助的玩家；Lite 只保留计时和最小界面；
Lite 绿色版与 Lite 功能相同，但自带 Python 运行库且无需启动器。超级爆弹版是另
行的付费订阅版本，订阅内容以官网展示为准。

### 和 WTRTI 有什么区别？

Bomana 侧重全真模式收益计时和简单的航行参考；WTRTI 侧重通用飞行数据展示。
两者可以同时使用，具体请以各自项目的规则和功能说明为准。

## 隐私说明

启动器和绿色版可能上报匿名使用统计（设备哈希、安装标识、版本、通道和事件类型），
用于更新服务和活跃度统计。不收集姓名、邮箱、游戏账号、战绩或支付信息。完整说明
见 [隐私政策](docs/PRIVACY.md)。网络不可用时，统计上报会静默失败，不影响启动。

## 许可证与免责声明

Lite、Standard 及绿色版的公开源码闭包使用 [MIT License](LICENSE)。超级爆弹版的
新增实现、数据和发布包属于独立的订阅闭包，不随本仓库发布。

War Thunder® 及相关标识归 Gaijin Entertainment AG 所有。Bomana 是独立项目，
与 Gaijin 无关联、授权或赞助关系。软件按“现状”提供，使用风险由用户自行承担。

## 赞助支持

如果 Bomana 对你有帮助，欢迎微信赞助支持开发：

<img src="bomana/assets/branding/sponsor_wechat.png" width="200" alt="微信赞赏二维码">

---

# 开发者

## 文档导航

| 文档 | 内容 |
|---|---|
| [docs/QUICKSTART.md](docs/QUICKSTART.md) | 玩家向快速上手 |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 代码结构、数据流与构建链路 |
| [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md) | 协作、提交与发布约定 |
| [docs/PRIVACY.md](docs/PRIVACY.md) | 匿名统计和隐私边界 |
| [docs/CHANGELOG.md](docs/CHANGELOG.md) | 版本变更记录 |
| [docs/PITFALLS.md](docs/PITFALLS.md) | 已知问题与排障 |
| [tests/README.md](tests/README.md) | 测试分层与规范映射 |

## 从源码运行

需要 Windows、Python 3.14+ 和 [uv](https://docs.astral.sh/uv/)：

```powershell
uv sync --extra dev --frozen
uv run python Bomana.pyw
```

公开源码默认运行 Standard。源码开发和测试命令见 [CONTRIBUTING.md](docs/CONTRIBUTING.md)。

## 项目目录结构

```text
.
├─ Bomana.pyw                 # App 入口
├─ launcher.pyw               # 绿色版启动器
├─ bomana/                    # 计时、导航、状态和 UI
├─ launcher/                  # 清单、下载缓存和安装事务
├─ tools/                     # 构建与发布工具
├─ tests/                     # 公开行为与发布合同测试
└─ docs/                      # 玩家文档与维护规范
```

## 构建与发布

公开构建只接受 Lite、Standard 和 Lite 绿色版：

```powershell
uv run --frozen python tools/build_portable.py --variant Standard --target app
uv run --frozen python tools/build_portable.py --variant Lite --target app
uv run --frozen python tools/build_portable.py --variant Lite --target green
uv run --frozen python tools/build_portable.py --target launcher
```

发布清单使用 Ed25519 签名，私钥不得写入仓库或日志。超级爆弹版由独立私有发布闭包
维护，公开 CI 不构建也不上传该版本。

## 更新服务仓库

独立更新 / 统计服务（Docker / FastAPI）在
[Thankyou-Cheems/bomana-worker](https://github.com/Thankyou-Cheems/bomana-worker)。
本仓库维护主程序与启动器；部署说明以更新服务仓库为准。

---

*Made by 猹Cheems for the Space Monkeys community*
