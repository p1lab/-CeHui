#!/usr/bin/env python3
# scripts/simulate_forest_farm.py
#
# 林场实习: 附合导线 + 二等水准 观测数据模拟
#
# 场景: 基于 sample/points.csv 中的模拟 RTK 三维点数据
#   - 附合导线: B → K1 → K2 → … → K12 → G
#   - 二等水准: B → K1 → … → K12 → G (往返观测, 因瓦基辅尺)
#   - 导线方位基准: B2-B (起始已知方位), G-G2 (终止已知方位)
#
# 数据说明:
#   - 平面坐标: 某地方坐标系 (X=东向, Y=北向)
#   - 高程: 椭球高 → 正常高 (常数 zeta 近似)

import math
import sys
import os
import json
from typing import List, Tuple

# 确保项目根目录在路径中
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.models.common import (
    LevelingGrade, TraverseGrade, RouteInfo,
    InstrumentGrade, AngleDefinition, AngleObservationMethod,
    SurveyMetadata, RodType,
)
from src.models.leveling import RodSpec
from src.preconditions.height_datum import convert_ellipsoid_to_normal
from src.preconditions.feasibility import (
    check_leveling_feasibility,
    check_traversing_feasibility,
)
from src.generators.leveling_generator import generate_leveling_workbook
from src.generators.traversing_generator import generate_traversing_workbook
from src.validators.leveling_validator import validate_leveling_workbook
from src.validators.traversing_validator import validate_traversing_workbook
from src.checkers.leveling_compliance import check_leveling_compliance
from src.checkers.traversing_compliance import check_traversing_compliance
from src.formatters.text_formatter import workbook_to_text, workbook_to_markdown
from src.formatters.excel_formatter import workbook_to_excel


# ──────────────────────────────────────────────────────────────────────
# 1. 从 sample/points.csv 加载模拟 RTK 三维点数据
# ──────────────────────────────────────────────────────────────────────

SAMPLE_CSV_PATH = os.path.join(
    os.path.dirname(__file__), "..", "sample", "points.csv"
)

# 高程异常 (常数近似, 短路线内 zeta 变化小)
ZETA_CONSTANT = 2.300  # m


def load_sample_points(csv_path: str) -> List[Tuple[str, float, float, float]]:
    """从 CSV 加载 (点名, X, Y, 椭球高) 数据."""
    points = []
    with open(csv_path, encoding="utf-8") as f:
        next(f)  # 跳过表头
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split(",")
            name = parts[0].strip()
            x = float(parts[1].strip())
            y = float(parts[2].strip())
            z = float(parts[3].strip())
            points.append((name, x, y, z))
    return points


# ──────────────────────────────────────────────────────────────────────
# 2. 高程基准转换
# ──────────────────────────────────────────────────────────────────────

def convert_heights():
    """椭球高 → 正常高"""
    ellipsoid_points = load_sample_points(SAMPLE_CSV_PATH)
    name_to_point = {p[0]: p for p in ellipsoid_points}

    # 仅转换导线/水准路线上的点 (B, K1-K12, G)
    route_names = ["B"] + [f"K{i}" for i in range(1, 13)] + ["G"]
    traverse_ellipsoid = [name_to_point[n] for n in route_names]

    normal_points, report = convert_ellipsoid_to_normal(
        points=traverse_ellipsoid,
        zeta_source="constant",
        zeta_constant=ZETA_CONSTANT,
    )

    print("=" * 72)
    print("【高程基准转换】")
    print(report.summary)
    print()
    for item in report.items:
        print(
            f"  {item.point_name:>3s}: "
            f"椭球高 = {item.h_ellipsoid:.4f} m → "
            f"正常高 = {item.h_normal:.4f} m  "
            f"(zeta = {item.zeta:.4f} m)"
        )
    print()

    return normal_points


# ──────────────────────────────────────────────────────────────────────
# 3. 导线观测数据模拟
# ──────────────────────────────────────────────────────────────────────

