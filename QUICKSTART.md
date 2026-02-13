# 快速入门指南 | Quick Start Guide

欢迎使用 Bomana！这份指南将帮助你在 5 分钟内开始使用。

[中文](#中文快速入门) | [English](#english-quick-start)

---

## 中文快速入门

### 📥 步骤 1：获取软件

#### 选项 A：下载打包版（推荐新手）

1. 访问 [Releases 页面](https://github.com/Thankyou-Cheems/Bomana/releases)
2. 下载通用启动器：`Bomana_launcher_vX.X.X.exe`

启动器内可选版本通道：

| 通道 | 包含功能 | 适合人群 |
|------|----------|----------|
| **Enhanced** | 计时器 + 导航 + 燃油 + CCRP | 推荐大多数玩家 |
| **Standard** | 计时器 + 导航 + 燃油（无CCRP） | 不需要投弹预测 |
| **Lite** | 仅计时器 | 只要极简与低占用 |
3. 下载完成！跳到步骤 2

#### 选项 B：从源码运行（开发者）

```bash
# 克隆仓库
git clone https://github.com/Thankyou-Cheems/Bomana.git
cd Bomana

# 首次使用请先安装 uv: https://docs.astral.sh/uv/getting-started/installation/
# 安装依赖
uv sync

# 运行
uv run python Bomana.pyw
```

### 🎮 步骤 2：启动战雷

1. **启动战雷客户端**
2. **进入全真模式（Simulator Battles）**
3. **选择载具并进入战斗**

> 💡 **提示**：Bomana 需要在战斗中才能工作，在机库不会显示数据

### 🚀 步骤 3：运行 Bomana

1. **双击 `Bomana_launcher_vX.X.X.exe`**（或运行 `uv run python Bomana.pyw`）
2. 窗口会出现在**屏幕右上角**
3. 初始状态显示 "🏠机库" 或 "等待中"
4. 启动器打开后会自动检查当前通道（可手动切换），优先连接国内更新服务；失败时自动回退 GitHub
5. 界面会先展示新版本来源与下载总大小，点击“下载更新”后还会二次确认
6. 首次运行通常需要联网完成应用包下载，后续可离线启动本地版本
7. 可使用 `checksums_launcher.txt` 与 `checksums_app_*.txt` 验证下载完整性
8. 程序显示名为 `Bomana香焦`

### ✈️ 步骤 4：出生后开始计时

1. **在游戏中出生**（选择载具进入战场）
2. Bomana 会自动检测并开始计时
3. 显示 **"战斗中"** 徽章和 **15:00** 倒计时

### 🎯 步骤 5：使用导航功能

当你在空中飞行时，Bomana 会自动显示：

#### 🎯 战区导航
```
🎯 战区导航                HDG: 045°
➤ 前 23.5km  (+12°)   ⏱️03:45
○ 右 31.2km  (+67°)
○ 右 45.8km  (+89°)
```
- **➤** = 当前目标（前方 45° 内最近的战区）
- **方位** = 前/后/左/右
- **距离** = 到战区的直线距离（km）
- **角度** = 相对航向（+右 / -左）
- **⏱️** = 预计抵达时间

#### 🛫 机场导航
```
🛫 机场导航
🟢 ➤ 后 12.3km  (-175°)   ⏱️02:15
🔴 ○ 前 45.6km  (+5°)
```
- **🟢** = 友方机场（返航点）
- **🔴** = 敌方机场

#### ⛽ 燃油管理
```
⛽ 燃油管理
650kg (72%)  ⏱️ 18:30
油耗 35kg/min │ 高度 2500m
🏠 返航: 需~180kg (20%)  ✅ 充足
```
- **油量** = 当前燃油（kg）和百分比
- **⏱️** = 剩余飞行时间
- **油耗** = 平均消耗率（kg/分钟）
- **返航** = 返回友方机场所需油量和状态
  - ✅ 充足（绿色）
  - ⚠️ 注意（黄色）
  - 🔴 不足（红色）

### ⌨️ 步骤 6：熟悉快捷键

| 按键 | 功能 | 说明 |
|------|------|------|
| **F7** | 重置计时器 | 手动重启 15 分钟周期 |
| **F8** | 锁定/解锁 | 锁定后窗口点击穿透 |
| **F9** | 切换角落 | 在四个屏幕角落间切换 |
| **F10** | 声音开关 | 启用/禁用提示音 |
| **F11** | 战区音效 | 战区被摧毁提示音开关 |

### 🎨 步骤 7：自定义设置（可选）

右键点击**系统托盘图标**（屏幕右下角），选择：

- **⚙️ 设置**：调整透明度、缩放、主题
- **📊 显示面板**：选择显示哪些信息面板
- **📝 编辑检查清单**：自定义起飞前检查项

### ✅ 完成！

现在你已经可以使用 Bomana 了！

---

## 常见问题

### ❓ 窗口显示 "❌8111不可用"？

**原因**：战雷的 8111 接口未开启或无法访问

**解决**：
1. 确保战雷正在运行
2. 进入战斗（不是机库）
3. 如果还不行，重启战雷

### ❓ 战区/机场信息不显示？

**原因**：可能在机库或单人任务

**解决**：
1. 确保在多人全真模式战斗中
2. 某些地图可能没有战区数据

### ❓ 计时器不准确？

**解决**：
1. 按 **F7** 手动重置
2. 或重启 Bomana

### ❓ 想调整窗口大小？

**解决**：
1. 设置中调整 **UI 缩放**（默认 0.85）
2. 范围：0.6 - 1.5

### ❓ 声音太吵？

**解决**：
1. 按 **F10** 关闭所有声音
2. 或按 **F11** 只关闭战区提示音

### ❓ 如何隐藏某些面板？

**解决**：
1. 右键托盘图标 → **显示面板**
2. 取消勾选不需要的面板

---

## 进阶技巧

### 💡 技巧 1：利用目标锁定

Bomana 会自动锁定前方 45° 内最近的战区。如果你想切换目标：

1. **对准目标** <5° 持续 **3 秒**
2. Bomana 自动切换到该目标

### 💡 技巧 2：返航油量判断

观察燃油面板的返航估算：

- **✅ 充足**：继续战斗，油量足够
- **⚠️ 注意**：考虑返航，油量紧张
- **🔴 不足**：立即返航！油量不够

### 💡 技巧 3：战区优先级

当有多个战区时：
- Bomana 优先选择**角度最小**的（正前方）
- 而非**距离最近**的
- 这更符合飞行逻辑

### 💡 技巧 4：多显示器用户

1. 将 Bomana 放在副显示器
2. 游戏在主显示器全屏
3. 完美配合！

### 💡 技巧 5：自定义快捷键

在设置中可以重新分配 F7-F11 的功能，避免与游戏快捷键冲突。

---

## 开发者：更新 CCRP 炸弹参数

如果需要更新 `ccrp_bomb_params.json`：

```bash
python tools/blkx_extractor.py ^
  <path-to-datamine>\aces.vromfs.bin_u\gamedata\weapons\bombguns ^
  -o ccrp_bomb_params.json
```

---

## 下一步

- 📖 阅读完整的 [README.md](README.md)
- 🎨 尝试不同的主题（设置中）
- 📝 自定义检查清单（右键托盘 → 编辑检查清单）
- ⭐ 给项目一个 Star！

---

## English Quick Start

### 📥 Step 1: Get the Software

#### Option A: Download Packaged Version (Recommended)

1. Visit [Releases page](https://github.com/Thankyou-Cheems/Bomana/releases)
2. Download the universal launcher: `Bomana_launcher_vX.X.X.exe`

Choose channel inside launcher:

| Channel | Features | Best for |
|------|----------|----------|
| **Enhanced** | Timer + navigation + fuel + CCRP | Most players (recommended) |
| **Standard** | Timer + navigation + fuel (no CCRP) | Players not using bombing prediction |
| **Lite** | Timer only | Minimal UI and lowest overhead |
3. Done! Skip to Step 2

#### Option B: Run from Source

```bash
git clone https://github.com/Thankyou-Cheems/Bomana.git
cd Bomana
# Install uv first if needed: https://docs.astral.sh/uv/getting-started/installation/
uv sync
uv run python Bomana.pyw
```

### 🎮 Step 2: Start War Thunder

1. Launch War Thunder
2. Enter Simulator Battles
3. Select vehicle and enter battle

### 🚀 Step 3: Run Bomana

1. Double-click your `Bomana_launcher_vX.X.X.exe`
2. Window appears in **top-right corner**
3. Shows "🏠Hangar" or "IDLE"
4. Launcher auto-checks the current channel on startup (you can switch channels), using Tencent update service first and GitHub Releases as fallback
5. The UI shows update source and total download size before downloading, and "Download Update" asks for confirmation
6. First launch usually needs network access to fetch the app package; later you can launch offline from local files
7. Use `checksums_launcher.txt` and `checksums_app_*.txt` to verify file integrity
8. Display name: `Bomana香焦`

### ✈️ Step 4: Spawn and Start Timer

1. Spawn in game
2. Bomana auto-detects and starts timer
3. Shows **"战斗中"** badge and **15:00** countdown

### 🎯 Step 5: Use Navigation

When airborne, Bomana shows:

#### Zone Navigation
```
🎯 Zone Navigation           HDG: 045°
➤ Front 23.5km  (+12°)   ⏱️03:45
○ Right 31.2km  (+67°)
```

#### Airfield Navigation
```
🛫 Airfield Navigation
🟢 ➤ Back 12.3km  (-175°)   ⏱️02:15
🔴 ○ Front 45.6km  (+5°)
```

#### Fuel Management
```
⛽ Fuel Management
650kg (72%)  ⏱️ 18:30
Rate 35kg/min │ Alt 2500m
🏠 Return: ~180kg (20%)  ✅ Safe
```

### ⌨️ Step 6: Learn Hotkeys

| Key | Function | Description |
|-----|----------|-------------|
| **F7** | Reset Timer | Manual reset to 15:00 |
| **F8** | Lock/Unlock | Lock = click-through |
| **F9** | Switch Corner | Cycle through corners |
| **F10** | Sound Toggle | Enable/disable sounds |
| **F11** | Zone Sound | Zone destroyed alert |

### ✅ Done!

You're ready to use Bomana!

---

## FAQ

**Q: Shows "❌8111 Unavailable"?**  
A: Ensure War Thunder is running and you're in battle (not hangar)

**Q: No zone/airfield data?**  
A: Ensure you're in multiplayer Simulator Battle

**Q: Timer inaccurate?**  
A: Press **F7** to manually reset

**Q: Too noisy?**  
A: Press **F10** to disable sounds

---

<div align="center">

**Enjoy flying! ✈️**

祝你飞行愉快！✈️

</div>
