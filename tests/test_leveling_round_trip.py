# tests/test_leveling_round_trip.py
# 阶段十一：水准往返观测 + 奇偶站观测顺序交替
#
# P0 核心缺口修复验证

import math
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.models.common import LevelingGrade, RouteInfo, SurveyMetadata
from src.models.leveling import (
    RodSpec, ObservationSequence, LevelingWorkbook,
)
from src.generators.leveling_generator import generate_leveling_workbook
from src.validators.leveling_validator import validate_leveling_workbook
from src.checkers.leveling_compliance import check_leveling_compliance


# ──────────────────────────────────────────────────────────────────────
# 辅助
# ──────────────────────────────────────────────────────────────────────

def _grade2_route():
    return RouteInfo("B", 50.000, "G", 51.200, total_length_km=2.3)


def _grade2_rods():
    return (
        RodSpec("No.1", RodType.INVAR_BASIC_AUX, c_aux_m=3.0155),
        RodSpec("No.2", RodType.INVAR_BASIC_AUX, c_aux_m=3.0155),
    )


# 需要导入 RodType
from src.models.common import RodType


# ──────────────────────────────────────────────────────────────────────
# 往返观测基础
# ──────────────────────────────────────────────────────────────────────

class TestRoundTripBasic:
    """往返观测基本生成与验证"""

    def test_round_trip_creates_two_sections(self):
        """往返观测应生成两个测段"""
        route = _grade2_route()
        rod_back, rod_fore = _grade2_rods()
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_2,
            num_stations=21,
            rod_back=rod_back, rod_fore=rod_fore,
            round_trip=True, observation_sequence="alternate",
            seed=42,
        )
        assert wb.is_round_trip
        assert len(wb.sections) == 2

    def test_single_trip_has_one_section(self):
        """非往返观测只有1个测段"""
        route = _grade2_route()
        rod_back, rod_fore = _grade2_rods()
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_2,
            num_stations=21,
            rod_back=rod_back, rod_fore=rod_fore,
            round_trip=False, seed=42,
        )
        assert not wb.is_round_trip
        assert len(wb.sections) == 1

    def test_round_trip_discrepancy_populated(self):
        """往返测高差不符值应被计算"""
        route = _grade2_route()
        rod_back, rod_fore = _grade2_rods()
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_2,
            num_stations=21,
            rod_back=rod_back, rod_fore=rod_fore,
            round_trip=True, observation_sequence="alternate",
            seed=42,
        )
        assert wb.round_trip_discrepancy_mm is not None
        assert wb.round_trip_discrepancy_mm >= 0
        assert wb.round_trip_limit_mm is not None
        assert wb.round_trip_limit_mm > 0

    def test_round_trip_passes(self):
        """往返测不符值应在限差内"""
        route = _grade2_route()
        rod_back, rod_fore = _grade2_rods()
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_2,
            num_stations=21,
            rod_back=rod_back, rod_fore=rod_fore,
            round_trip=True, observation_sequence="alternate",
            seed=42,
        )
        assert wb.round_trip_passed is True

    def test_round_trip_limit_formula(self):
        """限差应为 4√L mm"""
        route = _grade2_route()
        rod_back, rod_fore = _grade2_rods()
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_2,
            num_stations=21,
            rod_back=rod_back, rod_fore=rod_fore,
            round_trip=True, observation_sequence="alternate",
            seed=42,
        )
        expected_limit = 4.0 * math.sqrt(2.3)
        assert abs(wb.round_trip_limit_mm - expected_limit) < 0.01

    def test_round_trip_directions_opposite(self):
        """往测和返测路线方向应相反"""
        route = _grade2_route()
        rod_back, rod_fore = _grade2_rods()
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_2,
            num_stations=21,
            rod_back=rod_back, rod_fore=rod_fore,
            round_trip=True, observation_sequence="alternate",
            seed=42,
        )
        # 往测: B → G
        assert wb.sections[0].route.start_point_name == "B"
        assert wb.sections[0].route.end_point_name == "G"
        # 返测: G → B
        assert wb.sections[1].route.start_point_name == "G"
        assert wb.sections[1].route.end_point_name == "B"


