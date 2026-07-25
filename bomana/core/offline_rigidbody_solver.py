"""Pure-offline rigid-body kernel for the versioned bomb model.

The module accepts only ordinary numeric state, bundled static weapon
properties, and the versioned offline atmosphere.  It deliberately has no
telemetry, process, or game-client dependency so the production runtime can
remain inside the 8111-plus-heightmap boundary.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Final

from bomana.core.atmosphere import (
    DAGOR_STANDARD_DENSITY_KG_M3,
    dagor_air_density,
    dagor_speed_of_sound,
)

OFFLINE_RIGIDBODY_STEP_SECONDS: Final = 1.0 / 48.0
OFFLINE_RIGIDBODY_GRAVITY_MS2: Final = 9.81
OFFLINE_RIGIDBODY_MAX_ACCELERATION_MS2: Final = 6_000.0
OFFLINE_RIGIDBODY_MIN_SPEED_MS: Final = 0.1
_VECTOR_EPSILON: Final = 1.0e-9


@dataclass(frozen=True, slots=True)
class Vec3:
    """Small immutable three-vector used by the offline solver."""

    x: float
    y: float
    z: float

    def __add__(self, other: Vec3) -> Vec3:
        return Vec3(self.x + other.x, self.y + other.y, self.z + other.z)

    def __sub__(self, other: Vec3) -> Vec3:
        return Vec3(self.x - other.x, self.y - other.y, self.z - other.z)

    def __neg__(self) -> Vec3:
        return Vec3(-self.x, -self.y, -self.z)

    def __mul__(self, scalar: float) -> Vec3:
        return Vec3(self.x * scalar, self.y * scalar, self.z * scalar)

    __rmul__ = __mul__

    def __truediv__(self, scalar: float) -> Vec3:
        return Vec3(self.x / scalar, self.y / scalar, self.z / scalar)

    def dot(self, other: Vec3) -> float:
        return self.x * other.x + self.y * other.y + self.z * other.z

    def cross(self, other: Vec3) -> Vec3:
        return Vec3(
            self.y * other.z - self.z * other.y,
            self.z * other.x - self.x * other.z,
            self.x * other.y - self.y * other.x,
        )

    def magnitude_squared(self) -> float:
        return self.dot(self)

    def magnitude(self) -> float:
        return math.sqrt(self.magnitude_squared())

    def normalized(self, *, fallback: Vec3 | None = None) -> Vec3:
        magnitude = self.magnitude()
        if magnitude > _VECTOR_EPSILON:
            return self / magnitude
        return fallback if fallback is not None else ZERO_VEC3


ZERO_VEC3: Final = Vec3(0.0, 0.0, 0.0)
LOCAL_FORWARD: Final = Vec3(1.0, 0.0, 0.0)


@dataclass(frozen=True, slots=True)
class Quaternion:
    """Body-to-world quaternion in ``x, y, z, w`` storage order."""

    x: float
    y: float
    z: float
    w: float

    def __mul__(self, other: Quaternion) -> Quaternion:
        return Quaternion(
            self.w * other.x
            + self.x * other.w
            + self.y * other.z
            - self.z * other.y,
            self.w * other.y
            - self.x * other.z
            + self.y * other.w
            + self.z * other.x,
            self.w * other.z
            + self.x * other.y
            - self.y * other.x
            + self.z * other.w,
            self.w * other.w
            - self.x * other.x
            - self.y * other.y
            - self.z * other.z,
        )

    def conjugate(self) -> Quaternion:
        return Quaternion(-self.x, -self.y, -self.z, self.w)

    def normalized(self) -> Quaternion:
        magnitude = math.sqrt(
            self.x * self.x + self.y * self.y + self.z * self.z + self.w * self.w
        )
        if magnitude <= _VECTOR_EPSILON:
            return IDENTITY_QUATERNION
        inverse = 1.0 / magnitude
        return Quaternion(
            self.x * inverse,
            self.y * inverse,
            self.z * inverse,
            self.w * inverse,
        )

    def rotate(self, vector: Vec3) -> Vec3:
        """Rotate a body-space vector into world space."""

        q_vector = Vec3(self.x, self.y, self.z)
        doubled_cross = q_vector.cross(vector) * 2.0
        return vector + doubled_cross * self.w + q_vector.cross(doubled_cross)

    def inverse_rotate(self, vector: Vec3) -> Vec3:
        """Rotate a world-space vector into body space."""

        return self.conjugate().rotate(vector)

    @classmethod
    def from_rotation_vector(cls, rotation_vector: Vec3) -> Quaternion:
        angle = rotation_vector.magnitude()
        if angle <= _VECTOR_EPSILON:
            half = 0.5
            return cls(
                rotation_vector.x * half,
                rotation_vector.y * half,
                rotation_vector.z * half,
                1.0,
            ).normalized()
        half_angle = 0.5 * angle
        scale = math.sin(half_angle) / angle
        return cls(
            rotation_vector.x * scale,
            rotation_vector.y * scale,
            rotation_vector.z * scale,
            math.cos(half_angle),
        )


IDENTITY_QUATERNION: Final = Quaternion(0.0, 0.0, 0.0, 1.0)


@dataclass(frozen=True, slots=True)
class OfflineRigidbodySolverProperties:
    """Validated ordinary-bomb subset of ``ShellBallisticsProperties``."""

    mass_kg: float
    inertia_kg_m2: Vec3
    frontal_area_m2: float
    lateral_area_m2: float
    stabilizer_lever_m: float
    length_m: float
    axial_coefficient: float
    normal_coefficient: float
    normal_aoa_limit: float
    aoa_drag_coefficient: float
    rotational_damping: Vec3
    rotational_reference_m4: float
    aerodynamic_axis: Quaternion = field(default=IDENTITY_QUATERNION)

    @classmethod
    def from_static(
        cls,
        values: Mapping[str, Any] | None,
    ) -> OfflineRigidbodySolverProperties | None:
        """Resolve a complete solver block from one bundled weapon record."""

        record = values if isinstance(values, Mapping) else {}
        derived = record.get("offline_rigidbody")
        if not isinstance(derived, Mapping):
            return None

        def number(name: str, *, positive: bool = False) -> float:
            raw = float(derived[name])
            if not math.isfinite(raw) or (positive and raw <= 0.0):
                raise ValueError(name)
            return raw

        try:
            return cls(
                mass_kg=number("mass_kg", positive=True),
                inertia_kg_m2=Vec3(
                    number("inertia_x_kg_m2", positive=True),
                    number("inertia_y_kg_m2", positive=True),
                    number("inertia_z_kg_m2", positive=True),
                ),
                frontal_area_m2=number("frontal_area_m2", positive=True),
                lateral_area_m2=number("lateral_area_m2", positive=True),
                stabilizer_lever_m=number("stabilizer_lever_m"),
                length_m=number("length_m", positive=True),
                axial_coefficient=number("axial_coefficient", positive=True),
                normal_coefficient=number("normal_coefficient"),
                normal_aoa_limit=number("normal_aoa_limit", positive=True),
                aoa_drag_coefficient=number("aoa_drag_coefficient"),
                rotational_damping=Vec3(
                    number("rotational_damping_x"),
                    number("rotational_damping_y"),
                    number("rotational_damping_z"),
                ),
                rotational_reference_m4=number("rotational_reference_m4", positive=True),
            )
        except (KeyError, TypeError, ValueError):
            return None


@dataclass(frozen=True, slots=True)
class OfflineRigidbodyEnvironment:
    """External inputs supplied to one offline solver step."""

    wind_velocity_world_ms: Vec3 = field(default=ZERO_VEC3)
    extra_acceleration_world_ms2: Vec3 = field(default=ZERO_VEC3)
    extra_torque_body_nm: Vec3 = field(default=ZERO_VEC3)
    extra_axial_coefficient: float = 0.0
    extra_stabilizer_lever_m: float = 0.0
    sea_level_density_kg_m3: float = DAGOR_STANDARD_DENSITY_KG_M3
    gravity_ms2: float = OFFLINE_RIGIDBODY_GRAVITY_MS2


DEFAULT_OFFLINE_RIGIDBODY_ENVIRONMENT: Final = OfflineRigidbodyEnvironment()


@dataclass(frozen=True, slots=True)
class OfflineRigidbodyState:
    """Position, attitude, and velocities for a offline fixed step."""

    position_world_m: Vec3
    orientation_body_to_world: Quaternion
    linear_velocity_world_ms: Vec3
    angular_velocity_body_rad_s: Vec3 = field(default=ZERO_VEC3)
    elapsed_seconds: float = 0.0


@dataclass(frozen=True, slots=True)
class OfflineRigidbodyLoads:
    """Forces and accelerations evaluated at the start of a solver step."""

    force_world_n: Vec3
    aerodynamic_torque_body_nm: Vec3
    damping_torque_body_nm: Vec3
    linear_acceleration_world_ms2: Vec3
    angular_acceleration_body_rad_s2: Vec3
    speed_ms: float
    mach: float
    dynamic_pressure_pa: float
    sine_aoa: float
    axial_cx: float
    normal_cy: float


@dataclass(frozen=True, slots=True)
class OfflineRigidbodyImpact:
    """Linearly interpolated intersection with a horizontal terrain plane."""

    elapsed_seconds: float
    position_world_m: Vec3
    linear_velocity_world_ms: Vec3


TerrainAltitudeAtRange = Callable[[float], float | None]


def axial_drag_curve(mach: float) -> float:
    """Versioned base axial Mach curve."""

    resolved_mach = max(0.0, float(mach))
    if not math.isfinite(resolved_mach):
        return 0.308
    if resolved_mach < 0.61:
        return 0.308
    if resolved_mach < 1.0:
        return 0.308 + 0.505 * (resolved_mach - 0.61) ** 2.31
    if resolved_mach < 1.4:
        offset = resolved_mach - 1.0
        return 0.551 + 0.4485 * offset**0.505 * math.exp(-5.68 * offset)
    if resolved_mach < 4.0:
        return resolved_mach / (((0.356 * resolved_mach + 2.237) * resolved_mach) - 1.4)
    return 0.302


def _fold_normal_force(raw: float, limit: float) -> float:
    if raw > limit:
        return max(0.0, 2.0 * limit - raw)
    if raw < -limit:
        return min(0.0, -2.0 * limit - raw)
    return raw


def _limited_damping_component(
    *,
    raw_damping_torque: float,
    non_damping_torque: float,
    inertia: float,
    angular_velocity: float,
    step_seconds: float,
) -> float:
    """Clamp damping so one step cannot reverse angular velocity."""

    cancel_torque = -(inertia * angular_velocity / step_seconds + non_damping_torque)
    if abs(cancel_torque) < abs(raw_damping_torque):
        return cancel_torque
    return raw_damping_torque


def evaluate_rigidbody_loads(
    state: OfflineRigidbodyState,
    properties: OfflineRigidbodySolverProperties,
    environment: OfflineRigidbodyEnvironment = DEFAULT_OFFLINE_RIGIDBODY_ENVIRONMENT,
    *,
    step_seconds: float = OFFLINE_RIGIDBODY_STEP_SECONDS,
) -> OfflineRigidbodyLoads:
    """Evaluate the ordinary free-fall branch of the offline reference model."""

    air_velocity = state.linear_velocity_world_ms - environment.wind_velocity_world_ms
    speed = max(OFFLINE_RIGIDBODY_MIN_SPEED_MS, air_velocity.magnitude())
    airflow_unit = air_velocity / speed
    aerodynamic_axis_body = properties.aerodynamic_axis.rotate(LOCAL_FORWARD)
    aerodynamic_axis_world = state.orientation_body_to_world.rotate(aerodynamic_axis_body)
    cosine_aoa = max(-1.0, min(1.0, aerodynamic_axis_world.dot(airflow_unit)))
    normal_axis = aerodynamic_axis_world - airflow_unit * cosine_aoa
    sine_aoa = min(1.0, normal_axis.magnitude())
    lift_direction = normal_axis.normalized()

    altitude = state.position_world_m.y
    density = dagor_air_density(altitude, environment.sea_level_density_kg_m3)
    mach = speed / dagor_speed_of_sound(altitude)
    cx_base = axial_drag_curve(mach)
    cxi = 2.43525 * cx_base + 0.250019
    axial_cx = (
        (properties.axial_coefficient + environment.extra_axial_coefficient) * cx_base
        + sine_aoa**2 * properties.axial_coefficient * properties.aoa_drag_coefficient * cxi
    )
    normal_cy = _fold_normal_force(
        sine_aoa * properties.normal_coefficient,
        properties.normal_aoa_limit,
    )
    dynamic_pressure = 0.5 * density * speed**2
    drag_force = (
        -airflow_unit
        * dynamic_pressure
        * properties.frontal_area_m2
        * axial_cx
    )
    lift_force = (
        lift_direction
        * dynamic_pressure
        * properties.lateral_area_m2
        * normal_cy
    )
    force_world = drag_force + lift_force

    force_body = state.orientation_body_to_world.inverse_rotate(force_world)
    effective_arm = (
        properties.stabilizer_lever_m + environment.extra_stabilizer_lever_m
    )
    # Angular-state components use the opposite handedness from the body-to-world
    # quaternion rotation used for linear vectors.
    stabilizer_lever_body = aerodynamic_axis_body * effective_arm
    aerodynamic_torque = (
        stabilizer_lever_body.cross(force_body) + environment.extra_torque_body_nm
    )

    damping_reference = dynamic_pressure * properties.rotational_reference_m4
    omega = state.angular_velocity_body_rad_s
    raw_damping = Vec3(
        -0.01 * damping_reference * properties.rotational_damping.x * omega.x,
        -0.05 * damping_reference * properties.rotational_damping.y * omega.y,
        -0.05 * damping_reference * properties.rotational_damping.z * omega.z,
    )
    inertia = properties.inertia_kg_m2
    damping_torque = Vec3(
        _limited_damping_component(
            raw_damping_torque=raw_damping.x,
            non_damping_torque=aerodynamic_torque.x,
            inertia=inertia.x,
            angular_velocity=omega.x,
            step_seconds=step_seconds,
        ),
        _limited_damping_component(
            raw_damping_torque=raw_damping.y,
            non_damping_torque=aerodynamic_torque.y,
            inertia=inertia.y,
            angular_velocity=omega.y,
            step_seconds=step_seconds,
        ),
        _limited_damping_component(
            raw_damping_torque=raw_damping.z,
            non_damping_torque=aerodynamic_torque.z,
            inertia=inertia.z,
            angular_velocity=omega.z,
            step_seconds=step_seconds,
        ),
    )
    total_torque = aerodynamic_torque + damping_torque
    angular_acceleration = Vec3(
        (
            total_torque.x
            + (inertia.y - inertia.z) * omega.y * omega.z
        )
        / inertia.x,
        (
            total_torque.y
            + (inertia.z - inertia.x) * omega.z * omega.x
        )
        / inertia.y,
        (
            total_torque.z
            + (inertia.x - inertia.y) * omega.x * omega.y
        )
        / inertia.z,
    )

    linear_acceleration = (
        force_world / properties.mass_kg
        + environment.extra_acceleration_world_ms2
        + Vec3(0.0, -environment.gravity_ms2, 0.0)
    )
    acceleration_magnitude = linear_acceleration.magnitude()
    if acceleration_magnitude > OFFLINE_RIGIDBODY_MAX_ACCELERATION_MS2:
        linear_acceleration = (
            linear_acceleration
            * (OFFLINE_RIGIDBODY_MAX_ACCELERATION_MS2 / acceleration_magnitude)
        )

    return OfflineRigidbodyLoads(
        force_world_n=force_world,
        aerodynamic_torque_body_nm=aerodynamic_torque,
        damping_torque_body_nm=damping_torque,
        linear_acceleration_world_ms2=linear_acceleration,
        angular_acceleration_body_rad_s2=angular_acceleration,
        speed_ms=speed,
        mach=mach,
        dynamic_pressure_pa=dynamic_pressure,
        sine_aoa=sine_aoa,
        axial_cx=axial_cx,
        normal_cy=normal_cy,
    )


def step_rigidbody(
    state: OfflineRigidbodyState,
    properties: OfflineRigidbodySolverProperties,
    environment: OfflineRigidbodyEnvironment = DEFAULT_OFFLINE_RIGIDBODY_ENVIRONMENT,
    *,
    step_seconds: float = OFFLINE_RIGIDBODY_STEP_SECONDS,
) -> OfflineRigidbodyState:
    """Advance one versioned constant-acceleration rigid-body step."""

    loads = evaluate_rigidbody_loads(
        state,
        properties,
        environment,
        step_seconds=step_seconds,
    )
    half_dt_squared = 0.5 * step_seconds**2
    next_position = (
        state.position_world_m
        + state.linear_velocity_world_ms * step_seconds
        + loads.linear_acceleration_world_ms2 * half_dt_squared
    )
    next_linear_velocity = (
        state.linear_velocity_world_ms
        + loads.linear_acceleration_world_ms2 * step_seconds
    )
    stored_rotation_vector = (
        state.angular_velocity_body_rad_s * step_seconds
        + loads.angular_acceleration_body_rad_s2 * half_dt_squared
    )
    delta_orientation = Quaternion.from_rotation_vector(-stored_rotation_vector)
    next_orientation = (
        state.orientation_body_to_world * delta_orientation
    ).normalized()
    next_angular_velocity = (
        state.angular_velocity_body_rad_s
        + loads.angular_acceleration_body_rad_s2 * step_seconds
    )
    return OfflineRigidbodyState(
        position_world_m=next_position,
        orientation_body_to_world=next_orientation,
        linear_velocity_world_ms=next_linear_velocity,
        angular_velocity_body_rad_s=next_angular_velocity,
        elapsed_seconds=state.elapsed_seconds + step_seconds,
    )


def integrate_rigidbody_to_altitude(
    initial_state: OfflineRigidbodyState,
    properties: OfflineRigidbodySolverProperties,
    target_altitude_m: float,
    environment: OfflineRigidbodyEnvironment = DEFAULT_OFFLINE_RIGIDBODY_ENVIRONMENT,
    *,
    max_time_seconds: float = 120.0,
    step_seconds: float = OFFLINE_RIGIDBODY_STEP_SECONDS,
) -> OfflineRigidbodyImpact | None:
    """Integrate until the trajectory crosses a horizontal altitude plane."""

    if (
        not math.isfinite(target_altitude_m)
        or initial_state.position_world_m.y <= target_altitude_m
        or max_time_seconds <= 0.0
        or step_seconds <= 0.0
    ):
        return None

    state = initial_state
    while state.elapsed_seconds - initial_state.elapsed_seconds < max_time_seconds:
        next_state = step_rigidbody(
            state,
            properties,
            environment,
            step_seconds=step_seconds,
        )
        if next_state.position_world_m.y <= target_altitude_m:
            previous_clearance = state.position_world_m.y - target_altitude_m
            next_clearance = next_state.position_world_m.y - target_altitude_m
            denominator = previous_clearance - next_clearance
            fraction = (
                max(0.0, min(1.0, previous_clearance / denominator))
                if denominator > _VECTOR_EPSILON
                else 1.0
            )
            return OfflineRigidbodyImpact(
                elapsed_seconds=state.elapsed_seconds + step_seconds * fraction,
                position_world_m=state.position_world_m
                + (next_state.position_world_m - state.position_world_m) * fraction,
                linear_velocity_world_ms=state.linear_velocity_world_ms
                + (
                    next_state.linear_velocity_world_ms
                    - state.linear_velocity_world_ms
                )
                * fraction,
            )
        state = next_state
    return None


def integrate_rigidbody_to_terrain(
    initial_state: OfflineRigidbodyState,
    properties: OfflineRigidbodySolverProperties,
    terrain_altitude_at_range: TerrainAltitudeAtRange,
    environment: OfflineRigidbodyEnvironment = DEFAULT_OFFLINE_RIGIDBODY_ENVIRONMENT,
    *,
    max_time_seconds: float = 120.0,
    step_seconds: float = OFFLINE_RIGIDBODY_STEP_SECONDS,
) -> OfflineRigidbodyImpact | None:
    """Integrate until a segment crosses a supplied offline terrain profile."""

    if max_time_seconds <= 0.0 or step_seconds <= 0.0:
        return None

    origin = initial_state.position_world_m

    def horizontal_range(position: Vec3) -> float:
        return math.hypot(position.x - origin.x, position.z - origin.z)

    def terrain_altitude(position: Vec3) -> float | None:
        try:
            raw = terrain_altitude_at_range(horizontal_range(position))
            altitude = float(raw) if raw is not None else math.nan
        except (ArithmeticError, TypeError, ValueError):
            return None
        return altitude if math.isfinite(altitude) else None

    state = initial_state
    ground_altitude = terrain_altitude(state.position_world_m)
    if (
        ground_altitude is None
        or state.position_world_m.y <= ground_altitude
    ):
        return None

    while state.elapsed_seconds - initial_state.elapsed_seconds < max_time_seconds:
        next_state = step_rigidbody(
            state,
            properties,
            environment,
            step_seconds=step_seconds,
        )
        next_ground_altitude = terrain_altitude(next_state.position_world_m)
        if next_ground_altitude is None:
            return None
        previous_clearance = state.position_world_m.y - ground_altitude
        next_clearance = next_state.position_world_m.y - next_ground_altitude
        if next_clearance <= 0.0:
            denominator = previous_clearance - next_clearance
            fraction = (
                max(0.0, min(1.0, previous_clearance / denominator))
                if denominator > _VECTOR_EPSILON
                else 1.0
            )
            return OfflineRigidbodyImpact(
                elapsed_seconds=state.elapsed_seconds + step_seconds * fraction,
                position_world_m=state.position_world_m
                + (next_state.position_world_m - state.position_world_m) * fraction,
                linear_velocity_world_ms=state.linear_velocity_world_ms
                + (
                    next_state.linear_velocity_world_ms
                    - state.linear_velocity_world_ms
                )
                * fraction,
            )
        state = next_state
        ground_altitude = next_ground_altitude
    return None


def integrate_pitch_projection_to_terrain(
    *,
    release_world_altitude_m: float,
    velocity_x_ms: float,
    velocity_y_ms: float,
    initial_body_angle_rad: float,
    properties: OfflineRigidbodySolverProperties,
    terrain_altitude_at_range: TerrainAltitudeAtRange,
    environment: OfflineRigidbodyEnvironment = DEFAULT_OFFLINE_RIGIDBODY_ENVIRONMENT,
    max_time_seconds: float = 120.0,
    step_seconds: float = OFFLINE_RIGIDBODY_STEP_SECONDS,
) -> OfflineRigidbodyImpact | None:
    """Optimized planar specialization of the same rigid-body equations.

    Official 8111 telemetry can reconstruct the along-track/vertical plane but
    not a released store's complete quaternion.  This specialization preserves
    the versioned total-force moment and angular-state convention without the
    object-allocation cost of the general three-dimensional validation kernel.
    """

    if (
        max_time_seconds <= 0.0
        or step_seconds <= 0.0
        or abs(environment.wind_velocity_world_ms.z) > _VECTOR_EPSILON
        or abs(environment.extra_acceleration_world_ms2.z) > _VECTOR_EPSILON
        or abs(environment.extra_torque_body_nm.x) > _VECTOR_EPSILON
        or abs(environment.extra_torque_body_nm.y) > _VECTOR_EPSILON
    ):
        return None

    def terrain_altitude(horizontal_range_m: float) -> float | None:
        try:
            raw = terrain_altitude_at_range(horizontal_range_m)
            altitude = float(raw) if raw is not None else math.nan
        except (ArithmeticError, TypeError, ValueError):
            return None
        return altitude if math.isfinite(altitude) else None

    horizontal_range = 0.0
    altitude = release_world_altitude_m
    velocity_x = velocity_x_ms
    velocity_y = velocity_y_ms
    body_angle = initial_body_angle_rad
    stored_angular_velocity = 0.0
    elapsed = 0.0
    ground_altitude = terrain_altitude(horizontal_range)
    if ground_altitude is None or altitude <= ground_altitude:
        return None

    inertia_z = properties.inertia_kg_m2.z
    effective_arm = (
        properties.stabilizer_lever_m
        + environment.extra_stabilizer_lever_m
    )
    while elapsed < max_time_seconds:
        air_velocity_x = velocity_x - environment.wind_velocity_world_ms.x
        air_velocity_y = velocity_y - environment.wind_velocity_world_ms.y
        speed = max(
            OFFLINE_RIGIDBODY_MIN_SPEED_MS,
            math.hypot(air_velocity_x, air_velocity_y),
        )
        airflow_x = air_velocity_x / speed
        airflow_y = air_velocity_y / speed
        axis_x = math.cos(body_angle)
        axis_y = math.sin(body_angle)
        cosine_aoa = max(
            -1.0,
            min(1.0, axis_x * airflow_x + axis_y * airflow_y),
        )
        normal_x = axis_x - airflow_x * cosine_aoa
        normal_y = axis_y - airflow_y * cosine_aoa
        sine_aoa = min(1.0, math.hypot(normal_x, normal_y))
        if sine_aoa > _VECTOR_EPSILON:
            lift_x = normal_x / sine_aoa
            lift_y = normal_y / sine_aoa
        else:
            lift_x = 0.0
            lift_y = 0.0

        density = dagor_air_density(
            altitude,
            environment.sea_level_density_kg_m3,
        )
        mach = speed / dagor_speed_of_sound(altitude)
        cx_base = axial_drag_curve(mach)
        cxi = 2.43525 * cx_base + 0.250019
        axial_cx = (
            (properties.axial_coefficient + environment.extra_axial_coefficient) * cx_base
            + sine_aoa**2 * properties.axial_coefficient * properties.aoa_drag_coefficient * cxi
        )
        normal_cy = _fold_normal_force(
            sine_aoa * properties.normal_coefficient,
            properties.normal_aoa_limit,
        )
        dynamic_pressure = 0.5 * density * speed**2
        drag_force = (
            dynamic_pressure * properties.frontal_area_m2 * axial_cx
        )
        lift_force = (
            dynamic_pressure * properties.lateral_area_m2 * normal_cy
        )
        force_x = -drag_force * airflow_x + lift_force * lift_x
        force_y = -drag_force * airflow_y + lift_force * lift_y

        body_normal_force = -axis_y * force_x + axis_x * force_y
        aerodynamic_torque = (
            effective_arm * body_normal_force
            + environment.extra_torque_body_nm.z
        )
        raw_damping_torque = (
            -0.05
            * dynamic_pressure
            * properties.rotational_reference_m4
            * properties.rotational_damping.z
            * stored_angular_velocity
        )
        damping_torque = _limited_damping_component(
            raw_damping_torque=raw_damping_torque,
            non_damping_torque=aerodynamic_torque,
            inertia=inertia_z,
            angular_velocity=stored_angular_velocity,
            step_seconds=step_seconds,
        )
        angular_acceleration = (
            aerodynamic_torque + damping_torque
        ) / inertia_z

        acceleration_x = (
            force_x / properties.mass_kg
            + environment.extra_acceleration_world_ms2.x
        )
        acceleration_y = (
            force_y / properties.mass_kg
            + environment.extra_acceleration_world_ms2.y
            - environment.gravity_ms2
        )
        acceleration_magnitude = math.hypot(acceleration_x, acceleration_y)
        if acceleration_magnitude > OFFLINE_RIGIDBODY_MAX_ACCELERATION_MS2:
            acceleration_scale = (
                OFFLINE_RIGIDBODY_MAX_ACCELERATION_MS2 / acceleration_magnitude
            )
            acceleration_x *= acceleration_scale
            acceleration_y *= acceleration_scale

        half_dt_squared = 0.5 * step_seconds**2
        next_range = (
            horizontal_range
            + velocity_x * step_seconds
            + acceleration_x * half_dt_squared
        )
        next_altitude = (
            altitude
            + velocity_y * step_seconds
            + acceleration_y * half_dt_squared
        )
        next_velocity_x = velocity_x + acceleration_x * step_seconds
        next_velocity_y = velocity_y + acceleration_y * step_seconds
        next_body_angle = body_angle - (
            stored_angular_velocity * step_seconds
            + angular_acceleration * half_dt_squared
        )
        next_angular_velocity = (
            stored_angular_velocity + angular_acceleration * step_seconds
        )

        next_ground_altitude = terrain_altitude(next_range)
        if next_ground_altitude is None:
            return None
        previous_clearance = altitude - ground_altitude
        next_clearance = next_altitude - next_ground_altitude
        if next_clearance <= 0.0:
            denominator = previous_clearance - next_clearance
            fraction = (
                max(0.0, min(1.0, previous_clearance / denominator))
                if denominator > _VECTOR_EPSILON
                else 1.0
            )
            return OfflineRigidbodyImpact(
                elapsed_seconds=elapsed + step_seconds * fraction,
                position_world_m=Vec3(
                    horizontal_range
                    + (next_range - horizontal_range) * fraction,
                    altitude + (next_altitude - altitude) * fraction,
                    0.0,
                ),
                linear_velocity_world_ms=Vec3(
                    velocity_x + (next_velocity_x - velocity_x) * fraction,
                    velocity_y + (next_velocity_y - velocity_y) * fraction,
                    0.0,
                ),
            )

        horizontal_range = next_range
        altitude = next_altitude
        velocity_x = next_velocity_x
        velocity_y = next_velocity_y
        body_angle = next_body_angle
        stored_angular_velocity = next_angular_velocity
        elapsed += step_seconds
        ground_altitude = next_ground_altitude
    return None


__all__ = [
    "DEFAULT_OFFLINE_RIGIDBODY_ENVIRONMENT",
    "IDENTITY_QUATERNION",
    "LOCAL_FORWARD",
    "OFFLINE_RIGIDBODY_GRAVITY_MS2",
    "OFFLINE_RIGIDBODY_MAX_ACCELERATION_MS2",
    "OFFLINE_RIGIDBODY_STEP_SECONDS",
    "OfflineRigidbodyEnvironment",
    "OfflineRigidbodyImpact",
    "OfflineRigidbodyLoads",
    "OfflineRigidbodySolverProperties",
    "OfflineRigidbodyState",
    "Quaternion",
    "TerrainAltitudeAtRange",
    "Vec3",
    "ZERO_VEC3",
    "evaluate_rigidbody_loads",
    "integrate_rigidbody_to_altitude",
    "integrate_rigidbody_to_terrain",
    "integrate_pitch_projection_to_terrain",
    "axial_drag_curve",
    "step_rigidbody",
]
