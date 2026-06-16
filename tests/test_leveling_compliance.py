# tests/test_leveling_compliance.py
# 水准合规检核测试
#
# 测试策略: 生成 → 合规检核 → 全部通过
# 附加: 负向测试 (手动超限, 验证检核器能正确报告失败)

import math
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.models.common import LevelingGrade, RodType, SurveyMetadata, RouteInfo
from src.models.leveling import (
    RodSpec, LevelingReading, LevelingStation,
    LevelingSection, ExtraLevelingSection, LevelingWorkbook,
)
from src.generators.leveling_generator import generate_leveling_workbook
from src.checkers.leveling_compliance import (
    check_leveling_compliance, LevelingComplianceReport, _LEVELING_LIMITS,
)


# ──────────────────────────────────────────────────────────────────────
# 三等水准合规
# ──────────────────────────────────────────────────────────────────────

class TestGrade3Compliance:
    """三等水准合规检核: 双面木质尺"""

    def test_basic_compliance(self):
        """基本路线合规"""
        route = RouteInfo("BM.A", 100.000, "BM.B", 101.500, 0.4)
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_3,
            num_stations=4, seed=42,
        )
        report = check_leveling_compliance(wb)
        assert report.passed, (
            f"三等合规未通过: " +
            "; ".join(
                f"{i.name}={i.computed:.3f}>{i.limit:.3f}"
                for i in report.items if not i.passed
            )
        )

    def test_all_items_have_limit(self):
        """每项检核都有 limit 值"""
        route = RouteInfo("BM.A", 100.000, "BM.B", 101.500, 0.3)
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_3,
            num_stations=3, seed=42,
        )
        report = check_leveling_compliance(wb)
        for item in report.items:
            assert item.limit > 0, f"{item.name} 的 limit 应 > 0"

    def test_closure_checked(self):
        """闭合差已检核"""
        route = RouteInfo("BM.A", 100.000, "BM.B", 101.500, 0.3)
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_3,
            num_stations=3, seed=42,
        )
        report = check_leveling_compliance(wb)
        closure_items = [i for i in report.items if "闭合差" in i.name]
        assert len(closure_items) >= 1, "应有闭合差检核项"
        assert all(i.passed for i in closure_items)

    def test_sight_length_checked(self):
        """视距长度已检核"""
        route = RouteInfo("BM.A", 100.000, "BM.B", 101.500, 0.4)
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_3,
            num_stations=4, seed=42,
        )
        report = check_leveling_compliance(wb)
        sight_items = [i for i in report.items if "视距长度" in i.name]
        assert len(sight_items) > 0, "应有视距长度检核项"
        assert all(i.passed for i in sight_items)


# ──────────────────────────────────────────────────────────────────────
# 二等水准合规 (因瓦基辅)
# ──────────────────────────────────────────────────────────────────────

class TestGrade2Compliance:
    """二等水准合规检核: 因瓦基辅分划尺"""

    def test_basic_compliance(self):
        route = RouteInfo("BM.A", 100.000, "BM.B", 101.200, 0.5)
        rod_back = RodSpec("No.1", RodType.INVAR_BASIC_AUX, c_aux_m=3.0155)
        rod_fore = RodSpec("No.2", RodType.INVAR_BASIC_AUX, c_aux_m=3.0155)
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_2,
            num_stations=5, rod_back=rod_back, rod_fore=rod_fore,
            seed=42,
        )
        report = check_leveling_compliance(wb)
        assert report.passed, (
            f"二等合规未通过: " +
            "; ".join(
                f"{i.name}={i.computed:.4f}>{i.limit:.4f}"
                for i in report.items if not i.passed
            )
        )

    def test_base_aux_checks_present(self):
        """基辅读数差和基辅高差之差已检核"""
        route = RouteInfo("BM.A", 100.000, "BM.B", 101.200, 0.5)
        rod_back = RodSpec("No.1", RodType.INVAR_BASIC_AUX, c_aux_m=3.0155)
        rod_fore = RodSpec("No.2", RodType.INVAR_BASIC_AUX, c_aux_m=3.0155)
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_2,
            num_stations=3, rod_back=rod_back, rod_fore=rod_fore,
            seed=42,
        )
        report = check_leveling_compliance(wb)
        ba_items = [i for i in report.items if "基辅" in i.name]
        assert len(ba_items) > 0, "应有基辅检核项"
        assert all(i.passed for i in ba_items)


