# src/generators/traversing_generator.py
# 导线测量逆向生成器
#
# 从 RTK 坐标真值逆向生成导线观测手簿数据.
# 核空间约束:
#   - 角度: 同一测站同一测回所有方向施加相同扰动, 水平角精确不变
#   - 距离: 斜距与天顶距耦合扰动, 平距精确不变
#
# 覆盖: 一级/二级/图根导线

from __future__ import annotations

import math
from typing import List, Optional, Tuple

import numpy as np

from ..models.common import (
    TraverseGrade, InstrumentGrade, Face, AngleDefinition, AngleObservationMethod,
    SurveyMetadata, TraverseInfo, GenerationMetadata,
    TRAVERSE_DISTANCE_DECIMAL_PLACES,
)
from ..models.traversing import (
    DirectionReading, AngleSet, StationAngleObservation,
    DistanceReading, DistanceSet, EdgeDistanceObservation,
    TraversePointRecord, TraverseComputation, TraversingWorkbook,
)
from ..validators.traversing_validator import (
    normalize_angle, normalize_2c, propagate_azimuth,
)
from ..config_loader import (
    load_traversing_config, load_observation_program_config,
    get_traversing_grade_params, get_degree_plate_offset_rad,
    get_traversing_limits,
)
from ._utils import truncated_normal, arcsec_to_rad, mm_to_m


# ──────────────────────────────────────────────────────────────────────
# 模拟参数 (从 config_traversing.json 提取)
# ──────────────────────────────────────────────────────────────────────

_ANGLE_PARAMS = {
    TraverseGrade.GRADE_1: {"sigma_arcsec": 0.5, "sigma_2c_arcsec": 3.0,
                             "sigma_set_arcsec": 2.0},
    TraverseGrade.GRADE_2: {"sigma_arcsec": 2.0, "sigma_2c_arcsec": 6.0,
                             "sigma_set_arcsec": 4.0},
    TraverseGrade.ROOT:    {"sigma_arcsec": 10.0, "sigma_2c_arcsec": 15.0,
                             "sigma_set_arcsec": 8.0},
}

_DISTANCE_PARAMS = {
    TraverseGrade.GRADE_1: {"sigma_mm": 0.5, "readings_per_set": 3,
                             "reading_diff_sigma_mm": 1.0,
                             "sigma_reading_mm": 1.2},
    TraverseGrade.GRADE_2: {"sigma_mm": 2.0, "readings_per_set": 3,
                             "reading_diff_sigma_mm": 2.0,
                             "sigma_reading_mm": 1.2},
    TraverseGrade.ROOT:    {"sigma_mm": 10.0, "readings_per_set": 3,
                             "reading_diff_sigma_mm": 5.0,
                             "sigma_reading_mm": 2.5},
}

# 度盘配置偏移 (config_observation_program.json: 150")
_DEGREE_PLATE_OFFSET_RAD = arcsec_to_rad(150.0)


# ──────────────────────────────────────────────────────────────────────
# 几何计算
# ──────────────────────────────────────────────────────────────────────

def _compute_azimuth(x1: float, y1: float, x2: float, y2: float) -> float:
    """坐标方位角: atan2(dy, dx), 归化至 [0, 2π)"""
    return normalize_angle(math.atan2(y2 - y1, x2 - x1))


def compute_azimuth(x1: float, y1: float, x2: float, y2: float) -> float:
    """
    公共 API: 计算两点间坐标方位角.

    参数:
        x1, y1: 起点 X, Y 坐标 (m)
        x2, y2: 终点 X, Y 坐标 (m)

    返回:
        方位角 (rad), 范围 [0, 2π)

    坐标系约定: X=东向(E), Y=北向(N)
    方位角 = atan2(dy, dx), 从正东逆时针
    """
    return _compute_azimuth(x1, y1, x2, y2)


def _compute_distance(x1: float, y1: float, x2: float, y2: float) -> float:
    """水平距离"""
    return math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)


# ──────────────────────────────────────────────────────────────────────
# 角度观测生成
# ──────────────────────────────────────────────────────────────────────

