# src/formatters/text_formatter.py
# 纯文本 / Markdown 格式化器
#
# 将 LevelingWorkbook / TraversingWorkbook 格式化为可读文本.
# 支持纯文本 (等宽表格) 和 Markdown 两种输出.

from __future__ import annotations

import math
from typing import List, Optional

from ..models.leveling import (
    LevelingWorkbook, LevelingSection, ExtraLevelingSection,
    LevelingStation, ExtraLevelingStation,
)
from ..models.traversing import (
    TraversingWorkbook, StationAngleObservation, EdgeDistanceObservation,
)
from ..models.common import LevelingGrade, RodType
from ._utils import (
    rad_to_dms, format_meter, format_mm, format_arcsec, format_optional,
    build_disclaimer, build_per_face_direction_values, _TWO_PI,
)


# ──────────────────────────────────────────────────────────────────────
# 辅助: 简易表格渲染
# ──────────────────────────────────────────────────────────────────────

def _render_text_table(headers: List[str], rows: List[List[str]]) -> str:
    """渲染等宽对齐的纯文本表格."""
    if not rows:
        return _render_text_headers_only(headers)

    # 计算列宽
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            if i < len(widths):
                widths[i] = max(widths[i], len(cell))

    # 表头
    header_line = " | ".join(h.ljust(widths[i]) for i, h in enumerate(headers))
    sep_line = "-+-".join("-" * w for w in widths)

    lines = [header_line, sep_line]
    for row in rows:
        padded = []
        for i, cell in enumerate(row):
            w = widths[i] if i < len(widths) else len(cell)
            padded.append(cell.ljust(w))
        lines.append(" | ".join(padded))

    return "\n".join(lines)


def _render_text_headers_only(headers: List[str]) -> str:
    widths = [len(h) for h in headers]
    header_line = " | ".join(h.ljust(widths[i]) for i, h in enumerate(headers))
    sep_line = "-+-".join("-" * w for w in widths)
    return f"{header_line}\n{sep_line}"


def _render_md_table(headers: List[str], rows: List[List[str]]) -> str:
    """渲染 Markdown 表格."""
    if not rows:
        header_line = "| " + " | ".join(headers) + " |"
        sep_line = "| " + " | ".join("---" for _ in headers) + " |"
        return f"{header_line}\n{sep_line}"

    header_line = "| " + " | ".join(headers) + " |"
    sep_line = "| " + " | ".join("---" for _ in headers) + " |"

    lines = [header_line, sep_line]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")

    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────
# 等级标签
# ──────────────────────────────────────────────────────────────────────

_GRADE_LABELS = {
    LevelingGrade.GRADE_2: "二等",
    LevelingGrade.GRADE_3: "三等",
    LevelingGrade.GRADE_4: "四等",
    LevelingGrade.EXTRA: "等外",
}

# 读数精度 (小数位)
_READING_DP = {
    LevelingGrade.GRADE_2: 4,
    LevelingGrade.GRADE_3: 3,
    LevelingGrade.GRADE_4: 3,
    LevelingGrade.EXTRA: 3,
}

_HEIGHT_DIFF_DP = {
    LevelingGrade.GRADE_2: 5,
    LevelingGrade.GRADE_3: 4,
    LevelingGrade.GRADE_4: 4,
    LevelingGrade.EXTRA: 3,
}


# ──────────────────────────────────────────────────────────────────────
# 水准手簿: 表头区
# ──────────────────────────────────────────────────────────────────────

