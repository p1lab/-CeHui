# tests/test_traversing_validator.py
# 导线正向验证器测试
#
# 测试策略: 从已知坐标构造方位角/平距真值 → 生成度盘读数/斜距 → 验证器计算 → 精确相等

import math
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.models.traversing import (
    DirectionReading, AngleSet, StationAngleObservation,
    DistanceReading, DistanceSet, EdgeDistanceObservation,
    TraversePointRecord, TraverseComputation, TraversingWorkbook,
)
from src.models.common import (
    TraverseGrade, InstrumentGrade, Face, AngleDefinition,
    SurveyMetadata, TraverseInfo,
)
from src.validators.traversing_validator import (
    validate_traversing_workbook,
    normalize_angle, normalize_2c, propagate_azimuth,
    ANGLE_TOLERANCE_RAD, COORD_TOLERANCE_M,
)


TWO_PI = 2.0 * math.pi


# ──────────────────────────────────────────────────────────────────────
# 辅助函数
# ──────────────────────────────────────────────────────────────────────

def make_angle_set(
    set_number: int,
    l0_rad: float,
    back_azimuth: float,
    fore_azimuth: float,
    back_target: str = "BACK",
    fore_target: str = "FORE",
    two_c_base: float = 0.0,
) -> AngleSet:
    """
    从方位角构造一测回方向观测.

    构造逻辑:
        方向值 L_bar = 方位角 (简化: 零方向 = 后视)
        后视方向值 = 0 (归零)
        前视方向值 = fore_azimuth - back_azimuth (= 水平角)

        L = L_0 + L_bar + delta (其中 delta = two_c_base / 2)
        R = L_0 + L_bar - delta + pi
    """
    delta = two_c_base / 2.0  # 2C 的一半

    # 后视方向: L_bar = 0
    L_back = l0_rad + 0.0 + delta
    R_back = l0_rad + 0.0 - delta + math.pi

    # 前视方向: L_bar = 水平角
    horizontal_angle = normalize_angle(fore_azimuth - back_azimuth)
    L_fore = l0_rad + horizontal_angle + delta
    R_fore = l0_rad + horizontal_angle - delta + math.pi

    directions = [
        DirectionReading(target=back_target, face=Face.LEFT,
                         reading_rad=normalize_angle(L_back)),
        DirectionReading(target=fore_target, face=Face.LEFT,
                         reading_rad=normalize_angle(L_fore)),
        DirectionReading(target=back_target, face=Face.RIGHT,
                         reading_rad=normalize_angle(R_back)),
        DirectionReading(target=fore_target, face=Face.RIGHT,
                         reading_rad=normalize_angle(R_fore)),
    ]

    return AngleSet(
        set_number=set_number,
        degree_plate_zero_rad=l0_rad,
        directions=directions,
    )


def make_distance_edge(
    edge_name: str,
    from_point: str,
    to_point: str,
    horizontal_distance: float,
    zenith_angle: float = math.pi / 2.0,
    inst_height: float = 1.50,
    prism_height: float = 1.20,
) -> EdgeDistanceObservation:
    """
    从平距构造距离观测 (往返各 1 测回 3 读数).

    默认天顶距 = pi/2 (水平视线), 此时斜距 = 平距.
    """
    # 斜距 = 平距 / sin(Z)
    slope_dist = horizontal_distance / math.sin(zenith_angle)

    # 往测: 3 次读数 (精确相同, 无扰动)
    fwd_readings = [DistanceReading(reading_m=slope_dist, is_slope=True) for _ in range(3)]
    fwd_set = DistanceSet(set_number=1, readings=fwd_readings)

    # 返测: 3 次读数
    bwd_readings = [DistanceReading(reading_m=slope_dist, is_slope=True) for _ in range(3)]
    bwd_set = DistanceSet(set_number=1, readings=bwd_readings)

    return EdgeDistanceObservation(
        edge_name=edge_name,
        from_point=from_point,
        to_point=to_point,
        instrument_height_m=inst_height,
        prism_height_m=prism_height,
        zenith_angle_forward_rad=zenith_angle,
        zenith_angle_backward_rad=zenith_angle,
        forward_sets=[fwd_set],
        backward_sets=[bwd_set],
    )


