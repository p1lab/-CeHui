# src/checkers/leveling_compliance.py
# 水准测量合规性检核
#
# 功能: 对照规范限差 (config_leveling.json) 逐项检查观测数据合规性.
# 前置: 需先运行正向验证器填充计算字段.
#
# 检核项:
#   1. 视距长度 (max_length_m)
#   2. 前后视距差 (max_station_distance_diff_m)
#   3. 累积视距差 (max_cumulative_distance_diff_m)
#   4. K+黑-红 (双面尺, k_plus_black_minus_red_mm)
#   5. 黑红面高差之差 (双面尺, black_red_height_diff_diff_mm)
#   6. 基辅读数差 (因瓦尺, base_aux_reading_diff_mm)
#   7. 基辅高差之差 (因瓦尺, base_aux_height_diff_mm)
#   8. 路线闭合差 (closure.flat_coefficient * sqrt(L_km))
#   9. 等外变动仪高较差 (height_diff_diff_mm <= 5mm)

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional
import math

from ..models.common import LevelingGrade, RodType
from ..models.leveling import LevelingWorkbook, LevelingSection, ExtraLevelingSection
from ..validators.leveling_validator import validate_leveling_workbook


# ──────────────────────────────────────────────────────────────────────
# 数据结构
# ──────────────────────────────────────────────────────────────────────

@dataclass
class ComplianceItem:
    """单项合规检核结果"""
    name: str
    computed: float
    limit: float
    passed: bool
    message: str
    station: str = ""


@dataclass
class LevelingComplianceReport:
    """水准合规检核报告"""
    items: List[ComplianceItem] = field(default_factory=list)
    grade: LevelingGrade = LevelingGrade.GRADE_3
    passed: bool = True
    warnings: List[str] = field(default_factory=list)

    def add_item(self, item: ComplianceItem):
        self.items.append(item)
        if not item.passed:
            self.passed = False

    def add_warning(self, msg: str):
        self.warnings.append(msg)


# ──────────────────────────────────────────────────────────────────────
# 限差参数 (硬编码, 与 config_leveling.json 保持一致)
# ──────────────────────────────────────────────────────────────────────

_LEVELING_LIMITS = {
    LevelingGrade.GRADE_2: {
        "max_sight_length_m": 50.0,
        "max_station_distance_diff_m": 1.0,
        "max_cumulative_distance_diff_m": 3.0,
        "base_aux_reading_diff_mm": 0.5,
        "base_aux_height_diff_mm": 0.7,
        "closure_coefficient": 4.0,
    },
    LevelingGrade.GRADE_3: {
        "max_sight_length_m": 75.0,
        "max_station_distance_diff_m": 3.0,
        "max_cumulative_distance_diff_m": 10.0,
        "k_plus_black_minus_red_mm": 2.0,
        "black_red_height_diff_diff_mm": 5.0,
        "closure_coefficient": 12.0,
    },
    LevelingGrade.GRADE_4: {
        "max_sight_length_m": 100.0,
        "max_station_distance_diff_m": 3.0,
        "max_cumulative_distance_diff_m": 10.0,
        "k_plus_black_minus_red_mm": 3.0,
        "black_red_height_diff_diff_mm": 5.0,
        "closure_coefficient": 20.0,
    },
    LevelingGrade.EXTRA: {
        "height_diff_diff_mm": 5.0,
        "closure_coefficient": 40.0,
    },
}


# ──────────────────────────────────────────────────────────────────────
# 辅助检核函数
# ──────────────────────────────────────────────────────────────────────

