"""Compact, integrity-checked catalog for the offline rigid-body model."""

from __future__ import annotations

import hashlib
import json
import math
import re
import struct
import zlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

CATALOG_SCHEMA_VERSION: Final = 2
CATALOG_PROFILE_ID: Final = "offline_rigidbody_v2"
CATALOG_MAGIC: Final = b"BRC2\x00\x00\x00\x00"
CATALOG_HEADER: Final = struct.Struct(">8sI32s")
MAX_CATALOG_RECORDS: Final = 1_000
MAX_COMPRESSED_BYTES: Final = 4 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES: Final = 16 * 1024 * 1024
RECORD_ID_RE: Final = re.compile(r"^[a-z0-9][a-z0-9_-]{0,95}$")
PREDICTION_KINDS: Final = frozenset({"freefall", "guided_glide", "high_drag"})
REQUIRED_RECORD_FIELDS: Final = frozenset(
    {
        "mass_kg",
        "diameter_m",
        "length_m",
        "display_drag_reference",
        "prediction_kind",
        "lift_area_scale",
        "stabilizer_lever_m",
        "axial_coefficient",
        "normal_coefficient",
        "normal_aoa_limit",
        "aoa_drag_coefficient",
    }
)
OPTIONAL_RECORD_FIELDS: Final = frozenset({"aliases"})


class OfflineRigidbodyCatalogError(ValueError):
    """Raised when the bundled rigid-body catalog fails validation."""


