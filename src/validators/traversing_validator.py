# src/validators/traversing_validator.py
# 导线测量正向验证器
#
# 功能: 从导线观测手簿计算方位角/坐标, 验证与输入真值精确相等.
#
# 验证内容:
# 1. 角度: 2C, 方向值, 半测回角, 测回角, 多测回均值, 方位角闭合差
# 2. 距离: 读数均值, 读数差, 斜距→平距, 往返差
# 3. 坐标: 坐标增量, 坐标传递, 坐标闭合差, 相对闭合差

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Dict
import math

from ..models.traversing import (
    DirectionReading, AngleSet, StationAngleObservation,
    DistanceReading, DistanceSet, EdgeDistanceObservation,
    TraversePointRecord, TraverseComputation, TraversingWorkbook,
)
from ..models.common import (
    TraverseGrade, InstrumentGrade, Face, AngleDefinition, TraverseInfo,
)
from .leveling_validator import CheckResult


@dataclass
class TraversingValidationResult:
    """导线测量正向验证结果"""
    checks: List[CheckResult] = field(default_factory=list)
    computed_coordinates: Dict[str, tuple] = field(default_factory=dict)
    # point_name -> (X, Y)
    computed_heights: Dict[str, float] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return all(c.passed for c in self.checks) and len(self.errors) == 0

    def add_check(self, check: CheckResult):
        self.checks.append(check)

    def add_error(self, msg: str):
        self.errors.append(msg)


# 容差
ANGLE_TOLERANCE_RAD = 1e-10  # 角度容差 (rad), 约 0.00002"
DISTANCE_TOLERANCE_M = 1e-10
COORD_TOLERANCE_M = 1e-8     # 坐标容差 (m), 考虑累积误差


def normalize_angle(angle_rad: float) -> float:
    """将角度归化到 [0, 2*pi)"""
    two_pi = 2.0 * math.pi
    result = angle_rad % two_pi
    if result < 0:
        result += two_pi
    return result


def normalize_2c(value_rad: float) -> float:
    """将 2C 归化到 (-pi, pi]"""
    two_pi = 2.0 * math.pi
    result = value_rad % two_pi
    if result > math.pi:
        result -= two_pi
    elif result <= -math.pi:
        result += two_pi
    return result


# ──────────────────────────────────────────────────────────────────────
# 角度验证: 单测回
# ──────────────────────────────────────────────────────────────────────

