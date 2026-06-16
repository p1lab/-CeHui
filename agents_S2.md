# AGENTS_S2.md — 阶段二：林场实习观测模式适配

> 本文档描述将模拟观测数据CeHui项目适配为林场实习导线+水准观测模式所需的全部修改。
> 前置：阶段一至八全部完成（149/149 测试通过）。
> 观测模式来源：`GNSS实习_导线水准观测模型提取_20260616.md`

---

## 问题总览

| # | 问题 | 类型 | 优先级 | 影响范围 |
|---|------|------|--------|---------|
| P1 | 水准无往返观测 | 核心缺失 | P0 | 生成器+验证器+检核器+格式化器 |
| P2 | 水准无奇偶站观测顺序交替 | 核心缺失 | P0 | 生成器+格式化器 |
| P3 | 导线测距仅各1测回，应为各2测回 | 数量不足 | P1 | 生成器 |
| P4 | 限差数值不一致（多处） | 参数错误 | P1 | 配置+检核器 |
| P5 | 仪器高/棱镜高硬编码 | 参数化缺失 | P1 | 生成器接口 |
| P6 | 转点标记与导线点无法区分 | 功能缺失 | P2 | 生成器+模型 |
| P7 | 高程基准转换未实现 | 已知遗留 | P2 | 新模块 |

---

## P1：水准往返观测

### 问题描述

当前 `generate_leveling_workbook()` 只生成单程观测数据（一个 `LevelingSection`）。二等水准要求**往返观测**，并以往返测高差不符值 `|h_往 + h_返| ≤ 4√L mm` 作为核心质量检核指标。

### 实习观测模式要求

- 往测：B → K1 → … → G（后视→前视方向）
- 返测：G → K1 → … → B（路线反向）
- 返测观测顺序与往测**相反**：
  - 往测奇数站：后-前-前-后，偶数站：前-后-后-前
  - 返测奇数站：前-后-后-前，偶数站：后-前-前-后
- 往返测高差不符值限差：`4√L mm`（L 为测段长度 km）

### 当前代码现状

```python
# leveling_generator.py — 主入口
def generate_leveling_workbook(
    route: RouteInfo,        # 只有起终点
    grade: LevelingGrade,
    num_stations: int,       # 总站数
    ...
) -> LevelingWorkbook:
    # 仅生成单程，LevelingWorkbook.sections 只有一个元素
```

```python
# leveling.py — 模型定义
@dataclass
class LevelingWorkbook:
    grade: LevelingGrade
    sections: List[LevelingSection] = field(default_factory=list)      # 可容纳多段
    extra_sections: List[ExtraLevelingSection] = field(default_factory=list)
    # ⚠ 无往返测不符值字段
```

### 修改方案

#### 步骤 1：扩展模型 (`src/models/leveling.py`)

在 `LevelingWorkbook` 中增加往返测汇总字段：

```python
@dataclass
class LevelingWorkbook:
    grade: LevelingGrade
    project_name: str = ""
    sections: List[LevelingSection] = field(default_factory=list)
    extra_sections: List[ExtraLevelingSection] = field(default_factory=list)
    generation_metadata: Optional[GenerationMetadata] = None
    teaching_disclaimer: str = "..."

    # ── 新增：往返观测汇总 ──
    is_round_trip: bool = False                    # 是否往返观测
    round_trip_discrepancy_mm: Optional[float] = None  # |h_往 + h_返| (mm)
    round_trip_limit_mm: Optional[float] = None        # 4√L (mm)
    round_trip_passed: Optional[bool] = None           # 是否合格
```

#### 步骤 2：扩展生成器接口 (`src/generators/leveling_generator.py`)

```python
def generate_leveling_workbook(
    route: RouteInfo,
    grade: LevelingGrade,
    num_stations: int,
    rod_back: Optional[RodSpec] = None,
    rod_fore: Optional[RodSpec] = None,
    metadata: Optional[SurveyMetadata] = None,
    section_id: str = "S1",
    seed: Optional[int] = None,
    truncation_k: float = 3.0,
    # ── 新增参数 ──
    round_trip: bool = False,                      # 是否生成往返观测
    return_metadata: Optional[SurveyMetadata] = None,  # 返测表头（日期等可不同）
    return_section_id: str = "S2",                 # 返测测段编号
    observation_sequence: str = "alternate",       # "alternate"=奇偶站交替, "uniform"=统一顺序
) -> LevelingWorkbook:
```

