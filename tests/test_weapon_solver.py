"""Behavioral coverage for conservative weapon-envelope models."""

import pytest

from bomana.config.settings import WeaponBallisticModelConfig
from bomana.core.weapon_solver import WeaponSolver, isa_air_density


def _powered_weapon(**overrides):
    weapon = {
        "id": "test_agm",
        "role": "agm",
        "propulsion": "powered",
        "control": "guided",
        "planform": "normal",
        "mass_start_kg": 100.0,
        "mass_end_kg": 75.0,
        "caliber_m": 0.25,
        "cx_k": 0.45,
        "drag_cx": 0.04,
        "wing_area_mult": 1.0,
        "time_life_s": 25.0,
        "start_speed_mps": 0.0,
        "min_distance_m": 300.0,
        "hard_max_distance_m": 50000.0,
        "stat_card_range_m": 1200.0,
        "max_speed_mps": 900.0,
        "motor_stages": [
            {"duration_s": 3.0, "thrust_n": 9000.0, "mass_end_kg": 85.0},
            {"duration_s": 4.0, "thrust_n": 4000.0, "mass_end_kg": 75.0},
        ],
    }
    weapon.update(overrides)
    return weapon


def _aam_envelope_weapon(**overrides):
    weapon = _powered_weapon(
        id="us_aim_120c_5",
        role="aam",
        min_distance_m=30.0,
        hard_max_distance_m=10_000.0,
        model_unsupported_reasons=["conditional_propulsion_autopilot"],
        guidance_envelope={
            "tables": [
                {
                    "table": "table0",
                    "altitude_m": 5000.0,
                    "fighter_mach": [0.9, 1.2],
                    "target_mach": [0.9, 0.9],
                    "target_mach2_mult": -1.0,
                    "range_min_m": [548.949, 1247.15, 632.025, 1288.37],
                    "range_max_m": [13562.0, 81819.2, 15747.1, 92218.4],
                    "time_max_s": [39.0833, 70.3742, 41.1873, 118.921],
                },
                {
                    "table": "table1",
                    "altitude_m": 10000.0,
                    "fighter_mach": [0.9, 1.2],
                    "target_mach": [0.9, 0.9],
                    "target_mach2_mult": -1.0,
                    "range_min_m": [913.146, 2079.19, 884.301, 2260.35],
                    "range_max_m": [31951.9, 107881.0, 45065.3, 114953.0],
                    "time_max_s": [86.772, 120.0, 113.982, 120.0],
                },
            ]
        },
    )
    weapon.update(overrides)
    return weapon


def _solve(weapon, *, ballistic_model=None, **overrides):
    inputs = {
        "launch_altitude_m": 1000.0,
        "launch_speed_mps": 250.0,
        "target_distance_m": 3000.0,
        "target_relative_deg": 0.0,
        "target_kind": "zone",
        "target_name": "Target",
    }
    inputs.update(overrides)
    return WeaponSolver(ballistic_model=ballistic_model).solve(weapon, **inputs)


def _glide_weapon(**overrides):
    weapon = {
        "id": "us_gbu_39",
        "role": "bomb",
        "propulsion": "unpowered",
        "control": "guided",
        "planform": "glide",
        "wing_area_mult": 3.5,
        "time_life_s": 700.0,
        "min_distance_m": 0.0,
        "hard_max_distance_m": 0.0,
        "guidance_kind": "ins_gnss",
        "guidance": {"type": "ins", "seeker": "gnss"},
    }
    weapon.update(overrides)
    return weapon


def test_isa_density_decreases_with_altitude() -> None:
    assert isa_air_density(0.0) == pytest.approx(1.225, rel=0.002)
    assert isa_air_density(10000.0) < isa_air_density(5000.0) < isa_air_density(0.0)


