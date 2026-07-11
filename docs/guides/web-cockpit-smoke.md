# 网页驾驶舱人工冒烟 | Web Cockpit Manual Smoke

本指南记录 `docs/specs/web-dashboard.md` 中无法由 CI 代替的真实环境检查。自动化测试覆盖协议、配对、Host/Origin、安全响应头、快照 schema、资源清单和监听器生命周期；真实手机、Windows Firewall、多网卡、打包产物与 War Thunder 实时对局必须分别人工验证。

This guide covers real-environment checks that CI cannot replace. Record each scenario as `PASS`, `FAIL`, or `N/A`, together with the app build, browser/device, network, selected port, and brief evidence.

## 准备 | Setup

- 使用普通权限运行 Bomana；不要为了网页驾驶舱启动管理员版本。
- 准备一台桌面浏览器，以及连接到同一可信局域网的真实手机。
- 打包检查使用真实 `Bomana_app_<Variant>_vX.Y.Z.zip`，不要用源码目录代替。
- 实时检查需启动 War Thunder 并进入一场能够产生 8111 数据的战斗。
- 如需检查端口，可在 PowerShell 中运行 `Get-NetTCPConnection -State Listen | Where-Object LocalPort -In 8777..8787`。

## 场景 | Scenarios

| ID | 人工步骤 | 预期结果 |
|----|----------|----------|
| WDB-M01 桌面浏览器 | 启动 Bomana，从托盘选择“网页驾驶舱 -> 打开本机页面”；再占用首选端口后重复一次。 | 浏览器通过带配对码的链接打开并跳转到无配对码地址；默认监听 `127.0.0.1:8777`，占用时只选择有限的相邻端口。页面、地图、缩放/平移/跟随与各卡片可用，浏览器控制台无错误。 |
| WDB-M02 真实手机 | 在托盘选择“允许局域网访问（本次运行）”，把自动复制的链接发到真实手机并打开；分别检查竖屏和横屏。 | 只绑定一个 RFC1918 地址，手机完成配对并持续刷新；地图是移动端主要信息入口，页面无横向溢出，关键计时/飞行/导航/告警无需桌面宽度也能读取。 |
| WDB-M03 Windows Firewall | 在 Windows Defender Firewall 中分别拒绝和允许该打包 App 的“专用网络”访问，再从手机连接。 | 拒绝时手机连接失败但本机页面仍可用；允许专用网络后手机可访问。Bomana 本身不新增规则、不触发 UAC，也不开放公用网络规则。 |
| WDB-M04 多网卡 | 在同时存在以太网/Wi-Fi/VPN/虚拟网卡的电脑上开启 LAN，并检查监听地址和托盘复制链接。 | Bomana 选择一个可用 RFC1918 IPv4，链接与监听地址一致；没有 `0.0.0.0` 或公网监听。若所选网卡并非手机所在网络，应记录为失败并附网络配置。 |
| WDB-M05 打包资源 | 分别从 Enhanced、Standard、Lite 的真实 App 包启动；断开外网后打开页面并查看浏览器 Network 面板。 | HTML/CSS/JS/SVG 全部从 Bomana 自身地址加载，无 CDN、远程字体、分析或上传请求；三个通道均可打开，功能卡片按该通道的 `ENABLE_*` 能力显示，无资源 404。 |
| WDB-M06 War Thunder 实时对局 | 进入真实战斗，观察出生、飞行、燃油变化、导航目标、武器/投弹提示、告警、坠毁与同局复活。 | 页面随 Bomana 主界面更新；地图只显示己机、战区、机场、POI 与 Trace back，不出现敌机标记或原始 8111 内容。8111 断开时页面进入诚实的不可用/待机状态而不显示陈旧数据。 |
| WDB-M07 当次运行与退出 | 开启 LAN 后先从托盘关闭，再重新开启；最后退出并重启 Bomana。 | 关闭 LAN 后手机入口失效而本机页保留；退出后本机和 LAN 端口都释放；重启后 LAN 默认为关闭，配对码和会话令牌已更换，旧手机会话不能读取新进程快照。 |

## 记录模板 | Result Record

```text
Build / commit:
Variant:
Desktop browser:
Phone / mobile browser:
Network / adapters:
Selected loopback and LAN address:
WDB-M01..M07 results:
Evidence / notes:
```

发布交接必须分别写明哪些场景已实际执行；自动化测试通过、桌面响应式模拟器或源码预览均不能代替真实手机、Windows Firewall、打包产物和 War Thunder 对局检查。
