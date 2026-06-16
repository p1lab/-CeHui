# tests/test_leveling_generator.py
# 水准逆向生成器端到端测试
#
# 测试策略: 生成 → 正向验证 → 全通过
# 每个测试覆盖: 闭合差=0, 终点高程=真值, 核空间约束

import math
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.models.common import (
    LevelingGrade, RodType, SurveyMetadata, RouteInfo,
)
from src.models.leveling import RodSpec
from src.generators.leveling_generator import generate_leveling_workbook
from src.validators.leveling_validator import validate_leveling_workbook


# ──────────────────────────────────────────────────────────────────────
# 辅助
# ──────────────────────────────────────────────────────────────────────

def _default_metadata():
    return SurveyMetadata(
        date="2025-06-01", observer="测试", recorder="测试",
        instrument_model="DS3", instrument_serial="T-001",
    )


def _run_and_validate(workbook):
    """运行正向验证器并返回结果, 打印失败项"""
    result = validate_leveling_workbook(workbook)
    if not result.all_passed:
        for c in result.checks:
            if not c.passed:
                print(f"  FAIL: {c.name}: {c.message}")
        for e in result.errors:
            print(f"  ERROR: {e}")
    return result


# ──────────────────────────────────────────────────────────────────────
# 三等水准 (双面尺, 最典型)
# ──────────────────────────────────────────────────────────────────────

class TestGrade3DoubleFace:
    """三等水准: 双面木质尺, 4 站附合路线"""

    def test_basic_route(self):
        """基本路线: H_A=100, H_B=101.5, 4站"""
        route = RouteInfo("BM.A", 100.000, "BM.B", 101.500, 0.4)
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_3,
            num_stations=4, seed=42,
        )
        result = _run_and_validate(wb)
        assert result.all_passed, "三等水准验证未通过"

        # 闭合差应接近零 (取整误差)
        section = wb.sections[0]
        assert abs(section.closure_error_mm) < 2.0, \
            f"闭合差过大: {section.closure_error_mm:.3f} mm"

    def test_downhill_route(self):
        """下坡路线: H_A=200, H_B=198"""
        route = RouteInfo("BM.C", 200.000, "BM.D", 198.000, 0.3)
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_3,
            num_stations=3, seed=123,
        )
        result = _run_and_validate(wb)
        assert result.all_passed

    def test_flat_route(self):
        """平坦路线: H_A=H_B"""
        route = RouteInfo("BM.E", 50.000, "BM.F", 50.000, 0.2)
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_3,
            num_stations=3, seed=7,
        )
        result = _run_and_validate(wb)
        assert result.all_passed

    def test_single_station(self):
        """最短路线: 1 站"""
        route = RouteInfo("BM.G", 10.000, "BM.H", 10.500, 0.05)
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_3,
            num_stations=1, seed=99,
        )
        result = _run_and_validate(wb)
        assert result.all_passed

    def test_many_stations(self):
        """多站累积: 10 站"""
        route = RouteInfo("BM.I", 100.000, "BM.J", 105.000, 1.0)
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_3,
            num_stations=10, seed=42,
        )
        result = _run_and_validate(wb)
        assert result.all_passed

    def test_endpoint_height_exact(self):
        """终点高程精确等于真值"""
        route = RouteInfo("BM.K", 100.000, "BM.L", 103.750, 0.5)
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_3,
            num_stations=5, seed=55,
        )
        result = _run_and_validate(wb)

        computed_h = result.computed_heights.get("BM.L")
        assert computed_h is not None
        assert abs(computed_h - 103.750) < 1e-10, \
            f"终点高程偏差: {computed_h - 103.750:.2e} m"

    def test_kernel_constraint_per_station(self):
        """核空间约束: 每站 a-b 精确等于黑面高差"""
        route = RouteInfo("BM.M", 50.000, "BM.N", 52.000, 0.3)
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_3,
            num_stations=4, seed=42,
        )
        # 先运行验证器填充计算字段
        validate_leveling_workbook(wb)
        section = wb.sections[0]
        for st in section.stations:
            a = st.backsight.black_mid_m
            b = st.foresight.black_mid_m
            h = st.height_diff_black_m
            assert h is not None
            # a - b 应精确等于 h (validator 设置的值)
            assert abs((a - b) - h) < 1e-10


