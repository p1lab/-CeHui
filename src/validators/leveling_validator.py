# src/validators/leveling_validator.py
# 水准测量正向验证器
#
# 功能: 从水准观测手簿计算高程, 验证与输入真值精确相等.
# 这是数学正确性的保障层, 必须在逆向生成器之前完成.
#
# 验证内容:
# 1. 逐站计算: 高差 h = a - b, 视距, 检核差
# 2. 路线汇总: SUM(h), 闭合差 f_h
# 3. 真值验证: 计算高程 vs 已知高程 (精确相等, 容差 1e-10 m)

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional
import math

from ..models.leveling import (
    LevelingStation, LevelingReading,
    LevelingSection, ExtraLevelingSection,
    LevelingWorkbook, ExtraLevelingStation,
    RodSpec,
)
from ..models.common import LevelingGrade, RodType


# ──────────────────────────────────────────────────────────────────────
# 验证结果
# ──────────────────────────────────────────────────────────────────────

@dataclass
class CheckResult:
    """单项检核结果"""
    name: str
    computed: float
    expected: Optional[float] = None
    limit: Optional[float] = None
    passed: bool = True
    message: str = ""


@dataclass
class LevelingValidationResult:
    """水准测量正向验证结果"""
    checks: List[CheckResult] = field(default_factory=list)
    computed_heights: dict = field(default_factory=dict)  # point_name -> height (m)
    errors: List[str] = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return all(c.passed for c in self.checks) and len(self.errors) == 0

    def add_check(self, check: CheckResult):
        self.checks.append(check)

    def add_error(self, msg: str):
        self.errors.append(msg)


# 浮点比较容差
HEIGHT_TOLERANCE_M = 1e-10   # 高程容差 (m), 约 0.0001 nm
READING_TOLERANCE_M = 1e-12  # 读数容差 (m)


# ──────────────────────────────────────────────────────────────────────
# 逐站计算
# ──────────────────────────────────────────────────────────────────────

def compute_stadia_distance(reading: LevelingReading,
                            stadia_constant: float = 100.0) -> Optional[float]:
    """由上下丝计算视距 (axiom A4.1: S = C * (u - l))"""
    return reading.compute_stadia_distance(stadia_constant)


def compute_station_height_diff_black(station: LevelingStation) -> Optional[float]:
    """黑面/基本分划高差 (axiom A1.1: h = a - b)"""
    a = station.backsight.black_mid_m
    b = station.foresight.black_mid_m
    if a is not None and b is not None:
        return a - b
    return None


def compute_station_height_diff_red(station: LevelingStation,
                                     k_back: float, k_fore: float) -> Optional[float]:
    """
    红面高差 (含零点差改正).
    正确公式: h_red = a_red - b_red - (K_back - K_fore)

    推导: 若 red = black + K (K+黑-红=0), 则
      h_red_raw = (a_black+K_back) - (b_black+K_fore) = h_black + (K_back-K_fore)
      h_red_corrected = h_red_raw - (K_back-K_fore) = h_black

    注: axiom A5.4 原文写为 + (K_back - K_fore), 符号有误, 此处已修正.
    """
    a_red = station.backsight.red_mid_m
    b_red = station.foresight.red_mid_m
    if a_red is not None and b_red is not None:
        return a_red - b_red - (k_back - k_fore)
    return None


def compute_station_height_diff_aux(station: LevelingStation) -> Optional[float]:
    """辅助分划高差 (axiom A6.2: h_aux = a_aux - b_aux)"""
    a_aux = station.backsight.aux_mid_m
    b_aux = station.foresight.aux_mid_m
    if a_aux is not None and b_aux is not None:
        return a_aux - b_aux
    return None


def compute_k_plus_black_minus_red(reading: LevelingReading,
                                    k_value: float) -> Optional[float]:
    """
    K+黑-红 检核差 (mm).
    axiom A5.1: delta = K + black - red
    """
    black = reading.black_mid_m
    red = reading.red_mid_m
    if black is not None and red is not None:
        return (k_value + black - red) * 1000.0  # 转换为 mm
    return None


def compute_base_aux_reading_diff(reading: LevelingReading,
                                   c_aux: float) -> Optional[float]:
    """
    基辅读数较差 (mm).
    axiom A6.1: delta = basic - aux + C_aux
    注意: 实际应为 |basic + C_aux - aux|, 即 |aux - basic - C_aux|
    """
    basic = reading.black_mid_m
    aux = reading.aux_mid_m
    if basic is not None and aux is not None:
        return (basic + c_aux - aux) * 1000.0  # 转换为 mm
    return None


# ──────────────────────────────────────────────────────────────────────
# 逐站验证
# ──────────────────────────────────────────────────────────────────────

