# src/generators/leveling_generator.py
# 水准测量逆向生成器
#
# 从 RTK 高程真值逆向生成水准观测手簿数据.
# 核空间约束: 后视前视读数施加同向等量扰动, 高差精确不变.
#
# 覆盖: 二等 (因瓦基辅), 三等/四等 (双面尺), 等外 (变动仪高法)
#
# 数学框架:
#   正向: h = a - b (高差 = 后视 - 前视)
#   逆向: 给定 h, 选择 H_sight, 分解 a = H_sight - H_back, b = a - h
#   扰动: delta ~ truncated_normal(sigma), a' = a + delta, b' = b + delta
#   断言: a' - b' == a - b (核空间约束, 不可关闭)

from __future__ import annotations

import math
from typing import List, Optional, Tuple

import numpy as np

from ..models.common import (
    LevelingGrade, RodType, SurveyMetadata, RouteInfo, GenerationMetadata,
    LEVELING_READING_DECIMAL_PLACES,
)
from ..models.leveling import (
    RodSpec, LevelingReading, LevelingStation,
    ExtraLevelingStation, LevelingSection, ExtraLevelingSection,
    LevelingWorkbook, ObservationSequence,
)
from ._utils import truncated_normal, mm_to_m, round_reading


# ──────────────────────────────────────────────────────────────────────
# 默认参数 (从 config_leveling.json 提取)
# ──────────────────────────────────────────────────────────────────────

# 默认尺型
DEFAULT_ROD_SPECS = {
    LevelingGrade.GRADE_2: (
        RodSpec("No.1", RodType.INVAR_BASIC_AUX, c_aux_m=3.0155),
        RodSpec("No.2", RodType.INVAR_BASIC_AUX, c_aux_m=3.0155),
    ),
    LevelingGrade.GRADE_3: (
        RodSpec("K1", RodType.DOUBLE_FACE, k_value_m=4.687),
        RodSpec("K2", RodType.DOUBLE_FACE, k_value_m=4.787),
    ),
    LevelingGrade.GRADE_4: (
        RodSpec("K1", RodType.DOUBLE_FACE, k_value_m=4.687),
        RodSpec("K2", RodType.DOUBLE_FACE, k_value_m=4.787),
    ),
    LevelingGrade.EXTRA: (
        RodSpec("R1", RodType.SINGLE_FACE),
        RodSpec("R1", RodType.SINGLE_FACE),
    ),
}

# 模拟参数 (sigma, 视距范围, 读数精度)
_GRADE_PARAMS = {
    LevelingGrade.GRADE_2: {
        "sigma_mm": 0.05,
        "sight_dist_range": (20.0, 50.0),
        "dist_diff_max": 0.8,
        "reading_dp": 4,
        "buffer": (1.5, 2.5),
        "reading_range": (0.3, 2.5),
    },
    LevelingGrade.GRADE_3: {
        "sigma_mm": 0.5,
        "sight_dist_range": (20.0, 75.0),
        "dist_diff_max": 3.0,
        "reading_dp": 3,
        "buffer": (1.5, 2.5),
        "reading_range": (0.3, 2.5),
    },
    LevelingGrade.GRADE_4: {
        "sigma_mm": 1.0,
        "sight_dist_range": (20.0, 100.0),
        "dist_diff_max": 3.0,
        "reading_dp": 3,
        "buffer": (1.5, 2.5),
        "reading_range": (0.3, 2.5),
    },
    LevelingGrade.EXTRA: {
        "sigma_mm": 2.0,
        "reading_dp": 3,
        "reading_range": (0.3, 2.5),
    },
}


# 往返测高差不符值限差系数 (C × √L mm, L 单位 km)
_ROUND_TRIP_LIMIT_COEFF = {
    LevelingGrade.GRADE_2: 4.0,
    LevelingGrade.GRADE_3: 12.0,
    LevelingGrade.GRADE_4: 20.0,
    LevelingGrade.EXTRA: 40.0,
}


# ──────────────────────────────────────────────────────────────────────
# 高差分配 (总和精确等于 dh_total)
# ──────────────────────────────────────────────────────────────────────

