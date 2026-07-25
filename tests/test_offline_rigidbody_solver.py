from __future__ import annotations

import math

import pytest

from bomana.config.settings import BombConfig
from bomana.core.offline_rigidbody_solver import (
    OFFLINE_RIGIDBODY_STEP_SECONDS,
    OfflineRigidbodySolverProperties,
    OfflineRigidbodyState,
    Quaternion,
    Vec3,
    evaluate_rigidbody_loads,
    integrate_pitch_projection_to_terrain,
    integrate_rigidbody_to_terrain,
    step_rigidbody,
)


def _quaternion_angle_error_deg(first: Quaternion, second: Quaternion) -> float:
    dot = abs(
        first.x * second.x
        + first.y * second.y
        + first.z * second.z
        + first.w * second.w
    )
    return math.degrees(2.0 * math.acos(max(-1.0, min(1.0, dot))))


def _zb500_properties() -> OfflineRigidbodySolverProperties:
    properties = OfflineRigidbodySolverProperties.from_static(
        BombConfig.get_bomb_physics_params("su_zb_500")
    )
    assert properties is not None
    return properties


def test_rigidbody_force_moment_uses_total_body_normal_force() -> None:
    properties = _zb500_properties()
    body_angle = math.radians(10.0)
    state = OfflineRigidbodyState(
        position_world_m=Vec3(0.0, 1_000.0, 0.0),
        orientation_body_to_world=Quaternion.from_rotation_vector(
            Vec3(0.0, 0.0, body_angle)
        ),
        linear_velocity_world_ms=Vec3(200.0, 0.0, 0.0),
    )

    loads = evaluate_rigidbody_loads(state, properties)
    force_body = state.orientation_body_to_world.inverse_rotate(loads.force_world_n)

    assert loads.aerodynamic_torque_body_nm.z == pytest.approx(
        properties.stabilizer_lever_m * force_body.y
    )
    lift_only_moment = (
        properties.stabilizer_lever_m
        * loads.dynamic_pressure_pa
        * properties.lateral_area_m2
        * loads.normal_cy
        * math.cos(body_angle)
    )
    assert abs(loads.aerodynamic_torque_body_nm.z) > abs(lift_only_moment)


def test_rigidbody_rotational_damping_cannot_reverse_omega_in_one_step() -> None:
    properties = _zb500_properties()
    state = OfflineRigidbodyState(
        position_world_m=Vec3(0.0, 0.0, 0.0),
        orientation_body_to_world=Quaternion(0.0, 0.0, 0.0, 1.0),
        linear_velocity_world_ms=Vec3(2_000.0, 0.0, 0.0),
        angular_velocity_body_rad_s=Vec3(0.0, 0.0, 1.0),
    )

    next_state = step_rigidbody(state, properties)

    assert next_state.angular_velocity_body_rad_s.z == pytest.approx(0.0, abs=1.0e-12)


def test_optimized_pitch_projection_matches_general_rigidbody_kernel() -> None:
    properties = _zb500_properties()
    velocity_x = 220.0
    velocity_y = -25.0
    body_angle = math.atan2(velocity_y, velocity_x) + math.radians(3.0)

    def terrain(_range_m: float) -> float:
        return 0.0

    initial_state = OfflineRigidbodyState(
        position_world_m=Vec3(0.0, 3_000.0, 0.0),
        orientation_body_to_world=Quaternion.from_rotation_vector(
            Vec3(0.0, 0.0, body_angle)
        ),
        linear_velocity_world_ms=Vec3(velocity_x, velocity_y, 0.0),
    )

    general = integrate_rigidbody_to_terrain(
        initial_state,
        properties,
        terrain,
    )
    projected = integrate_pitch_projection_to_terrain(
        release_world_altitude_m=3_000.0,
        velocity_x_ms=velocity_x,
        velocity_y_ms=velocity_y,
        initial_body_angle_rad=body_angle,
        properties=properties,
        terrain_altitude_at_range=terrain,
    )

    assert general is not None
    assert projected is not None
    assert projected.elapsed_seconds == pytest.approx(general.elapsed_seconds, abs=1.0e-10)
    assert projected.position_world_m.x == pytest.approx(
        general.position_world_m.x,
        abs=1.0e-8,
    )
    assert projected.position_world_m.y == pytest.approx(
        general.position_world_m.y,
        abs=1.0e-8,
    )
    assert projected.linear_velocity_world_ms.x == pytest.approx(
        general.linear_velocity_world_ms.x,
        abs=1.0e-8,
    )
    assert projected.linear_velocity_world_ms.y == pytest.approx(
        general.linear_velocity_world_ms.y,
        abs=1.0e-8,
    )


def test_zb500_offline_kernel_matches_fixed_step_reference_checkpoint() -> None:
    properties = _zb500_properties()
    state = OfflineRigidbodyState(
        position_world_m=Vec3(
            -11_074.71484375,
            1_232.7552490234375,
            12_589.7978515625,
        ),
        orientation_body_to_world=Quaternion(
            0.4713728427886963,
            0.3415212333202362,
            0.15337415039539337,
            -0.7985281944274902,
        ).normalized(),
        linear_velocity_world_ms=Vec3(
            122.86457061767578,
            16.736722946166992,
            200.04335021972656,
        ),
    )

    for _ in range(300):
        state = step_rigidbody(state, properties)

    expected_position = Vec3(
        -10_310.115234375,
        1_150.392578125,
        13_818.9326171875,
    )
    expected_velocity = Vec3(
        120.79949188232422,
        -42.87856674194336,
        194.20379638671875,
    )
    expected_orientation = Quaternion(
        0.3842693567276001,
        0.3841237425804138,
        0.30452147126197815,
        -0.7823379635810852,
    )
    expected_angular_velocity = Vec3(
        0.0,
        -0.03450075536966324,
        0.021448632702231407,
    )

    assert state.elapsed_seconds == pytest.approx(300 * OFFLINE_RIGIDBODY_STEP_SECONDS)
    assert (state.position_world_m - expected_position).magnitude() < 0.05
    assert (state.linear_velocity_world_ms - expected_velocity).magnitude() < 0.01
    assert (
        _quaternion_angle_error_deg(
            state.orientation_body_to_world,
            expected_orientation,
        )
        < 0.15
    )
    assert (
        state.angular_velocity_body_rad_s - expected_angular_velocity
    ).magnitude() < 0.0002


def test_all_static_bomb_records_resolve_complete_solver_properties() -> None:
    BombConfig._ensure_database_loaded()

    unresolved = [
        weapon_id
        for weapon_id, params in BombConfig.BOMB_DATABASE.items()
        if OfflineRigidbodySolverProperties.from_static(params) is None
    ]

    assert len(BombConfig.BOMB_DATABASE) == 437
    assert unresolved == []
