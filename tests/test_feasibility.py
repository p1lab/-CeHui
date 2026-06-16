# tests/test_feasibility.py
# 可行性预检测试
#
# 测试: 水准/导线可行性预检 (A7.1/A7.2)
# - 数学真值模式跳过
# - 不可行判定 (RTK 精度不足)
# - 可行判定 (自定义小 sigma)
# - 报告结构

import math
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.models.common import LevelingGrade, TraverseGrade
from src.preconditions.feasibility import (
    check_leveling_feasibility,
    check_traversing_feasibility,
    FeasibilityReport,
    FeasibilityItem,
    _compute_min_edge_length,
    _RHO,
)


# ──────────────────────────────────────────────────────────────────────
# 水准可行性预检
# ──────────────────────────────────────────────────────────────────────

class TestLevelingFeasibility:

    def test_math_true_mode_skipped(self):
        """数学真值模式: 预检跳过, skipped=True"""
        report = check_leveling_feasibility(
            LevelingGrade.GRADE_3,
            math_true_value_mode=True,
        )
        assert report.skipped is True
        assert report.feasible is True  # 跳过视为可行
        assert report.items == []
        assert "数学真值" in report.disclaimer

    def test_grade2_infeasible(self):
        """二等水准: sigma_dh ≈ 42.4mm >> 0.45mm, 不可行"""
        report = check_leveling_feasibility(
            LevelingGrade.GRADE_2,
            sigma_H_m=0.03,
            math_true_value_mode=False,
        )
        assert report.skipped is False
        assert report.feasible is False
        assert len(report.items) == 1
        assert report.items[0].passed is False
        # sigma_dh = sqrt(2) * 30mm ≈ 42.43mm
        assert abs(report.items[0].computed - 42.43) < 0.1
        # threshold = 0.15 * 3 = 0.45mm
        assert abs(report.items[0].threshold - 0.45) < 0.01
        assert len(report.warnings) > 0

    def test_grade3_infeasible(self):
        """三等水准: sigma_dh ≈ 42.4mm >> 5.7mm, 不可行"""
        report = check_leveling_feasibility(
            LevelingGrade.GRADE_3,
            sigma_H_m=0.03,
            math_true_value_mode=False,
        )
        assert report.feasible is False
        assert report.items[0].passed is False

    def test_extra_infeasible(self):
        """等外水准: sigma_dh ≈ 42.4mm >> 18.9mm, 不可行"""
        report = check_leveling_feasibility(
            LevelingGrade.EXTRA,
            sigma_H_m=0.03,
            math_true_value_mode=False,
        )
        assert report.feasible is False
        # threshold = 6.3 * 3 = 18.9mm, sigma_dh = 42.4mm > 18.9
        assert report.items[0].computed > report.items[0].threshold

    def test_feasible_with_small_sigma(self):
        """极小 sigma_H → 可行"""
        # sigma_dh = sqrt(2) * 0.0001m * 1000 = 0.141mm < 0.45mm
        report = check_leveling_feasibility(
            LevelingGrade.GRADE_2,
            sigma_H_m=0.0001,  # 0.1mm
            math_true_value_mode=False,
        )
        assert report.feasible is True
        assert report.items[0].passed is True
        assert len(report.warnings) == 0

    def test_feasible_extra_large_sigma(self):
        """等外: sigma_H=1mm → sigma_dh=1.41mm < 18.9mm, 可行"""
        report = check_leveling_feasibility(
            LevelingGrade.EXTRA,
            sigma_H_m=0.001,  # 1mm
            math_true_value_mode=False,
        )
        assert report.feasible is True

    def test_custom_threshold_multiplier(self):
        """自定义阈值倍数"""
        report = check_leveling_feasibility(
            LevelingGrade.EXTRA,
            sigma_H_m=0.03,
            threshold_multiplier=1.0,  # 更严格
            math_true_value_mode=False,
        )
        # threshold = 6.3 * 1.0 = 6.3mm (比默认的18.9mm更严格)
        assert abs(report.items[0].threshold - 6.3) < 0.01

    def test_disclaimer_present_when_skipped(self):
        """跳过时声明包含关键信息"""
        report = check_leveling_feasibility(
            LevelingGrade.GRADE_3,
            math_true_value_mode=True,
        )
        assert "数学真值" in report.disclaimer
        assert "不代表" in report.disclaimer

    def test_report_summary_skipped(self):
        """跳过时 summary 文本"""
        report = check_leveling_feasibility(
            LevelingGrade.GRADE_3,
            math_true_value_mode=True,
        )
        summary = report.summary
        assert "跳过" in summary
        assert "leveling" in summary