# ──────────────────────────────────────────────────────────────────────
# 四等水准合规
# ──────────────────────────────────────────────────────────────────────

class TestGrade4Compliance:
    """四等水准合规检核"""

    def test_basic_compliance(self):
        route = RouteInfo("BM.A", 100.000, "BM.B", 102.000, 0.6)
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_4,
            num_stations=6, seed=42,
        )
        report = check_leveling_compliance(wb)
        assert report.passed, "四等合规未通过"


# ──────────────────────────────────────────────────────────────────────
# 等外水准合规
# ──────────────────────────────────────────────────────────────────────

class TestExtraCompliance:
    """等外水准合规检核: 变动仪高法"""

    def test_basic_compliance(self):
        route = RouteInfo("BM.A", 100.000, "BM.B", 101.000, 0.2)
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.EXTRA,
            num_stations=3, seed=42,
        )
        report = check_leveling_compliance(wb)
        assert report.passed, (
            f"等外合规未通过: " +
            "; ".join(
                f"{i.name}={i.computed:.3f}>{i.limit:.3f}"
                for i in report.items if not i.passed
            )
        )

    def test_height_change_items_present(self):
        """变动仪高较差检核项存在"""
        route = RouteInfo("BM.A", 100.000, "BM.B", 101.000, 0.2)
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.EXTRA,
            num_stations=3, seed=42,
        )
        report = check_leveling_compliance(wb)
        hd_items = [i for i in report.items if "变动仪高" in i.name]
        assert len(hd_items) == 3, f"应有 3 站变动仪高检核, 实际 {len(hd_items)}"


# ──────────────────────────────────────────────────────────────────────
# 负向测试: 手动构造超限数据
# ──────────────────────────────────────────────────────────────────────

class TestNegativeCompliance:
    """构造超限数据, 验证检核器能正确报告失败"""

    def test_sight_length_exceeds_limit(self):
        """视距超限: 三等 max=75m, 设为 80m"""
        route = RouteInfo("BM.A", 100.000, "BM.B", 101.500, 0.4)
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_3,
            num_stations=3, seed=42,
        )
        # 手动修改第一站后视距为超限值
        # 上下丝差值 = S / 100, 所以设 upper - lower = 80/100 = 0.8
        st = wb.sections[0].stations[0]
        mid = st.backsight.black_mid_m
        st.backsight.upper_wire_m = mid + 0.4   # S = 100 * 0.8 = 80 m
        st.backsight.lower_wire_m = mid - 0.4

        report = check_leveling_compliance(wb)
        # 应有视距超限项
        failed_items = [i for i in report.items if not i.passed]
        sight_fails = [i for i in failed_items if "视距长度" in i.name]
        assert len(sight_fails) >= 1, "应检测到视距超限"
        assert not report.passed

    def test_closure_exceeds_limit(self):
        """闭合差超限: 手动修改前视读数使闭合差超出限差"""
        route = RouteInfo("BM.A", 100.000, "BM.B", 101.000, 0.1)
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_3,
            num_stations=2, seed=42,
        )
        # 修改最后一站前视黑面读数, 使高差变大 → 闭合差超限
        # 三等限差 = 12 * sqrt(L_km) ≈ 12 * sqrt(0.1) ≈ 3.79 mm
        # 加 10mm (= 0.01 m) 偏移, 必然超限
        last_st = wb.sections[0].stations[-1]
        last_st.foresight.black_mid_m -= 0.01  # 前视减小 → 高差增大
        last_st.foresight.red_mid_m -= 0.01

        report = check_leveling_compliance(wb)
        closure_fails = [
            i for i in report.items
            if "闭合差" in i.name and not i.passed
        ]
        assert len(closure_fails) >= 1, "应检测到闭合差超限"
        assert not report.passed

    def test_k_black_red_exceeds_limit(self):
        """K+黑-红超限: 三等限差 2mm"""
        route = RouteInfo("BM.A", 100.000, "BM.B", 101.500, 0.3)
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_3,
            num_stations=3, seed=42,
        )
        # 修改第一站后视红面读数, 使 K+黑-红 超限
        # K_back=4.687, K+黑-红 = 4.687 + black - red
        # 将 red 减小 5mm → K+黑-红 = +5mm > 2mm 限差
        st = wb.sections[0].stations[0]
        st.backsight.red_mid_m -= 0.005

        report = check_leveling_compliance(wb)
        kbr_fails = [
            i for i in report.items
            if "K+黑-红" in i.name and not i.passed
        ]
        assert len(kbr_fails) >= 1, "应检测到 K+黑-红 超限"
        assert not report.passed