def simulate_traversing(normal_points):
    """一级附合导线模拟 (附合于 B2-B 与 G-G2 已知方位)"""
    print("=" * 72)
    print("【一级附合导线模拟】")
    print()

    # 从 sample/points.csv 加载全部点 (含 B2, G2)
    ellipsoid_points = load_sample_points(SAMPLE_CSV_PATH)
    name_to_point = {p[0]: p for p in ellipsoid_points}

    # 导线点坐标 (平面): B → K1 → ... → K12 → G
    points_xy = [(n, x, y) for n, x, y, _ in normal_points]

    # 外部方位基准: B2-B (起始), G-G2 (终止)
    # 起始方位角 = B2 → B, 终止方位角 = G → G2
    from src.generators.traversing_generator import compute_azimuth
    b2 = name_to_point["B2"]
    b = name_to_point["B"]
    g = name_to_point["G"]
    g2 = name_to_point["G2"]

    az_start = compute_azimuth(b2[1], b2[2], b[1], b[2])  # B2 → B
    az_end = compute_azimuth(g[1], g[2], g2[1], g2[2])    # G → G2

    start_ref = (b2[0], b2[1], b2[2])
    end_ref = (g2[0], g2[1], g2[2])

    # 仪器高/棱镜高 (按点名)
    instrument_heights = {
        "B": 1.55, "K1": 1.60, "K2": 1.50, "K3": 1.58,
        "K4": 1.52, "K5": 1.65, "K6": 1.48, "K7": 1.55,
        "K8": 1.62, "K9": 1.50, "K10": 1.58, "K11": 1.55,
        "K12": 1.60, "G": 1.58,
    }
    prism_heights = {
        "B": 1.25, "K1": 1.30, "K2": 1.20, "K3": 1.28,
        "K4": 1.22, "K5": 1.35, "K6": 1.18, "K7": 1.25,
        "K8": 1.32, "K9": 1.20, "K10": 1.28, "K11": 1.25,
        "K12": 1.30, "G": 1.28,
    }

    metadata = SurveyMetadata(
        date="2026-06-16",
        observer="张三",
        recorder="李四",
        instrument_model="Leica TS16",
        instrument_serial="SN-2024001",
    )

    # 生成导线观测数据
    # P5: 使用 MEASUREMENT (测回法) 而非 DIRECTION (方向观测法)
    # P6: 传入外部基准点, 生成器自动计算连接角和方位角闭合差
    wb = generate_traversing_workbook(
        points=points_xy,
        start_azimuth=az_start,
        end_azimuth=az_end,
        grade=TraverseGrade.GRADE_1,
        instrument_grade=InstrumentGrade.SEC_2,
        num_angle_sets=2,
        angle_definition=AngleDefinition.LEFT_ANGLE,
        angle_observation_method=AngleObservationMethod.MEASUREMENT,
        num_distance_sets=2,
        instrument_heights=instrument_heights,
        prism_heights=prism_heights,
        metadata=metadata,
        seed=20260616,
        start_reference_point=start_ref,
        end_reference_point=end_ref,
    )

    # 正向验证
    val = validate_traversing_workbook(wb)
    print(f"正向验证: {'全部通过 [OK]' if val.all_passed else '未通过 [FAIL]'}")

    # 合规检核
    comp = check_traversing_compliance(wb)
    print(f"合规检核: {'合格 [OK]' if comp.passed else '不合格 [FAIL]'}")
    print()

    # 输出关键数据
    print("── 角度观测 ──")
    for obs in wb.angle_observations:
        station_name = obs.station_name
        # 每个测回的角值
        for aset in obs.sets:
            beta = aset.set_angle_rad
            beta_deg = math.degrees(beta) if beta else 0
            beta_d = int(beta_deg)
            beta_m = int((beta_deg - beta_d) * 60)
            beta_s = ((beta_deg - beta_d) * 60 - beta_m) * 60
            print(
                f"  {station_name} 测回{aset.set_number}: "
                f"beta = {beta_d}d{beta_m:02d}m{beta_s:05.2f}s"
            )
        # 最终水平角
        if obs.observed_angle_rad is not None:
            a_deg = math.degrees(obs.observed_angle_rad)
            a_d = int(a_deg)
            a_m = int((a_deg - a_d) * 60)
            a_s = ((a_deg - a_d) * 60 - a_m) * 60
            print(f"  {station_name} 平均: beta = {a_d}d{a_m:02d}m{a_s:05.2f}s")

    print()
    print("── 边长观测 ──")
    for edge in wb.distance_observations:
        d_forward = edge.forward_sets[0].readings[0].reading_m if edge.forward_sets else 0
        print(
            f"  {edge.from_point} → {edge.to_point}: "
            f"D ≈ {d_forward:.4f} m  "
            f"(i={edge.instrument_height_m:.2f}m, v={edge.prism_height_m:.2f}m)"
        )

    if wb.computation:
        comp_data = wb.computation
        print()
        print("  -- 闭合差 --")
        print(f"  方位角闭合差: {comp_data.azimuth_closure_error_arcsec:.1f}s")
        print(f"  f_X = {comp_data.fx_m*1000:.1f} mm")
        print(f"  f_Y = {comp_data.fy_m*1000:.1f} mm")
        print(f"  f_D = {comp_data.fd_m*1000:.1f} mm")
        if comp_data.total_length_m and comp_data.total_length_m > 0 and comp_data.fd_m:
            k = 1.0 / (comp_data.fd_m / comp_data.total_length_m)
            print(f"  全长相对闭合差: 1/{k:.0f}")

        # 平差结果 (阶段二十四)
        print()
        print("  -- 平差结果 (简易平差) --")
        last_point = comp_data.point_records[-1]
        if last_point.corrected_x_m is not None:
            print(f"  改正后终点坐标: X={last_point.corrected_x_m:.4f}, Y={last_point.corrected_y_m:.4f}")
            # 验证改正后终点坐标精确归位
            target_x = points_xy[-1][1]
            target_y = points_xy[-1][2]
            dx = abs(last_point.corrected_x_m - target_x)
            dy = abs(last_point.corrected_y_m - target_y)
            print(f"  已知终点坐标:   X={target_x:.4f}, Y={target_y:.4f}")
            print(f"  坐标闭合精度:   dX={dx*1000:.2f} mm, dY={dy*1000:.2f} mm")
            if dx < 1e-4 and dy < 1e-4:
                print("  改正后坐标精确归位 [OK]")
            else:
                print("  改正后坐标未精确归位 [FAIL]")

    return wb