当 `round_trip=True` 时：

1. 生成往测 `LevelingSection`（route 正向）
2. 生成返测 `LevelingSection`（route 反向，`RouteInfo(end→start)`）
3. 返测中：
   - 各站高差 = -(往测对应站高差)，但施加独立的核空间扰动
   - 观测顺序按奇偶站交替（见 P2）
4. 计算往返测高差不符值：`|SUM(h_往) + SUM(h_返)|`（往测高差+返测高差，理论为0）
5. 限差：`4√L mm`

#### 步骤 3：扩展验证器 (`src/validators/leveling_validator.py`)

在 `validate_leveling_workbook()` 中，若 `is_round_trip=True`：
- 分别验证往测和返测的内部一致性
- 计算往返测高差不符值
- 比对限差

#### 步骤 4：扩展检核器 (`src/checkers/leveling_compliance.py`)

增加往返测不符值检核项：

```python
# 在 check_leveling_compliance() 末尾
if workbook.is_round_trip and workbook.round_trip_discrepancy_mm is not None:
    report.add_item(ComplianceItem(
        name="往返测高差不符值",
        computed=workbook.round_trip_discrepancy_mm,
        limit=workbook.round_trip_limit_mm,
        passed=workbook.round_trip_discrepancy_mm <= workbook.round_trip_limit_mm,
        message=f"|h往+h返| = {workbook.round_trip_discrepancy_mm:.3f} mm ≤ {workbook.round_trip_limit_mm:.1f} mm",
    ))
```

#### 步骤 5：扩展格式化器

- `text_formatter.py`：往测和返测分节输出
- `excel_formatter.py`：返测独立 Sheet
- `json_formatter.py`：自动序列化新字段

### 验收测试

```python
# tests/test_leveling_round_trip.py
def test_grade2_round_trip():
    route = RouteInfo("B", 50.000, "G", 51.200, 2.3)
    wb = generate_leveling_workbook(
        route=route, grade=LevelingGrade.GRADE_2,
        num_stations=21,
        rod_back=RodSpec("No.1", RodType.INVAR_BASIC_AUX, c_aux_m=3.0155),
        rod_fore=RodSpec("No.2", RodType.INVAR_BASIC_AUX, c_aux_m=3.0155),
        round_trip=True, observation_sequence="alternate",
        seed=42,
    )
    assert wb.is_round_trip
    assert len(wb.sections) == 2  # 往测 + 返测
    assert wb.round_trip_discrepancy_mm is not None
    assert wb.round_trip_passed is True

    # 正向验证
    val = validate_leveling_workbook(wb)
    assert val.all_passed

    # 合规检核
    comp = check_leveling_compliance(wb)
    assert comp.passed
```

---

## P2：奇偶站观测顺序交替

### 问题描述

二等水准要求往测中奇数站和偶数站使用不同的观测顺序，返测则互换。当前代码所有测站使用相同的生成逻辑，不区分站号奇偶。

### 实习观测模式要求

| | 往测 | 返测 |
|---|---|---|
| **奇数站** | 后基→前基→前辅→后辅 | 前基→后基→后辅→前辅 |
| **偶数站** | 前基→后基→后辅→前辅 | 后基→前基→前辅→后辅 |

### 数学影响

**观测顺序不影响数学结果**——核空间约束保证无论读数按什么顺序记录，基辅分划高差计算完全相同。此修改仅影响**手簿记录的顺序**（输出格式化层），不影响生成器的数学逻辑。

但为了输出格式正确（手簿必须按规范顺序排列读数），需要在模型中记录每站的观测顺序类型。

### 修改方案

#### 步骤 1：扩展模型 (`src/models/leveling.py`)

```python
class ObservationSequence(str, Enum):
    """测站观测顺序"""
    BACK_FORE_FORE_BACK = "后前前后"   # 后基→前基→前辅→后辅
    FORE_BACK_BACK_FORE = "前后后前"   # 前基→后基→后辅→前辅

@dataclass
class LevelingStation:
    # ... existing fields ...
    observation_sequence: Optional[ObservationSequence] = None  # 新增
```

#### 步骤 2：生成器中按站号设置顺序 (`src/generators/leveling_generator.py`)

