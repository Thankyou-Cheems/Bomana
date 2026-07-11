# 隐私政策 | Privacy Policy

**生效日期：** 2026年2月6日
**最后更新：** 2026年7月11日

---

## 数据收集声明 | Data Collection Statement

Bomana（以下简称"本应用"）致力于保护用户隐私。本应用仅收集**必要的匿名使用数据**，用于统计日活用户（DAU）和区分真实用户，以帮助改进产品质量。

### 我们收集哪些数据？ | What Data We Collect

本应用主要由绿色版启动器收集以下**匿名化**数据。源码调试模式（source test mode）默认不会向更新服务上报事件：

| 数据类型 | 收集方式 | 用途 | 是否可识别个人 |
|---------|---------|------|---------------|
| **设备标识符** (device_id) | SHA256哈希（基于Windows MachineGUID或本地随机UUID） | 统计独立设备数量，计算真实DAU | 否 - 已脱敏 |
| **安装标识符** (install_id) | 本地随机生成的UUID | 区分同一设备上的多次安装 | 否 - 随机生成 |
| **应用版本** (app_version) | 主应用版本号（如"8.0.0"） | 了解版本分布，定位版本特定问题 | 否 |
| **启动器版本** (launcher_version) | 启动器版本号（如"3.0.0"） | 统计启动器使用情况 | 否 |
| **功能通道** (channel) | Enhanced/Standard/Lite | 分析功能偏好 | 否 |
| **事件时间戳** (event_time_utc) | UTC标准时间 | 计算DAU、活跃时段分析 | 否 |
| **事件类型** (event) | 如：`launcher_start`、`version_check`、`app_launch`、`launcher_update_result` | 追踪关键用户行为 | 否 |

### 我们**不会**收集的数据 | What We DO NOT Collect

**我们承诺绝不收集以下任何数据：**

- 个人身份信息（姓名、邮箱、电话等）
- 游戏账号信息（War Thunder账号、ID、用户名）
- IP地址或精确地理位置
- 游戏内操作或战绩数据
- 系统敏感信息（文件列表、进程列表等）
- 任何剪贴板或输入法数据

可选的高权限热键 Broker 不进行网络访问或事件上报；它只向当前 Bomana App 发送固定动作 ID，不记录按键内容，不读取游戏进程、账号、文件或 8111 数据。普通 App 启动时只会对可见 War Thunder 窗口查询进程文件名和管理员状态，用于决定是否显示可选授权按钮；不会读取进程内存或模块。

### 网页驾驶舱 | Web Cockpit

Bomana 可在本机浏览器或同一局域网的手机上提供网页驾驶舱。它发布筛选后的状态，也可在严格授权后操作 Bomana 自身的固定语义功能：

- 本机 Web 服务默认随 App 启动，也可由用户在 Launcher 中关闭；Launcher 还可保存“启动成功后自动打开本机页面”。这两个布尔偏好是 Launcher 唯一保存的网页设置。
- 监听器默认仅绑定 `127.0.0.1`，优先使用端口 `8777`；端口占用时只会在有限的相邻端口中回退。监听器、所选端口、配对 URL 和浏览器打开时机都由 App 管理。
- 局域网访问必须由用户从 App 或托盘为**本次运行**显式开启，只在每个成功绑定的 RFC1918 私有 IPv4 上建立精确监听而不使用 `0.0.0.0`；Bomana 不会保存该开关、修改 Windows 防火墙/UPnP，也不会为此请求管理员权限。
- 网页只读取 App 发布的筛选 `UISnapshot` 与有界地图图片内存快照，不代理 8111，也不发布敌机标记、原始 8111 JSON 响应或诊断数据。
- 每次启动都会生成新的配对材料；每次成功配对又会创建独立的会话令牌、授权记录、CSRF 证明和有界幂等记录。浏览器通过 HttpOnly、`SameSite=Strict` Cookie 读取快照与控制状态。
- 本机会话可获得控制权限；局域网会话默认只读。LAN 控制必须在运行 Bomana 的电脑上为**本次运行**再次明确开启，开启时会轮换配对码，只有之后重新配对的设备才可控制。撤销会立即使已有 LAN 控制会话失效。
- 写入只允许重置计时、切换窗口角落、设置窗口锁定/提示音/面板显示，以及在功能可用时选择当前武器与弹道模型。请求必须同源并带当前会话的 CSRF 与幂等证明；App 主线程会再次检查权限、功能开关和目标有效性。
- 网页控制不会合成 F7-F11、控制 War Thunder、调用任意回调或配置路径，也不会增加热键 Broker 或网络能力。
- 页面资源全部随 Bomana 打包。网页服务不使用外部资源、CORS、上传或分析脚本，也不记录客户端地址、请求路径、配对信息或飞行快照。

