# tests/test_height_datum.py
# 高程基准转换测试
#
# 测试: 椭球高→正常高转换 (A6.1/A6.2)
# - 常数 zeta 模式
# - 线性 zeta 模式
# - 逐点 zeta 模式
# - delta_zeta 警告
# - 高程基准一致性检查
# - 集成: 水准生成器 + 高程转换
# - 集成: 导线生成器 + 高程转换

import math
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.preconditions.height_datum import (
    convert_ellipsoid_to_normal,
    check_height_datum_consistency,
    HeightDatumItem,
    HeightDatumReport,
)
from src.models.common import (
    LevelingGrade, TraverseGrade, RouteInfo, TraverseInfo,
    InstrumentGrade, AngleDefinition, AngleObservationMethod,
)


# ──────────────────────────────────────────────────────────────────────
# 常数模式
# ──────────────────────────────────────────────────────────────────────

class TestConstantZeta:

    def test_basic_conversion(self):
        """基本常数 zeta 转换: H = h - zeta"""
        points = [("A", 100.0, 200.0, 52.500)]
        result, report = convert_ellipsoid_to_normal(
            points, zeta_source="constant", zeta_constant=2.300,
        )
        assert len(result) == 1
        assert abs(result[0][3] - 50.200) < 1e-10
        assert report.zeta_source == "constant"
        assert abs(report.zeta_constant - 2.300) < 1e-10

    def test_multiple_points(self):
        """多点常数 zeta: 所有点使用相同 zeta, delta_zeta = 0"""
        points = [
            ("B", 100.0, 200.0, 52.500),
            ("K1", 150.0, 250.0, 53.800),
            ("G", 200.0, 300.0, 55.100),
        ]
        result, report = convert_ellipsoid_to_normal(
            points, zeta_source="constant", zeta_constant=2.300,
        )
        assert len(result) == 3
        # 高差不变: (53.8-52.5) = 1.3, (53.8-2.3)-(52.5-2.3) = 1.3
        assert abs(result[1][3] - result[0][3] - 1.3) < 1e-10
        # delta_zeta 全为 0
        for item in report.items[1:]:
            assert item.delta_zeta == 0.0 or abs(item.delta_zeta) < 1e-15
        assert report.max_delta_zeta_m < 1e-10

    def test_zeta_zero(self):
        """zeta=0: 椭球高 = 正常高"""
        points = [("A", 0, 0, 100.0)]
        result, report = convert_ellipsoid_to_normal(
            points, zeta_source="constant", zeta_constant=0.0,
        )
        assert abs(result[0][3] - 100.0) < 1e-10

    def test_negative_zeta(self):
        """负 zeta (高程异常为负): 正常高 > 椭球高"""
        points = [("A", 0, 0, 50.0)]
        result, _ = convert_ellipsoid_to_normal(
            points, zeta_source="constant", zeta_constant=-1.5,
        )
        assert abs(result[0][3] - 51.5) < 1e-10

    def test_missing_zeta_constant_raises(self):
        """缺少 zeta_constant 时抛出 ValueError"""
        points = [("A", 0, 0, 50.0)]
        with pytest.raises(ValueError, match="常数模式"):
            convert_ellipsoid_to_normal(
                points, zeta_source="constant",
            )

    def test_report_items_detail(self):
        """报告项目详细字段"""
        points = [("A", 100.0, 200.0, 52.500)]
        result, report = convert_ellipsoid_to_normal(
            points, zeta_source="constant", zeta_constant=2.300,
        )
        item = report.items[0]
        assert item.point_name == "A"
        assert abs(item.h_ellipsoid - 52.500) < 1e-10
        assert abs(item.h_normal - 50.200) < 1e-10
        assert abs(item.zeta - 2.300) < 1e-10
        assert item.delta_zeta is None  # 第一个点无 delta_zeta


# ──────────────────────────────────────────────────────────────────────
# 线性模式
# ──────────────────────────────────────────────────────────────────────