# ──────────────────────────────────────────────────────────────────────
# 测试: 角度归一化
# ──────────────────────────────────────────────────────────────────────

class TestAngleNormalization:
    """测试角度归一化函数"""

    def test_normalize_angle_positive(self):
        assert normalize_angle(0.5) == pytest.approx(0.5)

    def test_normalize_angle_negative(self):
        assert normalize_angle(-0.5) == pytest.approx(TWO_PI - 0.5)

    def test_normalize_angle_over_2pi(self):
        assert normalize_angle(TWO_PI + 0.1) == pytest.approx(0.1)

    def test_normalize_2c_small(self):
        assert normalize_2c(0.001) == pytest.approx(0.001)

    def test_normalize_2c_large_positive(self):
        assert normalize_2c(4.0) == pytest.approx(4.0 - TWO_PI)

    def test_normalize_2c_large_negative(self):
        assert normalize_2c(-4.0) == pytest.approx(-4.0 + TWO_PI)


# ──────────────────────────────────────────────────────────────────────
# 测试: 方位角递推
# ──────────────────────────────────────────────────────────────────────

class TestAzimuthPropagation:
    """测试方位角递推 (axiom A1.3)"""

    def test_left_angle_forward(self):
        """左角递推: alpha_next = alpha + beta - pi"""
        alpha0 = math.radians(45.0)   # 45°
        beta = math.radians(120.0)     # 120°
        alpha1 = propagate_azimuth(alpha0, beta, AngleDefinition.LEFT_ANGLE)
        expected = normalize_angle(math.radians(45.0 + 120.0 - 180.0))
        assert alpha1 == pytest.approx(expected, abs=1e-12)

    def test_right_angle_forward(self):
        """右角递推: alpha_next = alpha - beta + pi"""
        alpha0 = math.radians(45.0)
        beta = math.radians(120.0)
        alpha1 = propagate_azimuth(alpha0, beta, AngleDefinition.RIGHT_ANGLE)
        expected = normalize_angle(math.radians(45.0 - 120.0 + 180.0))
        assert alpha1 == pytest.approx(expected, abs=1e-12)


# ──────────────────────────────────────────────────────────────────────
# 测试: 单测回 2C 和方向值
# ──────────────────────────────────────────────────────────────────────

class TestAngleSetComputation:
    """测试 2C, 方向值, 半测回角"""

    def test_2c_computation(self):
        """2C = L - (R - pi), 构造时设定 2C = 5\""""
        l0 = math.radians(0.0)  # 度盘零位 = 0
        back_az = math.radians(45.0)
        fore_az = math.radians(165.0)
        two_c_arcsec = 5.0
        two_c_rad = math.radians(two_c_arcsec / 3600.0)

        aset = make_angle_set(
            set_number=1, l0_rad=l0,
            back_azimuth=back_az, fore_azimuth=fore_az,
            two_c_base=two_c_rad,
        )

        from src.validators.traversing_validator import validate_angle_set
        from src.validators.traversing_validator import TraversingValidationResult
        result = TraversingValidationResult()
        validate_angle_set(aset, "BACK", "FORE", result)

        # 2C 应等于构造值
        assert aset.two_c_values_rad.get("BACK") == pytest.approx(two_c_rad, abs=1e-10)
        assert aset.two_c_values_rad.get("FORE") == pytest.approx(two_c_rad, abs=1e-10)

    def test_direction_value(self):
        """方向值 L_bar = (L + R - pi) / 2 - L_0"""
        l0 = math.radians(2.5 / 60.0)  # 度盘零位 2'30"
        back_az = math.radians(30.0)
        fore_az = math.radians(150.0)
        expected_angle = normalize_angle(fore_az - back_az)

        aset = make_angle_set(
            set_number=1, l0_rad=l0,
            back_azimuth=back_az, fore_azimuth=fore_az,
        )

        from src.validators.traversing_validator import validate_angle_set
        from src.validators.traversing_validator import TraversingValidationResult
        result = TraversingValidationResult()
        validate_angle_set(aset, "BACK", "FORE", result)

        # 后视方向值 = 0 (归零)
        assert aset.zero_reduced_directions_rad.get("BACK") == pytest.approx(0.0, abs=1e-10)

        # 前视方向值 = 水平角
        assert aset.zero_reduced_directions_rad.get("FORE") == pytest.approx(
            expected_angle, abs=1e-10)

    def test_set_angle(self):
        """一测回角值 = (beta_L + beta_R) / 2"""
        l0 = math.radians(0.0)
        back_az = math.radians(0.0)
        fore_az = math.radians(90.0)
        expected_angle = math.radians(90.0)

        aset = make_angle_set(
            set_number=1, l0_rad=l0,
            back_azimuth=back_az, fore_azimuth=fore_az,
        )

        from src.validators.traversing_validator import validate_angle_set
        from src.validators.traversing_validator import TraversingValidationResult
        result = TraversingValidationResult()
        validate_angle_set(aset, "BACK", "FORE", result)

        assert aset.set_angle_rad is not None
        assert aset.set_angle_rad == pytest.approx(expected_angle, abs=1e-10)

        # 半测回较差 = 0 (构造时 2C 对称)
        assert aset.half_set_diff_rad == pytest.approx(0.0, abs=1e-10)