def test_powered_range_responds_to_altitude_and_launch_speed() -> None:
    weapon = _powered_weapon()

    low = _solve(weapon, launch_altitude_m=0.0, launch_speed_mps=180.0)
    high = _solve(weapon, launch_altitude_m=8000.0, launch_speed_mps=180.0)
    fast = _solve(weapon, launch_altitude_m=0.0, launch_speed_mps=320.0)

    assert high.max_range_m > low.max_range_m
    assert fast.max_range_m > low.max_range_m
    assert {low.quality, high.quality, fast.quality} == {"two_dimensional"}


def test_datamine_start_speed_replaces_carrier_speed_and_then_obeys_cap() -> None:
    inherited_slow = _solve(
        _powered_weapon(start_speed_mps=0.0),
        launch_speed_mps=120.0,
        target_distance_m=1500.0,
    )
    inherited_fast = _solve(
        _powered_weapon(start_speed_mps=0.0),
        launch_speed_mps=320.0,
        target_distance_m=1500.0,
    )
    fixed_from_slow_carrier = _solve(
        _powered_weapon(start_speed_mps=220.0),
        launch_speed_mps=120.0,
        target_distance_m=1500.0,
    )
    fixed_from_fast_carrier = _solve(
        _powered_weapon(start_speed_mps=220.0),
        launch_speed_mps=320.0,
        target_distance_m=1500.0,
    )
    fixed_capped = _solve(
        _powered_weapon(start_speed_mps=300.0, max_speed_mps=200.0),
        launch_speed_mps=120.0,
        target_distance_m=1500.0,
    )
    inherited_at_cap = _solve(
        _powered_weapon(start_speed_mps=0.0, max_speed_mps=200.0),
        launch_speed_mps=200.0,
        target_distance_m=1500.0,
    )

    assert inherited_fast.max_range_m > inherited_slow.max_range_m
    assert fixed_from_slow_carrier.max_range_m == pytest.approx(fixed_from_fast_carrier.max_range_m)
    assert fixed_from_slow_carrier.time_to_target_s == pytest.approx(
        fixed_from_fast_carrier.time_to_target_s
    )
    assert fixed_capped.max_range_m == pytest.approx(inherited_at_cap.max_range_m)


def test_second_motor_stage_extends_range_and_target_time_is_integrated() -> None:
    two_stage = _powered_weapon()
    one_stage = _powered_weapon(
        motor_stages=[{"duration_s": 3.0, "thrust_n": 9000.0, "mass_end_kg": 85.0}],
        mass_end_kg=85.0,
    )

    one = _solve(one_stage, target_distance_m=1200.0)
    two = _solve(two_stage, target_distance_m=1200.0)
    farther = _solve(two_stage, target_distance_m=2400.0)

    assert two.max_range_m > one.max_range_m
    assert 0.0 < two.time_to_target_s < farther.time_to_target_s


def test_fire_delay_stage_is_preserved_and_feeds_mass_into_later_impulse() -> None:
    delayed = _powered_weapon(
        mass_start_kg=100.0,
        mass_end_kg=70.0,
        caliber_m=0.1,
        cx_k=0.0,
        time_life_s=4.0,
        min_distance_m=0.0,
        hard_max_distance_m=0.0,
        max_speed_mps=0.0,
        motor_stages=[
            {"duration_s": 2.0, "thrust_n": 0.0, "mass_end_kg": 90.0},
            {"duration_s": 2.0, "thrust_n": 5000.0, "mass_end_kg": 70.0},
        ],
    )
    impulse_from_delay_end_mass = _powered_weapon(
        mass_start_kg=90.0,
        mass_end_kg=70.0,
        caliber_m=0.1,
        cx_k=0.0,
        time_life_s=2.0,
        min_distance_m=0.0,
        hard_max_distance_m=0.0,
        max_speed_mps=0.0,
        motor_stages=[
            {"duration_s": 2.0, "thrust_n": 5000.0, "mass_end_kg": 70.0},
        ],
    )

    delayed_result = _solve(
        delayed,
        launch_speed_mps=100.0,
        target_distance_m=250.0,
    )
    impulse_result = _solve(
        impulse_from_delay_end_mass,
        launch_speed_mps=100.0,
        target_distance_m=250.0,
    )

    # With zero drag, the only range difference is the two-second 100 m/s delay.
    # Equality also proves the impulse inherited the delay stage's 90 kg end mass.
    assert delayed_result.max_range_m == pytest.approx(
        impulse_result.max_range_m + 200.0,
        abs=1e-6,
    )
    assert delayed_result.time_to_target_s > impulse_result.time_to_target_s


