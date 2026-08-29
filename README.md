<div align="center">

<img src="frontend/src/generated/bomana-logo.svg" width="176" alt="Bomana 品牌标志">

# Bomana

**War Thunder 全真模式浏览器伴侣** · Browser Companion for Simulator Battles

[![App Web](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fbomana.ruikang.wang%2Fapp%2Fapp-release.json&query=%24.app_web_version&label=App%20Web&prefix=v&color=0ea5e9)](https://bomana.ruikang.wang/launcher/)
[![Bridge](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fbomana.ruikang.wang%2Fdownloads%2Fbridge-release.json&query=%24.bridge_version&label=Bridge&prefix=v&color=6366f1)](https://bomana.ruikang.wang/launcher/)
[![Public Editions](https://img.shields.io/badge/Lite%20%2B%20Standard-MIT-22c55e)](LICENSE)
[![Runtime](https://img.shields.io/badge/runtime-Browser%20%2B%20Windows-eab308)](https://bomana.ruikang.wang/launcher/)

**[在线 Launcher](https://bomana.ruikang.wang/launcher/)** ·
[GitHub Releases](https://github.com/Thankyou-Cheems/Bomana/releases) ·
[English](README.en.md)

</div>

---

Bomana 是面向 War Thunder 全真模式的浏览器 App。

- **Lite**：纯复活周期计时。
- **Standard**：官方战区与机场的基础导航、燃油与检查单。
- **Bridge**：Windows 本机只读 8111 网关与 Local Data Store。
- **Enhanced**：订阅 Edition；其战术情报、高程、机场模块和武器解算实现不在本公共仓库。

## 在线使用

1. 打开 <https://bomana.ruikang.wang/launcher/>。
2. 下载并运行 `BomanaBridge.exe`。
3. 在线 Launcher 发现 Bridge 后，选择 Lite 或 Standard。

旧 Python App、桌面 Launcher 与热键 Broker 已从当前源码树退役。它们仍保留在 Git 历史与既有 Release 中，不会被重写或删除。

## 开发

```powershell
cd frontend
pnpm install --frozen-lockfile
pnpm check

cd ..\native\telemetry_gateway
go test ./...
go vet ./...
```

生产运行时只使用官方 `localhost:8111` 数据，不读游戏内存、不注入、不修改游戏文件。

许可证：MIT。
