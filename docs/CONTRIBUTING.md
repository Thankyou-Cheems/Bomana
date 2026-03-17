# 贡献指南 | Contributing Guide

感谢你对 Bomana 项目的关注！我们欢迎任何形式的贡献。

[中文](#中文) | [English](#english)

---

## 中文

### 如何贡献

#### 报告 Bug

如果你发现了 Bug，请：

1. **检查是否已存在相同问题**：在 [Issues](https://github.com/Thankyou-Cheems/Bomana/issues) 中搜索
2. **创建新 Issue**：如果没有找到，请创建新的 Issue
3. **提供详细信息**：
   - 操作系统和版本（如 Windows 10 21H2）
   - Python 版本（如 Python 3.14.3）
   - 软件版本（如 v6.8.0）
   - 复现步骤
   - 错误截图或错误信息
   - 预期行为 vs 实际行为

#### 建议新功能

欢迎提出新功能建议！请：

1. **检查是否已有类似建议**
2. **创建 Feature Request**
3. **说明**：
   - 功能描述
   - 使用场景
   - 为什么需要这个功能
   - 可能的实现方案（可选）

#### 提交代码

##### 准备工作

1. **Fork 仓库**
   ```bash
   # 点击仓库右上角的 "Fork" 按钮
   ```

2. **克隆到本地**
   ```bash
   git clone https://github.com/YOUR_USERNAME/Bomana.git
   cd Bomana
   ```

3. **创建新分支**
   ```bash
   git checkout -b feature/your-feature-name
   # 或
   git checkout -b fix/bug-description
   ```

4. **安装依赖**
   ```bash
   # 首次使用请先安装 uv: https://docs.astral.sh/uv/getting-started/installation/
   uv sync
   ```

##### 开发规范

**代码风格**

- 遵循 [PEP 8](https://pep8.org/) 规范
- 使用 4 个空格缩进（不使用 Tab）
- 最大行长度：100 字符（注释可适当放宽）
- 中文注释优先（英文注释也可接受）

**命名规范**

```python
# 类名：大驼峰（PascalCase）
class GameLogic:
    pass

# 函数/变量名：小写+下划线（snake_case）
def calculate_distance(x1, y1, x2, y2):
    player_position = (x1, y1)
    
# 常量：全大写+下划线
MAX_ZONE_COUNT = 6
API_BASE_URL = "http://127.0.0.1:8111"

# 私有方法/变量：单下划线前缀
def _internal_method(self):
    pass
```

**注释规范**

```python
def calculate_bearing(x1: float, y1: float, x2: float, y2: float) -> float:
    """计算从点1到点2的方位角
    
    Args:
        x1, y1: 起点坐标
        x2, y2: 终点坐标
    
    Returns:
        方位角（0°=北，90°=东，顺时针）
    """
    # 具体实现
    pass
```

**重要提示框**

对于关键代码段，使用提示框注释：

```python
# ╔══════════════════════════════════════════════════════════════════════╗
# ║ 修改注意事项 - 窗口尺寸计算                                        ║
# ╠══════════════════════════════════════════════════════════════════════╣
# ║ 1. hint_min_width 必须足够容纳底部提示文字的完整显示                  ║
# ║ 2. 面板可见性影响最小宽度计算                                         ║
# ╚══════════════════════════════════════════════════════════════════════╝
```

**数据类和配置类**

- 使用 `@dataclass` 装饰器
- 配置类继承规范：
  ```python
  class GameConfig:
      """游戏逻辑相关配置
      
      这些参数直接影响游戏状态判断的准确性，修改时需谨慎测试。
      """
      CYCLE_SECONDS = 15 * 60
      LAND_SPEED_KMH = 40
  ```

##### 提交规范

**Commit Message 格式**

使用约定式提交（Conventional Commits）：

```
<类型>: <简短描述>

<详细描述>（可选）

<关联 Issue>（可选）
```

**类型**：
- `feat`: 新功能
- `fix`: Bug 修复
- `docs`: 文档更新
- `style`: 代码格式（不影响功能）
- `refactor`: 重构（不改变功能）
- `perf`: 性能优化
- `test`: 测试相关
- `chore`: 构建/工具相关

**示例**：

```bash
# 好的示例
git commit -m "feat: 添加燃油管理系统"
git commit -m "fix: 修复多显示器窗口位置错误 (#123)"
git commit -m "docs: 更新 README 安装说明"

# 不好的示例
git commit -m "修改了一些东西"
git commit -m "bug"
```

##### 提交 Pull Request

1. **推送到你的 Fork**
   ```bash
   git push origin feature/your-feature-name
   ```

2. **创建 Pull Request**
   - 访问原仓库页面
   - 点击 "New Pull Request"
   - 选择你的分支

3. **填写 PR 描述**
   - 说明修改内容
   - 关联相关 Issue（如果有）
   - 提供测试步骤
   - 附上截图（UI 变更）

4. **等待审查**
   - 维护者会审查你的代码
   - 可能会提出修改建议
   - 请及时回复和修改

### 文档贡献

文档同样重要！你可以：

- 修正错别字
- 改进说明文字
- 添加使用示例
- 翻译文档（中英文互译）
- 补充常见问题

### 测试

如果你修改了代码，请：

1. **手动测试**
   - 在战雷全真模式中实际测试
   - 覆盖主要使用场景
   - 测试边界情况

2. **回归测试**
   - 确保没有破坏现有功能
   - 检查各个面板显示是否正常
   - 验证热键功能

3. **性能测试**
   - 监控 CPU/内存占用
   - 确保 UI 刷新流畅（20fps）
   - 网络请求不超时

### UI/UX 建议

如果你想改进界面：

- **保持风格一致**：遵循现有的配色方案（Theme 类）
- **考虑可访问性**：对比度、字体大小
- **测试多 DPI**：在不同 DPI 设置下测试
- **多显示器测试**：确保在多显示器环境下正常工作

### 发布流程

仅维护者可以发布新版本：

1. 更新 `docs/CHANGELOG.md`
2. 更新版本号（`bomana/config.py` 中的 `__version__`）
3. 创建 Git Tag（按发布目标选择）：
   - `vX.Y.Z`：完整发布（启动器 + 应用包）
   - `vX.Y.Z-app`：仅应用包
   - `vX.Y.Z-launcher`：仅启动器
4. 推送 Tag：`git push origin <tag>`（触发 GitHub Actions 云端自动打包）
5. 等待 Actions 自动创建/更新 GitHub Release
6. 检查产物是否齐全：
   - 通用启动器：`Bomana_launcher_vX.Y.Z.exe`
   - 应用包：`Bomana_app_*_vX.Y.Z.zip`
   - 清单：`manifest_*.json`
   - 校验：`checksums_app_*.txt`、`checksums_launcher.txt`

手动触发工作流时可选择构建目标：
- `all`：启动器 + 应用包
- `app`：仅应用包（常规更新）
- `launcher`：仅启动器

### ❓ 有问题？

- 查看 [README.md](../README.md)
- 查看 [Issues](https://github.com/Thankyou-Cheems/Bomana/issues)
- 创建新 Issue 提问

---

## English

### How to Contribute

#### Reporting Bugs

If you find a bug:

1. **Check existing issues**: Search in [Issues](https://github.com/Thankyou-Cheems/Bomana/issues)
2. **Create new issue**: If not found, create a new one
3. **Provide details**:
   - OS and version (e.g., Windows 10 21H2)
   - Python version (e.g., Python 3.14.3)
   - Software version (e.g., v6.8.0)
   - Steps to reproduce
   - Screenshots or error messages
   - Expected vs actual behavior

#### Suggesting Features

We welcome feature suggestions! Please:

1. **Check for similar suggestions**
2. **Create Feature Request**
3. **Explain**:
   - Feature description
   - Use case
   - Why this feature is needed
   - Possible implementation (optional)

#### Submitting Code

##### Preparation

1. **Fork the repository**
2. **Clone locally**
   ```bash
   git clone https://github.com/YOUR_USERNAME/Bomana.git
   cd Bomana
   ```
3. **Create new branch**
   ```bash
   git checkout -b feature/your-feature-name
   ```
4. **Install dependencies**
   ```bash
   # Install uv first if needed: https://docs.astral.sh/uv/getting-started/installation/
   uv sync
   ```

##### Development Guidelines

**Code Style**
- Follow [PEP 8](https://pep8.org/)
- Use 4 spaces for indentation
- Max line length: 100 characters
- Comments in Chinese or English

**Commit Message**
Use Conventional Commits:
```
<type>: <short description>

<detailed description> (optional)
```

Types: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `chore`

##### Pull Request

1. **Push to your fork**
   ```bash
   git push origin feature/your-feature-name
   ```
2. **Create Pull Request**
3. **Fill PR description**
4. **Wait for review**

### Documentation

You can also contribute by:
- Fixing typos
- Improving explanations
- Adding examples
- Translating docs

### Testing

Please test your changes:
- Manual testing in War Thunder SB
- Regression testing
- Performance testing

---

<div align="center">

**Thank you for contributing to Bomana!**

感谢你为 Bomana 做出贡献！

</div>