def _leveling_header_text(wb: LevelingWorkbook) -> str:
    """水准手簿表头."""
    lines = [
        "=" * 60,
        "水准观测手簿",
        "=" * 60,
        f"项目: {wb.project_name or '-'}",
        f"等级: {_GRADE_LABELS.get(wb.grade, wb.grade.value)}",
    ]

    # 元数据 (从第一个 section 取)
    if wb.sections:
        md = wb.sections[0].metadata
        lines.extend([
            f"日期: {md.date}  天气: {md.weather or '-'}",
            f"仪器: {md.instrument_model} ({md.instrument_serial})",
            f"观测: {md.observer}  记录: {md.recorder}",
        ])
        route = wb.sections[0].route
        lines.extend([
            f"路线: {route.start_point_name} (H={route.start_point_height:.3f}m)"
            f" → {route.end_point_name} (H={route.end_point_height:.3f}m)",
        ])
        # 尺参数
        rod = wb.sections[0].rod_back
        if rod.rod_type == RodType.DOUBLE_FACE:
            k_back = wb.sections[0].rod_back.k_value_m
            k_fore = wb.sections[0].rod_fore.k_value_m
            lines.append(f"尺型: 双面木质尺  K后={k_back}m  K前={k_fore}m")
        elif rod.rod_type == RodType.INVAR_BASIC_AUX:
            c = wb.sections[0].rod_back.c_aux_m
            lines.append(f"尺型: 因瓦基辅尺  C_aux={c}m")

    elif wb.extra_sections:
        md = wb.extra_sections[0].metadata
        lines.extend([
            f"日期: {md.date}  天气: {md.weather or '-'}",
            f"仪器: {md.instrument_model} ({md.instrument_serial})",
            f"观测: {md.observer}  记录: {md.recorder}",
        ])
        route = wb.extra_sections[0].route
        lines.extend([
            f"路线: {route.start_point_name} (H={route.start_point_height:.3f}m)"
            f" → {route.end_point_name} (H={route.end_point_height:.3f}m)",
            f"尺型: 单面尺 (变动仪高法)",
        ])

    lines.append("")
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────
# 水准手簿: 观测表
# ──────────────────────────────────────────────────────────────────────

def _leveling_obs_table(section: LevelingSection, is_md: bool) -> str:
    """Grade 2/3/4 观测表."""
    grade = section.grade
    rdp = _READING_DP.get(grade, 3)
    hdp = _HEIGHT_DIFF_DP.get(grade, 4)
    is_double_face = (section.rod_back.rod_type == RodType.DOUBLE_FACE)

    if is_double_face:
        headers = [
            "站号", "后视", "前视",
            "后上丝", "后下丝", "后黑中", "后红中",
            "前上丝", "前下丝", "前黑中", "前红中",
            "后视距", "前视距", "视距差", "累积差",
            "K+黑-红后", "K+黑-红前",
            "h黑", "h红", "h中",
        ]
    else:  # invar
        headers = [
            "站号", "后视", "前视",
            "后上丝", "后下丝", "后基中", "后辅中",
            "前上丝", "前下丝", "前基中", "前辅中",
            "后视距", "前视距", "视距差", "累积差",
            "基辅差后", "基辅差前",
            "h基", "h辅", "h中",
        ]

    rows = []
    for st in section.stations:
        bs = st.backsight
        fs = st.foresight
        row = [
            str(st.station_number),
            st.backsight_point,
            st.foresight_point,
            format_meter(bs.upper_wire_m, rdp),
            format_meter(bs.lower_wire_m, rdp),
            format_meter(bs.black_mid_m, rdp),
            format_meter(bs.red_mid_m if is_double_face else bs.aux_mid_m, rdp),
            format_meter(fs.upper_wire_m, rdp),
            format_meter(fs.lower_wire_m, rdp),
            format_meter(fs.black_mid_m, rdp),
            format_meter(fs.red_mid_m if is_double_face else fs.aux_mid_m, rdp),
            format_meter(st.stadia_back_m, 1),
            format_meter(st.stadia_fore_m, 1),
            format_meter(st.distance_diff_m, 1),
            format_meter(st.cumulative_diff_m, 1),
            format_mm(st.k_plus_black_minus_red_back_mm if is_double_face
                      else st.base_aux_reading_diff_back_mm, 2),
            format_mm(st.k_plus_black_minus_red_fore_mm if is_double_face
                      else st.base_aux_reading_diff_fore_mm, 2),
            format_meter(st.height_diff_black_m if is_double_face
                         else st.height_diff_basic_m, hdp),
            format_meter(st.height_diff_red_m if is_double_face
                         else st.height_diff_aux_m, hdp),
            format_meter(st.height_diff_mean_m, hdp),
        ]
        rows.append(row)

    if is_md:
        return _render_md_table(headers, rows)
    return _render_text_table(headers, rows)


