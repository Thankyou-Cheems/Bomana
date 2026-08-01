"""Release-manifest verification helpers for the portable launcher."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from launcher.core import verify_release_manifest_signature


def project_verified_manifest_fields(
    manifest: dict[str, Any],
    fields: Iterable[str],
    *,
    manifest_label: str,
    expected_kind: str,
    public_keys: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Verify a release manifest before projecting trusted signed fields."""

    verify_release_manifest_signature(
        manifest,
        manifest_label=manifest_label,
        public_keys=public_keys,
        expected_kind=expected_kind,
    )
    return {field: manifest[field] for field in fields}