class TestRoundTripValidation:
    """往返观测正向验证"""

    def test_round_trip_validation_passes(self):
        """往返观测应通过正向验证"""
        route = _grade2_route()
        rod_back, rod_fore = _grade2_rods()
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_2,
            num_stations=21,
            rod_back=rod_back, rod_fore=rod_fore,
            round_trip=True, observation_sequence="alternate",
            seed=42,
        )
        result = validate_leveling_workbook(wb)
        assert result.all_passed, f"验证失败: {[c.message for c in result.checks if not c.passed]}"

    def test_round_trip_has_discrepancy_check(self):
        """验证结果应包含往返测不符值检核"""
        route = _grade2_route()
        rod_back, rod_fore = _grade2_rods()
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_2,
            num_stations=21,
            rod_back=rod_back, rod_fore=rod_fore,
            round_trip=True, observation_sequence="alternate",
            seed=42,
        )
        result = validate_leveling_workbook(wb)
        discrepancy_checks = [c for c in result.checks if "往返" in c.name]
        assert len(discrepancy_checks) >= 1


class TestRoundTripCompliance:
    """往返观测合规检核"""

    def test_round_trip_compliance_passes(self):
        """往返观测应通过合规检核"""
        route = _grade2_route()
        rod_back, rod_fore = _grade2_rods()
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_2,
            num_stations=8,
            rod_back=rod_back, rod_fore=rod_fore,
            round_trip=True, observation_sequence="alternate",
            seed=42,
        )
        report = check_leveling_compliance(wb)
        assert report.passed, f"合规失败: {[i.message for i in report.items if not i.passed]}"

    def test_round_trip_has_discrepancy_item(self):
        """合规报告应包含往返测不符值检核项"""
        route = _grade2_route()
        rod_back, rod_fore = _grade2_rods()
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_2,
            num_stations=21,
            rod_back=rod_back, rod_fore=rod_fore,
            round_trip=True, observation_sequence="alternate",
            seed=42,
        )
        report = check_leveling_compliance(wb)
        discrepancy_items = [i for i in report.items if "往返" in i.name]
        assert len(discrepancy_items) >= 1


# ──────────────────────────────────────────────────────────────────────
# 奇偶站观测顺序交替
# ──────────────────────────────────────────────────────────────────────

class TestObservationSequenceAlternate:
    """奇偶站观测顺序交替"""

    def test_outbound_odd_station_back_fore_fore_back(self):
        """往测奇数站应为后前前后"""
        route = _grade2_route()
        rod_back, rod_fore = _grade2_rods()
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_2,
            num_stations=4,
            rod_back=rod_back, rod_fore=rod_fore,
            round_trip=True, observation_sequence="alternate",
            seed=42,
        )
        outbound = wb.sections[0]
        # 站1(奇) = 后前前后
        assert outbound.stations[0].observation_sequence == ObservationSequence.BACK_FORE_FORE_BACK
        # 站3(奇) = 后前前后
        assert outbound.stations[2].observation_sequence == ObservationSequence.BACK_FORE_FORE_BACK

    def test_outbound_even_station_fore_back_back_fore(self):
        """往测偶数站应为前后后前"""
        route = _grade2_route()
        rod_back, rod_fore = _grade2_rods()
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_2,
            num_stations=4,
            rod_back=rod_back, rod_fore=rod_fore,
            round_trip=True, observation_sequence="alternate",
            seed=42,
        )
        outbound = wb.sections[0]
        # 站2(偶) = 前后后前
        assert outbound.stations[1].observation_sequence == ObservationSequence.FORE_BACK_BACK_FORE
        # 站4(偶) = 前后后前
        assert outbound.stations[3].observation_sequence == ObservationSequence.FORE_BACK_BACK_FORE

    def test_return_odd_station_fore_back_back_fore(self):
        """返测奇数站应为前后后前 (与往测相反)"""
        route = _grade2_route()
        rod_back, rod_fore = _grade2_rods()
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_2,
            num_stations=4,
            rod_back=rod_back, rod_fore=rod_fore,
            round_trip=True, observation_sequence="alternate",
            seed=42,
        )
        inbound = wb.sections[1]
        # 返测站1(奇) = 前后后前
        assert inbound.stations[0].observation_sequence == ObservationSequence.FORE_BACK_BACK_FORE

    def test_return_even_station_back_fore_fore_back(self):
        """返测偶数站应为后前前后 (与往测相反)"""
        route = _grade2_route()
        rod_back, rod_fore = _grade2_rods()
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_2,
            num_stations=4,
            rod_back=rod_back, rod_fore=rod_fore,
            round_trip=True, observation_sequence="alternate",
            seed=42,
        )
        inbound = wb.sections[1]
        # 返测站2(偶) = 后前前后
        assert inbound.stations[1].observation_sequence == ObservationSequence.BACK_FORE_FORE_BACK

    def test_uniform_sequence_all_back_fore_fore_back(self):
        """uniform模式下所有站都为后前前后"""
        route = _grade2_route()
        rod_back, rod_fore = _grade2_rods()
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_2,
            num_stations=4,
            rod_back=rod_back, rod_fore=rod_fore,
            round_trip=True, observation_sequence="uniform",
            seed=42,
        )
        for section in wb.sections:
            for station in section.stations:
                assert station.observation_sequence == ObservationSequence.BACK_FORE_FORE_BACK

    def test_no_round_trip_no_sequence(self):
        """非往返但指定alternate时仍有观测顺序"""
        route = _grade2_route()
        rod_back, rod_fore = _grade2_rods()
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_2,
            num_stations=4,
            rod_back=rod_back, rod_fore=rod_fore,
            round_trip=False, observation_sequence="uniform",
            seed=42,
        )
        # uniform 模式下所有站都是后前前后
        for station in wb.sections[0].stations:
            assert station.observation_sequence == ObservationSequence.BACK_FORE_FORE_BACK


