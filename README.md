# Bomana

War Thunder 飞行辅助：Lite 出击倒计时、Standard 官方战区 / 机场导航、机型限速、燃油估算、置顶导航窗和局域网手机配对。

[打开 Bomana](https://bomana.ruikang.wang/) · [在线启动器与 Bridge 下载](https://bomana.ruikang.wang/launcher/) · [飞行工具箱](https://bomana.ruikang.wang/calculator/)

本仓库是持续生成的公开源码发行树。Lite / Standard 的源码、基础运行时、参数、Bridge 和 Launcher 来自同一个维护入口，通过检查后同步到 `main`。请勿直接修改生成分支；公开贡献会先纳入维护源，再随下一次同步返回这里。历史提交、标签和 Releases 保留供查阅，当前下载以在线启动器为准。

Enhanced 解算器、地形和高级目标算法不在本仓库中。公开 Bridge 仅转发官方 8111 数据、管理本地资源和配对传输，不操作游戏，也不决定 Edition 权益。

使用 Node.js 22、pnpm 11.3.0、Go 1.25 和 PowerShell 7：

```pwsh
pnpm --dir frontend install --frozen-lockfile
pnpm --dir frontend check
go -C native/telemetry_gateway test ./...
go -C native/telemetry_gateway vet ./...
```

构建输出在 `frontend/dist/Lite`、`Standard` 和 `launcher`。本地构建使用公开的开发签名，不需要生产密钥；生产 Bridge 只信任正式签名资源。公开仓库 Actions 仅检查源码与构建，不发布正式安装包、不连接生产服务器。正式发布签名和打包由维护源统一管理，腾讯云部署在维护者本地执行。

Standard 手机端从电脑生成的二维码进入，同一 Wi-Fi 下无需账号；置顶导航窗需要桌面 Edge / Chrome 支持 Document Picture-in-Picture。浏览器被系统冻结时可能暂停，恢复后重连并恢复出击状态。燃油是机型初估与本次飞行测量，缺少 TAS 或稳定采样时降低可信度。

参见 [版本边界](docs/specs/public-editions.md)、[架构](docs/ARCHITECTURE.md)、[隐私](docs/PRIVACY.md)和 [MIT 许可证](LICENSE)。
