# 贡献指南 | Contributing Guide

感谢你对 Bomana 的关注。这个仓库当前以 Windows 本地开发、`uv` 环境、`bd` 任务跟踪和 GitHub PR 为主线协作。

[中文](#中文) | [English](#english)

---

## 中文

### 提交前先了解的规则

- 只使用 War Thunder 官方 `localhost:8111` 数据；禁止内存读取、注入或修改游戏文件。
- 所有任务跟踪都使用 `bd (beads)`，不要新增 markdown TODO 或外部任务列表。
- 修改架构或代码流时，必须同步更新 [ARCHITECTURE.md](./ARCHITECTURE.md)。
- 遇到新的失败模式时，必须在 [PITFALLS.md](./PITFALLS.md) 追加简短记录。
- 功能开关受 `bomana/config.py` 中的 `ENABLE_*` 控制，三种构建变体共用同一份配置逻辑。

### 环境准备

```bash
git clone https://github.com/YOUR_USERNAME/Bomana.git
cd Bomana
uv sync
```

如果要本地打包绿色版，再安装构建依赖：

```bash
uv sync --extra build
```

源码运行：

```bash
uv run python Bomana.pyw
```

### 任务跟踪（必须使用 bd）

开始工作前：

```bash
bd ready --json
```

认领已有任务：

```bash
bd update <issue-id> --status in_progress --json
```

发现了新工作：

```bash
bd create "Issue title" --description="Context" -t task -p 2 --deps discovered-from:<parent-id> --json
```

完成后关闭：

```bash
bd close <issue-id> --reason "Completed" --json
```

如果你是外部贡献者，PR 里请直接写明对应的 `bd` 编号；若没有权限操作 `bd` 数据库，请在 PR 描述里说明原因和上下文。

### 开发规范

- Python 版本要求：`3.14+`
- 代码风格：PEP 8、4 空格缩进、尽量保持单行不超过 100 字符
- 注释：保留现有注释与文件头，新增注释只写必要背景，不写显而易见的语句复述
- 配置/状态类优先集中在 `bomana/config.py` 与 `bomana/core/state.py`
- UI 改动请同时检查多 DPI、多显示器、历史速度模式、独立导航窗口和 HUD 开关

### 提交与 PR

- 分支命名建议：`feature/...`、`fix/...`、`docs/...`
- Commit message 使用 Conventional Commits，例如 `docs: refresh contribution and privacy docs`
- 如果直接在 `main` 分支提交，先运行 `/gc`（`git-commit-smart`）生成提交信息，再执行 `git commit`
- PR 描述请包含：
  - 变更目标
  - 对应 `bd` 编号
  - 测试步骤
  - UI 变更截图（如适用）

### 文档要求

这些文档默认需要一起考虑：

- [../README.md](../README.md)：面向用户的安装、功能和合规说明
- [ARCHITECTURE.md](./ARCHITECTURE.md)：目录结构、运行数据流、构建链路
- [PRIVACY.md](./PRIVACY.md)：匿名统计和更新服务行为
- [CHANGELOG.md](./CHANGELOG.md)：对用户可见的版本变化

### 测试与验证

代码改动至少应覆盖其中相关项：

- `uv run python Bomana.pyw` 基础启动验证
- 受影响功能的静态自测
- 真实 War Thunder SB 实测（如果改动涉及 8111 数据、UI 刷新、热键、导航、HUD、启动器）
- 打包链路验证：`tools\scripts\build_portable.bat <Variant> <all|app|launcher>`（如果改动涉及发布或资源）

### 发布流程（维护者）

1. 更新 `docs/CHANGELOG.md`
2. 更新 `bomana/config.py` 中的 `__version__`
3. 若 app 包需要新启动器能力，更新 `PORTABLE_MIN_LAUNCHER_VERSION`
4. 根据发布目标做最少真实验证：
   - app 发布：启动器兼容性、下载/启动正常
   - launcher 发布：重查排队、保留一个 `app_previous/`、回退互换正常
5. 推送标签：
   - `vX.Y.Z`：完整发布
   - `vX.Y.Z-app`：仅应用包
   - `vX.Y.Z-launcher`：仅启动器
6. GitHub Actions 会构建对应产物并创建/更新 Release
7. 如需同步到国内更新服务，等待 `deploy-manifests-to-server.yml` 完成

### 有问题？

- 先看 [../README.md](../README.md)
- 再看 [ARCHITECTURE.md](./ARCHITECTURE.md) 和 [PITFALLS.md](./PITFALLS.md)
- 需要讨论时，请在 PR 中带上复现步骤、日志和对应 `bd` 编号

---

## English

### Project Rules First

- Use only the official War Thunder `localhost:8111` API. No memory reads, injection, or game-file edits.
- Track work in `bd (beads)` only; do not add markdown TODO systems.
- Update [ARCHITECTURE.md](./ARCHITECTURE.md) when module boundaries or data flow change.
- Add a short note to [PITFALLS.md](./PITFALLS.md) when you hit a new failure mode.
- Respect `ENABLE_*` feature flags in `bomana/config.py`; all build variants share the same config model.

### Setup

```bash
git clone https://github.com/YOUR_USERNAME/Bomana.git
cd Bomana
uv sync
```

If you need packaging locally:

```bash
uv sync --extra build
```

Run from source:

```bash
uv run python Bomana.pyw
```

### Task Tracking With bd

Check ready work:

```bash
bd ready --json
```

Claim work:

```bash
bd update <issue-id> --status in_progress --json
```

Create discovered follow-up work:

```bash
bd create "Issue title" --description="Context" -t task -p 2 --deps discovered-from:<parent-id> --json
```

Close finished work:

```bash
bd close <issue-id> --reason "Completed" --json
```

If you are contributing from a fork and cannot update the project beads database directly, mention the intended `bd` linkage in your PR description.

### Development Expectations

- Python `3.14+`
- PEP 8, 4-space indentation, preferably <= 100 columns
- Preserve existing headers and comments; add comments only when they provide real context
- Re-check multi-DPI, multi-monitor, history-speed mode, standalone nav window, and HUD behavior when UI changes

### Commits And PRs

- Suggested branch names: `feature/...`, `fix/...`, `docs/...`
- Use Conventional Commits
- On `main`, generate the commit message with `/gc` (`git-commit-smart`) before `git commit`
- PRs should include:
  - scope of change
  - linked `bd` issue id
  - test steps
  - screenshots for UI changes

### Documentation Set

Keep these in sync with the code:

- [../README.md](../README.md)
- [ARCHITECTURE.md](./ARCHITECTURE.md)
- [PRIVACY.md](./PRIVACY.md)
- [CHANGELOG.md](./CHANGELOG.md)

### Validation

Relevant changes should be validated with some combination of:

- `uv run python Bomana.pyw`
- focused local static checks
- real War Thunder SB smoke testing
- `tools\scripts\build_portable.bat <Variant> <all|app|launcher>` for packaging/release changes

### Release Notes For Maintainers

1. Update `docs/CHANGELOG.md`
2. Bump `__version__` in `bomana/config.py`
3. Update `PORTABLE_MIN_LAUNCHER_VERSION` if the app now requires newer launcher behavior
4. Smoke test the relevant release path
5. Push `vX.Y.Z`, `vX.Y.Z-app`, or `vX.Y.Z-launcher`
6. Let GitHub Actions build and publish the assets
7. Wait for the deploy workflow if the Tencent/EdgeOne update service should receive the new artifacts


