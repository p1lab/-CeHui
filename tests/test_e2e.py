# tests/test_e2e.py
# 端到端集成测试
#
# 完整管线: 坐标 → 生成 → 验证 → 合规 → 四种格式输出
# 验证: 生成通过 → 验证通过 → 合规通过 → 输出非空且含教学声明

import json
import math
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.models.common import (
    LevelingGrade, TraverseGrade, InstrumentGrade,
    AngleDefinition, RouteInfo, SurveyMetadata,
)
from src.models.leveling import RodSpec
from src.models.common import RodType
from src.generators.leveling_generator import generate_leveling_workbook
from src.generators.traversing_generator import generate_traversing_workbook
from src.validators.leveling_validator import validate_leveling_workbook
from src.validators.traversing_validator import (
    validate_traversing_workbook, normalize_angle,
)
from src.checkers.leveling_compliance import check_leveling_compliance
from src.checkers.traversing_compliance import check_traversing_compliance
from src.formatters.json_formatter import workbook_to_json
from src.formatters.text_formatter import workbook_to_text, workbook_to_markdown
from src.formatters.excel_formatter import workbook_to_excel


# ──────────────────────────────────────────────────────────────────────
# 辅助
# ──────────────────────────────────────────────────────────────────────

def _azimuth(x1, y1, x2, y2):
    return normalize_angle(math.atan2(y2 - y1, x2 - x1))


# ──────────────────────────────────────────────────────────────────────
# 水准三等 E2E
# ──────────────────────────────────────────────────────────────────────

class TestLevelingE2E:
    """水准完整管线: 生成 → 验证 → 合规 → 四种格式输出"""

    @pytest.fixture
    def grade3_wb(self):
        route = RouteInfo("BM.A", 100.000, "BM.B", 101.500, 0.4)
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_3,
            num_stations=4, seed=42,
        )
        return wb

    def test_pipeline_passes(self, grade3_wb):
        """生成 → 验证通过 → 合规通过"""
        val_result = validate_leveling_workbook(grade3_wb)
        assert val_result.all_passed, "正向验证未通过"

        comp_report = check_leveling_compliance(grade3_wb)
        assert comp_report.passed, "合规检核未通过"

    def test_json_output(self, grade3_wb):
        """JSON 输出可解析, 含关键字段"""
        j = workbook_to_json(grade3_wb)
        data = json.loads(j)

        assert "sections" in data or "extra_sections" in data
        assert "disclaimer" in data
        assert "教学" in data["disclaimer"] or "模拟" in data["disclaimer"]

    def test_text_output(self, grade3_wb):
        """纯文本输出非空, 含表头和观测数据"""
        text = workbook_to_text(grade3_wb)
        assert len(text) > 100
        assert "水准" in text or "观测" in text or "站" in text
        assert "教学" in text or "模拟" in text

    def test_markdown_output(self, grade3_wb):
        """Markdown 输出含表格标记"""
        md = workbook_to_markdown(grade3_wb)
        assert "|" in md  # 表格管道符
        assert "教学" in md or "模拟" in md

    def test_excel_output(self, grade3_wb, tmp_path):
        """Excel 输出可创建, Sheet 数量正确"""
        fp = str(tmp_path / "leveling_e2e.xlsx")
        workbook_to_excel(grade3_wb, fp)

        assert os.path.exists(fp)
        assert os.path.getsize(fp) > 100

        from openpyxl import load_workbook
        xlsx = load_workbook(fp)
        # 水准应有: 表头, 观测记录, 汇总 (+ 可选合规)
        assert len(xlsx.sheetnames) >= 3


# ──────────────────────────────────────────────────────────────────────
# 水准二等 E2E (因瓦基辅)
# ──────────────────────────────────────────────────────────────────────

