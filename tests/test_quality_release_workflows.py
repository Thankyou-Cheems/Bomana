import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_tencent_deploy_workflow_is_manual_only() -> None:
    workflow = (ROOT / ".github/workflows/deploy-manifests-to-server.yml").read_text(
        encoding="utf-8"
    )

    assert "workflow_dispatch:" in workflow
    assert "workflow_run:" not in workflow
    assert "Build and Release Bomana Portable" not in workflow


def test_local_deploy_script_validates_required_assets(tmp_path: Path) -> None:
    script_path = ROOT / "tools/deploy_update_assets.py"
    spec = importlib.util.spec_from_file_location("deploy_update_assets", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    with pytest.raises(FileNotFoundError, match="Bomana_app_Enhanced_v9.9.9.zip"):
        module.required_assets(tmp_path, "app", "9.9.9", "1.0.0")
