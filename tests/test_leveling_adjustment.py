# tests/test_leveling_adjustment.py
# 水准平差测试

import math
import pytest

from src.models.common import RouteInfo, LevelingGrade, RodType
from src.models.leveling import (
    LevelingWorkbook, LevelingSection, LevelingStation,
    LevelingReading, ExtraLevelingSection, ExtraLevelingStation,
    RodSpec, SurveyMetadata,
)
from src.adjustment.leveling_adjustment import adjust_leveling


def _make_metadata() -> SurveyMetadata:
    return SurveyMetadata(
        date="2025-06-01", observer="Test",
        recorder="Test", instrument_model="DS3",
        instrument_serial="TEST-001",
    )


def _make_section(
    start_h: float, end_h: float,
    heights: list,
    start_name="BM.A", end_name="BM.B",
    distances_m: list = None,
) -> LevelingSection:
    """构造 LevelingSection 用于平差测试."""
    n = len(heights)
    route = RouteInfo(
        start_point_name=start_name, start_point_height=start_h,
        end_point_name=end_name, end_point_height=end_h,
        total_length_km=1.0,
    )
    stations = []
    point_names = [f"TP.{i+1}" for i in range(n - 1)] + [end_name]
    for i in range(n):
        bs = LevelingReading(black_mid_m=start_h + sum(heights[:i+1]) + 0.5)
        fs = LevelingReading(black_mid_m=start_h + sum(heights[:i]) + 0.5 - heights[i])
        st = LevelingStation(
            station_number=i + 1,
            backsight_point=start_name if i == 0 else point_names[i - 1],
            foresight_point=point_names[i],
            backsight=bs, foresight=fs,
            height_diff_mean_m=heights[i],
            stadia_back_m=distances_m[i] if distances_m else 50.0,
            stadia_fore_m=distances_m[i] if distances_m else 50.0,
        )
        stations.append(st)

    section = LevelingSection(
        section_id="S1",
        metadata=_make_metadata(),
        route=route,
        grade=LevelingGrade.GRADE_3,
        rod_back=RodSpec(rod_id="K1", rod_type=RodType.DOUBLE_FACE),
        rod_fore=RodSpec(rod_id="K2", rod_type=RodType.DOUBLE_FACE),
        stations=stations,
    )
    return section


class TestSingleRunAdjustment:
    """单程路线平差测试."""

    def test_zero_closure(self):
        """闭合差为零时改正数全零."""
        heights = [1.0, 1.0, 1.0, 1.0, 1.0]
        section = _make_section(100.0, 105.0, heights)
        wb = LevelingWorkbook(
            grade=LevelingGrade.GRADE_3,
            sections=[section],
        )
        adjust_leveling(wb)
        adj = wb.adjustment
        assert adj is not None
        assert abs(adj.closure_error_mm) < 1e-8
        for rec in adj.records:
            assert abs(rec.correction_mm) < 1e-8
            assert abs(rec.corrected_height_diff_m - rec.observed_height_diff_m) < 1e-10

    def test_positive_closure(self):
        """正闭合差（观测值偏大）改正数为负."""
        heights = [1.002, 1.002, 1.002, 1.002, 1.002]
        section = _make_section(100.0, 105.0, heights)
        wb = LevelingWorkbook(
            grade=LevelingGrade.GRADE_3,
            sections=[section],
        )
        adjust_leveling(wb)
        adj = wb.adjustment
        assert adj is not None
        assert abs(adj.closure_error_mm - 10.0) < 0.01
        for rec in adj.records:
            assert rec.correction_mm < 0
        last = adj.records[-1]
        assert abs(last.height_m - 105.0) < 1e-6

    def test_negative_closure(self):
        """负闭合差（观测值偏小）改正数为正."""
        heights = [0.998, 0.998, 0.998, 0.998, 0.998]
        section = _make_section(100.0, 105.0, heights)
        wb = LevelingWorkbook(
            grade=LevelingGrade.GRADE_3,
            sections=[section],
        )
        adjust_leveling(wb)
        adj = wb.adjustment
        assert adj is not None
        assert abs(adj.closure_error_mm + 10.0) < 0.01
        for rec in adj.records:
            assert rec.correction_mm > 0
        last = adj.records[-1]
        assert abs(last.height_m - 105.0) < 1e-6

    def test_correction_sum_equals_negative_closure(self):
        """改正数总和 = -f_h."""
        heights = [0.997, 1.003, 0.998, 1.004, 0.996]
        section = _make_section(100.0, 105.0, heights)
        wb = LevelingWorkbook(
            grade=LevelingGrade.GRADE_3,
            sections=[section],
        )
        adjust_leveling(wb)
        adj = wb.adjustment
        sum_v = sum(rec.correction_mm for rec in adj.records)
        assert abs(sum_v + adj.closure_error_mm) < 1e-8

    def test_unequal_distances(self):
        """不等距时按距离比例分配."""
        heights = [1.002, 1.002, 1.002, 1.002, 1.002]
        distances = [30.0, 50.0, 70.0, 40.0, 60.0]
        section = _make_section(100.0, 105.0, heights, distances_m=distances)
        wb = LevelingWorkbook(
            grade=LevelingGrade.GRADE_3,
            sections=[section],
        )
        adjust_leveling(wb)
        adj = wb.adjustment
        corrections = [abs(rec.correction_mm) for rec in adj.records]
        total_dist = sum(distances)
        expected_ratios = [d / total_dist for d in distances]
        actual_ratios = [c / sum(corrections) for c in corrections]
        for actual, expected in zip(actual_ratios, expected_ratios):
            assert abs(actual - expected) < 1e-8

    def test_closed_loop(self):
        """闭合路线（起终点相同）."""
        heights = [1.0, 1.0, 1.0, -3.002]
        section = _make_section(80.0, 80.0, heights)
        wb = LevelingWorkbook(
            grade=LevelingGrade.GRADE_4,
            sections=[section],
        )
        adjust_leveling(wb)
        adj = wb.adjustment
        assert abs(adj.closure_error_mm + 2.0) < 0.01
        last = adj.records[-1]
        assert abs(last.height_m - 80.0) < 1e-6


