import math

import pytest

from bomana.config.settings import BombConfig
from bomana.core.ballistics import (
    axial_drag_curve,
    calculate_bomb_trajectory,
    offline_speed_of_sound,
)
from bomana.core.offline_ballistics_model import (
    OFFLINE_DEFAULT_AXIAL_COEFFICIENT,
    OFFLINE_RIGIDBODY_PROJECTION_MODEL_ID,
    OFFLINE_RIGIDBODY_UNAVAILABLE_MODEL_ID,
    OFFLINE_STEP_SECONDS,
    resolve_offline_ballistics_model,
)


def test_selected_freefall_weapon_resolves_offline_rigidbody_model() -> None:
    params = BombConfig.get_bomb_physics_params("uk_1000lbs_gp")

    model = resolve_offline_ballistics_model(params)

    assert model.supported
    assert model.model_id == OFFLINE_RIGIDBODY_PROJECTION_MODEL_ID
    assert model.category == "freefall"
    assert model.quality == "offline_rigidbody_8111_projection"
    assert model.rigidbody_projection_enabled
    assert model.axial_coefficient == OFFLINE_DEFAULT_AXIAL_COEFFICIENT == pytest.approx(0.2)
    assert model.effective_axial_coefficient == pytest.approx(model.axial_coefficient)
    assert model.step_seconds == OFFLINE_STEP_SECONDS == pytest.approx(1.0 / 48.0)
    assert all("process" not in source for source in model.runtime_input_sources)
    assert all("memory" not in source for source in model.runtime_input_sources)


def test_exact_mk82_uses_rigidbody_projection_without_old_axial_fit() -> None:
    params = BombConfig.get_bomb_physics_params("us_500lb_mk_82_ldgp")

    model = resolve_offline_ballistics_model(params)

    assert model.supported
    assert model.model_id == OFFLINE_RIGIDBODY_PROJECTION_MODEL_ID
    assert model.quality == "offline_rigidbody_8111_projection"
    assert model.rigidbody_projection_enabled
    assert model.axial_coefficient == pytest.approx(OFFLINE_DEFAULT_AXIAL_COEFFICIENT)
    assert model.effective_axial_coefficient == pytest.approx(OFFLINE_DEFAULT_AXIAL_COEFFICIENT)
    assert model.coefficient_source == "offline_rigidbody_catalog"


def test_generic_stores_share_the_unscaled_rigidbody_solver() -> None:
    default_variant = resolve_offline_ballistics_model(
        BombConfig.get_bomb_physics_params("us_500lb_mk_82_ldgp_default")
    )
    uk_holdout = resolve_offline_ballistics_model(
        BombConfig.get_bomb_physics_params("uk_1000lbs_gp")
    )

    assert default_variant.effective_axial_coefficient == pytest.approx(OFFLINE_DEFAULT_AXIAL_COEFFICIENT)
    assert default_variant.model_id == OFFLINE_RIGIDBODY_PROJECTION_MODEL_ID
    assert default_variant.rigidbody_projection_enabled
    assert uk_holdout.effective_axial_coefficient == pytest.approx(OFFLINE_DEFAULT_AXIAL_COEFFICIENT)
    assert uk_holdout.model_id == OFFLINE_RIGIDBODY_PROJECTION_MODEL_ID


def test_exact_500mc_long_tail_uses_the_shared_rigidbody_solver() -> None:
    params = BombConfig.get_bomb_physics_params("uk_500lb_mc_mk1_mk4_long_tail")

    model = resolve_offline_ballistics_model(params)

    assert params["weapon_id"] == "uk_500lb_mc_mk1_mk4_long_tail"
    assert model.model_id == OFFLINE_RIGIDBODY_PROJECTION_MODEL_ID
    assert model.quality == "offline_rigidbody_8111_projection"
    assert model.rigidbody_projection_enabled
    assert model.effective_axial_coefficient == pytest.approx(0.2)


def test_500mc_default_variant_uses_the_same_rigidbody_solver() -> None:
    params = BombConfig.get_bomb_physics_params(
        "uk_500lb_mc_mk1_mk4_long_tail_bomb_default"
    )

    model = resolve_offline_ballistics_model(params)

    assert params["weapon_id"] == "uk_500lb_mc_mk1_mk4_long_tail_bomb_default"
    assert model.model_id == OFFLINE_RIGIDBODY_PROJECTION_MODEL_ID
    assert model.rigidbody_projection_enabled


