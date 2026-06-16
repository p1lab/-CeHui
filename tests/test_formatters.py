# tests/test_formatters.py
# 格式化器单元测试
#
# 测试: DMS 转换、JSON 输出、纯文本/Markdown 输出、Excel 输出

import math
import json
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.models.common import (
    LevelingGrade, TraverseGrade, InstrumentGrade,
    AngleDefinition, RouteInfo,
)
from src.generators.leveling_generator import generate_leveling_workbook
from src.generators.traversing_generator import generate_traversing_workbook
from src.validators.traversing_validator import normalize_angle
from src.formatters._utils import (
    rad_to_dms, format_meter, format_mm, format_arcsec, build_disclaimer,
)
from src.formatters.json_formatter import workbook_to_json
from src.formatters.text_formatter import workbook_to_text, workbook_to_markdown
from src.formatters.excel_formatter import workbook_to_excel


# ──────────────────────────────────────────────────────────────────────
# DMS 转换
# ──────────────────────────────────────────────────────────────────────

class TestRadToDms:

    def test_zero(self):
        assert rad_to_dms(0.0) == '0°00\'00.0"'

    def test_90_degrees(self):
        result = rad_to_dms(math.pi / 2)
        assert result == '90°00\'00.0"'

    def test_45_degrees_30_min(self):
        rad = math.radians(45 + 30 / 60)
        result = rad_to_dms(rad)
        assert "45°30'00.0\"" == result

    def test_arbitrary_angle(self):
        # 123°45'06.5"
        d, m, s = 123, 45, 6.5
        total_sec = d * 3600 + m * 60 + s
        rad = total_sec / (180.0 * 3600 / math.pi)
        result = rad_to_dms(rad)
        assert "123°45'06.5\"" == result

    def test_small_angle(self):
        # 0°02'30" = 150"
        rad = 150.0 / (180.0 * 3600 / math.pi)
        result = rad_to_dms(rad)
        assert "0°02'30.0\"" == result


class TestFormatFunctions:

    def test_format_meter(self):
        assert format_meter(1.2346, 3) == "1.235"  # 常规进位
        assert format_meter(1.234, 4) == "1.2340"
        assert format_meter(None, 3) == "-"

    def test_format_mm(self):
        assert format_mm(0.001, 2) == "1.00"
        assert format_mm(None) == "-"

    def test_format_arcsec(self):
        # 1" = pi/(180*3600) rad
        rad = 1.0 / (180.0 * 3600 / math.pi)
        result = format_arcsec(rad, 2)
        assert abs(float(result) - 1.0) < 0.01


# ──────────────────────────────────────────────────────────────────────
# 教学声明
# ──────────────────────────────────────────────────────────────────────

class TestBuildDisclaimer:

    def test_leveling_disclaimer(self):
        route = RouteInfo("A", 100.0, "B", 101.0, 0.3)
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_3,
            num_stations=3, seed=42,
        )
        disclaimer = build_disclaimer(wb)
        assert "教学" in disclaimer or "模拟" in disclaimer
        assert "grade_3" in disclaimer
        assert "0.5" in disclaimer  # sigma = 0.5mm

    def test_traversing_disclaimer(self):
        pts = [("A", 0, 0), ("P1", 100, 50), ("B", 200, 100)]
        az_s = normalize_angle(math.atan2(50, 100))
        az_e = normalize_angle(math.atan2(50, 100))
        wb = generate_traversing_workbook(
            points=pts, start_azimuth=az_s, end_azimuth=az_e,
            grade=TraverseGrade.GRADE_1, seed=42,
        )
        disclaimer = build_disclaimer(wb)
        assert "grade_1" in disclaimer


# ──────────────────────────────────────────────────────────────────────
# JSON 格式化
# ──────────────────────────────────────────────────────────────────────

class TestJsonFormatter:

    def test_leveling_json_valid(self):
        route = RouteInfo("A", 100.0, "B", 101.5, 0.3)
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_3,
            num_stations=3, seed=42,
        )
        result = workbook_to_json(wb)
        data = json.loads(result)
        assert "grade" in data
        assert "sections" in data
        assert "disclaimer" in data

    def test_traversing_json_valid(self):
        pts = [("A", 0, 0), ("P1", 100, 50), ("B", 200, 100)]
        az = normalize_angle(math.atan2(50, 100))
        wb = generate_traversing_workbook(
            points=pts, start_azimuth=az, end_azimuth=az,
            grade=TraverseGrade.GRADE_1, seed=42,
        )
        result = workbook_to_json(wb)
        data = json.loads(result)
        assert "angle_observations" in data
        assert "distance_observations" in data
        assert "disclaimer" in data

    def test_json_contains_stations(self):
        route = RouteInfo("A", 100.0, "B", 101.5, 0.3)
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_3,
            num_stations=4, seed=42,
        )
        data = json.loads(workbook_to_json(wb))
        stations = data["sections"][0]["stations"]
        assert len(stations) == 4

    def test_json_ensure_ascii_false(self):
        route = RouteInfo("A", 100.0, "B", 101.5, 0.3)
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_3,
            num_stations=2, seed=42,
        )
        result = workbook_to_json(wb)
        assert "模拟" in result  # 中文不被转义


