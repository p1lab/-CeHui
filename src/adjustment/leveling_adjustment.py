# src/adjustment/leveling_adjustment.py
# 水准测量简易平差（闭合差分配）
#
# 架构原则（同导线平差）：
#   平差是正向解算之后的二次解算，输入=已完成的 LevelingWorkbook，
#   输出=LevelingAdjustment。不修改生成器和验证器的原有逻辑。
#
# 两种场景：
#   1. 单程路线：基于 section.closure_error_mm 按距离反号分配
#   2. 往返测：先取中数 h_mean=(h_fwd-h_ret)/2，再分配路线闭合差
#
# 参考：docs/research_adjustment.md

from __future__ import annotations
import math
from typing import List, Optional

from ..models.leveling import (
    LevelingWorkbook, LevelingSection, ExtraLevelingSection,
    LevelingStation, ExtraLevelingStation,
    LevelingAdjustment, LevelingAdjustmentRecord,
)
from ..models.common import LevelingGrade

# ──────────────────────────────────────────────────────────────────────
# 等级相关的限差系数
# ──────────────────────────────────────────────────────────────────────

_CLOSURE_LIMIT_COEFF = {
    LevelingGrade.GRADE_2: 4.0,
    LevelingGrade.GRADE_3: 12.0,
    LevelingGrade.GRADE_4: 20.0,
    LevelingGrade.EXTRA: 40.0,
}


# ──────────────────────────────────────────────────────────────────────
# 辅助：从测站提取高差和距离
# ──────────────────────────────────────────────────────────────────────

def _extract_station_data_from_section(
    section: LevelingSection,
) -> List[tuple]:
    """
    从 LevelingSection 提取逐站数据.

    优先使用 height_diff_mean_m（验证器已计算），
    否则从原始读数计算 h = a_black - b_black（黑面高差）。

    返回: [(前视点名, 高差m, 本站距离m), ...]
    """
    result = []
    for station in section.stations:
        h = station.height_diff_mean_m
        if h is None:
            # 从原始读数计算（验证器尚未调用）
            a = station.backsight.black_mid_m
            b = station.foresight.black_mid_m
            if a is not None and b is not None:
                h = a - b
            else:
                h = 0.0

        # 本站距离 = (后视距 + 前视距) / 2
        dist_m = None
        if station.stadia_back_m is not None and station.stadia_fore_m is not None:
            dist_m = (station.stadia_back_m + station.stadia_fore_m) / 2.0
        result.append((station.foresight_point, h, dist_m))
    return result


def _extract_station_data_from_extra(
    section: ExtraLevelingSection,
) -> List[tuple]:
    """
    从 ExtraLevelingSection 提取逐站数据.

    优先使用 height_diff_mean_m（验证器已计算），
    否则从原始读数计算 h = (a1-b1 + a2-b2) / 2。

    返回: [(前视点名, 高差m, 本站距离km), ...]
    """
    result = []
    for station in section.stations:
        h = station.height_diff_mean_m
        if h is None:
            # 从原始读数计算
            h1 = station.height_diff_1_m
            h2 = station.height_diff_2_m
            # 如果 h1/h2 为默认 0.0 但原始读数非零，从原始读数计算
            if h1 == 0.0 and station.backsight_1_m != 0.0:
                h1 = station.backsight_1_m - station.foresight_1_m
            if h2 == 0.0 and station.backsight_2_m != 0.0:
                h2 = station.backsight_2_m - station.foresight_2_m
            if h1 != 0.0 or h2 != 0.0:
                h = (h1 + h2) / 2.0
            else:
                h = 0.0
        result.append((station.foresight_point, h, None))
    return result


# ──────────────────────────────────────────────────────────────────────
# 辅助：计算路线总长
# ──────────────────────────────────────────────────────────────────────

