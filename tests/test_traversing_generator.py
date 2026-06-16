# tests/test_traversing_generator.py
# 导线逆向生成器端到端测试
#
# 测试策略: 生成 → 正向验证 → 全通过
# 重点: 坐标闭合差, 方位角闭合差, 核空间约束

import math
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.models.common import (
    TraverseGrade, InstrumentGrade, AngleDefinition, SurveyMetadata,
)
from src.generators.traversing_generator import generate_traversing_workbook
from src.validators.traversing_validator import (
    validate_traversing_workbook, normalize_angle,
)


# ──────────────────────────────────────────────────────────────────────
# 辅助
# ──────────────────────────────────────────────────────────────────────

def _run_and_validate(workbook):
    """运行正向验证器, 打印失败项"""
    result = validate_traversing_workbook(workbook)
    if not result.all_passed:
        for c in result.checks:
            if not c.passed:
                print(f"  FAIL: {c.name}: {c.message}")
        for e in result.errors:
            print(f"  ERROR: {e}")
    return result


def _azimuth(x1, y1, x2, y2):
    """坐标方位角"""
    return normalize_angle(math.atan2(y2 - y1, x2 - x1))


# ──────────────────────────────────────────────────────────────────────
# 一级导线 (2 测回)
# ──────────────────────────────────────────────────────────────────────

class TestGrade1Traverse:
    """一级导线: 2 测回, 2" 级仪器"""

    def _make_points(self):
        return [
            ("A", 1000.0, 1000.0),
            ("P1", 1100.0, 1050.0),
            ("P2", 1200.0, 1100.0),
            ("B", 1300.0, 1200.0),
        ]

    def test_basic_traverse(self):
        """基本附合导线: A → P1 → P2 → B"""
        pts = self._make_points()
        az_start = _azimuth(1000, 1000, 1100, 1050)
        az_end = _azimuth(1200, 1100, 1300, 1200)

        wb = generate_traversing_workbook(
            points=pts,
            start_azimuth=az_start,
            end_azimuth=az_end,
            grade=TraverseGrade.GRADE_1,
            num_angle_sets=2,
            seed=42,
        )
        result = _run_and_validate(wb)
        assert result.all_passed, "一级导线验证未通过"

    def test_coordinate_closure(self):
        """终点坐标精确等于真值"""
        pts = self._make_points()
        az_start = _azimuth(1000, 1000, 1100, 1050)
        az_end = _azimuth(1200, 1100, 1300, 1200)

        wb = generate_traversing_workbook(
            points=pts,
            start_azimuth=az_start,
            end_azimuth=az_end,
            grade=TraverseGrade.GRADE_1,
            num_angle_sets=2,
            seed=42,
        )
        result = _run_and_validate(wb)

        # 终点坐标
        end_coords = result.computed_coordinates.get("B")
        assert end_coords is not None
        assert abs(end_coords[0] - 1300.0) < 0.01, \
            f"X 偏差: {end_coords[0] - 1300.0:.4f} m"
        assert abs(end_coords[1] - 1200.0) < 0.01, \
            f"Y 偏差: {end_coords[1] - 1200.0:.4f} m"

    def test_azimuth_closure(self):
        """方位角闭合差 ≈ 0"""
        pts = self._make_points()
        az_start = _azimuth(1000, 1000, 1100, 1050)
        az_end = _azimuth(1200, 1100, 1300, 1200)

        wb = generate_traversing_workbook(
            points=pts,
            start_azimuth=az_start,
            end_azimuth=az_end,
            grade=TraverseGrade.GRADE_1,
            num_angle_sets=2,
            seed=42,
        )
        comp = wb.computation
        assert comp is not None
        # 方位角闭合差
        if comp.azimuth_closure_error_arcsec is not None:
            assert abs(comp.azimuth_closure_error_arcsec) < 1.0, \
                f"方位角闭合差: {comp.azimuth_closure_error_arcsec:.3f}\""


# ──────────────────────────────────────────────────────────────────────
# 二级导线 (1 测回)
# ──────────────────────────────────────────────────────────────────────