# ──────────────────────────────────────────────────────────────────────
# 二等水准 (因瓦基辅)
# ──────────────────────────────────────────────────────────────────────

class TestGrade2Invar:
    """二等水准: 因瓦基辅分划尺"""

    def test_basic_route(self):
        """基本路线: 5 站"""
        route = RouteInfo("BM.A", 100.000, "BM.B", 101.200, 0.5)
        rod_back = RodSpec("No.1", RodType.INVAR_BASIC_AUX, c_aux_m=3.0155)
        rod_fore = RodSpec("No.2", RodType.INVAR_BASIC_AUX, c_aux_m=3.0155)
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_2,
            num_stations=5, rod_back=rod_back, rod_fore=rod_fore,
            seed=42,
        )
        result = _run_and_validate(wb)
        assert result.all_passed, "二等因瓦验证未通过"

    def test_short_route(self):
        """2 站短路线"""
        route = RouteInfo("BM.C", 50.000, "BM.D", 50.300, 0.1)
        rod_back = RodSpec("No.1", RodType.INVAR_BASIC_AUX, c_aux_m=3.0155)
        rod_fore = RodSpec("No.2", RodType.INVAR_BASIC_AUX, c_aux_m=3.0155)
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_2,
            num_stations=2, rod_back=rod_back, rod_fore=rod_fore,
            seed=7,
        )
        result = _run_and_validate(wb)
        assert result.all_passed


# ──────────────────────────────────────────────────────────────────────
# 四等水准 (双面尺, 大 sigma)
# ──────────────────────────────────────────────────────────────────────

class TestGrade4DoubleFace:
    """四等水准: 双面尺, sigma=1.0mm"""

    def test_basic_route(self):
        route = RouteInfo("BM.A", 100.000, "BM.B", 102.000, 0.6)
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_4,
            num_stations=6, seed=42,
        )
        result = _run_and_validate(wb)
        assert result.all_passed, "四等水准验证未通过"


# ──────────────────────────────────────────────────────────────────────
# 等外水准 (变动仪高法)
# ──────────────────────────────────────────────────────────────────────

class TestExtraLeveling:
    """等外水准: 单面尺, 变动仪高法"""

    def test_basic_route(self):
        route = RouteInfo("BM.A", 100.000, "BM.B", 101.000, 0.2)
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.EXTRA,
            num_stations=3, seed=42,
        )
        result = _run_and_validate(wb)
        assert result.all_passed, "等外水准验证未通过"

    def test_height_change_check(self):
        """变动仪高检核: |h1-h2| <= 5mm"""
        route = RouteInfo("BM.C", 50.000, "BM.D", 51.500, 0.3)
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.EXTRA,
            num_stations=4, seed=99,
        )
        result = _run_and_validate(wb)
        section = wb.extra_sections[0]
        for st in section.stations:
            assert st.height_diff_diff_mm is not None
            assert st.height_diff_diff_mm <= 5.01, \
                f"站{st.station_number}: |h1-h2| = {st.height_diff_diff_mm:.2f} mm > 5mm"


# ──────────────────────────────────────────────────────────────────────
# 可复现性
# ──────────────────────────────────────────────────────────────────────

