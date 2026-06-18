# tests/test_config_loader.py
# 配置加载与封装工具测试

import json
import math
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.models.common import LevelingGrade, TraverseGrade, AngleObservationMethod
from src.config_loader import (
    load_leveling_config, load_traversing_config, load_observation_program_config,
    get_leveling_grade_params, get_leveling_limits, get_leveling_round_trip_coeff,
    get_traversing_grade_params, get_traversing_limits, get_degree_plate_offset_rad,
)
from src.generators.leveling_generator import generate_leveling_workbook
from src.generators.traversing_generator import generate_traversing_workbook
from src.models.leveling import RouteInfo


# ──────────────────────────────────────────────────────────────────────
# 基础加载
# ──────────────────────────────────────────────────────────────────────

def test_load_leveling_config_default():
    """默认路径应成功加载 config_leveling.json"""
    cfg = load_leveling_config()
    assert "grade_2" in cfg
    assert cfg["grade_2"]["instrument"]["type"] == ["DS05", "DS1"]


def test_load_traversing_config_with_inheritance():
    """traversing config 应解析 _inherits_from"""
    cfg = load_traversing_config()
    grade_2 = cfg["grade_2"]
    # 继承自 grade_1 的 distance.readings_per_set
    assert grade_2["distance"]["readings_per_set"] == 3
    # 自身覆盖的 azimuth_closure_coefficient
    assert grade_2["angular"]["azimuth_closure_coefficient"] == 16.0


def test_load_observation_program_config_default():
    """默认路径应成功加载 config_observation_program.json"""
    cfg = load_observation_program_config()
    assert "degree_plate_config" in cfg
    # 教学演示用: 度盘偏移设为 0, 后视读数精确为 0°/90°
    assert cfg["degree_plate_config"]["offset_arcsec"] == 0


def test_load_missing_config_returns_empty():
    """缺失的配置文件返回空 dict, 不抛异常"""
    cfg = load_leveling_config("nonexistent_config.json")
    assert cfg == {}


# ──────────────────────────────────────────────────────────────────────
# 水准参数提取
# ──────────────────────────────────────────────────────────────────────

def test_get_leveling_grade_params_grade2():
    """二等水准参数结构正确"""
    lvl_cfg = load_leveling_config()
    prog_cfg = load_observation_program_config()
    params = get_leveling_grade_params(lvl_cfg, prog_cfg, LevelingGrade.GRADE_2)
    assert params["sigma_mm"] == 0.05
    assert params["base_aux_sigma_mm"] == 0.15
    assert params["sight_dist_range"] == (20.0, 50.0)
    assert params["dist_diff_max"] == 0.8
    assert params["reading_dp"] == 4


def test_get_leveling_grade_params_grade3():
    """三等水准参数结构正确"""
    lvl_cfg = load_leveling_config()
    prog_cfg = load_observation_program_config()
    params = get_leveling_grade_params(lvl_cfg, prog_cfg, LevelingGrade.GRADE_3)
    assert params["sigma_mm"] == 0.5
    assert "base_aux_sigma_mm" not in params
    assert params["reading_dp"] == 3


def test_get_leveling_limits_grade2():
    """二等水准限差结构正确"""
    cfg = load_leveling_config()
    limits = get_leveling_limits(cfg, LevelingGrade.GRADE_2)
    assert limits["max_sight_length_m"] == 50.0
    assert limits["digital"]["base_aux_reading_diff_mm"] == 0.4
    assert limits["closure_coefficient"] == 4.0


def test_get_leveling_round_trip_coeff():
    """往返测限差系数正确"""
    cfg = load_leveling_config()
    assert get_leveling_round_trip_coeff(cfg, LevelingGrade.GRADE_2) == 4.0
    assert get_leveling_round_trip_coeff(cfg, LevelingGrade.GRADE_3) == 12.0


# ──────────────────────────────────────────────────────────────────────
# 导线参数提取
# ──────────────────────────────────────────────────────────────────────