def _extra_obs_table(section: ExtraLevelingSection, is_md: bool) -> str:
    """等外水准观测表."""
    headers = [
        "站号", "后视", "前视",
        "后视1", "前视1", "h1",
        "后视2", "前视2", "h2",
        "|h1-h2|", "h中",
    ]
    rows = []
    for st in section.stations:
        rows.append([
            str(st.station_number),
            st.backsight_point,
            st.foresight_point,
            format_meter(st.backsight_1_m, 3),
            format_meter(st.foresight_1_m, 3),
            format_meter(st.height_diff_1_m, 3),
            format_meter(st.backsight_2_m, 3),
            format_meter(st.foresight_2_m, 3),
            format_meter(st.height_diff_2_m, 3),
            format_mm(st.height_diff_diff_mm, 2),
            format_meter(st.height_diff_mean_m, 3),
        ])
    if is_md:
        return _render_md_table(headers, rows)
    return _render_text_table(headers, rows)


# ──────────────────────────────────────────────────────────────────────
# 水准手簿: 汇总区
# ──────────────────────────────────────────────────────────────────────

def _leveling_summary(section, is_md: bool) -> str:
    """路线汇总."""
    lines = []
    if is_md:
        lines.append("\n## 路线汇总\n")
    else:
        lines.append("\n" + "=" * 40)
        lines.append("路线汇总")
        lines.append("=" * 40)

    items = []
    if hasattr(section, 'sum_backsight_m') and section.sum_backsight_m is not None:
        items.append(f"SUM(后视) = {section.sum_backsight_m:.6f} m")
    if hasattr(section, 'sum_foresight_m') and section.sum_foresight_m is not None:
        items.append(f"SUM(前视) = {section.sum_foresight_m:.6f} m")
    if section.sum_height_diff_m is not None:
        items.append(f"SUM(高差) = {section.sum_height_diff_m:.6f} m")
    if section.total_distance_km is not None:
        items.append(f"路线总长 = {section.total_distance_km:.3f} km")
    sc = getattr(section, 'station_count', None)
    if sc is not None:
        items.append(f"测站数 = {sc}")
    if section.closure_error_mm is not None:
        items.append(f"闭合差 = {section.closure_error_mm:.3f} mm")
    if section.closure_limit_mm is not None:
        items.append(f"限差 = ±{section.closure_limit_mm:.1f} mm")

    lines.extend(items)
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────
# 导线手簿: 表头区
# ──────────────────────────────────────────────────────────────────────

def _traversing_header_text(wb: TraversingWorkbook) -> str:
    """导线手簿表头."""
    lines = [
        "=" * 60,
        "导线观测手簿",
        "=" * 60,
        f"项目: {wb.project_name or '-'}",
        f"等级: {wb.grade.value}",
        f"仪器等级: {wb.instrument_grade.value}",
    ]

    if wb.metadata:
        md = wb.metadata
        lines.extend([
            f"日期: {md.date}  天气: {md.weather or '-'}",
            f"仪器: {md.instrument_model} ({md.instrument_serial})",
            f"观测: {md.observer}  记录: {md.recorder}",
        ])

    if wb.info:
        info = wb.info
        lines.extend([
            f"导线: {info.name}",
            f"起点: {info.start_point_name} ({info.start_point_x:.3f}, {info.start_point_y:.3f})",
            f"终点: {info.end_point_name} ({info.end_point_x:.3f}, {info.end_point_y:.3f})",
            f"角度定义: {info.angle_definition.value}",
        ])
        if info.start_reference_azimuth is not None:
            ref_s = f"{info.start_reference_point or '?'}→{info.start_point_name}"
            ref_e = f"{info.end_point_name}→{info.end_reference_point or '?'}"
            lines.append(f"方位基准: {ref_s} (起始), {ref_e} (终止)")
            lines.append(f"起始方位角: {ref_s} = {rad_to_dms(info.start_reference_azimuth)}")
            lines.append(f"终止方位角: {ref_e} = {rad_to_dms(info.end_reference_azimuth)}")

    lines.append("")
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────
# 导线手簿: 角度观测表
# ──────────────────────────────────────────────────────────────────────