# ──────────────────────────────────────────────────────────────────────
# 报告结构
# ──────────────────────────────────────────────────────────────────────

class TestReportStructure:

    def test_report_has_grade(self):
        route = RouteInfo("BM.A", 100.000, "BM.B", 101.500, 0.3)
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_3,
            num_stations=3, seed=42,
        )
        report = check_leveling_compliance(wb)
        assert report.grade == LevelingGrade.GRADE_3

    def test_report_has_items(self):
        route = RouteInfo("BM.A", 100.000, "BM.B", 101.500, 0.3)
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_3,
            num_stations=3, seed=42,
        )
        report = check_leveling_compliance(wb)
        assert len(report.items) > 0, "报告应有检核项"

    def test_closure_limit_populated(self):
        """检核后 section.closure_limit_mm 被填充"""
        route = RouteInfo("BM.A", 100.000, "BM.B", 101.500, 0.3)
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_3,
            num_stations=3, seed=42,
        )
        check_leveling_compliance(wb)
        section = wb.sections[0]
        assert section.closure_limit_mm is not None
        assert section.closure_limit_mm > 0


# ──────────────────────────────────────────────────────────────────────
# 二等水准基辅限差测试 (阶段九新增)
# ──────────────────────────────────────────────────────────────────────

class TestGrade2BaseAuxLimits:
    """二等水准基辅分划限差: 数字 0.4/0.6mm vs 光学 0.5/0.7mm"""

    def test_digital_limits_in_config(self):
        """配置中应包含数字水准仪限差 0.4/0.6mm"""
        g2 = _LEVELING_LIMITS[LevelingGrade.GRADE_2]
        assert g2["digital"]["base_aux_reading_diff_mm"] == 0.4
        assert g2["digital"]["base_aux_height_diff_mm"] == 0.6

    def test_optical_limits_in_config(self):
        """配置中应包含光学水准仪限差 0.5/0.7mm"""
        g2 = _LEVELING_LIMITS[LevelingGrade.GRADE_2]
        assert g2["optical"]["base_aux_reading_diff_mm"] == 0.5
        assert g2["optical"]["base_aux_height_diff_mm"] == 0.7

    def test_default_is_digital(self):
        """默认限差应使用数字水准仪值 (0.4/0.6mm)"""
        g2 = _LEVELING_LIMITS[LevelingGrade.GRADE_2]
        assert g2["base_aux_reading_diff_mm"] == 0.4
        assert g2["base_aux_height_diff_mm"] == 0.6

    def test_digital_compliance(self):
        """使用数字水准仪限差(默认)生成数据应合规"""
        route = RouteInfo("BM.A", 100.000, "BM.B", 101.200, 0.5)
        rod_back = RodSpec("No.1", RodType.INVAR_BASIC_AUX, c_aux_m=3.0155)
        rod_fore = RodSpec("No.2", RodType.INVAR_BASIC_AUX, c_aux_m=3.0155)
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_2,
            num_stations=5, rod_back=rod_back, rod_fore=rod_fore,
            seed=42,
        )
        report = check_leveling_compliance(wb)
        assert report.passed, (
            f"数字限差合规未通过: " +
            "; ".join(
                f"{i.name}={i.computed:.4f}>{i.limit:.4f}"
                for i in report.items if not i.passed
            )
        )

    def test_base_aux_items_use_digital_limit(self):
        """基辅检核项应使用数字水准仪限差"""
        route = RouteInfo("BM.A", 100.000, "BM.B", 101.200, 0.5)
        rod_back = RodSpec("No.1", RodType.INVAR_BASIC_AUX, c_aux_m=3.0155)
        rod_fore = RodSpec("No.2", RodType.INVAR_BASIC_AUX, c_aux_m=3.0155)
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_2,
            num_stations=3, rod_back=rod_back, rod_fore=rod_fore,
            seed=42,
        )
        report = check_leveling_compliance(wb)
        ba_items = [i for i in report.items if "基辅" in i.name]
        assert len(ba_items) > 0
        for item in ba_items:
            if "读数差" in item.name:
                assert item.limit == 0.4, f"基辅读数差限差应为0.4mm, 实际{item.limit}"
            elif "高差" in item.name:
                assert item.limit == 0.6, f"基辅高差之差限差应为0.6mm, 实际{item.limit}"