```python
# 在生成每站数据时：
if observation_sequence == "alternate":
    is_outbound = (section_id == "S1")  # 往测
    is_odd = (station_number % 2 == 1)
    if is_outbound:
        seq = ObservationSequence.BACK_FORE_FORE_BACK if is_odd else ObservationSequence.FORE_BACK_BACK_FORE
    else:
        seq = ObservationSequence.FORE_BACK_BACK_FORE if is_odd else ObservationSequence.BACK_FORE_FORE_BACK
else:
    seq = ObservationSequence.BACK_FORE_FORE_BACK  # 默认

station.observation_sequence = seq
```

#### 步骤 3：格式化器按顺序排列读数

`text_formatter.py` 和 `excel_formatter.py` 中，根据 `station.observation_sequence` 调整读数行的排列顺序。

**关键**：这不是重新排列读数数值，而是调整**输出行的顺序**。数值本身不变（核空间约束不变）。

### 验收测试

```python
def test_alternating_sequence():
    wb = generate_leveling_workbook(
        route=..., grade=LevelingGrade.GRADE_2,
        num_stations=4, round_trip=True, observation_sequence="alternate",
        seed=42,
    )
    outbound = wb.sections[0]
    # 奇数站应为 后前前后
    assert outbound.stations[0].observation_sequence == ObservationSequence.BACK_FORE_FORE_BACK
    # 偶数站应为 前后后前
    assert outbound.stations[1].observation_sequence == ObservationSequence.FORE_BACK_BACK_FORE

    inbound = wb.sections[1]
    # 返测奇数站应为 前后后前（与往测相反）
    assert inbound.stations[0].observation_sequence == ObservationSequence.FORE_BACK_BACK_FORE
```

---

## P3：导线测距往返各2测回

### 问题描述

实习要求斜距"往返各2测回"，当前代码硬编码各1测回。

### 当前代码

```python
# traversing_generator.py → _gen_edge_distance()
return EdgeDistanceObservation(
    ...
    forward_sets=[make_set(1)],      # 1测回
    backward_sets=[make_set(1)],     # 1测回
)
```

### 修改方案

#### 步骤 1：扩展生成器接口

```python
def generate_traversing_workbook(
    ...
    num_angle_sets: int = 2,
    # ── 新增 ──
    num_distance_sets: int = 2,      # 测距测回数（往返各N测回）
) -> TraversingWorkbook:
```

#### 步骤 2：修改 `_gen_edge_distance()`

```python
def _gen_edge_distance(
    ...
    num_sets: int = 2,     # 新增参数
) -> EdgeDistanceObservation:
    Z = math.pi / 2.0

    def make_set(set_num):
        readings = [
            DistanceReading(reading_m=true_D, is_slope=True)
            for _ in range(n_readings)
        ]
        return DistanceSet(set_number=set_num, readings=readings)

    return EdgeDistanceObservation(
        ...
        forward_sets=[make_set(j + 1) for j in range(num_sets)],
        backward_sets=[make_set(j + 1) for j in range(num_sets)],
    )
```

#### 步骤 3：更新配置

```json
// config_traversing.json → grade_1.distance
"measurement_sets": 2   // 从1改为2
```

### 验收测试

```python
def test_distance_2_sets():
    wb = generate_traversing_workbook(
        points=..., grade=TraverseGrade.GRADE_1,
        num_distance_sets=2, seed=42,
    )
    for edge in wb.distance_observations:
        assert len(edge.forward_sets) == 2
        assert len(edge.backward_sets) == 2
```

---

## P4：限差数值不一致

### 问题描述

代码中的限差取自 GB 50026-2020（方向观测法）和 GB/T 12897-2006，而实习设计书采用了不同条款（测回法）或不同版本的限差。需要逐一确认并修正。

### 差异清单

| 项目 | 代码当前值 | 实习设计书值 | 代码位置 | 分析 |
|------|-----------|-------------|---------|------|
| 导线半测回较差（2″级） | `half_set_diff_arcsec = 12.0` | 9″ | `traversing_compliance.py` | ⚠ 代码12″取自方向观测法的通用值；测回法2″级仪器应为9″ |
| 导线测回间较差（2″级） | `direction_diff_across_sets_arcsec = 9.0` | 10″ | `traversing_compliance.py` | ⚠ 代码9″取自方向观测法的方向值较差；测回法的测回间角值较差应为10″ |
| 基辅读数差 | `0.5 mm` | 0.4 mm | `config_leveling.json` | ⚠ GB/T 12897-2006 表3：测站观测限差，因瓦尺基辅分划读数差为0.4mm（数字水准仪）/ 0.5mm（光学）。设计书取0.4mm |
| 基辅高差差 | `0.7 mm` | 0.6 mm | `config_leveling.json` | ⚠ GB/T 12897-2006 表3：基辅分划所测高差之差为0.6mm（数字）/ 0.7mm（光学）。设计书取0.6mm |
| 导线测距读数差 | `5.0 mm` | 10 mm | `traversing_compliance.py` | ⚠ 代码5mm取自一测回内3次读数较差；设计书10mm可能是另一标准。需确认 |
| 导线测距往返差 | `10.0 mm` | 10 mm | 两处一致 | ✅ 一致 |