def test_max_speed_cap_and_hard_distance_cutoff_are_enforced() -> None:
    uncapped = _solve(_powered_weapon(max_speed_mps=0.0), target_distance_m=1000.0)
    capped = _solve(_powered_weapon(max_speed_mps=280.0), target_distance_m=1000.0)
    hard = _solve(
        _powered_weapon(
            hard_max_distance_m=1500.0,
            time_life_s=60.0,
            max_speed_mps=1000.0,
        ),
        target_distance_m=2000.0,
    )

    assert capped.max_range_m < uncapped.max_range_m
    assert hard.max_range_m == pytest.approx(1500.0)
    assert hard.status == "out_of_range"
    assert hard.reason == "beyond_hard_max_distance"


def test_stat_card_range_does_not_seed_dynamic_range() -> None:
    short_card = _solve(_powered_weapon(stat_card_range_m=1.0))
    long_card = _solve(_powered_weapon(stat_card_range_m=999999.0))

    assert short_card.max_range_m == pytest.approx(long_card.max_range_m)
    assert short_card.time_to_target_s == pytest.approx(long_card.time_to_target_s)


def test_aam_unknown_target_motion_uses_more_conservative_post_burn_floor() -> None:
    common = {
        "time_life_s": 50.0,
        "motor_stages": [{"duration_s": 1.0, "thrust_n": 0.0, "mass_end_kg": 98.0}],
        "cx_k": 0.2,
        "max_speed_mps": 0.0,
    }
    agm = _solve(_powered_weapon(role="agm", **common), launch_speed_mps=180.0)
    aam = _solve(_powered_weapon(role="aam", **common), launch_speed_mps=180.0)

    assert aam.max_range_m < agm.max_range_m
    assert aam.quality == "two_dimensional"


def test_guided_normal_fallback_is_explicitly_uncalibrated_and_never_green() -> None:
    calls = []

    def trajectory(**kwargs):
        calls.append(kwargs)
        return 20.0, 4000.0, 250.0

    weapon = {
        "role": "bomb",
        "propulsion": "unpowered",
        "control": "guided",
        "planform": "normal",
        "mass_start_kg": 500.0,
        "caliber_m": 0.4,
        "drag_cx": 0.05,
        "time_life_s": 30.0,
        "min_distance_m": 0.0,
        "hard_max_distance_m": 10000.0,
        "fins_aoa_horiz": 30.0,
        "fins_aoa_vert": 30.0,
        "guidance_kind": "tv",
        "guidance": {"type": "tv", "seeker": "contrast"},
    }
    result = WeaponSolver(trajectory_func=trajectory).solve(
        weapon,
        launch_altitude_m=3000.0,
        launch_speed_mps=250.0,
        target_altitude_m=500.0,
        target_distance_m=3000.0,
    )

    assert len(calls) == 1
    assert calls[0]["target_alt_m"] == 500.0
    assert result.max_range_m == pytest.approx(3400.0)
    assert result.quality == "experimental"
    assert result.status == "within_experimental_reference"
    assert result.reason == "guided_ballistic_uncalibrated"

    weak_control = dict(
        weapon,
        fins_aoa_horiz=0.0,
        fins_aoa_vert=0.0,
        guidance_kind="unknown",
        guidance={"type": "unknown", "seeker": "unknown"},
    )
    weak_result = WeaponSolver(trajectory_func=trajectory).solve(
        weak_control,
        launch_altitude_m=3000.0,
        launch_speed_mps=250.0,
        target_altitude_m=500.0,
        target_distance_m=2000.0,
    )
    assert weak_result.max_range_m < result.max_range_m


