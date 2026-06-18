# src/checkers/traversing_compliance.py
# 导线测量合规性检核
#
# 功能: 对照规范限差 (config_traversing.json) 逐项检查导线观测数据合规性.
# 前置: 需先运行正向验证器填充计算字段.
#
# 检核项:
#   1. 2C 互差 (one_set_2c_mutual_diff_arcsec)
#   2. 半测回较差 (half_set_diff_arcsec)
#   3. 方向值跨测回较差 (direction_value_diff_across_sets_arcsec)
#   4. 距离读数差 (reading_diff_mm)
#   5. 往返测较差 (round_trip_diff_mm)
#   6. 方位角闭合差 (azimuth_closure_coefficient * sqrt(n))
#   7. 全长相对闭合差 (full_length_relative_closure_denominator)

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Dict
import math

from ..models.common import TraverseGrade, InstrumentGrade, AngleObservationMethod
from ..models.traversing import TraversingWorkbook, StationAngleObservation
from ..validators.traversing_validator import (
    validate_traversing_workbook, normalize_angle,
)
from ..generators._utils import rad_to_arcsec
from ..config_loader import load_traversing_config, get_traversing_limits


# ──────────────────────────────────────────────────────────────────────
# 数据结构 (复用 leveling 的 ComplianceItem)
# ──────────────────────────────────────────────────────────────────────

from .leveling_compliance import ComplianceItem


@dataclass
class TraversingComplianceReport:
    """导线合规检核报告"""
    items: List[ComplianceItem] = field(default_factory=list)
    grade: TraverseGrade = TraverseGrade.GRADE_1
    passed: bool = True
    warnings: List[str] = field(default_factory=list)

    def add_item(self, item: ComplianceItem):
        self.items.append(item)
        if not item.passed:
            self.passed = False

    def add_warning(self, msg: str):
        self.warnings.append(msg)


# ──────────────────────────────────────────────────────────────────────
# 限差参数 (硬编码, 与 config_traversing.json 保持一致)
#
# 结构: grade → observation_method → instrument_grade → check_name → limit
#
# 观测方法分支 (GB 50026-2020):
#   方向观测法 (direction): 方向数 ≥ 3, 含归零, 限差取表 4.3.3
#   测回法 (measurement): 仅前后两方向, 无归零, 限差取表 4.3.4
# ──────────────────────────────────────────────────────────────────────