def _traversing_angle_table(wb: TraversingWorkbook, is_md: bool) -> str:
    """导线角度观测表.

    格式规则:
    - 后视行: 仅填读数和 2C, 方向值和归零方向值留空
    - 前视L行: 填读数、2C、方向值(前视L-后视L), 归零方向值留空
    - 前视R行: 填读数、2C、方向值(前视R-后视R)、归零方向值(均值)
    """
    headers = [
        "测站", "测回", "目标", "盘位",
        "读数(DMS)", "2C(\")", "方向值", "归零方向值",
    ]
    rows = []
    for obs in wb.angle_observations:
        for aset in obs.sets:
            per_face_dv = build_per_face_direction_values(
                aset, obs.backsight_target)

            # 按 L/R 分组收集前视盘位方向值, 用于计算归零方向值
            foresight_dv_groups = {}
            for (tgt, face), dv in per_face_dv.items():
                foresight_dv_groups.setdefault(tgt, {})[face] = dv

            for dr in aset.directions:
                two_c = aset.two_c_values_rad.get(dr.target)
                is_backsight = (dr.target == obs.backsight_target)

                dv_val = per_face_dv.get((dr.target, dr.face.value))
                dv_str = rad_to_dms(dv_val) if dv_val is not None else "-"

                # 归零方向值: 仅前视R行填写, = (方向值_L + 方向值_R) / 2
                zdr_str = "-"
                if (not is_backsight
                        and dr.face.value == "R"
                        and dr.target in foresight_dv_groups):
                    dv_group = foresight_dv_groups[dr.target]
                    if "L" in dv_group and "R" in dv_group:
                        zdr = (dv_group["L"] + dv_group["R"]) / 2.0
                        zdr = zdr % _TWO_PI
                        zdr_str = rad_to_dms(zdr)

                rows.append([
                    obs.station_name,
                    str(aset.set_number),
                    dr.target,
                    dr.face.value,
                    rad_to_dms(dr.reading_rad),
                    format_arcsec(two_c, 2) if two_c is not None else "-",
                    "-" if is_backsight else dv_str,
                    zdr_str,
                ])

    if is_md:
        return _render_md_table(headers, rows)
    return _render_text_table(headers, rows)


# ──────────────────────────────────────────────────────────────────────
# 导线手簿: 距离观测表
# ──────────────────────────────────────────────────────────────────────

def _traversing_distance_table(wb: TraversingWorkbook, is_md: bool) -> str:
    """导线距离观测表."""
    headers = [
        "边名", "方向", "读数1", "读数2", "读数3",
        "读数差(mm)", "均值(m)", "最终距离(m)",
    ]
    rows = []
    for edge in wb.distance_observations:
        for label, sets in [("往测", edge.forward_sets),
                            ("返测", edge.backward_sets)]:
            for ds in sets:
                vals = [r.reading_m for r in ds.readings]
                r1 = format_meter(vals[0], 4) if len(vals) > 0 else "-"
                r2 = format_meter(vals[1], 4) if len(vals) > 1 else "-"
                r3 = format_meter(vals[2], 4) if len(vals) > 2 else "-"
                rows.append([
                    edge.edge_name,
                    label,
                    r1, r2, r3,
                    format_mm(ds.reading_diff_mm, 1) if ds.reading_diff_mm is not None else "-",
                    format_meter(ds.mean_distance_m, 4),
                    format_meter(edge.final_distance_m, 4),
                ])

    if is_md:
        return _render_md_table(headers, rows)
    return _render_text_table(headers, rows)


# ──────────────────────────────────────────────────────────────────────
# 导线手簿: 成果计算表
# ──────────────────────────────────────────────────────────────────────

def _traversing_computation_table(wb: TraversingWorkbook, is_md: bool) -> str:
    """导线成果计算表."""
    if wb.computation is None:
        return ""

    comp = wb.computation
    headers = ["点名", "观测角(DMS)", "方位角(DMS)", "距离(m)",
               "Δx(m)", "Δy(m)", "X(m)", "Y(m)"]
    rows = []

    # 交错输出: point[0], edge[0], point[1], edge[1], ...
    n_edges = len(comp.edge_records)
    n_points = len(comp.point_records)

    for i in range(max(n_points, n_edges)):
        if i < n_points:
            pr = comp.point_records[i]
            rows.append([
                pr.point_name,
                rad_to_dms(pr.observed_angle_rad) if pr.observed_angle_rad else "-",
                "-",
                "-",
                "-",
                "-",
                format_meter(pr.x_m, 3),
                format_meter(pr.y_m, 3),
            ])
        if i < n_edges:
            er = comp.edge_records[i]
            rows.append([
                f"  → {er.point_name}",
                rad_to_dms(er.observed_angle_rad) if er.observed_angle_rad else "-",
                rad_to_dms(er.azimuth_rad) if er.azimuth_rad else "-",
                format_meter(er.distance_m, 4),
                format_meter(er.delta_x_m, 4),
                format_meter(er.delta_y_m, 4),
                "",
                "",
            ])

    if is_md:
        return _render_md_table(headers, rows)
    return _render_text_table(headers, rows)