def _compute_total_distance_km(
    station_data: List[tuple],
    fallback_km: Optional[float] = None,
) -> float:
    """计算路线总长 (km)."""
    total_m = 0.0
    has_dist = False
    for _, _, dist_m in station_data:
        if dist_m is not None:
            total_m += dist_m
            has_dist = True
    if has_dist:
        return total_m / 1000.0
    return fallback_km or 1.0


# ──────────────────────────────────────────────────────────────────────
# 单程路线平差
# ──────────────────────────────────────────────────────────────────────

def _adjust_single_run(
    station_data: List[tuple],
    start_point_name: str,
    start_height: float,
    end_height: float,
    closure_error_mm: float,
    closure_limit_mm: Optional[float],
    total_distance_km: float,
    grade: LevelingGrade,
) -> LevelingAdjustment:
    """
    单程路线平差：闭合差按距离反号分配.

    算法:
        v_i = -f_h × L_i / ΣL  (按站距比例)
        h'_i = h_i + v_i
        H_i+1 = H_i + h'_i
    """
    n = len(station_data)
    if n == 0:
        return LevelingAdjustment()

    # 逐站距离
    distances_km = []
    for _, _, dist_m in station_data:
        if dist_m is not None:
            distances_km.append(dist_m / 1000.0)
        else:
            # 无视距数据时按等距分配
            distances_km.append(total_distance_km / n)

    sum_dist = sum(distances_km)

    # 改正数分配
    fh_m = closure_error_mm / 1000.0  # 闭合差 (m)
    records: List[LevelingAdjustmentRecord] = []
    cumulative_dist_km = 0.0
    current_height = start_height

    # 起点
    cum_corrections_mm = 0.0

    for i, (point_name, h, _) in enumerate(station_data):
        if h is None:
            h = 0.0

        # 改正数 = -f_h × L_i / ΣL (mm)
        ratio = distances_km[i] / sum_dist if sum_dist > 0 else 1.0 / n
        v_mm = -closure_error_mm * ratio
        cum_corrections_mm += v_mm

        # 改正后高差
        corrected_h = h + v_mm / 1000.0

        # 改正后高程
        current_height += corrected_h

        cumulative_dist_km += distances_km[i]

        records.append(LevelingAdjustmentRecord(
            point_name=point_name,
            distance_km=cumulative_dist_km,
            observed_height_diff_m=h,
            correction_mm=v_mm,
            corrected_height_diff_m=corrected_h,
            height_m=current_height,
        ))

    # 检核：改正后终点高程 = 已知值
    assert abs(current_height - end_height) < 1e-6, (
        f"改正后终点高程={current_height:.6f} ≠ 已知值={end_height:.6f}"
    )

    # 检核：改正数总和 = -f_h
    assert abs(cum_corrections_mm + closure_error_mm) < 1e-8, (
        f"SUM(v)={cum_corrections_mm:.4f} mm ≠ -f_h={-closure_error_mm:.4f} mm"
    )

    # 限差
    if closure_limit_mm is None:
        L_km = total_distance_km or 1.0
        coeff = _CLOSURE_LIMIT_COEFF.get(grade, 12.0)
        closure_limit_mm = coeff * math.sqrt(L_km)

    passed = abs(closure_error_mm) <= closure_limit_mm + 0.01
    corr_per_km = -closure_error_mm / total_distance_km if total_distance_km > 0 else 0.0

    return LevelingAdjustment(
        records=records,
        closure_error_mm=closure_error_mm,
        closure_limit_mm=closure_limit_mm,
        passed=passed,
        correction_per_km_mm=corr_per_km,
        total_distance_km=total_distance_km,
    )


# ──────────────────────────────────────────────────────────────────────
# 往返测平差
# ──────────────────────────────────────────────────────────────────────