# ──────────────────────────────────────────────────────────────────────
# 测试: 距离观测
# ──────────────────────────────────────────────────────────────────────

class TestDistanceComputation:
    """测试斜距→平距, 读数差, 往返较差"""

    def test_horizontal_distance_from_slope(self):
        """斜距 * sin(Z) = 平距"""
        D_true = 100.0
        Z = math.radians(85.0)  # 天顶距 85° (略仰)
        S = D_true / math.sin(Z)

        edge = make_distance_edge(
            edge_name="A-P1", from_point="A", to_point="P1",
            horizontal_distance=D_true, zenith_angle=Z,
        )

        from src.validators.traversing_validator import validate_edge_distance
        from src.validators.traversing_validator import TraversingValidationResult
        result = TraversingValidationResult()
        validate_edge_distance(edge, result)

        assert edge.forward_mean_distance_m == pytest.approx(D_true, abs=1e-8)
        assert edge.backward_mean_distance_m == pytest.approx(D_true, abs=1e-8)
        assert edge.round_trip_diff_mm == pytest.approx(0.0, abs=1e-6)
        assert edge.final_distance_m == pytest.approx(D_true, abs=1e-8)

    def test_reading_diff_zero(self):
        """3 次读数相同时, 读数差 = 0"""
        edge = make_distance_edge(
            edge_name="A-P1", from_point="A", to_point="P1",
            horizontal_distance=200.0,
        )

        from src.validators.traversing_validator import validate_edge_distance
        from src.validators.traversing_validator import TraversingValidationResult
        result = TraversingValidationResult()
        validate_edge_distance(edge, result)

        for dist_set in edge.forward_sets:
            assert dist_set.reading_diff_mm == pytest.approx(0.0, abs=1e-6)


# ──────────────────────────────────────────────────────────────────────
# 测试: 完整导线 (2 站 3 点)
# ──────────────────────────────────────────────────────────────────────

