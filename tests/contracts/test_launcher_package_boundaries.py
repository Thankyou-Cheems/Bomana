# enforces: docs/specs/release-signing.md SIGN-03, SIGN-09, SIGN-11

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from launcher import core as launcher_core
from launcher import manifest_sources, metadata, verify

ROOT = Path(__file__).resolve().parents[2]


class GuardedManifest(dict[str, Any]):
    def __init__(self) -> None:
        super().__init__(
            {
                "schema_version": 1,
                "channel": "Enhanced",
                "app_version": "8.0.0",
                "min_launcher_version": "3.0.0",
                "entrypoint": "Bomana.pyw",
                "package_asset": "Bomana_app_Enhanced_v8.0.0.zip",
                "package_sha256": "a" * 64,
                "launcher_version": "3.0.0",
                "launcher_asset": "Bomana_launcher_v3.0.0.exe",
                "launcher_sha256": "b" * 64,
                "launcher_size_bytes": 123,
            }
        )
        self.projected_fields: list[str] = []

    def __getitem__(self, key: str) -> Any:
        self.projected_fields.append(key)
        return super().__getitem__(key)


@pytest.mark.parametrize("expected_kind", ["app", "launcher"])
def test_project_verified_manifest_fields_does_not_trust_fields_before_verify(
    monkeypatch: pytest.MonkeyPatch,
    expected_kind: str,
) -> None:
    manifest = GuardedManifest()
    verifier_calls: list[str] = []

    def reject_unsigned_manifest(*_args, **kwargs) -> None:
        verifier_calls.append(str(kwargs["expected_kind"]))
        raise RuntimeError("signature rejected before projection")

    monkeypatch.setattr(verify, "verify_release_manifest_signature", reject_unsigned_manifest)

    with pytest.raises(RuntimeError, match="signature rejected before projection"):
        verify.project_verified_manifest_fields(
            manifest,
            ["app_version", "package_sha256"],
            manifest_label="contract ",
            expected_kind=expected_kind,
        )

    assert verifier_calls == [expected_kind]
    assert manifest.projected_fields == []


def test_verified_app_manifest_projection_exposes_only_trusted_runtime_fields() -> None:
    manifest = {
        "schema_version": 1,
        "channel": "Enhanced",
        "app_version": "8.0.0",
        "min_launcher_version": "3.0.0",
        "entrypoint": "Bomana.pyw",
        "package_asset": "Bomana_app_Enhanced_v8.0.0.zip",
        "package_sha256": "a" * 64,
    }

    signed = launcher_core.sign_release_manifest(
        manifest,
        "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
        key_id="test-key",
    )
    public_key = launcher_core.ed25519_public_key_from_private_key(
        "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"
    )

    def verify_with_test_key(manifest_arg, **kwargs) -> None:
        kwargs.pop("public_keys", None)
        launcher_core.verify_release_manifest_signature(
            manifest_arg,
            public_keys={"test-key": public_key},
            **kwargs,
        )

    original = verify.verify_release_manifest_signature
    verify.verify_release_manifest_signature = verify_with_test_key
    try:
        trusted = manifest_sources.verified_app_manifest_fields(
            signed,
            channel="Enhanced",
            label="manifest_Enhanced.json ",
            default_entrypoint="Bomana.pyw",
        )
    finally:
        verify.verify_release_manifest_signature = original

    assert trusted == {
        "remote_version": "8.0.0",
        "min_launcher_version": "3.0.0",
        "package_asset": "Bomana_app_Enhanced_v8.0.0.zip",
        "package_sha256": "a" * 64,
        "entrypoint": "Bomana.pyw",
    }


def test_launcher_entry_uses_package_metadata_version_source() -> None:
    launcher_entry = (ROOT / "launcher.pyw").read_text(encoding="utf-8")

    assert "from launcher.metadata import LAUNCHER_VERSION" in launcher_entry
    assert f'LAUNCHER_VERSION = "{metadata.LAUNCHER_VERSION}"' not in launcher_entry


def test_launcher_core_helpers_live_in_launcher_package() -> None:
    assert not (ROOT / "bomana" / "launcher_core.py").exists()

    checked_paths = [
        ROOT / "launcher.pyw",
        *sorted((ROOT / "launcher").glob("*.py")),
        ROOT / "tools" / "build_portable.py",
        ROOT / "tools" / "deploy_update_assets.py",
    ]
    offenders = [
        path.relative_to(ROOT).as_posix()
        for path in checked_paths
        if (
            "bomana.launcher_core" in path.read_text(encoding="utf-8")
            or "from bomana import launcher_core" in path.read_text(encoding="utf-8")
        )
    ]

    assert offenders == []