class TestGrade2Traverse:
    """二级导线: 1 测回"""

    def test_basic(self):
        pts = [
            ("K1", 500.0, 500.0),
            ("T1", 600.0, 550.0),
            ("T2", 700.0, 500.0),
            ("K2", 800.0, 600.0),
        ]
        az_start = _azimuth(500, 500, 600, 550)
        az_end = _azimuth(700, 500, 800, 600)

        wb = generate_traversing_workbook(
            points=pts,
            start_azimuth=az_start,
            end_azimuth=az_end,
            grade=TraverseGrade.GRADE_2,
            num_angle_sets=1,
            seed=77,
        )
        result = _run_and_validate(wb)
        assert result.all_passed, "二级导线验证未通过"


# ──────────────────────────────────────────────────────────────────────
# 图根导线
# ──────────────────────────────────────────────────────────────────────

class TestRootTraverse:
    """图根导线: 1 测回, 大 sigma"""

    def test_basic(self):
        pts = [
            ("G1", 0.0, 0.0),
            ("R1", 50.0, 30.0),
            ("R2", 100.0, 10.0),
            ("G2", 150.0, 50.0),
        ]
        az_start = _azimuth(0, 0, 50, 30)
        az_end = _azimuth(100, 10, 150, 50)

        wb = generate_traversing_workbook(
            points=pts,
            start_azimuth=az_start,
            end_azimuth=az_end,
            grade=TraverseGrade.ROOT,
            num_angle_sets=1,
            seed=123,
        )
        result = _run_and_validate(wb)
        assert result.all_passed, "图根导线验证未通过"


# ──────────────────────────────────────────────────────────────────────
# 右角定义
# ──────────────────────────────────────────────────────────────────────

class TestRightAngle:
    """右角定义"""

    def test_right_angle_traverse(self):
        pts = [
            ("A", 1000.0, 1000.0),
            ("P1", 1100.0, 1050.0),
            ("B", 1200.0, 1100.0),
        ]
        az_start = _azimuth(1000, 1000, 1100, 1050)
        az_end = _azimuth(1100, 1050, 1200, 1100)

        wb = generate_traversing_workbook(
            points=pts,
            start_azimuth=az_start,
            end_azimuth=az_end,
            grade=TraverseGrade.GRADE_1,
            num_angle_sets=2,
            angle_definition=AngleDefinition.RIGHT_ANGLE,
            seed=42,
        )
        result = _run_and_validate(wb)
        assert result.all_passed, "右角导线验证未通过"


# ──────────────────────────────────────────────────────────────────────
# 可复现性
# ──────────────────────────────────────────────────────────────────────

class TestReproducibility:

    def test_same_seed(self):
        pts = [
            ("A", 1000.0, 1000.0),
            ("P1", 1100.0, 1050.0),
            ("B", 1200.0, 1100.0),
        ]
        az_start = _azimuth(1000, 1000, 1100, 1050)
        az_end = _azimuth(1100, 1050, 1200, 1100)

        wb1 = generate_traversing_workbook(
            points=pts, start_azimuth=az_start, end_azimuth=az_end,
            grade=TraverseGrade.GRADE_1, seed=42,
        )
        wb2 = generate_traversing_workbook(
            points=pts, start_azimuth=az_start, end_azimuth=az_end,
            grade=TraverseGrade.GRADE_1, seed=42,
        )

        # 比较第一个测回的第一个方向读数
        r1 = wb1.angle_observations[0].sets[0].directions[0].reading_rad
        r2 = wb2.angle_observations[0].sets[0].directions[0].reading_rad
        assert r1 == r2

    def test_different_seed(self):
        pts = [
            ("A", 1000.0, 1000.0),
            ("P1", 1100.0, 1050.0),
            ("B", 1200.0, 1100.0),
        ]
        az_start = _azimuth(1000, 1000, 1100, 1050)
        az_end = _azimuth(1100, 1050, 1200, 1100)

        wb1 = generate_traversing_workbook(
            points=pts, start_azimuth=az_start, end_azimuth=az_end,
            grade=TraverseGrade.GRADE_1, seed=42,
        )
        wb2 = generate_traversing_workbook(
            points=pts, start_azimuth=az_start, end_azimuth=az_end,
            grade=TraverseGrade.GRADE_1, seed=99,
        )

        r1 = wb1.angle_observations[0].sets[0].directions[0].reading_rad
        r2 = wb2.angle_observations[0].sets[0].directions[0].reading_rad
        assert r1 != r2