# ──────────────────────────────────────────────────────────────────────
# 4. 水准观测数据模拟
# ──────────────────────────────────────────────────────────────────────

def simulate_leveling(normal_points):
    """二等水准模拟 (往返观测)"""
    print()
    print("=" * 72)
    print("【二等水准模拟 (往返观测)】")
    print()

    # 水准路线: B → K1 → … → K12 → G (不考虑 B2, G2, 不加转点)
    start_name, start_x, start_y, start_h = normal_points[0]
    end_name, end_x, end_y, end_h = normal_points[-1]

    # 中间控制点 (K1-K12, 水准必须经过)
    intermediate_points = [(n, h) for n, x, y, h in normal_points[1:-1]]

    # 计算路线长度
    total_length = 0.0
    for i in range(len(normal_points) - 1):
        _, x1, y1, _ = normal_points[i]
        _, x2, y2, _ = normal_points[i + 1]
        total_length += math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)
    total_length_km = total_length / 1000.0

    print(f"  路线: {start_name} → … → {end_name}")
    print(f"  中间导线点: {len(intermediate_points)} 个")
    print(f"  路线总长: {total_length_km:.2f} km")
    print(f"  高差: {(end_h - start_h)*1000:.1f} mm")
    print()

    # 构造路线信息
    route = RouteInfo(
        start_point_name=start_name,
        start_point_height=start_h,
        end_point_name=end_name,
        end_point_height=end_h,
        total_length_km=total_length_km,
        intermediate_points=intermediate_points,
    )

    # 因瓦基辅尺 (二等水准)
    rod_back = RodSpec(
        rod_id="No.60151",
        rod_type=RodType.INVAR_BASIC_AUX,
        k_value_m=None,
        c_aux_m=3.0155,
    )
    rod_fore = RodSpec(
        rod_id="No.60152",
        rod_type=RodType.INVAR_BASIC_AUX,
        k_value_m=None,
        c_aux_m=3.0155,
    )

    metadata = SurveyMetadata(
        date="2026-06-16",
        observer="张三",
        recorder="李四",
        instrument_model="DNA03",
        instrument_serial="SN-3001",
    )

    # 站数: 二等水准视距<=50m, 路线约2.02km
    # 22站为设计值, 偶数站利于视距差累积
    num_stations = 22

    # 生成 (往返观测 + 奇偶站交替 + 真实性参数)
    wb = generate_leveling_workbook(
        route=route,
        grade=LevelingGrade.GRADE_2,
        num_stations=num_stations,
        rod_back=rod_back,
        rod_fore=rod_fore,
        metadata=metadata,
        section_id="S1",
        seed=20260616,
        round_trip=True,
        return_section_id="S2",
        observation_sequence="alternate",
        target_closure_ratio=0.3,       # 各测段闭合差约为限差的30%
        target_round_trip_ratio=0.4,    # 往返不符值约为限差的40%
        round_trip_split_ratio=0.6,     # 往返测非对称误差: 往测承担60%, 返测承担40%
    )

    # 正向验证
    val = validate_leveling_workbook(wb)
    print(f"正向验证: {'全部通过 [OK]' if val.all_passed else '未通过 [FAIL]'}")

    # 合规检核
    comp = check_leveling_compliance(wb)
    print(f"合规检核: {'合格 [OK]' if comp.passed else '不合格 [FAIL]'}")
    if not comp.passed:
        for item in comp.items:
            if not item.passed:
                print(f"  [FAIL] {item.name}: {item.message}")
    print()

    # 输出关键数据
    print("── 往测 (S1) ──")
    if wb.sections:
        s1 = wb.sections[0]
        print(f"  测站数: {len(s1.stations)}")
        print(f"  高差之和: {s1.sum_height_diff_m * 1000:.2f} mm" if s1.sum_height_diff_m else "  高差之和: (待验证)")

        # 输出前3站详情
        for st in s1.stations[:3]:
            pt_type = st.point_type or ""
            seq = st.observation_sequence.value if st.observation_sequence else ""
            print(
                f"  站{st.station_number}: "
                f"{st.backsight_point} → {st.foresight_point} "
                f"[{pt_type}] [{seq}]"
            )
        if len(s1.stations) > 3:
            print(f"  … (共 {len(s1.stations)} 站)")

    print()
    print("── 返测 (S2) ──")
    if len(wb.sections) >= 2:
        s2 = wb.sections[1]
        print(f"  测站数: {len(s2.stations)}")
        print(f"  高差之和: {s2.sum_height_diff_m * 1000:.2f} mm" if s2.sum_height_diff_m else "  高差之和: (待验证)")

    # 往返测高差不符值
    if wb.is_round_trip and wb.round_trip_discrepancy_mm is not None:
        print()
        print("── 往返测检核 ──")
        print(f"  |h往 + h返| = {wb.round_trip_discrepancy_mm:.3f} mm")
        print(f"  限差 4√L = {wb.round_trip_limit_mm:.1f} mm")
        print(f"  {'合格 [OK]' if wb.round_trip_passed else '不合格 [FAIL]'}")

    # 闭合差
    if wb.sections and wb.sections[0].closure_error_mm is not None:
        print()
        print("── 路线闭合差 ──")
        for i, sec in enumerate(wb.sections):
            print(
                f"  测段{i+1} ({sec.section_id}): "
                f"f_h = {sec.closure_error_mm:.2f} mm, "
                f"限差 = {sec.closure_limit_mm:.1f} mm"
            )

    # 平差结果 (阶段二十四)
    if wb.adjustment is not None:
        print()
        print("── 平差结果 (简易平差) ──")
        adj = wb.adjustment
        print(f"  闭合差: {adj.closure_error_mm:.3f} mm")
        print(f"  限差: ±{adj.closure_limit_mm:.1f} mm")
        print(f"  是否合格: {'合格' if adj.passed else '不合格'}")
        if adj.correction_per_km_mm is not None:
            print(f"  每公里改正数: {adj.correction_per_km_mm:.3f} mm/km")

        # 验证改正后终点高程精确归位
        last_rec = adj.records[-1]
        if last_rec.height_m is not None:
            print(f"  改正后终点高程: {last_rec.height_m:.5f} m")
            print(f"  已知终点高程:   {end_h:.5f} m")
            dh = abs(last_rec.height_m - end_h)
            print(f"  高程闭合精度:   {dh*1000:.2f} mm")
            if dh < 1e-4:
                print("  改正后高程精确归位 [OK]")
            else:
                print("  改正后高程未精确归位 [FAIL]")

        # 往返测附注
        if wb.is_round_trip:
            print()
            print("  -- 往返测附注 --")
            if adj.round_trip_discrepancy_mm is not None:
                print(f"  往返测不符值: {adj.round_trip_discrepancy_mm:.3f} mm")
            if adj.round_trip_limit_mm is not None:
                print(f"  往返测限差: ±{adj.round_trip_limit_mm:.1f} mm")
            if adj.mean_height_diff_m is not None:
                print(f"  往返测中数高差: {adj.mean_height_diff_m:.5f} m")

    return wb