# ──────────────────────────────────────────────────────────────────────
# 三等水准往返（非因瓦尺也支持往返）
# ──────────────────────────────────────────────────────────────────────

class TestRoundTripGrade3:
    """三等水准往返观测"""

    def test_grade3_round_trip(self):
        route = RouteInfo("BM1", 100.000, "BM2", 101.500, total_length_km=1.5)
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_3,
            num_stations=10, round_trip=True,
            observation_sequence="alternate", seed=42,
        )
        assert wb.is_round_trip
        assert len(wb.sections) == 2
        # 三等水准限差也是 4√L（统一公式）
        assert wb.round_trip_limit_mm is not None


# ──────────────────────────────────────────────────────────────────────
# 等外水准不生成往返
# ──────────────────────────────────────────────────────────────────────

class TestRoundTripExtra:
    """等外水准不支持往返观测"""

    def test_extra_no_round_trip(self):
        route = RouteInfo("E1", 50.0, "E2", 51.0, total_length_km=0.5)
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.EXTRA,
            num_stations=5, round_trip=True, seed=42,
        )
        # 等外不支持往返，is_round_trip 应为 False
        assert not wb.is_round_trip


# ──────────────────────────────────────────────────────────────────────
# 阶段十八：往返测真实性改进
# ──────────────────────────────────────────────────────────────────────