def _finite_number(
    record: Mapping[str, Any],
    field: str,
    *,
    positive: bool = False,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    try:
        value = float(record[field])
    except (KeyError, TypeError, ValueError) as exc:
        raise OfflineRigidbodyCatalogError(
            f"invalid catalog field: {field}"
        ) from exc
    if not math.isfinite(value) or (positive and value <= 0.0):
        raise OfflineRigidbodyCatalogError(f"invalid catalog field: {field}")
    if minimum is not None and value < minimum:
        raise OfflineRigidbodyCatalogError(f"catalog field below range: {field}")
    if maximum is not None and value > maximum:
        raise OfflineRigidbodyCatalogError(f"catalog field above range: {field}")
    return value


def validate_catalog_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and normalize a decoded catalog payload."""

    if set(payload) != {"schema_version", "profile_id", "records"}:
        raise OfflineRigidbodyCatalogError("invalid catalog root fields")
    if payload.get("schema_version") != CATALOG_SCHEMA_VERSION:
        raise OfflineRigidbodyCatalogError("unsupported catalog schema")
    if payload.get("profile_id") != CATALOG_PROFILE_ID:
        raise OfflineRigidbodyCatalogError("unsupported catalog profile")
    raw_records = payload.get("records")
    if (
        not isinstance(raw_records, Mapping)
        or not 0 < len(raw_records) <= MAX_CATALOG_RECORDS
    ):
        raise OfflineRigidbodyCatalogError("invalid catalog record collection")

    records: dict[str, dict[str, Any]] = {}
    aliases_seen: set[str] = set()
    for raw_id, raw_record in raw_records.items():
        record_id = str(raw_id)
        if not RECORD_ID_RE.fullmatch(record_id) or not isinstance(raw_record, Mapping):
            raise OfflineRigidbodyCatalogError("invalid catalog record")
        fields = set(raw_record)
        if (
            not REQUIRED_RECORD_FIELDS.issubset(fields)
            or not fields.issubset(REQUIRED_RECORD_FIELDS | OPTIONAL_RECORD_FIELDS)
        ):
            raise OfflineRigidbodyCatalogError(
                f"invalid catalog record fields: {record_id}"
            )
        prediction_kind = str(raw_record.get("prediction_kind") or "")
        if prediction_kind not in PREDICTION_KINDS:
            raise OfflineRigidbodyCatalogError(
                f"invalid prediction kind: {record_id}"
            )

        aliases_raw = raw_record.get("aliases", [])
        if not isinstance(aliases_raw, list) or len(aliases_raw) > 8:
            raise OfflineRigidbodyCatalogError(f"invalid aliases: {record_id}")
        aliases: list[str] = []
        for raw_alias in aliases_raw:
            alias = str(raw_alias)
            if (
                not RECORD_ID_RE.fullmatch(alias)
                or alias == record_id
                or alias in raw_records
                or alias in aliases_seen
            ):
                raise OfflineRigidbodyCatalogError(f"invalid alias: {record_id}")
            aliases_seen.add(alias)
            aliases.append(alias)

        records[record_id] = {
            "mass_kg": _finite_number(
                raw_record, "mass_kg", positive=True, maximum=100_000.0
            ),
            "diameter_m": _finite_number(
                raw_record, "diameter_m", positive=True, maximum=10.0
            ),
            "length_m": _finite_number(
                raw_record, "length_m", positive=True, maximum=100.0
            ),
            "display_drag_reference": _finite_number(
                raw_record,
                "display_drag_reference",
                minimum=0.0,
                maximum=10_000.0,
            ),
            "prediction_kind": prediction_kind,
            "lift_area_scale": _finite_number(
                raw_record, "lift_area_scale", positive=True, maximum=100.0
            ),
            "stabilizer_lever_m": _finite_number(
                raw_record,
                "stabilizer_lever_m",
                minimum=-100.0,
                maximum=100.0,
            ),
            "axial_coefficient": _finite_number(
                raw_record, "axial_coefficient", positive=True, maximum=100.0
            ),
            "normal_coefficient": _finite_number(
                raw_record,
                "normal_coefficient",
                minimum=-100.0,
                maximum=100.0,
            ),
            "normal_aoa_limit": _finite_number(
                raw_record, "normal_aoa_limit", positive=True, maximum=100.0
            ),
            "aoa_drag_coefficient": _finite_number(
                raw_record,
                "aoa_drag_coefficient",
                minimum=-100.0,
                maximum=100.0,
            ),
            "aliases": sorted(aliases),
        }

    return {
        "schema_version": CATALOG_SCHEMA_VERSION,
        "profile_id": CATALOG_PROFILE_ID,
        "records": dict(sorted(records.items())),
    }


def encode_catalog(payload: Mapping[str, Any]) -> bytes:
    """Encode a validated payload into the deterministic BRC2 container."""

    normalized = validate_catalog_payload(payload)
    raw = json.dumps(
        normalized,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    if len(raw) > MAX_UNCOMPRESSED_BYTES:
        raise OfflineRigidbodyCatalogError("catalog payload exceeds size limit")
    compressed = zlib.compress(raw, level=9)
    if len(compressed) > MAX_COMPRESSED_BYTES:
        raise OfflineRigidbodyCatalogError("compressed catalog exceeds size limit")
    return (
        CATALOG_HEADER.pack(
            CATALOG_MAGIC,
            len(raw),
            hashlib.sha256(raw).digest(),
        )
        + compressed
    )


def decode_catalog(data: bytes) -> dict[str, Any]:
    """Decode and verify one BRC2 catalog from bounded bytes."""

    if len(data) < CATALOG_HEADER.size or len(data) > (
        CATALOG_HEADER.size + MAX_COMPRESSED_BYTES
    ):
        raise OfflineRigidbodyCatalogError("catalog container size is invalid")
    magic, declared_size, expected_digest = CATALOG_HEADER.unpack_from(data)
    if magic != CATALOG_MAGIC or not 0 < declared_size <= MAX_UNCOMPRESSED_BYTES:
        raise OfflineRigidbodyCatalogError("catalog header is invalid")

    decompressor = zlib.decompressobj()
    try:
        raw = decompressor.decompress(
            data[CATALOG_HEADER.size :],
            MAX_UNCOMPRESSED_BYTES + 1,
        )
        if decompressor.unconsumed_tail or len(raw) > MAX_UNCOMPRESSED_BYTES:
            raise OfflineRigidbodyCatalogError("catalog expands beyond size limit")
        raw += decompressor.flush(MAX_UNCOMPRESSED_BYTES + 1 - len(raw))
    except zlib.error as exc:
        raise OfflineRigidbodyCatalogError("catalog compression is invalid") from exc
    if (
        not decompressor.eof
        or decompressor.unused_data
        or len(raw) != declared_size
        or hashlib.sha256(raw).digest() != expected_digest
    ):
        raise OfflineRigidbodyCatalogError("catalog integrity check failed")

    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OfflineRigidbodyCatalogError("catalog payload is invalid") from exc
    if not isinstance(payload, Mapping):
        raise OfflineRigidbodyCatalogError("catalog payload root is invalid")
    return validate_catalog_payload(payload)


def load_catalog(path: Path) -> dict[str, Any]:
    """Load a bounded, integrity-checked catalog from disk."""

    try:
        size = path.stat().st_size
        if size > CATALOG_HEADER.size + MAX_COMPRESSED_BYTES:
            raise OfflineRigidbodyCatalogError("catalog file exceeds size limit")
        return decode_catalog(path.read_bytes())
    except OSError as exc:
        raise OfflineRigidbodyCatalogError(f"unable to read catalog: {exc}") from exc


__all__ = [
    "CATALOG_MAGIC",
    "CATALOG_PROFILE_ID",
    "CATALOG_SCHEMA_VERSION",
    "OfflineRigidbodyCatalogError",
    "decode_catalog",
    "encode_catalog",
    "load_catalog",
    "validate_catalog_payload",
]