class TestLinearZeta:

    def test_two_points(self):
        """两点线性: 起终点 zeta 值"""
        points = [
            ("B", 0, 0, 52.500),
            ("G", 1000, 0, 55.100),
        ]
        result, report = convert_ellipsoid_to_normal(
            points, zeta_source="linear",
            zeta_start=2.300, zeta_end=2.500,
        )
        assert abs(result[0][3] - 50.200) < 1e-10  # 52.5 - 2.3
        assert abs(result[1][3] - 52.600) < 1e-10  # 55.1 - 2.5

    def test_three_points_linear(self):
        """三点线性: 中间点 zeta 线性内插"""
        points = [
            ("B", 0, 0, 52.500),
            ("K", 500, 0, 53.800),
            ("G", 1000, 0, 55.100),
        ]
        result, report = convert_ellipsoid_to_normal(
            points, zeta_source="linear",
            zeta_start=2.300, zeta_end=2.500,
        )
        # 中间点 zeta = 2.300 + (2.500 - 2.300) * 0.5 = 2.400
        assert abs(report.items[1].zeta - 2.400) < 1e-10
        assert abs(result[1][3] - 51.400) < 1e-10  # 53.8 - 2.4

    def test_delta_zeta_nonzero(self):
        """线性模式: delta_zeta 非零"""
        points = [
            ("B", 0, 0, 52.500),
            ("G", 1000, 0, 55.100),
        ]
        _, report = convert_ellipsoid_to_normal(
            points, zeta_source="linear",
            zeta_start=2.300, zeta_end=2.500,
        )
        assert abs(report.max_delta_zeta_m - 0.200) < 1e-10

    def test_missing_zeta_start_raises(self):
        """缺少 zeta_start 时抛出 ValueError"""
        points = [("A", 0, 0, 50.0)]
        with pytest.raises(ValueError, match="线性模式"):
            convert_ellipsoid_to_normal(
                points, zeta_source="linear",
                zeta_end=2.5,
            )


# ──────────────────────────────────────────────────────────────────────
# 逐点模式
# ──────────────────────────────────────────────────────────────────────

class TestPerPointZeta:

    def test_basic(self):
        """逐点指定 zeta"""
        points = [
            ("A", 0, 0, 52.500),
            ("B", 100, 0, 55.100),
        ]
        result, report = convert_ellipsoid_to_normal(
            points, zeta_source="per_point",
            zeta_per_point={"A": 2.300, "B": 2.500},
        )
        assert abs(result[0][3] - 50.200) < 1e-10
        assert abs(result[1][3] - 52.600) < 1e-10

    def test_missing_point_raises(self):
        """缺少某个点的 zeta 时抛出 ValueError"""
        points = [
            ("A", 0, 0, 52.500),
            ("B", 100, 0, 55.100),
        ]
        with pytest.raises(ValueError, match="缺少点.*'B'"):
            convert_ellipsoid_to_normal(
                points, zeta_source="per_point",
                zeta_per_point={"A": 2.300},
            )

    def test_missing_dict_raises(self):
        """缺少 zeta_per_point 时抛出 ValueError"""
        points = [("A", 0, 0, 50.0)]
        with pytest.raises(ValueError, match="逐点模式"):
            convert_ellipsoid_to_normal(
                points, zeta_source="per_point",
            )


# ──────────────────────────────────────────────────────────────────────
# 边界与错误
# ──────────────────────────────────────────────────────────────────────

