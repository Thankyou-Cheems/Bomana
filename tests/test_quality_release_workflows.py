import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from bomana import metadata
from launcher import core as launcher_core

ROOT = Path(__file__).resolve().parents[1]


def build_workflow_source() -> str:
    return (ROOT / ".github/workflows/build.yml").read_text(encoding="utf-8")


def workflow_sources() -> list[tuple[Path, str]]:
    return [
        (path, path.read_text(encoding="utf-8"))
        for path in sorted((ROOT / ".github/workflows").glob("*.yml"))
    ]


def load_tool_module(name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_tencent_deploy_is_local_only() -> None:
    deploy_workflow = ROOT / ".github/workflows/deploy-manifests-to-server.yml"
    release_spec = (ROOT / "docs/specs/release-signing.md").read_text(encoding="utf-8")

    assert not deploy_workflow.exists()
    for clause_id in ("SIGN-03", "SIGN-05", "SIGN-07"):
        assert f"`{clause_id}`" in release_spec
    assert "tools/deploy_update_assets.py" in release_spec


def test_docs_do_not_restore_github_to_tencent_deploy_fallback() -> None:
    checked_docs = (
        ROOT / "README.md",
        ROOT / "docs/ARCHITECTURE.md",
        ROOT / "docs/CONTRIBUTING.md",
        ROOT / "docs/QUICKSTART.md",
    )
    combined = "\n".join(path.read_text(encoding="utf-8") for path in checked_docs)

    assert "deploy-manifests-to-server.yml" not in combined
    assert "workflow_dispatch` only as a fallback" not in combined
    assert "manual-only fallback" not in combined
    assert "GitHub-hosted Actions must not SSH, rsync, or scp" in combined


def test_local_deploy_script_validates_signed_manifests_and_public_endpoints() -> None:
    source = (ROOT / "tools/deploy_update_assets.py").read_text(encoding="utf-8")

    assert "validate_local_release_assets" in source
    assert "verify_public" in source
    assert "verify_release_manifest_signature" in source
    assert 'expected_kind="launcher"' in source
    assert "public asset sha256 mismatch" in source
    assert "versioned_manifest" in source
    assert "launcher_manifest_v{launcher_version}.json" in source
    assert 'choices=("app", "launcher", "all")' in source
    assert 'if target == "terrain":' not in source
    assert "hashlib.sha256(asset_src.read_bytes())" not in source


def test_build_release_workflow_reads_version_from_metadata_without_dev_fallback() -> None:
    workflow = build_workflow_source()

    assert "bomana/metadata.py" in workflow
    assert 'bomana/config.py || echo "dev"' not in workflow
    assert "无法从 bomana/metadata.py 提取 __version__" in workflow


def test_build_release_workflow_passes_manifest_signing_secret() -> None:
    workflow = build_workflow_source()

    assert "BOMANA_RELEASE_ED25519_PRIVATE_KEY" in workflow
    assert "${{ secrets.BOMANA_RELEASE_ED25519_PRIVATE_KEY }}" in workflow
    assert "BOMANA_RELEASE_ED25519_PUBLIC_KEY" in workflow
    assert "${{ secrets.BOMANA_RELEASE_ED25519_PUBLIC_KEY }}" in workflow
    assert "BOMANA_RELEASE_SIGNING_KEY_ID: bomana-release-2026-06" in workflow


def test_launcher_build_pins_cheemspay_receipt_public_key() -> None:
    workflow = build_workflow_source()

    assert "CHEEMSPAY_LICENSE_PUBLIC_KEY_DER_BASE64URL" in workflow
    assert "${{ secrets.CHEEMSPAY_LICENSE_PUBLIC_KEY_DER_BASE64URL }}" in workflow
    assert "CHEEMSPAY_LICENSE_KEY_ID: prod-2026-01" in workflow


def test_public_release_has_no_subscriber_terrain_builder() -> None:
    workflow = build_workflow_source()

    assert '- { name: "超级爆弹版", slug: "Enhanced"' not in workflow
    assert '- { name: "标准版", slug: "Standard"' in workflow
    assert '- { name: "精简版", slug: "Lite"' in workflow
    assert "超级爆弹版（`Enhanced`）不会进入公开 Release" in workflow
    assert "tools/prepare_builtin_terrain.py" not in workflow
    assert "tools/build_terrain_release.py" not in workflow
    assert not (ROOT / ".github/workflows/build-terrain.yml").exists()
    assert not (ROOT / "tools/build_terrain_release.py").exists()


def test_public_release_builds_lite_green_bundle_without_launcher() -> None:
    workflow = build_workflow_source()

    assert "  build_green:" in workflow
    assert '"--variant", "Lite"' in workflow
    assert '"--target", "green"' in workflow
    assert "Bomana_Green_Lite_v${{ needs.prepare.outputs.version }}.zip" in workflow
    assert "checksums_green_Lite.txt" in workflow
    assert "内含 Python 运行时，无需启动器" in workflow
    assert "needs: [prepare, quality, build_app, build_green, build_launcher]" in workflow
    assert "needs.build_green.result" in workflow


def test_hotkey_broker_is_zero_install_and_release_assets_are_attested() -> None:
    workflow = build_workflow_source()
    quality_workflow = (ROOT / ".github/workflows/quality.yml").read_text(encoding="utf-8")
    tool = (ROOT / "tools/build_hotkey_broker.py").read_text(encoding="utf-8")
    portable = (ROOT / "tools/build_portable.py").read_text(encoding="utf-8")

    assert "tools/build_hotkey_broker.py" in workflow
    assert "TemporaryDirectory" in tool
    assert "HOTKEY_BROKER_CHECKSUM_NAME" in portable
    assert "resolve_hotkey_broker" in portable
    assert "cargo fmt --check --manifest-path native/hotkey_broker/Cargo.toml" in workflow
    assert "cargo test --locked --manifest-path native/hotkey_broker/Cargo.toml" in workflow
    assert "tools/build_hotkey_broker.py --mode dev" in workflow
    assert "cargo fmt --check --manifest-path native/hotkey_broker/Cargo.toml" in quality_workflow
    assert "cargo test --locked --manifest-path native/hotkey_broker/Cargo.toml" in quality_workflow
    assert "tools/build_hotkey_broker.py --mode dev" in quality_workflow
    assert workflow.count("actions/attest@a1948c3f048ba23858d222213b7c278aabede763 # v4.1.1") == 3
    assert workflow.count("id-token: write") == 3
    assert workflow.count("attestations: write") == 3
    assert workflow.count("artifact-metadata: write") == 3
    assert "gh attestation verify <文件> --repo Thankyou-Cheems/Bomana" in workflow
    combined = f"{workflow}\n{quality_workflow}\n{tool}\n{portable}"
    for forbidden in (
        "BomanaHotkeyBrokerSetup.exe",
        "hotkey_broker_setup",
        "BOMANA_AUTHENTICODE_PFX_B64",
        "BOMANA_AUTHENTICODE_PFX_PASSWORD",
        "signtool",
    ):
        assert forbidden not in combined


@pytest.mark.parametrize(
    "relative_path",
    ("tools/build_portable.py", "tools/deploy_update_assets.py"),
)
def test_release_tool_entrypoints_run_without_pythonpath(relative_path: str) -> None:
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    env["PYTHONNOUSERSITE"] = "1"

    result = subprocess.run(
        [sys.executable, relative_path, "--help"],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    assert "--target" in result.stdout


def test_build_release_workflow_isolates_python_env_and_uses_frozen_uv() -> None:
    workflow = build_workflow_source()

    assert 'PYTHONNOUSERSITE: "1"' in workflow
    assert 'PYTHONPATH: ""' in workflow
    assert 'PYTHONHOME: ""' in workflow
    assert "uv sync --extra dev --frozen" in workflow
    assert "uv sync --extra build --frozen" in workflow
    assert "uv run --frozen --extra dev ruff check ." in workflow
    assert "uv run --frozen --extra dev ruff format --check ." in workflow
    assert "uv run --frozen python tools/build_portable.py" in workflow


def test_build_release_workflow_validates_release_version_inputs() -> None:
    workflow = build_workflow_source()

    assert "set -euo pipefail" in workflow
    assert "SEMVER_RE='^[0-9]+[.][0-9]+[.][0-9]+$'" in workflow
    assert "TAG_RE='^v([0-9]+[.][0-9]+[.][0-9]+)(-(app|launcher))?$'" in workflow
    assert 'validate_version "workflow_dispatch version"' in workflow
    assert 'validate_version "source version"' in workflow
    assert 'validate_version "launcher version"' in workflow
    assert "release tag must match vX.Y.Z, vX.Y.Z-app, or vX.Y.Z-launcher" in workflow


def test_manual_package_build_does_not_publish_release_by_default() -> None:
    workflow = build_workflow_source()

    assert "publish_release:" in workflow
    assert 'description: "构建完成后创建 GitHub Release（预发布打包请保持关闭）"' in workflow
    assert "default: false" in workflow
    assert "github.event_name == 'workflow_dispatch' && inputs.publish_release == true" in workflow


def test_build_release_workflow_avoids_shell_expression_injection() -> None:
    workflow = build_workflow_source()

    assert "INPUT_VERSION: ${{ github.event.inputs.version || '' }}" in workflow
    assert "INPUT_BUILD_TARGET: ${{ github.event.inputs.build_target || '' }}" in workflow
    assert 'VERSION="${{ github.event.inputs.version }}"' not in workflow
    assert 'BUILD_TARGET="${{ github.event.inputs.build_target }}"' not in workflow
    assert '--version "${{ needs.prepare.outputs.version }}"' not in workflow
    assert '--version "${{ needs.prepare.outputs.launcher_version }}"' not in workflow
    assert '--version "$env:BUILD_VERSION"' in workflow
    assert '--version "$env:BUILD_LAUNCHER_VERSION"' in workflow


def test_build_release_workflow_scopes_write_token_to_release_job() -> None:
    workflow = build_workflow_source()
    top_permissions = workflow.index("permissions:\n  contents: read")
    jobs = workflow.index("jobs:")
    release = workflow.index("  release:")
    release_permissions = workflow.index("    permissions:\n      contents: write", release)
    release_steps = workflow.index("    steps:", release)

    assert top_permissions < jobs
    assert release < release_permissions < release_steps
    assert "permissions:\n  contents: write" not in workflow[:jobs]


def test_github_workflows_pin_actions_to_full_commit_sha() -> None:
    uses_lines: list[tuple[Path, str]] = []
    for path, workflow in workflow_sources():
        for line in workflow.splitlines():
            stripped = line.strip()
            if stripped.startswith("uses: ") and not stripped.startswith(
                ("uses: ./", "uses: docker://")
            ):
                uses_lines.append((path, stripped))

    assert uses_lines
    assert all(re.search(r"@[0-9a-f]{40}(?:\s+#\s+\S+)?$", line) for _path, line in uses_lines)


def test_local_portable_build_scripts_isolate_python_env_and_use_frozen_uv() -> None:
    for relative_path in (
        "tools/scripts/build_portable.bat",
        "tools/scripts/build_launcher.bat",
    ):
        script = (ROOT / relative_path).read_text(encoding="utf-8")
        env_index = script.index('set "PYTHONNOUSERSITE=1"')
        uv_index = script.index('set "UV_CMD=uv"')

        assert 'set "PYTHONPATH="' in script
        assert 'set "PYTHONHOME="' in script
        assert env_index < uv_index
        assert "sync --extra build --frozen" in script
        assert "run --frozen python tools\\build_portable.py" in script


def test_local_deploy_script_validates_required_assets(tmp_path: Path) -> None:
    script_path = ROOT / "tools/deploy_update_assets.py"
    spec = importlib.util.spec_from_file_location("deploy_update_assets", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    with pytest.raises(FileNotFoundError, match="Bomana_app_Standard_v9.9.9.zip"):
        module.required_assets(tmp_path, "app", "9.9.9", "1.0.0")


def test_local_deploy_script_accepts_build_portable_all_checksum_names(tmp_path: Path) -> None:
    deploy = load_tool_module("deploy_update_assets_all", "tools/deploy_update_assets.py")
    launcher_version = "2.0.0"

    for channel in deploy.PUBLIC_CHANNELS:
        (tmp_path / f"Bomana_app_{channel}_v{metadata.__version__}.zip").touch()
        (tmp_path / f"manifest_{channel}.json").touch()
        (tmp_path / f"CHANGELOG_{channel}_v{metadata.__version__}.md").touch()
        (tmp_path / f"checksums_app_{channel}.txt").touch()
    (tmp_path / f"Bomana_launcher_v{launcher_version}.exe").touch()
    (tmp_path / "launcher_manifest.json").touch()
    (tmp_path / "checksums_launcher.txt").touch()

    assets = deploy.required_assets(tmp_path, "all", metadata.__version__, launcher_version)

    assert tmp_path / "checksums_app_Standard.txt" in assets
    assert tmp_path / "checksums_app_Lite.txt" in assets
    assert tmp_path / "checksums_launcher.txt" in assets
    assert not any("terrain" in path.name.lower() for path in assets)


def test_local_deploy_script_quotes_remote_env_values() -> None:
    deploy = load_tool_module("deploy_update_assets_quote", "tools/deploy_update_assets.py")

    command = deploy.remote_env_command(
        stage_dir="x'$(touch /tmp/pwn)",
        remote_root="/opt/stacks/bomana-update",
        target="app",
        app_version="1.0.0",
        launcher_version="2.0.0",
    )

    assert command.startswith("STAGE_DIR='x'\"'\"'$(touch /tmp/pwn)' ")
    assert 'STAGE_DIR="x' not in command


def test_local_deploy_script_remote_stage_assets_are_filename_only() -> None:
    source = (ROOT / "tools/deploy_update_assets.py").read_text(encoding="utf-8")

    assert "def stage_asset_path" in source
    assert '"/" in asset_name or "\\\\" in asset_name' in source
    assert "candidate.relative_to(stage_root)" in source
    assert 'manifest["package_asset"]' in source
    assert 'manifest["launcher_asset"]' in source
    assert "def require_manifest_signature" in source
    assert "missing manifest_signature" in source
    assert "verify_release_manifest_signature" in source
    assert "BOMANA_RELEASE_ED25519_PUBLIC_KEY" in source
    assert "validate_local_release_assets" in source
    assert 'expected_kind="launcher"' in source
    assert "public asset sha256 mismatch" in source
    assert "require_edgeone_public_base" in source
    assert "require_edgeone_response" in source
    assert "EO-LOG-UUID" in source


def test_edgeone_distribution_guard_rejects_origin_and_redirect_bypass() -> None:
    deploy = load_tool_module(
        "deploy_update_assets_edgeone_guard",
        "tools/deploy_update_assets.py",
    )

    assert (
        deploy.require_edgeone_public_base("https://bomanaupdate.ruikang.wang/")
        == "https://bomanaupdate.ruikang.wang"
    )
    with pytest.raises(RuntimeError, match="must use the EdgeOne update host"):
        deploy.require_edgeone_public_base("https://124.221.119.113")
    with pytest.raises(RuntimeError, match="must use the EdgeOne update host"):
        deploy.require_edgeone_public_url(
            "https://origin.example.test/downloads/app.zip",
            label="test asset",
        )

    class Response:
        def __init__(self) -> None:
            self.headers = {"EO-LOG-UUID": "edge-request-id"}

        @staticmethod
        def geturl() -> str:
            return "https://origin.example.test/downloads/app.zip"

    with pytest.raises(RuntimeError, match="must use the EdgeOne update host"):
        deploy.require_edgeone_response(
            Response(),
            requested_url="https://bomanaupdate.ruikang.wang/downloads/app.zip",
        )


def test_edgeone_distribution_guard_requires_edge_response_marker() -> None:
    deploy = load_tool_module(
        "deploy_update_assets_edgeone_marker",
        "tools/deploy_update_assets.py",
    )
    url = "https://bomanaupdate.ruikang.wang/downloads/app.zip"

    class MissingMarkerResponse:
        def __init__(self) -> None:
            self.headers: dict[str, str] = {}

        @staticmethod
        def geturl() -> str:
            return url

    with pytest.raises(RuntimeError, match="EO-LOG-UUID missing"):
        deploy.require_edgeone_response(MissingMarkerResponse(), requested_url=url)

    class EdgeOneResponse:
        def __init__(self) -> None:
            self.headers = {"EO-LOG-UUID": "edge-request-id"}

        @staticmethod
        def geturl() -> str:
            return url

    deploy.require_edgeone_response(EdgeOneResponse(), requested_url=url)


def test_public_endpoint_verifiers_validate_signature_before_fields() -> None:
    deploy_source = (ROOT / "tools/deploy_update_assets.py").read_text(encoding="utf-8")
    deploy_decode = deploy_source.index('payload = json.loads(response.read().decode("utf-8"))')
    deploy_verify = deploy_source.index("verify_release_manifest_signature(", deploy_decode)
    deploy_field_check = deploy_source.index(
        'if str(payload.get(field, "")) != expected', deploy_decode
    )
    assert deploy_decode < deploy_verify < deploy_field_check


def test_local_deploy_script_prevalidates_signed_launcher_assets(
    tmp_path: Path,
    monkeypatch,
) -> None:
    deploy = load_tool_module("deploy_update_assets_prevalidate", "tools/deploy_update_assets.py")
    private_key = "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"
    public_key = launcher_core.ed25519_public_key_from_private_key(private_key)
    monkeypatch.setenv("BOMANA_RELEASE_ED25519_PUBLIC_KEY", public_key)
    monkeypatch.setenv("BOMANA_RELEASE_SIGNING_KEY_ID", "test-key")
    launcher = tmp_path / "Bomana_launcher_v2.0.0.exe"
    launcher.write_bytes(b"launcher")
    manifest = launcher_core.sign_release_manifest(
        {
            "schema_version": 1,
            "launcher_version": "2.0.0",
            "launcher_asset": launcher.name,
            "launcher_sha256": deploy.sha256_file(launcher),
            "launcher_size_bytes": launcher.stat().st_size,
        },
        private_key,
        key_id="test-key",
    )
    (tmp_path / "launcher_manifest.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )

    deploy.validate_local_release_assets(tmp_path, "launcher", metadata.__version__, "2.0.0")

    manifest["launcher_sha256"] = "0" * 64
    (tmp_path / "launcher_manifest.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="发布签名校验失败"):
        deploy.validate_local_release_assets(tmp_path, "launcher", metadata.__version__, "2.0.0")


def test_public_verify_downloads_launcher_asset_and_checks_signed_sha(monkeypatch) -> None:
    deploy = load_tool_module("deploy_update_assets_public_verify", "tools/deploy_update_assets.py")
    private_key = "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"
    public_key = launcher_core.ed25519_public_key_from_private_key(private_key)
    monkeypatch.setenv("BOMANA_RELEASE_ED25519_PUBLIC_KEY", public_key)
    monkeypatch.setenv("BOMANA_RELEASE_SIGNING_KEY_ID", "test-key")
    launcher_bytes = b"launcher"
    launcher_sha = launcher_core.sha256_bytes(launcher_bytes)
    payload = launcher_core.sign_release_manifest(
        {
            "schema_version": 1,
            "launcher_version": "2.0.0",
            "launcher_asset": "Bomana_launcher_v2.0.0.exe",
            "launcher_sha256": launcher_sha,
            "launcher_size_bytes": len(launcher_bytes),
        },
        private_key,
        key_id="test-key",
    )
    payload.update(
        {
            "package_url": "/downloads/Bomana_launcher_v2.0.0.exe",
            "package_sha256": launcher_sha,
        }
    )

    class Response:
        def __init__(self, body: bytes) -> None:
            self._body = body
            self._offset = 0

        def __enter__(self):
            return self

        def __exit__(self, _exc_type, _exc, _tb) -> None:
            return None

        def read(self, size: int = -1) -> bytes:
            if size < 0:
                size = len(self._body) - self._offset
            chunk = self._body[self._offset : self._offset + size]
            self._offset += len(chunk)
            return chunk

    requested: list[str] = []

    def fake_urlopen(url: str, timeout: int):
        requested.append(url)
        if "/api/v1/launcher" in url:
            return Response(json.dumps(payload).encode("utf-8"))
        if "/downloads/" in url:
            return Response(launcher_bytes)
        raise AssertionError(url)

    monkeypatch.setattr(deploy, "urlopen", fake_urlopen)

    deploy.verify_public(
        host="unused",
        public_base_url="https://updates.example.test",
        target="launcher",
        app_version=metadata.__version__,
        launcher_version="2.0.0",
        require_edgeone=False,
    )

    assert "https://updates.example.test/downloads/Bomana_launcher_v2.0.0.exe" in requested


def test_legacy_build_delegates_version_info_to_secure_builder() -> None:
    script = (ROOT / "tools/scripts/build.bat").read_text(encoding="utf-8")
    portable = (ROOT / "tools/build_portable.py").read_text(encoding="utf-8")

    assert "tools\\build_portable.py" in script
    assert "--target app" in script
    assert "create_version_info.py" not in script
    assert "file_version_info.txt" not in script
    assert "def generate_version_info(" in portable
    assert "version_file = generate_version_info(work_dir, version)" in portable
    assert 'cmd.extend(["--version-file", str(version_file)])' in portable


def test_build_portable_rejects_app_version_mismatch() -> None:
    build_portable = load_tool_module("build_portable_app_version", "tools/build_portable.py")

    build_portable.validate_requested_version(
        metadata.__version__,
        "app",
        metadata.__version__,
        "2.0.0",
    )
    with pytest.raises(RuntimeError, match="app expected"):
        build_portable.validate_requested_version(
            "9.9.9",
            "app",
            metadata.__version__,
            "2.0.0",
        )


def test_build_portable_rejects_launcher_version_mismatch() -> None:
    build_portable = load_tool_module("build_portable_launcher_version", "tools/build_portable.py")
    launcher_version = "2.0.0"

    build_portable.validate_requested_version(
        launcher_version,
        "launcher",
        metadata.__version__,
        launcher_version,
    )
    with pytest.raises(RuntimeError, match="launcher expected"):
        build_portable.validate_requested_version(
            "9.9.9",
            "launcher",
            metadata.__version__,
            launcher_version,
        )


def test_build_portable_all_rejects_ambiguous_single_version() -> None:
    build_portable = load_tool_module("build_portable_all_version", "tools/build_portable.py")

    with pytest.raises(RuntimeError, match="launcher expected"):
        build_portable.validate_requested_version(
            metadata.__version__,
            "all",
            metadata.__version__,
            "2.0.0",
        )


def test_build_portable_writes_deployable_checksum_names(tmp_path: Path) -> None:
    build_portable = load_tool_module("build_portable_checksums", "tools/build_portable.py")
    app_zip = tmp_path / f"Bomana_app_Enhanced_v{metadata.__version__}.zip"
    launcher = tmp_path / "Bomana_launcher_v2.0.0.exe"
    app_zip.write_bytes(b"app")
    launcher.write_bytes(b"launcher")

    app_checksum = build_portable.write_checksum_info(
        tmp_path,
        "Enhanced",
        metadata.__version__,
        None,
        app_zip,
        None,
        "app",
    )
    launcher_checksum = build_portable.write_checksum_info(
        tmp_path,
        "Universal",
        None,
        "2.0.0",
        None,
        launcher,
        "launcher",
    )

    assert app_checksum.name == "checksums_app_Enhanced.txt"
    assert launcher_checksum.name == "checksums_launcher.txt"
    assert not (tmp_path / "checksums_portable_Enhanced.txt").exists()
