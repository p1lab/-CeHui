# src/config_loader.py
# 配置加载与封装工具
#
# 将 config/*.json 中的规范参数转换为生成器/检核器可直接使用的字典,
# 消除源码中硬编码参数与配置文件的双轨制.
#
# 设计原则:
#   - 每个配置加载函数在文件缺失/解析失败时返回空 dict, 由调用方回退到内置默认值.
#   - 提供与原有 _GRADE_PARAMS / _LEVELING_LIMITS 等结构兼容的参数字典.
#   - 支持相对路径 (基于当前工作目录) 和绝对路径.

from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional, Tuple

from .models.common import LevelingGrade, TraverseGrade, AngleObservationMethod


# ──────────────────────────────────────────────────────────────────────
# 默认文件路径 (相对于项目工作目录)
# ──────────────────────────────────────────────────────────────────────

_DEFAULT_LEVELING_CONFIG_PATH = "config/config_leveling.json"
_DEFAULT_TRAVERSING_CONFIG_PATH = "config/config_traversing.json"
_DEFAULT_OBSERVATION_PROGRAM_PATH = "config/config_observation_program.json"


# ──────────────────────────────────────────────────────────────────────
# 基础加载
# ──────────────────────────────────────────────────────────────────────

def _resolve_path(path: Optional[str], default_path: str) -> str:
    """解析配置路径: None 时使用默认路径."""
    if path is None:
        return default_path
    return path