def test_get_traversing_grade_params_grade1():
    """一级导线生成参数结构正确"""
    cfg = load_traversing_config()
    ap, dp = get_traversing_grade_params(cfg, TraverseGrade.GRADE_1)
    assert ap["sigma_arcsec"] == 0.5
    assert ap["sigma_2c_arcsec"] == 3.0
    assert ap["sigma_set_arcsec"] == 2.0
    assert dp["sigma_mm"] == 0.5
    assert dp["sigma_reading_mm"] == 1.2
    assert dp["readings_per_set"] == 3


def test_get_traversing_grade_params_root():
    """图根导线生成参数结构正确 (含继承)"""
    cfg = load_traversing_config()
    ap, dp = get_traversing_grade_params(cfg, TraverseGrade.ROOT)
    assert ap["sigma_arcsec"] == 10.0
    assert ap["sigma_2c_arcsec"] == 15.0
    assert dp["sigma_mm"] == 10.0


def test_get_traversing_limits_grade1():
    """一级导线限差结构正确"""
    cfg = load_traversing_config()
    limits = get_traversing_limits(cfg, TraverseGrade.GRADE_1)
    direction = limits[AngleObservationMethod.DIRECTION]
    assert direction["2sec"]["direction_diff_across_sets_arcsec"] == 9.0
    assert direction["relative_closure_denominator"] == 15000

    measurement = limits[AngleObservationMethod.MEASUREMENT]
    assert measurement["2sec"]["half_set_diff_arcsec"] == 9.0


def test_get_degree_plate_offset_rad():
    """度盘零位偏移正确 (教学演示用: 0°, 后视读数精确为 0°/90°)"""
    cfg = load_observation_program_config()
    offset = get_degree_plate_offset_rad(cfg)
    assert abs(offset - math.radians(0.0 / 3600.0)) < 1e-6


# ──────────────────────────────────────────────────────────────────────
# 配置驱动生成器
# ──────────────────────────────────────────────────────────────────────

def test_custom_leveling_config_affects_generation():
    """传入自定义水准配置后, 生成器使用新参数"""
    route = RouteInfo("BM.A", 100.000, "BM.B", 101.500, 0.8)
    custom_cfg = {"grade_3": {"simulation": {
        "sight_distance_range_m": [20.0, 75.0],
        "distance_diff_range_m": [-3.0, 3.0],
        "reading_perturbation_sigma_mm": 5.0,
    }}}
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as f:
        json.dump(custom_cfg, f)
        cfg_path = f.name
    try:
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_3,
            num_stations=3, seed=42, config_path=cfg_path,
        )
        assert wb.generation_metadata.leveling_sigma_mm == 5.0
    finally:
        os.unlink(cfg_path)


def test_custom_traversing_config_affects_generation():
    """传入自定义导线配置后, 生成器使用新参数"""
    pts = [("A", 0.0, 0.0), ("B", 100.0, 0.0), ("C", 200.0, 0.0)]
    custom_cfg = {"grade_1": {"simulation": {
        "angle_perturbation_sigma_arcsec": 10.0,
        "distance_perturbation_sigma_mm": 10.0,
        "2c_perturbation_sigma_arcsec": 3.0,
        "set_perturbation_sigma_arcsec": 2.0,
        "distance_reading_sigma_mm": 1.2,
        "reading_diff_sigma_mm": 1.0,
    }}}
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as f:
        json.dump(custom_cfg, f)
        cfg_path = f.name
    try:
        wb = generate_traversing_workbook(
            points=pts, start_azimuth=0.0, end_azimuth=0.0,
            grade=TraverseGrade.GRADE_1, num_angle_sets=1,
            seed=42, config_path=cfg_path,
        )
        # angle_sigma_arcsec 已不再使用, 置为 None
        assert wb.generation_metadata.angle_sigma_arcsec is None
        assert wb.generation_metadata.angle_set_sigma_arcsec == 2.0
        assert wb.generation_metadata.distance_sigma_mm == 10.0
    finally:
        os.unlink(cfg_path)


def test_missing_config_falls_back_to_defaults():
    """配置文件缺失时, 生成器仍可用内置默认值运行"""
    route = RouteInfo("BM.A", 100.000, "BM.B", 101.500, 0.8)
    wb = generate_leveling_workbook(
        route=route, grade=LevelingGrade.GRADE_3,
        num_stations=3, seed=42,
        config_path="this_file_does_not_exist.json",
    )
    assert wb is not None
    assert len(wb.sections) == 1
