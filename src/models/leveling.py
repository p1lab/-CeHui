# src/models/leveling.py
# 水准测量观测手簿数据模型
#
# 覆盖: 二等 (基辅分划), 三四等 (黑红面), 等外 (单面尺/变动仪高法)
#
# 字段设计依据:
#   - axiom_leveling.md A1-A9 (正向模型公理)
#   - config_leveling.json (限差参数)
#   - config_observation_program.json (观测顺序)
#
# 每站原始观测标量数:
#   双面尺: 8 个 (a_black, a_red, b_black, b_red, u_back, l_back, u_fore, l_fore)
#   基辅尺: 4 个中丝读数 + 视距 (由上下丝计算)
#   单面尺: 2 个中丝读数 (变动仪高后重复)

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, List

from .common import (
    SurveyMetadata, RouteInfo, LevelingGrade, RodType, GenerationMetadata,
    LEVELING_READING_DECIMAL_PLACES, LEVELING_HEIGHT_DIFF_DECIMAL_PLACES,
)


# ──────────────────────────────────────────────────────────────────────
# 标尺参数 (每把尺的固有属性)
# ──────────────────────────────────────────────────────────────────────

@dataclass
class RodSpec:
    """
    水准尺规格.

    双面尺: K 值为红面起点常数, 典型值 4.687m 或 4.787m (axiom A5.1).
    基辅尺: C_aux 为基辅分划常数差, 典型值约 3.0155m (axiom A6.1).
    """
    rod_id: str                     # 尺号 (如 "K1", "K2", "No.1234")
    rod_type: RodType
    length_m: float = 3.0           # 标尺全长 (m)
    k_value_m: Optional[float] = None  # 红面尺常数 (m), 双面尺必填
    c_aux_m: Optional[float] = None  # 基辅分划常数差 (m), 因瓦尺必填


# ──────────────────────────────────────────────────────────────────────
# 水准读数 (尺面读数)
# ──────────────────────────────────────────────────────────────────────

@dataclass
class LevelingReading:
    """
    单方向 (后视或前视) 的水准读数.

    根据尺型不同, 包含不同字段:
    - 双面尺 (三四等): black_mid, red_mid, upper, lower
    - 基辅尺 (二等): basic, aux, upper, lower
    - 单面尺 (等外): black_mid (或 mid)

    精度约定 (以 m 为单位):
        二等读数: 4 位小数 (= 0.1 mm)
        三四等读数: 3 位小数 (= 1 mm)
        等外读数: 3 位小数 (= 1 mm)
    """
    # 中丝读数 (主分划/黑面/基本分划) — 所有尺型必填
    black_mid_m: Optional[float] = None   # 黑面/基本分划中丝 (m)

    # 辅分划读数
    red_mid_m: Optional[float] = None     # 红面中丝 (m), 双面尺必填
    aux_mid_m: Optional[float] = None     # 辅助分划中丝 (m), 因瓦尺必填

    # 视距丝读数
    upper_wire_m: Optional[float] = None  # 上丝 (m)
    lower_wire_m: Optional[float] = None  # 下丝 (m)

    def compute_stadia_distance(self, stadia_constant: float = 100.0) -> Optional[float]:
        """由上下丝计算视距 (axiom A4.1: S = C * (u - l))"""
        if self.upper_wire_m is not None and self.lower_wire_m is not None:
            return stadia_constant * (self.upper_wire_m - self.lower_wire_m)
        return None


# ──────────────────────────────────────────────────────────────────────
# 测站记录 (核心数据单元)
# ──────────────────────────────────────────────────────────────────────

@dataclass
class LevelingStation:
    """
    单站水准观测记录.

    结构: 原始观测 → 视距计算 → 读数检核 → 高差计算

    字段与公理的对应关系:
        backsight, foresight  → axiom A1.1: h = a - b
        stadia_back/fore      → axiom A4.1-A4.3: S = 100*(u-l), d, Sigma_d
        k_plus_black_minus_red → axiom A5.1: delta = K + black - red
        height_diff_black/red → axiom A5.3-A5.4: h_black, h_red_corrected
        height_diff_mean      → axiom A5.5: h_mid = (h_black + h_red) / 2

    精度约定:
        高差: 二等 5 位小数 (0.01 mm), 三四等 4 位小数 (0.1 mm)
    """
    station_number: int          # 测站序号
    backsight_point: str         # 后视点号 (如 "BM.A", "TP.1")
    foresight_point: str         # 前视点号

    # ── 原始观测读数 ──
    backsight: LevelingReading   # 后视读数 (a)
    foresight: LevelingReading   # 前视读数 (b)

    # ── 生成器人工参数 (axiom A9) ──
    sight_height_m: Optional[float] = None  # 视线高 (m), 逆向生成器设定
    # H_sight = H_back + a, 用于将高差 h 分解为前后视读数

    # ── 视距计算 (axiom A4) ──
    stadia_back_m: Optional[float] = None    # 后视距 (m)
    stadia_fore_m: Optional[float] = None    # 前视距 (m)
    distance_diff_m: Optional[float] = None  # 本站视距差 = back - fore (m)
    cumulative_diff_m: Optional[float] = None  # 累积视距差 (m)

    # ── 读数检核 ──
    # 双面尺 (axiom A5.1): K + black - red
    k_plus_black_minus_red_back_mm: Optional[float] = None
    k_plus_black_minus_red_fore_mm: Optional[float] = None

    # 基辅分划 (axiom A6.1): basic - aux + C_aux
    base_aux_reading_diff_back_mm: Optional[float] = None
    base_aux_reading_diff_fore_mm: Optional[float] = None

    # ── 高差计算 ──
    height_diff_black_m: Optional[float] = None  # 黑面/基本高差 (m)
    height_diff_red_m: Optional[float] = None    # 红面/辅助高差 (m, 含零点差改正)
    height_diff_mean_m: Optional[float] = None   # 高差中数 (m)

    # 基辅高差 (axiom A6.2)
    height_diff_basic_m: Optional[float] = None  # 基本分划高差 (m)
    height_diff_aux_m: Optional[float] = None    # 辅助分划高差 (m)

    # ── 检核差 (用于合规验证) ──
    black_red_height_diff_diff_mm: Optional[float] = None   # 黑红面高差之差 (mm)
    base_aux_height_diff_diff_mm: Optional[float] = None    # 基辅高差之差 (mm)


