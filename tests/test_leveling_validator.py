# tests/test_leveling_validator.py
# 水准正向验证器测试
#
# 测试策略: 手工构造已知真值 → 生成观测读数 → 验证器计算 → 精确相等

import math
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.models.leveling import (
    LevelingStation, LevelingReading, LevelingSection,
    ExtraLevelingStation, ExtraLevelingSection,
    LevelingWorkbook, RodSpec,
)
from src.models.common import (
    LevelingGrade, RodType, SurveyMetadata, RouteInfo,
)
from src.validators.leveling_validator import (
    validate_leveling_workbook,
    compute_station_height_diff_black,
    compute_station_height_diff_red,
    compute_k_plus_black_minus_red,
    HEIGHT_TOLERANCE_M,
)


# ──────────────────────────────────────────────────────────────────────
# 辅助函数: 从真值构造观测数据
# ──────────────────────────────────────────────────────────────────────

def make_double_face_station(
    station_num: int,
    back_point: str,
    fore_point: str,
    height_diff: float,
    sight_height: float,
    k_back: float = 4.687,
    k_fore: float = 4.787,
    stadia_back: float = 30.0,
    stadia_fore: float = 30.0,
) -> LevelingStation:
    """
    从已知高差构造双面尺测站.

    构造逻辑 (保证 K+黑-红 = 0):
        a_red = K_back + a_black
        b_red = K_fore + b_black
    """
    a_black = sight_height
    b_black = a_black - height_diff
    a_red = k_back + a_black
    b_red = k_fore + b_black

    half_back = stadia_back / 200.0
    u_back = a_black + half_back
    l_back = a_black - half_back
    half_fore = stadia_fore / 200.0
    u_fore = b_black + half_fore
    l_fore = b_black - half_fore

    return LevelingStation(
        station_number=station_num,
        backsight_point=back_point,
        foresight_point=fore_point,
        backsight=LevelingReading(
            black_mid_m=a_black, red_mid_m=a_red,
            upper_wire_m=u_back, lower_wire_m=l_back,
        ),
        foresight=LevelingReading(
            black_mid_m=b_black, red_mid_m=b_red,
            upper_wire_m=u_fore, lower_wire_m=l_fore,
        ),
    )


def make_extra_station(
    station_num: int,
    back_point: str,
    fore_point: str,
    height_diff: float,
) -> ExtraLevelingStation:
    """构造等外水准测站 (变动仪高法)"""
    a1 = 1.500
    b1 = a1 - height_diff
    a2 = 1.650  # 变动仪高 >= 10 cm
    b2 = a2 - height_diff
    return ExtraLevelingStation(
        station_number=station_num,
        backsight_point=back_point,
        foresight_point=fore_point,
        backsight_1_m=a1, foresight_1_m=b1,
        backsight_2_m=a2, foresight_2_m=b2,
    )


# ──────────────────────────────────────────────────────────────────────
# 测试: 基本高差方程 (axiom A1)
# ──────────────────────────────────────────────────────────────────────

class TestBasicHeightDiff:
    """测试 h = a - b (axiom A1.1)"""

    def test_positive_height_diff(self):
        station = LevelingStation(
            station_number=1, backsight_point="A", foresight_point="B",
            backsight=LevelingReading(black_mid_m=1.500),
            foresight=LevelingReading(black_mid_m=1.200),
        )
        h = compute_station_height_diff_black(station)
        assert h == pytest.approx(0.300, abs=1e-12)

    def test_negative_height_diff(self):
        station = LevelingStation(
            station_number=1, backsight_point="A", foresight_point="B",
            backsight=LevelingReading(black_mid_m=1.200),
            foresight=LevelingReading(black_mid_m=1.500),
        )
        h = compute_station_height_diff_black(station)
        assert h == pytest.approx(-0.300, abs=1e-12)

    def test_zero_height_diff(self):
        station = LevelingStation(
            station_number=1, backsight_point="A", foresight_point="B",
            backsight=LevelingReading(black_mid_m=1.350),
            foresight=LevelingReading(black_mid_m=1.350),
        )
        h = compute_station_height_diff_black(station)
        assert h == pytest.approx(0.0, abs=1e-12)


