# src/models/common.py
# 通用类型与元数据定义
#
# 设计原则:
# - 所有物理量内部存储使用 SI 单位 (米, 弧度)
# - 仅输出格式化时转换为测绘惯例 (毫米, 度分秒)
# - dataclass 字段按 "原始观测 → 计算检核" 顺序排列

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Tuple


# ──────────────────────────────────────────────────────────────────────
# 枚举类型
# ──────────────────────────────────────────────────────────────────────

class LevelingGrade(str, Enum):
    """水准测量等级"""
    GRADE_2 = "grade_2"   # 二等
    GRADE_3 = "grade_3"   # 三等
    GRADE_4 = "grade_4"   # 四等
    EXTRA   = "extra"      # 等外/图根


class TraverseGrade(str, Enum):
    """导线测量等级"""
    GRADE_1 = "grade_1"   # 一级
    GRADE_2 = "grade_2"   # 二级
    ROOT    = "root"       # 图根


class RodType(str, Enum):
    """水准尺类型"""
    INVAR_BASIC_AUX = "invar_basic_aux"        # 因瓦基辅分划尺 (二等)
    DOUBLE_FACE     = "double_face"            # 双面木质尺 (三四等)
    SINGLE_FACE     = "single_face"            # 单面木质尺 (等外)


class InstrumentGrade(str, Enum):
    """全站仪精度等级"""
    SEC_2 = "2sec"    # 2" 级仪器
    SEC_6 = "6sec"    # 6" 级仪器


class Face(str, Enum):
    """盘左/盘右"""
    LEFT  = "L"       # 盘左 (Face Left)
    RIGHT = "R"       # 盘右 (Face Right)


class AngleDefinition(str, Enum):
    """水平角定义 (必须在项目启动时锁定, 全程不可混用)"""
    LEFT_ANGLE  = "left_angle"    # 左角: beta = alpha_fwd - alpha_bwd + pi
    RIGHT_ANGLE = "right_angle"   # 右角: beta = alpha_bwd - alpha_fwd + pi


class AngleObservationMethod(str, Enum):
    """水平角观测方法 (影响限差选取)"""
    DIRECTION    = "direction"      # 方向观测法 (方向数 >= 3, 含归零)
    MEASUREMENT  = "measurement"    # 测回法 (仅前后两方向, 无归零)


# ──────────────────────────────────────────────────────────────────────
# 通用元数据
# ──────────────────────────────────────────────────────────────────────

@dataclass
class SurveyMetadata:
    """
    观测手簿通用表头 (所有类型共享).

    对应规范: GB/T 12897-2006 表头要求 + GB 50026-2020 表头要求.
    """
    date: str                              # 日期, ISO 格式 "YYYY-MM-DD"
    observer: str                          # 观测者
    recorder: str                          # 记录者
    instrument_model: str                  # 仪器型号 (如 "DSZ05", "Leica TS16")
    instrument_serial: str                 # 仪器编号
    weather: str = ""                      # 天气
    imaging: str = ""                      # 呈像 (清晰/一般/模糊)
    location: str = ""                     # 地点
    temperature_c: Optional[float] = None  # 温度 (°C), 二等水准必填
    wind: str = ""                         # 风力


@dataclass
class RouteInfo:
    """
    水准路线信息.

    intermediate_points: 必须经过的中间已知点 (如导线点),
        生成器会在这些点间自动加设转点 (因视距限制).
        格式: [(点名, 高程), ...]
    """
    start_point_name: str       # 起点名
    start_point_height: float   # 起点已知高程 (m, 正常高)
    end_point_name: str         # 终点名
    end_point_height: float     # 终点已知高程 (m, 正常高)
    total_length_km: float = 0.0  # 路线总长 (km), 用于闭合差限差计算
    intermediate_points: Optional[List[Tuple[str, float]]] = None


@dataclass
class TraverseInfo:
    """
    导线路线信息.
    """
    name: str                          # 导线名称
    start_point_name: str              # 起点名
    start_point_x: float               # 起点 X 坐标 (m)
    start_point_y: float               # 起点 Y 坐标 (m)
    end_point_name: str                # 终点名
    end_point_x: float                 # 终点 X 坐标 (m)
    end_point_y: float                 # 终点 Y 坐标 (m)
    start_azimuth: Optional[float] = None  # 起始方位角 (rad), 由坐标反算
    end_azimuth: Optional[float] = None    # 终止方位角 (rad), 由坐标反算
    angle_definition: AngleDefinition = AngleDefinition.LEFT_ANGLE


# ──────────────────────────────────────────────────────────────────────
# 精度约定 (与 config 文件对应)
# ──────────────────────────────────────────────────────────────────────

# 水准读数小数位 (以米为单位)
#   二等: 4 位 (0.0001 m = 0.1 mm)
#   三四等: 3 位 (0.001 m = 1 mm)
#   等外: 3 位
LEVELING_READING_DECIMAL_PLACES = {
    LevelingGrade.GRADE_2: 4,
    LevelingGrade.GRADE_3: 3,
    LevelingGrade.GRADE_4: 3,
    LevelingGrade.EXTRA:   3,
}

# 水准高差小数位 (以米为单位)
#   二等: 5 位 (0.00001 m = 0.01 mm)
#   三四等: 4 位 (0.0001 m = 0.1 mm)
#   等外: 3 位
LEVELING_HEIGHT_DIFF_DECIMAL_PLACES = {
    LevelingGrade.GRADE_2: 5,
    LevelingGrade.GRADE_3: 4,
    LevelingGrade.GRADE_4: 4,
    LevelingGrade.EXTRA:   3,
}

# 导线角度记录精度: 0.1" (角秒一位小数)
#   对应 config_observation_program.json: angle_precision = "1 decimal (seconds)"
#   示例: 123°45'06.5"
TRAVERSE_ANGLE_DECIMAL_PLACES_ARCSEC = 1  # 角秒小数位

# 导线距离记录精度: 4 位小数 (0.0001 m = 0.1 mm)
TRAVERSE_DISTANCE_DECIMAL_PLACES = 4


# ──────────────────────────────────────────────────────────────────────
# 生成元数据 (逆向生成器返回, 编码约定要求)
# ──────────────────────────────────────────────────────────────────────

@dataclass
class GenerationMetadata:
    """
    逆向生成器的元数据 (编码约定: "每个生成器函数必须返回元数据字典").

    记录所用参数和扰动强度, 用于:
    - 可复现性 (random_seed)
    - 可追溯性 (target_grade, sigma values)
    - 教学声明 (math_true_value_mode)
    """
    target_grade: str                     # 目标等级 (如 "grade_2", "grade_1")
    random_seed: Optional[int] = None     # 随机种子 (None=不固定)
    perturbation_distribution: str = "truncated_normal"
    truncation_k: float = 3.0             # 截断系数 [-k*sigma, k*sigma]

    # 扰动强度 (实际使用的 sigma 值)
    leveling_sigma_mm: Optional[float] = None     # 水准读数扰动 sigma (mm)
    angle_sigma_arcsec: Optional[float] = None     # 导线角度扰动 sigma (")
    distance_sigma_mm: Optional[float] = None      # 导线距离扰动 sigma (mm)

    # 数学真值假设
    math_true_value_mode: bool = True
    _mtv_note: str = "忽略 RTK 物理噪声, 核心导出量精确无噪声"