def validate_angle_set(angle_set: AngleSet,
                        backsight: str,
                        foresight: str,
                        result: TraversingValidationResult):
    """
    验证单测回方向观测.

    计算: 2C, 方向值, 归零方向值, 半测回角, 一测回角.
    """
    prefix = f"测回{angle_set.set_number}"

    # 按目标分组盘左/盘右读数
    readings_by_target: Dict[str, Dict[str, float]] = {}
    for dr in angle_set.directions:
        target = dr.target
        if target not in readings_by_target:
            readings_by_target[target] = {}
        readings_by_target[target][dr.face.value] = dr.reading_rad

    # 计算每个方向的 2C 和方向值
    for target, faces in readings_by_target.items():
        L = faces.get("L")
        R = faces.get("R")
        if L is not None and R is not None:
            # 2C = L - (R - pi), 归化到 (-pi, pi]  (axiom A4.3)
            two_c = normalize_2c(L - (R - math.pi))
            angle_set.two_c_values_rad[target] = two_c

            # 方向值 L_bar = (L + R - pi) / 2 - L_0  (axiom A4.4)
            direction_value = (L + R - math.pi) / 2.0 - angle_set.degree_plate_zero_rad
            direction_value = normalize_angle(direction_value)
            angle_set.direction_values_rad[target] = direction_value

    # 归零方向值 = 各方向 L_bar - 零方向 L_bar
    # 零方向: 取 backsight (或 AngleSet 中第一个方向)
    zero_dir = backsight
    zero_value = angle_set.direction_values_rad.get(zero_dir)
    if zero_value is not None:
        for target, dv in angle_set.direction_values_rad.items():
            if dv is not None:
                angle_set.zero_reduced_directions_rad[target] = normalize_angle(
                    dv - zero_value
                )

    # 半测回角值
    # 盘左: beta_L = zero_reduced[foresight] - zero_reduced[backsight]
    #      但 zero_reduced[backsight] = 0, 所以 beta_L = zero_reduced[foresight]
    # 等价: beta_L = direction_value[foresight] - direction_value[backsight]
    dv_back = angle_set.direction_values_rad.get(backsight)
    dv_fore = angle_set.direction_values_rad.get(foresight)

    if dv_back is not None and dv_fore is not None:
        # 使用方向值计算 (包含 L 和 R 的信息)
        # 盘左半测回: 仅用 L 读数
        L_back = readings_by_target.get(backsight, {}).get("L")
        L_fore = readings_by_target.get(foresight, {}).get("L")
        R_back = readings_by_target.get(backsight, {}).get("R")
        R_fore = readings_by_target.get(foresight, {}).get("R")

        if L_back is not None and L_fore is not None:
            # 盘左方向值: L_bar_L = L - L_0 (仅盘左)
            lbar_back_L = normalize_angle(L_back - angle_set.degree_plate_zero_rad)
            lbar_fore_L = normalize_angle(L_fore - angle_set.degree_plate_zero_rad)
            beta_L = normalize_angle(lbar_fore_L - lbar_back_L)
            angle_set.half_set_angle_left_rad = beta_L

        if R_back is not None and R_fore is not None:
            # 盘右方向值: L_bar_R = R - L_0 - pi (仅盘右)
            lbar_back_R = normalize_angle(R_back - angle_set.degree_plate_zero_rad - math.pi)
            lbar_fore_R = normalize_angle(R_fore - angle_set.degree_plate_zero_rad - math.pi)
            beta_R = normalize_angle(lbar_fore_R - lbar_back_R)
            angle_set.half_set_angle_right_rad = beta_R

        # 一测回角值 (axiom A4.7)
        beta_L = angle_set.half_set_angle_left_rad
        beta_R = angle_set.half_set_angle_right_rad
        if beta_L is not None and beta_R is not None:
            # 处理跨 0° 的情况: 取差值, 归化到 [0, 2pi)
            beta_set = normalize_angle((beta_L + beta_R) / 2.0)
            angle_set.set_angle_rad = beta_set

            # 半测回较差
            diff = normalize_angle(beta_L - beta_R)
            # 取绝对值, 如果 > pi 则用 2pi - diff
            if diff > math.pi:
                diff = 2 * math.pi - diff
            angle_set.half_set_diff_rad = diff

            result.add_check(CheckResult(
                name=f"{prefix}_半测回较差",
                computed=diff * 206265.0,  # 转换为角秒
                message=f"|β_L - β_R| = {diff * 206265.0:.2f}\""
            ))

        # 使用方向值计算的平均角 (验证用)
        if dv_back is not None and dv_fore is not None:
            angle_from_dv = normalize_angle(dv_fore - dv_back)


# ──────────────────────────────────────────────────────────────────────
# 角度验证: 测站
# ──────────────────────────────────────────────────────────────────────

def validate_station_angle(obs: StationAngleObservation,
                            result: TraversingValidationResult):
    """
    验证单站水平角观测 (多测回汇总).
    """
    # 逐测回验证
    for angle_set in obs.sets:
        validate_angle_set(angle_set, obs.backsight_target,
                           obs.foresight_target, result)

    # 多测回平均角
    set_angles = []
    for angle_set in obs.sets:
        if angle_set.set_angle_rad is not None:
            set_angles.append(angle_set.set_angle_rad)

    if set_angles:
        # 平均角度 (处理跨 0° 的情况: 用圆周平均)
        if len(set_angles) == 1:
            mean_angle = set_angles[0]
        else:
            # 圆周平均: 先转换为单位向量, 取平均, 再转回角度
            sum_cos = sum(math.cos(a) for a in set_angles)
            sum_sin = sum(math.sin(a) for a in set_angles)
            mean_angle = math.atan2(sum_sin, sum_cos)
            if mean_angle < 0:
                mean_angle += 2 * math.pi

        obs.observed_angle_rad = mean_angle

    # 多测回平均方向值
    all_targets = set()
    for angle_set in obs.sets:
        all_targets.update(angle_set.direction_values_rad.keys())

    for target in all_targets:
        dvs = []
        for angle_set in obs.sets:
            dv = angle_set.direction_values_rad.get(target)
            if dv is not None:
                dvs.append(dv)
        if dvs:
            # 圆周平均
            sum_cos = sum(math.cos(d) for d in dvs)
            sum_sin = sum(math.sin(d) for d in dvs)
            mean_dv = math.atan2(sum_sin, sum_cos)
            if mean_dv < 0:
                mean_dv += 2 * math.pi
            obs.mean_direction_values_rad[target] = mean_dv

    # 2C 互差 (max - min within each set)
    max_2c_diff = 0.0
    for angle_set in obs.sets:
        two_cs = [v for v in angle_set.two_c_values_rad.values() if v is not None]
        if len(two_cs) >= 2:
            diff = max(two_cs) - min(two_cs)
            max_2c_diff = max(max_2c_diff, diff)
    obs.max_2c_mutual_diff_arcsec = max_2c_diff * 206265.0