def _distribute_height_diffs(
    dh_total: float, n: int, rng: np.random.Generator
) -> List[float]:
    """
    将总高差分配到各站, 保证 sum = dh_total.

    方法: 均分 + 零和随机偏差 (最后一站吸收余量).
    """
    if n == 1:
        return [dh_total]

    dh_base = dh_total / n
    epsilons = rng.uniform(-0.05, 0.05, size=n - 1)
    # 使 epsilons 零和: 减去均值
    epsilons -= epsilons.mean()
    last_eps = -epsilons.sum()  # 精确使总和为零

    diffs = [dh_base + float(e) for e in epsilons]
    diffs.append(dh_base + last_eps)
    return diffs


# ──────────────────────────────────────────────────────────────────────
# 单站生成: 双面尺 (三四等)
# ──────────────────────────────────────────────────────────────────────

def _gen_double_face_station(
    station_num: int, back_name: str, fore_name: str,
    dh: float, h_back: float, h_fore: float,
    sigma_m: float, reading_dp: int,
    params: dict, rng: np.random.Generator,
    k_back: float, k_fore: float,
) -> dict:
    """
    生成双面尺测站数据 (返回字段字典).

    核空间约束: delta 同时加到 a_black, a_red, b_black, b_red.
    断言: (a' - b') == dh (精确, 浮点误差 < 1e-12)
    """
    buf_lo, buf_hi = params["buffer"]
    r_lo, r_hi = params["reading_range"]
    sd_lo, sd_hi = params["sight_dist_range"]
    dd_max = params["dist_diff_max"]

    # 1. 视线高
    sight_height = max(h_back, h_fore) + rng.uniform(buf_lo, buf_hi)

    # 2. 分解高差为精确读数
    a_black = sight_height - h_back
    b_black = a_black - dh
    a_red = k_back + a_black
    b_red = k_fore + b_black

    # 3. 核空间扰动 (同一个 delta 加到所有中丝读数)
    delta = truncated_normal(sigma_m, rng=rng)

    a_black_p = a_black + delta
    a_red_p = a_red + delta
    b_black_p = b_black + delta
    b_red_p = b_red + delta

    # 核空间断言 (不可关闭)
    assert abs((a_black_p - b_black_p) - dh) < 1e-12, \
        f"核空间约束违反: 站{station_num}"

    # 4. 取整到等级精度
    a_black_r = round_reading(a_black_p, reading_dp)
    a_red_r = round_reading(a_red_p, reading_dp)
    b_black_r = round_reading(b_black_p, reading_dp)
    b_red_r = round_reading(b_red_p, reading_dp)

    # 5. 视距 (上下丝)
    s_back = rng.uniform(sd_lo, sd_hi)
    s_fore = rng.uniform(
        max(sd_lo, s_back - dd_max),
        min(sd_hi, s_back + dd_max)
    )
    half_back = s_back / 200.0
    half_fore = s_fore / 200.0

    return {
        "station_number": station_num,
        "backsight_point": back_name,
        "foresight_point": fore_name,
        "backsight": LevelingReading(
            black_mid_m=a_black_r,
            red_mid_m=a_red_r,
            upper_wire_m=round(a_black_r + half_back, reading_dp),
            lower_wire_m=round(a_black_r - half_back, reading_dp),
        ),
        "foresight": LevelingReading(
            black_mid_m=b_black_r,
            red_mid_m=b_red_r,
            upper_wire_m=round(b_black_r + half_fore, reading_dp),
            lower_wire_m=round(b_black_r - half_fore, reading_dp),
        ),
        "sight_height_m": sight_height,
        "_h_exact": dh,  # 暂存, 用于闭合差校正
    }


# ──────────────────────────────────────────────────────────────────────
# 单站生成: 因瓦基辅 (二等)
# ──────────────────────────────────────────────────────────────────────

