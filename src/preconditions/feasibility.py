# src/preconditions/feasibility.py
# 可行性预检: RTK 精度 vs 目标等级判定
#
# 数学基础: docs/error_propagation.md A7
#
# 水准 (A7.1):
#   sigma_dh = sqrt(2) * sigma_H
#   if sigma_dh > target_per_station_h_error * multiplier → 警告
#
# 导线 (A7.2):
#   sigma_alpha = (sigma_XY / D_min) * rho
#   if sigma_alpha > target_angle_error * multiplier → 警告
#
# 数学真值模式 (A7.3): 跳过预检, 附加强制声明

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from ..models.common import LevelingGrade, TraverseGrade


# ──────────────────────────────────────────────────────────────────────
# 常量
# ──────────────────────────────────────────────────────────────────────

# 弧秒转换常数 (精确)
_RHO = 180.0 * 3600 / math.pi  # ≈ 206264.806

# RTK 默认精度 (config: rtk_reference.defaults_for_formulas)
_DEFAULT_SIGMA_H_M = 0.03     # 高程精度 3 cm
_DEFAULT_SIGMA_XY_M = 0.02    # 平面精度 2 cm

# 阈值倍数 (config: feasibility_check.threshold_multiplier)
_DEFAULT_THRESHOLD_MULTIPLIER = 3.0

# 强制声明 (config: feasibility_check.math_true_value_mode.mandatory_disclaimer)
_MATH_TRUE_VALUE_DISCLAIMER = (
    "本数据基于数学真值假设模拟生成, 不代表RTK实测精度可达目标等级"
)

# 各等级每站高差中误差 (mm)
# Grade 2: config 显式值 0.15
# Grade 3/4/Extra: 从闭合差系数推算
#   sigma_station ≈ flat_coefficient / sqrt(2 * stations_per_km)
#   假设站距 50m → 20 站/km → sqrt(40) ≈ 6.32
_LEVELING_TARGETS_MM: dict = {
    LevelingGrade.GRADE_2: 0.15,   # config: per_station_height_diff_mean_error_mm
    LevelingGrade.GRADE_3: 1.9,    # 从 flat_coefficient=12 推算: 12/6.32
    LevelingGrade.GRADE_4: 3.2,    # 从 flat_coefficient=20 推算: 20/6.32
    LevelingGrade.EXTRA:   6.3,    # 从 flat_coefficient=40 推算: 40/6.32
}

# 各等级测角中误差 (arcsec, config 显式)
_TRAVERSING_TARGETS_ARCSEC: dict = {
    TraverseGrade.GRADE_1: 5.0,    # config: measurement_mean_error_arcsec
    TraverseGrade.GRADE_2: 10.0,
    TraverseGrade.ROOT:    25.0,   # 取 [20, 30] 中值
}


# ──────────────────────────────────────────────────────────────────────
# 数据结构
# ──────────────────────────────────────────────────────────────────────

@dataclass
class FeasibilityItem:
    """单条可行性检核项."""
    name: str           # 检核项名称
    computed: float     # 计算值 (sigma_dh mm 或 sigma_alpha arcsec)
    threshold: float    # 阈值 (target * multiplier)
    passed: bool        # True=可行, False=不可行
    message: str        # 描述

    @property
    def unit(self) -> str:
        """根据 name 推断单位."""
        if "高差" in self.name or "sigma_dh" in self.name:
            return "mm"
        return "arcsec"


@dataclass
class FeasibilityReport:
    """可行性预检报告."""
    items: List[FeasibilityItem]
    survey_type: str          # "leveling" 或 "traversing"
    target_grade: str         # 等级值 (如 "grade_2", "grade_1")
    feasible: bool            # 全部通过 (非跳过时)
    skipped: bool             # 数学真值模式跳过
    disclaimer: str           # 跳过时的强制声明, 非跳过时为空
    warnings: List[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        """生成摘要文本."""
        if self.skipped:
            return (
                f"[{self.survey_type}/{self.target_grade}] "
                f"可行性预检已跳过 (数学真值模式). {self.disclaimer}"
            )
        status = "可行" if self.feasible else "不可行"
        details = "; ".join(
            f"{it.name}: {it.computed:.2f} {it.unit} vs {it.threshold:.2f} {it.unit}"
            for it in self.items
        )
        return f"[{self.survey_type}/{self.target_grade}] {status}: {details}"


# ──────────────────────────────────────────────────────────────────────
# 水准可行性预检
# ──────────────────────────────────────────────────────────────────────

def check_leveling_feasibility(
    grade: LevelingGrade,
    sigma_H_m: float = _DEFAULT_SIGMA_H_M,
    threshold_multiplier: float = _DEFAULT_THRESHOLD_MULTIPLIER,
    math_true_value_mode: bool = True,
) -> FeasibilityReport:
    """
    水准可行性预检 (A7.1).

    判定 RTK 高程精度是否足以模拟目标等级.

    Args:
        grade: 目标水准等级
        sigma_H_m: RTK 高程精度 (m), 默认 0.03 (3cm)
        threshold_multiplier: 阈值倍数, 默认 3.0
        math_true_value_mode: 数学真值模式 (跳过预检)

    Returns:
        FeasibilityReport
    """
    # 数学真值模式: 跳过
    if math_true_value_mode:
        return FeasibilityReport(
            items=[],
            survey_type="leveling",
            target_grade=grade.value,
            feasible=True,   # 跳过时视为可行
            skipped=True,
            disclaimer=_MATH_TRUE_VALUE_DISCLAIMER,
        )

    # A7.1: sigma_dh = sqrt(2) * sigma_H
    sigma_dh_mm = math.sqrt(2) * sigma_H_m * 1000  # m → mm

    target_mm = _LEVELING_TARGETS_MM.get(grade)
    if target_mm is None:
        return FeasibilityReport(
            items=[],
            survey_type="leveling",
            target_grade=grade.value,
            feasible=False,
            skipped=False,
            disclaimer="",
            warnings=[f"未知等级: {grade.value}"],
        )

    threshold_mm = target_mm * threshold_multiplier
    passed = sigma_dh_mm <= threshold_mm

    item = FeasibilityItem(
        name="RTK高程噪声 vs 每站高差中误差",
        computed=sigma_dh_mm,
        threshold=threshold_mm,
        passed=passed,
        message=(
            f"σ_dh = √2 × {sigma_H_m*1000:.1f}mm = {sigma_dh_mm:.2f}mm, "
            f"阈值 = {target_mm:.2f}mm × {threshold_multiplier} = {threshold_mm:.2f}mm"
        ),
    )

    warnings = []
    if not passed:
        warnings.append(
            f"RTK 高程精度 ({sigma_dh_mm:.1f}mm) 不足以模拟 {grade.value} "
            f"(需要 ≤ {threshold_mm:.1f}mm, 差 {sigma_dh_mm/threshold_mm:.1f} 倍)"
        )

    return FeasibilityReport(
        items=[item],
        survey_type="leveling",
        target_grade=grade.value,
        feasible=passed,
        skipped=False,
        disclaimer="",
        warnings=warnings,
    )


# ──────────────────────────────────────────────────────────────────────
# 导线可行性预检
# ──────────────────────────────────────────────────────────────────────

def _compute_min_edge_length(
    points: List[Tuple[str, float, float]],
) -> Optional[float]:
    """
    从坐标点序列计算最短边长 (m).

    Args:
        points: [(name, x, y), ...] 至少 2 个点

    Returns:
        最短边长 (m), 点不足时返回 None
    """
    if len(points) < 2:
        return None

    min_dist = float('inf')
    for i in range(len(points) - 1):
        _, x1, y1 = points[i]
        _, x2, y2 = points[i + 1]
        dist = math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)
        if dist < min_dist:
            min_dist = dist

    return min_dist if min_dist < float('inf') else None


