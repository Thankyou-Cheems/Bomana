import json
import math
import re
from pathlib import Path

CCRP_DATA_PATH = Path("bomana/data/ccrp_bomb_params.json")
SMALL_CALIBER_MM_RE = re.compile(r"(?<!\d)(\d{2,3})\s*_?mm(?![a-z])", re.IGNORECASE)


def _small_caliber_mm_markers(bomb_id: str, params: dict) -> list[tuple[str, int]]:
    fields = {
        "id": bomb_id,
        "source_file": str(params.get("source_file", "")),
        "mesh": str(params.get("mesh", "")),
    }

    markers: list[tuple[str, int]] = []
    for field, text in fields.items():
        for match in SMALL_CALIBER_MM_RE.finditer(text):
            mm = int(match.group(1))
            if mm < 200:
                markers.append((field, mm))
    return markers


def test_small_mm_ccrp_calibers_are_stored_as_meters() -> None:
    payload = json.loads(CCRP_DATA_PATH.read_text(encoding="utf-8"))

    failures: list[str] = []
    for bomb_id, params in payload["ballistic_params"].items():
        markers = _small_caliber_mm_markers(bomb_id, params)
        if not markers:
            continue

        caliber = float(params["caliber"])
        expected_calibers = {mm / 1000 for _, mm in markers}
        if any(
            math.isclose(caliber, expected_caliber, rel_tol=0.0, abs_tol=1e-9)
            for expected_caliber in expected_calibers
        ):
            continue

        marker_text = ", ".join(f"{field}={mm}mm" for field, mm in markers)
        expected_text = ", ".join(str(value) for value in sorted(expected_calibers))
        failures.append(
            f"{bomb_id}: caliber={caliber}, expected one of {expected_text} from {marker_text}"
        )

    assert not failures, "\n".join(failures)