# ──────────────────────────────────────────────────────────────────────
# 测试: 双面尺检核 (axiom A5)
# ──────────────────────────────────────────────────────────────────────

class TestDoubleFaceChecks:
    """测试 K+黑-红 和 红面高差改正"""

    def test_k_plus_black_minus_red_zero(self):
        """K+黑-红 = 0 (完美情况: red = K + black)"""
        k = 4.687
        black = 1.234
        red = k + black
        reading = LevelingReading(black_mid_m=black, red_mid_m=red)
        delta = compute_k_plus_black_minus_red(reading, k)
        assert delta == pytest.approx(0.0, abs=1e-10)

    def test_k_plus_black_minus_red_nonzero(self):
        """K+黑-红 ≠ 0 (有读数偏差)"""
        k = 4.787
        black = 1.500
        red = k + black + 0.001  # 偏差 1 mm
        reading = LevelingReading(black_mid_m=black, red_mid_m=red)
        delta = compute_k_plus_black_minus_red(reading, k)
        assert delta == pytest.approx(-1.0, abs=1e-6)

    def test_red_face_height_diff_correction(self):
        """
        红面高差改正后 = 黑面高差.

        推导 (red = black + K, K+黑-红 = 0):
          h_red_raw = (a_black+K_back) - (b_black+K_fore) = h_black + (K_back-K_fore)
          h_red_corrected = h_red_raw - (K_back-K_fore) = h_black
        """
        k_back, k_fore = 4.687, 4.787
        h_true = 0.300
        station = LevelingStation(
            station_number=1, backsight_point="A", foresight_point="B",
            backsight=LevelingReading(black_mid_m=1.500, red_mid_m=k_back + 1.500),
            foresight=LevelingReading(black_mid_m=1.200, red_mid_m=k_fore + 1.200),
        )
        h_black = compute_station_height_diff_black(station)
        h_red = compute_station_height_diff_red(station, k_back, k_fore)
        assert h_black == pytest.approx(h_true, abs=1e-12)
        assert h_red == pytest.approx(h_black, abs=1e-12), \
            f"h_red={h_red}, h_black={h_black}, 红面改正后应等于黑面"


# ──────────────────────────────────────────────────────────────────────
# 测试: 三等水准路线 (3站)
# ──────────────────────────────────────────────────────────────────────