class TestExtraLevelingAdjustment:
    """等外水准（变动仪高法）平差测试."""

    def test_extra_adjustment(self):
        """等外水准单程平差."""
        route = RouteInfo(
            start_point_name="BM.E", start_point_height=50.0,
            end_point_name="BM.F", end_point_height=52.5,
            total_length_km=0.8,
        )
        stations = []
        point_names = ["TP.1", "TP.2", "TP.3", "BM.F"]
        h_diffs = [0.600, 0.650, 0.640, 0.612]
        for i in range(4):
            st = ExtraLevelingStation(
                station_number=i + 1,
                backsight_point="BM.E" if i == 0 else point_names[i - 1],
                foresight_point=point_names[i],
                backsight_1_m=1.5,
                foresight_1_m=1.5 - h_diffs[i],
                height_diff_1_m=h_diffs[i],
                backsight_2_m=1.4,
                foresight_2_m=1.4 - h_diffs[i],
                height_diff_2_m=h_diffs[i],
            )
            stations.append(st)

        section = ExtraLevelingSection(
            section_id="E1",
            metadata=_make_metadata(),
            route=route,
            rod=RodSpec(rod_id="K1", rod_type=RodType.SINGLE_FACE),
            stations=stations,
        )

        wb = LevelingWorkbook(
            grade=LevelingGrade.EXTRA,
            extra_sections=[section],
        )
        adjust_leveling(wb)
        adj = wb.adjustment
        assert adj is not None
        assert abs(adj.closure_error_mm - 2.0) < 0.01
        last = adj.records[-1]
        assert abs(last.height_m - 52.5) < 1e-6