### 修改方案

#### 步骤 1：引入观测方法参数

限差不仅取决于等级和仪器精度，还取决于观测方法（测回法 vs 方向观测法）。当前代码未区分。

```python
# src/models/common.py — 新增枚举
class AngleObservationMethod(str, Enum):
    DIRECTION = "direction"         # 方向观测法（方向数 ≥ 3）
    MEASUREMENT = "measurement"     # 测回法（仅前后两方向）
```

#### 步骤 2：限差按观测方法分支

```python
# src/checkers/traversing_compliance.py
_TRAVERSING_LIMITS = {
    TraverseGrade.GRADE_1: {
        "2sec": {
            "2c_mutual_diff_arcsec": 13.0,      # 不变
            # 方向观测法
            "direction_diff_across_sets_arcsec": 9.0,
            # 测回法
            "half_set_diff_arcsec": 9.0,         # 12.0 → 9.0
            "set_diff_arcsec": 10.0,              # 新增：测回间角值较差
        },
        ...
        # 通用（不再单一 half_set_diff_arcsec）
    },
}
```

合规检核器根据 `workbook.angle_observation_method` 选择对应限差。

#### 步骤 3：修正水准限差

```python
# src/checkers/leveling_compliance.py
_LEVELING_LIMITS = {
    LevelingGrade.GRADE_2: {
        "base_aux_reading_diff_mm": 0.4,    # 0.5 → 0.4（数字水准仪标准）
        "base_aux_height_diff_mm": 0.6,     # 0.7 → 0.6（数字水准仪标准）
        ...
    },
}
```

同时在 `config_leveling.json` 中同步修改。

**注意**：若实习使用光学水准仪，则应保留 0.5/0.7。此修改应参数化（仪器类型：数字/光学），而非硬切。

#### 步骤 4：测距读数差限差

确认实习设计书的10mm限差来源。可能对应：
- GB 50026-2020：一测回内读数较差 ≤ 10mm（II级测距）
- 当前代码5mm对应I级测距

解决方案：按测距精度等级分设限差，或增加 `distance_grade` 参数。

### 验收测试

```python
def test_grade1_measurement_method_limits():
    wb = generate_traversing_workbook(
        ..., angle_method=AngleObservationMethod.MEASUREMENT,
    )
    comp = check_traversing_compliance(wb)
    # 半测回较差限差应为 9″，而非 12″
    half_set_items = [i for i in comp.items if "半测回" in i.name]
    for item in half_set_items:
        assert item.limit == 9.0
```

---

## P5：仪器高/棱镜高参数化

### 问题描述

导线生成器中仪器高和棱镜高硬编码为 1.50m 和 1.20m。

### 当前代码

```python
# traversing_generator.py → _gen_edge_distance()
return EdgeDistanceObservation(
    ...
    instrument_height_m=1.50,
    prism_height_m=1.20,
    ...
)
```

### 修改方案

#### 步骤 1：生成器接口增加参数

```python
def generate_traversing_workbook(
    ...
    # ── 新增 ──
    instrument_heights: Optional[Dict[str, float]] = None,   # {站名: 仪高(m)}
    prism_heights: Optional[Dict[str, float]] = None,        # {站名: 镜高(m)}
    default_instrument_height_m: float = 1.50,
    default_prism_height_m: float = 1.20,
) -> TraversingWorkbook:
```

#### 步骤 2：距离观测中使用参数

```python
# _gen_edge_distance() 增加参数
def _gen_edge_distance(
    ...
    instrument_height_m: float = 1.50,
    prism_height_m: float = 1.20,
) -> EdgeDistanceObservation:
```

### 验收测试

