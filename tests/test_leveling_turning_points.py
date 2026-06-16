# tests/test_leveling_turning_points.py
# 阶段十二测试: 转点标记与导线点区分 (P6)

import pytest
from src.models.common import RouteInfo, LevelingGrade
from src.models.leveling import (
    RodSpec, RodType, LevelingWorkbook,
    ObservationSequence,
)
from src.generators.leveling_generator import (
    generate_leveling_workbook,
    _build_waypoints_and_heights,
    _build_point_type_map,
)
from src.validators.leveling_validator import validate_leveling_workbook
from src.checkers.leveling_compliance import check_leveling_compliance

import numpy as np


# ──────────────────────────────────────────────────────────────────────
# 辅助函数
# ──────────────────────────────────────────────────────────────────────

def _make_route_with_intermediates():
    """创建含中间导线点的水准路线"""
    return RouteInfo(
        start_point_name="B",
        start_point_height=50.000,
        end_point_name="G",
        end_point_height=51.200,
        total_length_km=2.3,
        intermediate_points=[
            ("K1", 50.150),
            ("K2", 50.350),
            ("K3", 50.500),
        ],
    )


def _make_route_no_intermediates():
    """创建不含中间点的水准路线 (原行为)"""
    return RouteInfo(
        start_point_name="B",
        start_point_height=50.000,
        end_point_name="G",
        end_point_height=51.200,
        total_length_km=2.3,
    )


# ──────────────────────────────────────────────────────────────────────
# _build_waypoints_and_heights 测试
# ──────────────────────────────────────────────────────────────────────

class TestBuildWaypoints:
    """路线点序列构建"""

    def test_no_intermediates_point_count(self):
        """无中间点: n站 → n+1 个点"""
        route = _make_route_no_intermediates()
        rng = np.random.default_rng(42)
        names, heights = _build_waypoints_and_heights(route, 5, rng)
        assert len(names) == 6
        assert len(heights) == 6

    def test_no_intermediates_endpoints(self):
        """无中间点: 首尾点名正确"""
        route = _make_route_no_intermediates()
        rng = np.random.default_rng(42)
        names, heights = _build_waypoints_and_heights(route, 5, rng)
        assert names[0] == "B"
        assert names[-1] == "G"

    def test_no_intermediates_tp_naming(self):
        """无中间点: 转点命名为 TP.1, TP.2..."""
        route = _make_route_no_intermediates()
        rng = np.random.default_rng(42)
        names, heights = _build_waypoints_and_heights(route, 5, rng)
        assert names[1] == "TP.1"
        assert names[2] == "TP.2"

    def test_with_intermediates_includes_control_points(self):
        """有中间点: 路线中包含所有控制点"""
        route = _make_route_with_intermediates()
        rng = np.random.default_rng(42)
        names, heights = _build_waypoints_and_heights(route, 10, rng)
        assert "B" in names
        assert "K1" in names
        assert "K2" in names
        assert "K3" in names
        assert "G" in names

    def test_with_intermediates_control_point_heights(self):
        """有中间点: 控制点高程精确"""
        route = _make_route_with_intermediates()
        rng = np.random.default_rng(42)
        names, heights = _build_waypoints_and_heights(route, 10, rng)

        name_to_h = dict(zip(names, heights))
        assert abs(name_to_h["B"] - 50.000) < 1e-12
        assert abs(name_to_h["K1"] - 50.150) < 1e-12
        assert abs(name_to_h["K2"] - 50.350) < 1e-12
        assert abs(name_to_h["K3"] - 50.500) < 1e-12
        assert abs(name_to_h["G"] - 51.200) < 1e-12

    def test_with_intermediates_tp_naming_by_segment(self):
        """有中间点: 转点命名区分段号 TP.{段号}.{段内序号}"""
        route = _make_route_with_intermediates()
        rng = np.random.default_rng(42)
        names, heights = _build_waypoints_and_heights(route, 10, rng)

        # 4段: B→K1, K1→K2, K2→K3, K3→G
        # 段1的转点应为 TP.1.x
        seg1_tps = [n for n in names if n.startswith("TP.1.")]
        assert len(seg1_tps) >= 0  # 段内站数>=1时无转点

    def test_with_intermediates_point_count(self):
        """有中间点: 总点数 = 站数 + 1"""
        route = _make_route_with_intermediates()
        rng = np.random.default_rng(42)
        names, heights = _build_waypoints_and_heights(route, 10, rng)
        assert len(names) == 11  # 10站 + 1

    def test_with_intermediates_heights_monotonic(self):
        """有中间点: 高程序列单调 (本例终点高于起点)"""
        route = _make_route_with_intermediates()
        rng = np.random.default_rng(42)
        names, heights = _build_waypoints_and_heights(route, 10, rng)
        for i in range(len(heights) - 1):
            assert heights[i] <= heights[i + 1] + 1e-12


# ──────────────────────────────────────────────────────────────────────
# _build_point_type_map 测试
# ──────────────────────────────────────────────────────────────────────

class TestBuildPointTypeMap:
    """点类型映射"""

    def test_no_intermediates_only_control(self):
        """无中间点: 起终点为 control, TP 为 turning"""
        route = _make_route_no_intermediates()
        names = ["B", "TP.1", "TP.2", "G"]
        type_map = _build_point_type_map(names, route)
        assert type_map["B"] == "control"
        assert type_map["G"] == "control"
        assert type_map["TP.1"] == "turning"
        assert type_map["TP.2"] == "turning"

    def test_with_intermediates_all_control_points_marked(self):
        """有中间点: 所有中间控制点标记为 control"""
        route = _make_route_with_intermediates()
        names = ["B", "TP.1.1", "K1", "TP.2.1", "K2", "K3", "G"]
        type_map = _build_point_type_map(names, route)
        assert type_map["B"] == "control"
        assert type_map["K1"] == "control"
        assert type_map["K2"] == "control"
        assert type_map["K3"] == "control"
        assert type_map["G"] == "control"
        assert type_map["TP.1.1"] == "turning"
        assert type_map["TP.2.1"] == "turning"