局域网页面使用普通 HTTP，请只在可信的家庭或个人网络中临时开启。端口、配对、LAN 访问、LAN 控制、会话、CSRF 与授权状态都不会持久化；关闭局域网访问或退出 Bomana 后，该入口立即失效。此功能不会改变启动器匿名统计的范围。

Bomana's Web Cockpit is loopback-only by default. Each successful pairing creates a distinct session; LAN sessions remain view-only unless control is explicitly enabled for the current run and the device pairs again. Writes are limited to allowlisted Bomana semantics with same-origin, CSRF, idempotency, and Tk-owner rechecks. No port, pairing, LAN, control, session, or authorization state is persisted. The Web Cockpit does not proxy 8111, publish hostile contacts, synthesize keys, control the game, upload snapshots, load remote assets, or keep HTTP request logs.

---

## 数据安全与匿名化 | Data Security & Anonymization

### 设备标识符生成机制

设备标识符 (`device_id`) 通过以下步骤生成，确保**不可逆向追溯**：

```python
# 伪代码示例
if 存在Windows MachineGUID:
    原始字符串 = "Bomana香焦|machine|{MachineGUID}"
else:
    # 降级方案：使用本地随机UUID
    原始字符串 = "Bomana香焦|fallback|{计算机名}|{install_id}"

device_id = SHA256(原始字符串)[:32]  # 取前32位，单向哈希
```

**关键技术特性：**
- **单向加密** - SHA256不可逆，无法从device_id还原MachineGUID
- **应用隔离** - 加盐字符串包含"Bomana香焦"，其他应用无法关联
- **本地生成** - 敏感数据不离开本地设备
- **无跨应用追踪** - 该ID仅用于Bomana，不与第三方共享

### 数据传输安全

- **HTTPS加密传输** - 所有数据通过TLS 1.2+加密
- **证书校验** - 使用certifi提供的Mozilla CA证书包
- **国内加速节点** - 优先使用腾讯云CDN（`bomanaupdate.ruikang.wang`），失败时回退GitHub；用户也可在启动器中手动切换来源

---

## 数据用途 | How We Use Data

收集的数据**仅用于以下合法目的**：

### 1. 产品改进
- 分析崩溃率较高的版本，优先修复
- 了解功能使用频率，优化资源分配
- 识别异常更新失败模式

### 2. 运营决策
- 统计日活用户（DAU），评估产品健康度
- 区分真实用户与测试/刷量行为
- 识别恶意滥用（如DDoS攻击）

### 3. 透明公开
- 在GitHub主页展示实时DAU徽章（公开数据）
- 在README中展示启动总次数（公开数据）

### 我们承诺**不会**将数据用于：
- 商业广告或精准营销
- 出售或共享给第三方
- 用户画像或行为预测
- 任何侵犯隐私的用途

---

## 用户权利 | Your Rights

### 1. 知情权
您有权了解本应用收集哪些数据及其用途（即本隐私政策）。

### 2. 选择权
**如何禁用数据收集？**

本应用的数据上报功能**目前无独立 UI 开关**，但您可以通过以下方式阻止主更新服务请求与事件上报：

