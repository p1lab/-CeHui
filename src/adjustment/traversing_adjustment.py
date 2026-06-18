# src/adjustment/traversing_adjustment.py
# 导线简易平差（闭合差分配）
#
# 架构原则：
#   平差是正向解算之后的二次解算，输入=已完成的 TraverseComputation，
#   输出=改正数+改正后值。不修改 _build_computation() 和
#   validate_traverse_computation() 的原有逻辑。
#
# 4 步平差：
#   1. 角度闭合差分配（反号平均，余数短边优先）
#   2. 改正后方位角推算
#   3. 坐标增量闭合差分配（按边长比例）
#   4. 改正后坐标推算
#
# 参考：docs/research_adjustment.md

from __future__ import annotations
import math
from typing import List

from ..models.traversing import TraverseComputation, TraversePointRecord
from ..models.common import AngleDefinition

# ──────────────────────────────────────────────────────────────────────
# 数学工具（自包含，不依赖 generators/validators 内部函数）
# ──────────────────────────────────────────────────────────────────────

_RO_ARCSEC = 180.0 * 3600.0 / math.pi  # 弧度→角秒 精确常数
_TWO_PI = 2.0 * math.pi


def _normalize_angle(rad: float) -> float:
    """归一化到 [0, 2π)"""
    return rad % _TWO_PI


def _normalize_small(rad: float) -> float:
    """归化到 (-π, π]（小角度）"""
    return (rad + math.pi) % _TWO_PI - math.pi


def _propagate_azimuth(current_az: float, angle_rad: float,
                       angle_def: AngleDefinition) -> float:
    """方位角递推（同 axiom A1.3）"""
    if angle_def == AngleDefinition.LEFT_ANGLE:
        return _normalize_angle(current_az + angle_rad - math.pi)
    else:
        return _normalize_angle(current_az - angle_rad + math.pi)


# ──────────────────────────────────────────────────────────────────────
# 辅助：计算方位角闭合差
# ──────────────────────────────────────────────────────────────────────

def _compute_azimuth_closure_arcsec(comp: TraverseComputation) -> float:
    """
    从已有 edge_records 推算方位角闭合差（角秒）.

    仅当 comp.azimuth_closure_error_arcsec 为 None 时使用.
    """
    info = comp.info
    angle_def = info.angle_definition

    # 起始方位角
    if info.start_reference_azimuth is not None:
        current_az = info.start_reference_azimuth
    else:
        current_az = info.start_azimuth
        if current_az is None and len(comp.point_records) >= 2:
            dx = (comp.point_records[1].x_m or 0.0) - (comp.point_records[0].x_m or 0.0)
            dy = (comp.point_records[1].y_m or 0.0) - (comp.point_records[0].y_m or 0.0)
            current_az = _normalize_angle(math.atan2(dy, dx))

    for er in comp.edge_records:
        if er.observed_angle_rad is not None:
            current_az = _propagate_azimuth(
                current_az, er.observed_angle_rad, angle_def)

    target_end = info.end_reference_azimuth or info.end_azimuth
    if target_end is None:
        return 0.0

    f_beta = _normalize_small(current_az - target_end)
    return f_beta * _RO_ARCSEC


# ──────────────────────────────────────────────────────────────────────
# 主入口
# ──────────────────────────────────────────────────────────────────────