def validate_station(station: LevelingStation,
                     rod_back: RodSpec,
                     rod_fore: RodSpec,
                     grade: LevelingGrade,
                     result: LevelingValidationResult):
    """
    验证单站水准观测数据.

    填充计算字段, 检查数学一致性.
    """
    prefix = f"站{station.station_number}"

    # ── 黑面/基本高差 ──
    h_black = compute_station_height_diff_black(station)
    if h_black is not None:
        station.height_diff_black_m = h_black
        result.add_check(CheckResult(
            name=f"{prefix}_黑面高差",
            computed=h_black,
            message=f"h = a - b = {station.backsight.black_mid_m:.6f} - "
                    f"{station.foresight.black_mid_m:.6f} = {h_black:.6f} m"
        ))

    # ── 视距 ──
    s_back = compute_stadia_distance(station.backsight)
    s_fore = compute_stadia_distance(station.foresight)
    if s_back is not None:
        station.stadia_back_m = s_back
    if s_fore is not None:
        station.stadia_fore_m = s_fore
    if s_back is not None and s_fore is not None:
        d = s_back - s_fore
        station.distance_diff_m = d

    # ── 双面尺检核 (三四等) ──
    if rod_back.rod_type == RodType.DOUBLE_FACE:
        k_back = rod_back.k_value_m or 4.687
        k_fore = rod_fore.k_value_m or 4.787

        # K+黑-红
        delta_back = compute_k_plus_black_minus_red(station.backsight, k_back)
        delta_fore = compute_k_plus_black_minus_red(station.foresight, k_fore)
        if delta_back is not None:
            station.k_plus_black_minus_red_back_mm = delta_back
        if delta_fore is not None:
            station.k_plus_black_minus_red_fore_mm = delta_fore

        # 红面高差
        h_red = compute_station_height_diff_red(station, k_back, k_fore)
        if h_red is not None:
            station.height_diff_red_m = h_red

        # 高差中数
        if h_black is not None and h_red is not None:
            h_mid = (h_black + h_red) / 2.0
            station.height_diff_mean_m = h_mid

            # 黑红面高差之差
            diff_mm = abs(h_black - h_red) * 1000.0
            station.black_red_height_diff_diff_mm = diff_mm
            result.add_check(CheckResult(
                name=f"{prefix}_黑红面高差之差",
                computed=diff_mm,
                message=f"|h_black - h_red| = {diff_mm:.2f} mm"
            ))

    # ── 基辅分划检核 (二等) ──
    elif rod_back.rod_type == RodType.INVAR_BASIC_AUX:
        c_aux = rod_back.c_aux_m or 3.0155

        # 基辅读数差
        diff_back = compute_base_aux_reading_diff(station.backsight, c_aux)
        diff_fore = compute_base_aux_reading_diff(station.foresight, c_aux)
        if diff_back is not None:
            station.base_aux_reading_diff_back_mm = diff_back
        if diff_fore is not None:
            station.base_aux_reading_diff_fore_mm = diff_fore

        # 辅助分划高差
        h_aux = compute_station_height_diff_aux(station)
        if h_aux is not None:
            station.height_diff_aux_m = h_aux

        # 基本分划高差 = 黑面高差
        station.height_diff_basic_m = h_black

        # 高差中数 (基辅平均)
        if h_black is not None and h_aux is not None:
            h_mid = (h_black + h_aux) / 2.0
            station.height_diff_mean_m = h_mid

            # 基辅高差之差
            diff_mm = abs(h_black - h_aux) * 1000.0
            station.base_aux_height_diff_diff_mm = diff_mm
            result.add_check(CheckResult(
                name=f"{prefix}_基辅高差之差",
                computed=diff_mm,
                message=f"|h_basic - h_aux| = {diff_mm:.3f} mm"
            ))

    # ── 单面尺: 高差中数 = 黑面高差 ──
    else:
        station.height_diff_mean_m = h_black


# ──────────────────────────────────────────────────────────────────────
# 路线验证
# ──────────────────────────────────────────────────────────────────────