class TestRoundTripAdjustment:
    """往返测平差测试."""

    def test_round_trip_zero_discrepancy(self):
        """往返不符值为零."""
        route = RouteInfo(
            start_point_name="BM.C", start_point_height=200.0,
            end_point_name="BM.D", end_point_height=210.0,
            total_length_km=2.0,
        )
        fwd_heights = [2.0, 2.0, 2.0, 2.0, 2.0]
        fwd_section = _make_section(200.0, 210.0, fwd_heights,
                                     start_name="BM.C", end_name="BM.D")

        ret_route = RouteInfo(
            start_point_name="BM.D", start_point_height=210.0,
            end_point_name="BM.C", end_point_height=200.0,
            total_length_km=2.0,
        )
        ret_stations = []
        for i in range(5):
            bs = LevelingReading(black_mid_m=1.5)
            fs = LevelingReading(black_mid_m=3.5)
            st = LevelingStation(
                station_number=i + 1,
                backsight_point=f"TP.{10+i}",
                foresight_point=f"TP.{11+i}" if i < 4 else "BM.C",
                backsight=bs, foresight=fs,
                height_diff_mean_m=-2.0,
                stadia_back_m=50.0,
                stadia_fore_m=50.0,
            )
            ret_stations.append(st)
        ret_section = LevelingSection(
            section_id="S2",
            metadata=_make_metadata(),
            route=ret_route,
            grade=LevelingGrade.GRADE_2,
            rod_back=RodSpec(rod_id="K1", rod_type=RodType.INVAR_BASIC_AUX),
            rod_fore=RodSpec(rod_id="K2", rod_type=RodType.INVAR_BASIC_AUX),
            stations=ret_stations,
        )

        wb = LevelingWorkbook(
            grade=LevelingGrade.GRADE_2,
            sections=[fwd_section, ret_section],
            is_round_trip=True,
            round_trip_discrepancy_mm=0.0,
            round_trip_limit_mm=5.66,
            round_trip_passed=True,
        )
        adjust_leveling(wb)
        adj = wb.adjustment
        assert adj is not None
        assert abs(adj.closure_error_mm) < 1e-8
        last = adj.records[-1]
        assert abs(last.height_m - 210.0) < 1e-6

    def test_round_trip_with_discrepancy(self):
        """往返测有不符值时取中数再分配."""
        route = RouteInfo(
            start_point_name="BM.X", start_point_height=300.0,
            end_point_name="BM.Y", end_point_height=310.0,
            total_length_km=1.5,
        )
        fwd_heights = [2.001, 2.001, 2.001, 2.0, 2.0]
        fwd_section = _make_section(300.0, 310.0, fwd_heights,
                                     start_name="BM.X", end_name="BM.Y")

        ret_route = RouteInfo(
            start_point_name="BM.Y", start_point_height=310.0,
            end_point_name="BM.X", end_point_height=300.0,
            total_length_km=1.5,
        )
        ret_heights = [-1.999, -2.0, -2.0, -1.999, -1.999]
        ret_stations = []
        for i in range(5):
            bs = LevelingReading(black_mid_m=1.5)
            fs = LevelingReading(black_mid_m=3.5)
            st = LevelingStation(
                station_number=i + 1,
                backsight_point=f"TP.{20+i}",
                foresight_point=f"TP.{21+i}" if i < 4 else "BM.X",
                backsight=bs, foresight=fs,
                height_diff_mean_m=ret_heights[i],
                stadia_back_m=50.0,
                stadia_fore_m=50.0,
            )
            ret_stations.append(st)
        ret_section = LevelingSection(
            section_id="S2",
            metadata=_make_metadata(),
            route=ret_route,
            grade=LevelingGrade.GRADE_2,
            rod_back=RodSpec(rod_id="K1", rod_type=RodType.INVAR_BASIC_AUX),
            rod_fore=RodSpec(rod_id="K2", rod_type=RodType.INVAR_BASIC_AUX),
            stations=ret_stations,
        )

        discrepancy = abs(10.003 + (-9.997)) * 1000
        wb = LevelingWorkbook(
            grade=LevelingGrade.GRADE_2,
            sections=[fwd_section, ret_section],
            is_round_trip=True,
            round_trip_discrepancy_mm=discrepancy,
            round_trip_limit_mm=4.0 * math.sqrt(1.5),
            round_trip_passed=True,
        )
        adjust_leveling(wb)
        adj = wb.adjustment
        assert adj is not None
        assert abs(adj.closure_error_mm) < 0.01
        last = adj.records[-1]
        assert abs(last.height_m - 310.0) < 1e-6


class TestGeneratorIntegration:
    """与生成器集成测试."""

    def test_grade3_single(self):
        """三等单程生成+平差."""
        from src.generators.leveling_generator import generate_leveling_workbook
        route = RouteInfo(
            start_point_name="BM.A", start_point_height=100.0,
            end_point_name="BM.B", end_point_height=108.0,
            total_length_km=1.5,
        )
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_3, num_stations=6,
            seed=42, target_closure_ratio=0.3,
        )
        assert wb.adjustment is not None
        assert len(wb.adjustment.records) == 6
        last = wb.adjustment.records[-1]
        assert abs(last.height_m - 108.0) < 1e-6

    def test_grade2_round_trip(self):
        """二等往返测生成+平差."""
        from src.generators.leveling_generator import generate_leveling_workbook
        route = RouteInfo(
            start_point_name="BM.C", start_point_height=200.0,
            end_point_name="BM.D", end_point_height=215.0,
            total_length_km=2.5,
        )
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_2, num_stations=8,
            seed=42, round_trip=True, target_round_trip_ratio=0.3,
        )
        assert wb.adjustment is not None
        assert len(wb.adjustment.records) == 8
        last = wb.adjustment.records[-1]
        assert abs(last.height_m - 215.0) < 1e-6

    def test_extra_single(self):
        """等外水准生成+平差."""
        from src.generators.leveling_generator import generate_leveling_workbook
        route = RouteInfo(
            start_point_name="BM.E", start_point_height=50.0,
            end_point_name="BM.F", end_point_height=53.0,
            total_length_km=0.6,
        )
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.EXTRA, num_stations=5,
            seed=42,
        )
        assert wb.adjustment is not None
        assert len(wb.adjustment.records) == 5
        last = wb.adjustment.records[-1]
        assert abs(last.height_m - 53.0) < 1e-6

    def test_grade4_closed_loop(self):
        """四等闭合路线生成+平差."""
        from src.generators.leveling_generator import generate_leveling_workbook
        route = RouteInfo(
            start_point_name="BM.G", start_point_height=80.0,
            end_point_name="BM.G", end_point_height=80.0,
            total_length_km=0.8,
        )
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_4, num_stations=6,
            seed=42, target_closure_ratio=0.2,
        )
        assert wb.adjustment is not None
        last = wb.adjustment.records[-1]
        assert abs(last.height_m - 80.0) < 1e-6