def test_500mc_pitch_plane_matches_reference_anchor() -> None:
    params = BombConfig.get_bomb_physics_params("uk_500lb_mc_mk1_mk4_long_tail")

    predicted = calculate_bomb_trajectory(
        release_alt_m=1428.0,
        release_speed_ms=98.28606836458513,
        target_alt_m=25.141159057617188,
        initial_vz_ms=8.0,
        initial_aoa_deg=3.1,
        bomb_params=params,
        atmosphere_altitude_datum_m=60.0,
        air_density_sea_level=1.2239287045925167,
    )

    assert predicted[0] == pytest.approx(19.082895278930664, abs=0.30)
    assert predicted[1] == pytest.approx(1923.0783899589226, abs=15.0)
    assert predicted[2] == pytest.approx(189.0075177331257, abs=0.5)


@pytest.mark.parametrize(
    "weapon_id",
    (
        "uk_500lb_mc_mk1_mk4_long_tail",
        "uk_1000lbs_gp",
        "us_500lb_mk_82_ldgp",
        "su_fab_250m_62",
    ),
)
def test_pitch_plane_fails_closed_without_8111_aoa(weapon_id: str) -> None:
    params = BombConfig.get_bomb_physics_params(weapon_id)

    assert calculate_bomb_trajectory(
        release_alt_m=1428.0,
        release_speed_ms=98.28606836458513,
        target_alt_m=25.141159057617188,
        initial_vz_ms=8.0,
        bomb_params=params,
    ) == (0.0, 0.0, 0.0)


def test_explicit_axial_coefficient_is_used_without_per_weapon_flight_calibration() -> None:
    params = BombConfig.get_bomb_physics_params("su_fab_250m_62")

    model = resolve_offline_ballistics_model(params)

    assert params["offline_rigidbody"]["axial_coefficient"] == pytest.approx(0.726074)
    assert model.axial_coefficient == pytest.approx(0.726074)
    assert model.effective_axial_coefficient == pytest.approx(0.726074)
    assert model.model_id == OFFLINE_RIGIDBODY_PROJECTION_MODEL_ID
    assert model.rigidbody_projection_enabled


def test_store_specific_pitch_plane_properties_change_trajectory() -> None:
    selected_ids = (
        "uk_1000lbs_gp",
        "us_500lb_mk_82_ldgp",
        "su_fab_250m_62",
        "us_blu_1",
    )
    property_signatures = set()
    trajectories = set()
    for weapon_id in selected_ids:
        params = BombConfig.get_bomb_physics_params(weapon_id)
        rigidbody = params["offline_rigidbody"]
        property_signatures.add(
            (
                rigidbody["mass_kg"],
                rigidbody["lateral_area_m2"],
                rigidbody["stabilizer_lever_m"],
                rigidbody["inertia_z_kg_m2"],
                rigidbody["axial_coefficient"],
                rigidbody["normal_coefficient"],
                rigidbody["aoa_drag_coefficient"],
            )
        )
        trajectories.add(
            tuple(
                round(value, 3)
                for value in calculate_bomb_trajectory(
                    release_alt_m=3000.0,
                    release_speed_ms=220.0,
                    initial_vz_ms=-25.0,
                    initial_aoa_deg=3.0,
                    target_alt_m=0.0,
                    bomb_params=params,
                )
            )
        )

    assert len(property_signatures) == len(selected_ids)
    assert len(trajectories) == len(selected_ids)


def test_high_drag_category_has_no_old_estimation_fallback() -> None:
    params = BombConfig.get_bomb_physics_params("us_500lb_mk_82_ldgp_snakeye")

    model = resolve_offline_ballistics_model(params)

    assert not params["prediction_supported"]
    assert params["prediction_kind"] == "high_drag"
    assert not model.supported
    assert model.model_id == OFFLINE_RIGIDBODY_UNAVAILABLE_MODEL_ID
    assert model.unavailable_reason == "offline_high_drag_unavailable"


@pytest.mark.parametrize(
    ("mach", "expected"),
    (
        (0.0, 0.308),
        (0.60, 0.308),
        (0.61, 0.308),
        (1.0, 0.551),
        (4.0, 0.302),
        (5.0, 0.302),
    ),
)
def test_offline_mach_curve_anchors(mach: float, expected: float) -> None:
    assert axial_drag_curve(mach) == pytest.approx(expected, abs=1e-12)


def test_offline_sound_speed_is_physical_at_sea_level() -> None:
    assert offline_speed_of_sound(0.0) == pytest.approx(341.20305, abs=0.0001)
    assert offline_speed_of_sound(10_000.0) < offline_speed_of_sound(0.0)