# ──────────────────────────────────────────────────────────────────────
# 5. 可行性预检
# ──────────────────────────────────────────────────────────────────────

def run_feasibility_checks():
    """运行可行性预检"""
    print("=" * 72)
    print("【可行性预检】")
    print()

    # 水准: RTK 高程精度 vs 二等
    lev_report = check_leveling_feasibility(
        grade=LevelingGrade.GRADE_2,
        sigma_H_m=0.03,
        math_true_value_mode=True,  # 数学真值模式
    )
    print(f"水准 (二等): {lev_report.summary}")

    # 导线: RTK 平面精度 vs 一级
    # 从 sample 数据计算最短边长
    ellipsoid_points = load_sample_points(SAMPLE_CSV_PATH)
    name_to_xy = {p[0]: (p[1], p[2]) for p in ellipsoid_points}
    route_names = ["B"] + [f"K{i}" for i in range(1, 13)] + ["G"]
    min_edge_m = float("inf")
    for i in range(len(route_names) - 1):
        x1, y1 = name_to_xy[route_names[i]]
        x2, y2 = name_to_xy[route_names[i + 1]]
        d = math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)
        if d < min_edge_m:
            min_edge_m = d

    trav_report = check_traversing_feasibility(
        grade=TraverseGrade.GRADE_1,
        min_edge_m=min_edge_m,
        sigma_XY_m=0.02,
        math_true_value_mode=True,
    )
    print(f"导线 (一级): {trav_report.summary}")
    print()


