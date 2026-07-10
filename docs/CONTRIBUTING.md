# 贡献指南 | Contributing Guide

Bomana is developed primarily on Windows with Python 3.14, `uv`, pytest, Ruff,
and `bd`. 中文和 English 共用同一套命令与规范，避免两套说明随时间漂移。

## 先看事实源 | Sources of Truth

| Topic | Canonical source |
| --- | --- |
| Repository routing and closeout | [`AGENTS.md`](../AGENTS.md) |
| Runtime, security, threading, config, and quality contracts | [`docs/specs/`](./specs/) |
| Current module and data flow | [`ARCHITECTURE.md`](./ARCHITECTURE.md) |
| Test placement | [`tests/README.md`](../tests/README.md) |
| Known failure modes | [`PITFALLS.md`](./PITFALLS.md) |
| User-visible changes | [`CHANGELOG.md`](./CHANGELOG.md) |

Do not restate a durable contract in an entrypoint document. Keep a short
summary and link to the owning spec. 不要在入口文档复制长期规则；摘要后链接到对应 spec。

Project-wide boundaries:

- Use only the official War Thunder `localhost:8111` API. No memory reads,
  injection, packet inspection, or game-file edits.
- Respect `ENABLE_*` flags in `bomana/config/feature_profile.py`.
- Track repository work in `bd`; do not add Markdown TODO/task systems.
- Keep launcher and Python App at ordinary integrity. Privileged hotkeys follow
  [`startup-elevation.md`](./specs/startup-elevation.md).

## 环境准备 | Setup

```powershell
git clone https://github.com/YOUR_USERNAME/Bomana.git
cd Bomana
uv sync --python 3.14.5 --extra dev
uv run python Bomana.pyw
```

`.python-version` pins the tested local interpreter. Packaging dependencies are
separate:

```powershell
uv sync --python 3.14.5 --extra build
```

## 工作流 | Workflow

1. Read the relevant spec and inspect existing tests.
2. Check or create the `bd` issue, then mark it `in_progress`.
3. Make the smallest coherent change and update its owning docs/tests.
4. Run the relevant focused checks and required full gates.
5. Close the issue only after verification; commit and push according to
   [`AGENTS.md`](../AGENTS.md).

常用 `bd` 命令：

```powershell
bd ready --json
bd update <issue-id> --status in_progress --json
bd create "Issue title" --description="Context" -t task -p 2 --deps discovered-from:<parent-id> --json
bd close <issue-id> --reason "Completed" --json
bd backup status
```

`bd` uses its local Dolt database as the issue source of truth. Do not restore
the retired `bd sync`, `sync-branch`, hand-started Dolt-server, or Markdown task
list workflows. External contributors who cannot access the project database
should name the intended issue linkage in the PR.

## 验证 | Validation

Every code-changing task runs these repository-wide gates:

```powershell
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run --extra dev pytest
```

`tools\scripts\check_smoke.bat` is the fast Windows entrypoint for the same
pytest suite. Pure documentation or issue-only changes may report Ruff as not
applicable, but documentation tests should still run when docs change.

Additional gates by area:

| Changed area | Additional validation |
| --- | --- |
| `native/hotkey_broker/`, `tools/build_hotkey_broker.py` | `cargo fmt --check --manifest-path native/hotkey_broker/Cargo.toml`; `cargo test --locked --manifest-path native/hotkey_broker/Cargo.toml`; `uv run python tools/build_hotkey_broker.py --mode dev` |
| Release/build/launcher assets | relevant build tests and packaged-launcher smoke |
| 8111, HUD, hotkeys, tray, navigation | focused automated tests plus clearly reported real War Thunder smoke |
| Unicode ambiguity investigation | `uv run --extra dev ruff check --select RUF001,RUF002,RUF003 <path>` |

CI uses Windows, Python 3.14, frozen `uv` dependencies, Ruff, pytest, and native
broker checks. Automated tests never count as real War Thunder / 8111 evidence.

For packaged launcher changes, use:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools\scripts\packaged_launcher_smoke.ps1 -Variant Enhanced
```

The smoke builds or reuses release-shaped assets, moves them through paths with
spaces and Chinese characters, poisons ambient Python variables/PATH, and checks
the launcher-to-App handoff. Use `-NoBuild -ArtifactDir dist` to reuse artifacts.

## 测试维护 | Test Maintenance

Follow [`tests/README.md`](../tests/README.md). In particular:

- Put cross-module rules in `tests/contracts/` with an exact first-line
  `# enforces: docs/specs/<spec>.md CLAUSE-01` header.
- Prefer pytest for new tests and name substantial new files by system boundary.
- Extend the authoritative check instead of adding a weaker duplicate.
- Keep manual runtime evidence separate from automated results.

## 文档维护 | Documentation Maintenance

- Update [`ARCHITECTURE.md`](./ARCHITECTURE.md) for module, directory, ownership,
  or major data-flow changes.
- Amend the owning file under [`specs/`](./specs/) when an invariant changes,
  then update classified contract coverage.
- Add a short [`PITFALLS.md`](./PITFALLS.md) entry for a new failure mode.
- Update [`CHANGELOG.md`](./CHANGELOG.md) for user-visible behavior.
- Keep temporary plans and task status in `bd`, not as top-level docs.
- Keep public wording short, natural, and bilingual where it helps users.

## 提交与 PR | Commits and Pull Requests

- Use focused branches and Conventional Commits.
- On `main`, generate the message with `/gc` (`git-commit-smart`) before commit.
- Preserve unrelated workspace changes; never weaken or delete tests just to
  make a gate pass.
- PR descriptions should include the objective, `bd` issue, checks run, manual
  smoke status, and screenshots for visible UI changes.

## 发布维护者摘要 | Maintainer Release Summary

The complete trust and deployment contract is
[`release-signing.md`](./specs/release-signing.md). This section lists operations,
not a competing policy.

1. Update `docs/CHANGELOG.md` and the authoritative version in
   `bomana/metadata.py` and/or `launcher/metadata.py`. If an App package now
   needs newer launcher behavior, update `PORTABLE_MIN_LAUNCHER_VERSION` too.
2. Confirm the matching Ed25519 manifest-signing secrets; never generate,
   rotate, print, upload, or replace private keys without an approved retention
   plan.
3. Push `vX.Y.Z`, `vX.Y.Z-app`, or `vX.Y.Z-launcher`; GitHub Actions builds,
   signs manifests, and adds Artifact Attestations to final assets.
4. Download the finished Release locally and deploy Tencent/EdgeOne assets from
   the maintainer workstation only:

```powershell
gh release download vX.Y.Z --dir dist
uv run python tools/deploy_update_assets.py --target app|launcher|all --version X.Y.Z
```

GitHub Actions must not SSH, rsync, or scp release assets to Tencent. Artifact
Attestations prove GitHub build provenance; they do not create an Authenticode
publisher identity for Windows UAC.

## 获取帮助 | Getting Help

Start with [`README.md`](../README.md), then the relevant spec,
[`ARCHITECTURE.md`](./ARCHITECTURE.md), and [`PITFALLS.md`](./PITFALLS.md).
Include reproduction steps, logs, affected paths, and the `bd` issue when asking
for review.