# ──────────────────────────────────────────────────────────────────────
# 方位角传递
# ──────────────────────────────────────────────────────────────────────

def propagate_azimuth(current_azimuth: float,
                       horizontal_angle: float,
                       angle_def: AngleDefinition) -> float:
    """
    方位角递推 (axiom A1.3).

    左角: alpha_next = alpha_current + beta - pi
    右角: alpha_next = alpha_current - beta + pi
    """
    if angle_def == AngleDefinition.LEFT_ANGLE:
        next_az = current_azimuth + horizontal_angle - math.pi
    else:
        next_az = current_azimuth - horizontal_angle + math.pi
    return normalize_angle(next_az)


# ──────────────────────────────────────────────────────────────────────
# 距离验证
# ──────────────────────────────────────────────────────────────────────

def validate_distance_set(dist_set: DistanceSet,
                           result: TraversingValidationResult,
                           prefix: str = ""):
    """验证单测回距离观测"""
    values = dist_set.get_readings_values()
    if len(values) >= 2:
        # 读数差
        diff_mm = (max(values) - min(values)) * 1000.0
        dist_set.reading_diff_mm = diff_mm
        result.add_check(CheckResult(
            name=f"{prefix}读数差",
            computed=diff_mm,
            message=f"max-min = {diff_mm:.1f} mm"
        ))

    if values:
        dist_set.mean_distance_m = sum(values) / len(values)


def validate_edge_distance(edge: EdgeDistanceObservation,
                            result: TraversingValidationResult):
    """验证单边距离观测"""
    prefix = f"边{edge.edge_name}_"

    # 往测
    for dist_set in edge.forward_sets:
        validate_distance_set(dist_set, result, f"{prefix}往测")

    fwd_means = [s.mean_distance_m for s in edge.forward_sets if s.mean_distance_m is not None]
    if fwd_means:
        fwd_mean = sum(fwd_means) / len(fwd_means)
        # 斜距→平距
        if edge.forward_sets and edge.forward_sets[0].is_slope_distance():
            if edge.zenith_angle_forward_rad is not None:
                fwd_mean = fwd_mean * math.sin(edge.zenith_angle_forward_rad)
        edge.forward_mean_distance_m = fwd_mean

    # 返测
    for dist_set in edge.backward_sets:
        validate_distance_set(dist_set, result, f"{prefix}返测")

    bwd_means = [s.mean_distance_m for s in edge.backward_sets if s.mean_distance_m is not None]
    if bwd_means:
        bwd_mean = sum(bwd_means) / len(bwd_means)
        if edge.backward_sets and edge.backward_sets[0].is_slope_distance():
            if edge.zenith_angle_backward_rad is not None:
                bwd_mean = bwd_mean * math.sin(edge.zenith_angle_backward_rad)
        edge.backward_mean_distance_m = bwd_mean

    # 往返较差
    if edge.forward_mean_distance_m is not None and edge.backward_mean_distance_m is not None:
        diff_mm = abs(edge.forward_mean_distance_m - edge.backward_mean_distance_m) * 1000.0
        edge.round_trip_diff_mm = diff_mm
        result.add_check(CheckResult(
            name=f"{prefix}往返较差",
            computed=diff_mm,
            message=f"|D_fwd - D_bwd| = {diff_mm:.1f} mm"
        ))

        # 最终距离
        edge.final_distance_m = (edge.forward_mean_distance_m +
                                  edge.backward_mean_distance_m) / 2.0


# ──────────────────────────────────────────────────────────────────────
# 坐标传递与闭合差
# ──────────────────────────────────────────────────────────────────────

