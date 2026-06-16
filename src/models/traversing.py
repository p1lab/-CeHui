# src/models/traversing.py
# 导线测量观测手簿数据模型
#
# 覆盖: 一级/二级导线 (方向观测法/测回法) + 图根导线
#
# 字段设计依据:
#   - axiom_traversing.md A1-A9 (正向模型公理)
#   - config_traversing.json (限差参数)
#   - config_observation_program.json (度盘配置, 观测程序)
#
# 每方向每测回原始标量: L (盘左), R (盘右) = 2 个
# 核空间维度 (axiom A7.6): dim(ker) = 2mk - k + 1
#   示例: 2 测回 x 3 方向 = 2*2*3 - 3 + 1 = 10

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, List, Dict

from .common import (
    SurveyMetadata, TraverseInfo, TraverseGrade, InstrumentGrade,
    Face, AngleDefinition, GenerationMetadata,
    TRAVERSE_DISTANCE_DECIMAL_PLACES,
)


# ──────────────────────────────────────────────────────────────────────
# 角度观测: 单方向读数
# ──────────────────────────────────────────────────────────────────────

@dataclass
class DirectionReading:
    """
    单方向在盘左或盘右的度盘读数.

    精度: 1" (整角秒), 内部存储为弧度.
    输出时转换为度分秒格式: 123°45'06"

    公理对应:
        axiom A4.1: L = L_0 + L_bar + delta
        axiom A4.2: R = L_0 + L_bar - delta + pi
    """
    target: str               # 照准目标名 (如 "A", "P1", "后视")
    face: Face                # 盘左(L) / 盘右(R)
    reading_rad: float        # 水平度盘读数 (rad)


# ──────────────────────────────────────────────────────────────────────
# 角度观测: 一测回方向组
# ──────────────────────────────────────────────────────────────────────

@dataclass
class AngleSet:
    """
    一测回的角度观测 (包含所有方向的盘左和盘右读数).

    度盘零位配置 (axiom A5.1):
        L_0_j = (pi / m) * (j - 1) + offset

    观测程序 (方向观测法, 方向数 >= 3):
        盘左: 零方向 → 顺时针依次照准 → 归零
        盘右: 零方向 → 逆时针依次照准 → 归零
    """
    set_number: int                                  # 测回序号 (1, 2, ...)
    degree_plate_zero_rad: float                     # 度盘零位 L_0 (rad)
    directions: List[DirectionReading] = field(default_factory=list)

    # ── 计算字段 ──
    # 每个方向的 2C 和方向值
    two_c_values_rad: Dict[str, Optional[float]] = field(default_factory=dict)
    # key=target, value=2C (rad), axiom A4.3: 2C = L - (R - pi)

    direction_values_rad: Dict[str, Optional[float]] = field(default_factory=dict)
    # key=target, value=方向值 L_bar (rad), axiom A4.4: L_bar = (L+R-pi)/2 - L_0

    zero_reduced_directions_rad: Dict[str, Optional[float]] = field(default_factory=dict)
    # key=target, value=归零方向值 = L_bar - L_bar_zero

    # ── 半测回检核 ──
    half_set_closing_error_rad: Optional[float] = None
    # 归零差: 盘左/盘右零方向的出发读数与回归读数之差

    # 盘左半测回角值 (axiom A4.5): beta_L = L_bar_fore_L - L_bar_back_L
    half_set_angle_left_rad: Optional[float] = None

    # 盘右半测回角值 (axiom A4.6): beta_R = L_bar_fore_R - L_bar_back_R
    half_set_angle_right_rad: Optional[float] = None

    # 一测回角值 (axiom A4.7): beta_set = (beta_L + beta_R) / 2
    set_angle_rad: Optional[float] = None

    # 半测回较差 (axiom A4.5 检核): |beta_L - beta_R|
    half_set_diff_rad: Optional[float] = None


# ──────────────────────────────────────────────────────────────────────
# 角度观测: 测站水平角 (多测回汇总)
# ──────────────────────────────────────────────────────────────────────

