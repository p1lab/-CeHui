# src/formatters/_utils.py
# 格式化共享工具函数
#
# 包含: 弧度→DMS转换、米/毫米格式化、角秒格式化、教学声明构建

from __future__ import annotations

import math
from typing import Optional


# ──────────────────────────────────────────────────────────────────────
# 角度转换
# ──────────────────────────────────────────────────────────────────────

# 弧度 → 角秒精确转换常数 (= 180*3600/π ≈ 206264.806...)
_ARCSEC_PER_RAD = 180.0 * 3600 / math.pi


def rad_to_dms(rad: float) -> str:
    """
    弧度 → DMS 字符串.

    例: 2.15862 → "123°45'06.5""
    角秒保留 1 位小数.
    """
    # 转为总角秒 (使用精确常数, 保证 π/2 → 324000.0 恰好)
    total_arcsec = rad * _ARCSEC_PER_RAD

    # 处理负角 (不常见, 但安全)
    sign = ""
    if total_arcsec < 0:
        sign = "-"
        total_arcsec = abs(total_arcsec)

    # 先 round 到输出精度 (0.1"), 消除浮点噪声
    # 例: 323999.9999... → 324000.0 → 90°00'00.0"
    total_arcsec = round(total_arcsec, 1)

    degrees = int(total_arcsec // 3600)
    remainder = total_arcsec - degrees * 3600
    minutes = int(remainder // 60)
    seconds = remainder - minutes * 60

    return f"{sign}{degrees}°{minutes:02d}'{seconds:04.1f}\""


def rad_to_dms_tuple(rad: float) -> tuple:
    """弧度 → (degrees, minutes, seconds) 元组."""
    total_arcsec = rad * _ARCSEC_PER_RAD
    sign = 1 if total_arcsec >= 0 else -1
    total_arcsec = abs(total_arcsec)
    degrees = int(total_arcsec // 3600)
    remainder = total_arcsec - degrees * 3600
    minutes = int(remainder // 60)
    seconds = remainder - minutes * 60
    return sign * degrees, minutes, seconds


# ──────────────────────────────────────────────────────────────────────
# 数值格式化
# ──────────────────────────────────────────────────────────────────────

def format_meter(value: Optional[float], dp: int = 3) -> str:
    """米 → 定小数位字符串. None → '-'"""
    if value is None:
        return "-"
    return f"{value:.{dp}f}"


def format_mm(value: Optional[float], dp: int = 2) -> str:
    """米 → 毫米字符串. None → '-'"""
    if value is None:
        return "-"
    return f"{value * 1000:.{dp}f}"


def format_arcsec(value: Optional[float], dp: int = 2) -> str:
    """弧度 → 角秒字符串. None → '-'"""
    if value is None:
        return "-"
    return f"{value * _ARCSEC_PER_RAD:.{dp}f}"


def format_optional(value, fmt: str = ".3f") -> str:
    """通用可选值格式化. None → '-'"""
    if value is None:
        return "-"
    return f"{value:{fmt}}"


# ──────────────────────────────────────────────────────────────────────
# 教学声明构建
# ──────────────────────────────────────────────────────────────────────

def build_disclaimer(workbook) -> str:
    """
    从 workbook 构建完整教学声明.

    包含:
    - 基本声明文本 (来自 workbook.teaching_disclaimer)
    - 目标等级
    - 扰动参数 (sigma 值)
    - 数学真值模式声明
    """
    lines = [workbook.teaching_disclaimer]

    gm = getattr(workbook, 'generation_metadata', None)
    if gm is not None:
        lines.append(f"目标等级: {gm.target_grade}")
        if gm.leveling_sigma_mm is not None:
            lines.append(f"水准读数扰动 σ = {gm.leveling_sigma_mm} mm")
        if gm.angle_sigma_arcsec is not None:
            lines.append(f"导线角度扰动 σ = {gm.angle_sigma_arcsec}\"")
        if gm.distance_sigma_mm is not None:
            lines.append(f"导线距离扰动 σ = {gm.distance_sigma_mm} mm")
        if gm.random_seed is not None:
            lines.append(f"随机种子: {gm.random_seed}")
        if gm.math_true_value_mode:
            lines.append(
                "本数据基于数学真值假设模拟生成, 不代表RTK实测精度可达目标等级")

    return "\n".join(lines)