_TRAVERSING_LIMITS = {
    TraverseGrade.GRADE_1: {
        # ── 方向观测法 (direction) ──
        AngleObservationMethod.DIRECTION: {
            "2sec": {
                "2c_mutual_diff_arcsec": 13.0,
                "half_set_return_zero_diff_arcsec": 8.0,
                "direction_diff_across_sets_arcsec": 9.0,
            },
            "6sec": {
                "2c_mutual_diff_arcsec": 18.0,
                "half_set_return_zero_diff_arcsec": 12.0,
                "direction_diff_across_sets_arcsec": 12.0,
            },
            "half_set_diff_arcsec": 12.0,
            "reading_diff_mm": 10.0,
            "round_trip_diff_mm": 10.0,
            "azimuth_closure_coefficient": 10.0,
            "relative_closure_denominator": 15000,
        },
        # ── 测回法 (measurement) ──
        AngleObservationMethod.MEASUREMENT: {
            "2sec": {
                "2c_mutual_diff_arcsec": 13.0,
                "half_set_diff_arcsec": 9.0,
                "set_diff_arcsec": 10.0,
            },
            "6sec": {
                "2c_mutual_diff_arcsec": 18.0,
                "half_set_diff_arcsec": 18.0,
                "set_diff_arcsec": 24.0,
            },
            "reading_diff_mm": 10.0,
            "round_trip_diff_mm": 10.0,
            "azimuth_closure_coefficient": 10.0,
            "relative_closure_denominator": 15000,
        },
    },
    TraverseGrade.GRADE_2: {
        # ── 方向观测法 (direction) ──
        AngleObservationMethod.DIRECTION: {
            "2sec": {
                "2c_mutual_diff_arcsec": 13.0,
                "half_set_return_zero_diff_arcsec": 8.0,
                "direction_diff_across_sets_arcsec": 9.0,
            },
            "6sec": {
                "2c_mutual_diff_arcsec": 18.0,
                "half_set_return_zero_diff_arcsec": 12.0,
                "direction_diff_across_sets_arcsec": 12.0,
            },
            "half_set_diff_arcsec": 12.0,
            "reading_diff_mm": 10.0,
            "round_trip_diff_mm": 10.0,
            "azimuth_closure_coefficient": 16.0,
            "relative_closure_denominator": 10000,
        },
        # ── 测回法 (measurement) ──
        AngleObservationMethod.MEASUREMENT: {
            "2sec": {
                "2c_mutual_diff_arcsec": 13.0,
                "half_set_diff_arcsec": 9.0,
                "set_diff_arcsec": 10.0,
            },
            "6sec": {
                "2c_mutual_diff_arcsec": 18.0,
                "half_set_diff_arcsec": 18.0,
                "set_diff_arcsec": 24.0,
            },
            "reading_diff_mm": 10.0,
            "round_trip_diff_mm": 10.0,
            "azimuth_closure_coefficient": 16.0,
            "relative_closure_denominator": 10000,
        },
    },
    TraverseGrade.ROOT: {
        # ── 方向观测法 (direction) ──
        AngleObservationMethod.DIRECTION: {
            "2sec": {
                "2c_mutual_diff_arcsec": 13.0,
                "half_set_return_zero_diff_arcsec": 8.0,
                "direction_diff_across_sets_arcsec": 9.0,
            },
            "6sec": {
                "2c_mutual_diff_arcsec": 18.0,
                "half_set_return_zero_diff_arcsec": 12.0,
                "direction_diff_across_sets_arcsec": 12.0,
            },
            "half_set_diff_arcsec": 30.0,
            "reading_diff_mm": 10.0,
            "round_trip_diff_mm": 20.0,
            "azimuth_closure_coefficient": 10.0,
            "relative_closure_denominator": 2000,
        },
        # ── 测回法 (measurement) ──
        AngleObservationMethod.MEASUREMENT: {
            "2sec": {
                "2c_mutual_diff_arcsec": 13.0,
                "half_set_diff_arcsec": 24.0,
                "set_diff_arcsec": 24.0,
            },
            "6sec": {
                "2c_mutual_diff_arcsec": 18.0,
                "half_set_diff_arcsec": 36.0,
                "set_diff_arcsec": 36.0,
            },
            "reading_diff_mm": 15.0,
            "round_trip_diff_mm": 20.0,
            "azimuth_closure_coefficient": 10.0,
            "relative_closure_denominator": 2000,
        },
    },
}


def _get_instrument_key(inst_grade: InstrumentGrade) -> str:
    """仪器等级 → config key"""
    if inst_grade == InstrumentGrade.SEC_2:
        return "2sec"
    return "6sec"


# ──────────────────────────────────────────────────────────────────────
# 方向值跨测回较差 (需补充计算)
# ──────────────────────────────────────────────────────────────────────

def _compute_direction_diff_across_sets(
    obs: StationAngleObservation,
) -> Optional[float]:
    """
    计算同一方向在不同测回间的方向值较差最大值 (arcsec).

    对每个目标: 取各测回的 zero_reduced_directions_rad[target],
    使用圆周距离 (min(|a-b|, 2π-|a-b|)) 计算每对较差, 取最大值.
    """
    if len(obs.sets) < 2:
        return None

    # 收集各目标的方向值 (归零后)
    targets_directions: Dict[str, List[float]] = {}
    for aset in obs.sets:
        for target, val in aset.zero_reduced_directions_rad.items():
            if val is not None:
                if target not in targets_directions:
                    targets_directions[target] = []
                targets_directions[target].append(val)

    if not targets_directions:
        return None

    max_diff_arcsec = 0.0
    for target, vals in targets_directions.items():
        if len(vals) < 2:
            continue
        # 逐对计算圆周较差
        for i in range(len(vals)):
            for j in range(i + 1, len(vals)):
                diff = abs(vals[i] - vals[j])
                if diff > math.pi:
                    diff = 2 * math.pi - diff
                diff_arcsec = diff * 206265.0
                max_diff_arcsec = max(max_diff_arcsec, diff_arcsec)

    return max_diff_arcsec if max_diff_arcsec > 0 else None


# ──────────────────────────────────────────────────────────────────────
# 角度合规检核
# ──────────────────────────────────────────────────────────────────────