class TestTraverseFullRoute:
    """
    附合导线: A(已知) -> P1 -> B(已知)
    A = (1000.000, 1000.000)
    P1 = (1100.000, 1050.000)
    B = (1200.000, 1100.000)

    方位角:
        alpha_AP1 = atan2(50, 100) ≈ 26.565°
        alpha_P1B = atan2(50, 100) ≈ 26.565°
    水平角 (左角):
        beta_P1 = alpha_P1B - alpha_AP1 + 180° = 180°
    平距:
        D_AP1 = sqrt(100^2 + 50^2) ≈ 111.803
        D_P1B = sqrt(100^2 + 50^2) ≈ 111.803
    """

    def setup_method(self):
        self.A = (1000.0, 1000.0)
        self.P1 = (1100.0, 1050.0)
        self.B = (1200.0, 1100.0)

        self.alpha_AP1 = normalize_angle(math.atan2(
            self.P1[1] - self.A[1], self.P1[0] - self.A[0]))
        self.alpha_P1B = normalize_angle(math.atan2(
            self.B[1] - self.P1[1], self.B[0] - self.P1[0]))

        self.D_AP1 = math.sqrt(
            (self.P1[0] - self.A[0])**2 + (self.P1[1] - self.A[1])**2)
        self.D_P1B = math.sqrt(
            (self.B[0] - self.P1[0])**2 + (self.B[1] - self.P1[1])**2)

        # 左角: beta = alpha_fwd - alpha_bwd + pi
        self.beta_P1 = normalize_angle(self.alpha_P1B - self.alpha_AP1 + math.pi)

    def test_coordinate_propagation(self):
        """坐标传递: 从 A 经 P1 到 B, 终点坐标精确匹配"""
        # 构造角度观测 (P1 站)
        l0 = math.radians(0.0)
        aset = make_angle_set(
            set_number=1, l0_rad=l0,
            back_azimuth=self.alpha_AP1,
            fore_azimuth=self.alpha_P1B,
            back_target="A", fore_target="B",
        )
        obs = StationAngleObservation(
            station_name="P1",
            backsight_target="A",
            foresight_target="B",
            zero_direction="A",
            sets=[aset],
            angle_definition=AngleDefinition.LEFT_ANGLE,
        )

        # 构造距离观测
        edge_AP1 = make_distance_edge("A-P1", "A", "P1", self.D_AP1)
        edge_P1B = make_distance_edge("P1-B", "P1", "B", self.D_P1B)

        # 构造成果计算表
        comp = TraverseComputation(
            info=TraverseInfo(
                name="Test",
                start_point_name="A", start_point_x=self.A[0], start_point_y=self.A[1],
                end_point_name="B", end_point_x=self.B[0], end_point_y=self.B[1],
                start_azimuth=self.alpha_AP1,
                end_azimuth=self.alpha_P1B,
                angle_definition=AngleDefinition.LEFT_ANGLE,
            ),
            grade=TraverseGrade.GRADE_1,
            point_records=[
                TraversePointRecord(point_name="A", is_known=True),
                TraversePointRecord(point_name="P1", is_known=False),
                TraversePointRecord(point_name="B", is_known=True),
            ],
            edge_records=[
                TraversePointRecord(
                    point_name="A-P1", observed_angle_rad=None,
                    distance_m=self.D_AP1,
                ),
                TraversePointRecord(
                    point_name="P1-B", observed_angle_rad=self.beta_P1,
                    distance_m=self.D_P1B,
                ),
            ],
        )

        workbook = TraversingWorkbook(
            grade=TraverseGrade.GRADE_1,
            info=comp.info,
            angle_observations=[obs],
            distance_observations=[edge_AP1, edge_P1B],
            computation=comp,
        )

        result = validate_traversing_workbook(workbook)

        # 终点坐标精确匹配
        end_coord = result.computed_coordinates.get("B")
        assert end_coord is not None
        assert end_coord[0] == pytest.approx(self.B[0], abs=COORD_TOLERANCE_M), \
            f"X_B = {end_coord[0]}, expected {self.B[0]}"
        assert end_coord[1] == pytest.approx(self.B[1], abs=COORD_TOLERANCE_M), \
            f"Y_B = {end_coord[1]}, expected {self.B[1]}"

        # 坐标闭合差 = 0
        assert comp.fx_m == pytest.approx(0.0, abs=COORD_TOLERANCE_M)
        assert comp.fy_m == pytest.approx(0.0, abs=COORD_TOLERANCE_M)

        # 方位角闭合差 = 0
        assert comp.azimuth_closure_error_arcsec is not None
        assert abs(comp.azimuth_closure_error_arcsec) < 0.001  # < 0.001"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