```python
def test_custom_heights():
    wb = generate_traversing_workbook(
        points=...,
        instrument_heights={"P1": 1.55, "P2": 1.60},
        prism_heights={"P1": 1.25, "P2": 1.30},
        seed=42,
    )
    for edge in wb.distance_observations:
        if edge.from_point == "P1":
            assert edge.instrument_height_m == 1.55
```

---

## P6：转点标记与导线点区分

### 问题描述

当前水准生成器接受 `num_stations` 参数，中间转点自动命名为 `TP.1, TP.2...`，无法区分哪些是导线点（必须经过）、哪些是纯转点（因视距限制临时加设）。

### 实习场景

导线点 B, K1, K2, …, K9, G 间距约100-200m，远超二等水准视距限制（≤50m），相邻导线点间需加设1-3个转点。转点在下一测站变为后视点，但不参与导线计算。

### 修改方案

#### 步骤 1：扩展 RouteInfo

```python
@dataclass
class RouteInfo:
    start_point_name: str
    start_point_height: float
    end_point_name: str
    end_point_height: float
    total_length_km: float = 0.0
    # ── 新增 ──
    intermediate_points: Optional[List[Tuple[str, float]]] = None  # [(点名, 高程), ...]
    # 必须经过的中间已知点（如导线点），生成器会在这些点间自动加转点
```

#### 步骤 2：生成器自动计算转点

```python
def generate_leveling_workbook(
    ...
    max_sight_distance: float = 50.0,  # 最大视距(m)
) -> LevelingWorkbook:
    # 如果指定了 intermediate_points:
    # 1. 将路线分为若干段：B→K1, K1→K2, ..., K9→G
    # 2. 对每段计算需要多少转点：ceil(段长 / max_sight_distance) - 1
    # 3. 转点命名：TP.B_K1.1, TP.B_K1.2, ... (可区分所属段)
    # 4. 各段高差按距离比例分配
```

#### 步骤 3：标记点类型

```python
@dataclass
class LevelingStation:
    ...
    point_type: Optional[str] = None  # "control"=导线点, "turning"=转点
```

### 验收测试

```python
def test_intermediate_points_with_turning():
    route = RouteInfo(
        "B", 50.000, "G", 51.200, 2.3,
        intermediate_points=[
            ("K1", 50.150), ("K2", 50.350), ("K3", 50.500),
        ],
    )
    wb = generate_leveling_workbook(
        route=route, grade=LevelingGrade.GRADE_2,
        max_sight_distance=50.0,
        seed=42,
    )
    # 导线点应出现在后视或前视点号中
    section = wb.sections[0]
    control_points = set()
    for st in section.stations:
        if st.point_type == "control":
            control_points.add(st.foresight_point)
    assert "K1" in control_points
    assert "K2" in control_points
    assert "K3" in control_points
```

---

## P7：高程基准转换

### 问题描述

RTK 输出椭球高 `h_ellipsoid`，水准测量基于正常高 `H_normal`，两者关系为 `H_normal = h_ellipsoid - zeta`（zeta 为高程异常）。当前代码未实现此转换。

这是阶段一至八的已知遗留项，`config_leveling.json` 中已预留 `height_datum` 配置段，公理 `error_propagation.md A6` 已冻结公式。

### 修改方案

#### 步骤 1：新增模块 `src/preconditions/height_datum.py`

```python
def convert_ellipsoid_to_normal(
    points: List[Tuple[str, float, float, float]],  # [(名, X, Y, 椭球高)]
    zeta_source: str = "constant",  # "constant" | "grid" | "model"
    zeta_constant: Optional[float] = None,  # 常数zeta值(m)
    grid_file: Optional[str] = None,  # 高程异常格网文件
) -> List[Tuple[str, float, float, float]]:  # [(名, X, Y, 正常高)]
    """椭球高 → 正常高 (error_propagation.md A6.1)"""
    if zeta_source == "constant":
        if zeta_constant is None:
            raise ValueError("常数模式必须提供 zeta_constant")
        return [(n, x, y, h - zeta_constant) for n, x, y, h in points]
    elif zeta_source == "grid":
        # 格网插值 (待实现)
        raise NotImplementedError("格网插值模式待实现")
    ...
```

#### 步骤 2：集成到生成器

在 `generate_leveling_workbook()` 和 `generate_traversing_workbook()` 入口处，检测输入高程类型，必要时自动转换。

### 验收测试

