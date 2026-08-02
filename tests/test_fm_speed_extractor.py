from __future__ import annotations

import json
from pathlib import Path

from tools.fm_speed_extractor import _extract_unit_mapping


def test_extract_unit_mapping_normalizes_legacy_leading_fm_slash(tmp_path: Path) -> None:
    path = tmp_path / "tornado_ids_de_assta1_france_killstreak.blkx"
    path.write_text(
        json.dumps({"fmFile": "/fm/tornado_ids_de_assta1.blk"}),
        encoding="utf-8",
    )

    assert _extract_unit_mapping(path) == (
        "tornado_ids_de_assta1_france_killstreak",
        "tornado_ids_de_assta1",
    )


def test_extract_unit_mapping_normalizes_backslashes_and_blkx_suffix(tmp_path: Path) -> None:
    path = tmp_path / "rafale_m_f3r.blkx"
    path.write_text(
        json.dumps({"fmFile": "\\fm\\rafale_m_f3r.blkx"}),
        encoding="utf-8",
    )

    assert _extract_unit_mapping(path) == ("rafale_m_f3r", "rafale_m_f3r")


def test_extract_unit_mapping_keeps_french_f16_killstreak_on_shared_fm(tmp_path: Path) -> None:
    path = tmp_path / "f_16a_block_15_adf_france_killstreak.blkx"
    path.write_text(
        json.dumps({"fmFile": "fm/f_16a_block_15_adf.blk"}),
        encoding="utf-8",
    )

    assert _extract_unit_mapping(path) == (
        "f_16a_block_15_adf_france_killstreak",
        "f_16a_block_15_adf",
    )


def test_runtime_reference_normalization_handles_legacy_path() -> None:
    from bomana.core.overspeed import SpeedLimitDatabase

    assert SpeedLimitDatabase._normalize_fm_reference("/fm/rafale_c_f3.blk") == "rafale_c_f3"