@dataclass
class StationAngleObservation:
    """
    单站水平角观测记录 (多测回汇总).

    包含该站所有测回的方向观测数据, 以及最终的水平角计算结果.

    公理对应:
        一测回角值 (axiom A4.7): beta_set = (beta_L + beta_R) / 2
        多测回平均 (axiom A4.8): beta_final = mean(beta_set_j)
    """
    station_name: str                     # 测站名
    backsight_target: str                 # 后视目标名
    foresight_target: str                 # 前视目标名
    zero_direction: str                   # 零方向目标名 (方向观测法)
    sets: List[AngleSet] = field(default_factory=list)

    # ── 多测回汇总计算 ──
    mean_direction_values_rad: Dict[str, Optional[float]] = field(default_factory=dict)
    # key=target, value=各测回平均方向值 (rad)

    # 2C 检核
    max_2c_mutual_diff_arcsec: Optional[float] = None
    # 本测回内 2C 互差 (max - min), 限差: 13" (2"级仪器)

    # 方向值检核
    max_direction_diff_across_sets_arcsec: Optional[float] = None
    # 同一方向各测回间最大较差, 限差: 9" (2"级仪器)

    # 半测回较差
    half_set_diff_arcsec: Optional[float] = None
    # |beta_L - beta_R|, 限差: 12"

    # ── 最终水平角 ──
    observed_angle_rad: Optional[float] = None
    # 各测回平均水平角 (rad)

    angle_definition: AngleDefinition = AngleDefinition.LEFT_ANGLE


# ──────────────────────────────────────────────────────────────────────
# 距离观测: 单次读数
# ──────────────────────────────────────────────────────────────────────

@dataclass
class DistanceReading:
    """
    单次斜距/平距读数.

    精度: 4 位小数 (m), 即 0.0001 m = 0.1 mm.
    """
    reading_m: float        # 读数 (m)
    is_slope: bool = True   # True=斜距, False=平距 (仪器显示模式)


# ──────────────────────────────────────────────────────────────────────
# 距离观测: 一测回 (多次读数取平均)
# ──────────────────────────────────────────────────────────────────────

@dataclass
class DistanceSet:
    """
    一测回距离观测 (3 次读数取平均).

    公理对应:
        axiom A6.1: S_mean = mean(S_k, k=1..3)
        检核: max(S_k) - min(S_k) <= 读数差限差

    读数为斜距 (is_slope=True) 时, 需配合天顶距计算平距:
        D = S_mean * sin(Z)  (axiom A3.2)
    读数为平距 (is_slope=False) 时, 直接使用:
        D = S_mean
    """
    set_number: int                          # 测回序号
    readings: List[DistanceReading] = field(default_factory=list)
    # 3 次读数, 每次标注斜距/平距

    reading_diff_mm: Optional[float] = None  # max - min (mm), 限差 5mm
    mean_distance_m: Optional[float] = None  # 3 次读数平均 (m), 保留斜距/平距语义

    def get_readings_values(self) -> List[float]:
        """提取纯数值列表 (便于计算均值/极差)"""
        return [r.reading_m for r in self.readings]

    def is_slope_distance(self) -> bool:
        """该组读数是否为斜距"""
        return all(r.is_slope for r in self.readings) if self.readings else True


# ──────────────────────────────────────────────────────────────────────
# 距离观测: 单边 (往返测汇总)
# ──────────────────────────────────────────────────────────────────────

@dataclass
class EdgeDistanceObservation:
    """
    单边的距离观测记录 (含往返测).

    公理对应:
        axiom A6.2-A6.4: 往测平距, 返测平距, 平均值

    精度: 平距记录至 0.001 m (1 mm).
    """
    edge_name: str                          # 边名 (如 "A-P1", "K3-K4")
    from_point: str                         # 起点
    to_point: str                           # 终点

    # 仪器与棱镜参数
    instrument_height_m: Optional[float] = None  # 仪器高 (m)
    prism_height_m: Optional[float] = None       # 棱镜高 (m)

    # 天顶距 (用于斜距→平距转换, axiom A3.2: D = S * sin(Z))
    zenith_angle_forward_rad: Optional[float] = None   # 往测天顶距 (rad)
    zenith_angle_backward_rad: Optional[float] = None  # 返测天顶距 (rad)

    # 往测
    forward_sets: List[DistanceSet] = field(default_factory=list)
    forward_mean_distance_m: Optional[float] = None    # 往测平距均值 (m)

    # 返测
    backward_sets: List[DistanceSet] = field(default_factory=list)
    backward_mean_distance_m: Optional[float] = None   # 返测平距均值 (m)

    # 往返检核
    round_trip_diff_mm: Optional[float] = None         # |往-返| (mm), 限差 10mm

    # 最终结果
    final_distance_m: Optional[float] = None           # (往+返)/2 (m)


# ──────────────────────────────────────────────────────────────────────
# 导线成果计算表 (内业)
# ──────────────────────────────────────────────────────────────────────