def _check_section_stations(
    section: LevelingSection,
    grade: LevelingGrade,
    limits: dict,
    report: LevelingComplianceReport,
):
    """检核正规测段 (Grade 2/3/4) 各站限差."""
    rod_back = section.rod_back

    for st in section.stations:
        sn = f"站{st.station_number}"

        # ── 视距长度 ──
        max_sight = limits.get("max_sight_length_m")
        if max_sight is not None:
            for label, dist in [("后视", st.stadia_back_m),
                                ("前视", st.stadia_fore_m)]:
                if dist is not None:
                    report.add_item(ComplianceItem(
                        name=f"{sn}_{label}视距长度",
                        computed=dist,
                        limit=max_sight,
                        passed=dist <= max_sight,
                        message=f"{dist:.1f} m ≤ {max_sight:.1f} m",
                        station=sn,
                    ))

        # ── 前后视距差 ──
        max_dd = limits.get("max_station_distance_diff_m")
        if max_dd is not None and st.distance_diff_m is not None:
            abs_dd = abs(st.distance_diff_m)
            report.add_item(ComplianceItem(
                name=f"{sn}_前后视距差",
                computed=abs_dd,
                limit=max_dd,
                passed=abs_dd <= max_dd,
                message=f"|d| = {abs_dd:.2f} m ≤ {max_dd:.1f} m",
                station=sn,
            ))

        # ── 累积视距差 ──
        max_cd = limits.get("max_cumulative_distance_diff_m")
        if max_cd is not None and st.cumulative_diff_m is not None:
            abs_cd = abs(st.cumulative_diff_m)
            report.add_item(ComplianceItem(
                name=f"{sn}_累积视距差",
                computed=abs_cd,
                limit=max_cd,
                passed=abs_cd <= max_cd,
                message=f"|Σd| = {abs_cd:.2f} m ≤ {max_cd:.1f} m",
                station=sn,
            ))

        # ── 双面尺检核 ──
        if rod_back.rod_type == RodType.DOUBLE_FACE:
            k_limit = limits.get("k_plus_black_minus_red_mm")
            if k_limit is not None:
                for label, val in [("后视", st.k_plus_black_minus_red_back_mm),
                                   ("前视", st.k_plus_black_minus_red_fore_mm)]:
                    if val is not None:
                        abs_val = abs(val)
                        report.add_item(ComplianceItem(
                            name=f"{sn}_K+黑-红_{label}",
                            computed=abs_val,
                            limit=k_limit,
                            passed=abs_val <= k_limit,
                            message=f"|K+黑-红| = {abs_val:.2f} mm ≤ {k_limit:.1f} mm",
                            station=sn,
                        ))

            hr_limit = limits.get("black_red_height_diff_diff_mm")
            if hr_limit is not None and st.black_red_height_diff_diff_mm is not None:
                report.add_item(ComplianceItem(
                    name=f"{sn}_黑红面高差之差",
                    computed=st.black_red_height_diff_diff_mm,
                    limit=hr_limit,
                    passed=st.black_red_height_diff_diff_mm <= hr_limit,
                    message=(f"|Δh| = {st.black_red_height_diff_diff_mm:.2f} mm "
                             f"≤ {hr_limit:.1f} mm"),
                    station=sn,
                ))

        # ── 因瓦基辅检核 ──
        elif rod_back.rod_type == RodType.INVAR_BASIC_AUX:
            ba_limit = limits.get("base_aux_reading_diff_mm")
            if ba_limit is not None:
                for label, val in [("后视", st.base_aux_reading_diff_back_mm),
                                   ("前视", st.base_aux_reading_diff_fore_mm)]:
                    if val is not None:
                        abs_val = abs(val)
                        report.add_item(ComplianceItem(
                            name=f"{sn}_基辅读数差_{label}",
                            computed=abs_val,
                            limit=ba_limit,
                            passed=abs_val <= ba_limit,
                            message=(f"|基辅差| = {abs_val:.3f} mm "
                                     f"≤ {ba_limit:.1f} mm"),
                            station=sn,
                        ))

            bah_limit = limits.get("base_aux_height_diff_mm")
            if bah_limit is not None and st.base_aux_height_diff_diff_mm is not None:
                report.add_item(ComplianceItem(
                    name=f"{sn}_基辅高差之差",
                    computed=st.base_aux_height_diff_diff_mm,
                    limit=bah_limit,
                    passed=st.base_aux_height_diff_diff_mm <= bah_limit,
                    message=(f"|Δh| = {st.base_aux_height_diff_diff_mm:.3f} mm "
                             f"≤ {bah_limit:.1f} mm"),
                    station=sn,
                ))


def _check_extra_section(
    section: ExtraLevelingSection,
    limits: dict,
    report: LevelingComplianceReport,
):
    """检核等外水准测段 (变动仪高法)."""
    hd_limit = limits.get("height_diff_diff_mm", 5.0)

    for st in section.stations:
        sn = f"站{st.station_number}"
        if st.height_diff_diff_mm is not None:
            report.add_item(ComplianceItem(
                name=f"{sn}_变动仪高较差",
                computed=st.height_diff_diff_mm,
                limit=hd_limit,
                passed=st.height_diff_diff_mm <= hd_limit + 0.01,
                message=(f"|h1-h2| = {st.height_diff_diff_mm:.2f} mm "
                         f"≤ {hd_limit:.1f} mm"),
                station=sn,
            ))


def _check_closure(
    section, grade: LevelingGrade, limits: dict,
    report: LevelingComplianceReport,
):
    """检核路线闭合差."""
    coeff = limits.get("closure_coefficient")
    if coeff is None:
        return

    L_km = section.total_distance_km or section.route.total_length_km or 1.0
    limit_mm = coeff * math.sqrt(L_km)

    # 填充 section 的 closure_limit_mm (供后续使用)
    section.closure_limit_mm = limit_mm

    if section.closure_error_mm is not None:
        abs_closure = abs(section.closure_error_mm)
        report.add_item(ComplianceItem(
            name="路线闭合差",
            computed=abs_closure,
            limit=limit_mm,
            passed=abs_closure <= limit_mm + 0.01,
            message=(f"|f_h| = {abs_closure:.3f} mm "
                     f"≤ ±{limit_mm:.1f} mm"),
        ))


# ──────────────────────────────────────────────────────────────────────
# 主入口
# ──────────────────────────────────────────────────────────────────────

def check_leveling_compliance(
    workbook: LevelingWorkbook,
    config_path: str = "config/config_leveling.json",
) -> LevelingComplianceReport:
    """
    检查水准手簿合规性.

    流程:
        1. 调用正向验证器填充计算字段
        2. 按等级选取限差参数
        3. 逐站逐项比较计算值与限差
        4. 汇总报告

    参数:
        workbook: 水准观测手簿
        config_path: 配置文件路径 (保留接口, 当前使用内置限差)

    返回:
        LevelingComplianceReport
    """
    # 先运行正向验证器, 填充所有计算字段
    validate_leveling_workbook(workbook)

    grade = workbook.grade
    limits = _LEVELING_LIMITS.get(grade, {})
    report = LevelingComplianceReport(grade=grade)

    # 正规测段 (Grade 2/3/4)
    for section in workbook.sections:
        _check_section_stations(section, grade, limits, report)
        _check_closure(section, grade, limits, report)

    # 等外测段
    for section in workbook.extra_sections:
        _check_extra_section(section, limits, report)
        _check_closure(section, grade, limits, report)

    return report