def _gen_invar_station(
    station_num: int, back_name: str, fore_name: str,
    dh: float, h_back: float, h_fore: float,
    sigma_m: float, reading_dp: int,
    params: dict, rng: np.random.Generator,
    c_aux: float,
) -> dict:
    """
    生成因瓦基辅分划测站数据.

    核空间约束: delta 同时加到 basic, aux (后视+前视).
    """
    buf_lo, buf_hi = params["buffer"]
    sd_lo, sd_hi = params["sight_dist_range"]
    dd_max = params["dist_diff_max"]

    sight_height = max(h_back, h_fore) + rng.uniform(buf_lo, buf_hi)

    a_basic = sight_height - h_back
    b_basic = a_basic - dh
    a_aux = a_basic + c_aux
    b_aux = b_basic + c_aux

    delta = truncated_normal(sigma_m, rng=rng)

    a_basic_p = a_basic + delta
    a_aux_p = a_aux + delta
    b_basic_p = b_basic + delta
    b_aux_p = b_aux + delta

    assert abs((a_basic_p - b_basic_p) - dh) < 1e-12, \
        f"核空间约束违反: 站{station_num}"

    a_basic_r = round_reading(a_basic_p, reading_dp)
    a_aux_r = round_reading(a_aux_p, reading_dp)
    b_basic_r = round_reading(b_basic_p, reading_dp)
    b_aux_r = round_reading(b_aux_p, reading_dp)

    s_back = rng.uniform(sd_lo, sd_hi)
    s_fore = rng.uniform(
        max(sd_lo, s_back - dd_max),
        min(sd_hi, s_back + dd_max)
    )
    half_back = s_back / 200.0
    half_fore = s_fore / 200.0

    return {
        "station_number": station_num,
        "backsight_point": back_name,
        "foresight_point": fore_name,
        "backsight": LevelingReading(
            black_mid_m=a_basic_r,
            aux_mid_m=a_aux_r,
            upper_wire_m=round(a_basic_r + half_back, reading_dp),
            lower_wire_m=round(a_basic_r - half_back, reading_dp),
        ),
        "foresight": LevelingReading(
            black_mid_m=b_basic_r,
            aux_mid_m=b_aux_r,
            upper_wire_m=round(b_basic_r + half_fore, reading_dp),
            lower_wire_m=round(b_basic_r - half_fore, reading_dp),
        ),
        "sight_height_m": sight_height,
        "_h_exact": dh,
    }


# ──────────────────────────────────────────────────────────────────────
# 单站生成: 等外 (变动仪高法)
# ──────────────────────────────────────────────────────────────────────

def _gen_extra_station(
    station_num: int, back_name: str, fore_name: str,
    dh: float, h_back: float, h_fore: float,
    sigma_m: float, reading_dp: int,
    rng: np.random.Generator,
) -> dict:
    """
    生成等外水准测站 (变动仪高法).

    两次仪高, 相差 >= 10 cm.
    核空间约束: 每对读数施加同向等量扰动.
    """
    # 第一次仪高
    a1_exact = rng.uniform(0.8, 2.0)
    b1_exact = a1_exact - dh

    # 第二次仪高 (变动 >= 10 cm, 取 15-25 cm)
    shift = rng.uniform(0.15, 0.25)
    a2_exact = a1_exact + shift
    b2_exact = a2_exact - dh

    # 核空间扰动 (每对独立采样, 但同对内 delta 相同)
    delta1 = truncated_normal(sigma_m, rng=rng)
    delta2 = truncated_normal(sigma_m, rng=rng)

    return {
        "station_number": station_num,
        "backsight_point": back_name,
        "foresight_point": fore_name,
        "backsight_1_m": round_reading(a1_exact + delta1, reading_dp),
        "foresight_1_m": round_reading(b1_exact + delta1, reading_dp),
        "backsight_2_m": round_reading(a2_exact + delta2, reading_dp),
        "foresight_2_m": round_reading(b2_exact + delta2, reading_dp),
        "_h_exact": dh,
    }


# ──────────────────────────────────────────────────────────────────────
# 闭合差校正
# ──────────────────────────────────────────────────────────────────────

def _apply_closure_correction_double_face(
    last_station_data: dict, closure: float, reading_dp: int
):
    """
    校正最后一站的前视读数, 使路线闭合差精确为零.

    对双面尺: 前视黑面和红面同时加 closure.
    核空间约束保持 (黑红面同量偏移), K+黑-红 不变.
    """
    fs = last_station_data["foresight"]
    fs.black_mid_m = round_reading(fs.black_mid_m + closure, reading_dp)
    fs.red_mid_m = round_reading(fs.red_mid_m + closure, reading_dp)


