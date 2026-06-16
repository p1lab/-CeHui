# src/preconditions/height_datum.py
# 高程基准转换: 椭球高 → 正常高
#
# 数学基础: docs/error_propagation.md A6
#
# A6.1: H_normal = h_ellipsoid - zeta
# A6.2: delta_zeta = zeta_i - zeta_{i-1}
#
# 短路线近似: zeta 在路线范围内为常数 (delta_zeta ≈ 0)
# 长路线: zeta 可按线性变化或格网插值

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


# ──────────────────────────────────────────────────────────────────────
# 数据结构
# ──────────────────────────────────────────────────────────────────────

@dataclass
class HeightDatumItem:
    """单个点的高程转换记录."""
    point_name: str
    x: float                     # 平面坐标 X (m)
    y: float                     # 平面坐标 Y (m)
    h_ellipsoid: float           # 椭球高 (m), 转换前
    h_normal: float              # 正常高 (m), 转换后
    zeta: float                  # 高程异常 (m), 该点使用的值
    delta_zeta: Optional[float] = None  # 与前一点的 zeta 差值 (m)


@dataclass
class HeightDatumReport:
    """高程基准转换报告."""
    items: List[HeightDatumItem]
    zeta_source: str              # "constant" / "linear" / "per_point"
    zeta_constant: Optional[float] = None    # 常数模式使用的 zeta (m)
    zeta_start: Optional[float] = None       # 线性模式起点 zeta
    zeta_end: Optional[float] = None         # 线性模式终点 zeta
    max_delta_zeta_m: float = 0.0            # 最大相邻点 zeta 差值 (m)
    max_delta_zeta_impact_mm: float = 0.0    # 最大 zeta 差值对高差的影响 (mm)
    warnings: List[str] = field(default_factory=list)

    @property
    def point_count(self) -> int:
        return len(self.items)

    @property
    def summary(self) -> str:
        lines = [
            f"高程基准转换报告: {self.point_count} 点, "
            f"zeta_source={self.zeta_source}",
        ]
        if self.zeta_source == "constant":
            lines.append(f"  zeta = {self.zeta_constant:.4f} m")
        elif self.zeta_source == "linear":
            lines.append(
                f"  zeta: {self.zeta_start:.4f} m → {self.zeta_end:.4f} m"
            )
        if self.max_delta_zeta_m > 0:
            lines.append(
                f"  最大相邻 zeta 差值: {self.max_delta_zeta_m:.4f} m "
                f"(高差影响: {self.max_delta_zeta_impact_mm:.2f} mm)"
            )
        if self.warnings:
            for w in self.warnings:
                lines.append(f"  ⚠ {w}")
        return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────
# 核心转换函数
# ──────────────────────────────────────────────────────────────────────

