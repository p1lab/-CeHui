# src/generators/_utils.py
# 逆向生成器共享工具函数
#
# 包含: 截断正态采样、单位转换、读数取整

import math
import numpy as np


def truncated_normal(sigma: float, k: float = 3.0,
                     rng: np.random.Generator = None) -> float:
    """
    采样 delta ~ N(0, sigma^2), 截断至 [-k*sigma, k*sigma].

    参数:
        sigma: 标准差
        k: 截断系数 (默认 3.0)
        rng: NumPy 随机数生成器

    返回:
        截断正态分布采样值
    """
    if rng is None:
        rng = np.random.default_rng()
    if sigma <= 0:
        return 0.0
    while True:
        x = rng.normal(0.0, sigma)
        if abs(x) <= k * sigma:
            return x


def arcsec_to_rad(arcsec: float) -> float:
    """角秒 → 弧度"""
    return arcsec / 206265.0


def rad_to_arcsec(rad: float) -> float:
    """弧度 → 角秒"""
    return rad * 206265.0


def mm_to_m(mm: float) -> float:
    """毫米 → 米"""
    return mm / 1000.0


def m_to_mm(m: float) -> float:
    """米 → 毫米"""
    return m * 1000.0


def round_reading(value_m: float, decimal_places: int) -> float:
    """将读数 (m) 按指定小数位取整"""
    return round(value_m, decimal_places)


def normalize_angle(angle_rad: float) -> float:
    """归一化角度至 [0, 2*pi)"""
    return angle_rad % (2.0 * math.pi)