# ──────────────────────────────────────────────────────────────────────
# 导线可行性预检
# ──────────────────────────────────────────────────────────────────────

class TestTraversingFeasibility:

    def _make_points(self, spacing_m=200.0):
        """生成等间距点序列."""
        return [
            ("A", 0.0, 0.0),
            ("P1", spacing_m, 0.0),
            ("P2", 2 * spacing_m, 0.0),
            ("B", 3 * spacing_m, 0.0),
        ]

    def test_math_true_mode_skipped(self):
        """数学真值模式: 预检跳过"""
        pts = self._make_points()
        report = check_traversing_feasibility(
            TraverseGrade.GRADE_1,
            points=pts,
            math_true_value_mode=True,
        )
        assert report.skipped is True
        assert report.feasible is True
        assert "数学真值" in report.disclaimer

    def test_grade1_infeasible(self):
        """一级导线 D=200m: sigma_alpha ≈ 20.6" >> 15", 不可行"""
        pts = self._make_points(200.0)
        report = check_traversing_feasibility(
            TraverseGrade.GRADE_1,
            points=pts,
            math_true_value_mode=False,
        )
        assert report.feasible is False
        assert report.items[0].passed is False
        # sigma_alpha = (0.02/200) * rho ≈ 20.6"
        assert abs(report.items[0].computed - 20.63) < 0.1
        # threshold = 5 * 3 = 15"
        assert abs(report.items[0].threshold - 15.0) < 0.01

    def test_grade2_infeasible(self):
        """二级导线 D=200m: sigma_alpha ≈ 20.6" >> 30" → 可行 (恰好)"""
        pts = self._make_points(200.0)
        report = check_traversing_feasibility(
            TraverseGrade.GRADE_2,
            points=pts,
            math_true_value_mode=False,
        )
        # sigma_alpha ≈ 20.6", threshold = 10 * 3 = 30" → 可行
        assert report.feasible is True

    def test_root_feasible_long_side(self):
        """图根导线 D=500m: sigma_alpha ≈ 8.3" < 75", 可行"""
        pts = self._make_points(500.0)
        report = check_traversing_feasibility(
            TraverseGrade.ROOT,
            points=pts,
            math_true_value_mode=False,
        )
        assert report.feasible is True
        assert report.items[0].passed is True
        assert len(report.warnings) == 0

    def test_grade1_infeasible_short_side(self):
        """一级导线 D=50m: sigma_alpha ≈ 82.5" >> 15", 不可行"""
        pts = self._make_points(50.0)
        report = check_traversing_feasibility(
            TraverseGrade.GRADE_1,
            points=pts,
            math_true_value_mode=False,
        )
        assert report.feasible is False
        # sigma_alpha = (0.02/50) * rho ≈ 82.5"
        assert report.items[0].computed > 80.0

    def test_explicit_min_edge(self):
        """显式提供 min_edge_m, 不使用 points"""
        report = check_traversing_feasibility(
            TraverseGrade.GRADE_1,
            min_edge_m=100.0,
            math_true_value_mode=False,
        )
        assert report.feasible is False
        # sigma_alpha = (0.02/100) * rho ≈ 41.3"
        assert abs(report.items[0].computed - 41.25) < 0.1

    def test_no_points_no_min_edge(self):
        """未提供 points 和 min_edge_m → 警告"""
        report = check_traversing_feasibility(
            TraverseGrade.GRADE_1,
            math_true_value_mode=False,
        )
        assert report.feasible is False
        assert len(report.warnings) > 0
        assert "最短边长" in report.warnings[0]

    def test_d_min_computed_from_points(self):
        """从坐标自动计算最短边"""
        pts = [
            ("A", 0.0, 0.0),
            ("P1", 300.0, 0.0),    # 边1: 300m
            ("P2", 350.0, 0.0),    # 边2: 50m (最短)
            ("B", 650.0, 0.0),     # 边3: 300m
        ]
        report = check_traversing_feasibility(
            TraverseGrade.GRADE_1,
            points=pts,
            math_true_value_mode=False,
        )
        # D_min = 50m, sigma_alpha = (0.02/50) * rho ≈ 82.5"
        assert report.items[0].computed > 80.0

    def test_disclaimer_when_skipped(self):
        """跳过时声明存在"""
        pts = self._make_points()
        report = check_traversing_feasibility(
            TraverseGrade.GRADE_1,
            points=pts,
            math_true_value_mode=True,
        )
        assert "数学真值" in report.disclaimer
        assert "不代表" in report.disclaimer

    def test_report_summary_not_skipped(self):
        """非跳过时 summary 包含可行性结论"""
        pts = self._make_points(200.0)
        report = check_traversing_feasibility(
            TraverseGrade.GRADE_1,
            points=pts,
            math_true_value_mode=False,
        )
        summary = report.summary
        assert "不可行" in summary
        assert "traversing" in summary