def convert_ellipsoid_to_normal(
    points: List[Tuple[str, float, float, float]],
    zeta_source: str = "constant",
    zeta_constant: Optional[float] = None,
    zeta_start: Optional[float] = None,
    zeta_end: Optional[float] = None,
    zeta_per_point: Optional[dict] = None,
) -> Tuple[List[Tuple[str, float, float, float]], HeightDatumReport]:
    """
    椭球高 → 正常高 (A6.1).

    H_normal = h_ellipsoid - zeta

    Args:
        points: [(点名, X, Y, 椭球高), ...]
        zeta_source: zeta 来源模式
            - "constant": 全路线使用同一常数 zeta
            - "linear": 起终点 zeta 线性内插
            - "per_point": 逐点指定 zeta
        zeta_constant: 常数 zeta 值 (m), constant 模式必需
        zeta_start: 起点 zeta (m), linear 模式必需
        zeta_end: 终点 zeta (m), linear 模式必需
        zeta_per_point: {点名: zeta_m}, per_point 模式必需

    Returns:
        (转换后点列表, 转换报告)
        转换后点列表: [(点名, X, Y, 正常高), ...]

    Raises:
        ValueError: 参数不匹配时
    """
    if not points:
        return [], HeightDatumReport(
            items=[], zeta_source=zeta_source,
            warnings=["输入点列表为空"],
        )

    # 计算 zeta 值序列
    zeta_values = _compute_zeta_values(
        points=points,
        zeta_source=zeta_source,
        zeta_constant=zeta_constant,
        zeta_start=zeta_start,
        zeta_end=zeta_end,
        zeta_per_point=zeta_per_point,
    )

    # 执行转换
    result_points = []
    items = []
    max_delta_zeta = 0.0

    for i, (name, x, y, h_ell) in enumerate(points):
        zeta = zeta_values[i]
        h_normal = h_ell - zeta  # A6.1

        delta_zeta = None
        if i > 0:
            dz = zeta - zeta_values[i - 1]  # A6.2
            delta_zeta = dz
            max_delta_zeta = max(max_delta_zeta, abs(dz))

        result_points.append((name, x, y, h_normal))
        items.append(HeightDatumItem(
            point_name=name,
            x=x, y=y,
            h_ellipsoid=h_ell,
            h_normal=h_normal,
            zeta=zeta,
            delta_zeta=delta_zeta,
        ))

    # 最大 delta_zeta 对高差的影响 (mm)
    max_impact_mm = max_delta_zeta * 1000.0

    # 警告
    warnings = []
    if max_delta_zeta > 0.01:  # 10 mm
        warnings.append(
            f"相邻点 zeta 差值达 {max_delta_zeta*1000:.1f} mm, "
            f"可能影响高差闭合差检核"
        )

    report = HeightDatumReport(
        items=items,
        zeta_source=zeta_source,
        zeta_constant=zeta_constant,
        zeta_start=zeta_start,
        zeta_end=zeta_end,
        max_delta_zeta_m=max_delta_zeta,
        max_delta_zeta_impact_mm=max_impact_mm,
        warnings=warnings,
    )

    return result_points, report


def _compute_zeta_values(
    points: List[Tuple[str, float, float, float]],
    zeta_source: str,
    zeta_constant: Optional[float],
    zeta_start: Optional[float],
    zeta_end: Optional[float],
    zeta_per_point: Optional[dict],
) -> List[float]:
    """计算每个点的 zeta 值."""
    n = len(points)

    if zeta_source == "constant":
        if zeta_constant is None:
            raise ValueError("常数模式必须提供 zeta_constant")
        return [zeta_constant] * n

    elif zeta_source == "linear":
        if zeta_start is None or zeta_end is None:
            raise ValueError("线性模式必须提供 zeta_start 和 zeta_end")
        if n == 1:
            return [zeta_start]
        return [
            zeta_start + (zeta_end - zeta_start) * i / (n - 1)
            for i in range(n)
        ]

    elif zeta_source == "per_point":
        if zeta_per_point is None:
            raise ValueError("逐点模式必须提供 zeta_per_point")
        result = []
        for name, _, _, _ in points:
            if name not in zeta_per_point:
                raise ValueError(f"逐点模式缺少点 '{name}' 的 zeta 值")
            result.append(zeta_per_point[name])
        return result

    else:
        raise ValueError(f"未知 zeta_source: {zeta_source}")


# ──────────────────────────────────────────────────────────────────────
# 辅助: 检查高程类型
# ──────────────────────────────────────────────────────────────────────

def check_height_datum_consistency(
    route_start_height: float,
    route_end_height: float,
    intermediate_heights: Optional[List[float]] = None,
    height_datum: str = "normal_height",
) -> Tuple[bool, List[str]]:
    """
    检查高程基准一致性.

    当 height_datum="ellipsoid_height" 时发出警告:
    RTK 椭球高与正常高之间存在系统性偏差.

    Args:
        route_start_height: 起点高程
        route_end_height: 终点高程
        intermediate_heights: 中间点高程序列
        height_datum: "normal_height" 或 "ellipsoid_height"

    Returns:
        (consistent, warnings)
    """
    warnings = []

    if height_datum == "ellipsoid_height":
        warnings.append(
            "输入高程为椭球高, 未转换为正常高. "
            "高程异常 zeta 将作为系统性偏差叠加到闭合差中, "
            "可能导致闭合差超限. 建议使用 convert_ellipsoid_to_normal() 转换."
        )
        return False, warnings

    return True, warnings