def _load_json(path: str) -> Dict[str, Any]:
    """加载 JSON 文件; 失败时返回空 dict."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def load_leveling_config(path: Optional[str] = None) -> Dict[str, Any]:
    """加载水准测量规范配置."""
    return _load_json(_resolve_path(path, _DEFAULT_LEVELING_CONFIG_PATH))


def load_traversing_config(path: Optional[str] = None) -> Dict[str, Any]:
    """加载导线测量规范配置 (含继承解析)."""
    raw = _load_json(_resolve_path(path, _DEFAULT_TRAVERSING_CONFIG_PATH))
    return _resolve_inheritance(raw)


def load_observation_program_config(path: Optional[str] = None) -> Dict[str, Any]:
    """加载观测程序配置."""
    return _load_json(_resolve_path(path, _DEFAULT_OBSERVATION_PROGRAM_PATH))


# ──────────────────────────────────────────────────────────────────────
# 继承解析 (traversing config)
# ──────────────────────────────────────────────────────────────────────

def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """深度合并两个字典: override 覆盖 base."""
    result = dict(base)
    for key, val in override.items():
        if key.startswith("_"):
            # 元数据字段直接覆盖
            result[key] = val
        elif isinstance(val, dict) and key in result and isinstance(result[key], dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result


def _resolve_inheritance(config: Dict[str, Any]) -> Dict[str, Any]:
    """解析 grade 间的 _inherits_from 关系."""
    resolved = dict(config)
    grades = ["grade_1", "grade_2", "root"]
    for grade_key in grades:
        grade_cfg = resolved.get(grade_key)
        if not isinstance(grade_cfg, dict):
            continue
        parent_key = grade_cfg.get("_inherits_from")
        if parent_key and parent_key in resolved:
            parent_cfg = resolved[parent_key]
            # 合并: 父级为基础, 子级覆盖 (保留子级 _label 等元数据)
            merged = _deep_merge(parent_cfg, grade_cfg)
            resolved[grade_key] = merged
    return resolved


# ──────────────────────────────────────────────────────────────────────
# 等级键映射
# ──────────────────────────────────────────────────────────────────────

def _leveling_grade_key(grade: LevelingGrade) -> str:
    return {
        LevelingGrade.GRADE_2: "grade_2",
        LevelingGrade.GRADE_3: "grade_3",
        LevelingGrade.GRADE_4: "grade_4",
        LevelingGrade.EXTRA: "extra",
    }.get(grade, "grade_3")


def _traversing_grade_key(grade: TraverseGrade) -> str:
    return {
        TraverseGrade.GRADE_1: "grade_1",
        TraverseGrade.GRADE_2: "grade_2",
        TraverseGrade.ROOT: "root",
    }.get(grade, "grade_1")


def _instrument_key(inst_grade: Any) -> str:
    """InstrumentGrade / 字符串 → config key."""
    from .models.common import InstrumentGrade
    if inst_grade == InstrumentGrade.SEC_2:
        return "2sec"
    if inst_grade == InstrumentGrade.SEC_6:
        return "6sec"
    if isinstance(inst_grade, str):
        return inst_grade.lower()
    return "2sec"


# ──────────────────────────────────────────────────────────────────────
# 水准: 生成器参数
# ──────────────────────────────────────────────────────────────────────

def get_leveling_grade_params(
    leveling_config: Dict[str, Any],
    observation_program_config: Dict[str, Any],
    grade: LevelingGrade,
) -> Dict[str, Any]:
    """
    获取水准生成器参数 (兼容原 _GRADE_PARAMS 结构).

    返回字段:
        sigma_mm, base_aux_sigma_mm (GRADE_2), sight_dist_range, dist_diff_max,
        reading_dp, buffer, reading_range
    """
    grade_key = _leveling_grade_key(grade)
    grade_cfg = leveling_config.get(grade_key, {})
    sim = grade_cfg.get("simulation", {})

    out_fmt = observation_program_config.get("output_format", {})
    reading_dp_map = out_fmt.get("leveling_reading_decimal_places", {})
    reading_dp = reading_dp_map.get(grade_key, 3)

    default_sim = observation_program_config.get("default_simulation_parameters", {})
    lvl_defaults = default_sim.get("leveling", {})
    buffer = tuple(lvl_defaults.get("sight_height_buffer_m", [1.5, 2.5]))
    reading_range = tuple(lvl_defaults.get("reading_range_m", [0.3, 2.5]))

    if grade == LevelingGrade.EXTRA:
        return {
            "sigma_mm": sim.get("reading_perturbation_sigma_mm", 2.0),
            "reading_dp": reading_dp,
            "reading_range": reading_range,
        }

    sight_dist = sim.get("sight_distance_range_m", [20.0, 50.0])
    dist_diff_range = sim.get("distance_diff_range_m", [-3.0, 3.0])
    dist_diff_max = max(abs(float(dist_diff_range[0])), abs(float(dist_diff_range[1])))

    params = {
        "sigma_mm": sim.get("reading_perturbation_sigma_mm", 0.5),
        "sight_dist_range": tuple(sight_dist),
        "dist_diff_max": dist_diff_max,
        "reading_dp": reading_dp,
        "buffer": buffer,
        "reading_range": reading_range,
    }

    if grade == LevelingGrade.GRADE_2:
        params["base_aux_sigma_mm"] = sim.get(
            "base_aux_perturbation_sigma_mm", 0.15)

    return params


def get_leveling_round_trip_coeff(
    leveling_config: Dict[str, Any],
    grade: LevelingGrade,
) -> float:
    """获取往返测高差不符值限差系数 (C × √L mm)."""
    grade_key = _leveling_grade_key(grade)
    grade_cfg = leveling_config.get(grade_key, {})
    closure = grade_cfg.get("closure", {})

    if grade == LevelingGrade.GRADE_2:
        return closure.get("national_grade_coefficient", 4.0)
    return closure.get("flat_coefficient", 12.0)


# ──────────────────────────────────────────────────────────────────────
# 水准: 检核器限差
# ──────────────────────────────────────────────────────────────────────

def get_leveling_limits(
    leveling_config: Dict[str, Any],
    grade: LevelingGrade,
) -> Dict[str, Any]:
    """获取水准合规检核限差 (兼容原 _LEVELING_LIMITS 结构)."""
    grade_key = _leveling_grade_key(grade)
    grade_cfg = leveling_config.get(grade_key, {})
    sight = grade_cfg.get("sight", {})
    reading_check = grade_cfg.get("reading_check", {})
    closure = grade_cfg.get("closure", {})

    if grade == LevelingGrade.GRADE_2:
        digital = reading_check.get("digital", {})
        optical = reading_check.get("optical", {})
        return {
            "max_sight_length_m": sight.get("max_length_m", 50.0),
            "max_station_distance_diff_m": sight.get(
                "max_station_distance_diff_m", 1.0),
            "max_cumulative_distance_diff_m": sight.get(
                "max_cumulative_distance_diff_m", 3.0),
            "digital": {
                "base_aux_reading_diff_mm": digital.get(
                    "base_aux_reading_diff_mm", 0.4),
                "base_aux_height_diff_mm": digital.get(
                    "base_aux_height_diff_mm", 0.6),
            },
            "optical": {
                "base_aux_reading_diff_mm": optical.get(
                    "base_aux_reading_diff_mm", 0.5),
                "base_aux_height_diff_mm": optical.get(
                    "base_aux_height_diff_mm", 0.7),
            },
            "base_aux_reading_diff_mm": reading_check.get(
                "base_aux_reading_diff_mm", 0.4),
            "base_aux_height_diff_mm": reading_check.get(
                "base_aux_height_diff_mm", 0.6),
            "closure_coefficient": closure.get("national_grade_coefficient", 4.0),
        }

    if grade == LevelingGrade.EXTRA:
        check_method = grade_cfg.get("check_method", {})
        return {
            "height_diff_diff_mm": check_method.get("height_diff_diff_mm", 5.0),
            "closure_coefficient": closure.get("flat_coefficient", 40.0),
        }

    # GRADE_3 / GRADE_4
    return {
        "max_sight_length_m": sight.get("max_length_m", 75.0),
        "max_station_distance_diff_m": sight.get(
            "max_station_distance_diff_m", 3.0),
        "max_cumulative_distance_diff_m": sight.get(
            "max_cumulative_distance_diff_m", 10.0),
        "k_plus_black_minus_red_mm": reading_check.get(
            "k_plus_black_minus_red_mm", 2.0),
        "black_red_height_diff_diff_mm": reading_check.get(
            "black_red_height_diff_diff_mm", 5.0),
        "closure_coefficient": closure.get("flat_coefficient", 12.0),
    }


# ──────────────────────────────────────────────────────────────────────
# 导线: 生成器参数
# ──────────────────────────────────────────────────────────────────────

def get_traversing_grade_params(
    traversing_config: Dict[str, Any],
    grade: TraverseGrade,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    获取导线生成器参数 (兼容原 _ANGLE_PARAMS / _DISTANCE_PARAMS 结构).

    返回: (angle_params, distance_params)
    """
    grade_key = _traversing_grade_key(grade)
    grade_cfg = traversing_config.get(grade_key, {})
    sim = grade_cfg.get("simulation", {})
    angular = grade_cfg.get("angular", {})
    distance = grade_cfg.get("distance", {})

    # 角度参数
    sigma_arcsec = sim.get("angle_perturbation_sigma_arcsec")
    if sigma_arcsec is None:
        sigma_arcsec = angular.get("measurement_mean_error_arcsec", 5.0) / 10.0

    # 2C 扰动 sigma: 优先取显式配置, 否则由 2c_range 推导
    sigma_2c_arcsec = sim.get("2c_perturbation_sigma_arcsec")
    if sigma_2c_arcsec is None:
        range_2c = sim.get("2c_range_arcsec", [-6.5, 6.5])
        sigma_2c_arcsec = (float(range_2c[1]) - float(range_2c[0])) / 6.0

    # 测回间角值扰动 sigma
    sigma_set_arcsec = sim.get(
        "set_perturbation_sigma_arcsec",
        # 默认与角度扰动同数量级, 保证测回间存在自然分散
        sigma_arcsec * 4.0,
    )

    angle_params = {
        "sigma_arcsec": float(sigma_arcsec),
        "sigma_2c_arcsec": float(sigma_2c_arcsec),
        "sigma_set_arcsec": float(sigma_set_arcsec),
    }

    # 距离参数
    sigma_mm = sim.get("distance_perturbation_sigma_mm")
    if sigma_mm is None:
        sigma_mm = distance.get("measurement_mean_error_mm", 15.0) / 30.0

    sigma_reading_mm = sim.get("distance_reading_sigma_mm")
    if sigma_reading_mm is None:
        # 默认值与现有硬编码保持一致
        defaults = {TraverseGrade.GRADE_1: 1.2, TraverseGrade.GRADE_2: 1.2,
                    TraverseGrade.ROOT: 2.5}
        sigma_reading_mm = defaults.get(grade, 1.2)

    reading_diff_sigma_mm = sim.get("reading_diff_sigma_mm")
    if reading_diff_sigma_mm is None:
        reading_diff_sigma_mm = distance.get("reading_diff_mm", 10.0) / 10.0

    distance_params = {
        "sigma_mm": float(sigma_mm),
        "readings_per_set": int(distance.get("readings_per_set", 3)),
        "reading_diff_sigma_mm": float(reading_diff_sigma_mm),
        "sigma_reading_mm": float(sigma_reading_mm),
    }

    return angle_params, distance_params


