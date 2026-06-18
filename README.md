# 模拟观测数据生成系统

测绘教学数据模拟系统 —— 以 RTK 测量的三维坐标作为数学真值，逆向生成符合测量规范格式的水准测量与导线测量观测手簿数据。

> **教学声明**：本系统生成的数据**仅供教学演示**，不可用于工程验收或成果提交。

## 项目简介

本项目面向测绘教学场景，核心目标是：

- 以 RTK 三维坐标/高程为**数学真值**；
- 逆向构造符合 GB/T 12897、GB/T 12898、GB 50026 等规范格式的水准与导线观测手簿；
- 保证生成的数据在数学上自洽、可通过规范检核、支持平差计算与成果输出；
- 提供文本、Markdown、Excel、JSON 等多种输出格式，并支持可视化。

## 核心功能

| 模块 | 功能 |
|---|---|
| **数据模型** | 水准手簿、导线手簿、平差成果等完整数据结构 |
| **逆向生成器** | 从 RTK 真值生成水准/导线观测数据，支持核空间扰动、往返测、非对称误差等 |
| **正向验证器** | 按规范公式验证观测数据，计算高差、方位角、坐标增量、闭合差等 |
| **合规检核器** | 对照规范限差检查视距差、2C 互差、方位角闭合差、全长相对闭合差等 |
| **平差计算** | 简易平差：角度闭合差分配、坐标增量闭合差分配，改正后终点精确归位 |
| **格式化输出** | Markdown 手簿、Excel 工作簿、JSON 序列化、纯文本表格 |
| **可行性预检** | RTK 精度与目标等级可模拟性判定、高程基准转换检查 |
| **可视化** | 基于成果 Markdown 文件生成高程剖面、导线平面图等静态图表 |

## 技术栈

- **语言**：Python 3.8+
- **数学计算**：NumPy
- **数据处理**：pandas（可视化脚本使用）
- **Excel 输出**：openpyxl
- **数据可视化**：matplotlib
- **测试**：pytest
- **配置**：JSON

## 项目结构

```text
模拟观测数据CeHui/
├── config/                     # 规范参数与观测程序配置
│   ├── config_leveling.json
│   ├── config_observation_program.json
│   └── config_traversing.json
├── docs/                       # 设计文档与公理模型
│   ├── axiom_leveling.md
│   ├── axiom_traversing.md
│   └── error_propagation.md
├── output/                     # 生成的手簿与可视化成果
│   ├── visualization/          # 可视化图表
│   ├── 二等水准观测手簿.md
│   ├── 二等水准观测手簿.xlsx
│   ├── 一级导线观测手簿.md
│   └── 一级导线观测手簿.xlsx
├── sample/                     # 示例 RTK 坐标数据
├── scripts/                    # 可执行脚本
│   ├── simulate_forest_farm.py # 林场实习全流程模拟
│   └── visualize_results.py    # 成果可视化
├── src/                        # 核心源码
│   ├── adjustment/             # 平差计算
│   ├── checkers/               # 合规检核
│   ├── formatters/             # 输出格式化
│   ├── generators/             # 逆向生成器
│   ├── models/                 # 数据模型
│   ├── preconditions/          # 可行性预检与高程基准转换
│   └── validators/             # 正向验证器
├── tests/                      # pytest 测试集
├── AGENTS.md                   # 开发阶段总览
├── agents_S2.md                # 阶段九至十三记录
├── AGENTS_S3.md                # 阶段十四至十七记录
└── kimi.md                     # 数学推导与可行性分析
```

## 安装与依赖

本项目核心模块仅依赖 Python 标准库、NumPy 与 openpyxl：

```bash
pip install numpy openpyxl
```

运行测试需要 pytest：

```bash
pip install pytest
```

可视化脚本需要 pandas 与 matplotlib：

```bash
pip install pandas matplotlib
```

> 注：当前开发环境中，Python 3.8 已预装 pandas 与 matplotlib，可直接通过 `py -3.8 scripts/visualize_results.py` 运行可视化脚本。

## 快速开始

### 1. 运行林场实习模拟脚本

```bash
python scripts/simulate_forest_farm.py
```

该脚本会生成完整的二等水准往返测手簿与一级附合导线手簿，输出到 `output/` 目录。

### 2. 运行可视化脚本

```bash
py -3.8 scripts/visualize_results.py
```

生成的高程剖面图与导线平面图保存于 `output/visualization/`。

### 3. 运行测试

```bash
pytest -q
```

当前全量测试：344 项通过。

## 使用示例

### 生成三等水准单程手簿

```python
from src.generators.leveling_generator import generate_leveling_workbook
from src.models.common import LevelingGrade, RouteInfo

route = RouteInfo("BM.A", 100.0, "BM.B", 108.0, total_length_km=1.5)
wb = generate_leveling_workbook(
    route=route,
    grade=LevelingGrade.GRADE_3,
    num_stations=8,
    seed=42,
)
```

### 生成一级附合导线手簿

```python
from src.generators.traversing_generator import generate_traversing_workbook
from src.models.common import TraversingGrade, TraverseInfo

info = TraverseInfo(
    start_point_name="B",
    end_point_name="G",
    start_reference_point="B2",
    end_reference_point="G2",
)
wb = generate_traversing_workbook(
    traverse_info=info,
    grade=TraversingGrade.GRADE_1,
    seed=42,
)
```

## 核心数学框架

- **正向映射**：观测数据 → 高差/方位角/平距 → 坐标/高程，是一个线性商映射。
- **逆向构造**：坐标/高程 → 观测数据，解空间为高维仿射子空间，通过核空间约束采样。
- **核空间约束**：扰动不改变核心导出量，是数据自洽的根本。例如水准单面尺中 `delta_a = delta_b`。
- **平差计算**：基于正向解算结果二次解算，分配角度闭合差与坐标增量闭合差，使改正后终点精确归位。

详见 `docs/axiom_leveling.md`、`docs/axiom_traversing.md` 与 `kimi.md`。

## 重要限制与合规声明

1. 本系统生成的数据**仅供教学演示**，不可用于工程验收或成果提交。
2. 每个输出文件自动附加数据来源声明与精度等级标注。
3. RTK 椭球高与正常高的差异（高程异常 ζ）在数公里范围内可达分米级，若未转换将导致系统性偏差。
4. 构造的视距、仪器高与 RTK 测量时的实际空间位置无关，不能反推实际观测站位。

## 参考规范

- GB/T 12897-2006：国家一、二等水准测量规范
- GB/T 12898-2009：国家三、四等水准测量规范
- GB 50026-2020：工程测量标准

## 开发阶段

项目按瀑布式阶段推进，共完成 25 个阶段：

- 阶段一至八：公理模型、规范参数、数据模型、验证器、生成器、检核器、格式化输出、可行性预检
- 阶段九至十三：林场实习观测模式适配（往返测、奇偶站交替、多测回、转点标记、高程基准转换）
- 阶段十四至十七：数据真实性改进（角度/距离分散、可控闭合差、附合导线外部方位基准）
- 阶段十八至二十四：平差计算与成果输出（平差、成果表格式化、端到端测试）
- 阶段二十五：水准往返测非对称误差支持

详见 `AGENTS.md` 及各阶段实施记录。
