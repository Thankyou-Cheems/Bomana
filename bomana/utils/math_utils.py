# -*- coding: utf-8 -*-
"""Math/navigation helpers."""

import math
from typing import Optional, Tuple

from bomana.config import ZoneConfig, Theme

def calculate_smart_scale(screen_width: int, screen_height: int, base_dpi_scale: float) -> float:
    """根据屏幕分辨率智能计算UI缩放倍数（v5.9.3新增）
    
    ╔══════════════════════════════════════════════════════════════════════╗
    ║ 智能缩放逻辑说明                                                      ║
    ╠══════════════════════════════════════════════════════════════════════╣
    ║ 目标：让界面在不同分辨率下都有合适的大小                               ║
    ║                                                                      ║
    ║ 缩放策略：                                                            ║
    ║ 1. 1080p及以下（≤1920x1080）：1.5x - 更大字体，提高可读性             ║
    ║ 2. 1440p（2560x1440）：1.2x - 120%大小                               ║
    ║ 3. 4K及以上（≥3840x2160）：0.9x - 更紧凑，充分利用屏幕空间           ║
    ║                                                                      ║
    ║ 特殊情况：                                                            ║
    ║ - 如果Windows DPI缩放已经>1.25，说明用户自己已经设置了大字体，       ║
    ║   此时不再额外放大，使用1.0x                                          ║
    ╚══════════════════════════════════════════════════════════════════════╝
    
    Args:
        screen_width: 屏幕宽度（像素）
        screen_height: 屏幕高度（像素）
        base_dpi_scale: Windows DPI缩放倍数
    
    Returns:
        推荐的UI缩放倍数
    """
    # 如果Windows DPI已经很大（>125%），说明用户希望大字体
    # 此时不再额外放大
    if base_dpi_scale > 1.25:
        return 1.0
    
    # 根据分辨率决定缩放
    # 1080p及以下：放大50%
    if screen_width <= 1920 and screen_height <= 1080:
        return 1.5
    # 1440p：放大20%
    elif screen_width <= 2560 and screen_height <= 1440:
        return 1.2
    # 4K及以上：缩小10%（利用高分辨率显示更多内容）
    else:
        return 0.9

# ============================================================================
# 导航数学函数
# ============================================================================

def calculate_heading_from_vector(dx: float, dy: float) -> Optional[float]:
    """从方向向量计算航向角度
    
    战雷8111地图坐标系：Y轴向下（屏幕坐标系），需要翻转。
    
    Args:
        dx: X方向分量
        dy: Y方向分量
    
    Returns:
        航向角度（0°=北，90°=东，顺时针），或None（如果向量为零）
    """
    if abs(dx) < 1e-9 and abs(dy) < 1e-9:
        return None
    # atan2(x, -y) 因为地图Y轴向下
    angle = math.degrees(math.atan2(dx, -dy))
    return (angle + 360) % 360


def calculate_bearing(x1: float, y1: float, x2: float, y2: float) -> float:
    """计算从点1到点2的方位角
    
    Args:
        x1, y1: 起点坐标
        x2, y2: 终点坐标
    
    Returns:
        方位角（0°=北，90°=东，顺时针）
    """
    dx = x2 - x1
    dy = y2 - y1
    angle = math.degrees(math.atan2(dx, -dy))
    return (angle + 360) % 360


def calculate_distance(x1: float, y1: float, x2: float, y2: float) -> float:
    """计算两点间的欧几里得距离
    
    Args:
        x1, y1: 点1坐标
        x2, y2: 点2坐标
    
    Returns:
        距离（归一化单位，乘以DISTANCE_SCALE得到km）
    """
    return math.sqrt((x2 - x1)**2 + (y2 - y1)**2)


def normalize_angle(angle: float) -> float:
    """将角度规范化到 [-180, 180] 区间
    
    Args:
        angle: 任意角度
    
    Returns:
        规范化后的角度
    """
    while angle > 180:
        angle -= 360
    while angle < -180:
        angle += 360
    return angle


def calculate_relative_bearing(player_heading: float, target_bearing: float) -> float:
    """计算相对方位角
    
    Args:
        player_heading: 玩家当前航向
        target_bearing: 目标绝对方位
    
    Returns:
        相对方位（-180到180，负数=左，正数=右）
    """
    relative = target_bearing - player_heading
    return normalize_angle(relative)


def get_direction_text(relative: float) -> str:
    """将相对方位转换为方向文字
    
    Args:
        relative: 相对方位角
    
    Returns:
        方向文字："前"、"后"、"左"、"右"
    """
    abs_rel = abs(relative)
    if abs_rel <= 30:
        return "前"
    elif abs_rel >= 150:
        return "后"
    elif relative > 0:
        return "右"
    else:
        return "左"
