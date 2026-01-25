# -*- coding: utf-8 -*-
"""Ballistics calculations (CCRP)."""

import math
from typing import Optional, Tuple

from bomana.config import BallisticPhysicsParams, BombConfig

# ============================================================================
# 弹道物理计算辅助函数
# ============================================================================

def _wt_get_air_density(altitude_m: float, temp_k: float = None) -> float:
    """计算War Thunder指数衰减大气密度

    公式：ρ(h) = 1.225 × exp(-h/14426) × (288.15/T)
    """
    if altitude_m < 0:
        altitude_m = 0

    rho_sea = BallisticPhysicsParams.AIR_DENSITY_SEA
    scale_h = BallisticPhysicsParams.AIR_DENSITY_SCALE_HEIGHT

    density = rho_sea * math.exp(-altitude_m / scale_h)

    if temp_k is not None and temp_k > 0 and BallisticPhysicsParams.USE_TEMPERATURE_CORRECTION:
        density *= BallisticPhysicsParams.TEMP_REFERENCE_K / temp_k

    return density

# ============================================================================
# 弹道计算模块（CCRP v3.0）
# ============================================================================

def calculate_bomb_trajectory(
    release_alt_m: float,
    release_speed_ms: float,
    bomb_mass_kg: float = 0.0,
    bomb_bc: float = 0.0,
    target_alt_m: float = 0.0,
    dive_angle_deg: float = 0.0,
    initial_vz_ms = None,
    bomb_params: dict = None
) -> tuple:
    """计算炸弹弹道（支持多种阻力模型）
    
    Args:
        release_alt_m: 投弹高度（米）
        release_speed_ms: 投弹时水平速度（m/s）
        target_alt_m: 目标高度（米）
        dive_angle_deg: 俯冲角度（度）
        initial_vz_ms: 初始垂直速度（m/s）
        bomb_params: 炸弹物理参数字典
    
    Returns:
        (飞行时间秒, 水平飞行距离米, 落地速度m/s)
    """
    g = BallisticPhysicsParams.GRAVITY
    drag_model = BallisticPhysicsParams.DRAG_MODEL
    
    alt_offset = BallisticPhysicsParams.ALTITUDE_CORRECTION_OFFSET
    range_mult = BallisticPhysicsParams.RANGE_CORRECTION_MULT
    time_mult = BallisticPhysicsParams.TIME_CORRECTION_MULT
    
    h = (release_alt_m + alt_offset) - target_alt_m
    if h <= 0:
        return 0.0, 0.0, 0.0
    
    dive_rad = math.radians(dive_angle_deg)
    vx = release_speed_ms * math.cos(dive_rad)
    vz0 = float(initial_vz_ms) if initial_vz_ms is not None else -release_speed_ms * math.sin(dive_rad)
    
    if drag_model == "none":
        discriminant = vz0 * vz0 + 2.0 * g * h
        if discriminant < 0:
            return 0.0, 0.0, 0.0
        t = (vz0 + math.sqrt(discriminant)) / g
        x = vx * t
        vz_final = vz0 - g * t
        impact_speed = math.sqrt(vx * vx + vz_final * vz_final)
        return t * time_mult, x * range_mult, impact_speed
    
    elif drag_model == "simple":
        return _calculate_trajectory_with_drag(h, vx, vz0, g, bomb_params, range_mult, time_mult)
    
    elif drag_model == "advanced":
        return _calculate_trajectory_advanced(h, vx, vz0, g, bomb_params, range_mult, time_mult)
    
    else:
        discriminant = vz0 * vz0 + 2.0 * g * h
        if discriminant < 0:
            return 0.0, 0.0, 0.0
        t = (vz0 + math.sqrt(discriminant)) / g
        x = vx * t
        vz_final = vz0 - g * t
        impact_speed = math.sqrt(vx * vx + vz_final * vz_final)
        return t * time_mult, x * range_mult, impact_speed


