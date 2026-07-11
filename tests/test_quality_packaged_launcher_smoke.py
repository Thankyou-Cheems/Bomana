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


def test_packaged_launcher_smoke_script_source_is_ascii_safe_for_windows_powershell() -> None:
    source = read_script()

    assert all(ord(char) < 128 for char in source)
    assert "New-UnicodeText" in source
    assert "0x4e2d, 0x6587" in source
    assert "0x8def, 0x5f84" in source
    assert "0x542f, 0x52a8, 0x5668" in source


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
    assert "Assert-StrictVersionAtLeast" in source
    assert '"app_version") "8.0.0"' in source
    assert '"min_launcher_version") "3.0.0"' in source
    assert '"launcher_version") "3.0.0"' in source


def test_packaged_launcher_smoke_stages_hostile_path_and_app_layout() -> None:
    source = read_script()

    assert "Bomana packaged smoke " in source
    assert "$script:TextChinese" in source
    assert "$script:TextPath" in source
    assert "install target " in source
    assert "$script:TextLauncher" in source
    assert "$script:TextReleaseAssets" in source
    assert "[System.IO.Compression.ZipFile]::ExtractToDirectory" in source
    assert '"app"' in source
    assert '"Bomana.pyw"' in source
    assert '"bomana_version.py"' in source
    assert '"bomana\\config\\__init__.py"' in source
    assert '"bomana\\config\\feature_profile.py"' in source
    assert '"bomana\\bin\\BomanaHotkeyBroker.exe"' in source
    assert '"bomana\\bin\\BomanaHotkeyBroker.sha256"' in source
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
    assert "user profile " in source
    assert "$script:TextUser" in source
    assert "LOCALAPPDATA" in source
    assert "APPDATA" in source
    assert "TEMP = $tempRoot" in source
    assert "$psi.UseShellExecute = $false" in source
    assert "$psi.EnvironmentVariables.Remove($key)" in source
    assert 'BOMANA_UPDATE_BASE_URL = "http://127.0.0.1:9"' in source
    assert 'download_source_mode = "primary"' in source
    assert "web_dashboard_autostart = $true" in source
    assert "web_dashboard_auto_open = $false" in source
    assert '"BOMANA_LAUNCHER_VERSION"' in source
    assert '"BOMANA_SOURCE_DEVELOPMENT"' in source


def test_packaged_launcher_smoke_verifies_gui_handoff_contract() -> None:
    source = read_script()

    assert "UIAutomationClient" in source
    assert "BomanaSmokeWin32" in source
    assert "Wait-AndInvokeLaunchButton" in source
    assert '$title -eq "WT Timer"' in source
    assert "Get-SmokeProcesses" in source
    assert "candidate.Path" in source
    assert "Stop-SmokeProcesses" in source
    assert "$script:LaunchButtonPattern" in source
    assert "Invoke-KeyboardLaunchShortcut" in source
    assert "keybd_event" in source
    assert "GetForegroundWindow" in source
    assert "finally" in source
    assert "0x542f, 0x52a8" in source
    assert "0x5668" in source
    assert "Wait-AppWindow" in source
    assert '$title -eq "WT Timer"' in source
    assert "interactive Windows desktop" in source
    assert "SkipGuiHandoff" in source

    launcher_source = (ROOT / "launcher.pyw").read_text(encoding="utf-8")
    assert 'self.root.bind("<Control-Return>", self._on_launch_shortcut' in launcher_source
    assert "def _on_launch_shortcut" in launcher_source