# ──────────────────────────────────────────────────────────────────────
# 纯文本格式化
# ──────────────────────────────────────────────────────────────────────

class TestTextFormatter:

    def test_leveling_text_not_empty(self):
        route = RouteInfo("A", 100.0, "B", 101.5, 0.3)
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_3,
            num_stations=3, seed=42,
        )
        text = workbook_to_text(wb)
        assert len(text) > 100
        assert "水准观测手簿" in text

    def test_leveling_text_contains_stations(self):
        route = RouteInfo("A", 100.0, "B", 101.5, 0.3)
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_3,
            num_stations=3, seed=42,
        )
        text = workbook_to_text(wb)
        assert "TP.1" in text or "TP.2" in text

    def test_leveling_text_has_disclaimer(self):
        route = RouteInfo("A", 100.0, "B", 101.5, 0.3)
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_3,
            num_stations=2, seed=42,
        )
        text = workbook_to_text(wb)
        assert "教学" in text or "模拟" in text

    def test_extra_text(self):
        route = RouteInfo("A", 100.0, "B", 101.0, 0.2)
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.EXTRA,
            num_stations=3, seed=42,
        )
        text = workbook_to_text(wb)
        assert "等外" in text

    def test_traversing_text_not_empty(self):
        pts = [("A", 0, 0), ("P1", 100, 50), ("B", 200, 100)]
        az = normalize_angle(math.atan2(50, 100))
        wb = generate_traversing_workbook(
            points=pts, start_azimuth=az, end_azimuth=az,
            grade=TraverseGrade.GRADE_1, seed=42,
        )
        text = workbook_to_text(wb)
        assert len(text) > 100
        assert "导线观测手簿" in text
        assert "水平角观测" in text
        assert "距离观测" in text


# ──────────────────────────────────────────────────────────────────────
# Markdown 格式化
# ──────────────────────────────────────────────────────────────────────

class TestMarkdownFormatter:

    def test_leveling_markdown_has_tables(self):
        route = RouteInfo("A", 100.0, "B", 101.5, 0.3)
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_3,
            num_stations=3, seed=42,
        )
        md = workbook_to_markdown(wb)
        assert "|" in md  # 有表格分隔符
        assert "---" in md  # 有表格分隔线

    def test_traversing_markdown_has_sections(self):
        pts = [("A", 0, 0), ("P1", 100, 50), ("B", 200, 100)]
        az = normalize_angle(math.atan2(50, 100))
        wb = generate_traversing_workbook(
            points=pts, start_azimuth=az, end_azimuth=az,
            grade=TraverseGrade.GRADE_1, seed=42,
        )
        md = workbook_to_markdown(wb)
        assert "## 水平角观测" in md
        assert "## 距离观测" in md
        assert "## 成果计算" in md


# ──────────────────────────────────────────────────────────────────────
# Excel 格式化
# ──────────────────────────────────────────────────────────────────────

class TestExcelFormatter:

    def test_leveling_excel_creates_file(self):
        route = RouteInfo("A", 100.0, "B", 101.5, 0.3)
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_3,
            num_stations=3, seed=42,
        )
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            filepath = f.name
        try:
            workbook_to_excel(wb, filepath)
            assert os.path.exists(filepath)
            assert os.path.getsize(filepath) > 0

            # 验证可以打开
            from openpyxl import load_workbook
            wb_excel = load_workbook(filepath)
            sheet_names = wb_excel.sheetnames
            assert "表头" in sheet_names
            assert "观测记录" in sheet_names
            assert "汇总" in sheet_names
        finally:
            os.unlink(filepath)

    def test_traversing_excel_creates_file(self):
        pts = [("A", 0, 0), ("P1", 100, 50), ("B", 200, 100)]
        az = normalize_angle(math.atan2(50, 100))
        wb = generate_traversing_workbook(
            points=pts, start_azimuth=az, end_azimuth=az,
            grade=TraverseGrade.GRADE_1, seed=42,
        )
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            filepath = f.name
        try:
            workbook_to_excel(wb, filepath)
            assert os.path.exists(filepath)

            from openpyxl import load_workbook
            wb_excel = load_workbook(filepath)
            sheet_names = wb_excel.sheetnames
            assert "表头" in sheet_names
            assert "角度观测" in sheet_names
            assert "距离观测" in sheet_names
            assert "成果计算" in sheet_names
        finally:
            os.unlink(filepath)

    def test_excel_observation_sheet_has_data(self):
        route = RouteInfo("A", 100.0, "B", 101.5, 0.3)
        wb = generate_leveling_workbook(
            route=route, grade=LevelingGrade.GRADE_3,
            num_stations=3, seed=42,
        )
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            filepath = f.name
        try:
            workbook_to_excel(wb, filepath)
            from openpyxl import load_workbook
            wb_excel = load_workbook(filepath)
            ws = wb_excel["观测记录"]
            # 表头行 + 3 站数据 = 4 行
            assert ws.max_row >= 4
        finally:
            os.unlink(filepath)