@dataclass
class TraversePointRecord:
    """
    导线成果计算表中单点记录.

    每个点对应一行, 包含该点的角度观测结果和推算坐标.
    每条边对应一行, 包含距离和坐标增量.

    实际表格中点和边交替排列:
        Point(已知) → Edge → Point → Edge → ... → Point(已知)

    本模型将点和边分离, 用索引关联.
    """
    point_name: str                          # 点号
    is_known: bool = False                   # 是否为已知点

    # 角度 (仅中间站有观测角)
    observed_angle_rad: Optional[float] = None   # 观测水平角 (rad)
    angle_correction_rad: Optional[float] = None # 角度改正数 (rad)
    corrected_angle_rad: Optional[float] = None  # 改正后角度 (rad)

    # 方位角 (每条边)
    azimuth_rad: Optional[float] = None          # 坐标方位角 (rad)

    # 距离 (每条边)
    distance_m: Optional[float] = None           # 边长 (m)
    distance_correction_m: Optional[float] = None # 边长改正数 (m)

    # 坐标增量
    delta_x_m: Optional[float] = None            # dx = D * cos(alpha)
    delta_y_m: Optional[float] = None            # dy = D * sin(alpha)
    delta_x_correction_m: Optional[float] = None # dx 改正数
    delta_y_correction_m: Optional[float] = None # dy 改正数
    corrected_delta_x_m: Optional[float] = None  # 改正后 dx
    corrected_delta_y_m: Optional[float] = None  # 改正后 dy

    # 坐标
    x_m: Optional[float] = None                  # 纵坐标 X (m)
    y_m: Optional[float] = None                  # 横坐标 Y (m)

    # 高程 (三角高程, axiom A3.3: dH = S*cos(Z) + h_inst - h_prism)
    height_m: Optional[float] = None             # 高程 H (m)
    delta_height_m: Optional[float] = None       # 高差 dH (m)


@dataclass
class TraverseComputation:
    """
    导线成果计算表 (内业).

    包含:
    - 路线信息 (起终点坐标/方位角)
    - 角度闭合差计算与分配
    - 坐标增量闭合差计算与分配
    - 最终坐标成果

    公理对应:
        方位角闭合差 (axiom A2.6): f_beta = alpha_n_computed - alpha_n_known
        坐标闭合差 (axiom A2.7-A2.10): f_x, f_y, f_D, K
    """
    info: TraverseInfo                       # 导线信息
    grade: TraverseGrade                     # 等级

    # 点/边记录序列 (交替排列: point[0] → edge[0] → point[1] → edge[1] → ...)
    # 奇数索引为点记录, 偶数索引为边记录
    point_records: List[TraversePointRecord] = field(default_factory=list)
    edge_records: List[TraversePointRecord] = field(default_factory=list)

    # ── 闭合差汇总 ──
    azimuth_closure_error_arcsec: Optional[float] = None  # f_beta (")
    azimuth_closure_limit_arcsec: Optional[float] = None  # 限差 (")

    fx_m: Optional[float] = None             # X 坐标闭合差 (m)
    fy_m: Optional[float] = None             # Y 坐标闭合差 (m)
    fd_m: Optional[float] = None             # 全长闭合差 (m) = sqrt(fx^2 + fy^2)
    total_length_m: Optional[float] = None   # 导线全长 (m)
    relative_closure: Optional[float] = None  # 相对闭合差 K = fD / SUM(D)
    relative_closure_limit: Optional[float] = None  # 限差 (如 1/15000)

    # ── 平差方法 ──
    adjustment_method: str = "proportional"  # 按边长比例分配 (简易平差)


# ──────────────────────────────────────────────────────────────────────
# 完整导线手簿
# ──────────────────────────────────────────────────────────────────────

@dataclass
class TraversingWorkbook:
    """
    完整导线观测手簿.

    包含三类数据:
    1. 各站水平角观测记录 (StationAngleObservation)
    2. 各边距离观测记录 (EdgeDistanceObservation)
    3. 导线成果计算表 (TraverseComputation)

    数据流向:
        角度观测表 → 各测回平均方向值 → 水平角 → 成果计算表(观测角)
        距离观测表 → 平距中数 → 成果计算表(边长)
        成果计算表 → 闭合差检核 → 平差改正 → 最终坐标
    """
    grade: TraverseGrade
    instrument_grade: InstrumentGrade = InstrumentGrade.SEC_2
    project_name: str = ""

    # 元数据
    metadata: Optional[SurveyMetadata] = None
    info: Optional[TraverseInfo] = None

    # 观测数据
    angle_observations: List[StationAngleObservation] = field(default_factory=list)
    distance_observations: List[EdgeDistanceObservation] = field(default_factory=list)

    # 内业计算
    computation: Optional[TraverseComputation] = None

    # 生成元数据 (逆向生成器填写)
    generation_metadata: Optional[GenerationMetadata] = None

    # 教学声明
    teaching_disclaimer: str = (
        "本数据基于RTK坐标模拟生成, 仅供教学使用, 非真实外业观测数据"
    )