def test_gbu31_visible_ground_curve_replaces_falsified_ballistic_fallback_near_anchor() -> None:
    def must_not_run(**_kwargs):
        raise AssertionError("matched visible curve must bypass the free-fall fallback")

    weapon = {
        "id": "us_2000lb_gbu31_usaf",
        "role": "bomb",
        "propulsion": "unpowered",
        "control": "guided",
        "planform": "normal",
        "min_distance_m": 0.0,
    }
    solver = WeaponSolver(trajectory_func=must_not_run)

    within = solver.solve(
        weapon,
        launch_altitude_m=3000.0,
        launch_speed_mps=250.0,
        target_altitude_m=None,
        target_distance_m=5000.0,
        target_kind="zone",
    )
    beyond = solver.solve(
        weapon,
        launch_altitude_m=3000.0,
        launch_speed_mps=250.0,
        target_altitude_m=100.0,
        target_distance_m=12000.0,
        target_kind="ground",
        ground_closing_speed_mps=100.0,
    )

    assert within.status == "within_experimental_reference"
    assert within.reason == "player_visible_trajectory_reference"
    assert within.quality == "experimental"
    assert within.max_range_m == 10000.0
    assert within.time_to_target_s == pytest.approx(22.2229, abs=0.001)
    assert beyond.status == "beyond_experimental_reference"
    assert beyond.reason == "player_visible_trajectory_reference"
    assert beyond.max_range_m == 10000.0
    assert beyond.time_to_window_s == pytest.approx(20.0)


def test_glide_does_not_reuse_the_iron_bomb_trajectory_as_an_envelope() -> None:
    calls = []

    def trajectory(**kwargs):
        calls.append(kwargs)
        physics = kwargs["bomb_params"]
        raw_range = (
            5000.0
            + physics["mass"] * 2.0
            - physics["caliber"] * 500.0
            - physics["drag_cx"] * 1000.0
        )
        return 20.0, raw_range, 250.0

    base = {
        "role": "bomb",
        "propulsion": "unpowered",
        "control": "guided",
        "planform": "glide",
        "time_life_s": 30.0,
        "min_distance_m": 0.0,
        "hard_max_distance_m": 50000.0,
        "fins_aoa_horiz": 30.0,
        "fins_aoa_vert": 30.0,
        "guidance_kind": "ins_gnss",
        "guidance": {"type": "ins", "seeker": "gnss"},
    }
    gbu_39 = dict(
        base,
        id="us_gbu_39",
        mass_start_kg=129.0,
        caliber_m=0.19,
        drag_cx=0.08,
        wing_area_mult=9999.0,
        cx_k=0.0001,
    )
    gbu_53 = dict(
        base,
        id="us_gbu_53",
        mass_start_kg=93.0,
        caliber_m=0.18,
        drag_cx=0.11,
        wing_area_mult=0.001,
        cx_k=9999.0,
    )
    solver = WeaponSolver(
        trajectory_func=trajectory,
        ballistic_model=WeaponBallisticModelConfig.STRICT_OFFICIAL,
    )
    first = solver.solve(
        gbu_39,
        launch_altitude_m=1000.0,
        launch_speed_mps=250.0,
        target_distance_m=1000.0,
    )
    second = solver.solve(
        gbu_53,
        launch_altitude_m=1000.0,
        launch_speed_mps=250.0,
        target_distance_m=1000.0,
    )

    assert calls == []
    assert {first.status, second.status} == {"insufficient_data"}
    assert {first.reason, second.reason} == {"glide_envelope_unavailable"}
    assert {first.model, second.model} == {"strict_official"}
    assert not first.valid
    assert not second.valid