def get_degree_plate_offset_rad(observation_program_config: Dict[str, Any]) -> float:
    """获取度盘零位偏移 (rad)."""
    cfg = observation_program_config.get("degree_plate_config", {})
    return float(cfg.get("offset_radians", 0.000727))


# ──────────────────────────────────────────────────────────────────────
# 导线: 检核器限差
# ──────────────────────────────────────────────────────────────────────

def get_traversing_limits(
    traversing_config: Dict[str, Any],
    grade: TraverseGrade,
) -> Dict[str, Any]:
    """获取导线合规检核限差 (兼容原 _TRAVERSING_LIMITS 结构)."""
    grade_key = _traversing_grade_key(grade)
    grade_cfg = traversing_config.get(grade_key, {})
    angular = grade_cfg.get("angular", {})
    distance = grade_cfg.get("distance", {})
    closure = grade_cfg.get("closure", {})

    # 仪器级检核 (2sec / 6sec)
    checks_2sec = angular.get("checks_2sec_instrument", {})
    checks_6sec = angular.get("checks_6sec_instrument", {})
    measurement_checks = angular.get("measurement_method_checks", {})

    # 方向观测法限差
    direction_instrument = {
        "2sec": {
            "2c_mutual_diff_arcsec": checks_2sec.get(
                "one_set_2c_mutual_diff_arcsec", 13.0),
            "half_set_return_zero_diff_arcsec": checks_2sec.get(
                "half_set_return_zero_diff_arcsec", 8.0),
            "direction_diff_across_sets_arcsec": checks_2sec.get(
                "direction_value_diff_across_sets_arcsec", 9.0),
        },
        "6sec": {
            "2c_mutual_diff_arcsec": checks_6sec.get(
                "one_set_2c_mutual_diff_arcsec", 18.0),
            "half_set_return_zero_diff_arcsec": checks_6sec.get(
                "half_set_return_zero_diff_arcsec", 12.0),
            "direction_diff_across_sets_arcsec": checks_6sec.get(
                "direction_value_diff_across_sets_arcsec", 12.0),
        },
    }

    direction_common = {
        "half_set_diff_arcsec": angular.get("half_set_diff_arcsec", 12.0),
        "reading_diff_mm": distance.get("reading_diff_mm", 10.0),
        "round_trip_diff_mm": distance.get("round_trip_diff_mm", 10.0),
        "azimuth_closure_coefficient": angular.get(
            "azimuth_closure_coefficient", 10.0),
        "relative_closure_denominator": closure.get(
            "full_length_relative_closure_denominator", 15000),
    }

    # 测回法限差
    measurement_2sec = measurement_checks.get("2sec", {})
    measurement_6sec = measurement_checks.get("6sec", {})
    measurement_instrument = {
        "2sec": {
            "2c_mutual_diff_arcsec": measurement_2sec.get(
                "2c_mutual_diff_arcsec", 13.0),
            "half_set_diff_arcsec": measurement_2sec.get(
                "half_set_diff_arcsec", 9.0),
            "set_diff_arcsec": measurement_2sec.get("set_diff_arcsec", 10.0),
        },
        "6sec": {
            "2c_mutual_diff_arcsec": measurement_6sec.get(
                "2c_mutual_diff_arcsec", 18.0),
            "half_set_diff_arcsec": measurement_6sec.get(
                "half_set_diff_arcsec", 18.0),
            "set_diff_arcsec": measurement_6sec.get("set_diff_arcsec", 24.0),
        },
    }

    measurement_common = {
        "reading_diff_mm": distance.get("reading_diff_mm", 10.0),
        "round_trip_diff_mm": distance.get("round_trip_diff_mm", 10.0),
        "azimuth_closure_coefficient": angular.get(
            "azimuth_closure_coefficient", 10.0),
        "relative_closure_denominator": closure.get(
            "full_length_relative_closure_denominator", 15000),
    }

    return {
        AngleObservationMethod.DIRECTION: {
            **direction_instrument,
            **direction_common,
        },
        AngleObservationMethod.MEASUREMENT: {
            **measurement_instrument,
            **measurement_common,
        },
    }