def _check_angle_observations(
    workbook: TraversingWorkbook,
    limits: dict,
    inst_key: str,
    report: TraversingComplianceReport,
):
    """检核各站角度观测.

    根据观测方法 (方向观测法 vs 测回法) 选取不同的限差:
    - 方向观测法: half_set_diff 取顶级值, direction_diff_across_sets 取仪器级值
    - 测回法: half_set_diff 取仪器级值, set_diff 取仪器级值
    """
    inst_limits = limits.get(inst_key, {})
    obs_method = workbook.angle_observation_method
    limit_2c = inst_limits.get("2c_mutual_diff_arcsec", 13.0)

    # 半测回较差限差: 测回法从仪器级取, 方向观测法从顶级取
    if obs_method == AngleObservationMethod.MEASUREMENT:
        limit_half = inst_limits.get("half_set_diff_arcsec", 12.0)
    else:
        limit_half = limits.get("half_set_diff_arcsec", 12.0)

    # 测回间较差限差: 测回法用 set_diff, 方向观测法用 direction_diff_across_sets
    if obs_method == AngleObservationMethod.MEASUREMENT:
        limit_set = inst_limits.get("set_diff_arcsec", None)
    else:
        limit_set = inst_limits.get("direction_diff_across_sets_arcsec", 9.0)

    for obs in workbook.angle_observations:
        sn = obs.station_name

        # ── 2C 互差 ──
        if obs.max_2c_mutual_diff_arcsec is not None:
            report.add_item(ComplianceItem(
                name=f"站{sn}_2C互差",
                computed=obs.max_2c_mutual_diff_arcsec,
                limit=limit_2c,
                passed=obs.max_2c_mutual_diff_arcsec <= limit_2c,
                message=(f"2C互差 = {obs.max_2c_mutual_diff_arcsec:.2f}\" "
                         f"≤ {limit_2c:.1f}\""),
                station=sn,
            ))

        # ── 半测回较差 (每测回) ──
        for aset in obs.sets:
            if aset.half_set_diff_rad is not None:
                diff_arcsec = aset.half_set_diff_rad * 206265.0
                report.add_item(ComplianceItem(
                    name=f"站{sn}_测回{aset.set_number}_半测回较差",
                    computed=diff_arcsec,
                    limit=limit_half,
                    passed=diff_arcsec <= limit_half,
                    message=(f"|β_L-β_R| = {diff_arcsec:.2f}\" "
                             f"≤ {limit_half:.1f}\""),
                    station=sn,
                ))

        # ── 测回间较差 (方向观测法: 方向值跨测回; 测回法: 角值跨测回) ──
        if obs_method == AngleObservationMethod.MEASUREMENT:
            # 测回法: 计算各测回角值间的较差
            set_angles = []
            for aset in obs.sets:
                if aset.set_angle_rad is not None:
                    set_angles.append(aset.set_angle_rad)
            if len(set_angles) >= 2 and limit_set is not None:
                max_set_diff = 0.0
                for i in range(len(set_angles)):
                    for j in range(i + 1, len(set_angles)):
                        diff = abs(set_angles[i] - set_angles[j])
                        if diff > math.pi:
                            diff = 2 * math.pi - diff
                        max_set_diff = max(max_set_diff, diff)
                max_set_diff_arcsec = max_set_diff * 206265.0
                obs.max_direction_diff_across_sets_arcsec = max_set_diff_arcsec
                report.add_item(ComplianceItem(
                    name=f"站{sn}_测回间角值较差",
                    computed=max_set_diff_arcsec,
                    limit=limit_set,
                    passed=max_set_diff_arcsec <= limit_set,
                    message=(f"max|βi-βj| = {max_set_diff_arcsec:.2f}\" "
                             f"≤ {limit_set:.1f}\""),
                    station=sn,
                ))
        else:
            # 方向观测法: 方向值跨测回较差
            dir_diff = _compute_direction_diff_across_sets(obs)
            if dir_diff is not None and limit_set is not None:
                obs.max_direction_diff_across_sets_arcsec = dir_diff
                report.add_item(ComplianceItem(
                    name=f"站{sn}_方向值跨测回较差",
                    computed=dir_diff,
                    limit=limit_set,
                    passed=dir_diff <= limit_set,
                    message=(f"max差 = {dir_diff:.2f}\" "
                             f"≤ {limit_set:.1f}\""),
                    station=sn,
                ))


# ──────────────────────────────────────────────────────────────────────
# 距离合规检核
# ──────────────────────────────────────────────────────────────────────