# ──────────────────────────────────────────────────────────────────────
# 6. 输出文件
# ──────────────────────────────────────────────────────────────────────

def save_outputs(lev_wb, trav_wb, output_dir):
    """保存输出文件"""
    os.makedirs(output_dir, exist_ok=True)

    # 水准 - Markdown
    lev_md = workbook_to_markdown(lev_wb)
    with open(os.path.join(output_dir, "二等水准观测手簿.md"), "w", encoding="utf-8") as f:
        f.write(lev_md)

    # 水准 - Excel
    lev_excel_path = os.path.join(output_dir, "二等水准观测手簿.xlsx")
    workbook_to_excel(lev_wb, lev_excel_path)

    # 导线 - Markdown
    trav_md = workbook_to_markdown(trav_wb)
    with open(os.path.join(output_dir, "一级导线观测手簿.md"), "w", encoding="utf-8") as f:
        f.write(trav_md)

    # 导线 - Excel
    trav_excel_path = os.path.join(output_dir, "一级导线观测手簿.xlsx")
    workbook_to_excel(trav_wb, trav_excel_path)

    print()
    print("=" * 72)
    print("【输出文件】")
    print(f"  目录: {output_dir}")
    print(f"  - 二等水准观测手簿.md")
    print(f"  - 二等水准观测手簿.xlsx")
    print(f"  - 一级导线观测手簿.md")
    print(f"  - 一级导线观测手簿.xlsx")


# ──────────────────────────────────────────────────────────────────────
# 主流程
# ──────────────────────────────────────────────────────────────────────

def main():
    print("+--------------------------------------------------------------+")
    print("|     林场实习 — 附合导线 + 二等水准 观测数据模拟             |")
    print("+--------------------------------------------------------------+")
    print()

    # 1. 可行性预检
    run_feasibility_checks()

    # 2. 高程基准转换
    normal_points = convert_heights()

    # 3. 导线模拟
    trav_wb = simulate_traversing(normal_points)

    # 4. 水准模拟
    lev_wb = simulate_leveling(normal_points)

    # 5. 保存输出
    output_dir = os.path.join(os.path.dirname(__file__), '..', 'output')
    save_outputs(lev_wb, trav_wb, output_dir)

    print()
    print("模拟完成。")


if __name__ == "__main__":
    main()