# ──────────────────────────────────────────────────────────────────────
# 默认配置 (向后兼容: 当配置文件完全不可用时使用)
# ──────────────────────────────────────────────────────────────────────

DEFAULT_LEVELING_CONFIG: Dict[str, Any] = {
    "grade_2": {
        "sight": {
            "max_length_m": 50.0,
            "max_station_distance_diff_m": 1.0,
            "max_cumulative_distance_diff_m": 3.0,
        },
        "reading_check": {
            "digital": {"base_aux_reading_diff_mm": 0.4,
                        "base_aux_height_diff_mm": 0.6},
            "optical": {"base_aux_reading_diff_mm": 0.5,
                        "base_aux_height_diff_mm": 0.7},
            "base_aux_reading_diff_mm": 0.4,
            "base_aux_height_diff_mm": 0.6,
        },
        "closure": {"national_grade_coefficient": 4.0},
        "simulation": {
            "sight_distance_range_m": [20.0, 50.0],
            "distance_diff_range_m": [-0.8, 0.8],
            "reading_perturbation_sigma_mm": 0.05,
            "base_aux_perturbation_sigma_mm": 0.15,
        },
    },
    "grade_3": {
        "sight": {
            "max_length_m": 75.0,
            "max_station_distance_diff_m": 3.0,
            "max_cumulative_distance_diff_m": 10.0,
        },
        "reading_check": {
            "k_plus_black_minus_red_mm": 2.0,
            "black_red_height_diff_diff_mm": 5.0,
        },
        "closure": {"flat_coefficient": 12.0},
        "simulation": {
            "sight_distance_range_m": [20.0, 75.0],
            "distance_diff_range_m": [-3.0, 3.0],
            "reading_perturbation_sigma_mm": 0.5,
        },
    },
    "grade_4": {
        "sight": {
            "max_length_m": 100.0,
            "max_station_distance_diff_m": 3.0,
            "max_cumulative_distance_diff_m": 10.0,
        },
        "reading_check": {
            "k_plus_black_minus_red_mm": 3.0,
            "black_red_height_diff_diff_mm": 5.0,
        },
        "closure": {"flat_coefficient": 20.0},
        "simulation": {
            "sight_distance_range_m": [20.0, 100.0],
            "distance_diff_range_m": [-3.0, 3.0],
            "reading_perturbation_sigma_mm": 1.0,
        },
    },
    "extra": {
        "check_method": {"height_diff_diff_mm": 5.0},
        "closure": {"flat_coefficient": 40.0},
        "simulation": {
            "reading_range_m": [0.3, 2.5],
            "reading_perturbation_sigma_mm": 2.0,
        },
    },
}