# ──────────────────────────────────────────────────────────────────────
# 等外水准专用: 变动仪高法 (双仪高)
# ──────────────────────────────────────────────────────────────────────

@dataclass
class ExtraLevelingStation:
    """
    等外水准测站 (变动仪器高法).

    观测程序: 第一次仪高读数 → 变动仪高 (>=10cm) → 第二次仪高读数.
    检核: |h1 - h2| <= 5 mm.
    """
    station_number: int
    backsight_point: str
    foresight_point: str

    # 第一次仪高
    backsight_1_m: float         # 后视读数 (m)
    foresight_1_m: float         # 前视读数 (m)
    height_diff_1_m: float = 0.0 # h1 = a1 - b1

    # 第二次仪高 (变动 >= 10 cm)
    backsight_2_m: float = 0.0
    foresight_2_m: float = 0.0
    height_diff_2_m: float = 0.0 # h2 = a2 - b2

    # 检核
    height_diff_diff_mm: Optional[float] = None  # |h1 - h2| (mm), 限差 <= 5mm
    height_diff_mean_m: Optional[float] = None   # (h1 + h2) / 2


# ──────────────────────────────────────────────────────────────────────
# 路线汇总 (多站集合 + 闭合差检核)
# ──────────────────────────────────────────────────────────────────────

@dataclass
class LevelingSection:
    """
    水准测段 (起终点均为已知点, 或起终点相同构成闭合路线).

    闭合差 (axiom A3.3):
        f_h = SUM(h_i) - (H_end - H_start)
    """
    section_id: str                    # 测段编号
    metadata: SurveyMetadata           # 表头信息
    route: RouteInfo                   # 路线信息
    grade: LevelingGrade               # 等级
    rod_back: RodSpec                  # 后视尺规格
    rod_fore: RodSpec                  # 前视尺规格

    # 测站序列
    stations: List[LevelingStation] = field(default_factory=list)

    # ── 路线汇总计算 ──
    sum_backsight_m: Optional[float] = None   # SUM(a) (m)
    sum_foresight_m: Optional[float] = None   # SUM(b) (m)
    sum_height_diff_m: Optional[float] = None # SUM(h) (m)
    total_distance_km: Optional[float] = None  # 路线总长 (km)

    # ── 闭合差 ──
    closure_error_mm: Optional[float] = None  # f_h = SUM(h) - (H_end - H_start) (mm)
    closure_limit_mm: Optional[float] = None  # 限差 (mm)
    station_count: Optional[int] = None       # 测站数 n


@dataclass
class ExtraLevelingSection:
    """
    等外水准测段 (使用变动仪高法).
    """
    section_id: str
    metadata: SurveyMetadata
    route: RouteInfo
    rod: RodSpec                       # 仅一把尺 (单面尺)

    stations: List[ExtraLevelingStation] = field(default_factory=list)

    sum_height_diff_m: Optional[float] = None
    total_distance_km: Optional[float] = None
    closure_error_mm: Optional[float] = None
    closure_limit_mm: Optional[float] = None


# ──────────────────────────────────────────────────────────────────────
# 完整手簿 (可能包含多个测段)
# ──────────────────────────────────────────────────────────────────────

@dataclass
class LevelingWorkbook:
    """
    完整水准观测手簿.

    包含:
    - 全局元数据
    - 等级与配置
    - 一个或多个测段 (往返测各为一个测段)
    """
    grade: LevelingGrade
    project_name: str = ""
    sections: List[LevelingSection] = field(default_factory=list)
    extra_sections: List[ExtraLevelingSection] = field(default_factory=list)

    # 生成元数据 (逆向生成器填写)
    generation_metadata: Optional[GenerationMetadata] = None

    # 教学声明 (自动附加)
    teaching_disclaimer: str = (
        "本数据基于RTK坐标模拟生成, 仅供教学使用, 非真实外业观测数据"
    )