def test_glide_unavailable_state_precedes_flat_propulsion_fallback() -> None:
    def trajectory(**_kwargs):
        return 40.0, 10_000.0, 250.0

    weapon = {
        "role": "bomb",
        "propulsion": "unpowered",
        "control": "guided",
        "planform": "glide",
        "mass_start_kg": 120.0,
        "caliber_m": 0.2,
        "drag_cx": 0.03,
        "time_life_s": 20.0,
        "hard_max_distance_m": 2000.0,
        "fins_aoa_horiz": 30.0,
        "fins_aoa_vert": 30.0,
        "guidance_kind": "ins_gnss",
        "guidance": {"type": "ins", "seeker": "gnss"},
        "model_unsupported_reasons": ["conditional_propulsion_autopilot"],
    }

    result = WeaponSolver(
        trajectory_func=trajectory,
        ballistic_model=WeaponBallisticModelConfig.STRICT_OFFICIAL,
    ).solve(
        weapon,
        launch_altitude_m=3000.0,
        launch_speed_mps=250.0,
        target_distance_m=1000.0,
    )

    assert result.status == "insufficient_data"
    assert result.reason == "glide_envelope_unavailable"
    assert result.model == "strict_official"
    assert result.max_range_m == 0.0


def test_foxthree_compatible_glide_uses_clean_room_energy_height_formula() -> None:
    weapon = _glide_weapon(
        wing_area_mult=2.0,
        time_life_s=1000.0,
        hard_max_distance_m=0.0,
    )

    result = _solve(
        weapon,
        ballistic_model=WeaponBallisticModelConfig.FOXTHREE_COMPATIBLE,
        launch_altitude_m=3000.0,
        launch_speed_mps=200.0,
        target_altitude_m=500.0,
        target_distance_m=10_000.0,
    )

    energy_height_m = 2500.0 + 200.0**2 / (2.0 * 9.80665)
    expected_range_m = 0.8 * (2.4 * 2.0) * energy_height_m
    assert result.max_range_m == pytest.approx(expected_range_m)
    assert result.time_to_target_s == pytest.approx(50.0)
    assert result.status == "within_experimental_reference"
    assert result.quality == "experimental"
    assert result.reason == "foxthree_compatible_glide"
    assert result.model == "foxthree_compatible"
    assert result.valid


def test_foxthree_compatible_glide_clamps_lift_drag_and_applies_lifetime_and_hard_caps() -> None:
    energy_height_m = 4000.0 + 200.0**2 / (2.0 * 9.80665)
    low = _solve(
        _glide_weapon(wing_area_mult=0.0, time_life_s=0.0),
        ballistic_model="foxthree_compatible",
        launch_altitude_m=4000.0,
        launch_speed_mps=200.0,
        target_distance_m=1000.0,
    )
    high = _solve(
        _glide_weapon(wing_area_mult=999.0, time_life_s=0.0),
        ballistic_model="foxthree_compatible",
        launch_altitude_m=4000.0,
        launch_speed_mps=200.0,
        target_distance_m=1000.0,
    )
    capped = _solve(
        _glide_weapon(
            wing_area_mult=999.0,
            time_life_s=20.0,
            hard_max_distance_m=2500.0,
        ),
        ballistic_model="foxthree_compatible",
        launch_altitude_m=4000.0,
        launch_speed_mps=200.0,
        target_distance_m=3000.0,
    )

    assert low.max_range_m == pytest.approx(0.8 * 1.5 * energy_height_m)
    assert high.max_range_m == pytest.approx(0.8 * 12.0 * energy_height_m)
    assert capped.max_range_m == pytest.approx(2500.0)
    assert capped.status == "beyond_experimental_reference"
    assert capped.reason == "foxthree_compatible_glide"


def test_foxthree_compatible_glide_handles_unsupported_flag_but_not_missing_wing_data() -> None:
    supported_fallback = _solve(
        _glide_weapon(model_unsupported_reasons=["conditional_propulsion_autopilot"]),
        ballistic_model="foxthree_compatible",
        target_distance_m=1000.0,
    )
    unavailable = _solve(
        {key: value for key, value in _glide_weapon().items() if key != "wing_area_mult"},
        ballistic_model="foxthree_compatible",
        target_distance_m=1000.0,
    )

    assert supported_fallback.reason == "foxthree_compatible_glide"
    assert supported_fallback.quality == "experimental"
    assert unavailable.status == "insufficient_data"
    assert unavailable.reason == "foxthree_compatible_glide_unavailable"
    assert not unavailable.valid


