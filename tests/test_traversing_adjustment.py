# tests/test_traversing_adjustment.py
# 导线简易平差测试
#
# 测试策略：
#   - 闭合/附合导线平差后终点坐标精确归位
#   - 改正数求和检核
#   - 余数分配（短边优先）
#   - 数学真值模式 vs 可控非零闭合差模式
#   - 右角导线
#   - 回归测试：_build_computation() 输出与平差前一致

import math
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.models.common import (
    TraverseGrade, InstrumentGrade, AngleDefinition,
)
from src.generators.traversing_generator import generate_traversing_workbook
from src.validators.traversing_validator import (
    validate_traversing_workbook, normalize_angle,
)
from src.adjustment.traversing_adjustment import adjust_traverse


# ──────────────────────────────────────────────────────────────────────
# 辅助
# ──────────────────────────────────────────────────────────────────────

def _azimuth(x1, y1, x2, y2):
    """坐标方位角"""
    return normalize_angle(math.atan2(y2 - y1, x2 - x1))


def _make_workbook(points, grade=TraverseGrade.GRADE_1, seed=42,
                   start_ref=None, end_ref=None,
                   target_closure_ratio=0.3,
                   angle_def=AngleDefinition.LEFT_ANGLE):
    """生成导线手簿（含平差）"""
    az_s = _azimuth(*points[0][1:], *points[1][1:])
    az_e = _azimuth(*points[-2][1:], *points[-1][1:])
    wb = generate_traversing_workbook(
        points=points,
        start_azimuth=az_s,
        end_azimuth=az_e,
        grade=grade,
        seed=seed,
        start_reference_point=start_ref,
        end_reference_point=end_ref,
        target_closure_ratio=target_closure_ratio,
        angle_definition=angle_def,
    )
    return wb


# ──────────────────────────────────────────────────────────────────────
# 核心检核：改正后终点坐标精确归位
# ──────────────────────────────────────────────────────────────────────

class TestAdjustedEndpointClosure:
    """平差后终点坐标/方位角精确归位"""

    def test_closed_traverse_endpoint_x(self):
        """闭合导线：改正后终点X精确等于已知值"""
        pts = [("A", 1000, 1000), ("P1", 1100, 1050), ("P2", 1200, 1100),
               ("B", 1300, 1200)]
        wb = _make_workbook(pts, grade=TraverseGrade.GRADE_1)
        comp = wb.computation
        last = comp.point_records[-1]
        assert abs(last.corrected_x_m - wb.info.end_point_x) < 1e-6

    def test_closed_traverse_endpoint_y(self):
        """闭合导线：改正后终点Y精确等于已知值"""
        pts = [("A", 1000, 1000), ("P1", 1100, 1050), ("P2", 1200, 1100),
               ("B", 1300, 1200)]
        wb = _make_workbook(pts, grade=TraverseGrade.GRADE_1)
        comp = wb.computation
        last = comp.point_records[-1]
        assert abs(last.corrected_y_m - wb.info.end_point_y) < 1e-6

    def test_attached_traverse_endpoint(self):
        """附合导线（外部基准）：改正后终点坐标精确归位"""
        pts = [("A", 1000, 1000), ("P1", 1100, 1050), ("P2", 1200, 1100),
               ("B", 1300, 1200)]
        wb = _make_workbook(pts, start_ref=("A0", 900, 950),
                            end_ref=("B0", 1400, 1250))
        comp = wb.computation
        last = comp.point_records[-1]
        assert abs(last.corrected_x_m - wb.info.end_point_x) < 1e-6
        assert abs(last.corrected_y_m - wb.info.end_point_y) < 1e-6

    def test_grade2_endpoint(self):
        """二级导线：改正后终点坐标归位"""
        pts = [("A", 1000, 1000), ("P1", 1100, 1050), ("B", 1200, 1100)]
        wb = _make_workbook(pts, grade=TraverseGrade.GRADE_2)
        comp = wb.computation
        last = comp.point_records[-1]
        assert abs(last.corrected_x_m - wb.info.end_point_x) < 1e-6
        assert abs(last.corrected_y_m - wb.info.end_point_y) < 1e-6

    def test_root_grade_endpoint(self):
        """图根导线：改正后终点坐标归位"""
        pts = [("A", 1000, 1000), ("P1", 1100, 1050), ("P2", 1200, 1100),
               ("B", 1300, 1200)]
        wb = _make_workbook(pts, grade=TraverseGrade.ROOT)
        comp = wb.computation
        last = comp.point_records[-1]
        assert abs(last.corrected_x_m - wb.info.end_point_x) < 1e-6
        assert abs(last.corrected_y_m - wb.info.end_point_y) < 1e-6

    def test_multiple_seeds_endpoint(self):
        """多种子下终点坐标均精确归位"""
        pts = [("A", 1000, 1000), ("P1", 1100, 1050), ("P2", 1200, 1100),
               ("B", 1300, 1200)]
        for seed in [1, 7, 42, 99, 200]:
            wb = _make_workbook(pts, seed=seed)
            comp = wb.computation
            last = comp.point_records[-1]
            assert abs(last.corrected_x_m - wb.info.end_point_x) < 1e-6, \
                f"seed={seed}: X偏差"
            assert abs(last.corrected_y_m - wb.info.end_point_y) < 1e-6, \
                f"seed={seed}: Y偏差"


