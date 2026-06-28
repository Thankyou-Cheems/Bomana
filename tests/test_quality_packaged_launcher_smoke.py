import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "scripts" / "packaged_launcher_smoke.ps1"


def read_script() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_packaged_launcher_smoke_script_parses_with_powershell() -> None:
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if powershell is None:
        pytest.skip("PowerShell parser is not available")

    script_literal = str(SCRIPT).replace("'", "''")
    command = (
        "$tokens = $null; $errors = $null; "
        f"[System.Management.Automation.Language.Parser]::ParseFile('{script_literal}', "
        "[ref]$tokens, [ref]$errors) | Out-Null; "
        "if ($errors.Count -gt 0) { $errors | Format-List *; exit 1 }"
    )
    subprocess.run(
        [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
        check=True,
    )


def test_packaged_launcher_smoke_builds_and_requires_signed_artifacts() -> None:
    source = read_script()

    assert 'ValidateSet("Enhanced", "Standard", "Lite")' in source
    assert '"tools\\build_portable.py"' in source
    assert '$env:PYTHONPATH = ""' in source
    assert '$env:PYTHONHOME = ""' in source
    assert '$env:PYTHONNOUSERSITE = "1"' in source
    assert '"--frozen",' in source
    assert '"--extra",' in source
    assert '"build",' in source
    assert '"--target",' in source
    assert '"all",' in source
    assert "build_portable.bat" not in source
    assert "Assert-ManifestSignature" in source
    assert "manifest_signature.algorithm must be ed25519" in source
    assert "manifest_signature.key_id must not be empty" in source
    assert "manifest_signature.signature must not be empty" in source
    assert "package_sha256" in source
    assert "launcher_sha256" in source
    assert "launcher_size_bytes" in source


def test_packaged_launcher_smoke_stages_hostile_path_and_app_layout() -> None:
    source = read_script()

    assert "Bomana packaged smoke 中文 路径" in source
    assert "install target 启动器 路径" in source
    assert "release assets 发布产物" in source
    assert "[System.IO.Compression.ZipFile]::ExtractToDirectory" in source
    assert '"app"' in source
    assert '"Bomana.pyw"' in source
    assert '"bomana\\config.py"' in source
    assert '"bomana\\metadata.py"' in source
    assert "Assert-PathWithin" in source
    assert "Remove-Item -LiteralPath $workRoot -Recurse -Force" in source


def test_packaged_launcher_smoke_poisons_python_for_packaged_launch() -> None:
    source = read_script()

    assert "New-PoisonBin" in source
    assert '"python.exe"' in source
    assert '"python3.exe"' in source
    assert '"py.exe"' in source
    assert '"uv.exe"' in source
    assert "PYTHONHOME" in source
    assert "PYTHONPATH" in source
    assert "PYTHONNOUSERSITE" in source
    assert "PYTHONUSERBASE" in source
    assert "user profile 用户" in source
    assert "LOCALAPPDATA" in source
    assert "APPDATA" in source
    assert "TEMP = $tempRoot" in source
    assert "$psi.UseShellExecute = $false" in source
    assert "$psi.EnvironmentVariables.Remove($key)" in source
    assert 'BOMANA_UPDATE_BASE_URL = "http://127.0.0.1:9"' in source
    assert 'download_source_mode = "primary"' in source


def test_packaged_launcher_smoke_verifies_gui_handoff_contract() -> None:
    source = read_script()

    assert "UIAutomationClient" in source
    assert "BomanaSmokeWin32" in source
    assert "Wait-AndInvokeLaunchButton" in source
    assert 'if ($name -match "^启动(?!器)")' in source
    assert 'if ($className -like "*Button*" -and $text -match "^启动(?!器)")' in source
    assert "Wait-AppWindow" in source
    assert '$title -eq "WT Timer"' in source
    assert "interactive Windows desktop" in source
    assert "SkipGuiHandoff" in source