def test_selected_weapon_mass_and_caliber_remain_effective() -> None:
    selected_ids = ("uk_1000lbs_gp", "us_500lb_mk_82_ldgp", "su_fab100")
    ranges = {
        round(
            calculate_bomb_trajectory(
                release_alt_m=3000.0,
                release_speed_ms=220.0,
                initial_vz_ms=-25.0,
                initial_aoa_deg=3.0,
                bomb_params=BombConfig.get_bomb_physics_params(weapon_id),
            )[1],
            3,
        )
        for weapon_id in selected_ids
    }

    assert len(ranges) == len(selected_ids)


def test_old_empirical_override_fields_have_no_effect() -> None:
    params = BombConfig.get_bomb_physics_params("uk_1000lbs_gp")
    baseline = calculate_bomb_trajectory(
        release_alt_m=3000.0,
        release_speed_ms=220.0,
        initial_vz_ms=-25.0,
        initial_aoa_deg=3.0,
        bomb_params=params,
    )
    attempted_override = calculate_bomb_trajectory(
        release_alt_m=3000.0,
        release_speed_ms=220.0,
        initial_vz_ms=-25.0,
        initial_aoa_deg=3.0,
        bomb_params={
            **params,
            "trajectory_drag_coefficient_mult": 99.0,
            "trajectory_reference_area_mult": 0.01,
        },
    )

    assert attempted_override == pytest.approx(baseline)


def test_heightmap_profile_can_stop_the_rigidbody_step_on_intervening_terrain() -> None:
    params = BombConfig.get_bomb_physics_params("uk_1000lbs_gp")
    flat = calculate_bomb_trajectory(
        release_alt_m=1200.0,
        release_speed_ms=220.0,
        target_alt_m=0.0,
        initial_aoa_deg=3.0,
        bomb_params=params,
    )
    ridge = calculate_bomb_trajectory(
        release_alt_m=1200.0,
        release_speed_ms=220.0,
        target_alt_m=0.0,
        initial_aoa_deg=3.0,
        bomb_params=params,
        terrain_altitude_at_range=lambda distance: 900.0 if distance >= 1200.0 else 0.0,
    )

    assert 0.0 < ridge[1] < flat[1]
    assert ridge[0] < flat[0]


def test_all_supported_freefall_catalog_entries_use_valid_pitch_plane_data() -> None:
    BombConfig._ensure_database_loaded()
    freefall_ids = [
        weapon_id
        for weapon_id, data in BombConfig.BOMB_DATABASE.items()
        if data.get("prediction_kind") == "freefall"
    ]
    reference_cases = (
        (1200.0, 100.0, 0.0, 0.0),
        (3000.0, 180.0, 40.0, 5.0),
        (5000.0, 300.0, -80.0, 8.0),
    )

    assert len(freefall_ids) == 331
    for weapon_id in freefall_ids:
        params = BombConfig.get_bomb_physics_params(weapon_id)
        model = resolve_offline_ballistics_model(params)

        assert model.supported, weapon_id
        assert model.rigidbody_projection_enabled, weapon_id
        assert model.model_id == OFFLINE_RIGIDBODY_PROJECTION_MODEL_ID, weapon_id
        for altitude_m, speed_ms, vy_ms, aoa_deg in reference_cases:
            trajectory = calculate_bomb_trajectory(
                release_alt_m=altitude_m,
                release_speed_ms=speed_ms,
                initial_vz_ms=vy_ms,
                initial_aoa_deg=aoa_deg,
                target_alt_m=0.0,
                bomb_params=params,
            )
            assert all(
                math.isfinite(value) and value > 0.0 for value in trajectory
            ), (weapon_id, altitude_m, speed_ms, vy_ms, aoa_deg)


def test_signed_stabilizer_distance_is_valid_static_weapon_data() -> None:
    params = BombConfig.get_bomb_physics_params("us_blu_1")
    model = resolve_offline_ballistics_model(params)

    assert params["offline_rigidbody"]["stabilizer_lever_m"] == pytest.approx(-0.25)
    assert model.supported
    assert model.rigidbody_projection_enabled


def test_missing_pitch_plane_static_block_fails_closed() -> None:
    params = BombConfig.get_bomb_physics_params("uk_1000lbs_gp")
    params.pop("offline_rigidbody")

    model = resolve_offline_ballistics_model(params)

    assert not model.supported
    assert model.model_id == OFFLINE_RIGIDBODY_UNAVAILABLE_MODEL_ID
    assert model.unavailable_reason == "offline_rigidbody_properties_unavailable"