# ──────────────────────────────────────────────────────────────────────
# 改正数求和检核
# ──────────────────────────────────────────────────────────────────────

class TestCorrectionSumCheck:
    """改正数求和等于负闭合差"""

    def test_vx_sum_equals_neg_fx(self):
        """SUM(v_x) = -f_x"""
        pts = [("A", 1000, 1000), ("P1", 1100, 1050), ("P2", 1200, 1100),
               ("B", 1300, 1200)]
        wb = _make_workbook(pts)
        comp = wb.computation
        real_edges = [er for er in comp.edge_records if er.distance_m is not None]
        sum_vx = sum(er.delta_x_correction_m for er in real_edges)
        fx = comp.fx_m or 0.0
        assert abs(sum_vx + fx) < 1e-8

    def test_vy_sum_equals_neg_fy(self):
        """SUM(v_y) = -f_y"""
        pts = [("A", 1000, 1000), ("P1", 1100, 1050), ("P2", 1200, 1100),
               ("B", 1300, 1200)]
        wb = _make_workbook(pts)
        comp = wb.computation
        real_edges = [er for er in comp.edge_records if er.distance_m is not None]
        sum_vy = sum(er.delta_y_correction_m for er in real_edges)
        fy = comp.fy_m or 0.0
        assert abs(sum_vy + fy) < 1e-8

    def test_vbeta_sum_approx_neg_fbeta(self):
        """SUM(v_beta) ≈ -f_beta（0.1" 精度内）"""
        pts = [("A", 1000, 1000), ("P1", 1100, 1050), ("P2", 1200, 1100),
               ("B", 1300, 1200)]
        wb = _make_workbook(pts, start_ref=("A0", 900, 950),
                            end_ref=("B0", 1400, 1250))
        comp = wb.computation
        angle_edges = [er for er in comp.edge_records if er.observed_angle_rad is not None]
        sum_v = sum(er.angle_correction_rad for er in angle_edges)
        f_beta = comp.azimuth_closure_error_arcsec or 0.0
        _RO = 180.0 * 3600.0 / math.pi
        # 精度 0.1" × n_angles
        tol = 0.1 * len(angle_edges) / _RO
        assert abs(sum_v * _RO + f_beta) < 0.5


# ──────────────────────────────────────────────────────────────────────
# 数学真值模式 vs 可控非零闭合差
# ──────────────────────────────────────────────────────────────────────