#### 方法1：环境变量（推荐）
```cmd
# 在启动前设置环境变量
set BOMANA_UPDATE_BASE_URL=
Bomana_launcher_vX.X.X.exe
```

#### 方法2：修改hosts文件
```
# C:\Windows\System32\drivers\etc\hosts
127.0.0.1 bomanaupdate.ruikang.wang
```

#### 方法3：使用源码版本
从源码运行时，可直接修改 `launcher.pyw` 中的 `PRIMARY_UPDATE_BASE_URL` 为空字符串；另外，源码调试模式默认不会上报事件。

**影响：** 禁用后将无法使用国内更新加速服务与对应匿名事件上报；启动器会只走 GitHub 检查/下载链路。

### 3. 数据最小化
本应用已采用**数据最小化**原则：
- 仅收集统计必需的字段
- 不收集任何可选的额外信息
- 不使用第三方分析SDK（如百度统计、友盟等）

### 4. 数据删除
由于收集的数据已完全匿名化且无法关联到个人，我们无法识别特定用户的数据。若您担心隐私，直接卸载应用即可，所有数据的影响将在30天内自然消失（统计窗口周期）。

---

## 数据存储与管理 | Data Storage

### 存储位置
- **更新/统计主服务：** 腾讯云 / EdgeOne（中国大陆分发）
- **回退下载来源：** GitHub Releases（全球 CDN）

### 数据保留期限
- **原始事件日志：** 保留30天后自动删除
- **聚合统计数据：** 长期保留（如每日DAU总数）- 已完全匿名，无隐私风险

### 访问控制
- 仅项目维护者有权访问原始数据
- 使用密码学签名验证数据完整性
- 定期审计访问日志

---

## 合规性 | Compliance

### 适用法律
本应用的隐私实践符合以下法律法规：
- 🇨🇳 **《个人信息保护法》（PIPL）** - 中国
- 🇪🇺 **《通用数据保护条例》（GDPR）** - 欧盟
- 🇺🇸 **《加州消费者隐私法案》（CCPA）** - 美国加州

### 法律依据
根据GDPR第6条，我们处理数据的法律依据为：
- **合法利益** (Article 6(1)(f)) - 统计匿名使用数据属于合法利益
- **用户同意** - 通过下载并运行本应用，您同意本隐私政策

### 未成年人保护
本应用不针对13岁以下儿童，不会故意收集未成年人数据。

---

## 政策更新 | Policy Updates

本隐私政策可能会随着功能更新而调整。重大变更将通过以下方式通知：
- 在GitHub仓库主页发布公告
- 在启动器更新日志中说明
- 更新README中的隐私政策链接

**建议定期查看本文档以了解最新变更。**

---

## 联系我们 | Contact Us

如果您对本隐私政策有任何疑问或顾虑，请通过以下方式联系：

- **GitHub Issues:** [https://github.com/Thankyou-Cheems/Bomana/issues](https://github.com/Thankyou-Cheems/Bomana/issues)
- **项目主页:** [https://github.com/Thankyou-Cheems/Bomana](https://github.com/Thankyou-Cheems/Bomana)

---

## 透明度声明 | Transparency Statement

为了最大程度的透明：

### 实时数据公开
您可以通过以下公开API查看实时统计数据（仅聚合数据，无个人信息）：
- **每日DAU统计：** `https://bomanaupdate.ruikang.wang/api/v1/stats/daily`
- **展示位置：** GitHub主页README的DAU徽章

### 开源承诺
本应用的核心代码已在GitHub开源，您可以：
- 审查所有数据收集代码（见 `launcher.pyw` 的 `_report_primary_event` 函数）
- 验证我们的隐私承诺
- 提交PR改进隐私保护

---

**最后更新：** 2026年7月11日
**版本：** 1.1.0

*Bomana团队致力于保护您的隐私。如有疑问，请随时联系我们。*


