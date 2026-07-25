# enforces: docs/specs/weapon-fire-control.md WFC-19
"""Contract anchors for narrow player-visible trajectory calibration data."""

import json
from pathlib import Path

from bomana.config.static_data import VISIBLE_TRAJECTORY_REFERENCES_JSON
from bomana.core.visible_trajectory_reference import load_visible_trajectory_references

ROOT = Path(__file__).resolve().parents[2]


def test_runtime_visible_references_are_versioned_reached_targets_not_max_envelopes() -> None:
    path = ROOT / VISIBLE_TRAJECTORY_REFERENCES_JSON
    payload = json.loads(path.read_text(encoding="utf-8"))
    references = load_visible_trajectory_references(path)

    assert payload["schema_version"] == 1
    assert payload["meta"]["source_kind"] == "player_visible_war_thunder_ui"
    assert payload["meta"]["game_version"] == "2.57.1.33"
    assert any("not a maximum envelope" in item for item in payload["meta"]["limitations"])

    runtime = [reference for reference in references if reference.runtime_reference]
    assert len(runtime) == 1
    reference = runtime[0]
    assert reference.weapon_id == "us_2000lb_gbu31_usaf"
    assert reference.target_reached_observed
    assert reference.requested_horizontal_distance_m == reference.verified_reach_m
    assert abs(reference.points[-1].x_m - reference.verified_reach_m) <= 50.0