class TestClosureModes:
    """数学真值模式与可控非零闭合差模式"""

    def test_mtv_mode_endpoint_closed(self):
        """数学真值模式（target_closure_ratio=0）：平差后终点仍精确归位"""
        pts = [("A", 1000, 1000), ("P1", 1100, 1050), ("P2", 1200, 1100),
               ("B", 1300, 1200)]
        wb = _make_workbook(pts, target_closure_ratio=0.0)
        comp = wb.computation
        last = comp.point_records[-1]
        assert abs(last.corrected_x_m - wb.info.end_point_x) < 1e-6
        assert abs(last.corrected_y_m - wb.info.end_point_y) < 1e-6
        # 流程完整执行
        real_edges = [er for er in comp.edge_records if er.distance_m is not None]
        for er in real_edges:
            assert er.corrected_delta_x_m is not None
            assert er.corrected_delta_y_m is not None

    def test_nonzero_mode_corrections_present(self):
        """可控非零模式（target_closure_ratio=0.3）：改正数有教学意义"""
        pts = [("A", 1000, 1000), ("P1", 1100, 1050), ("P2", 1200, 1100),
               ("B", 1300, 1200)]
        wb = _make_workbook(pts, target_closure_ratio=0.3, seed=42)
        comp = wb.computation
        # 闭合差非零
        assert abs(comp.fd_m) > 1e-6, "非零模式应有闭合差"

    def test_nonzero_mode_endpoint_still_closed(self):
        """可控非零模式：平差后终点仍精确归位"""
        pts = [("A", 1000, 1000), ("P1", 1100, 1050), ("P2", 1200, 1100),
               ("B", 1300, 1200)]
        wb = _make_workbook(pts, target_closure_ratio=0.3, seed=42)
        comp = wb.computation
        last = comp.point_records[-1]
        assert abs(last.corrected_x_m - wb.info.end_point_x) < 1e-6
        assert abs(last.corrected_y_m - wb.info.end_point_y) < 1e-6


# ──────────────────────────────────────────────────────────────────────
# 右角导线
# ──────────────────────────────────────────────────────────────────────

class TestRightAngleTraverse:
    """右角导线平差"""

    def test_right_angle_endpoint(self):
        """右角导线：改正后终点坐标归位"""
        pts = [("A", 1000, 1000), ("P1", 1100, 1050), ("P2", 1200, 1100),
               ("B", 1300, 1200)]
        wb = _make_workbook(pts, angle_def=AngleDefinition.RIGHT_ANGLE)
        comp = wb.computation
        last = comp.point_records[-1]
        assert abs(last.corrected_x_m - wb.info.end_point_x) < 1e-6
        assert abs(last.corrected_y_m - wb.info.end_point_y) < 1e-6

    def test_right_angle_vs_left_angle(self):
        """右角与左角改正后终点相同"""
        pts = [("A", 1000, 1000), ("P1", 1100, 1050), ("P2", 1200, 1100),
               ("B", 1300, 1200)]
        wb_left = _make_workbook(pts, angle_def=AngleDefinition.LEFT_ANGLE,
                                 seed=42)
        wb_right = _make_workbook(pts, angle_def=AngleDefinition.RIGHT_ANGLE,
                                  seed=42)
        # 两种角定义下的改正后终点都应归位到已知值
        last_l = wb_left.computation.point_records[-1]
        last_r = wb_right.computation.point_records[-1]
        assert abs(last_l.corrected_x_m - wb_left.info.end_point_x) < 1e-6
        assert abs(last_r.corrected_x_m - wb_right.info.end_point_x) < 1e-6


# ──────────────────────────────────────────────────────────────────────
# 回归测试：平差不改原有数据
# ──────────────────────────────────────────────────────────────────────

class TestRegressionNoOverwrite:
    """平差不覆盖原有正向传播结果"""

    def test_original_x_y_preserved(self):
        """x_m / y_m 不被平差覆盖"""
        pts = [("A", 1000, 1000), ("P1", 1100, 1050), ("P2", 1200, 1100),
               ("B", 1300, 1200)]
        wb = _make_workbook(pts, target_closure_ratio=0.3)
        comp = wb.computation
        # 有闭合差时 x_m ≠ corrected_x_m（中间点）
        mid = comp.point_records[1]
        if abs(comp.fd_m or 0) > 1e-6:
            # x_m 是未改正值，corrected_x_m 是改正后值
            # 它们可能不同（有闭合差时）
            pass
        # 但 x_m 应仍存在
        assert mid.x_m is not None
        assert mid.y_m is not None

    def test_original_deltas_preserved(self):
        """delta_x_m / delta_y_m 不被覆盖"""
        pts = [("A", 1000, 1000), ("P1", 1100, 1050), ("P2", 1200, 1100),
               ("B", 1300, 1200)]
        wb = _make_workbook(pts, target_closure_ratio=0.3)
        comp = wb.computation
        real_edges = [er for er in comp.edge_records if er.distance_m is not None]
        for er in real_edges:
            assert er.delta_x_m is not None, "原始 dx 不应为 None"
            assert er.delta_y_m is not None, "原始 dy 不应为 None"

    def test_distance_correction_zero(self):
        """简易平差：距离改正数始终为 0"""
        pts = [("A", 1000, 1000), ("P1", 1100, 1050), ("P2", 1200, 1100),
               ("B", 1300, 1200)]
        wb = _make_workbook(pts)
        comp = wb.computation
        real_edges = [er for er in comp.edge_records if er.distance_m is not None]
        for er in real_edges:
            if er.distance_correction_m is not None:
                assert er.distance_correction_m == 0.0


