from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from launcher import core as launcher_core

# enforces: docs/specs/release-signing.md SIGN-01..SIGN-04
# enforces: docs/specs/schemas/app-manifest.schema.json
# enforces: docs/specs/schemas/launcher-manifest.schema.json

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = ROOT / "docs/specs/schemas"
SIGNATURE_FIELD = launcher_core.RELEASE_MANIFEST_SIGNATURE_FIELD
PRIVATE_KEY = "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"
PUBLIC_KEY = launcher_core.ed25519_public_key_from_private_key(PRIVATE_KEY)
SUPPORTED_SCHEMA_KEYWORDS = {
    "$schema",
    "$id",
    "$defs",
    "$ref",
    "additionalProperties",
    "const",
    "enum",
    "minLength",
    "minimum",
    "pattern",
    "properties",
    "required",
    "title",
    "type",
    "x-contract-kind",
    "x-signed-fields",
}


def load_schema(name: str) -> dict[str, Any]:
    path = SCHEMA_DIR / name
    assert path.exists(), path
    schema = json.loads(path.read_text(encoding="utf-8"))
    assert not unsupported_schema_keywords(schema)
    return schema


def unsupported_schema_keywords(value: Any, *, schema_object: bool = True) -> list[str]:
    unsupported: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if schema_object and key not in SUPPORTED_SCHEMA_KEYWORDS and not key.startswith("x-"):
                unsupported.append(key)
            child_is_schema = key not in {"properties", "$defs"}
            if key in {"properties", "$defs"} and isinstance(item, dict):
                for child in item.values():
                    unsupported.extend(unsupported_schema_keywords(child))
            else:
                unsupported.extend(unsupported_schema_keywords(item, schema_object=child_is_schema))
    elif isinstance(value, list):
        for item in value:
            unsupported.extend(unsupported_schema_keywords(item))
    return unsupported


def assert_schema_accepts(schema: dict[str, Any], payload: dict[str, Any]) -> None:
    for field in schema["required"]:
        assert field in payload, field
    properties = schema["properties"]
    if schema.get("additionalProperties") is False:
        assert not (set(payload) - set(properties))
    for field, value in payload.items():
        rules = properties.get(field)
        if not rules:
            continue
        if "$ref" in rules:
            rules = schema["$defs"]["manifest_signature"]
        assert_value_matches_rules(field, value, rules)


def assert_value_matches_rules(field: str, value: Any, rules: dict[str, Any]) -> None:
    expected_type = rules.get("type")
    if expected_type == "object":
        assert isinstance(value, dict), field
        for required in rules.get("required", []):
            assert required in value, f"{field}.{required}"
        for key, item in value.items():
            item_rules = rules.get("properties", {}).get(key)
            if item_rules:
                assert_value_matches_rules(f"{field}.{key}", item, item_rules)
        return
    if expected_type == "integer":
        assert isinstance(value, int) and not isinstance(value, bool), field
    elif expected_type == "string":
        assert isinstance(value, str), field
    if "const" in rules:
        assert value == rules["const"], field
    if "enum" in rules:
        assert value in rules["enum"], field
    if rules.get("minLength") is not None:
        assert len(value) >= rules["minLength"], field
    if "minimum" in rules:
        assert value >= rules["minimum"], field
    if "pattern" in rules:
        assert re.fullmatch(rules["pattern"], value), field


def sign_and_roundtrip(manifest: dict[str, Any]) -> dict[str, Any]:
    signed = launcher_core.sign_release_manifest(manifest, PRIVATE_KEY, key_id="test-key")
    return json.loads(json.dumps(signed, ensure_ascii=False))


def test_app_manifest_schema_matches_signed_payload_fields() -> None:
    schema = load_schema("app-manifest.schema.json")
    signed_fields = tuple(schema["x-signed-fields"])

    assert signed_fields == launcher_core._APP_MANIFEST_SIGNATURE_FIELDS

    manifest = {
        "schema_version": 1,
        "channel": "Enhanced",
        "app_version": "7.0.0",
        "min_launcher_version": "2.0.0",
        "entrypoint": "Bomana.pyw",
        "package_asset": "Bomana_app_Enhanced_v7.0.0.zip",
        "package_sha256": "a" * 64,
    }

    signed_manifest = sign_and_roundtrip(manifest)
    assert_schema_accepts(schema, signed_manifest)
    launcher_core.verify_release_manifest_signature(
        signed_manifest,
        public_keys={"test-key": PUBLIC_KEY},
        expected_kind="app",
    )
    signed_payload = json.loads(
        launcher_core.manifest_signature_payload(signed_manifest, expected_kind="app")
    )
    assert set(signed_payload) == set(signed_fields)
    assert SIGNATURE_FIELD not in signed_payload

    signed_manifest["package_sha256"] = "b" * 64
    with pytest.raises(RuntimeError, match="发布签名校验失败"):
        launcher_core.verify_release_manifest_signature(
            signed_manifest,
            public_keys={"test-key": PUBLIC_KEY},
            expected_kind="app",
        )


def test_launcher_manifest_schema_matches_signed_payload_fields() -> None:
    schema = load_schema("launcher-manifest.schema.json")
    signed_fields = tuple(schema["x-signed-fields"])

    assert signed_fields == launcher_core._LAUNCHER_MANIFEST_SIGNATURE_FIELDS

    manifest = {
        "schema_version": 1,
        "launcher_version": "2.0.0",
        "launcher_asset": "Bomana_launcher_v2.0.0.exe",
        "launcher_sha256": "b" * 64,
        "launcher_size_bytes": 123456,
    }

    signed_manifest = sign_and_roundtrip(manifest)
    assert_schema_accepts(schema, signed_manifest)
    launcher_core.verify_release_manifest_signature(
        signed_manifest,
        public_keys={"test-key": PUBLIC_KEY},
        expected_kind="launcher",
    )
    signed_payload = json.loads(
        launcher_core.manifest_signature_payload(signed_manifest, expected_kind="launcher")
    )
    assert set(signed_payload) == set(signed_fields)
    assert SIGNATURE_FIELD not in signed_payload

    signed_manifest["launcher_size_bytes"] += 1
    with pytest.raises(RuntimeError, match="发布签名校验失败"):
        launcher_core.verify_release_manifest_signature(
            signed_manifest,
            public_keys={"test-key": PUBLIC_KEY},
            expected_kind="launcher",
        )


def test_manifest_signature_schema_requires_ed25519_identity() -> None:
    for schema_name in ("app-manifest.schema.json", "launcher-manifest.schema.json"):
        schema = load_schema(schema_name)
        signature_schema = schema["$defs"]["manifest_signature"]

        assert SIGNATURE_FIELD in schema["required"]
        assert SIGNATURE_FIELD not in schema["x-signed-fields"]
        assert signature_schema["required"] == ["algorithm", "key_id", "signature"]
        assert signature_schema["properties"]["algorithm"]["const"] == "ed25519"
        assert signature_schema["properties"]["key_id"]["minLength"] == 1
        assert signature_schema["properties"]["signature"]["minLength"] == 1
