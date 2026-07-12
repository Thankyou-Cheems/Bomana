# 网页驾驶舱人工冒烟 | Web Cockpit Manual Smoke

本指南记录 `docs/specs/web-dashboard.md`、`docs/specs/version-compatibility.md`
中无法由 CI 代替的真实环境检查。自动化测试覆盖协议、schema、配对、
Host/Origin/CSRF、幂等、版本拒绝和监听器生命周期；真实手机、Windows
Firewall、多网卡、打包资源、Launcher DPI/键盘与 War Thunder 实时同步必须
分别人工验证。

This guide covers real-environment checks that CI cannot replace. Record every
scenario as `PASS`, `FAIL`, or `N/A`, with the exact App/Launcher build,
browser/device, network, selected port, and brief evidence. A green automated
suite is not evidence that any scenario below was performed.

## 准备 | Setup

- 使用普通权限运行 Launcher 和 Bomana；网页驾驶舱不需要管理员权限。
- 准备两个相互隔离的桌面浏览器 profile，以及连接到同一可信局域网的真实
  手机。不要在记录中保存配对码、Cookie、CSRF 或幂等键。
- 打包检查使用真实 Launcher `3.1.0` 与
  `Bomana_app_<Variant>_v8.4.0.zip`，不要用源码目录代替。
- 如需源码对照，使用当前 PowerShell 进程内的显式开发标记：

  ```powershell
  $env:BOMANA_SOURCE_DEVELOPMENT = "1"
  uv run python Bomana.pyw
  ```

- 实时检查需启动 War Thunder 并进入一场能够产生 8111 数据的战斗。
- 如需检查端口，可在 PowerShell 中运行：

  ```powershell
  Get-NetTCPConnection -State Listen | Where-Object LocalPort -In 8777..8787
  ```

- 兼容性破坏测试只能在隔离的临时 Launcher 目录中执行；不要拿真实用户的
  `app/`、`app_previous/` 或 Launcher 状态做破坏性试验。

## 场景 | Scenarios

### WDB-M01 本机页面与独立会话 | Loopback page and distinct sessions

1. 保持 Launcher 的“随 App 启动本机 Web 服务”开启、“自动打开本机页面”
   关闭，启动 App；确认主窗口底部显示配对码与本机地址，再选择“打开”。
2. 在两个隔离浏览器 profile 中分别使用当前配对链接完成配对。
3. 占用首选端口后重启并重复一次。

预期：页面通过带配对码的 URL 完成配对后跳转到无配对码地址；两个 profile
得到不同的 HttpOnly 会话 Cookie，并都显示“本机控制”。默认监听
`127.0.0.1:8777`，占用时只选择有限的相邻端口。地图、缩放/平移/跟随、
状态卡与控制区可用，浏览器控制台无错误。

### WDB-M02 本机语义控制与异步完成 | Local semantic controls

在本机会话依次验证以下完整 allowlist，并同时观察桌面 App 与持久化结果：

- 确认后立即重置计时一次；
- 切换到下一个窗口角落；
- 显式设定窗口锁定/解除、提示音开/关、战区提示音开/关；
- 显式显示/隐藏战区、机场、燃油、速度、检查清单、武器解算面板；
- 在支持的通道选择当前目录武器，并显式切换“缺少官方数据时使用推测替代”
  与“缺少官方数据时不应用模型”；验证官方包线在两种策略下都保持官方来源。

预期：浏览器首先显示“已排队”，随后通过控制状态轮询显示成功或稳定的拒绝
原因；HTTP 202 不被呈现为同步执行完成。桌面状态同步变化，刷新浏览器后仍
与 App 一致。当前通道禁用的控制不可用，武器选择仍受当前机型兼容范围约束。
页面不产生键盘输入，不触发 UAC，也不新增 Broker 或 8111 请求。

### WDB-M03 LAN 自动发现与统一控制 | LAN discovery and unified control

1. 从 App 或托盘开启“局域网访问与控制”，用自动复制的新链接在真实手机配对，
   并分别检查竖屏和横屏。
2. 执行一个可逆的显式目标操作，并检查控制状态响应与 App 最终状态。