def _apply_closure_correction_invar(
    last_station_data: dict, closure: float, reading_dp: int
):
    """
    校正最后一站前视 (因瓦基辅): basic 和 aux 同时加 closure.
    """
    fs = last_station_data["foresight"]
    fs.black_mid_m = round_reading(fs.black_mid_m + closure, reading_dp)
    fs.aux_mid_m = round_reading(fs.aux_mid_m + closure, reading_dp)


def _apply_closure_correction_extra(
    last_station_data: dict, closure: float, reading_dp: int
):
    """
    校正最后一站 (等外): 两次仪高的前视同时加 closure.

    h1_mean 和 h2_mean 各自减少 closure,
    height_diff_mean = (h1+h2)/2 减少 closure → 闭合差归零.
    """
    last_station_data["foresight_1_m"] = round_reading(
        last_station_data["foresight_1_m"] + closure, reading_dp)
    last_station_data["foresight_2_m"] = round_reading(
        last_station_data["foresight_2_m"] + closure, reading_dp)


def _apply_target_residual(
    last_station_data: dict,
    route: RouteInfo,
    grade: LevelingGrade,
    target_ratio: float,
    reading_dp: int,
    rng: np.random.Generator,
    is_extra: bool = False,
    rod: Optional[RodSpec] = None,
):
    """
    在闭合差归零后, 对末站前视施加受控残差, 使闭合差达到目标值.

    目标闭合差 = target_ratio × 限差 × 随机符号
    限差: 三等 12√L mm, 四等 20√L mm, 等外 40√L mm, 二等 4√L mm
    """
    L_km = route.total_length_km
    if L_km < 0.001:
        L_km = 0.001  # 防止除零

    # 各等级限差公式 (mm)
    limit_mm = {
        LevelingGrade.GRADE_2: 4.0 * math.sqrt(L_km),
        LevelingGrade.GRADE_3: 12.0 * math.sqrt(L_km),
        LevelingGrade.GRADE_4: 20.0 * math.sqrt(L_km),
        LevelingGrade.EXTRA:   40.0 * math.sqrt(L_km),
    }.get(grade, 12.0 * math.sqrt(L_km))

    # 目标闭合差 (m), 随机符号
    target_closure_m = target_ratio * limit_mm / 1000.0
    sign = rng.choice([-1.0, 1.0])
    residual_m = target_closure_m * sign

    # 施加到末站前视: 前视加 residual → 高差减少 residual → 闭合差 = residual
    if is_extra:
        last_station_data["foresight_1_m"] = round_reading(
            last_station_data["foresight_1_m"] + residual_m, reading_dp)
        last_station_data["foresight_2_m"] = round_reading(
            last_station_data["foresight_2_m"] + residual_m, reading_dp)
    else:
        fs = last_station_data["foresight"]
        fs.black_mid_m = round_reading(fs.black_mid_m + residual_m, reading_dp)
        if rod and rod.rod_type == RodType.INVAR_BASIC_AUX:
            fs.aux_mid_m = round_reading(fs.aux_mid_m + residual_m, reading_dp)
        else:
            fs.red_mid_m = round_reading(fs.red_mid_m + residual_m, reading_dp)


def _compute_section_sum_h(section: LevelingSection) -> float:
    """从测站黑面读数计算高差总和 (m)."""
    total = 0.0
    for s in section.stations:
        if s.backsight.black_mid_m is not None and s.foresight.black_mid_m is not None:
            total += s.backsight.black_mid_m - s.foresight.black_mid_m
    return total


