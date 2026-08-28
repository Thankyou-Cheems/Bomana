# Bomana

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