def _gen_station_angle(
    station_name: str,
    back_name: str, fore_name: str,
    x_station: float, y_station: float,
    x_back: float, y_back: float,
    x_fore: float, y_fore: float,
    num_sets: int,
    sigma_dir_rad: float,
    sigma_2c_rad: float,
    sigma_set_rad: float,
    angle_definition: AngleDefinition,
    rng: np.random.Generator,
    degree_plate_offset_rad: float = 0.000727,
    truncation_k: float = 3.0,
) -> StationAngleObservation:
    """
    生成单站角度观测.

    设计决策 (2026-06-18):
        后视盘左读数必须精确等于度盘零位 L0.
        原因: 实际方向观测法中, 观测员先瞄准后视目标, 再人为置盘,
        因此后视读数是主动设定的参考基准, 不应带随机扰动.
        阶段二十八曾引入 delta_dir 同加于所有方向, 导致后视读数不再
        精确归零/归 90°, 已在本阶段回退.

    核空间约束:
        后视盘左精确为 L0; 前视盘左 = L0 + lbar + delta_set + delta_2c/2.
        水平角 = 前视方向值 - 后视方向值 = lbar + delta_set (含测回间分散).

    测回间扰动 (真实性改进):
        各测回的 beta_set 施加独立微小扰动 delta_set (仅前视),
        使测回间角值存在自然分散 (sigma_set_arcsec 控制).

    2C 控制:
        各方向独立采样 delta_2C, 使 2C 互差在限差内.
    """
    az_back = _compute_azimuth(x_station, y_station, x_back, y_back)
    az_fore = _compute_azimuth(x_station, y_station, x_fore, y_fore)

    # 真值方向值 (相对于后视方向, 后视为 0)
    # 实际方向观测法: 瞄准后视设定度盘读数, 后视为起始零方向
    true_lbar = {back_name: 0.0, fore_name: normalize_angle(az_fore - az_back)}

    # 真值水平角
    true_angle = normalize_angle(az_fore - az_back)

    angle_sets = []
    for j in range(num_sets):
        # 度盘零位 (config: L_0_j = π/m * j + offset)
        # 后视盘左读数精确等于 L0 (0°, 90°, 180°, ...)
        L0 = (math.pi / num_sets) * j + degree_plate_offset_rad

        # 测回间角值扰动 (真实性改进: 各测回独立, 仅前视)
        delta_set = truncated_normal(sigma_set_rad, k=truncation_k, rng=rng)

        # 扰动后的角值: beta_set = true_angle + delta_set
        # 将 delta_set 分配到前视方向值: lbar_fore += delta_set
        # 后视方向值不变, 则 beta = lbar_fore - lbar_back = true_angle + delta_set

        directions = []
        for target in [back_name, fore_name]:
            lbar = true_lbar[target]

            # 前视方向施加测回间扰动
            target_delta_set = delta_set if target == fore_name else 0.0

            # 各方向独立 2C 扰动
            delta_2c = truncated_normal(sigma_2c_rad / 2.0, k=truncation_k, rng=rng)

            if target == back_name:
                # 后视盘左: 无扰动 (观测员瞄准后视设定度盘读数)
                L = L0
                L = normalize_angle(L)
                # 后视盘右: 仅有 2C 效应, 无方向扰动
                R = L0 - delta_2c + math.pi
                R = normalize_angle(R)
            else:
                # 前视: 正常扰动 (含 delta_set, delta_2c)
                L = L0 + lbar + target_delta_set + delta_2c / 2.0
                L = normalize_angle(L)
                R = L0 + lbar + target_delta_set - delta_2c / 2.0 + math.pi
                R = normalize_angle(R)

            directions.append(
                DirectionReading(target=target, face=Face.LEFT,
                                 reading_rad=L))
            directions.append(
                DirectionReading(target=target, face=Face.RIGHT,
                                 reading_rad=R))

        angle_sets.append(AngleSet(
            set_number=j + 1,
            degree_plate_zero_rad=L0,
            directions=directions,
        ))

    return StationAngleObservation(
        station_name=station_name,
        backsight_target=back_name,
        foresight_target=fore_name,
        zero_direction=back_name,
        sets=angle_sets,
        angle_definition=angle_definition,
    )