class TestGrade3LevelingRoute:
    """
    三等水准附合路线: BM.A -> TP1 -> TP2 -> BM.B
    已知: H_A = 100.000 m, H_B = 101.500 m
    总高差: +1.500 m, 3 站
    """

    def setup_method(self):
        self.H_A = 100.000
        self.H_B = 101.500
        self.height_diffs = [0.300, 0.800, 0.400]
        self.k_back = 4.687
        self.k_fore = 4.787

        stations = []
        points = ["BM.A", "TP1", "TP2", "BM.B"]
        sight_heights = [101.000, 101.500, 102.500]

        for i, (dh, sh) in enumerate(zip(self.height_diffs, sight_heights)):
            st = make_double_face_station(
                station_num=i + 1,
                back_point=points[i],
                fore_point=points[i + 1],
                height_diff=dh,
                sight_height=sh,
                k_back=self.k_back,
                k_fore=self.k_fore,
            )
            stations.append(st)
        self.stations = stations

    def test_station_height_diffs(self):
        """各站黑面高差 = 真值"""
        for i, st in enumerate(self.stations):
            h = compute_station_height_diff_black(st)
            assert h == pytest.approx(self.height_diffs[i], abs=1e-12)

    def test_k_plus_black_minus_red(self):
        """K+黑-红 = 0 (构造时保证完美)"""
        for st in self.stations:
            d_back = compute_k_plus_black_minus_red(st.backsight, self.k_back)
            d_fore = compute_k_plus_black_minus_red(st.foresight, self.k_fore)
            assert abs(d_back) < 1e-6
            assert abs(d_fore) < 1e-6

    def test_full_route_closure(self):
        """路线闭合差 = 0, 终点高程精确相等"""
        rod_back = RodSpec(rod_id="K1", rod_type=RodType.DOUBLE_FACE,
                           k_value_m=self.k_back)
        rod_fore = RodSpec(rod_id="K2", rod_type=RodType.DOUBLE_FACE,
                           k_value_m=self.k_fore)
        metadata = SurveyMetadata(
            date="2025-06-01", observer="张三", recorder="李四",
            instrument_model="DS3", instrument_serial="001"
        )
        route = RouteInfo(
            start_point_name="BM.A", start_point_height=self.H_A,
            end_point_name="BM.B", end_point_height=self.H_B,
        )
        section = LevelingSection(
            section_id="S1", metadata=metadata, route=route,
            grade=LevelingGrade.GRADE_3,
            rod_back=rod_back, rod_fore=rod_fore,
            stations=self.stations,
        )
        workbook = LevelingWorkbook(
            grade=LevelingGrade.GRADE_3, sections=[section],
        )

        result = validate_leveling_workbook(workbook)

        # 闭合差 = 0
        assert section.closure_error_mm == pytest.approx(0.0, abs=1e-6)

        # 终点高程精确相等
        computed_H_B = result.computed_heights.get("BM.B")
        assert computed_H_B is not None
        assert computed_H_B == pytest.approx(self.H_B, abs=HEIGHT_TOLERANCE_M)

        # SUM(a) - SUM(b) = SUM(h)
        check_sum = section.sum_backsight_m - section.sum_foresight_m
        assert check_sum == pytest.approx(section.sum_height_diff_m, abs=1e-12)

        # 红面改正后 = 黑面, 高差中数 = 黑面高差
        for i, st in enumerate(self.stations):
            assert st.height_diff_red_m == pytest.approx(
                st.height_diff_black_m, abs=1e-10), \
                f"站{i+1}: h_red={st.height_diff_red_m} != h_black={st.height_diff_black_m}"
            assert st.height_diff_mean_m == pytest.approx(
                st.height_diff_black_m, abs=1e-10), \
                f"站{i+1}: h_mid={st.height_diff_mean_m} != h_black={st.height_diff_black_m}"


# ──────────────────────────────────────────────────────────────────────
# 测试: 等外水准 (变动仪高法)
# ──────────────────────────────────────────────────────────────────────

class TestExtraLeveling:
    """等外水准: BM.A -> TP1 -> BM.B"""

    def test_extra_route_closure(self):
        """路线闭合差 = 0"""
        H_A = 50.000
        H_B = 51.200
        height_diffs = [0.500, 0.700]

        stations = []
        points = ["BM.A", "TP1", "BM.B"]
        for i, dh in enumerate(height_diffs):
            st = make_extra_station(i + 1, points[i], points[i + 1], dh)
            stations.append(st)

        rod = RodSpec(rod_id="R1", rod_type=RodType.SINGLE_FACE)
        metadata = SurveyMetadata(
            date="2025-06-01", observer="王五", recorder="赵六",
            instrument_model="DS3", instrument_serial="002"
        )
        route = RouteInfo(
            start_point_name="BM.A", start_point_height=H_A,
            end_point_name="BM.B", end_point_height=H_B,
        )
        section = ExtraLevelingSection(
            section_id="S1", metadata=metadata, route=route,
            rod=rod, stations=stations,
        )
        workbook = LevelingWorkbook(
            grade=LevelingGrade.EXTRA, extra_sections=[section],
        )

        result = validate_leveling_workbook(workbook)

        # 闭合差 = 0
        assert section.closure_error_mm == pytest.approx(0.0, abs=1e-6)

        # 终点高程精确
        computed_H_B = result.computed_heights.get("BM.B")
        assert computed_H_B == pytest.approx(H_B, abs=HEIGHT_TOLERANCE_M)

        # 变动仪高较差 = 0 (构造时两次高差相同)
        for st in stations:
            assert st.height_diff_diff_mm == pytest.approx(0.0, abs=1e-6)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