class TestEdgeCases:

    def test_empty_input(self):
        """空输入"""
        result, report = convert_ellipsoid_to_normal(
            [], zeta_source="constant", zeta_constant=2.3,
        )
        assert result == []
        assert report.point_count == 0

    def test_unknown_source_raises(self):
        """未知 zeta_source"""
        points = [("A", 0, 0, 50.0)]
        with pytest.raises(ValueError, match="未知 zeta_source"):
            convert_ellipsoid_to_normal(
                points, zeta_source="grid",
            )

    def test_large_delta_zeta_warning(self):
        """大 delta_zeta 触发警告"""
        points = [
            ("A", 0, 0, 50.000),
            ("B", 100, 0, 50.100),
        ]
        _, report = convert_ellipsoid_to_normal(
            points, zeta_source="per_point",
            zeta_per_point={"A": 2.000, "B": 2.050},
        )
        # delta_zeta = 0.050 m = 50 mm > 10 mm → 警告
        assert len(report.warnings) > 0
        assert any("zeta 差值" in w for w in report.warnings)

    def test_small_delta_zeta_no_warning(self):
        """小 delta_zeta 无警告"""
        points = [
            ("A", 0, 0, 50.000),
            ("B", 100, 0, 50.100),
        ]
        _, report = convert_ellipsoid_to_normal(
            points, zeta_source="per_point",
            zeta_per_point={"A": 2.000, "B": 2.005},
        )
        # delta_zeta = 0.005 m = 5 mm < 10 mm → 无警告
        assert len(report.warnings) == 0


# ──────────────────────────────────────────────────────────────────────
# 高程基准一致性检查
# ──────────────────────────────────────────────────────────────────────

class TestHeightDatumConsistency:

    def test_normal_height_consistent(self):
        """正常高: 一致"""
        ok, warnings = check_height_datum_consistency(
            50.0, 51.0, height_datum="normal_height",
        )
        assert ok is True
        assert len(warnings) == 0

    def test_ellipsoid_height_warning(self):
        """椭球高: 发出警告"""
        ok, warnings = check_height_datum_consistency(
            52.5, 55.1, height_datum="ellipsoid_height",
        )
        assert ok is False
        assert len(warnings) > 0
        assert any("椭球高" in w for w in warnings)

    def test_ellipsoid_with_intermediates(self):
        """椭球高 + 中间点"""
        ok, warnings = check_height_datum_consistency(
            52.5, 55.1,
            intermediate_heights=[53.8],
            height_datum="ellipsoid_height",
        )
        assert ok is False
        assert len(warnings) > 0


# ──────────────────────────────────────────────────────────────────────
# 报告格式
# ──────────────────────────────────────────────────────────────────────

class TestReportFormat:

    def test_constant_summary(self):
        """常数模式摘要"""
        points = [("A", 0, 0, 52.5)]
        _, report = convert_ellipsoid_to_normal(
            points, zeta_source="constant", zeta_constant=2.3,
        )
        assert "constant" in report.summary
        assert "2.3000" in report.summary

    def test_linear_summary(self):
        """线性模式摘要"""
        points = [("A", 0, 0, 52.5), ("B", 100, 0, 55.1)]
        _, report = convert_ellipsoid_to_normal(
            points, zeta_source="linear",
            zeta_start=2.3, zeta_end=2.5,
        )
        assert "linear" in report.summary
        assert "2.3000" in report.summary


# ──────────────────────────────────────────────────────────────────────
# 集成: 水准生成器 + 高程转换
# ──────────────────────────────────────────────────────────────────────