def validate_section(section: LevelingSection,
                     result: LevelingValidationResult):
    """
    验证水准测段.

    逐站计算后汇总, 验证闭合差.
    """
    # 逐站验证
    prev_cumulative = 0.0
    sum_a = 0.0
    sum_b = 0.0
    sum_h = 0.0

    for station in section.stations:
        validate_station(station, section.rod_back, section.rod_fore,
                         section.grade, result)

        # 累积视距差
        if station.distance_diff_m is not None:
            prev_cumulative += station.distance_diff_m
            station.cumulative_diff_m = prev_cumulative

        # 汇总
        if station.backsight.black_mid_m is not None:
            sum_a += station.backsight.black_mid_m
        if station.foresight.black_mid_m is not None:
            sum_b += station.foresight.black_mid_m
        if station.height_diff_mean_m is not None:
            sum_h += station.height_diff_mean_m

    section.sum_backsight_m = sum_a
    section.sum_foresight_m = sum_b
    section.sum_height_diff_m = sum_h
    section.station_count = len(section.stations)

    # 路线总长
    total_dist = 0.0
    for station in section.stations:
        if station.stadia_back_m is not None and station.stadia_fore_m is not None:
            total_dist += (station.stadia_back_m + station.stadia_fore_m) / 2.0
    section.total_distance_km = total_dist / 1000.0

    # ── 计算检核: SUM(a) - SUM(b) = SUM(h) ──
    check_sum = sum_a - sum_b
    result.add_check(CheckResult(
        name="计算检核_SUM(a)-SUM(b)=SUM(h)",
        computed=check_sum,
        expected=sum_h,
        passed=abs(check_sum - sum_h) < READING_TOLERANCE_M,
        message=f"SUM(a)-SUM(b) = {check_sum:.6f}, SUM(h) = {sum_h:.6f}"
    ))

    # ── 高程传递 ──
    current_height = section.route.start_point_height
    result.computed_heights[section.route.start_point_name] = current_height

    for station in section.stations:
        if station.height_diff_mean_m is not None:
            current_height += station.height_diff_mean_m
            result.computed_heights[station.foresight_point] = current_height

    # ── 闭合差 ──
    expected_diff = section.route.end_point_height - section.route.start_point_height
    closure_error = sum_h - expected_diff
    closure_error_mm = closure_error * 1000.0
    section.closure_error_mm = closure_error_mm

    # 闭合差限差 (简化计算)
    L_km = section.total_distance_km or section.route.total_length_km or 1.0
    if section.grade == LevelingGrade.GRADE_2:
        limit_coeff = 4.0
    elif section.grade == LevelingGrade.GRADE_3:
        limit_coeff = 12.0
    elif section.grade == LevelingGrade.GRADE_4:
        limit_coeff = 20.0
    else:
        limit_coeff = 40.0

    closure_limit_mm = limit_coeff * math.sqrt(L_km)
    section.closure_limit_mm = closure_limit_mm

    result.add_check(CheckResult(
        name="闭合差",
        computed=closure_error_mm,
        limit=closure_limit_mm,
        passed=abs(closure_error_mm) <= closure_limit_mm + 0.01,
        message=f"f_h = {closure_error_mm:.3f} mm, 限差 = ±{closure_limit_mm:.1f} mm"
    ))

    # ── 真值验证: 终点高程 ──
    end_height_computed = result.computed_heights.get(section.route.end_point_name)
    if end_height_computed is not None:
        result.add_check(CheckResult(
            name="终点高程真值验证",
            computed=end_height_computed,
            expected=section.route.end_point_height,
            passed=abs(end_height_computed - section.route.end_point_height) < HEIGHT_TOLERANCE_M,
            message=f"H_end_computed = {end_height_computed:.6f} m, "
                    f"H_end_known = {section.route.end_point_height:.6f} m"
        ))


# ──────────────────────────────────────────────────────────────────────
# 等外水准验证
# ──────────────────────────────────────────────────────────────────────

def validate_extra_station(station: ExtraLevelingStation,
                            result: LevelingValidationResult):
    """验证等外水准单站 (变动仪高法)"""
    prefix = f"站{station.station_number}"

    station.height_diff_1_m = station.backsight_1_m - station.foresight_1_m
    station.height_diff_2_m = station.backsight_2_m - station.foresight_2_m

    diff_mm = abs(station.height_diff_1_m - station.height_diff_2_m) * 1000.0
    station.height_diff_diff_mm = diff_mm
    station.height_diff_mean_m = (station.height_diff_1_m + station.height_diff_2_m) / 2.0

    result.add_check(CheckResult(
        name=f"{prefix}_变动仪高较差",
        computed=diff_mm,
        limit=5.0,
        passed=diff_mm <= 5.0 + 0.01,
        message=f"|h1 - h2| = {diff_mm:.2f} mm, 限差 ≤ 5 mm"
    ))


def validate_extra_section(section: ExtraLevelingSection,
                            result: LevelingValidationResult):
    """验证等外水准测段"""
    sum_h = 0.0
    current_height = section.route.start_point_height
    result.computed_heights[section.route.start_point_name] = current_height

    for station in section.stations:
        validate_extra_station(station, result)
        if station.height_diff_mean_m is not None:
            sum_h += station.height_diff_mean_m
            current_height += station.height_diff_mean_m
            result.computed_heights[station.foresight_point] = current_height

    section.sum_height_diff_m = sum_h

    # 闭合差
    expected_diff = section.route.end_point_height - section.route.start_point_height
    closure_error_mm = (sum_h - expected_diff) * 1000.0
    section.closure_error_mm = closure_error_mm

    L_km = section.total_distance_km or section.route.total_length_km or 1.0
    closure_limit_mm = 40.0 * math.sqrt(L_km)
    section.closure_limit_mm = closure_limit_mm

    result.add_check(CheckResult(
        name="等外闭合差",
        computed=closure_error_mm,
        limit=closure_limit_mm,
        passed=abs(closure_error_mm) <= closure_limit_mm + 0.01,
        message=f"f_h = {closure_error_mm:.3f} mm, 限差 = ±{closure_limit_mm:.1f} mm"
    ))


# ──────────────────────────────────────────────────────────────────────
# 完整手簿验证
# ──────────────────────────────────────────────────────────────────────

def validate_leveling_workbook(workbook: LevelingWorkbook) -> LevelingValidationResult:
    """
    验证完整水准观测手簿.

    对每个测段执行正向验证, 返回验证结果.
    """
    result = LevelingValidationResult()

    for section in workbook.sections:
        validate_section(section, result)

    for section in workbook.extra_sections:
        validate_extra_section(section, result)

    return result