# ──────────────────────────────────────────────────────────────────────
# 距离观测生成
# ──────────────────────────────────────────────────────────────────────

def _gen_edge_distance(
    from_name: str, to_name: str,
    true_D: float,
    n_readings: int,
    reading_diff_sigma_m: float,
    sigma_reading_m: float,
    distance_dp: int,
    rng: np.random.Generator,
    num_sets: int = 1,
    instrument_height_m: float = 1.50,
    prism_height_m: float = 1.20,
    truncation_k: float = 3.0,
) -> EdgeDistanceObservation:
    """
    生成单边距离观测 (往返).

    天顶距设 π/2 (近水平), 斜距 ≈ 平距.

    读数分散 (真实性改进):
        各次读数施加独立扰动 delta_k ~ N(0, sigma_reading),
        使同测回内读数差 (max-min) 非零且在限差内.
        均值偏差 ~ sigma_reading / sqrt(n), 对坐标闭合差影响极小.
    """
    Z = math.pi / 2.0  # 天顶距 = 90° (水平)

    def make_set(set_num):
        readings = []
        for _ in range(n_readings):
            # 各次读数独立扰动 (真实性改进)
            delta_reading = truncated_normal(sigma_reading_m, k=truncation_k, rng=rng)
            reading = true_D + delta_reading
            readings.append(
                DistanceReading(reading_m=reading, is_slope=True)
            )
        return DistanceSet(set_number=set_num, readings=readings)

    return EdgeDistanceObservation(
        edge_name=f"{from_name}-{to_name}",
        from_point=from_name,
        to_point=to_name,
        instrument_height_m=instrument_height_m,
        prism_height_m=prism_height_m,
        zenith_angle_forward_rad=Z,
        zenith_angle_backward_rad=Z,
        forward_sets=[make_set(j + 1) for j in range(num_sets)],
        backward_sets=[make_set(j + 1) for j in range(num_sets)],
    )


# ──────────────────────────────────────────────────────────────────────
# 成果计算表
# ──────────────────────────────────────────────────────────────────────

