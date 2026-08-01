# Test Library Guide | 测试库指南

This file is a placement guide, not a second quality specification. Normative
requirements and closeout commands are canonical in
[`docs/specs/testing-quality-gates.md`](../docs/specs/testing-quality-gates.md).

本文件只说明测试放置位置，不重复定义质量规范。门禁、实机验证边界与收尾要求以
[`docs/specs/testing-quality-gates.md`](../docs/specs/testing-quality-gates.md) 为准。

## Layers | 分层

| Layer | Purpose | Examples |
| --- | --- | --- |
| `tests/contracts/` | Cross-module invariants with exact spec-clause headers | manifest schemas, 8111 boundary, Tk threading |
| `test_core_*` | Core state, telemetry, navigation, timer, and ballistics behavior | `test_core_8111_stability.py`, `test_core_helpers.py` |
| `test_ui_*` and presenter/runtime tests | Headless UI models, Tk adapters, geometry, lifecycle | `test_ui_geometry.py`, `test_panel_presenter.py` |
| `test_launcher_*` | Launcher download, verification, install, rollback, and handoff | `test_launcher_update_service.py` |
| `test_quality_*` | Repository, workflow, package, docs, and release gates | `test_quality_documentation.py` |
| `tests/fixtures/8111/` | Hash-locked real-session inputs for deterministic core replay | `test_8111_replay.py` |
| focused utility tests | Persistence, sound, fonts, resource lookup, portability | `test_file_utils_persistence.py` |

Existing descriptive filenames remain valid. New or substantially rewritten
tests should use the closest system-boundary prefix and avoid temporary names
such as `test_regression.py`, migration phases, or issue IDs.

现有描述性文件名可以保留；新增或大改测试应按系统边界命名，避免把临时阶段、issue
编号或笼统的 `regression` 固化为长期目录结构。

## Placement Rules | 放置规则

- Put a bug regression beside the behavior it protects.
- Put broad architecture rules in `tests/contracts/` and start the file with
  `# enforces: docs/specs/<spec>.md CLAUSE-01`.
- Keep real War Thunder / `localhost:8111` validation manual and report it
  separately from automated results.
- Prefer pytest-style tests for new coverage; do not rewrite stable tests only
  for syntax uniformity.
- Keep one authoritative test for each static repository rule. Extend it instead
  of adding a weaker duplicate in another layer.
- Keep ad-hoc recordings under ignored `recordings/`. Promote only intentional,
  validated captures through `tools/build_8111_replay_fixture.py`; never hand-edit
  a tracked fixture or its expected timeline.

- 行为回归放在对应功能边界附近；跨模块不变量放入 `tests/contracts/`。
- 真实 War Thunder / 8111 验证始终单独记录，不能包装成自动化测试结论。
- 新测试优先使用 pytest；不要仅为形式统一而重写稳定测试。
- 仓库静态规则只保留一个权威测试，优先扩展现有测试而不是复制弱化版本。
- 临时录制保留在被忽略的 `recordings/`；只有明确选定的完整录制才能通过导入工具进入
  `tests/fixtures/8111/`，不要手工修改 fixture 或期望时间线。

## Entry Points | 入口

- Fast suite: `tools\scripts\check_smoke.bat`
- Direct pytest: `uv run --extra dev pytest`
- Contract map: `uv run --extra dev pytest tests/contracts`
- Contributor workflow: [`docs/CONTRIBUTING.md`](../docs/CONTRIBUTING.md)
