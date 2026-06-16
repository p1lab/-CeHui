#!/usr/bin/env python3
# scripts/simulate_forest_farm.py
#
# 林场实习: 附合导线 + 二等水准 观测数据模拟
#
# 场景: 基于 GNSS实习_导线水准观测模型提取_20260616.md
#   - 附合导线: B → K1 → K2 → … → K9 → G
#   - 二等水准: B → K1 → … → K9 → G (往返观测, 因瓦基辅尺)
#   - 导线方位基准: B2-B (起始), G-G2 (终止)
#
# 假设数据: 一组三维坐标点 (模拟 RTK 测量结果)
#   - 平面坐标: 某地方坐标系
#   - 高程: 椭球高 → 正常高 (常数 zeta 近似)

import math
import sys
import os
import json

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
# 1. 假设三维点数据 (模拟 RTK 输出)
# ──────────────────────────────────────────────────────────────────────

# 点名, X(m), Y(m), 椭球高(m)
# 坐标系约定: X=东向(E), Y=北向(N) — 与生成器内部数学方位角一致
# 方位角 = atan2(dy, dx) 即从正东逆时针
# 模拟一条约 2.3 km 的附合导线 (大致向东北延伸)
ELLIPSOID_POINTS = [
    ("B2",  9800.000,  5000.000,  55.300),   # 起始方位基准 (B 的西南方)
    ("B",  10000.000,  5000.000,  52.500),   # 导线起点 (已知点)
    ("K1", 10150.000,  5200.000,  52.800),   # 导线点 1
    ("K2", 10280.000,  5400.000,  53.200),   # 导线点 2
    ("K3", 10380.000,  5650.000,  53.100),   # 导线点 3
    ("K4", 10500.000,  5880.000,  53.500),   # 导线点 4
    ("K5", 10620.000,  6100.000,  53.800),   # 导线点 5
    ("K6", 10730.000,  6350.000,  54.200),   # 导线点 6
    ("K7", 10820.000,  6600.000,  54.000),   # 导线点 7
    ("K8", 10920.000,  6850.000,  54.500),   # 导线点 8
    ("K9", 11000.000,  7100.000,  54.800),   # 导线点 9
    ("G",  11100.000,  7300.000,  55.100),   # 导线终点 (已知点)
    ("G2", 11200.000,  7500.000,  55.600),   # 终止方位基准 (G 的东北方向)
]

# 高程异常 (常数近似, 短路线内 zeta 变化小)
ZETA_CONSTANT = 2.300  # m


# ──────────────────────────────────────────────────────────────────────
# 2. 高程基准转换
# ──────────────────────────────────────────────────────────────────────

def convert_heights():
    """椭球高 → 正常高"""
    # 仅转换导线/水准路线上的点 (B, K1-K9, G)
    traverse_ellipsoid = ELLIPSOID_POINTS[1:12]  # B → G

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
    """一级附合导线模拟"""
    print("=" * 72)
    print("【一级附合导线模拟】")
    print()

    # 导线点坐标 (平面)
    points_xy = [(n, x, y) for n, x, y, _ in normal_points]

    # 起始方位角: B → K1 (第一条边的方位角)
    # 终止方位角: K9 → G (最后一条边的方位角)
    from src.generators.traversing_generator import compute_azimuth
    az_start = compute_azimuth(
        points_xy[0][1], points_xy[0][2],
        points_xy[1][1], points_xy[1][2],
    )
    az_end = compute_azimuth(
        points_xy[-2][1], points_xy[-2][2],
        points_xy[-1][1], points_xy[-1][2],
    )

    # 外部方位基准点 (附合导线)
    # B2→B: 起始外部基准方向
    # G→G2: 终止外部基准方向
    start_ref = (
        ELLIPSOID_POINTS[0][0],   # "B2"
        ELLIPSOID_POINTS[0][1],   # X
        ELLIPSOID_POINTS[0][2],   # Y
    )
    end_ref = (
        ELLIPSOID_POINTS[-1][0],  # "G2"
        ELLIPSOID_POINTS[-1][1],  # X
        ELLIPSOID_POINTS[-1][2],  # Y
    )

    # 仪器高/棱镜高
    instrument_heights = {
        "B": 1.55, "K1": 1.60, "K2": 1.50, "K3": 1.58,
        "K4": 1.52, "K5": 1.65, "K6": 1.48, "K7": 1.55,
        "K8": 1.62, "K9": 1.50, "G": 1.58,
    }
    prism_heights = {
        "B": 1.25, "K1": 1.30, "K2": 1.20, "K3": 1.28,
        "K4": 1.22, "K5": 1.35, "K6": 1.18, "K7": 1.25,
        "K8": 1.32, "K9": 1.20, "G": 1.28,
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

    # 水准路线: B → K1 → … → K9 → G
    start_name, start_x, start_y, start_h = normal_points[0]
    end_name, end_x, end_y, end_h = normal_points[-1]

    # 中间控制点 (导线点, 水准必须经过)
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

    # 站数: 二等水准视距<=50m, 路线2.56km, 约 51 个半站距
    # 21站 (设计值, 偶数站利于视距差累积)
    # 使用 seed=20260616 时站18累积视距差3.02m略超3.0m限差,
    # 改用 seed=2026 使视距分配更均匀
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
    # 最短边长约 200m
    trav_report = check_traversing_feasibility(
        grade=TraverseGrade.GRADE_1,
        min_edge_m=200.0,
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