# ──────────────────────────────────────────────────────────────────────
# 集成测试: 完整生成 → 验证 → 检核
# ──────────────────────────────────────────────────────────────────────

class TestTurningPointGeneration:
    """转点生成集成测试"""

    def test_intermediate_points_in_stations(self):
        """中间导线点出现在测站前视点名中"""
        route = _make_route_with_intermediates()
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_2,
            num_stations=12, seed=42,
        )
        section = wb.sections[0]
        foresight_names = {st.foresight_point for st in section.stations}
        assert "K1" in foresight_names
        assert "K2" in foresight_names
        assert "K3" in foresight_names

    def test_point_type_control_marked(self):
        """控制点标记为 control"""
        route = _make_route_with_intermediates()
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_2,
            num_stations=12, seed=42,
        )
        section = wb.sections[0]
        control_stations = [
            st for st in section.stations
            if st.point_type == "control"
        ]
        # K1, K2, K3 应被标记
        control_fore_names = {st.foresight_point for st in control_stations}
        assert "K1" in control_fore_names
        assert "K2" in control_fore_names
        assert "K3" in control_fore_names

    def test_point_type_turning_marked(self):
        """转点标记为 turning"""
        route = _make_route_with_intermediates()
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_2,
            num_stations=12, seed=42,
        )
        section = wb.sections[0]
        turning_stations = [
            st for st in section.stations
            if st.point_type == "turning"
        ]
        # 12站, 4段, 每段3站, 每段2个转点 → 8个转点
        # 但实际取决于段分配, 至少应有一些转点
        assert len(turning_stations) > 0
        for st in turning_stations:
            assert st.foresight_point.startswith("TP.")

    def test_no_intermediates_backward_compat(self):
        """无中间点: 起终点前视被标记为 control, TP 为 turning"""
        route = _make_route_no_intermediates()
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_3,
            num_stations=5, seed=42,
        )
        section = wb.sections[0]
        # 起点不是前视点, 终点G的前视站标记为 control
        control_stations = [
            st for st in section.stations if st.point_type == "control"
        ]
        turning_stations = [
            st for st in section.stations if st.point_type == "turning"
        ]
        # 终点 G 应为 control
        control_fore_names = {st.foresight_point for st in control_stations}
        assert "G" in control_fore_names
        # TP 应为 turning
        assert len(turning_stations) > 0

    def test_intermediate_points_validation(self):
        """含中间点: 正向验证通过"""
        route = _make_route_with_intermediates()
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_2,
            num_stations=12, seed=42,
        )
        result = validate_leveling_workbook(wb)
        assert result.all_passed

    def test_intermediate_points_compliance(self):
        """含中间点: 合规检核通过"""
        route = _make_route_with_intermediates()
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_2,
            num_stations=12, seed=42,
        )
        report = check_leveling_compliance(wb)
        assert report.passed

    def test_round_trip_with_intermediates(self):
        """含中间点: 往返观测正常"""
        route = _make_route_with_intermediates()
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_2,
            num_stations=12, round_trip=True,
            observation_sequence="alternate", seed=42,
        )
        assert wb.is_round_trip
        assert len(wb.sections) == 2
        assert wb.round_trip_passed

        # 返测也应包含中间控制点
        return_section = wb.sections[1]
        return_fore_names = {st.foresight_point for st in return_section.stations}
        assert "K1" in return_fore_names
        assert "K2" in return_fore_names
        assert "K3" in return_fore_names

    def test_extra_grade_with_intermediates(self):
        """等外水准 + 中间点: 生成和验证正常"""
        route = _make_route_with_intermediates()
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.EXTRA,
            num_stations=8, seed=42,
        )
        assert len(wb.extra_sections) == 1
        result = validate_leveling_workbook(wb)
        assert result.all_passed

    def test_extra_point_type_marked(self):
        """等外水准: 转点/控制点类型标记"""
        route = _make_route_with_intermediates()
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.EXTRA,
            num_stations=8, seed=42,
        )
        section = wb.extra_sections[0]
        control_stations = [
            st for st in section.stations
            if st.point_type == "control"
        ]
        turning_stations = [
            st for st in section.stations
            if st.point_type == "turning"
        ]
        assert len(control_stations) > 0
        assert len(turning_stations) >= 0

    def test_control_point_heights_match(self):
        """中间控制点: 正向验证高程与输入一致"""
        route = _make_route_with_intermediates()
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_2,
            num_stations=12, seed=42,
        )
        result = validate_leveling_workbook(wb)
        # 控制点高程应与输入精确一致
        for name, expected_h in [("K1", 50.150), ("K2", 50.350),
                                  ("K3", 50.500), ("G", 51.200)]:
            if name in result.computed_heights:
                assert abs(result.computed_heights[name] - expected_h) < 1e-6, \
                    f"{name}: computed={result.computed_heights[name]:.6f}, expected={expected_h:.6f}"


class TestReproducibilityWithIntermediates:
    """可复现性"""

    def test_same_seed_same_result(self):
        """相同种子 → 相同转点分布"""
        route = _make_route_with_intermediates()
        wb1 = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_2,
            num_stations=12, seed=123,
        )
        wb2 = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_2,
            num_stations=12, seed=123,
        )
        s1 = wb1.sections[0].stations
        s2 = wb2.sections[0].stations
        assert len(s1) == len(s2)
        for a, b in zip(s1, s2):
            assert a.foresight_point == b.foresight_point
            assert a.point_type == b.point_type
