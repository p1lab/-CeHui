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
    LevelingWorkbook,
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

    返回:
        LevelingWorkbook (可通过 validate_leveling_workbook 验证)

    数学保证:
        - 核空间约束: 每站后视前视读数施加同向等量扰动, 高差精确不变
        - 闭合差: 经末站校正后精确为零 (终点高程验证通过)
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

    # ── 构造点序列 ──
    n = num_stations
    dh_total = route.end_point_height - route.start_point_height
    point_names = [route.start_point_name]
    for i in range(1, n):
        point_names.append(f"TP.{i}")
    point_names.append(route.end_point_name)

    # 各站高程 (线性插值)
    heights = [route.start_point_height]
    for i in range(1, n + 1):
        heights.append(
            route.start_point_height + dh_total * i / n
        )

    # 分配高差 (总和精确 = dh_total)
    height_diffs = _distribute_height_diffs(dh_total, n, rng)

    # ── 生成各站 ──
    is_extra = (grade == LevelingGrade.EXTRA)

    station_data_list = []
    for i in range(n):
        if is_extra:
            sd = _gen_extra_station(
                i + 1, point_names[i], point_names[i + 1],
                height_diffs[i], heights[i], heights[i + 1],
                sigma_m, reading_dp, rng,
            )
        elif rod_back.rod_type == RodType.INVAR_BASIC_AUX:
            sd = _gen_invar_station(
                i + 1, point_names[i], point_names[i + 1],
                height_diffs[i], heights[i], heights[i + 1],
                sigma_m, reading_dp, params, rng,
                rod_back.c_aux_m or 3.0155,
            )
        else:  # DOUBLE_FACE
            sd = _gen_double_face_station(
                i + 1, point_names[i], point_names[i + 1],
                height_diffs[i], heights[i], heights[i + 1],
                sigma_m, reading_dp, params, rng,
                rod_back.k_value_m or 4.687,
                rod_fore.k_value_m or 4.787,
            )
        station_data_list.append(sd)

    # ── 闭合差校正 (末站前视调整) ──
    if is_extra:
        closure = sum(
            (sd["backsight_1_m"] - sd["foresight_1_m"]) +
            (sd["backsight_2_m"] - sd["foresight_2_m"])
            for sd in station_data_list
        ) / 2.0 - dh_total
        if abs(closure) > 1e-12:
            _apply_closure_correction_extra(
                station_data_list[-1], closure, reading_dp)
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
        workbook = LevelingWorkbook(
            grade=grade,
            extra_sections=[section],
            generation_metadata=GenerationMetadata(
                target_grade=grade.value,
                random_seed=seed,
                truncation_k=truncation_k,
                leveling_sigma_mm=params["sigma_mm"],
            ),
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
        workbook = LevelingWorkbook(
            grade=grade,
            sections=[section],
            generation_metadata=GenerationMetadata(
                target_grade=grade.value,
                random_seed=seed,
                truncation_k=truncation_k,
                leveling_sigma_mm=params["sigma_mm"],
            ),
        )

    return workbook