def _calculate_trajectory_with_drag(h, vx, vz0, g, bomb_params, range_mult, time_mult):
    """简化阻力模型"""
    if bomb_params is None:
        bomb_params = BombConfig.get_bomb_physics_params()
    
    mass = bomb_params.get('mass', 100.0)
    drag_cx = bomb_params.get('drag_cx', 0.04)
    caliber = bomb_params.get('caliber', 0.2)
    
    area = math.pi * (caliber / 2) ** 2 * BallisticPhysicsParams.DRAG_REFERENCE_AREA_MULT
    drag_cx *= BallisticPhysicsParams.DRAG_COEFFICIENT_MULT
    
    dt = BallisticPhysicsParams.TIME_STEP
    max_time = BallisticPhysicsParams.MAX_FLIGHT_TIME
    temp_k = BallisticPhysicsParams.MAP_TEMPERATURE_K
    temp_factor = BallisticPhysicsParams.TEMP_REFERENCE_K / temp_k if temp_k > 0 else 1.0
    
    x, z = 0.0, h
    vx_curr, vz_curr = vx, vz0
    t = 0.0
    
    while t < max_time and z > 0:
        current_altitude = max(0, z + BallisticPhysicsParams.DEFAULT_TARGET_ALT)
        rho = _wt_get_air_density(current_altitude) * temp_factor
        
        v = max(0.1, math.sqrt(vx_curr**2 + vz_curr**2))
        drag_coeff = 0.5 * rho * drag_cx * area / mass
        ax = -drag_coeff * vx_curr * v
        az = -g - drag_coeff * vz_curr * v
        
        vx_curr += ax * dt
        vz_curr += az * dt
        x += vx_curr * dt
        z += vz_curr * dt
        t += dt
    
    impact_speed = math.sqrt(vx_curr**2 + vz_curr**2)
    return t * time_mult, x * range_mult, impact_speed


def _calculate_trajectory_advanced(h, vx, vz0, g, bomb_params, range_mult, time_mult):
    """完整物理模型弹道计算 v3.0（使用RK4积分）"""
    if bomb_params is None:
        bomb_params = BombConfig.get_bomb_physics_params()
    
    mass = bomb_params.get('mass', 100.0)
    drag_cx = bomb_params.get('dragCx', bomb_params.get('drag_cx', 0.04))
    caliber = bomb_params.get('caliber', 0.2)
    brake_time = bomb_params.get('brakeTime', [0.0, 0.0])
    brake_cx_k = bomb_params.get('brakeCxK', 0.0)
    stab_enabled = bomb_params.get('stab_enabled', False)
    
    area = math.pi * (caliber / 2) ** 2 * BallisticPhysicsParams.DRAG_REFERENCE_AREA_MULT
    drag_cx *= BallisticPhysicsParams.DRAG_COEFFICIENT_MULT
    
    dt = BallisticPhysicsParams.TIME_STEP
    max_time = BallisticPhysicsParams.MAX_FLIGHT_TIME
    temp_k = BallisticPhysicsParams.MAP_TEMPERATURE_K
    temp_factor = BallisticPhysicsParams.TEMP_REFERENCE_K / temp_k if temp_k > 0 else 1.0
    
    x, z = 0.0, h
    vx_curr, vz_curr = vx, vz0
    t = 0.0
    prev_z, prev_vz, prev_vx, prev_x = h, vz0, vx, 0.0
    
    while t < max_time and z > BallisticPhysicsParams.GROUND_MARGIN:
        prev_z, prev_vz, prev_vx, prev_x = z, vz_curr, vx_curr, x
        
        current_altitude = max(0, z + BallisticPhysicsParams.DEFAULT_TARGET_ALT)
        rho = _wt_get_air_density(current_altitude) * temp_factor
        
        current_drag_cx = drag_cx
        if stab_enabled and len(brake_time) >= 2:
            brake_start = brake_time[0] + BallisticPhysicsParams.BRAKE_DEPLOY_DELAY
            brake_end = brake_time[1] + BallisticPhysicsParams.BRAKE_DEPLOY_DELAY
            if brake_start <= t <= brake_end and brake_cx_k > 0:
                brake_drag = brake_cx_k / (caliber ** 2) * BallisticPhysicsParams.BRAKE_DRAG_MULT
                current_drag_cx += brake_drag
        
        v = max(0.1, math.sqrt(vx_curr**2 + vz_curr**2))
        drag_factor = 0.5 * rho * current_drag_cx * area / mass
        
        # RK4积分
        ax1 = -drag_factor * vx_curr * v
        az1 = -g - drag_factor * vz_curr * v
        
        vx2, vz2 = vx_curr + ax1 * dt/2, vz_curr + az1 * dt/2
        v2 = max(0.1, math.sqrt(vx2**2 + vz2**2))
        ax2 = -drag_factor * vx2 * v2
        az2 = -g - drag_factor * vz2 * v2
        
        vx3, vz3 = vx_curr + ax2 * dt/2, vz_curr + az2 * dt/2
        v3 = max(0.1, math.sqrt(vx3**2 + vz3**2))
        ax3 = -drag_factor * vx3 * v3
        az3 = -g - drag_factor * vz3 * v3
        
        vx4, vz4 = vx_curr + ax3 * dt, vz_curr + az3 * dt
        v4 = max(0.1, math.sqrt(vx4**2 + vz4**2))
        ax4 = -drag_factor * vx4 * v4
        az4 = -g - drag_factor * vz4 * v4
        
        vx_curr += (ax1 + 2*ax2 + 2*ax3 + ax4) * dt / 6
        vz_curr += (az1 + 2*az2 + 2*az3 + az4) * dt / 6
        x += vx_curr * dt
        z += vz_curr * dt
        t += dt
    
    # 线性插值精确落地点
    if z < BallisticPhysicsParams.GROUND_MARGIN and prev_vz < 0:
        dz = prev_z - z
        if dz > 0.01:
            ratio = max(0.0, min(1.0, (prev_z - BallisticPhysicsParams.GROUND_MARGIN) / dz))
            t -= dt * (1 - ratio)
            x = prev_x + (x - prev_x) * ratio
            vx_curr = prev_vx + (vx_curr - prev_vx) * ratio
            vz_curr = prev_vz + (vz_curr - prev_vz) * ratio
    
    impact_speed = math.sqrt(vx_curr**2 + vz_curr**2)
    return t * time_mult, x * range_mult, impact_speed


