from types import SimpleNamespace

import pytest

from launcher import subscription_access
from launcher.subscription_key_contract import (
    CHEEMSPAY_LICENSE_KEY_ID,
    CHEEMSPAY_LICENSE_PUBLIC_KEY_DER_BASE64URL,
    CHEEMSPAY_LICENSE_PUBLIC_KEYS,
)


def test_production_cheemspay_trust_root_is_versioned_and_used_by_source_runtime() -> None:
    assert CHEEMSPAY_LICENSE_KEY_ID == "prod-2026-01"
    assert (
        CHEEMSPAY_LICENSE_PUBLIC_KEY_DER_BASE64URL
        == "MCowBQYDK2VwAyEAN30P0bd6DN_fP7iMf1qkzBBkssGMHj0b18B81TsW6n8"
    )
    assert CHEEMSPAY_LICENSE_PUBLIC_KEYS == {
        CHEEMSPAY_LICENSE_KEY_ID: CHEEMSPAY_LICENSE_PUBLIC_KEY_DER_BASE64URL,
    }
    assert subscription_access.CHEEMSPAY_LICENSE_PUBLIC_KEYS == CHEEMSPAY_LICENSE_PUBLIC_KEYS


def test_runtime_rejects_a_generated_key_module_that_replaces_the_contract(monkeypatch) -> None:
    mismatched_generated_keys = SimpleNamespace(
        CHEEMSPAY_LICENSE_PUBLIC_KEYS={"future-key": "not-the-production-key"}
    )

    monkeypatch.setattr(
        subscription_access.importlib,
        "import_module",
        lambda _name: mismatched_generated_keys,
    )

    with pytest.raises(RuntimeError, match="repository trust contract"):
        subscription_access._load_pinned_license_keys()
