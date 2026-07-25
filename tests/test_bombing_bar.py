from types import SimpleNamespace

import pytest

from bomana.ui.bombing_bar import CCRPTimingStabilizer, build_ccrp_cue_projection


def _snapshot(**overrides):
    values = {
        "bombing_valid": True,
        "release_status": "too_far",
        "time_to_release": 20.0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_ccrp_cue_converges_monotonically_toward_release() -> None:
    far = build_ccrp_cue_projection(_snapshot(time_to_release=20.0))
    approach = build_ccrp_cue_projection(
        _snapshot(release_status="approaching", time_to_release=4.0)
    )
    near = build_ccrp_cue_projection(
        _snapshot(release_status="approaching", time_to_release=1.0)
    )
    ready = build_ccrp_cue_projection(
        _snapshot(release_status="ready", time_to_release=0.1)
    )

    assert far.gap_ratio > approach.gap_ratio > near.gap_ratio > ready.gap_ratio > 0.0
    assert ready.pulse is True
    assert ready.status_text == "释放"


def test_ccrp_cue_crosses_center_after_release() -> None:
    passed = build_ccrp_cue_projection(
        _snapshot(release_status="passed", time_to_release=0.0)
    )

    assert passed.gap_ratio < 0.0
    assert "越过" in passed.status_text


def test_ccrp_cue_fails_closed_without_valid_solution() -> None:
    unavailable = build_ccrp_cue_projection(
        _snapshot(bombing_valid=False, release_status="ready", time_to_release=0.1)
    )

    assert unavailable.available is False
    assert unavailable.pulse is False
    assert unavailable.gap_ratio > 0.4


def test_ccrp_cue_piecewise_scale_is_continuous_at_status_boundaries() -> None:
    ready_edge = build_ccrp_cue_projection(
        _snapshot(release_status="ready", time_to_release=0.5)
    )
    approach_start = build_ccrp_cue_projection(
        _snapshot(release_status="approaching", time_to_release=0.5)
    )
    approach_end = build_ccrp_cue_projection(
        _snapshot(release_status="approaching", time_to_release=5.0)
    )
    far_start = build_ccrp_cue_projection(
        _snapshot(release_status="too_far", time_to_release=5.0)
    )

    assert ready_edge.gap_ratio == pytest.approx(approach_start.gap_ratio)
    assert approach_end.gap_ratio == pytest.approx(far_start.gap_ratio)


def test_ccrp_timing_stabilizer_tracks_deadline_through_noisy_samples() -> None:
    stabilizer = CCRPTimingStabilizer()
    samples = (
        (100.0, 4.00),
        (100.1, 3.65),
        (100.2, 3.95),
        (100.3, 3.35),
        (100.4, 3.60),
    )

    gaps = [
        stabilizer.update(
            _snapshot(release_status="approaching", time_to_release=remaining),
            now=now,
        ).gap_ratio
        for now, remaining in samples
    ]

    assert all(later < earlier for earlier, later in zip(gaps[:-1], gaps[1:], strict=True))
    between_samples = stabilizer.projection(now=100.45)
    assert between_samples.gap_ratio < gaps[-1]


def test_ccrp_timing_stabilizer_crosses_at_predicted_release_deadline() -> None:
    stabilizer = CCRPTimingStabilizer()
    stabilizer.update(
        _snapshot(release_status="ready", time_to_release=0.08),
        now=200.0,
    )

    before = stabilizer.projection(now=200.079)
    crossed = stabilizer.projection(now=200.08)

    assert before.pulse is True
    assert before.gap_ratio > 0.0
    assert crossed.pulse is False
    assert crossed.gap_ratio < 0.0


def test_ccrp_timing_stabilizer_removes_solution_to_ui_age() -> None:
    stabilizer = CCRPTimingStabilizer()
    stabilizer.update(
        _snapshot(
            release_status="ready",
            time_to_release=0.30,
            bombing_solution_age_s=0.10,
        ),
        now=300.0,
    )

    assert stabilizer.projection(now=300.199).gap_ratio > 0.0
    assert stabilizer.projection(now=300.20).gap_ratio < 0.0


def test_ccrp_ready_cue_reaches_visual_center_at_zero() -> None:
    centered = build_ccrp_cue_projection(
        _snapshot(release_status="ready", time_to_release=0.0)
    )

    assert centered.gap_ratio == 0.0
    assert centered.status_text == "释放"
    assert centered.pulse is True


def test_ccrp_ready_window_keeps_counting_down_before_release_prompt() -> None:
    early_ready = build_ccrp_cue_projection(
        _snapshot(release_status="ready", time_to_release=0.30)
    )

    assert early_ready.status_text == "T−0.30s"
    assert early_ready.pulse is False


def test_ccrp_cue_integrates_lateral_instability_message() -> None:
    projection = build_ccrp_cue_projection(
        _snapshot(
            bombing_valid=False,
            release_status="invalid",
            bombing_unavailable_reason="release_dynamics_unresolved",
            has_bombing_target=True,
            altitude_m=1000.0,
        )
    )

    assert projection.status_text == "侧飞 / 转弯过大"
    assert projection.available is False