```python
def test_ellipsoid_to_normal():
    points = [("A", 100.0, 200.0, 52.500)]  # 椭球高
    result = convert_ellipsoid_to_normal(points, zeta_constant=2.300)
    assert abs(result[0][3] - 50.200) < 1e-10  # 正常高 = 椭球高 - zeta
```

---

## 修改阶段规划

按依赖关系排序，每个阶段独立可测试：

### 阶段九：限差修正与观测方法参数化（P4） ✅ 已完成

**完成日期**：2026-06-16

**实际修改**：
- `src/models/common.py` — 新增 `AngleObservationMethod` 枚举 (DIRECTION / MEASUREMENT)
- `src/models/traversing.py` — `TraversingWorkbook` 新增 `angle_observation_method` 字段
- `src/generators/traversing_generator.py` — 接受并传播 `angle_observation_method` 参数
- `src/checkers/traversing_compliance.py` — 限差字典重构为二级嵌套 (grade→method→instrument)；测回法：半测回9″、测回间角值较差10″；修复 GRADE_2/DIRECTION 缩进错误
- `src/checkers/leveling_compliance.py` — 二等水准基辅限差区分数字(0.4/0.6mm)/光学(0.5/0.7mm)，默认数字
- `config/config_leveling.json` — 新增 digital/optical 子字典
- `config/config_traversing.json` — 新增 measurement_method_checks，grade_1.distance.measurement_sets 改为 2
- `tests/test_traversing_compliance.py` — 新增 9 项测试 (测回法合规4 + 传播3 + 负向2)
- `tests/test_leveling_compliance.py` — 新增 5 项测试 (基辅数字/光学限差)

**实际新增测试**：14 项（总计 163 passed）

**遗留**：
- [P0] 水准往返观测及不符值检核（阶段十一）
- [P0] 水准奇偶站观测顺序交替（阶段十一）
- [P1] 导线距离测回数硬编码→配置驱动（阶段十）
- [P1] 导线一测回读数较差限差 5mm vs 10mm（待确认）

### 阶段十：导线生成器参数化（P3 + P5） ✅ 已完成

**完成日期**：2026-06-16

**实际修改**：
- `src/generators/traversing_generator.py`:
  - `_gen_edge_distance()` 新增 `num_sets`、`instrument_height_m`、`prism_height_m` 参数
  - `generate_traversing_workbook()` 新增 `num_distance_sets`（默认2）、`instrument_heights`、`prism_heights`、`default_instrument_height_m`、`default_prism_height_m` 参数
  - 往返测各生成 `num_distance_sets` 个测回（默认2）
  - 仪器高/棱镜高按 `from_point` 查找字典，未指定时回退到默认值
- `tests/test_traversing_generator.py`:
  - `TestDistanceMultipleSets`（4项）：默认2测回、自定义1测回、3测回、多测回合规
  - `TestInstrumentPrismHeights`（4项）：默认高度、自定义默认高度、按点名指定、部分指定回退

**实际新增测试**：8 项（总计 171 passed）

**原始计划**：
- `src/generators/traversing_generator.py` — 测距多测回 + 仪器高/棱镜高参数化
- `tests/test_traversing_generator.py` — 新增多测回和自定义高度测试

**预期测试数**：+4~6 → **实际 +8**

### 阶段十一：水准往返观测（P1 + P2） ✅ 已完成

**完成日期**：2026-06-16

**实际修改**：
- `src/models/leveling.py`:
  - 新增 `ObservationSequence` 枚举 (BACK_FORE_FORE_BACK / FORE_BACK_BACK_FORE)
  - `LevelingStation` 新增 `observation_sequence` 字段
  - `LevelingWorkbook` 新增往返观测字段 (is_round_trip, round_trip_discrepancy_mm, round_trip_limit_mm, round_trip_passed)
- `src/generators/leveling_generator.py`:
  - 新增 `_generate_single_section()` 辅助函数，提取单测段生成逻辑
  - `generate_leveling_workbook()` 新增 `round_trip`、`return_section_id`、`observation_sequence` 参数
  - 往返观测: 生成两个测段（往测 + 返测），返测路线反向
  - 奇偶站交替: 往测奇数站=后前前后/偶数站=前后后前，返测相反
  - uniform模式: 所有站=后前前后
  - 往返测不符值计算: |h_往 + h_返| ≤ 4√L mm