def _build_computation(
    points: List[Tuple[str, float, float]],
    angle_obs: List[StationAngleObservation],
    distance_obs: List[EdgeDistanceObservation],
    info: TraverseInfo,
    grade: TraverseGrade,
) -> TraverseComputation:
    """
    构建导线成果计算表.

    point_records: 每个点一行 (已知点有坐标, 中间站有观测角)
    edge_records:  每条边一行 (距离 + 观测角)

    角度观测映射:
        无外部基准: angle_obs[i-1] → points[i] (中间站)
        有外部基准: angle_obs[0] = 起点站, angle_obs[1..n-1] = 中间站,
                    angle_obs[n] = 终点站
    """
    n = len(points) - 1  # 边数
    has_start_ref = info.start_reference_azimuth is not None
    has_end_ref = info.end_reference_azimuth is not None

    # 角度观测索引偏移
    # 无外部基准: angle_obs[0] = points[1]站 (第一个中间站)
    # 有外部基准: angle_obs[0] = points[0]站 (起点站), angle_obs[1] = points[1]站
    angle_offset = 1 if has_start_ref else 0

    # 点记录
    point_records = []
    for i, (name, x, y) in enumerate(points):
        is_known = (i == 0 or i == len(points) - 1)
        pr = TraversePointRecord(
            point_name=name,
            is_known=is_known,
            x_m=x if is_known else None,
            y_m=y if is_known else None,
        )
        # 中间站: 填充观测角
        if not is_known:
            idx = i - 1 + angle_offset
            if idx < len(angle_obs):
                pr.observed_angle_rad = angle_obs[idx].observed_angle_rad
        point_records.append(pr)

    # 边记录
    edge_records = []
    for i in range(n):
        er = TraversePointRecord(
            point_name=f"edge_{points[i][0]}_{points[i+1][0]}",
            distance_m=distance_obs[i].final_distance_m,
        )
        # 角度映射:
        # 无外部基准: edge[0]无角度, edge[i] → angle_obs[i-1]
        # 有外部基准: edge[0] → angle_obs[0] (起点站连接角),
        #            edge[i] → angle_obs[i] (中间站)
        if has_start_ref:
            idx = i
        else:
            idx = i - 1
        if idx >= 0 and idx < len(angle_obs):
            er.observed_angle_rad = angle_obs[idx].observed_angle_rad
        edge_records.append(er)

    # 终点站连接角: 作为额外的虚拟边记录 (无距离, 仅有角度)
    if has_end_ref:
        end_angle_idx = len(angle_obs) - 1  # 最后一个角度观测
        if end_angle_idx >= 0 and end_angle_idx < len(angle_obs):
            end_ref_name = info.end_reference_point or "REF_END"
            er_end = TraversePointRecord(
                point_name=f"edge_{points[-1][0]}_{end_ref_name}",
                distance_m=None,  # 虚拟边, 无距离
                observed_angle_rad=angle_obs[end_angle_idx].observed_angle_rad,
            )
            edge_records.append(er_end)

    # ── 正向传递方位角 ──
    angle_def = info.angle_definition

    # 起始方位角
    if has_start_ref:
        current_az = info.start_reference_azimuth
    else:
        current_az = info.start_azimuth
        if current_az is None:
            current_az = _compute_azimuth(
                points[0][1], points[0][2], points[1][1], points[1][2])

    azimuths = [current_az]
    for er in edge_records:
        if er.observed_angle_rad is not None:
            current_az = propagate_azimuth(
                current_az, er.observed_angle_rad, angle_def)
        azimuths.append(current_az)

    for i, er in enumerate(edge_records):
        az_idx = i + (1 if has_start_ref else 0)
        if az_idx < len(azimuths):
            er.azimuth_rad = azimuths[az_idx]

    # ── 正向传递坐标 ──
    # 无外部基准: azimuths[0] = 首边方位角, edge[i] 使用 azimuths[i]
    # 有外部基准: azimuths[0] = 外部基准方位角, edge[i] 使用 azimuths[i+1]
    cx, cy = info.start_point_x, info.start_point_y
    for i, er in enumerate(edge_records):
        az_idx = i + (1 if has_start_ref else 0)
        az = azimuths[az_idx] if az_idx < len(azimuths) else 0.0
        if er.distance_m is not None:
            dx = er.distance_m * math.cos(az)
            dy = er.distance_m * math.sin(az)
            er.delta_x_m = dx
            er.delta_y_m = dy
            cx += dx
            cy += dy
            if i + 1 < len(point_records):
                point_records[i + 1].x_m = cx
                point_records[i + 1].y_m = cy

    # 闭合差
    fx = cx - info.end_point_x
    fy = cy - info.end_point_y
    fd = math.sqrt(fx * fx + fy * fy)
    total_length = sum(e.distance_m or 0.0 for e in edge_records)
    rel_closure = fd / total_length if total_length > 0 and fd > 0 else 0.0

    # 方位角闭合差 (由验证器计算)
    azimuth_closure_arcsec = None

    return TraverseComputation(
        info=info,
        grade=grade,
        point_records=point_records,
        edge_records=edge_records,
        fx_m=fx, fy_m=fy, fd_m=fd,
        total_length_m=total_length,
        relative_closure=rel_closure,
        azimuth_closure_error_arcsec=azimuth_closure_arcsec,
    )


# ──────────────────────────────────────────────────────────────────────
# 闭合差可控非零化
# ──────────────────────────────────────────────────────────────────────

def _recompute_edge_distance(edge: EdgeDistanceObservation) -> None:
    """根据读数重新计算边的平距均值、往返较差和 final_distance."""
    fwd_vals = [r.reading_m for s in edge.forward_sets for r in s.readings]
    bwd_vals = [r.reading_m for s in edge.backward_sets for r in s.readings]
    fwd_mean = sum(fwd_vals) / len(fwd_vals) if fwd_vals else 0.0
    bwd_mean = sum(bwd_vals) / len(bwd_vals) if bwd_vals else 0.0
    edge.forward_mean_distance_m = fwd_mean
    edge.backward_mean_distance_m = bwd_mean
    edge.round_trip_diff_mm = abs(fwd_mean - bwd_mean) * 1000.0
    edge.final_distance_m = (fwd_mean + bwd_mean) / 2.0