预期：每个可绑定的 RFC1918 IPv4 都有独立精确监听，主窗口列出全部地址且没有
`0.0.0.0`；手机获得独立控制会话，写入仍经过 Origin、CSRF、幂等、schema
和 Tk 主线程复核。地图是移动端主要信息入口，页面无横向溢出，计时/飞行/
导航/告警无需桌面宽度即可读取。

### WDB-M04 LAN 控制、重新配对与立即撤销 | LAN control and revoke

1. 保留 WDB-M03 的手机控制会话，从电脑 App 或托盘关闭 LAN。
2. 验证配对码已轮换；不刷新页面，立即再次尝试操作并轮询控制状态。
3. 重新开启 LAN，使用轮换后的新链接在另一个手机 profile 配对并执行一个可逆操作。

预期：关闭会轮换配对码并立即使所有已有 LAN 会话失效；后续写入不得执行。
若命令恰好已排队但尚未到达 Tk，Tk 侧重新授权必须产生
`authorization_revoked`，不得晚执行。再次控制必须重新开启 LAN 并重新配对。

### WDB-M05 写入安全与幂等 | Write security and idempotency

在隔离测试会话中用浏览器 Network 面板和可编辑请求的本地 HTTP 客户端检查；
不要把认证材料写入日志或截图：

1. 检查一次正常请求只发往 `POST /api/v1/commands`，包含当前 Bomana 的精确
   `Origin`、`application/json`、非空 `X-Bomana-CSRF`、有效
   `Idempotency-Key` 与有界 body，并收到 202 `queued`。
2. 原样重放同一幂等键和同一合法 body；确认返回原 202 接受响应，控制状态中
   只有一次完成记录，动作没有重复执行。
3. 用同一幂等键发送另一个仍合法的目标 body；确认收到 409
   `idempotency_conflict`，目标状态不变。
4. 分别省略、重复或篡改 Origin/CSRF/幂等键，使用 `Origin: null` 或与 Host
   不同的 origin，并尝试错误/重复 Content-Type、空 body、超过 4096 字节、
   chunked、畸形 JSON、额外字段和未知命令。

预期：缺失或不匹配的授权/同源证明均失败；无效 media/body/schema/幂等请求
按协议返回 4xx，且 App 状态、配置文件和最近成功命令不变化。除
`POST /api/v1/commands` 外不存在写路由；响应无宽松 CORS。

### WDB-M06 Windows Firewall

在 Windows Defender Firewall 中分别拒绝和允许真实打包 App 的“专用网络”
访问，再从手机连接。

预期：拒绝时手机连接失败但本机页面仍可用；允许专用网络后手机可访问。
Bomana 本身不新增规则、不触发 UAC，也不开放公用网络规则。

### WDB-M07 多网卡 | Multiple adapters

在同时存在以太网、Wi-Fi、EasyTier/VPN 或虚拟网卡的电脑上开启 LAN，并检查
主窗口地址与复制链接；分别从物理 LAN 和 overlay 地址访问同一端口。

预期：Bomana 为每个成功绑定的 RFC1918 IPv4 生成链接；一个网卡绑定失败不会
阻止其他地址，关闭 LAN 会回收全部监听。没有 `0.0.0.0` 或公网监听。若手机
仍不可达，分别记录目标网段、Firewall profile 和 AP 隔离结果。

### WDB-M08 三通道打包资源 | Packaged variants and offline assets

分别从 Enhanced、Standard、Lite 的真实 App 8.4.0 包启动；断开外网后打开
页面并查看浏览器 Network 面板。

预期：HTML/CSS/JS/SVG、项目 PNG 标识与字体均从 Bomana 自身地址加载，无 CDN、远程字体、
分析或上传请求，也无资源 404；App ZIP 另包含三个 Web 控制 schema 供服务端
生产校验。Enhanced 提供完整可用控制；
Standard 不发布武器选择/模型或武器解算面板目标；Lite 仍可使用核心动作、
锁定、一般提示音与速度面板，但不重新启用被 `ENABLE_*` 禁止的功能。

### WDB-M09 War Thunder 实时同步 | Live-game synchronization

进入真实战斗，观察出生、飞行、燃油变化、导航目标、武器/投弹提示、告警、
坠毁与同局复活；同时从本机页面切换一个面板、选择一个兼容武器并更改模型。

