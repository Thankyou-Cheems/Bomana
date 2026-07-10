"""Behavioral coverage for conservative weapon-envelope models."""

import pytest

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


def _solve(weapon, **overrides):
    inputs = {
        "launch_altitude_m": 1000.0,
        "launch_speed_mps": 250.0,
        "target_distance_m": 3000.0,
        "target_relative_deg": 0.0,
        "target_kind": "zone",
        "target_name": "Target",
    }
    inputs.update(overrides)
    return WeaponSolver().solve(weapon, **inputs)


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


def test_guided_normal_reuses_ballistic_integration_conservatively() -> None:
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
    assert result.quality == "conservative"
    assert result.status == "in_envelope"

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


def test_glide_uses_distinct_ballistic_surrogates_without_claiming_an_envelope() -> None:
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
    solver = WeaponSolver(trajectory_func=trajectory)
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

    assert len(calls) == 2
    assert calls[0]["bomb_params"] == {
        "mass": 129.0,
        "drag_cx": 0.08,
        "caliber": 0.19,
    }
    assert calls[1]["bomb_params"] == {
        "mass": 93.0,
        "drag_cx": 0.11,
        "caliber": 0.18,
    }
    assert first.max_range_m != second.max_range_m
    assert {first.status, second.status} == {"within_ballistic_reference"}
    assert {first.reason, second.reason} == {"guided_ballistic_surrogate"}
    assert {first.quality, second.quality} == {"two_dimensional"}

    beyond = solver.solve(
        gbu_39,
        launch_altitude_m=1000.0,
        launch_speed_mps=250.0,
        target_distance_m=10_000.0,
        target_kind="zone",
        ground_closing_speed_mps=100.0,
    )
    assert beyond.status == "beyond_ballistic_reference"
    assert beyond.reason == "guided_ballistic_surrogate"
    assert beyond.time_to_window_s > 0.0


def test_glide_ballistic_surrogate_obeys_lifetime_and_hard_cap() -> None:
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
    }

    result = WeaponSolver(trajectory_func=trajectory).solve(
        weapon,
        launch_altitude_m=3000.0,
        launch_speed_mps=250.0,
        target_distance_m=1000.0,
    )

    assert result.status == "within_ballistic_reference"
    assert result.max_range_m == pytest.approx(2000.0)


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