def _apply_controlled_closure(
    distance_obs: list,
    points: List[Tuple[str, float, float]],
    grade: TraverseGrade,
    target_ratio: float,
    rng: np.random.Generator,
    distance_dp: int,
    rel_limit: float,
    truncation_k: float = 3.0,
    closure_azimuth_rad: Optional[float] = None,
) -> None:
    """
    对每条边施加整体距离偏移, 使坐标闭合差达到目标值.

    策略:
        目标全长闭合差 f_d = target_ratio × K_rel × total_length

    当 closure_azimuth_rad 为 None 时 (旧行为):
        各边施加扰动 delta_D_i ~ N(0, sigma_D), 仅控制 f_d 大小,
        方向由随机性决定.

    当 closure_azimuth_rad 指定时 (新行为):
        同时控制 f_x 和 f_y, 使闭合差向量方向等于 closure_azimuth_rad.
        使用最小范数最小二乘将目标 f_x/f_y 分配到各边距离偏移.
    """
    if rel_limit <= 0.0:
        return

    total_length = sum(
        _compute_distance(points[i][1], points[i][2],
                          points[i + 1][1], points[i + 1][2])
        for i in range(len(points) - 1)
    )
    if total_length < 1e-6:
        return

    target_fd = rel_limit * total_length * target_ratio
    if target_fd < 1e-9:
        return

    n = len(distance_obs)

    if closure_azimuth_rad is None:
        # 旧行为: 随机扰动, 仅控制 f_d 大小
        sigma_D_m = target_fd / max(1.0, math.sqrt(n))
        for edge in distance_obs:
            delta_D_m = truncated_normal(sigma_D_m, k=truncation_k, rng=rng)
            for ds in edge.forward_sets + edge.backward_sets:
                for r in ds.readings:
                    r.reading_m = r.reading_m + delta_D_m
    else:
        # 新行为: 同时控制 f_x 和 f_y
        target_fx = target_fd * math.cos(closure_azimuth_rad)
        target_fy = target_fd * math.sin(closure_azimuth_rad)

        azimuths = [
            _compute_azimuth(points[i][1], points[i][2],
                             points[i + 1][1], points[i + 1][2])
            for i in range(n)
        ]
        cos_a = np.array([math.cos(az) for az in azimuths])
        sin_a = np.array([math.sin(az) for az in azimuths])
        A = np.vstack([cos_a, sin_a])
        b = np.array([target_fx, target_fy])

        AAT = A @ A.T
        det = float(AAT[0, 0] * AAT[1, 1] - AAT[0, 1] * AAT[1, 0])
        if abs(det) < 1e-12:
            return
        inv_AAT = np.linalg.inv(AAT)
        delta_base = A.T @ inv_AAT @ b  # 长度 n

        for i, edge in enumerate(distance_obs):
            delta_D_m = float(delta_base[i])
            for ds in edge.forward_sets + edge.backward_sets:
                for r in ds.readings:
                    r.reading_m = r.reading_m + delta_D_m

    # 重新计算各边平距统计量 (供成果计算表使用)
    for edge in distance_obs:
        _recompute_edge_distance(edge)


# ──────────────────────────────────────────────────────────────────────
# 主入口
# ──────────────────────────────────────────────────────────────────────