def check_traversing_feasibility(
    grade: TraverseGrade,
    points: Optional[List[Tuple[str, float, float]]] = None,
    min_edge_m: Optional[float] = None,
    sigma_XY_m: float = _DEFAULT_SIGMA_XY_M,
    threshold_multiplier: float = _DEFAULT_THRESHOLD_MULTIPLIER,
    math_true_value_mode: bool = True,
) -> FeasibilityReport:
    """
    导线可行性预检 (A7.2).

    判定 RTK 平面精度是否足以模拟目标等级导线.

    Args:
        grade: 目标导线等级
        points: 坐标点序列 [(name, x, y), ...], 用于计算 D_min
        min_edge_m: 最短边长 (m), 若提供则优先使用, 否则从 points 计算
        sigma_XY_m: RTK 平面精度 (m), 默认 0.02 (2cm)
        threshold_multiplier: 阈值倍数, 默认 3.0
        math_true_value_mode: 数学真值模式 (跳过预检)

    Returns:
        FeasibilityReport
    """
    # 数学真值模式: 跳过
    if math_true_value_mode:
        return FeasibilityReport(
            items=[],
            survey_type="traversing",
            target_grade=grade.value,
            feasible=True,
            skipped=True,
            disclaimer=_MATH_TRUE_VALUE_DISCLAIMER,
        )

    # 计算 D_min
    d_min = min_edge_m
    if d_min is None and points is not None:
        d_min = _compute_min_edge_length(points)

    if d_min is None or d_min <= 0:
        return FeasibilityReport(
            items=[],
            survey_type="traversing",
            target_grade=grade.value,
            feasible=False,
            skipped=False,
            disclaimer="",
            warnings=["无法确定最短边长, 需提供 points 或 min_edge_m"],
        )

    # A7.2: sigma_alpha = (sigma_XY / D_min) * rho
    sigma_alpha_arcsec = (sigma_XY_m / d_min) * _RHO

    target_arcsec = _TRAVERSING_TARGETS_ARCSEC.get(grade)
    if target_arcsec is None:
        return FeasibilityReport(
            items=[],
            survey_type="traversing",
            target_grade=grade.value,
            feasible=False,
            skipped=False,
            disclaimer="",
            warnings=[f"未知等级: {grade.value}"],
        )

    threshold_arcsec = target_arcsec * threshold_multiplier
    passed = sigma_alpha_arcsec <= threshold_arcsec

    item = FeasibilityItem(
        name="RTK平面噪声 vs 测角中误差",
        computed=sigma_alpha_arcsec,
        threshold=threshold_arcsec,
        passed=passed,
        message=(
            f"σ_α = ({sigma_XY_m*100:.1f}cm / {d_min:.1f}m) × ρ "
            f"= {sigma_alpha_arcsec:.2f}\", "
            f"阈值 = {target_arcsec:.1f}\" × {threshold_multiplier} "
            f"= {threshold_arcsec:.2f}\""
        ),
    )

    warnings = []
    if not passed:
        warnings.append(
            f"RTK 平面精度 (σ_α={sigma_alpha_arcsec:.1f}\") 不足以模拟 "
            f"{grade.value} (需要 ≤ {threshold_arcsec:.1f}\", "
            f"差 {sigma_alpha_arcsec/threshold_arcsec:.1f} 倍)"
        )

    return FeasibilityReport(
        items=[item],
        survey_type="traversing",
        target_grade=grade.value,
        feasible=passed,
        skipped=False,
        disclaimer="",
        warnings=warnings,
    )