class TestRoundTripRealism:
    """往返测不符值非零且在限差内"""

    def test_default_zero_discrepancy(self):
        """默认 target_round_trip_ratio=0 时, 不符值应接近零"""
        route = _grade2_route()
        rod_back, rod_fore = _grade2_rods()
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_2,
            num_stations=8,
            rod_back=rod_back, rod_fore=rod_fore,
            round_trip=True, observation_sequence="alternate",
            seed=42,
        )
        assert wb.round_trip_discrepancy_mm is not None
        assert wb.round_trip_discrepancy_mm < 0.01  # 浮点残余, 几乎为零

    def test_nonzero_discrepancy_with_ratio(self):
        """target_round_trip_ratio > 0 时, 不符值应非零"""
        route = _grade2_route()
        rod_back, rod_fore = _grade2_rods()
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_2,
            num_stations=8,
            rod_back=rod_back, rod_fore=rod_fore,
            round_trip=True, observation_sequence="alternate",
            target_round_trip_ratio=0.5,
            seed=42,
        )
        assert wb.round_trip_discrepancy_mm is not None
        assert wb.round_trip_discrepancy_mm > 0.1  # 明显非零

    def test_discrepancy_within_limit(self):
        """往返不符值应在限差内"""
        route = _grade2_route()
        rod_back, rod_fore = _grade2_rods()
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_2,
            num_stations=8,
            rod_back=rod_back, rod_fore=rod_fore,
            round_trip=True, observation_sequence="alternate",
            target_round_trip_ratio=0.5,
            seed=42,
        )
        assert wb.round_trip_passed is True

    def test_discrepancy_approximately_target(self):
        """不符值应约为 target_round_trip_ratio × 限差"""
        route = _grade2_route()
        rod_back, rod_fore = _grade2_rods()
        for ratio in [0.3, 0.5, 0.7]:
            wb = generate_leveling_workbook(
                route=route, grade=LevelingGrade.GRADE_2,
                num_stations=8,
                rod_back=rod_back, rod_fore=rod_fore,
                round_trip=True, observation_sequence="alternate",
                target_round_trip_ratio=ratio,
                seed=42,
            )
            expected_mm = ratio * wb.round_trip_limit_mm
            # 允许 20% 相对误差 (取整影响)
            rel_err = abs(wb.round_trip_discrepancy_mm - expected_mm) / expected_mm
            assert rel_err < 0.20, (
                f"ratio={ratio}: discrepancy={wb.round_trip_discrepancy_mm:.3f} mm, "
                f"expected≈{expected_mm:.3f} mm, rel_err={rel_err:.2%}"
            )

    def test_round_trip_realism_validation(self):
        """往返测真实性数据应通过正向验证"""
        route = _grade2_route()
        rod_back, rod_fore = _grade2_rods()
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_2,
            num_stations=8,
            rod_back=rod_back, rod_fore=rod_fore,
            round_trip=True, observation_sequence="alternate",
            target_round_trip_ratio=0.5,
            seed=42,
        )
        result = validate_leveling_workbook(wb)
        assert result.all_passed, f"验证失败: {[c.message for c in result.checks if not c.passed]}"

    def test_round_trip_realism_compliance(self):
        """往返测真实性数据应通过合规检核"""
        route = _grade2_route()
        rod_back, rod_fore = _grade2_rods()
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_2,
            num_stations=8,
            rod_back=rod_back, rod_fore=rod_fore,
            round_trip=True, observation_sequence="alternate",
            target_round_trip_ratio=0.5,
            seed=42,
        )
        report = check_leveling_compliance(wb)
        assert report.passed, f"合规失败: {[i.message for i in report.items if not i.passed]}"

    def test_grade3_round_trip_realism(self):
        """三等水准往返测真实性"""
        route = RouteInfo("BM1", 100.000, "BM2", 101.500, total_length_km=1.5)
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_3,
            num_stations=10, round_trip=True,
            observation_sequence="alternate",
            target_round_trip_ratio=0.4,
            seed=42,
        )
        assert wb.is_round_trip
        assert wb.round_trip_discrepancy_mm > 0.1
        assert wb.round_trip_passed is True
        # 三等限差系数 12
        expected_limit = 12.0 * math.sqrt(1.5)
        assert abs(wb.round_trip_limit_mm - expected_limit) < 0.01

    def test_round_trip_ratio_overrides_closure_ratio(self):
        """target_round_trip_ratio > 0 时, 各测段闭合差应为零"""
        route = _grade2_route()
        rod_back, rod_fore = _grade2_rods()
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_2,
            num_stations=8,
            rod_back=rod_back, rod_fore=rod_fore,
            round_trip=True, observation_sequence="alternate",
            target_closure_ratio=0.3,
            target_round_trip_ratio=0.5,
            seed=42,
        )
        # target_round_trip_ratio > 0 时, 各测段闭合差归零
        for section in wb.sections:
            if section.closure_error_mm is not None:
                assert abs(section.closure_error_mm) < 0.01, (
                    f"测段 {section.section_id} 闭合差应为零: {section.closure_error_mm:.3f} mm"
                )

    def test_reproducibility(self):
        """相同种子应产生相同不符值"""
        route = _grade2_route()
        rod_back, rod_fore = _grade2_rods()
        kwargs = dict(
            route=route, grade=LevelingGrade.GRADE_2,
            num_stations=8,
            rod_back=rod_back, rod_fore=rod_fore,
            round_trip=True, observation_sequence="alternate",
            target_round_trip_ratio=0.5,
        )
        wb1 = generate_leveling_workbook(seed=123, **kwargs)
        wb2 = generate_leveling_workbook(seed=123, **kwargs)
        assert abs(wb1.round_trip_discrepancy_mm - wb2.round_trip_discrepancy_mm) < 1e-10