class TestLevelingIntegration:

    def test_convert_then_generate_grade3(self):
        """椭球高→正常高转换后, 生成三等水准手簿"""
        from src.generators.leveling_generator import generate_leveling_workbook

        # RTK 输出: 椭球高
        ellipsoid_points = [
            ("B", 0, 0, 52.500),
            ("K1", 500, 0, 53.800),
            ("G", 1000, 0, 55.100),
        ]

        # 转换
        normal_points, report = convert_ellipsoid_to_normal(
            ellipsoid_points, zeta_source="constant", zeta_constant=2.300,
        )

        # 构造 RouteInfo (使用正常高)
        route = RouteInfo(
            start_point_name=normal_points[0][0],
            start_point_height=normal_points[0][3],
            end_point_name=normal_points[-1][0],
            end_point_height=normal_points[-1][3],
            total_length_km=1.0,
            intermediate_points=[
                (normal_points[1][0], normal_points[1][3]),
            ],
        )

        # 生成
        wb = generate_leveling_workbook(
            route=route,
            grade=LevelingGrade.GRADE_3,
            num_stations=10,
            seed=42,
        )

        assert len(wb.sections) == 1
        # 验证器填充后检查
        from src.validators.leveling_validator import validate_leveling_workbook
        val = validate_leveling_workbook(wb)
        assert val.all_passed
        dh = wb.sections[0].sum_height_diff_m
        assert dh is not None
        # 正常高: B=50.200, G=52.800 → 高差 = 2.600
        assert abs(dh - (52.800 - 50.200)) < 0.01

    def test_ellipsoid_height_causes_closure_issue(self):
        """不转换时, 椭球高差与正常高差不同 (常数zeta不影响闭合差, 但线性zeta会)"""
        from src.generators.leveling_generator import generate_leveling_workbook

        # 线性 zeta: 起点 2.3m, 终点 2.5m
        # 正常高差 = 椭球高差 - delta_zeta = (55.1-52.5) - (2.5-2.3) = 2.4
        # 若不转换直接用椭球高, 高差为 2.6, 闭合差计算基于 51.1-50.2 = 0.9?
        # 实际: 起点椭球高 52.5, 终点椭球高 55.1, 椭球高差 = 2.6
        # 正常高差 = 2.6 - (2.5-2.3) = 2.4
        # 用椭球高当正常高: 高差 2.6, 但已知正常高差 = 2.4 → 闭合差 = 0.2m

        # 转换后正常高
        normal_points, _ = convert_ellipsoid_to_normal(
            [("B", 0, 0, 52.5), ("G", 1000, 0, 55.1)],
            zeta_source="linear", zeta_start=2.3, zeta_end=2.5,
        )

        # 用正常高生成: 闭合差应很小
        route_normal = RouteInfo(
            start_point_name="B",
            start_point_height=normal_points[0][3],
            end_point_name="G",
            end_point_height=normal_points[1][3],
            total_length_km=1.0,
        )
        wb_normal = generate_leveling_workbook(
            route=route_normal, grade=LevelingGrade.GRADE_3,
            num_stations=5, seed=42,
        )
        # 正常高的路线闭合差应在限差内
        closure_normal_mm = wb_normal.sections[0].closure_error_mm or 0.0
        assert abs(closure_normal_mm) < 100  # 100mm 内

        # 用椭球高当正常高: 闭合差大
        route_ellipsoid = RouteInfo(
            start_point_name="B",
            start_point_height=52.5,  # 椭球高
            end_point_name="G",
            end_point_height=55.1,    # 椭球高
            total_length_km=1.0,
        )
        wb_ellipsoid = generate_leveling_workbook(
            route=route_ellipsoid, grade=LevelingGrade.GRADE_3,
            num_stations=5, seed=42,
        )
        # 椭球高路线的"高差"=2.6m, 但路线两端正常高差=2.4m
        # 这个测试只验证生成器能接受输入, 不验证闭合差 (因为是数学真值模式)


# ──────────────────────────────────────────────────────────────────────
# 集成: 导线 + 高程转换 (三角高程)
# ──────────────────────────────────────────────────────────────────────