def _adjust_round_trip(
    fwd_station_data: List[tuple],
    ret_station_data: List[tuple],
    start_point_name: str,
    start_height: float,
    end_height: float,
    round_trip_discrepancy_mm: Optional[float],
    round_trip_limit_mm: Optional[float],
    total_distance_km: float,
    grade: LevelingGrade,
    fwd_closure_error_mm: float,
    ret_closure_error_mm: float,
) -> LevelingAdjustment:
    """
    往返测平差：先取中数，再分配路线闭合差.

    算法:
        1. h_mean = (h_fwd - h_ret) / 2  （返测高差反号取中数）
        2. 路线闭合差 f_h = SUM(h_mean) - (H_end - H_start)
        3. 按距离分配改正数 v_i = -f_h × L_i / ΣL
        4. 改正后高差和高程
    """
    n = len(fwd_station_data)
    if n == 0:
        return LevelingAdjustment()

    # 往返测逐站高差取中数
    # 返测路线反向，所以第i站返测高差取反
    mean_height_diffs: List[Optional[float]] = []
    point_names: List[str] = []
    distances_km: List[float] = []

    for i in range(n):
        fwd_name, fwd_h, fwd_dist = fwd_station_data[i]
        point_names.append(fwd_name)

        if fwd_h is None:
            fwd_h = 0.0

        # 返测对应站（路线反向）
        ret_h = 0.0
        if i < len(ret_station_data):
            _, ret_h_raw, _ = ret_station_data[i]
            if ret_h_raw is not None:
                ret_h = -ret_h_raw  # 返测高差反号

        # 中数
        h_mean = (fwd_h + ret_h) / 2.0
        mean_height_diffs.append(h_mean)

        # 距离
        if fwd_dist is not None:
            distances_km.append(fwd_dist / 1000.0)
        else:
            distances_km.append(total_distance_km / n)

    sum_dist = sum(distances_km)

    # 路线闭合差（从中数高差计算）
    sum_h_mean = sum(h for h in mean_height_diffs if h is not None)
    expected_diff = end_height - start_height
    fh_m = sum_h_mean - expected_diff
    fh_mm = fh_m * 1000.0

    # 改正数分配
    records: List[LevelingAdjustmentRecord] = []
    cumulative_dist_km = 0.0
    current_height = start_height
    cum_corrections_mm = 0.0

    for i in range(n):
        h = mean_height_diffs[i] if mean_height_diffs[i] is not None else 0.0

        # 改正数 = -f_h × L_i / ΣL (mm)
        ratio = distances_km[i] / sum_dist if sum_dist > 0 else 1.0 / n
        v_mm = -fh_mm * ratio
        cum_corrections_mm += v_mm

        # 改正后高差
        corrected_h = h + v_mm / 1000.0

        # 改正后高程
        current_height += corrected_h

        cumulative_dist_km += distances_km[i]

        records.append(LevelingAdjustmentRecord(
            point_name=point_names[i],
            distance_km=cumulative_dist_km,
            observed_height_diff_m=h,
            correction_mm=v_mm,
            corrected_height_diff_m=corrected_h,
            height_m=current_height,
        ))

    # 检核：改正后终点高程 = 已知值
    assert abs(current_height - end_height) < 1e-6, (
        f"改正后终点高程={current_height:.6f} ≠ 已知值={end_height:.6f}"
    )

    # 检核：改正数总和 = -f_h
    assert abs(cum_corrections_mm + fh_mm) < 1e-8, (
        f"SUM(v)={cum_corrections_mm:.4f} mm ≠ -f_h={-fh_mm:.4f} mm"
    )

    # 限差
    L_km = total_distance_km or 1.0
    coeff = _CLOSURE_LIMIT_COEFF.get(grade, 12.0)
    closure_limit_mm = coeff * math.sqrt(L_km)

    passed = abs(fh_mm) <= closure_limit_mm + 0.01
    corr_per_km = -fh_mm / total_distance_km if total_distance_km > 0 else 0.0

    # 往返测中数总高差
    mean_total_h = sum_h_mean

    return LevelingAdjustment(
        records=records,
        closure_error_mm=fh_mm,
        closure_limit_mm=closure_limit_mm,
        passed=passed,
        correction_per_km_mm=corr_per_km,
        total_distance_km=total_distance_km,
        round_trip_discrepancy_mm=round_trip_discrepancy_mm,
        round_trip_limit_mm=round_trip_limit_mm,
        mean_height_diff_m=mean_total_h,
    )