def calculate_heading_tape_scale(distance_km: float) -> float:
    """计算航向带的动态缩放系数
    
    v6.1新增: 针对高空投弹优化
    - 远距离(>15km): 基础缩放1.0x，方便大航向调整
    - 中距离(5-15km): 线性增加缩放
    - 近距离(<5km): 最大缩放4.0x，精确微调
    
    Args:
        distance_km: 到目标距离(公里)
    
    Returns:
        缩放系数(1.0-4.0)
    """
    start_km = ZoneConfig.HEADING_TAPE_SCALE_START_KM
    end_km = ZoneConfig.HEADING_TAPE_SCALE_END_KM
    max_scale = ZoneConfig.HEADING_TAPE_MAX_SCALE
    
    if distance_km >= start_km:
        return 1.0
    elif distance_km <= end_km:
        return max_scale
    else:
        # 线性插值
        ratio = (start_km - distance_km) / (start_km - end_km)
        return 1.0 + ratio * (max_scale - 1.0)
def get_cdi_tolerance(distance_km: float) -> float:
    """根据距离获取动态容差角度
    
    距离越近精度要求越高: >30km±15° / 15-30km±10° / 8-15km±5° / 3-8km±3° / <3km±1.5°
    
    Args:
        distance_km: 到目标的距离(公里)
    
    Returns:
        容差角度(度)
    """
    for threshold_km, tolerance_deg in ZoneConfig.CDI_TOLERANCE_THRESHOLDS:
        if distance_km < threshold_km:
            return tolerance_deg
    return 15.0  # 默认


# ============================================================================
# 导航显示工具函数 - v6.5 重构：复用导航条显示逻辑
# ============================================================================

def calculate_zone_turn_indicator(rel: float, tolerance: float) -> Tuple[str, str]:
    """计算战区转向指示文本和颜色
    
    根据相对方位角计算需要显示的转向指示（左转/右转/保持）
    独立导航条和集成导航条共用此逻辑。
    
    Args:
        rel: 相对方位角（正值=目标在右侧）
        tolerance: 当前距离对应的容差角度
    
    Returns:
        (指示文本, 颜色代码)
    """
    abs_rel = abs(rel)
    
    if abs_rel < 0.1:
        return "▶▶ 保持 ◀◀", Theme.GREEN
    elif abs_rel < 0.5:
        direction = "◀" if rel < 0 else "▶"
        return f"{direction} {abs_rel:.2f}° {direction}", Theme.GREEN
    elif abs_rel < tolerance * 0.3:
        if rel < 0:
            return f"◀ 左修 {abs_rel:.1f}°", Theme.GREEN
        else:
            return f"右修 {abs_rel:.1f}° ▶", Theme.GREEN
    elif rel < 0:
        color = Theme.YELLOW if abs_rel < tolerance else Theme.ORANGE
        return f"◀ 左转 {abs_rel:.1f}°", color
    else:
        color = Theme.YELLOW if abs_rel < tolerance else Theme.ORANGE
        return f"右转 {abs_rel:.1f}° ▶", color


def calculate_zone_status(abs_rel: float, tolerance: float) -> Tuple[str, str]:
    """计算战区状态描述文本和颜色
    
    根据相对方位角计算当前对准状态。
    独立导航条和集成导航条共用此逻辑。
    
    Args:
        abs_rel: 相对方位角的绝对值
        tolerance: 当前距离对应的容差角度
    
    Returns:
        (状态文本, 颜色代码)
    """
    if abs_rel < 0.1:
        return "★ 锁定", Theme.GREEN
    elif abs_rel < 0.3:
        return "精确对准", Theme.GREEN
    elif abs_rel < tolerance * 0.3:
        return "高精度", Theme.GREEN
    elif abs_rel < tolerance * 0.6:
        return "航线内", Theme.BLUE
    elif abs_rel < tolerance:
        return "边缘", Theme.YELLOW
    else:
        return "⚠ 偏航", Theme.ORANGE