DEFAULT_TRAVERSING_CONFIG: Dict[str, Any] = {
    "grade_1": {
        "angular": {
            "measurement_mean_error_arcsec": 5.0,
            "azimuth_closure_coefficient": 10.0,
            "checks_2sec_instrument": {
                "half_set_return_zero_diff_arcsec": 8.0,
                "one_set_2c_mutual_diff_arcsec": 13.0,
                "direction_value_diff_across_sets_arcsec": 9.0,
            },
            "checks_6sec_instrument": {
                "half_set_return_zero_diff_arcsec": 12.0,
                "one_set_2c_mutual_diff_arcsec": 18.0,
                "direction_value_diff_across_sets_arcsec": 12.0,
            },
            "half_set_diff_arcsec": 12.0,
            "measurement_method_checks": {
                "2sec": {"half_set_diff_arcsec": 9.0, "set_diff_arcsec": 10.0,
                         "2c_mutual_diff_arcsec": 13.0},
                "6sec": {"half_set_diff_arcsec": 18.0, "set_diff_arcsec": 24.0,
                         "2c_mutual_diff_arcsec": 18.0},
            },
        },
        "distance": {
            "readings_per_set": 3,
            "reading_diff_mm": 10.0,
            "round_trip_diff_mm": 10.0,
        },
        "closure": {
            "full_length_relative_closure_denominator": 15000,
        },
        "simulation": {
            "angle_perturbation_sigma_arcsec": 0.5,
            "distance_perturbation_sigma_mm": 0.5,
            "2c_perturbation_sigma_arcsec": 3.0,
            "set_perturbation_sigma_arcsec": 2.0,
            "distance_reading_sigma_mm": 1.2,
            "reading_diff_sigma_mm": 1.0,
        },
    },
    "grade_2": {
        "_inherits_from": "grade_1",
        "angular": {
            "measurement_mean_error_arcsec": 10.0,
            "azimuth_closure_coefficient": 16.0,
        },
        "closure": {
            "full_length_relative_closure_denominator": 10000,
        },
        "simulation": {
            "angle_perturbation_sigma_arcsec": 2.0,
            "distance_perturbation_sigma_mm": 2.0,
            "2c_perturbation_sigma_arcsec": 6.0,
            "set_perturbation_sigma_arcsec": 4.0,
            "distance_reading_sigma_mm": 1.2,
            "reading_diff_sigma_mm": 2.0,
        },
    },
    "root": {
        "_inherits_from": "grade_1",
        "angular": {
            "measurement_mean_error_arcsec": 30.0,
        },
        "closure": {
            "full_length_relative_closure_denominator": 2000,
        },
        "simulation": {
            "angle_perturbation_sigma_arcsec": 10.0,
            "distance_perturbation_sigma_mm": 10.0,
            "2c_perturbation_sigma_arcsec": 15.0,
            "set_perturbation_sigma_arcsec": 8.0,
            "distance_reading_sigma_mm": 2.5,
            "reading_diff_sigma_mm": 5.0,
        },
    },
}


DEFAULT_OBSERVATION_PROGRAM_CONFIG: Dict[str, Any] = {
    "degree_plate_config": {"offset_radians": 0.000727},
    "output_format": {
        "leveling_reading_decimal_places": {
            "grade_2": 4, "grade_3": 3, "grade_4": 3, "extra": 3,
        },
    },
    "default_simulation_parameters": {
        "leveling": {
            "sight_height_buffer_m": [1.5, 2.5],
            "reading_range_m": [0.3, 2.5],
        },
    },
}