def _apply_round_trip_residual(
    return_section: LevelingSection,
    residual_m: float,
    reading_dp: int,
):
    """
    对返测末站前视施加往返测残差.

    黑面/红面(或基辅)同步偏移, 保持 K+黑-红 / 基辅读数差不变.
    残差加到前视 → 高差减少 residual → 往返不符值 = |residual|
    """
    last_station = return_section.stations[-1]
    fs = last_station.foresight

    if fs.black_mid_m is not None:
        fs.black_mid_m = round_reading(fs.black_mid_m + residual_m, reading_dp)

    # 红面或辅助分划 (同步偏移, 保持检核差不变)
    if fs.red_mid_m is not None:
        fs.red_mid_m = round_reading(fs.red_mid_m + residual_m, reading_dp)
    if fs.aux_mid_m is not None:
        fs.aux_mid_m = round_reading(fs.aux_mid_m + residual_m, reading_dp)


# ──────────────────────────────────────────────────────────────────────
# 主入口
# ──────────────────────────────────────────────────────────────────────

def generate_leveling_workbook(
    route: RouteInfo,
    grade: LevelingGrade,
    num_stations: int,
    rod_back: Optional[RodSpec] = None,
    rod_fore: Optional[RodSpec] = None,
    metadata: Optional[SurveyMetadata] = None,
    section_id: str = "S1",
    seed: Optional[int] = None,
    truncation_k: float = 3.0,
    round_trip: bool = False,
    return_section_id: str = "S2",
    observation_sequence: str = "alternate",
    target_closure_ratio: float = 0.0,
    target_round_trip_ratio: float = 0.0,
) -> LevelingWorkbook:
    """
    从 RTK 高程真值逆向生成水准观测手簿.

    参数:
        route: 路线信息 (起终点名称 + 已知高程)
        grade: 目标等级
        num_stations: 测站数
        rod_back, rod_fore: 尺规格 (None=使用等级默认)
        metadata: 表头元数据 (None=使用默认)
        section_id: 测段编号
        seed: 随机种子 (None=不固定)
        truncation_k: 截断系数 (默认 3.0)
        round_trip: 是否生成往返观测 (二等水准)
        return_section_id: 返测测段编号
        observation_sequence: "alternate"=奇偶站交替, "uniform"=统一顺序
        target_closure_ratio: 目标闭合差/限差比值 (0-1, 默认0=精确零)
        target_round_trip_ratio: 目标往返不符值/限差比值 (0-1, 默认0=精确零)

    返回:
        LevelingWorkbook (可通过 validate_leveling_workbook 验证)

    数学保证:
        - 核空间约束: 每站后视前视读数施加同向等量扰动, 高差精确不变
        - 闭合差: target_closure_ratio=0 时精确为零; >0 时保留受控残差
        - 往返不符值: target_round_trip_ratio=0 时精确为零; >0 时保留受控残差
        - 读数精度: 按等级取整 (二等 0.1mm, 三四等 1mm)
    """
    rng = np.random.default_rng(seed)
    params = _GRADE_PARAMS[grade]
    sigma_m = mm_to_m(params["sigma_mm"])
    reading_dp = params["reading_dp"]

    # 默认尺型
    if rod_back is None or rod_fore is None:
        default_back, default_fore = DEFAULT_ROD_SPECS[grade]
        rod_back = rod_back or default_back
        rod_fore = rod_fore or default_fore

    # 默认元数据
    if metadata is None:
        metadata = SurveyMetadata(
            date="2025-06-01", observer="模拟观测",
            recorder="模拟记录", instrument_model="DS3",
            instrument_serial="SIM-001",
        )

    is_extra = (grade == LevelingGrade.EXTRA)

    # 往返测残差控制: target_round_trip_ratio > 0 时, 各测段闭合差归零, 仅控制往返不符值
    effective_closure_ratio = target_closure_ratio
    if round_trip and target_round_trip_ratio > 0:
        effective_closure_ratio = 0.0

    # ── 生成往测 ──
    outbound_section, outbound_stations_raw = _generate_single_section(
        route=route, grade=grade, num_stations=num_stations,
        rod_back=rod_back, rod_fore=rod_fore,
        metadata=metadata, section_id=section_id,
        sigma_m=sigma_m, reading_dp=reading_dp, params=params, rng=rng,
        is_extra=is_extra,
        observation_sequence_mode=observation_sequence,
        is_outbound=True,
        target_closure_ratio=effective_closure_ratio,
    )

    sections = [outbound_section]
    extra_sections = []

    # ── 生成返测 ──
    if round_trip and not is_extra:
        # 反转中间点顺序 (返测路线反向)
        return_intermediates = None
        if route.intermediate_points:
            return_intermediates = list(reversed(route.intermediate_points))

        return_route = RouteInfo(
            start_point_name=route.end_point_name,
            start_point_height=route.end_point_height,
            end_point_name=route.start_point_name,
            end_point_height=route.start_point_height,
            total_length_km=route.total_length_km,
            intermediate_points=return_intermediates,
        )
        return_section, return_stations_raw = _generate_single_section(
            route=return_route, grade=grade, num_stations=num_stations,
            rod_back=rod_back, rod_fore=rod_fore,
            metadata=metadata, section_id=return_section_id,
            sigma_m=sigma_m, reading_dp=reading_dp, params=params, rng=rng,
            is_extra=False,
            observation_sequence_mode=observation_sequence,
            is_outbound=False,
            target_closure_ratio=effective_closure_ratio,
        )
        sections.append(return_section)

        # ── 往返测残差: 使不符值非零且受控 ──
        if target_round_trip_ratio > 0:
            L_km = route.total_length_km or 1.0
            coeff = _ROUND_TRIP_LIMIT_COEFF.get(grade, 12.0)
            limit_mm = coeff * math.sqrt(L_km)
            target_m = target_round_trip_ratio * limit_mm / 1000.0
            sign = rng.choice([-1.0, 1.0])
            # 分摊到往测和返测, 各自闭合差 = half_residual, 往返不符值 = target
            half_residual_m = target_m * sign / 2.0
            _apply_round_trip_residual(sections[0], half_residual_m, reading_dp)
            _apply_round_trip_residual(sections[1], half_residual_m, reading_dp)

    # ── 构造 Workbook ──
    if is_extra:
        extra_sections = sections
        sections = []

    workbook = LevelingWorkbook(
        grade=grade,
        sections=sections,
        extra_sections=extra_sections,
        is_round_trip=round_trip and not is_extra,
        generation_metadata=GenerationMetadata(
            target_grade=grade.value,
            random_seed=seed,
            truncation_k=truncation_k,
            leveling_sigma_mm=params["sigma_mm"],
        ),
    )

    # ── 往返测高差不符值 ──
    if workbook.is_round_trip and len(sections) == 2:
        h_outbound = _compute_section_sum_h(sections[0])
        h_return = _compute_section_sum_h(sections[1])
        # 往测高差 + 返测高差，理论为 0 (h_往 = -(h_返))
        discrepancy_mm = abs(h_outbound + h_return) * 1000.0
        L_km = route.total_length_km or 1.0
        coeff = _ROUND_TRIP_LIMIT_COEFF.get(grade, 12.0)
        limit_mm = coeff * math.sqrt(L_km)
        workbook.round_trip_discrepancy_mm = float(discrepancy_mm)
        workbook.round_trip_limit_mm = float(limit_mm)
        workbook.round_trip_passed = bool(discrepancy_mm <= limit_mm)

    return workbook