# ──────────────────────────────────────────────────────────────────────
# 主入口
# ──────────────────────────────────────────────────────────────────────

def adjust_leveling(wb: LevelingWorkbook) -> None:
    """
    水准测量简易平差：就地填充 wb.adjustment 字段.

    前置条件：
        - wb.sections 或 wb.extra_sections 已有测站数据
        - section.closure_error_mm 已由验证器或生成器填入
        - 往返测时 wb.is_round_trip=True 且有两个 sections

    填充字段：
        wb.adjustment = LevelingAdjustment(...)
    """
    if wb.is_round_trip and len(wb.sections) == 2:
        # 往返测
        fwd_section = wb.sections[0]
        ret_section = wb.sections[1]

        fwd_data = _extract_station_data_from_section(fwd_section)
        ret_data = _extract_station_data_from_section(ret_section)

        start_name = fwd_section.route.start_point_name
        start_height = fwd_section.route.start_point_height
        end_height = fwd_section.route.end_point_height

        total_dist_km = _compute_total_distance_km(
            fwd_data, fwd_section.total_distance_km or fwd_section.route.total_length_km
        )

        wb.adjustment = _adjust_round_trip(
            fwd_station_data=fwd_data,
            ret_station_data=ret_data,
            start_point_name=start_name,
            start_height=start_height,
            end_height=end_height,
            round_trip_discrepancy_mm=wb.round_trip_discrepancy_mm,
            round_trip_limit_mm=wb.round_trip_limit_mm,
            total_distance_km=total_dist_km,
            grade=wb.grade,
            fwd_closure_error_mm=fwd_section.closure_error_mm or 0.0,
            ret_closure_error_mm=ret_section.closure_error_mm or 0.0,
        )

    elif wb.sections:
        # 单程路线（LevelingSection）
        section = wb.sections[0]
        station_data = _extract_station_data_from_section(section)

        start_name = section.route.start_point_name
        start_height = section.route.start_point_height
        end_height = section.route.end_point_height

        total_dist_km = _compute_total_distance_km(
            station_data, section.total_distance_km or section.route.total_length_km
        )

        # 从测站数据计算闭合差（验证器可能尚未调用）
        closure_mm = section.closure_error_mm
        if closure_mm is None:
            sum_h = sum(h for _, h, _ in station_data if h is not None)
            expected = end_height - start_height
            closure_mm = (sum_h - expected) * 1000.0

        wb.adjustment = _adjust_single_run(
            station_data=station_data,
            start_point_name=start_name,
            start_height=start_height,
            end_height=end_height,
            closure_error_mm=closure_mm,
            closure_limit_mm=section.closure_limit_mm,
            total_distance_km=total_dist_km,
            grade=wb.grade,
        )

    elif wb.extra_sections:
        # 等外水准（ExtraLevelingSection）
        section = wb.extra_sections[0]
        station_data = _extract_station_data_from_extra(section)

        start_name = section.route.start_point_name
        start_height = section.route.start_point_height
        end_height = section.route.end_point_height

        total_dist_km = _compute_total_distance_km(
            station_data, section.total_distance_km or section.route.total_length_km
        )

        # 从测站数据计算闭合差（验证器可能尚未调用）
        closure_mm = section.closure_error_mm
        if closure_mm is None:
            sum_h = sum(h for _, h, _ in station_data if h is not None)
            expected = end_height - start_height
            closure_mm = (sum_h - expected) * 1000.0

        wb.adjustment = _adjust_single_run(
            station_data=station_data,
            start_point_name=start_name,
            start_height=start_height,
            end_height=end_height,
            closure_error_mm=closure_mm,
            closure_limit_mm=section.closure_limit_mm,
            total_distance_km=total_dist_km,
            grade=wb.grade,
        )