class TestLevelingGrade2E2E:
    """二等因瓦尺完整管线"""

    def test_grade2_pipeline(self):
        route = RouteInfo("BM.C", 50.000, "BM.D", 50.800, 0.3)
        rod_back = RodSpec("No.1", RodType.INVAR_BASIC_AUX, c_aux_m=3.0155)
        rod_fore = RodSpec("No.2", RodType.INVAR_BASIC_AUX, c_aux_m=3.0155)
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_2,
            num_stations=3, rod_back=rod_back, rod_fore=rod_fore,
            seed=42,
        )

        val_result = validate_leveling_workbook(wb)
        assert val_result.all_passed

        comp_report = check_leveling_compliance(wb)
        assert comp_report.passed

        # 四种格式输出
        j = workbook_to_json(wb)
        assert json.loads(j) is not None

        text = workbook_to_text(wb)
        assert "基" in text or "辅" in text or "因瓦" in text or len(text) > 100

        md = workbook_to_markdown(wb)
        assert "|" in md

        with tempfile.TemporaryDirectory() as tmpdir:
            fp = os.path.join(tmpdir, "grade2.xlsx")
            workbook_to_excel(wb, fp)
            assert os.path.exists(fp)


# ──────────────────────────────────────────────────────────────────────
# 水准等外 E2E
# ──────────────────────────────────────────────────────────────────────

class TestLevelingExtraE2E:
    """等外水准 (变动仪高法) 完整管线"""

    def test_extra_pipeline(self):
        route = RouteInfo("BM.E", 100.000, "BM.F", 101.000, 0.2)
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.EXTRA,
            num_stations=3, seed=42,
        )

        val_result = validate_leveling_workbook(wb)
        assert val_result.all_passed

        comp_report = check_leveling_compliance(wb)
        assert comp_report.passed

        # JSON
        data = json.loads(workbook_to_json(wb))
        assert "extra_sections" in data

        # Text — 变动仪高法
        text = workbook_to_text(wb)
        assert len(text) > 50

        # Markdown
        md = workbook_to_markdown(wb)
        assert len(md) > 50


# ──────────────────────────────────────────────────────────────────────
# 导线一级 E2E
# ──────────────────────────────────────────────────────────────────────

class TestTraversingE2E:
    """导线完整管线: 坐标 → 生成 → 验证 → 合规 → 四种格式输出"""

    @pytest.fixture
    def grade1_wb(self):
        pts = [
            ("A", 1000.0, 1000.0),
            ("P1", 1100.0, 1050.0),
            ("P2", 1200.0, 1100.0),
            ("B", 1300.0, 1200.0),
        ]
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
        return wb

    def test_pipeline_passes(self, grade1_wb):
        """生成 → 验证通过 → 合规通过"""
        val_result = validate_traversing_workbook(grade1_wb)
        assert val_result.all_passed, "正向验证未通过"

        comp_report = check_traversing_compliance(grade1_wb)
        assert comp_report.passed, "合规检核未通过"

    def test_json_output(self, grade1_wb):
        """JSON 输出可解析, 含角度和距离观测"""
        j = workbook_to_json(grade1_wb)
        data = json.loads(j)

        assert "angle_observations" in data
        assert "distance_observations" in data
        assert "disclaimer" in data

    def test_text_output(self, grade1_wb):
        """纯文本输出含导线信息"""
        text = workbook_to_text(grade1_wb)
        assert len(text) > 100
        assert "导线" in text or "角度" in text or "距离" in text

    def test_markdown_output(self, grade1_wb):
        """Markdown 输出含表格"""
        md = workbook_to_markdown(grade1_wb)
        assert "|" in md

    def test_excel_output(self, grade1_wb, tmp_path):
        """Excel 输出 Sheet 数量正确"""
        fp = str(tmp_path / "traverse_e2e.xlsx")
        workbook_to_excel(grade1_wb, fp)

        assert os.path.exists(fp)

        from openpyxl import load_workbook
        xlsx = load_workbook(fp)
        # 导线应有: 表头, 角度观测, 距离观测, 成果计算
        assert len(xlsx.sheetnames) >= 4


# ──────────────────────────────────────────────────────────────────────
# 导线二级 E2E
# ──────────────────────────────────────────────────────────────────────