def calculate_release_timing(
    current_distance_m: float,
    current_alt_m: float,
    ground_speed_ms: float,
    bomb_mass_kg: float = 0.0,
    bomb_bc: float = 0.0,
    target_alt_m: float = 0.0,
    dive_angle_deg: float = 0.0,
    initial_vz_ms: Optional[float] = None
) -> Tuple[float, float, str]:
    """计算投弹时机
    
    Returns:
        (距离投弹距离米, 距离投弹时间秒, 状态字符串)
        状态: "ready" / "approaching" / "too_far" / "passed" / "invalid"
    """
    if ground_speed_ms < 10.0 or current_alt_m <= target_alt_m:
        return 0.0, 0.0, "invalid"
    
    flight_time, bomb_range_m, _ = calculate_bomb_trajectory(
        release_alt_m=current_alt_m,
        release_speed_ms=ground_speed_ms,
        bomb_mass_kg=bomb_mass_kg,
        bomb_bc=bomb_bc,
        target_alt_m=target_alt_m,
        dive_angle_deg=dive_angle_deg,
        initial_vz_ms=initial_vz_ms
    )
    
    if bomb_range_m <= 0:
        return 0.0, 0.0, "invalid"
    
    release_distance_m = current_distance_m - bomb_range_m
    
    if release_distance_m < 0:
        return abs(release_distance_m), 0.0, "passed"
    
    time_to_release = release_distance_m / ground_speed_ms
    
    if time_to_release <= BallisticPhysicsParams.RELEASE_READY_SEC:
        return release_distance_m, time_to_release, "ready"
    elif time_to_release <= BallisticPhysicsParams.RELEASE_WARNING_SEC:
        return release_distance_m, time_to_release, "approaching"
    else:
        return release_distance_m, time_to_release, "too_far"