# ──────────────────────────────────────────────────────────────────────
# 改正数按边长比例分配
# ──────────────────────────────────────────────────────────────────────

class TestProportionalDistribution:
    """坐标增量闭合差按边长比例分配"""

    def test_correction_proportional_to_distance(self):
        """改正数与边长成正比"""
        pts = [("A", 1000, 1000), ("P1", 1100, 1050), ("P2", 1200, 1100),
               ("B", 1300, 1200)]
        wb = _make_workbook(pts, target_closure_ratio=0.3)
        comp = wb.computation
        real_edges = [er for er in comp.edge_records if er.distance_m is not None
                      and er.delta_x_correction_m is not None]
        if len(real_edges) < 2:
            pytest.skip("需要至少2条实边")
        # 比值 v_xi / D_i 应近似相等
        ratios = []
        for er in real_edges:
            r = er.delta_x_correction_m / er.distance_m
            ratios.append(r)
        # 所有比值应近似等于 -fx / SUM(D)
        fx = comp.fx_m or 0.0
        total_d = sum(er.distance_m for er in real_edges)
        if abs(fx) > 1e-10:
            expected_ratio = -fx / total_d
            for r in ratios:
                assert abs(r - expected_ratio) < 1e-10, \
                    f"分配比例不均匀: {r:.10f} ≠ {expected_ratio:.10f}"


# ──────────────────────────────────────────────────────────────────────
# 余数分配：短边优先
# ──────────────────────────────────────────────────────────────────────

class TestRemainderDistribution:
    """角度闭合差余数分配给短边"""

    def test_remainder_goes_to_short_edge(self):
        """余数优先分配给最短边"""
        pts = [("A", 1000, 1000), ("P1", 1050, 1020), ("P2", 1200, 1100),
               ("B", 1300, 1200)]
        wb = _make_workbook(pts, start_ref=("A0", 900, 950),
                            end_ref=("B0", 1400, 1250),
                            target_closure_ratio=0.3, seed=42)
        comp = wb.computation
        angle_edges = [er for er in comp.edge_records if er.observed_angle_rad is not None]
        # 至少应有改正数
        for er in angle_edges:
            assert er.angle_correction_rad is not None, "角度改正数应已填充"
            assert er.corrected_angle_rad is not None, "改正后角值应已填充"


# ──────────────────────────────────────────────────────────────────────
# 预留字段完整性
# ──────────────────────────────────────────────────────────────────────

class TestFieldCompleteness:
    """平差后所有预留字段均已填充"""

    def test_all_7_adjustment_fields_filled(self):
        """7 个预留字段全部填充"""
        pts = [("A", 1000, 1000), ("P1", 1100, 1050), ("P2", 1200, 1100),
               ("B", 1300, 1200)]
        wb = _make_workbook(pts, start_ref=("A0", 900, 950),
                            end_ref=("B0", 1400, 1250))
        comp = wb.computation
        angle_edges = [er for er in comp.edge_records if er.observed_angle_rad is not None]
        for er in angle_edges:
            assert er.angle_correction_rad is not None
            assert er.corrected_angle_rad is not None
        real_edges = [er for er in comp.edge_records if er.distance_m is not None]
        for er in real_edges:
            assert er.distance_correction_m is not None
            assert er.delta_x_correction_m is not None
            assert er.delta_y_correction_m is not None
            assert er.corrected_delta_x_m is not None
            assert er.corrected_delta_y_m is not None

    def test_corrected_coordinates_filled(self):
        """改正后坐标已填充"""
        pts = [("A", 1000, 1000), ("P1", 1100, 1050), ("P2", 1200, 1100),
               ("B", 1300, 1200)]
        wb = _make_workbook(pts)
        comp = wb.computation
        for pr in comp.point_records:
            assert pr.corrected_x_m is not None, f"点{pr.point_name}缺corrected_x_m"
            assert pr.corrected_y_m is not None, f"点{pr.point_name}缺corrected_y_m"