def _build_waypoints_and_heights(
    route: RouteInfo,
    num_stations: int,
    rng: np.random.Generator,
) -> Tuple[List[str], List[float]]:
    """
    根据 RouteInfo 构建路线点序列和高程序列.

    - 无 intermediate_points: 行为不变 (起→TP.1→…→TP.{n-1}→终)
    - 有 intermediate_points: 起→TP.段序号.1→…→中间点→TP.段序号.1→…→终,
      在相邻控制点间自动插入转点, 并标记控制点.

    返回:
        point_names: 长度 = num_stations + 1
        heights: 长度 = num_stations + 1
    """
    dh_total = route.end_point_height - route.start_point_height

    if route.intermediate_points is None or len(route.intermediate_points) == 0:
        # 原有逻辑
        point_names = [route.start_point_name]
        for i in range(1, num_stations):
            point_names.append(f"TP.{i}")
        point_names.append(route.end_point_name)

        heights = [route.start_point_height]
        for i in range(1, num_stations + 1):
            heights.append(route.start_point_height + dh_total * i / num_stations)
        return point_names, heights

    # 有中间控制点: 将路线分为 segments
    control_points = [(route.start_point_name, route.start_point_height)]
    control_points.extend(route.intermediate_points)
    control_points.append((route.end_point_name, route.end_point_height))

    num_segments = len(control_points) - 1
    # 按段分配测站数: 按高差比例分配, 不足时每段至少1站
    seg_dh = []
    for i in range(num_segments):
        seg_dh.append(control_points[i + 1][1] - control_points[i][1])

    total_abs_dh = sum(abs(d) for d in seg_dh) or 1.0
    seg_stations = []
    remaining = num_stations
    for i in range(num_segments):
        if i == num_segments - 1:
            seg_stations.append(remaining)
        else:
            n_seg = max(1, round(num_stations * abs(seg_dh[i]) / total_abs_dh))
            n_seg = min(n_seg, remaining - (num_segments - 1 - i))
            n_seg = max(1, n_seg)
            seg_stations.append(n_seg)
            remaining -= n_seg

    point_names = []
    heights = []
    global_station_offset = 0

    for seg_idx in range(num_segments):
        cp_start_name, cp_start_h = control_points[seg_idx]
        cp_end_name, cp_end_h = control_points[seg_idx + 1]
        n_seg = seg_stations[seg_idx]
        seg_dh_val = cp_end_h - cp_start_h

        # 段内起点 (非首段时跳过, 因为是上一段的终点)
        if seg_idx == 0:
            point_names.append(cp_start_name)
            heights.append(cp_start_h)

        # 段内转点 (n_seg 个测站产生 n_seg-1 个中间点 + 终点)
        for j in range(1, n_seg):
            tp_name = f"TP.{seg_idx + 1}.{j}"
            point_names.append(tp_name)
            heights.append(cp_start_h + seg_dh_val * j / n_seg)

        # 段终点 (控制点)
        point_names.append(cp_end_name)
        heights.append(cp_end_h)
        global_station_offset += n_seg

    return point_names, heights