预期：页面与 Bomana 主界面双向保持一致。地图在官方缩略图上显示己机、战区、
机场、POI、Trace back、当前武器射程，以及原始 `/map_obj.json` 当前样本里的
敌方飞机、装甲、防空、海上和未知单位；Fighter、Tank、SPAA、SAM、Frigate、
Boat、Destroyer 等当前官方 `icon` 显示为可辨认的本地矢量符号，蓝方/己方
单位与地图要素不被误判。逐项点击地图角落的图例后，只隐藏/恢复对应类别，
刷新配对状态不应把过滤变成 App 配置或 Web 写命令。单位从下一原始样本消失
或采样失败时立即移除，桌面 HUD/航向带不出现这些标记；
浏览器只请求 App 的配对后图片路由，不直接请求 8111。
当前机型不兼容的武器在 Tk 执行前被拒绝。8111 断开时页面诚实进入不可用/
待机状态，不显示伪造数据，也不扩大 Web 控制权限。

### WDB-M10 进程生命周期与偏好持久化 | Lifecycle and preferences

1. 在 Launcher 中关闭 Web autostart 后启动 App；确认 LAN 偏好同步清除且没有监听器，再从托盘
   “打开本机页面”按需启动。
2. 开启 autostart、关闭 auto-open，重启后确认只启动服务而不打开浏览器；再
   开启 auto-open，确认只有本机监听成功后才打开页面。
3. 在 Launcher 中开启 LAN 启动偏好，确认 Web autostart 同步开启；启动 App 后
   检查自动发现的精确 LAN 监听与控制会话。随后关闭 LAN 并退出。

预期：Launcher 只保存 Web autostart、local auto-open 与 LAN startup 三个布尔
偏好。按需启动、接口发现、端口选择、配对 URL 与浏览器打开由 App 决定；
auto-open 在 autostart 关闭时不单独启动服务。退出后本机和 LAN 端口释放；
每次启动的配对材料和会话都不同，旧手机会话不能读取或控制新进程。

### WDB-M11 Launcher 3 打包 UI、DPI 与键盘 | Packaged Launcher UI

用真实 `Bomana_launcher_v3.1.0.exe` 在 Windows 100%、125%、150% 和 200%
缩放下启动，调整窗口大小，并只用 Tab / Shift+Tab / 方向键 / Space / Enter
完成通道、下载源、代理、三个 Web 偏好、主要启动/更新动作与辅助动作的遍历。

预期：标题、状态、主要动作、启动与版本设置、更新/网络选项层级清晰；没有
文字或按钮裁切、重叠、不可达控件或焦点丢失。原有检查、安装、离线启动、
导入、回退、支持页和 Launcher 自更新入口仍可发现。代理文案与实际优先/
回退顺序一致，三个 Web 偏好在重启 Launcher 后保持且依赖关系正确。

### WDB-M12 App 8 / Launcher 3 打包边界 | Packaged compatibility

在隔离副本中运行 packaged-launcher smoke，并人工核对以下结果：

- Launcher 3.1.0 + App 8.4.0 正常交接，App 在运行时初始化前拿到严格
  `BOMANA_LAUNCHER_VERSION`；
- 缺失、畸形或 `2.9.9` 的 Launcher 身份被打包 App 拒绝，即使设置
  `BOMANA_SOURCE_DEVELOPMENT=1` 也不能绕过；
- 非冻结源码仅在身份缺失且显式设置开发标记时允许启动，旧或畸形身份仍失败；
- 版本畸形或低于 8.0.0 的本地导入、`app_previous/` 与恢复候选在任何目录
  交换前失败，隔离目录中的原有效 `app/` 和 `app_previous/` 均保持原样。

已验签在线清单与暂存包精确版本不一致主要由自动化对抗测试覆盖；除非具备
批准的发布签名环境，不要为了人工烟测生成、读取或替换真实发布私钥。

## 记录模板 | Result Record

```text
Build / commit:
App version / variant:
Launcher version:
Windows version / DPI scale:
Desktop browser profiles:
Phone / mobile browser:
Network / adapters:
Selected loopback and LAN address:
WDB-M01..M12 results:
Evidence / notes (no pairing/session/CSRF/idempotency secrets):
```

发布交接必须分别写明哪些场景已实际执行；自动化测试通过、桌面响应式模拟器、
源码预览或一次普通浏览器访问都不能替代真实手机、Firewall、多网卡、打包
Launcher/App、DPI/键盘与 War Thunder 对局检查。