def validate_traverse_computation(comp: TraverseComputation,
                                   result: TraversingValidationResult):
    """
    验证导线成果计算表.

    正向传递方位角和坐标, 计算闭合差.
    """
    info = comp.info
    angle_def = info.angle_definition

    # ── 方位角闭合差 ──
    # 附合导线: 从外部基准方位角开始传递
    # 闭合导线: 从首边方位角开始传递
    if info.start_reference_azimuth is not None:
        current_az = info.start_reference_azimuth
    else:
        current_az = info.start_azimuth
        if current_az is None:
            dx = comp.point_records[1].x_m - comp.point_records[0].x_m \
                if len(comp.point_records) > 1 else 0
            dy = comp.point_records[1].y_m - comp.point_records[0].y_m \
                if len(comp.point_records) > 1 else 0
            current_az = normalize_angle(math.atan2(dy, dx))

    # 递推方位角
    azimuths = [current_az]
    for edge_rec in comp.edge_records:
        if edge_rec.observed_angle_rad is not None:
            current_az = propagate_azimuth(
                current_az, edge_rec.observed_angle_rad, angle_def
            )
            azimuths.append(current_az)

    # 检查方位角闭合差
    # 附合导线: 与终止外部基准方位角比较
    # 闭合导线: 与终止边方位角比较
    target_end_az = info.end_reference_azimuth or info.end_azimuth
    if target_end_az is not None and len(azimuths) > 1:
        f_beta = azimuths[-1] - target_end_az
        f_beta = normalize_2c(f_beta)  # 归化到小值
        f_beta_arcsec = f_beta * 206265.0
        comp.azimuth_closure_error_arcsec = f_beta_arcsec
        result.add_check(CheckResult(
            name="方位角闭合差",
            computed=f_beta_arcsec,
            message=f"f_β = {f_beta_arcsec:.2f}\""
        ))

    # ── 坐标传递 ──
    # 无外部基准: azimuths[0] = 首边方位角, edge[i] 使用 azimuths[i]
    # 有外部基准: azimuths[0] = 外部基准方位角, edge[i] 使用 azimuths[i+1]
    az_offset = 1 if info.start_reference_azimuth is not None else 0
    current_x = info.start_point_x
    current_y = info.start_point_y
    result.computed_coordinates[info.start_point_name] = (current_x, current_y)

    for i, edge_rec in enumerate(comp.edge_records):
        az_idx = i + az_offset
        az = azimuths[az_idx] if az_idx < len(azimuths) else 0.0
        edge_rec.azimuth_rad = az

        if edge_rec.distance_m is not None:
            dx = edge_rec.distance_m * math.cos(az)
            dy = edge_rec.distance_m * math.sin(az)
            edge_rec.delta_x_m = dx
            edge_rec.delta_y_m = dy

            current_x += dx
            current_y += dy

            # 更新对应的点记录
            if i + 1 < len(comp.point_records):
                comp.point_records[i + 1].x_m = current_x
                comp.point_records[i + 1].y_m = current_y
                result.computed_coordinates[comp.point_records[i + 1].point_name] = (
                    current_x, current_y
                )

    # ── 坐标闭合差 ──
    fx = current_x - info.end_point_x
    fy = current_y - info.end_point_y
    fd = math.sqrt(fx * fx + fy * fy)

    comp.fx_m = fx
    comp.fy_m = fy
    comp.fd_m = fd

    total_length = sum(e.distance_m or 0.0 for e in comp.edge_records)
    comp.total_length_m = total_length

    if total_length > 0:
        comp.relative_closure = fd / total_length

    result.add_check(CheckResult(
        name="X坐标闭合差",
        computed=fx,
        message=f"f_x = {fx * 1000:.2f} mm"
    ))
    result.add_check(CheckResult(
        name="Y坐标闭合差",
        computed=fy,
        message=f"f_y = {fy * 1000:.2f} mm"
    ))
    result.add_check(CheckResult(
        name="全长闭合差",
        computed=fd,
        message=f"f_D = {fd * 1000:.2f} mm"
    ))

    if total_length > 0:
        result.add_check(CheckResult(
            name="相对闭合差",
            computed=comp.relative_closure or 0.0,
            message=f"K = 1/{int(total_length / fd) if fd > 0 else '∞'}"
        ))


# ──────────────────────────────────────────────────────────────────────
# 完整手簿验证
# ──────────────────────────────────────────────────────────────────────

def validate_traversing_workbook(workbook: TraversingWorkbook) -> TraversingValidationResult:
    """
    验证完整导线观测手簿.
    """
    result = TraversingValidationResult()

    # 角度验证
    for obs in workbook.angle_observations:
        validate_station_angle(obs, result)

    # 距离验证
    for edge in workbook.distance_observations:
        validate_edge_distance(edge, result)

    # 成果计算表验证
    if workbook.computation is not None:
        validate_traverse_computation(workbook.computation, result)

    return result
