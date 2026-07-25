from pathlib import Path

import pytest

from bomana.core.offline_rigidbody_catalog import (
    CATALOG_HEADER,
    CATALOG_PROFILE_ID,
    CATALOG_SCHEMA_VERSION,
    OfflineRigidbodyCatalogError,
    decode_catalog,
    encode_catalog,
    load_catalog,
)

CATALOG_PATH = Path("bomana/data/offline_rigidbody_catalog.bin")


def _sample_payload() -> dict:
    return {
        "schema_version": CATALOG_SCHEMA_VERSION,
        "profile_id": CATALOG_PROFILE_ID,
        "records": {
            "sample_250": {
                "mass_kg": 250.0,
                "diameter_m": 0.32,
                "length_m": 1.8,
                "display_drag_reference": 0.07,
                "prediction_kind": "freefall",
                "lift_area_scale": 1.0,
                "stabilizer_lever_m": 0.5,
                "axial_coefficient": 0.2,
                "normal_coefficient": 2.2,
                "normal_aoa_limit": 1.0,
                "aoa_drag_coefficient": 9.0,
                "aliases": ["sample_250_bomb"],
            }
        },
    }


def test_catalog_round_trip_is_deterministic() -> None:
    first = encode_catalog(_sample_payload())
    decoded = decode_catalog(first)

    assert encode_catalog(decoded) == first
    assert decoded["records"]["sample_250"]["aliases"] == ["sample_250_bomb"]


def test_catalog_integrity_rejects_tampering() -> None:
    encoded = bytearray(encode_catalog(_sample_payload()))
    encoded[-1] ^= 0x01

    with pytest.raises(OfflineRigidbodyCatalogError):
        decode_catalog(bytes(encoded))


def test_catalog_rejects_trailing_data() -> None:
    with pytest.raises(OfflineRigidbodyCatalogError, match="integrity"):
        decode_catalog(encode_catalog(_sample_payload()) + b"x")


def test_bundled_catalog_is_compact_and_omits_provenance_fields() -> None:
    raw = CATALOG_PATH.read_bytes()
    payload = load_catalog(CATALOG_PATH)
    records = payload["records"]

    assert raw.startswith(b"BRC2")
    assert len(raw) > CATALOG_HEADER.size
    assert len(raw) < 100_000
    assert len(records) == 437
    assert sum(bool(record["aliases"]) for record in records.values()) == 15
    assert set(payload) == {"schema_version", "profile_id", "records"}
    assert {
        "source_file",
        "source_commit",
        "source_repo",
        "mesh",
        "generated_at",
    }.isdisjoint({key for record in records.values() for key in record})