def adjust_traverse(comp: TraverseComputation) -> None:
    """
    导线简易平差：就地填充 TraversePointRecord 的预留字段.

    前置条件：
        - comp.edge_records 已填充 observed_angle_rad, distance_m, delta_x_m, delta_y_m
        - comp.fx_m / fy_m 已由正向传播/验证器填入
        - comp.azimuth_closure_error_arcsec 已填入（若为 None 则内部计算）

    填充字段：
        angle_correction_rad, corrected_angle_rad,
        distance_correction_m (固定0),
        delta_x_correction_m, delta_y_correction_m,
        corrected_delta_x_m, corrected_delta_y_m,
        corrected_x_m, corrected_y_m
    """
    info = comp.info
    edge_records = comp.edge_records
    point_records = comp.point_records
    angle_def = info.angle_definition

    # ── 确定需要改正的观测角 ──
    angle_edges = [er for er in edge_records if er.observed_angle_rad is not None]
    n_angles = len(angle_edges)
    if n_angles == 0:
        return

    # ══════════════════════════════════════════════════════════════════
    # 第一步：角度闭合差分配
    # ══════════════════════════════════════════════════════════════════
    f_beta_arcsec = comp.azimuth_closure_error_arcsec
    if f_beta_arcsec is None:
        f_beta_arcsec = _compute_azimuth_closure_arcsec(comp)

    f_beta_rad = f_beta_arcsec / _RO_ARCSEC

    # 角度改正数离散化到 0.1" 步长，余数分配给短边
    step_arcsec = 0.1  # 离散化步长（角秒）
    needed_total = -f_beta_arcsec

    # 先按四舍五入得到均分基础改正数（避免 floor 的负向偏置）
    base_steps = int(round(needed_total / n_angles / step_arcsec))
    corrections_arcsec = [base_steps * step_arcsec] * n_angles

    # 计算与目标总改正量的差额，按 0.1" 整数倍分配给短边
    residual_arcsec = needed_total - sum(corrections_arcsec)
    n_extra = int(round(residual_arcsec / step_arcsec))

    # 余数分配给短边（距离短的边角度不确定性更大）
    # 虚拟边（distance_m=None）排最后
    if n_extra != 0:
        indexed = list(range(n_angles))
        indexed.sort(key=lambda i: angle_edges[i].distance_m
                     if angle_edges[i].distance_m is not None else float('inf'))
        sign = 1 if n_extra > 0 else -1
        for k in range(abs(n_extra)):
            corrections_arcsec[indexed[k % n_angles]] += sign * step_arcsec

    # 填充角度改正数和改正后角值
    for i, er in enumerate(angle_edges):
        er.angle_correction_rad = corrections_arcsec[i] / _RO_ARCSEC
        er.corrected_angle_rad = er.observed_angle_rad + er.angle_correction_rad

    # 检核：SUM(v_beta) = -f_beta（0.1" 精度内）
    sum_v_beta_arcsec = sum(corrections_arcsec)
    _check = abs(sum_v_beta_arcsec - needed_total)
    assert _check < step_arcsec * 0.5 + 1e-9, (
        f"SUM(v_beta)={sum_v_beta_arcsec:.2f}\" ≠ "
        f"-f_beta={needed_total:.2f}\""
    )

    # ══════════════════════════════════════════════════════════════════
    # 第二步：改正后方位角推算
    # ══════════════════════════════════════════════════════════════════
    has_start_ref = info.start_reference_azimuth is not None

    if has_start_ref:
        current_az = info.start_reference_azimuth
    else:
        current_az = info.start_azimuth
        if current_az is None and len(point_records) >= 2:
            dx = (point_records[1].x_m or 0.0) - (point_records[0].x_m or 0.0)
            dy = (point_records[1].y_m or 0.0) - (point_records[0].y_m or 0.0)
            current_az = _normalize_angle(math.atan2(dy, dx))

    corrected_azimuths = [current_az]
    for er in angle_edges:
        current_az = _propagate_azimuth(current_az, er.corrected_angle_rad, angle_def)
        corrected_azimuths.append(current_az)

    # 将改正后方位角写回对应的边
    for i, er in enumerate(angle_edges):
        er.azimuth_rad = corrected_azimuths[i + 1]

    # ══════════════════════════════════════════════════════════════════
    # 第三步：坐标增量闭合差分配
    # ══════════════════════════════════════════════════════════════════
    real_edges = [er for er in edge_records if er.distance_m is not None]
    total_length = sum(er.distance_m for er in real_edges)

    fx = comp.fx_m or 0.0
    fy = comp.fy_m or 0.0

    for er in real_edges:
        ratio = er.distance_m / total_length if total_length > 0 else 0.0
        er.delta_x_correction_m = -fx * ratio
        er.delta_y_correction_m = -fy * ratio
        er.corrected_delta_x_m = (er.delta_x_m or 0.0) + er.delta_x_correction_m
        er.corrected_delta_y_m = (er.delta_y_m or 0.0) + er.delta_y_correction_m
        er.distance_correction_m = 0.0  # 简易平差不改距离

    # 检核：SUM(v_x) = -fx, SUM(v_y) = -fy
    sum_vx = sum(er.delta_x_correction_m for er in real_edges)
    sum_vy = sum(er.delta_y_correction_m for er in real_edges)
    assert abs(sum_vx + fx) < 1e-8, (
        f"SUM(v_x)={sum_vx * 1000:.4f} mm ≠ -fx={-fx * 1000:.4f} mm"
    )
    assert abs(sum_vy + fy) < 1e-8, (
        f"SUM(v_y)={sum_vy * 1000:.4f} mm ≠ -fy={-fy * 1000:.4f} mm"
    )

    # ══════════════════════════════════════════════════════════════════
    # 第四步：改正后坐标推算
    # ══════════════════════════════════════════════════════════════════
    cx = info.start_point_x
    cy = info.start_point_y

    if len(point_records) > 0:
        point_records[0].corrected_x_m = cx
        point_records[0].corrected_y_m = cy

    # 遍历 edge_records，对实边累加改正后增量
    point_idx = 1
    for er in edge_records:
        if er.distance_m is not None:
            cx += er.corrected_delta_x_m or 0.0
            cy += er.corrected_delta_y_m or 0.0
            if point_idx < len(point_records):
                point_records[point_idx].corrected_x_m = cx
                point_records[point_idx].corrected_y_m = cy
            point_idx += 1

    # 检核终点坐标
    if len(point_records) > 0:
        last = point_records[-1]
        if last.corrected_x_m is not None:
            assert abs(last.corrected_x_m - info.end_point_x) < 1e-6, (
                f"改正后终点X={last.corrected_x_m:.6f} ≠ "
                f"已知值={info.end_point_x:.6f}"
            )
            assert abs(last.corrected_y_m - info.end_point_y) < 1e-6, (
                f"改正后终点Y={last.corrected_y_m:.6f} ≠ "
                f"已知值={info.end_point_y:.6f}"
            )