def test_existing_solver_observes_runtime_model_switch_without_restart(monkeypatch) -> None:
    monkeypatch.setattr(
        WeaponBallisticModelConfig,
        "selected_model",
        WeaponBallisticModelConfig.FOXTHREE_COMPATIBLE,
    )
    solver = WeaponSolver()
    assert WeaponBallisticModelConfig.set_selected("strict_official")

    result = solver.solve(
        _glide_weapon(),
        launch_altitude_m=3000.0,
        launch_speed_mps=250.0,
        target_distance_m=1000.0,
    )

    assert result.model == "strict_official"
    assert result.reason == "glide_envelope_unavailable"


def test_freefall_and_high_drag_return_to_ccrp_without_integration() -> None:
    def must_not_run(**_kwargs):
        raise AssertionError("existing CCRP path must own free-fall integration")

    solver = WeaponSolver(trajectory_func=must_not_run)
    for planform in ("normal", "high_drag"):
        result = solver.solve(
            {
                "role": "bomb",
                "propulsion": "unpowered",
                "control": "unguided",
                "planform": planform,
            },
            launch_altitude_m=1000.0,
            launch_speed_mps=200.0,
            target_distance_m=1000.0,
        )
        assert result.status == "ccrp"
        assert not result.valid


@pytest.mark.parametrize(
    ("distance", "relative", "expected"),
    [
        (100.0, 0.0, "too_close"),
        (100000.0, 0.0, "out_of_range"),
        (2000.0, 20.0, "align"),
        (2000.0, 2.0, "in_envelope"),
    ],
)
def test_machine_statuses_cover_range_and_alignment(distance, relative, expected) -> None:
    result = _solve(
        _powered_weapon(),
        target_distance_m=distance,
        target_relative_deg=relative,
    )

    assert result.status == expected


def test_missing_target_and_invalid_physics_fail_closed() -> None:
    no_target = _solve(_powered_weapon(), target_distance_m=None)
    bad_physics = _solve(_powered_weapon(time_life_s=0.0))

    assert no_target.status == "no_target"
    assert not no_target.valid
    assert bad_physics.status == "solver_error"
    assert not bad_physics.valid


@pytest.mark.parametrize(
    "guard",
    [
        {"model_unsupported_reasons": ["conditional_propulsion_autopilot"]},
        {"physics_support": False},
    ],
)
def test_conditional_propulsion_fails_closed_before_integration(guard) -> None:
    unsupported = _powered_weapon(motor_stages=[], **guard)

    result = _solve(unsupported)

    assert result.status == "insufficient_data"
    assert result.reason == "conditional_propulsion_unsupported"
    assert not result.valid


@pytest.mark.parametrize("ballistic_model", ["foxthree_compatible", "strict_official"])
def test_aam_guidance_table_uses_current_aspect_and_bypasses_flat_model_limits(
    ballistic_model,
) -> None:
    head_on = _solve(
        _aam_envelope_weapon(),
        ballistic_model=ballistic_model,
        launch_altitude_m=5000.0,
        launch_mach=0.9,
        target_distance_m=80_000.0,
        target_kind="aircraft",
        target_aspect_cosine=-1.0,
    )

    assert head_on.status == "within_aspect_reference"
    assert head_on.reason == "datamine_guidance_envelope"
    assert head_on.max_range_m == pytest.approx(81_819.2)
    assert head_on.rear_range_m == pytest.approx(13_562.0)
    assert head_on.head_range_m == pytest.approx(81_819.2)
    assert head_on.target_aspect_cosine == -1.0
    assert head_on.max_range_m > 10_000.0  # not clipped by missile maxDistance
    assert head_on.model == ballistic_model
    assert head_on.valid