def _build_point_type_map(point_names: List[str], route: RouteInfo) -> dict:
    """
    构建点号→点类型的映射.

    控制点: start, end, intermediate_points 中的点 → "control"
    转点: TP.x.y 格式 → "turning"
    其他: None
    """
    control_names = {route.start_point_name, route.end_point_name}
    if route.intermediate_points:
        for name, _ in route.intermediate_points:
            control_names.add(name)

    type_map = {}
    for name in point_names:
        if name in control_names:
            type_map[name] = "control"
        elif name.startswith("TP."):
            type_map[name] = "turning"
    return type_map


def _generate_single_section(
    route: RouteInfo,
    grade: LevelingGrade,
    num_stations: int,
    rod_back: RodSpec,
    rod_fore: RodSpec,
    metadata: SurveyMetadata,
    section_id: str,
    sigma_m: float,
    reading_dp: int,
    params: dict,
    rng: np.random.Generator,
    is_extra: bool,
    observation_sequence_mode: str = "uniform",
    is_outbound: bool = True,
    target_closure_ratio: float = 0.0,
):
    """
    生成单个测段 (往测或返测).

    返回: (LevelingSection, raw_station_data_list)
    """
    n = num_stations
    dh_total = route.end_point_height - route.start_point_height

    # 构建路线点序列和高程序列 (支持 intermediate_points)
    point_names, heights = _build_waypoints_and_heights(route, n, rng)

    # 构建点类型映射
    point_type_map = _build_point_type_map(point_names, route)

    # 各站精确高差: 从高程序列直接计算 (保证经过中间控制点)
    exact_height_diffs = [heights[i + 1] - heights[i] for i in range(n)]

    # 随机微扰高差 (保持总和精确 = dh_total)
    height_diffs = _distribute_height_diffs(dh_total, n, rng)

    # 有中间控制点时: 使用精确高差 (保证经过控制点的高程正确)
    # 无中间控制点时: 使用随机分配的高差 (原有行为)
    if route.intermediate_points and len(route.intermediate_points) > 0:
        # 精确高差保证控制点高程, 但需要末站校正以消除累积浮点误差
        use_height_diffs = exact_height_diffs
    else:
        use_height_diffs = height_diffs

    # ── 生成各站 ──
    station_data_list = []
    for i in range(n):
        if is_extra:
            sd = _gen_extra_station(
                i + 1, point_names[i], point_names[i + 1],
                use_height_diffs[i], heights[i], heights[i + 1],
                sigma_m, reading_dp, rng,
            )
        elif rod_back.rod_type == RodType.INVAR_BASIC_AUX:
            sd = _gen_invar_station(
                i + 1, point_names[i], point_names[i + 1],
                use_height_diffs[i], heights[i], heights[i + 1],
                sigma_m, reading_dp, params, rng,
                rod_back.c_aux_m or 3.0155,
            )
        else:  # DOUBLE_FACE
            sd = _gen_double_face_station(
                i + 1, point_names[i], point_names[i + 1],
                use_height_diffs[i], heights[i], heights[i + 1],
                sigma_m, reading_dp, params, rng,
                rod_back.k_value_m or 4.687,
                rod_fore.k_value_m or 4.787,
            )

        # ── 设置点类型 (前视点类型) ──
        fore_pt = point_names[i + 1]
        sd["point_type"] = point_type_map.get(fore_pt)

        # ── 设置观测顺序 (二等水准奇偶站交替) ──
        if observation_sequence_mode == "alternate" and not is_extra:
            is_odd = ((i + 1) % 2 == 1)
            if is_outbound:
                seq = (ObservationSequence.BACK_FORE_FORE_BACK if is_odd
                       else ObservationSequence.FORE_BACK_BACK_FORE)
            else:
                seq = (ObservationSequence.FORE_BACK_BACK_FORE if is_odd
                       else ObservationSequence.BACK_FORE_FORE_BACK)
            sd["observation_sequence"] = seq
        elif observation_sequence_mode == "uniform" and not is_extra:
            sd["observation_sequence"] = ObservationSequence.BACK_FORE_FORE_BACK

        station_data_list.append(sd)

    # ── 闭合差校正 (末站前视调整) ──
    # target_closure_ratio = 0: 完全校正, 闭合差精确为零
    # target_closure_ratio > 0: 完全校正后, 再施加受控残差
    if is_extra:
        closure = sum(
            (sd["backsight_1_m"] - sd["foresight_1_m"]) +
            (sd["backsight_2_m"] - sd["foresight_2_m"])
            for sd in station_data_list
        ) / 2.0 - dh_total
        if abs(closure) > 1e-12:
            _apply_closure_correction_extra(
                station_data_list[-1], closure, reading_dp)
        # 施加受控残差
        if target_closure_ratio > 0:
            _apply_target_residual(
                station_data_list[-1], route, grade,
                target_closure_ratio, reading_dp, rng, is_extra=True)
    else:
        closure = sum(
            sd["backsight"].black_mid_m - sd["foresight"].black_mid_m
            for sd in station_data_list
        ) - dh_total
        if abs(closure) > 1e-12:
            if rod_back.rod_type == RodType.INVAR_BASIC_AUX:
                _apply_closure_correction_invar(
                    station_data_list[-1], closure, reading_dp)
            else:
                _apply_closure_correction_double_face(
                    station_data_list[-1], closure, reading_dp)
        # 施加受控残差
        if target_closure_ratio > 0:
            _apply_target_residual(
                station_data_list[-1], route, grade,
                target_closure_ratio, reading_dp, rng,
                is_extra=False, rod=rod_back)

    # ── 构造模型对象 ──
    if is_extra:
        stations = [
            ExtraLevelingStation(**{k: v for k, v in sd.items()
                                     if not k.startswith('_')})
            for sd in station_data_list
        ]
        section = ExtraLevelingSection(
            section_id=section_id,
            metadata=metadata,
            route=route,
            rod=rod_back,
            stations=stations,
        )
    else:
        stations = [
            LevelingStation(**{k: v for k, v in sd.items()
                                if not k.startswith('_')})
            for sd in station_data_list
        ]
        section = LevelingSection(
            section_id=section_id,
            metadata=metadata,
            route=route,
            grade=grade,
            rod_back=rod_back,
            rod_fore=rod_fore,
            stations=stations,
        )

    return section, station_data_list