def calculate_airfield_turn_indicator(rel: float) -> Tuple[str, str]:
    """计算机场转向指示文本和颜色
    
    独立导航条和集成导航条共用此逻辑。
    
    Args:
        rel: 相对方位角（正值=目标在右侧）
    
    Returns:
        (指示文本, 颜色代码)
    """
    abs_rel = abs(rel)
    
    if abs_rel < 0.1:
        return "▶▶ 保持 ◀◀", Theme.GREEN
    elif abs_rel < 0.5:
        direction = "◀" if rel < 0 else "▶"
        return f"{direction} {abs_rel:.2f}° {direction}", Theme.GREEN
    elif abs_rel < 5:
        if rel < 0:
            return f"◀ 左修 {abs_rel:.1f}°", Theme.BLUE
        else:
            return f"右修 {abs_rel:.1f}° ▶", Theme.BLUE
    elif rel < 0:
        return f"◀ 左转 {abs_rel:.1f}°", Theme.BLUE
    else:
        return f"右转 {abs_rel:.1f}° ▶", Theme.BLUE


def calculate_airfield_status(abs_rel: float) -> Tuple[str, str]:
    """计算机场状态描述文本和颜色
    
    独立导航条和集成导航条共用此逻辑。
    
    Args:
        abs_rel: 相对方位角的绝对值
    
    Returns:
        (状态文本, 颜色代码)
    """
    if abs_rel < 0.1:
        return "★ 锁定", Theme.GREEN
    elif abs_rel < 0.5:
        return "精确对准", Theme.GREEN
    elif abs_rel < 5:
        return "高精度", Theme.GREEN
    elif abs_rel < 15:
        return "航线内", Theme.BLUE
    elif abs_rel < 45:
        return "接近", Theme.BLUE
    else:
        return "偏离", Theme.TEXT_DIM


def format_distance_ete(dist_km: float, ete_str: Optional[str] = None) -> str:
    """格式化距离和预计到达时间
    
    独立导航条和集成导航条共用此逻辑。
    
    Args:
        dist_km: 距离（公里）
        ete_str: 预计到达时间字符串（可选）
    
    Returns:
        格式化后的字符串，如 "12.3km ⏱2:30"
    """
    dist_str = f"{dist_km:.1f}km" if dist_km < 100 else f"{int(dist_km)}km"
    if ete_str:
        return f"{dist_str} ⏱{ete_str}"
    return dist_str


def format_distance_dynamic(distance_km: float) -> str:
    """v6.6.0: 动态精度距离格式化
    
    根据距离自动选择显示精度：
    - Distance > 20 km: 整数 (e.g., 25)
    - Distance 5 - 20 km: 1位小数 (e.g., 8.4)
    - Distance < 5 km: 1位小数或米 (e.g., 1.2 或 800m)
    
    Args:
        distance_km: 距离（公里）
    
    Returns:
        格式化后的距离字符串（不含单位）
    """
    if distance_km > 20:
        return f"{int(distance_km)}"
    elif distance_km >= 1:
        return f"{distance_km:.1f}"
    else:
        # 小于1km时显示米
        meters = int(distance_km * 1000)
        return f"{meters}m"


def get_deviation_color(relative_angle: float, distance_km: float) -> str:
    """v6.6.0: 根据偏差计算语义颜色
    
    距离标签颜色应继承当前航道偏差颜色。
    
    Args:
        relative_angle: 相对角度
        distance_km: 距离（公里）
    
    Returns:
        颜色代码
    """
    tolerance = get_cdi_tolerance(distance_km)
    abs_rel = abs(relative_angle)
    
    if abs_rel < 0.2:
        # 极精准
        return "#00FF00"  # 亮绿
    elif abs_rel <= tolerance * 0.3:
        return Theme.GREEN
    elif abs_rel <= tolerance * 0.6:
        return Theme.BLUE
    elif abs_rel <= tolerance:
        return Theme.YELLOW
    elif abs_rel <= tolerance * 1.5:
        return Theme.ORANGE
    else:
        return Theme.RED


