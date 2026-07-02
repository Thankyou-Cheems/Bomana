# 贡献指南 | Contributing Guide

感谢你对 Bomana 的关注。这个仓库当前以 Windows 本地开发、`uv` 环境、`bd` 任务跟踪和 GitHub PR 为主线协作。

[中文](#中文) | [English](#english)

---

## 中文

### 提交前先了解的规则

- 只使用 War Thunder 官方 `localhost:8111` 数据；禁止内存读取、注入或修改游戏文件。
- 所有任务跟踪都使用 `bd (beads)`，不要新增 markdown TODO 或外部任务列表。
- 跨模块不变量以 [docs/specs](./specs/) 为准；入口文档只保留摘要和链接。
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

### 轻量本地验证

默认本地 smoke 只跑不依赖游戏的快速回归，不设置覆盖率目标：

```bash
tools\scripts\check_smoke.bat
```

等价命令：

```bash
uv run --extra dev pytest
```

如果需要可选开发工具：

```bash
uv sync --extra dev
uv run --extra dev pytest
uv run --extra dev ruff check <本次修改的 Python 路径>
uv run --extra dev ruff format --check <本次修改的 Python 路径>
```

代码类任务（包括 `bd`/beads 任务）完成前必须运行 Ruff。推荐最终门禁：

```bash
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
```

纯文档或仅变更 issue 状态的任务可在交接中说明 Ruff 不适用。

Ruff 规则策略：`RUF012` 与 `RUF013` 已作为默认门禁启用，用于显式标记共享类状态和禁止隐式 `Optional`。`RUF001`、`RUF002`、`RUF003` 暂不全仓启用；仓库包含大量中文 UI 文案、注释、文档字符串和字体字形清单，直接启用会产生大量预期命中。需要排查 Unicode 歧义时，按文件或路径运行 targeted scan：

```bash
uv run --extra dev ruff check --select RUF001,RUF002,RUF003 <path>
```

### CI 质量门

`.github/workflows/quality.yml` 会在 PR 和 `main` 推送时运行 Windows 轻量门禁：

- Python 3.14
- `uv sync --extra dev --frozen`
- `uv run --extra dev ruff check .`
- `uv run --extra dev ruff format --check .`
- `tools\scripts\check_smoke.bat`

当前阶段不设置覆盖率阈值，也不把 CI 伪装成真实 War Thunder / `localhost:8111` 实机验证。涉及 8111、HUD、热键、托盘、导航或启动器的改动，仍需按下文手工 smoke 记录验证结果。

### 测试组织

测试文件随功能增长时按系统边界命名，而不是按临时 bug 命名。详见 [../tests/README.md](../tests/README.md)。

- `test_core_*.py`：核心逻辑、遥测、导航、计时状态和数据契约
- `test_ui_*.py`：可用 fake/headless 跑的 Tk UI 行为
- `test_launcher_*.py`：启动器更新、安装、回滚、清单和网络 fallback
- `test_utils_*.py`：持久化、诊断、字体、资源查找等共享工具
- `test_quality_*.py`：质量门和 workflow 配置
- `tests/contracts/`：对应 `docs/specs/` 的跨模块架构合同

现有测试文件可以在大改时再归并；新增或重写测试应优先使用上述前缀，避免 `test_misc.py`、`test_regression.py` 这类无边界文件。

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

关闭代码类 `bd` 任务前，先运行 Ruff 和相关测试/构建门禁，并在提交或交接中记录结果。

`bd` 数据以本地 Dolt 数据库为准；收尾或交接前用 `bd backup status` 检查备份状态。命令行自动化应使用 `--json`，不要恢复旧 `bd sync` / `sync-branch` 流程。

如果你是外部贡献者，PR 里请直接写明对应的 `bd` 编号；若没有权限操作 `bd` 数据库，请在 PR 描述里说明原因和上下文。

### 开发规范

- Python 版本要求：`3.14+`
- 本仓库通过 `.python-version` 默认 pin 到 `3.14.5`；本地初始化建议直接执行 `uv sync --python 3.14.5 --extra dev`
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
- [specs](./specs/)：8111、发布签名、UI 线程、配置变体和质量门禁合同
- [PRIVACY.md](./PRIVACY.md)：匿名统计和更新服务行为
- [CHANGELOG.md](./CHANGELOG.md)：对用户可见的版本变化

### 测试与验证

代码改动至少应覆盖其中相关项：

- `uv run --extra dev ruff check .`
- `uv run --extra dev ruff format --check .`
- `tools\scripts\check_smoke.bat` 轻量本地回归
- `uv run python Bomana.pyw` 基础启动验证
- 受影响功能的静态自测
- 真实 War Thunder SB 实测（如果改动涉及 8111 数据、UI 刷新、热键、导航、HUD、启动器）
- 打包链路验证：`tools\scripts\build_portable.bat <Variant> <all|app|launcher>`（如果改动涉及发布或资源）
- Windows 打包启动器发布 smoke：
  `powershell -NoProfile -ExecutionPolicy Bypass -File tools\scripts\packaged_launcher_smoke.ps1 -Variant Enhanced`
  会构建签名启动器与应用包、复制到带空格和中文的路径、毒化 Python 环境变量/PATH，并自动验证启动器到应用窗口的交接。
  已有产物可用 `-NoBuild -ArtifactDir dist` 复用。

需要实机 8111 的手工 smoke 建议至少记录：

- War Thunder 已进入战斗，`http://localhost:8111` 可访问
- `/indicators`、`/state`、`/map_obj.json`、`/map_info.json` 有符合当前场景的数据
- Bomana 能启动、断连提示合理，恢复 8111 后 UI/导航状态能继续刷新
- 涉及 HUD、热键、托盘、音效或启动器时，额外验证对应入口的关闭与恢复流程

### 发布流程（维护者）

完整规则以 [release-signing spec](./specs/release-signing.md) 为准；这里保留维护者操作摘要。

1. 更新 `docs/CHANGELOG.md`
2. 更新 `bomana/metadata.py` 中的 `__version__`
3. 若 app 包需要新启动器能力，更新 `bomana/metadata.py` 中的 `PORTABLE_MIN_LAUNCHER_VERSION`
4. 根据发布目标做最少真实验证：
   - app 发布：启动器兼容性、下载/启动正常
   - launcher 发布：重查排队、保留一个 `app_previous/`、回退互换正常
5. 确认 GitHub Secrets 已配置并成对匹配，且不要生成、轮换、覆盖或上传发布私钥，除非已明确确认私钥保管方案。
6. 本地发布构建必须使用匹配的私钥/公钥；`tools/build_portable.py` 会拒绝空签名、缺失公钥或公钥与私钥不匹配的清单。
7. 推送标签：
   - `vX.Y.Z`：完整发布
   - `vX.Y.Z-app`：仅应用包
   - `vX.Y.Z-launcher`：仅启动器
8. GitHub Actions 会构建对应产物并创建/更新 Release；构建会用 Ed25519 签名 `manifest_<Variant>.json` 与 `launcher_manifest.json`
9. 国内更新服务必须走本机直推，避免 Actions 到腾讯云的 SSH/rsync 链路：
   `uv run python tools\deploy_update_assets.py --target app --version X.Y.Z`
   不要添加或触发 GitHub Actions 到腾讯云主机的部署 workflow。
10. 部署脚本会调用 `verify_release_manifest_signature` 校验公开腾讯云/EdgeOne 接口返回的签名。服务端只转发 Release 清单签名并补 URL/大小/来源等派生字段，不应保存发布私钥。不要引入 COS/CDN 等额外付费对象存储，除非用户明确批准成本。

### 有问题？

- 先看 [../README.md](../README.md)
- 再看 [ARCHITECTURE.md](./ARCHITECTURE.md) 和 [PITFALLS.md](./PITFALLS.md)
- 需要讨论时，请在 PR 中带上复现步骤、日志和对应 `bd` 编号

---

## English

### Project Rules First

- Use only the official War Thunder `localhost:8111` API. No memory reads, injection, or game-file edits.
- Track work in `bd (beads)` only; do not add markdown TODO systems.
- Cross-module invariants are canonical in [docs/specs](./specs/); entrypoint docs should stay as summaries and links.
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

### Lightweight Local Validation

The default local smoke path runs only fast regressions that do not require the game. There is no coverage target:

```bash
tools\scripts\check_smoke.bat
```

Equivalent command:

```bash
uv run --extra dev pytest
```

Optional development tools:

```bash
uv sync --extra dev
uv run --extra dev pytest
uv run --extra dev ruff check <changed Python paths>
uv run --extra dev ruff format --check <changed Python paths>
```

Code-changing tasks, including `bd`/beads tasks, must run Ruff before completion. Recommended final gates:

```bash
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
```

Pure documentation or issue-status-only tasks may state that Ruff is not applicable in the handoff.

Ruff rule posture: `RUF012` and `RUF013` are enabled in the default gate to make shared class state explicit and disallow implicit `Optional`. `RUF001`, `RUF002`, and `RUF003` are intentionally not enabled repository-wide; the project contains many Chinese UI strings, comments, docstrings, and font glyph lists that would create a large number of expected findings. For Unicode ambiguity investigations, run a targeted scan by file or path:

```bash
uv run --extra dev ruff check --select RUF001,RUF002,RUF003 <path>
```

### CI Quality Gate

`.github/workflows/quality.yml` runs lightweight Windows checks for pull requests and pushes to `main`:

- Python 3.14
- `uv sync --extra dev --frozen`
- `uv run --extra dev ruff check .`
- `uv run --extra dev ruff format --check .`
- `tools\scripts\check_smoke.bat`

There is intentionally no coverage threshold yet, and CI is not treated as a replacement for real War Thunder / `localhost:8111` smoke validation. Changes touching 8111, HUD, hotkeys, tray, navigation, or launcher behavior still need the manual runtime checks documented below.

### Test Organization

As tests grow, name files by system boundary rather than by temporary bug. See [../tests/README.md](../tests/README.md).

- `test_core_*.py`: core logic, telemetry, navigation, timer state, and data contracts
- `test_ui_*.py`: Tk UI behavior that can run with fakes or headless setup
- `test_launcher_*.py`: launcher update, install, rollback, manifest, and network fallback behavior
- `test_utils_*.py`: persistence, diagnostics, fonts, resource lookup, and shared helpers
- `test_quality_*.py`: quality gates and workflow configuration
- `tests/contracts/`: cross-module architecture contracts traced to `docs/specs/`

Existing test files can be folded into this scheme when they receive substantial edits. New or rewritten tests should use these prefixes and avoid boundary-free files such as `test_misc.py` or `test_regression.py`.

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

Before closing a code-changing `bd` task, run Ruff plus the relevant tests/build checks and record the result in the commit or handoff.

`bd` state lives in the local Dolt database; use `bd backup status` before handoff/closeout to check backup state. Automation should pass `--json`, and the old `bd sync` / `sync-branch` flow should not be restored.

If you are contributing from a fork and cannot update the project beads database directly, mention the intended `bd` linkage in your PR description.

### Development Expectations

- Python `3.14+`
- `.python-version` pins local setup to `3.14.5`; use `uv sync --python 3.14.5 --extra dev` for a fresh checkout
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
- [specs](./specs/)
- [PRIVACY.md](./PRIVACY.md)
- [CHANGELOG.md](./CHANGELOG.md)

### Validation

Relevant changes should be validated with some combination of:

- `uv run --extra dev ruff check .`
- `uv run --extra dev ruff format --check .`
- `tools\scripts\check_smoke.bat`
- `uv run python Bomana.pyw`
- focused local static checks
- real War Thunder SB smoke testing
- `tools\scripts\build_portable.bat <Variant> <all|app|launcher>` for packaging/release changes
- Windows packaged-launcher release smoke:
  `powershell -NoProfile -ExecutionPolicy Bypass -File tools\scripts\packaged_launcher_smoke.ps1 -Variant Enhanced`
  builds signed launcher/app assets, copies them to a path with spaces and Chinese characters, poisons Python environment variables/PATH, and automates the launcher-to-app window handoff.
  Use `-NoBuild -ArtifactDir dist` to reuse existing artifacts.

Manual 8111 smoke notes should cover:

- War Thunder is in a battle and `http://localhost:8111` is reachable
- `/indicators`, `/state`, `/map_obj.json`, and `/map_info.json` return data that matches the current scene
- Bomana starts, shows a reasonable disconnected state, and resumes UI/navigation updates when 8111 data returns
- HUD, hotkey, tray, sound, or launcher changes also verify the affected close/recovery path

### Release Notes For Maintainers

The complete rules are canonical in [release-signing spec](./specs/release-signing.md);
this section is the maintainer operation summary.

1. Update `docs/CHANGELOG.md`
2. Bump `__version__` in `bomana/metadata.py`
3. Update `PORTABLE_MIN_LAUNCHER_VERSION` in `bomana/metadata.py` if the app now requires newer launcher behavior
4. Smoke test the relevant release path
5. Confirm GitHub Secrets are configured as a matching pair. Do not generate, rotate, overwrite, or upload release private keys unless the private-key retention plan is explicit.
6. Local release builds must use matching private/public keys; `tools/build_portable.py` rejects empty signatures, missing public keys, and public keys that do not match the private key.
7. Push `vX.Y.Z`, `vX.Y.Z-app`, or `vX.Y.Z-launcher`
8. Let GitHub Actions build, Ed25519-sign, and publish the assets
9. Deploy Tencent/EdgeOne update assets locally from the maintainer workstation:
   `uv run python tools\deploy_update_assets.py --target app --version X.Y.Z`
   Do not add or trigger a GitHub Actions workflow that deploys to the Tencent host.
10. The deploy path calls `verify_release_manifest_signature` before trusting public update endpoints. The update service only forwards Release manifest signatures and adds URL/size/source fields; it must not store the release private key. Do not introduce COS/CDN paid object storage unless the user explicitly approves the cost.