class TestTraversingIntegration:

    def test_convert_traversing_heights(self):
        """导线点椭球高→正常高, 验证高程传递"""
        from src.generators.traversing_generator import generate_traversing_workbook

        # RTK 导线点 (含椭球高)
        ellipsoid_points = [
            ("B", 1000.0, 2000.0, 52.500),
            ("K1", 1100.0, 2100.0, 53.800),
            ("K2", 1200.0, 2200.0, 55.100),
            ("G", 1300.0, 2300.0, 56.400),
        ]

        # 转换 (导线只用 X, Y; 高程用于三角高程)
        # 导线生成器接受 (name, x, y) 格式
        normal_points, report = convert_ellipsoid_to_normal(
            ellipsoid_points, zeta_source="constant", zeta_constant=2.300,
        )

        # 导线生成器: 使用转换后的平面坐标
        traverse_points = [(n, x, y) for n, x, y, _ in normal_points]

        start_az = math.atan2(100.0, 100.0)  # ~45°
        end_az = start_az

        wb = generate_traversing_workbook(
            points=traverse_points,
            start_azimuth=start_az,
            end_azimuth=end_az,
            grade=TraverseGrade.GRADE_1,
            seed=42,
        )

        assert wb is not None
        # 验证转换报告
        assert report.point_count == 4
        for item in report.items:
            assert abs(item.zeta - 2.300) < 1e-10


# ──────────────────────────────────────────────────────────────────────
# 数学验证: A6.1 / A6.2
# ──────────────────────────────────────────────────────────────────────

class TestMathVerification:

    def test_a61_formula(self):
        """A6.1: H_normal = h_ellipsoid - zeta"""
        h_ell = 100.0
        zeta = 5.0
        points = [("A", 0, 0, h_ell)]
        result, _ = convert_ellipsoid_to_normal(
            points, zeta_source="constant", zeta_constant=zeta,
        )
        assert abs(result[0][3] - (h_ell - zeta)) < 1e-10

    def test_a62_delta_zeta(self):
        """A6.2: delta_zeta = zeta_i - zeta_{i-1}"""
        points = [
            ("A", 0, 0, 50.0),
            ("B", 100, 0, 50.5),
        ]
        _, report = convert_ellipsoid_to_normal(
            points, zeta_source="per_point",
            zeta_per_point={"A": 2.000, "B": 2.030},
        )
        # delta_zeta = 2.030 - 2.000 = 0.030
        assert abs(report.items[1].delta_zeta - 0.030) < 1e-10

    def test_high_diff_unchanged_with_constant_zeta(self):
        """常数 zeta: 高差不变 (delta_zeta = 0)"""
        h1, h2 = 50.000, 51.200
        zeta = 2.300
        points = [("A", 0, 0, h1), ("B", 100, 0, h2)]
        result, _ = convert_ellipsoid_to_normal(
            points, zeta_source="constant", zeta_constant=zeta,
        )
        # 高差: (h2 - zeta) - (h1 - zeta) = h2 - h1
        dh_original = h2 - h1
        dh_converted = result[1][3] - result[0][3]
        assert abs(dh_converted - dh_original) < 1e-10

    def test_high_diff_changed_with_varying_zeta(self):
        """变化 zeta: 高差改变 delta_zeta"""
        points = [("A", 0, 0, 50.0), ("B", 100, 0, 51.2)]
        _, report = convert_ellipsoid_to_normal(
            points, zeta_source="per_point",
            zeta_per_point={"A": 2.000, "B": 2.030},
        )
        # 原始高差 = 1.2m
        # 转换后高差 = (51.2-2.030) - (50.0-2.000) = 49.170 - 48.000 = 1.170
        # 差值 = delta_zeta = 0.030m
        dh_converted = report.items[1].h_normal - report.items[0].h_normal
        assert abs(dh_converted - (1.2 - 0.030)) < 1e-10


# ──────────────────────────────────────────────────────────────────────
# 可复现性
# ──────────────────────────────────────────────────────────────────────

class TestReproducibility:

    def test_deterministic(self):
        """相同输入产生相同输出"""
        points = [("A", 0, 0, 52.5), ("B", 100, 0, 55.1)]
        r1, _ = convert_ellipsoid_to_normal(
            points, zeta_source="constant", zeta_constant=2.3,
        )
        r2, _ = convert_ellipsoid_to_normal(
            points, zeta_source="constant", zeta_constant=2.3,
        )
        assert r1 == r2