def generate_traversing_workbook(
    points: List[Tuple[str, float, float]],
    start_azimuth: float,
    end_azimuth: float,
    grade: TraverseGrade,
    instrument_grade: InstrumentGrade = InstrumentGrade.SEC_2,
    num_angle_sets: int = 2,
    angle_definition: AngleDefinition = AngleDefinition.LEFT_ANGLE,
    angle_observation_method: AngleObservationMethod = AngleObservationMethod.DIRECTION,
    num_distance_sets: int = 2,
    instrument_heights: Optional[dict] = None,
    prism_heights: Optional[dict] = None,
    default_instrument_height_m: float = 1.50,
    default_prism_height_m: float = 1.20,
    metadata: Optional[SurveyMetadata] = None,
    seed: Optional[int] = None,
    target_closure_ratio: float = 0.0,
    closure_azimuth_rad: Optional[float] = None,
    start_reference_point: Optional[Tuple[str, float, float]] = None,
    end_reference_point: Optional[Tuple[str, float, float]] = None,
    config_path: Optional[str] = None,
    truncation_k: float = 3.0,
) -> TraversingWorkbook:
    """
    从 RTK 坐标真值逆向生成导线观测手簿.

    参数:
        points: [(name, x, y), ...] 导线点序列 (首尾为已知点)
        start_azimuth: 起始方位角 (rad)
        end_azimuth: 终止方位角 (rad)
        grade: 目标等级
        instrument_grade: 仪器等级 (2"/6")
        num_angle_sets: 测回数
        angle_definition: 左角/右角
        metadata: 表头元数据
        seed: 随机种子
        target_closure_ratio: 目标闭合差/限差比值 (0-1, 默认0=精确零)
        closure_azimuth_rad: 目标闭合差方位角 (rad, None=方向随机)
        start_reference_point: 起始外部基准点 (name, x, y), 如 ("B2", 9800, 5000)
        end_reference_point: 终止外部基准点 (name, x, y), 如 ("G2", 11200, 7500)
        config_path: 导线配置文件路径 (None=使用默认 config/config_traversing.json)
        truncation_k: 截断系数 (默认 3.0)

    返回:
        TraversingWorkbook (可通过 validate_traversing_workbook 验证)

    数学保证:
        - 核空间角度约束: 同站同测回所有方向施加相同 delta_dir,
          水平角 = direction_value[fore] - direction_value[back] 精确不变
        - 坐标闭合: 距离均值施加受控扰动, 使闭合差达到 target_closure_ratio × limit
    """
    rng = np.random.default_rng(seed)

    # 从配置文件加载参数 (失败时回退到内置 _ANGLE_PARAMS / _DISTANCE_PARAMS)
    trav_cfg = load_traversing_config(config_path)
    prog_cfg = load_observation_program_config(None)
    if trav_cfg:
        ap, dp = get_traversing_grade_params(trav_cfg, grade)
        limits = get_traversing_limits(trav_cfg, grade)
        rel_denom = limits[AngleObservationMethod.DIRECTION].get(
            "relative_closure_denominator", 15000)
        rel_limit = 1.0 / rel_denom if rel_denom > 0 else 0.0
    else:
        ap = _ANGLE_PARAMS[grade]
        dp = _DISTANCE_PARAMS[grade]
        rel_limits = {
            TraverseGrade.GRADE_1: 1.0 / 15000,
            TraverseGrade.GRADE_2: 1.0 / 10000,
            TraverseGrade.ROOT: 1.0 / 4000,
        }
        rel_limit = rel_limits.get(grade, 1.0 / 15000)

    # 截断系数: 配置优先
    truncation_k = prog_cfg.get("default_simulation_parameters", {}).get(
        "truncation_k", truncation_k)

    sigma_dir_rad = arcsec_to_rad(ap["sigma_arcsec"])
    sigma_2c_rad = arcsec_to_rad(ap["sigma_2c_arcsec"])
    sigma_set_rad = arcsec_to_rad(ap["sigma_set_arcsec"])
    reading_diff_sigma_m = mm_to_m(dp["reading_diff_sigma_mm"])
    distance_dp = TRAVERSE_DISTANCE_DECIMAL_PLACES
    degree_plate_offset_rad = get_degree_plate_offset_rad(prog_cfg)

    n = len(points) - 1  # 边数

    if metadata is None:
        metadata = SurveyMetadata(
            date="2025-06-01", observer="模拟观测",
            recorder="模拟记录",
            instrument_model="Leica TS16",
            instrument_serial="SIM-001",
        )

    # TraverseInfo
    # 计算外部基准方位角
    start_ref_az = None
    end_ref_az = None
    start_ref_name = None
    end_ref_name = None
    if start_reference_point is not None:
        start_ref_az = _compute_azimuth(
            start_reference_point[1], start_reference_point[2],
            points[0][1], points[0][2],
        )
        start_ref_name = start_reference_point[0]
    if end_reference_point is not None:
        end_ref_az = _compute_azimuth(
            points[-1][1], points[-1][2],
            end_reference_point[1], end_reference_point[2],
        )
        end_ref_name = end_reference_point[0]

    info = TraverseInfo(
        name="模拟导线",
        start_point_name=points[0][0],
        start_point_x=points[0][1],
        start_point_y=points[0][2],
        end_point_name=points[-1][0],
        end_point_x=points[-1][1],
        end_point_y=points[-1][2],
        start_azimuth=start_azimuth,
        end_azimuth=end_azimuth,
        angle_definition=angle_definition,
        start_reference_azimuth=start_ref_az,
        end_reference_azimuth=end_ref_az,
        start_reference_point=start_ref_name,
        end_reference_point=end_ref_name,
    )

    # ── 角度观测 (中间站) ──
    angle_obs = []
    for i in range(1, len(points) - 1):
        name, x, y = points[i]
        back_name, xb, yb = points[i - 1]
        fore_name, xf, yf = points[i + 1]

        obs = _gen_station_angle(
            station_name=name,
            back_name=back_name, fore_name=fore_name,
            x_station=x, y_station=y,
            x_back=xb, y_back=yb,
            x_fore=xf, y_fore=yf,
            num_sets=num_angle_sets,
            sigma_dir_rad=sigma_dir_rad,
            sigma_2c_rad=sigma_2c_rad,
            sigma_set_rad=sigma_set_rad,
            angle_definition=angle_definition,
            rng=rng,
            degree_plate_offset_rad=degree_plate_offset_rad,
            truncation_k=truncation_k,
        )
        angle_obs.append(obs)

    # ── 端点连接角观测 (附合导线) ──
    # 起点站: 后视=外部基准点, 前视=第二点
    if start_reference_point is not None:
        ref_name, ref_x, ref_y = start_reference_point
        name, x, y = points[0]
        fore_name, xf, yf = points[1]
        obs_start = _gen_station_angle(
            station_name=name,
            back_name=ref_name, fore_name=fore_name,
            x_station=x, y_station=y,
            x_back=ref_x, y_back=ref_y,
            x_fore=xf, y_fore=yf,
            num_sets=num_angle_sets,
            sigma_dir_rad=sigma_dir_rad,
            sigma_2c_rad=sigma_2c_rad,
            sigma_set_rad=sigma_set_rad,
            angle_definition=angle_definition,
            rng=rng,
            degree_plate_offset_rad=degree_plate_offset_rad,
            truncation_k=truncation_k,
        )
        angle_obs.insert(0, obs_start)

    # 终点站: 后视=倒数第二点, 前视=外部基准点
    if end_reference_point is not None:
        ref_name, ref_x, ref_y = end_reference_point
        name, x, y = points[-1]
        back_name, xb, yb = points[-2]
        obs_end = _gen_station_angle(
            station_name=name,
            back_name=back_name, fore_name=ref_name,
            x_station=x, y_station=y,
            x_back=xb, y_back=yb,
            x_fore=ref_x, y_fore=ref_y,
            num_sets=num_angle_sets,
            sigma_dir_rad=sigma_dir_rad,
            sigma_2c_rad=sigma_2c_rad,
            sigma_set_rad=sigma_set_rad,
            angle_definition=angle_definition,
            rng=rng,
            degree_plate_offset_rad=degree_plate_offset_rad,
            truncation_k=truncation_k,
        )
        angle_obs.append(obs_end)

    # 预计算各站观测角 (供成果表使用)
    # 需要先用 validator 的逻辑计算, 这里直接解析
    for obs in angle_obs:
        set_angles = []
        for aset in obs.sets:
            # 从 L/R 读数计算半测回角
            readings_map = {}
            for dr in aset.directions:
                key = (dr.target, dr.face.value)
                readings_map[key] = dr.reading_rad

            L_back = readings_map.get((obs.backsight_target, "L"))
            L_fore = readings_map.get((obs.foresight_target, "L"))
            R_back = readings_map.get((obs.backsight_target, "R"))
            R_fore = readings_map.get((obs.foresight_target, "R"))

            if L_back is not None and L_fore is not None:
                lbar_bk = normalize_angle(L_back - aset.degree_plate_zero_rad)
                lbar_fr = normalize_angle(L_fore - aset.degree_plate_zero_rad)
                beta_L = normalize_angle(lbar_fr - lbar_bk)
            else:
                beta_L = None

            if R_back is not None and R_fore is not None:
                lbar_bk_r = normalize_angle(
                    R_back - aset.degree_plate_zero_rad - math.pi)
                lbar_fr_r = normalize_angle(
                    R_fore - aset.degree_plate_zero_rad - math.pi)
                beta_R = normalize_angle(lbar_fr_r - lbar_bk_r)
            else:
                beta_R = None

            if beta_L is not None and beta_R is not None:
                beta_set = normalize_angle((beta_L + beta_R) / 2.0)
                set_angles.append(beta_set)

        if set_angles:
            if len(set_angles) == 1:
                obs.observed_angle_rad = set_angles[0]
            else:
                sum_cos = sum(math.cos(a) for a in set_angles)
                sum_sin = sum(math.sin(a) for a in set_angles)
                mean = math.atan2(sum_sin, sum_cos)
                if mean < 0:
                    mean += 2 * math.pi
                obs.observed_angle_rad = mean

    # ── 距离观测 (各边) ──
    distance_obs = []
    for i in range(n):
        _, x1, y1 = points[i]
        _, x2, y2 = points[i + 1]
        D = _compute_distance(x1, y1, x2, y2)

        # 获取该边的仪器高/棱镜高
        from_pt = points[i][0]
        i_h = (instrument_heights or {}).get(from_pt, default_instrument_height_m)
        p_h = (prism_heights or {}).get(from_pt, default_prism_height_m)

        edge = _gen_edge_distance(
            from_name=points[i][0], to_name=points[i + 1][0],
            true_D=D,
            n_readings=dp["readings_per_set"],
            reading_diff_sigma_m=reading_diff_sigma_m,
            sigma_reading_m=mm_to_m(dp["sigma_reading_mm"]),
            distance_dp=distance_dp,
            rng=rng,
            num_sets=num_distance_sets,
            instrument_height_m=i_h,
            prism_height_m=p_h,
            truncation_k=truncation_k,
        )

        # 填充 final_distance (validator 会重新计算, 但我们需要用于 computation)
        fwd_vals = [r.reading_m for s in edge.forward_sets for r in s.readings]
        bwd_vals = [r.reading_m for s in edge.backward_sets for r in s.readings]
        fwd_mean = sum(fwd_vals) / len(fwd_vals) if fwd_vals else D
        bwd_mean = sum(bwd_vals) / len(bwd_vals) if bwd_vals else D
        # sin(π/2) = 1, 所以水平距 = 斜距均值
        edge.forward_mean_distance_m = fwd_mean
        edge.backward_mean_distance_m = bwd_mean
        edge.round_trip_diff_mm = abs(fwd_mean - bwd_mean) * 1000.0
        edge.final_distance_m = (fwd_mean + bwd_mean) / 2.0

        distance_obs.append(edge)

    # ── 闭合差可控非零化 ──
    if target_closure_ratio > 0:
        _apply_controlled_closure(
            distance_obs, points, grade, target_closure_ratio, rng,
            distance_dp, rel_limit,
            truncation_k=truncation_k,
            closure_azimuth_rad=closure_azimuth_rad,
        )

    # ── 成果计算表 ──
    computation = _build_computation(
        points, angle_obs, distance_obs, info, grade)

    # ── 简易平差（二次解算，基于正向传播结果） ──
    from ..adjustment import adjust_traverse
    adjust_traverse(computation)

    return TraversingWorkbook(
        grade=grade,
        instrument_grade=instrument_grade,
        angle_observation_method=angle_observation_method,
        metadata=metadata,
        info=info,
        angle_observations=angle_obs,
        distance_observations=distance_obs,
        computation=computation,
        generation_metadata=GenerationMetadata(
            target_grade=grade.value,
            random_seed=seed,
            truncation_k=truncation_k,
            # 后视读数精确为 L0, 不再使用 sigma_dir/delta_dir 方向扰动
            angle_sigma_arcsec=None,
            angle_set_sigma_arcsec=ap["sigma_set_arcsec"],
            distance_sigma_mm=dp["sigma_mm"],
            distance_reading_sigma_mm=dp["sigma_reading_mm"],
        ),
    )