class TestTraversingGrade2E2E:

    def test_grade2_pipeline(self):
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
            seed=42,
        )

        val_result = validate_traversing_workbook(wb)
        assert val_result.all_passed

        comp_report = check_traversing_compliance(wb)
        assert comp_report.passed

        # 四种格式
        j = workbook_to_json(wb)
        assert json.loads(j) is not None

        text = workbook_to_text(wb)
        assert len(text) > 100

        md = workbook_to_markdown(wb)
        assert "|" in md


# ──────────────────────────────────────────────────────────────────────
# 导线图根 E2E
# ──────────────────────────────────────────────────────────────────────

class TestTraversingRootE2E:

    def test_root_pipeline(self):
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

        val_result = validate_traversing_workbook(wb)
        assert val_result.all_passed

        comp_report = check_traversing_compliance(wb)
        assert comp_report.passed

        # 输出
        text = workbook_to_text(wb)
        assert len(text) > 100


# ──────────────────────────────────────────────────────────────────────
# 教学声明一致性
# ──────────────────────────────────────────────────────────────────────

class TestDisclaimerConsistency:
    """所有输出格式都包含教学声明"""

    def test_leveling_disclaimer_in_all(self):
        route = RouteInfo("BM.A", 100.000, "BM.B", 101.500, 0.3)
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_3,
            num_stations=3, seed=42,
        )

        j = workbook_to_json(wb)
        text = workbook_to_text(wb)
        md = workbook_to_markdown(wb)

        keyword = "教学"
        assert keyword in j, "JSON 缺少教学声明"
        assert keyword in text, "Text 缺少教学声明"
        assert keyword in md, "Markdown 缺少教学声明"

    def test_traversing_disclaimer_in_all(self):
        pts = [("A", 0, 0), ("P1", 100, 50), ("B", 200, 100)]
        az_s = _azimuth(0, 0, 100, 50)
        az_e = _azimuth(100, 50, 200, 100)

        wb = generate_traversing_workbook(
            points=pts, start_azimuth=az_s, end_azimuth=az_e,
            grade=TraverseGrade.GRADE_1, seed=42,
        )

        j = workbook_to_json(wb)
        text = workbook_to_text(wb)
        md = workbook_to_markdown(wb)

        keyword = "教学"
        assert keyword in j, "JSON 缺少教学声明"
        assert keyword in text, "Text 缺少教学声明"
        assert keyword in md, "Markdown 缺少教学声明"


# ──────────────────────────────────────────────────────────────────────
# 可复现性 E2E
# ──────────────────────────────────────────────────────────────────────

class TestReproducibilityE2E:
    """相同种子 → 完全相同的输出"""

    def test_leveling_reproducible(self):
        route = RouteInfo("BM.A", 100.000, "BM.B", 101.500, 0.3)
        wb1 = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_3,
            num_stations=3, seed=42,
        )
        wb2 = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_3,
            num_stations=3, seed=42,
        )

        j1 = workbook_to_json(wb1)
        j2 = workbook_to_json(wb2)
        assert j1 == j2, "相同种子应产生相同 JSON"

        t1 = workbook_to_text(wb1)
        t2 = workbook_to_text(wb2)
        assert t1 == t2, "相同种子应产生相同 Text"

    def test_traversing_reproducible(self):
        pts = [("A", 0, 0), ("P1", 100, 50), ("B", 200, 100)]
        az_s = _azimuth(0, 0, 100, 50)
        az_e = _azimuth(100, 50, 200, 100)

        wb1 = generate_traversing_workbook(
            points=pts, start_azimuth=az_s, end_azimuth=az_e,
            grade=TraverseGrade.GRADE_1, seed=42,
        )
        wb2 = generate_traversing_workbook(
            points=pts, start_azimuth=az_s, end_azimuth=az_e,
            grade=TraverseGrade.GRADE_1, seed=42,
        )

        j1 = workbook_to_json(wb1)
        j2 = workbook_to_json(wb2)
        assert j1 == j2, "相同种子应产生相同 JSON"