def _check_distance_observations(
    workbook: TraversingWorkbook,
    limits: dict,
    report: TraversingComplianceReport,
):
    """检核各边距离观测."""
    limit_rd = limits.get("reading_diff_mm", 10.0)
    limit_rt = limits.get("round_trip_diff_mm", 10.0)

    for edge in workbook.distance_observations:
        en = edge.edge_name

        # ── 距离读数差 (每测回, 往返) ──
        for label, sets in [("往测", edge.forward_sets),
                            ("返测", edge.backward_sets)]:
            for ds in sets:
                if ds.reading_diff_mm is not None:
                    report.add_item(ComplianceItem(
                        name=f"边{en}_{label}_读数差",
                        computed=ds.reading_diff_mm,
                        limit=limit_rd,
                        passed=ds.reading_diff_mm <= limit_rd,
                        message=(f"max-min = {ds.reading_diff_mm:.1f} mm "
                                 f"≤ {limit_rd:.1f} mm"),
                    ))

        # ── 往返测较差 ──
        if edge.round_trip_diff_mm is not None:
            report.add_item(ComplianceItem(
                name=f"边{en}_往返测较差",
                computed=edge.round_trip_diff_mm,
                limit=limit_rt,
                passed=edge.round_trip_diff_mm <= limit_rt,
                message=(f"|D往-D返| = {edge.round_trip_diff_mm:.1f} mm "
                         f"≤ {limit_rt:.1f} mm"),
            ))


# ──────────────────────────────────────────────────────────────────────
# 成果计算表合规检核
# ──────────────────────────────────────────────────────────────────────

def _check_computation(
    workbook: TraversingWorkbook,
    limits: dict,
    report: TraversingComplianceReport,
):
    """检核导线成果计算表 (方位角闭合差 + 相对闭合差)."""
    comp = workbook.computation
    if comp is None:
        return

    n_stations = len(workbook.angle_observations)

    # ── 方位角闭合差 ──
    az_coeff = limits.get("azimuth_closure_coefficient", 10.0)
    if n_stations > 0:
        az_limit_arcsec = az_coeff * math.sqrt(n_stations)
    else:
        az_limit_arcsec = az_coeff

    # 填充 limit 到 computation 对象
    comp.azimuth_closure_limit_arcsec = az_limit_arcsec

    if comp.azimuth_closure_error_arcsec is not None:
        abs_az_err = abs(comp.azimuth_closure_error_arcsec)
        report.add_item(ComplianceItem(
            name="方位角闭合差",
            computed=abs_az_err,
            limit=az_limit_arcsec,
            passed=abs_az_err <= az_limit_arcsec,
            message=(f"|f_β| = {abs_az_err:.2f}\" "
                     f"≤ ±{az_limit_arcsec:.1f}\""),
        ))

    # ── 全长相对闭合差 ──
    rel_denom = limits.get("relative_closure_denominator", 15000)
    rel_limit = 1.0 / rel_denom if rel_denom > 0 else 0.0

    # 填充 limit 到 computation 对象
    comp.relative_closure_limit = rel_limit

    if comp.relative_closure is not None:
        report.add_item(ComplianceItem(
            name="全长相对闭合差",
            computed=comp.relative_closure,
            limit=rel_limit,
            passed=comp.relative_closure <= rel_limit,
            message=(f"K = {comp.relative_closure:.2e} "
                     f"≤ 1/{rel_denom}"),
        ))


# ──────────────────────────────────────────────────────────────────────
# 主入口
# ──────────────────────────────────────────────────────────────────────

def check_traversing_compliance(
    workbook: TraversingWorkbook,
    config_path: str = "config/config_traversing.json",
) -> TraversingComplianceReport:
    """
    检查导线手簿合规性.

    流程:
        1. 调用正向验证器填充计算字段
        2. 按等级、观测方法和仪器等级选取限差参数
        3. 逐项比较计算值与限差
        4. 汇总报告

    参数:
        workbook: 导线观测手簿
        config_path: 配置文件路径 (None=使用默认, 默认=config/config_traversing.json)

    返回:
        TraversingComplianceReport
    """
    # 先运行正向验证器
    validate_traversing_workbook(workbook)

    grade = workbook.grade
    inst_grade = workbook.instrument_grade
    obs_method = workbook.angle_observation_method
    inst_key = _get_instrument_key(inst_grade)

    # 按等级选取限差字典
    cfg = load_traversing_config(config_path)
    if cfg:
        grade_limits = get_traversing_limits(cfg, grade)
    else:
        grade_limits = _TRAVERSING_LIMITS.get(
            grade, _TRAVERSING_LIMITS[TraverseGrade.GRADE_1])

    # 按观测方法选取限差子字典
    # 若指定方法不存在, 回退到方向观测法
    limits = grade_limits.get(obs_method, grade_limits.get(AngleObservationMethod.DIRECTION, {}))

    report = TraversingComplianceReport(grade=grade)

    # 角度检核
    _check_angle_observations(workbook, limits, inst_key, report)

    # 距离检核
    _check_distance_observations(workbook, limits, report)

    # 成果表检核
    _check_computation(workbook, limits, report)

    return report