def generate_cdi_indicator(relative_angle: float, distance_km: float) -> Tuple[str, str]:
    """生成高精度航道偏差指示器(CDI)字符串
    
    v6.1升级: 精度从10-20阶梯提升到30阶梯
    
    指示器显示航向与目标方位的偏差:
    - 中心●=完美对准
    - 指示点偏右=目标在右边=需右转
    - 指示点偏左=目标在左边=需左转
    - 超出范围显示溢出箭头◀◀/▶▶
    
    Args:
        relative_angle: 相对方位角(-180~180, 正=目标在右)
        distance_km: 到目标距离(公里)
    
    Returns:
        (指示器字符串, 颜色代码)
    """
    width = ZoneConfig.CDI_WIDTH
    tolerance = get_cdi_tolerance(distance_km)
    
    # 计算偏差比例：relative_angle / tolerance
    # 正值 = 目标在右 = 指示点显示在右边
    if tolerance > 0:
        deviation_ratio = relative_angle / tolerance
    else:
        deviation_ratio = 0.0
    
    # 限制在 -1.5 到 1.5 范围（超出1.0表示溢出）
    clamped_ratio = max(-1.5, min(1.5, deviation_ratio))
    
    # 计算指示点位置（0 = 最左，width-1 = 最右）
    center = (width - 1) // 2
    # 偏差比例映射到位置：ratio=0 -> center, ratio=1 -> 右边界附近
    track_width = center - 1  # 可用的偏移范围
    offset = int(clamped_ratio * track_width)
    pos = center + offset
    pos = max(1, min(width - 2, pos))  # 确保不覆盖边界符号
    
    # 判断是否溢出
    is_overflow_left = deviation_ratio < -1.0
    is_overflow_right = deviation_ratio > 1.0
    
    # 构建指示器字符串
    indicator = [ZoneConfig.CDI_TRACK] * width
    
    # 设置边界
    if is_overflow_left:
        indicator[0] = ZoneConfig.CDI_OVERFLOW_LEFT[0]
        indicator[1] = ZoneConfig.CDI_OVERFLOW_LEFT[1] if len(ZoneConfig.CDI_OVERFLOW_LEFT) > 1 else ZoneConfig.CDI_TRACK
    else:
        indicator[0] = ZoneConfig.CDI_LEFT
    
    if is_overflow_right:
        indicator[-1] = ZoneConfig.CDI_OVERFLOW_RIGHT[-1] if len(ZoneConfig.CDI_OVERFLOW_RIGHT) > 1 else ZoneConfig.CDI_OVERFLOW_RIGHT[0]
        indicator[-2] = ZoneConfig.CDI_OVERFLOW_RIGHT[0]
    else:
        indicator[-1] = ZoneConfig.CDI_RIGHT
    
    # 设置中心指示点
    indicator[pos] = ZoneConfig.CDI_CENTER
    
    # v6.1改进: 更细腻的颜色分级
    abs_ratio = abs(deviation_ratio)
    abs_angle = abs(relative_angle)
    
    if abs_angle < 0.2:
        # 极准（<0.2°），亮绿色
        color = "#00FF00"
    elif abs_ratio <= 0.2:
        # 接近中心（<20%容差），绿色
        color = Theme.GREEN
    elif abs_ratio <= 0.5:
        # 轻微偏差（20-50%容差），蓝色
        color = Theme.BLUE
    elif abs_ratio <= 0.8:
        # 中等偏差（50-80%容差），黄色
        color = Theme.YELLOW
    elif abs_ratio <= 1.0:
        # 接近边界（80-100%容差），橙色
        color = Theme.ORANGE
    else:
        # 严重偏差（超出容差），红色
        color = Theme.RED
    
    return "".join(indicator), color


def generate_cdi_indicator_extended(relative_angle: float, distance_km: float) -> dict:
    """生成扩展CDI信息（包含数值精度）
    
    v6.1新增: 提供更详细的CDI数据用于UI显示
    
    Args:
        relative_angle: 相对方位角(-180~180)
        distance_km: 到目标距离(公里)
    
    Returns:
        dict: {
            'indicator': 字符串指示器,
            'color': 颜色代码,
            'tolerance': 当前容差角度,
            'deviation_ratio': 偏差比例(-1.5~1.5),
            'precision_class': 精度等级(extreme/high/medium/low),
            'pointer_percent': 指针位置百分比(0-100, 50=中心)
        }
    """
    tolerance = get_cdi_tolerance(distance_km)
    indicator_str, color = generate_cdi_indicator(relative_angle, distance_km)
    
    # 计算偏差比例
    deviation_ratio = relative_angle / tolerance if tolerance > 0 else 0.0
    clamped_ratio = max(-1.5, min(1.5, deviation_ratio))
    
    # 指针位置百分比（50=中心，0=最左，100=最右）
    pointer_percent = 50 + (clamped_ratio * 50 / 1.5)
    pointer_percent = max(0, min(100, pointer_percent))
    
    # 精度等级
    abs_angle = abs(relative_angle)
    if abs_angle < 0.5:
        precision_class = "extreme"  # 极精准
    elif abs_angle < tolerance * 0.3:
        precision_class = "high"     # 高精度
    elif abs_angle < tolerance:
        precision_class = "medium"   # 中等
    else:
        precision_class = "low"      # 需要修正
    
    return {
        'indicator': indicator_str,
        'color': color,
        'tolerance': tolerance,
        'deviation_ratio': deviation_ratio,
        'precision_class': precision_class,
        'pointer_percent': pointer_percent,
    }

