# 隐私政策 | Privacy Policy

**生效日期：** 2026年2月6日  
**最后更新：** 2026年2月6日

---

## 数据收集声明 | Data Collection Statement

Bomana（以下简称"本应用"）致力于保护用户隐私。本应用仅收集**必要的匿名使用数据**，用于统计日活用户（DAU）和区分真实用户，以帮助改进产品质量。

### 我们收集哪些数据？ | What Data We Collect

本应用通过启动器自动收集以下**匿名化**数据：

| 数据类型 | 收集方式 | 用途 | 是否可识别个人 |
|---------|---------|------|---------------|
| **设备标识符** (device_id) | SHA256哈希（基于Windows MachineGUID或本地随机UUID） | 统计独立设备数量，计算真实DAU | 否 - 已脱敏 |
| **安装标识符** (install_id) | 本地随机生成的UUID | 区分同一设备上的多次安装 | 否 - 随机生成 |
| **应用版本** (app_version) | 主应用版本号（如"6.7.0"） | 了解版本分布，定位版本特定问题 | 否 |
| **启动器版本** (launcher_version) | 启动器版本号（如"1.1.0"） | 统计启动器使用情况 | 否 |
| **功能通道** (channel) | Enhanced/Standard/Lite | 分析功能偏好 | 否 |
| **事件时间戳** (event_time_utc) | UTC标准时间 | 计算DAU、活跃时段分析 | 否 |
| **事件类型** (event) | 如：launcher_start、app_launch、update_complete | 追踪关键用户行为 | 否 |

### 我们**不会**收集的数据 | What We DO NOT Collect

**我们承诺绝不收集以下任何数据：**

- 个人身份信息（姓名、邮箱、电话等）
- 游戏账号信息（War Thunder账号、ID、用户名）
- IP地址或精确地理位置
- 游戏内操作或战绩数据
- 系统敏感信息（文件列表、进程列表等）
- 任何剪贴板或输入法数据

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
- **国内加速节点** - 优先使用腾讯云CDN（`bomanaupdate.ruikang.wang`），失败时回退GitHub

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

本应用的数据上报功能**目前无独立开关**，但您可以通过以下方式阻止：

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
从源码运行时，可直接修改 `launcher.pyw` 中的 `PRIMARY_UPDATE_BASE_URL` 为空字符串。

**影响：** 禁用后将无法使用国内更新加速服务，仅能通过GitHub获取更新。

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
- **主服务器：** 腾讯云（中国大陆）
- **备份服务器：** GitHub仓库（全球CDN）

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

**最后更新：** 2026年2月6日  
**版本：** 1.0.0

*Bomana团队致力于保护您的隐私。如有疑问，请随时联系我们。*


