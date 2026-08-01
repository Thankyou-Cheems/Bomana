from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "scripts" / "packaged_launcher_smoke.ps1"


def read_script() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_public_packaged_smoke_uses_guarded_powershell_header() -> None:
    assert read_script().splitlines()[:4] == [
        "#requires -Version 7",
        "Set-StrictMode -Version 3.0",
        "$ErrorActionPreference = 'Stop'",
        "$PSNativeCommandUseErrorActionPreference = $true",
    ]


def test_public_packaged_smoke_builds_only_public_editions() -> None:
    source = read_script()

    assert "@('Standard', 'Lite')" in source
    assert "Enhanced" not in source
    assert "--target', 'all'" in source
    assert "$syncArgs" in source
    assert "$buildArgs" in source
    assert "& uv @syncArgs" in source
    assert "& uv @buildArgs" in source


def test_public_packaged_smoke_verifies_release_integrity_and_closure() -> None:
    source = read_script()

    assert "Assert-SignedManifest" in source
    assert "Assert-FileSha256" in source
    assert "System.IO.Compression.ZipFile" in source
    assert "subscriberPrefixes" in source
    assert "bomana/web/" in source
    assert "bomana/core/offline_rigidbody_" in source
    assert "bomana/core/weapon_" in source
    assert "bomana/ui/bombing_" in source
    assert "subscriber_paths_present = $false" in source


def test_public_packaged_smoke_is_ascii_and_returns_structured_output() -> None:
    source = read_script()

    assert all(ord(char) < 128 for char in source)
    assert "ConvertTo-Json -Depth 6 -Compress" in source
    assert "Format-" not in source