# ──────────────────────────────────────────────────────────────────────
# 生成元数据
# ──────────────────────────────────────────────────────────────────────

class TestMetadata:

    def test_generation_metadata(self):
        pts = [("A", 0, 0), ("P1", 100, 50), ("B", 200, 100)]
        az_s = _azimuth(0, 0, 100, 50)
        az_e = _azimuth(100, 50, 200, 100)

        wb = generate_traversing_workbook(
            points=pts, start_azimuth=az_s, end_azimuth=az_e,
            grade=TraverseGrade.GRADE_1, seed=42,
        )
        gm = wb.generation_metadata
        assert gm is not None
        assert gm.target_grade == "grade_1"
        assert gm.random_seed == 42
        assert gm.angle_sigma_arcsec == 0.5
        assert gm.distance_sigma_mm == 0.5


# ──────────────────────────────────────────────────────────────────────
# 阶段十：测距多测回 + 高度参数化
# ──────────────────────────────────────────────────────────────────────

class TestDistanceMultipleSets:
    """测距多测回生成与验证"""

    def test_default_2_distance_sets(self):
        """默认应生成 2 个测回"""
        pts = [("A", 1000, 1000), ("P1", 1100, 1050), ("B", 1200, 1100)]
        az_s = _azimuth(1000, 1000, 1100, 1050)
        az_e = _azimuth(1100, 1050, 1200, 1100)
        wb = generate_traversing_workbook(
            points=pts, start_azimuth=az_s, end_azimuth=az_e,
            grade=TraverseGrade.GRADE_1, seed=42,
        )
        for edge in wb.distance_observations:
            assert len(edge.forward_sets) == 2, f"往测应有2测回, 实际{len(edge.forward_sets)}"
            assert len(edge.backward_sets) == 2, f"返测应有2测回, 实际{len(edge.backward_sets)}"

    def test_custom_1_distance_set(self):
        """指定1测回应生成1测回"""
        pts = [("A", 1000, 1000), ("P1", 1100, 1050), ("B", 1200, 1100)]
        az_s = _azimuth(1000, 1000, 1100, 1050)
        az_e = _azimuth(1100, 1050, 1200, 1100)
        wb = generate_traversing_workbook(
            points=pts, start_azimuth=az_s, end_azimuth=az_e,
            grade=TraverseGrade.GRADE_1, num_distance_sets=1, seed=42,
        )
        for edge in wb.distance_observations:
            assert len(edge.forward_sets) == 1
            assert len(edge.backward_sets) == 1

    def test_3_distance_sets(self):
        """3测回"""
        pts = [("A", 1000, 1000), ("P1", 1100, 1050), ("B", 1200, 1100)]
        az_s = _azimuth(1000, 1000, 1100, 1050)
        az_e = _azimuth(1100, 1050, 1200, 1100)
        wb = generate_traversing_workbook(
            points=pts, start_azimuth=az_s, end_azimuth=az_e,
            grade=TraverseGrade.GRADE_1, num_distance_sets=3, seed=42,
        )
        for edge in wb.distance_observations:
            assert len(edge.forward_sets) == 3
            assert len(edge.backward_sets) == 3

    def test_multi_set_compliance(self):
        """多测回数据应通过合规检核"""
        from src.checkers.traversing_compliance import check_traversing_compliance
        pts = [("A", 1000, 1000), ("P1", 1100, 1050), ("B", 1200, 1100)]
        az_s = _azimuth(1000, 1000, 1100, 1050)
        az_e = _azimuth(1100, 1050, 1200, 1100)
        wb = generate_traversing_workbook(
            points=pts, start_azimuth=az_s, end_azimuth=az_e,
            grade=TraverseGrade.GRADE_1, num_distance_sets=2, seed=42,
        )
        report = check_traversing_compliance(wb)
        assert report.passed, "多测回应通过合规检核"