def _traversing_closure(wb: TraversingWorkbook) -> str:
    """导线闭合差汇总."""
    if wb.computation is None:
        return ""
    comp = wb.computation
    lines = [
        "\n闭合差汇总:",
        f"  方位角闭合差: {format_optional(comp.azimuth_closure_error_arcsec, '.2f')}\"",
    ]
    if comp.azimuth_closure_limit_arcsec is not None:
        lines.append(f"  方位角限差: ±{comp.azimuth_closure_limit_arcsec:.1f}\"")
    lines.extend([
        f"  f_x = {format_meter(comp.fx_m, 4)} m",
        f"  f_y = {format_meter(comp.fy_m, 4)} m",
        f"  f_D = {format_meter(comp.fd_m, 4)} m",
        f"  全长 = {format_meter(comp.total_length_m, 3)} m",
    ])
    if comp.relative_closure is not None and comp.relative_closure > 0:
        denom = int(1.0 / comp.relative_closure)
        lines.append(f"  相对闭合差 K = 1/{denom}")
    if comp.relative_closure_limit is not None:
        limit_denom = int(1.0 / comp.relative_closure_limit)
        lines.append(f"  相对闭合差限差 = 1/{limit_denom}")

    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────
# 主入口
# ──────────────────────────────────────────────────────────────────────

def workbook_to_text(workbook) -> str:
    """
    将手簿格式化为纯文本.

    支持 LevelingWorkbook 和 TraversingWorkbook.
    """
    return _format_workbook(workbook, is_md=False)


def workbook_to_markdown(workbook) -> str:
    """
    将手簿格式化为 Markdown.

    支持 LevelingWorkbook 和 TraversingWorkbook.
    """
    return _format_workbook(workbook, is_md=True)


def _format_workbook(workbook, is_md: bool) -> str:
    """通用格式化入口."""
    sections = []

    if isinstance(workbook, LevelingWorkbook):
        sections.append(_leveling_header_text(workbook))

        # 正规测段
        for sec in workbook.sections:
            if is_md:
                sections.append(f"\n## 测段 {sec.section_id} 观测记录\n")
            else:
                sections.append(f"\n--- 测段 {sec.section_id} ---\n")
            sections.append(_leveling_obs_table(sec, is_md))
            sections.append(_leveling_summary(sec, is_md))

        # 等外测段
        for sec in workbook.extra_sections:
            if is_md:
                sections.append(f"\n## 测段 {sec.section_id} (等外) 观测记录\n")
            else:
                sections.append(f"\n--- 测段 {sec.section_id} (等外) ---\n")
            sections.append(_extra_obs_table(sec, is_md))
            sections.append(_leveling_summary(sec, is_md))

    elif isinstance(workbook, TraversingWorkbook):
        sections.append(_traversing_header_text(workbook))

        if is_md:
            sections.append("\n## 水平角观测\n")
        else:
            sections.append("\n--- 水平角观测 ---\n")
        sections.append(_traversing_angle_table(workbook, is_md))

        if is_md:
            sections.append("\n## 距离观测\n")
        else:
            sections.append("\n--- 距离观测 ---\n")
        sections.append(_traversing_distance_table(workbook, is_md))

        if is_md:
            sections.append("\n## 成果计算\n")
        else:
            sections.append("\n--- 成果计算 ---\n")
        sections.append(_traversing_computation_table(workbook, is_md))
        sections.append(_traversing_closure(workbook))

    # 教学声明
    if is_md:
        sections.append("\n---\n")
        sections.append(f"**教学声明**: {build_disclaimer(workbook)}")
    else:
        sections.append("\n" + "=" * 60)
        sections.append("教学声明")
        sections.append("=" * 60)
        sections.append(build_disclaimer(workbook))

    return "\n".join(sections)