- `src/validators/leveling_validator.py`:
  - `validate_leveling_workbook()` 增加往返测高差不符值验证
- `src/checkers/leveling_compliance.py`:
  - `check_leveling_compliance()` 增加往返测不符值合规检核项
- `tests/test_leveling_round_trip.py` — 新测试文件，18项测试

**实际新增测试**：18 项（总计 189 passed）

**原始计划**：
- 修改8个文件，预期12-16项测试
- **实际修改7个文件，新增18项测试**

**解决P0缺口**：
- ✅ P1：水准往返观测及不符值检核
- ✅ P2：水准奇偶站观测顺序交替

### 阶段十二：转点标记与导线点区分（P6） ✅ 已完成

**完成日期**：2026-06-16

**实际修改**：
- `src/models/common.py`:
  - `RouteInfo` 新增 `intermediate_points: Optional[List[Tuple[str, float]]]` 字段
  - 导入增加 `Tuple`
- `src/models/leveling.py`:
  - `LevelingStation` 新增 `point_type: Optional[str]` 字段 ("control"/"turning")
  - `ExtraLevelingStation` 新增 `point_type: Optional[str]` 字段
- `src/generators/leveling_generator.py`:
  - 新增 `_build_waypoints_and_heights()` 辅助函数: 根据中间控制点自动划分段、分配站数、生成转点名
  - 新增 `_build_point_type_map()` 辅助函数: 构建点号→点类型映射
  - `_generate_single_section()` 重构: 使用新函数构建点序列，各站设置 `point_type`
  - 有中间控制点时使用精确高差 (保证控制点高程正确)，无中间点时保持原有随机分配行为
  - 往返测时反转 `intermediate_points` 顺序
- `tests/test_leveling_turning_points.py` — 新测试文件，21项测试

**实际新增测试**：21 项（总计 210 passed）

**关键技术点**:
- 转点命名区分段号: `TP.{段号}.{段内序号}` (如 TP.1.1, TP.2.1)
- 段站数按高差比例分配，每段至少1站
- 控制点 (起/终/中间点) → `"control"`, 转点 (TP.x.y) → `"turning"`
- 有中间点时使用精确高差 (heights[i+1]-heights[i])，保证控制点高程精确
- 无中间点时保持原有行为 (随机分配 + 末站校正)

### 阶段十三：高程基准转换（P7） ✅ 已完成

**完成日期**：2026-06-16

**实际修改**：
- `src/preconditions/height_datum.py` — 新模块:
  - `convert_ellipsoid_to_normal()`: 椭球高→正常高转换 (A6.1)
  - `check_height_datum_consistency()`: 高程基准一致性检查
  - 支持三种 zeta 模式: constant(常数)/linear(线性内插)/per_point(逐点指定)
  - `HeightDatumItem`/`HeightDatumReport` 数据结构: 记录转换细节、delta_zeta、警告
  - delta_zeta > 10mm 时自动警告 (可能影响高差闭合差)
- `src/preconditions/__init__.py` — 导出新模块
- `tests/test_height_datum.py` — 新测试文件，30项测试

**实际新增测试**：30 项（总计 240 passed）

**关键技术点**:
- A6.1: `H_normal = h_ellipsoid - zeta`
- A6.2: `delta_zeta = zeta_i - zeta_{i-1}` — 常数 zeta 下 delta_zeta=0 (高差不变), 变化 zeta 下高差改变 delta_zeta
- 常数 zeta 短路线近似: delta_zeta ≈ 0, 高差不受影响
- 线性 zeta 长路线: 起终点 zeta 线性内插中间点
- per_point 模式: 逐点指定 zeta (最灵活)
- 集成测试验证: 转换后正常高可直接输入水准/导线生成器

---

## 总结

| 阶段 | 问题 | 核心修改 | 实际新增测试 |
|------|------|---------|-------------|
| 九 | P4 限差修正 | 检核器+配置 | 14 |
| 十 | P3+P5 测距多测回+高度参数化 | 导线生成器 | 8 |
| 十一 | P1+P2 往返观测+奇偶站顺序 | 水准全链路 | 18 |
| 十二 | P6 转点标记 | 水准生成器+模型 | 21 |
| 十三 | P7 高程基准转换 | 新模块 | 30 |
| **合计** | | | **91** |

完成阶段九至十一后（约 P0+P1 全部），即可生成符合林场实习观测模式的导线+水准手簿。阶段十二和十三为增强功能。