class TestInstrumentPrismHeights:
    """仪器高/棱镜高参数化"""

    def test_default_heights(self):
        """默认仪器高1.50m, 棱镜高1.20m"""
        pts = [("A", 1000, 1000), ("P1", 1100, 1050), ("B", 1200, 1100)]
        az_s = _azimuth(1000, 1000, 1100, 1050)
        az_e = _azimuth(1100, 1050, 1200, 1100)
        wb = generate_traversing_workbook(
            points=pts, start_azimuth=az_s, end_azimuth=az_e,
            grade=TraverseGrade.GRADE_1, seed=42,
        )
        for edge in wb.distance_observations:
            assert edge.instrument_height_m == 1.50
            assert edge.prism_height_m == 1.20

    def test_custom_default_heights(self):
        """自定义默认高度"""
        pts = [("A", 1000, 1000), ("P1", 1100, 1050), ("B", 1200, 1100)]
        az_s = _azimuth(1000, 1000, 1100, 1050)
        az_e = _azimuth(1100, 1050, 1200, 1100)
        wb = generate_traversing_workbook(
            points=pts, start_azimuth=az_s, end_azimuth=az_e,
            grade=TraverseGrade.GRADE_1,
            default_instrument_height_m=1.65,
            default_prism_height_m=1.30,
            seed=42,
        )
        for edge in wb.distance_observations:
            assert edge.instrument_height_m == 1.65
            assert edge.prism_height_m == 1.30

    def test_per_point_heights(self):
        """按点名指定不同高度"""
        pts = [("A", 1000, 1000), ("P1", 1100, 1050), ("B", 1200, 1100)]
        az_s = _azimuth(1000, 1000, 1100, 1050)
        az_e = _azimuth(1100, 1050, 1200, 1100)
        wb = generate_traversing_workbook(
            points=pts, start_azimuth=az_s, end_azimuth=az_e,
            grade=TraverseGrade.GRADE_1,
            instrument_heights={"A": 1.55, "P1": 1.60},
            prism_heights={"A": 1.25, "P1": 1.35},
            seed=42,
        )
        # A→P1 边: from_point=A, 应使用 A 的高度
        edge_ap = [e for e in wb.distance_observations if e.from_point == "A"][0]
        assert edge_ap.instrument_height_m == 1.55
        assert edge_ap.prism_height_m == 1.25

        # P1→B 边: from_point=P1, 应使用 P1 的高度
        edge_pb = [e for e in wb.distance_observations if e.from_point == "P1"][0]
        assert edge_pb.instrument_height_m == 1.60
        assert edge_pb.prism_height_m == 1.35

    def test_per_point_heights_with_default_fallback(self):
        """指定部分点高度, 其余回退到默认"""
        pts = [("A", 1000, 1000), ("P1", 1100, 1050), ("B", 1200, 1100)]
        az_s = _azimuth(1000, 1000, 1100, 1050)
        az_e = _azimuth(1100, 1050, 1200, 1100)
        wb = generate_traversing_workbook(
            points=pts, start_azimuth=az_s, end_azimuth=az_e,
            grade=TraverseGrade.GRADE_1,
            instrument_heights={"P1": 1.60},
            default_instrument_height_m=1.50,
            default_prism_height_m=1.20,
            seed=42,
        )
        edge_ap = [e for e in wb.distance_observations if e.from_point == "A"][0]
        assert edge_ap.instrument_height_m == 1.50  # 回退到默认

        edge_pb = [e for e in wb.distance_observations if e.from_point == "P1"][0]
        assert edge_pb.instrument_height_m == 1.60  # 使用指定值
