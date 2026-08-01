<div align="center">

<img src="bomana/assets/branding/app.png" width="180" alt="Bomana">

# Bomana

**War Thunder 全真模式计时与飞行辅助**

[![App](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fbomanaupdate.ruikang.wang%2Fapi%2Fv1%2Fversion%3Fchannel%3DStandard&query=%24.app_version&label=Standard&prefix=v&color=0ea5e9)](https://bomana.ruikang.wang/)
[![Launcher](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fbomanaupdate.ruikang.wang%2Fapi%2Fv1%2Flauncher&query=%24.launcher_version&label=launcher&prefix=v&color=6366f1)](https://bomana.ruikang.wang/)
[![Public License](https://img.shields.io/badge/public%20editions-MIT-22c55e)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.14%2B-eab308)](https://www.python.org/)

**[官网下载](https://bomana.ruikang.wang/)** ·
**[English](README.en.md)**

</div>

Bomana 是独立桌面程序，只读取 War Thunder 官方提供的本机
`localhost:8111` 数据。它不读游戏进程内存、不注入、不修改游戏文件，
也不替玩家操作游戏。

## 产品版本

| 版本 | 访问方式 | 功能 |
|---|---|---|
| **Standard** | 公开、MIT | 计时、导航、燃油、检查单、速度/超速提示 |
| **Lite** | 公开、MIT | 核心计时与最小界面 |
| **Lite 绿色版** | 公开、MIT、免启动器 | Lite 功能 + 内置 Python 运行库，解压即用 |
| **超级爆弹版**（通道 `Enhanced`） | CheemsPay 付费订阅 | Strike Prediction、离线地形与 Web Cockpit |

本仓库是完整的 Lite / Standard 公开发布闭包。超级爆弹版的差异化实现、
模型数据、专属测试和发布定义位于单独的私有闭包，不由本仓库构建或发布。

通用 Launcher 会保留稳定的 `Enhanced` 通道名。选择该通道时，它使用
CheemsPay 设备授权流程，不收集用户密码；本机只保存 Windows DPAPI 保护的
设备身份、会话与签名订阅收据。Lite / Standard 不联系 CheemsPay。

## 安装

1. 从 [Bomana 官网](https://bomana.ruikang.wang/) 下载 Windows Launcher。
2. 选择 Standard 或 Lite 可直接下载公开版本。
3. 选择超级爆弹版时，先在 Launcher 的「购买 / 试用」按钮打开 CheemsPay
   商品页（现有 1 年授权或 3 天试用），完成支付后再按提示登录并刷新订阅。
4. 启动 War Thunder 并进入战斗；机库通常没有完整的 8111 飞行数据。

Launcher 验证签名清单、SHA-256 与版本兼容性，并保留一个上一版本用于回退。

CheemsPay 商品、付款和权益状态始终以
<https://pay.ruikang.wang/> 的实际账户中心为准；Launcher 不保存密码或支付信息。

不想使用 Launcher 时，可从 GitHub Release 下载 `Bomana_Green_Lite_v8.7.0.zip`。
绿色版只包含 Lite 功能及完整 Python 运行库，解压后直接运行 `Bomana.exe`。
它会异步上报每日一次的匿名活跃事件；网络失败不会阻塞启动，也不会影响功能。

## 公开功能

### Standard

- 15 分钟收益周期计时，可配置 1–180 分钟
- 战区、机场和兴趣点导航
- 燃油消耗、返航余量与速度/超速提示
- 检查单、托盘控制、窗口锁定与全局热键
- 本机配置与状态恢复

### Lite

- 收益周期计时
- 最小窗口与基础托盘控制
- 不包含导航、燃油、Strike Prediction 或 Web Cockpit

## 数据与安全边界

公开 App 的游戏数据入口只有官方 8111 HTTP 端点：

- `/indicators`
- `/state`
- `/map_obj.json`
- `/map_info.json`

生产版不会读取进程内存。离线研究目录、采集脚本和实验数据不属于任何发布
输入；只有经过审查的静态数据才能进入私有订阅闭包。

订阅客户端只做访问判断。真正的付费 artifact 隔离还要求 Enhanced manifest
与下载服务验证短期 CheemsPay artifact grant；公开 URL 或仅客户端门禁均不合规。

## 从源码运行

需要 Windows、Python 3.14+ 与 [uv](https://docs.astral.sh/uv/)：

```powershell
uv sync --extra dev --frozen
uv run python Bomana.pyw
```

公开源码默认运行 Standard。

## 测试

```powershell
uv run --extra dev pytest
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
```

测试围绕公开 module interface、Launcher 安装/回退、签名清单和最终发布闭包，
不再维护与私有实现文件布局绑定的源码字符串断言。

## 构建

公开仓库只接受 Standard / Lite：

```powershell
uv run --frozen python tools/build_portable.py --variant Standard --target app
uv run --frozen python tools/build_portable.py --variant Lite --target app
uv run --frozen python tools/build_portable.py --variant Lite --target green
uv run --frozen python tools/build_portable.py --target launcher
```

签名 App manifest 需要：

- `BOMANA_RELEASE_ED25519_PRIVATE_KEY`
- `BOMANA_RELEASE_ED25519_PUBLIC_KEY`
- `BOMANA_RELEASE_SIGNING_KEY_ID`

Launcher 构建还需要公开的 CheemsPay 验签材料：

- `CHEEMSPAY_LICENSE_PUBLIC_KEY_DER_BASE64URL`
- `CHEEMSPAY_LICENSE_KEY_ID`

私钥不得写入仓库或日志。公开构建器会拒绝 `Enhanced`。

## 仓库结构

```text
bomana/
  core/                  # 计时、导航、遥测与公开状态机
  ui/                    # Standard / Lite 桌面界面
  editions.py            # 唯一 Edition Policy module
  release_closure.py     # 公开/订阅源码闭包分类
launcher/
  subscription_access.py # CheemsPay HTTP 与内存 adapters、收据校验
  subscription_store.py  # DPAPI 持久化
  subscription_workflow.py
docs/
  adr/                    # 当前架构决策
  specs/                  # 公开产品与订阅 seam 合同
tests/                    # 公开行为、artifact 与安全不变量
```

架构与迁移顺序见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) 和
[公开/私有版本迁移指南](docs/guides/public-private-edition-migration.md)。

## 许可证

本仓库当前 Lite / Standard 公开闭包使用 [MIT License](LICENSE)。超级爆弹版的
未来私有新增内容不属于本仓库的 MIT 授权范围。此前已按 MIT 获得的历史版本仍
保留当时授予的权利；重写官方 Git 历史不会撤销这些既有权利或删除外部副本。

War Thunder® 及相关标识归 Gaijin Entertainment AG 所有。Bomana 是独立项目，
与 Gaijin 无关联、授权或赞助关系。
