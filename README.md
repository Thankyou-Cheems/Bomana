<div align="center">

<img src="docs/assets/bomana-app.png" width="144" alt="Bomana 应用图标">

# Bomana

**War Thunder 全真模式浏览器伴侣** · Browser Companion for Simulator Battles

[![App Web](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fbomana.ruikang.wang%2Fapp%2Fapp-release.json&query=%24.app_web_version&label=App%20Web&prefix=v&color=0ea5e9)](https://bomana.ruikang.wang/launcher/)
[![Bridge](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fbomana.ruikang.wang%2Fdownloads%2Fbridge-release.json&query=%24.bridge_version&label=Bridge&prefix=v&color=6366f1)](https://bomana.ruikang.wang/launcher/)
[![Product DAU](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fbomanaupdate.ruikang.wang%2Fapi%2Fv1%2Fstats%2Fdaily&query=%24.metrics.dau_unique_device&label=product%20DAU&color=22c55e&cacheSeconds=300)](https://bomanaupdate.ruikang.wang/api/v1/stats/daily)
[![Public Editions](https://img.shields.io/badge/Lite%20%2B%20Standard-MIT-22c55e)](LICENSE)
[![Runtime](https://img.shields.io/badge/runtime-Browser%20%2B%20Windows-eab308)](https://bomana.ruikang.wang/launcher/)

**[在线 Launcher](https://bomana.ruikang.wang/launcher/)** ·
[GitHub Releases](https://github.com/Thankyou-Cheems/Bomana/releases) ·
[English](README.en.md)

</div>

---

Bomana 是面向 War Thunder 全真模式的独立第三方浏览器 App。War Thunder 是载具
对战电子游戏；文中的“炸弹 / 投弹 / CCRP”等词只指游戏内虚拟机制，与现实用途无关。

- **Lite**：纯复活周期计时。
- **Standard**：官方战区与机场的基础导航、燃油与检查单。
- **Bridge**：Windows 本机只读 8111 网关与 Local Data Store。
- **Enhanced**：订阅 Edition；其战术情报、高程、机场模块和武器解算实现不在本公共仓库。

## 在线使用

1. 打开 <https://bomana.ruikang.wang/launcher/>。
2. 下载并运行 `BomanaBridge.exe`。
3. 在线 Launcher 发现 Bridge 后，选择 Lite 或 Standard。

如果 Edge 曾拒绝“设备上的应用 / 本地网络访问”，Launcher 会显示专门的恢复教程，
不再误报 Bridge 未运行；也可运行
[`BomanaBridgeDiagnostics.exe`](https://bomana.ruikang.wang/downloads/BomanaBridgeDiagnostics.exe)
生成不含账号、配对凭据或 8111 原文的连接报告。右键 Bridge 的“连接手机…”属于公开
配对传输协议；Enhanced App、地形与解算实现仍不在本仓库。

旧 Python App、桌面 Launcher 与热键 Broker 已从当前源码树退役。它们仍保留在 Git 历史与既有 Release 中，不会被重写或删除。

## 匿名日活

新 Browser + Bridge 架构继续兼容产品日活统计。官网 Browser App 在 Edition 成功初始化后，
以尽力而为方式发送每天一次的匿名信号；同一浏览器在 Lite、Standard 与 Enhanced 之间
切换时，每个 UTC 日仍只计一次。Bridge 不参与日活上报，8111 数据、游戏状态、账号和
支付信息都不会进入日活服务。上方 Product DAU Badge 读取公开的迁移兼容聚合值，详细
边界见[隐私说明](docs/PRIVACY.md)。

## 使用边界与防误解

Bomana 不是游戏修改器，也不隶属于 Gaijin，未获其授权或赞助。生产运行时由 Bridge
只读转发 War Thunder 官方 `localhost:8111` 数据；Bomana 不读取游戏进程内存、不注入
代码、不修改游戏文件，也不替玩家按键或自动操作对局。

这只是技术边界说明，不构成官方授权或“永不处罚”的保证。请始终遵守
[Gaijin 用户协议](https://legal.gaijin.net/termsofservice)和所在服务器的规则，并自行判断
是否启用任何第三方工具。

## 开发

```powershell
cd frontend
pnpm install --frozen-lockfile
pnpm check

cd ..\native\telemetry_gateway
go test ./...
go vet ./...
```

许可证：MIT。