# ──────────────────────────────────────────────────────────────────────
# 辅助函数
# ──────────────────────────────────────────────────────────────────────

class TestComputeMinEdge:

    def test_basic(self):
        pts = [("A", 0, 0), ("B", 100, 0), ("C", 250, 0)]
        assert _compute_min_edge_length(pts) == pytest.approx(100.0)

    def test_single_point(self):
        assert _compute_min_edge_length([("A", 0, 0)]) is None

    def test_empty(self):
        assert _compute_min_edge_length([]) is None

    def test_diagonal(self):
        pts = [("A", 0, 0), ("B", 3, 4)]
        assert _compute_min_edge_length(pts) == pytest.approx(5.0)


# ──────────────────────────────────────────────────────────────────────
# 报告结构
# ──────────────────────────────────────────────────────────────────────

class TestFeasibilityReportStructure:

    def test_report_fields(self):
        report = check_leveling_feasibility(
            LevelingGrade.GRADE_3,
            math_true_value_mode=True,
        )
        assert hasattr(report, 'items')
        assert hasattr(report, 'survey_type')
        assert hasattr(report, 'target_grade')
        assert hasattr(report, 'feasible')
        assert hasattr(report, 'skipped')
        assert hasattr(report, 'disclaimer')
        assert hasattr(report, 'warnings')
        assert hasattr(report, 'summary')

    def test_item_fields(self):
        report = check_leveling_feasibility(
            LevelingGrade.GRADE_3,
            math_true_value_mode=False,
        )
        item = report.items[0]
        assert hasattr(item, 'name')
        assert hasattr(item, 'computed')
        assert hasattr(item, 'threshold')
        assert hasattr(item, 'passed')
        assert hasattr(item, 'message')

    def test_survey_type_leveling(self):
        report = check_leveling_feasibility(
            LevelingGrade.GRADE_3,
            math_true_value_mode=True,
        )
        assert report.survey_type == "leveling"
        assert report.target_grade == "grade_3"

    def test_survey_type_traversing(self):
        report = check_traversing_feasibility(
            TraverseGrade.GRADE_1,
            min_edge_m=100.0,
            math_true_value_mode=True,
        )
        assert report.survey_type == "traversing"
        assert report.target_grade == "grade_1"
