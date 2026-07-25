import math
import re
from pathlib import Path

from bomana.core.offline_rigidbody_catalog import load_catalog

CATALOG_PATH = Path("bomana/data/offline_rigidbody_catalog.bin")
SMALL_CALIBER_MM_RE = re.compile(r"(?<!\d)(\d{2,3})\s*_?mm(?![a-z])", re.IGNORECASE)


def test_small_mm_catalog_diameters_are_stored_as_meters() -> None:
    records = load_catalog(CATALOG_PATH)["records"]
    failures: list[str] = []

    for record_id, record in records.items():
        labels = (record_id, *record["aliases"])
        markers = {
            int(match.group(1))
            for label in labels
            for match in SMALL_CALIBER_MM_RE.finditer(label)
            if int(match.group(1)) < 200
        }
        if not markers:
            continue

        diameter = float(record["diameter_m"])
        if any(
            math.isclose(diameter, millimeters / 1000, rel_tol=0.0, abs_tol=1e-9)
            for millimeters in markers
        ):
            continue
        failures.append(
            f"{record_id}: diameter={diameter}, markers={sorted(markers)}"
        )

    assert not failures, "\n".join(failures)


def test_mortar_diameter_is_normalized_without_raw_source_metadata() -> None:
    record = load_catalog(CATALOG_PATH)["records"]["bomb_ussr_82mm_o_832"]

    assert record["diameter_m"] == 0.082
    assert set(record) == {
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
        "aliases",
    }