@pytest.mark.parametrize(
    ("distance_m", "aspect", "expected"),
    [
        (10_000.0, 1.0, "within_all_aspect_reference"),
        (50_000.0, 1.0, "head_on_only_reference"),
        (50_000.0, None, "head_on_only_reference"),
        (90_000.0, -1.0, "beyond_envelope_reference"),
    ],
)
def test_aam_guidance_table_exposes_all_current_and_best_aspect_states(
    distance_m, aspect, expected
) -> None:
    result = _solve(
        _aam_envelope_weapon(),
        launch_altitude_m=5000.0,
        launch_mach=0.9,
        target_distance_m=distance_m,
        target_kind="aircraft",
        target_aspect_cosine=aspect,
    )

    assert result.status == expected
    assert result.quality == "two_dimensional"
    if aspect is None:
        assert result.min_range_m == 0.0


def test_aam_poi_candidate_keeps_unknown_motion_reference() -> None:
    result = _solve(
        _aam_envelope_weapon(),
        launch_altitude_m=5000.0,
        launch_mach=0.9,
        target_distance_m=50_000.0,
        target_kind="poi",
        target_name="Radar Point",
        target_aspect_cosine=None,
    )

    assert result.valid
    assert result.status == "head_on_only_reference"
    assert result.reason == "datamine_guidance_envelope"
    assert result.quality == "two_dimensional"
    assert result.target_kind == "poi"
    assert result.target_name == "Radar Point"
    assert result.target_aspect_cosine is None


def test_agm_guidance_table_can_bypass_conditional_propulsion_failure() -> None:
    weapon = _powered_weapon(
        model_unsupported_reasons=["conditional_propulsion_autopilot"],
        guidance_envelope={
            "tables": [
                {
                    "table": "table0",
                    "altitude_m": 500.0,
                    "fighter_mach": [0.4, 0.8],
                    "target_mach": [0.1, 0.1],
                    "target_mach2_mult": -1.0,
                    "range_min_m": [5000.0] * 4,
                    "range_max_m": [65000.0] * 4,
                }
            ]
        },
    )

    result = _solve(
        weapon,
        launch_altitude_m=500.0,
        launch_mach=0.8,
        target_distance_m=60_000.0,
        target_kind="zone",
    )

    assert result.status == "in_envelope"
    assert result.reason == "datamine_guidance_envelope"
    assert result.max_range_m == pytest.approx(65_000.0)


def test_aam_uses_only_a_2d_max_and_ignores_top_level_minimum() -> None:
    weapon = _powered_weapon(role="aam", min_distance_m=300.0)

    close = _solve(
        weapon,
        target_distance_m=50.0,
        target_kind="aircraft",
    )
    off_axis = _solve(
        weapon,
        target_distance_m=50.0,
        target_kind="aircraft",
        target_relative_deg=20.0,
    )

    assert close.status == "within_2d_max_only"
    assert close.reason == "aam_2d_max_only"
    assert close.min_range_m == 0.0
    assert close.time_to_target_s == 0.0
    assert close.valid
    assert off_axis.status == "align"
    assert off_axis.time_to_window_s == 0.0


def test_time_to_window_uses_aligned_ground_closing_speed_only() -> None:
    weapon = _powered_weapon(role="aam", hard_max_distance_m=1500.0)
    air = _solve(
        weapon,
        target_distance_m=3000.0,
        target_kind="aircraft",
        ground_closing_speed_mps=75.0,
    )
    ground = _solve(
        dict(weapon, role="agm"),
        target_distance_m=3000.0,
        target_kind="zone",
        ground_closing_speed_mps=75.0,
    )
    no_closing = _solve(
        dict(weapon, role="agm"),
        target_distance_m=3000.0,
        target_kind="zone",
    )
    off_axis = _solve(
        dict(weapon, role="agm"),
        target_distance_m=3000.0,
        target_kind="zone",
        target_relative_deg=20.0,
        ground_closing_speed_mps=75.0,
    )

    assert air.status == "out_of_range"
    assert air.time_to_window_s == 0.0
    assert ground.status == "out_of_range"
    assert ground.time_to_window_s == pytest.approx(20.0)
    assert no_closing.time_to_window_s == 0.0
    assert off_axis.status == "align"
    assert off_axis.time_to_window_s == 0.0