class TestReproducibility:
    """相同种子 → 相同输出"""

    def test_same_seed_same_output(self):
        route = RouteInfo("BM.A", 100.000, "BM.B", 101.500, 0.3)
        wb1 = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_3,
            num_stations=3, seed=42,
        )
        wb2 = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_3,
            num_stations=3, seed=42,
        )
        # 逐站逐读数比较
        for s1, s2 in zip(wb1.sections[0].stations, wb2.sections[0].stations):
            assert s1.backsight.black_mid_m == s2.backsight.black_mid_m
            assert s1.foresight.black_mid_m == s2.foresight.black_mid_m
            assert s1.backsight.red_mid_m == s2.backsight.red_mid_m
            assert s1.foresight.red_mid_m == s2.foresight.red_mid_m

    def test_different_seed_different_output(self):
        route = RouteInfo("BM.A", 100.000, "BM.B", 101.500, 0.3)
        wb1 = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_3,
            num_stations=3, seed=42,
        )
        wb2 = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_3,
            num_stations=3, seed=99,
        )
        # 至少有一个读数不同
        diffs = []
        for s1, s2 in zip(wb1.sections[0].stations, wb2.sections[0].stations):
            if s1.backsight.black_mid_m != s2.backsight.black_mid_m:
                diffs.append(True)
        assert len(diffs) > 0, "不同种子应产生不同输出"


# ──────────────────────────────────────────────────────────────────────
# 生成元数据
# ──────────────────────────────────────────────────────────────────────

class TestGenerationMetadata:

    def test_metadata_present(self):
        route = RouteInfo("BM.A", 100.000, "BM.B", 101.500, 0.3)
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_3,
            num_stations=3, seed=42,
        )
        gm = wb.generation_metadata
        assert gm is not None
        assert gm.target_grade == "grade_3"
        assert gm.random_seed == 42
        assert gm.leveling_sigma_mm == 0.5
        assert gm.math_true_value_mode is True

    def test_disclaimer_present(self):
        route = RouteInfo("BM.A", 100.000, "BM.B", 101.500, 0.3)
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_3,
            num_stations=3, seed=42,
        )
        assert "教学" in wb.teaching_disclaimer or "模拟" in wb.teaching_disclaimer


# ──────────────────────────────────────────────────────────────────────
# 阶段十六：水准闭合差可控非零化
# ──────────────────────────────────────────────────────────────────────

class TestLevelingControlledClosure:
    """水准闭合差可控非零化 (target_closure_ratio)"""

    def test_default_zero_closure(self):
        """target_closure_ratio=0 时闭合差为零"""
        route = RouteInfo("BM.A", 100.000, "BM.B", 101.500, 0.3)
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_3,
            num_stations=3, seed=42,
            target_closure_ratio=0.0,
        )
        val = validate_leveling_workbook(wb)
        # 闭合差应精确为零
        for item in val.checks:
            if "闭合差" in item.name:
                assert item.passed, f"{item.name}: {item.message}"

    def test_nonzero_closure_with_ratio(self):
        """target_closure_ratio=0.3 时闭合差非零"""
        route = RouteInfo("BM.A", 100.000, "BM.B", 101.500, 0.3)
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_3,
            num_stations=3, seed=42,
            target_closure_ratio=0.3,
        )
        val = validate_leveling_workbook(wb)
        # 查找闭合差检查项
        closure_items = [c for c in val.checks if "闭合差" in c.name]
        # 应存在非零闭合差
        has_nonzero = any(
            c.computed is not None and abs(c.computed) > 1e-6
            for c in closure_items
        )
        assert has_nonzero, "闭合差应为非零"

    def test_closure_within_limit(self):
        """target_closure_ratio=0.3 时闭合差在限差内"""
        from src.checkers.leveling_compliance import check_leveling_compliance
        route = RouteInfo("BM.A", 100.000, "BM.B", 101.500, 0.3)
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_3,
            num_stations=3, seed=42,
            target_closure_ratio=0.3,
        )
        report = check_leveling_compliance(wb)
        # 闭合差应在限差内
        closure_items = [i for i in report.items if "闭合差" in i.name and not i.passed]
        assert len(closure_items) == 0, \
            f"闭合差超限: {[i.message for i in closure_items]}"
