# AGENTS.md - 模拟观测数据生成系统

## 项目概述

本项目是一个**测绘教学数据模拟系统**，核心目标是：以 RTK 测量的三维坐标作为数学真值，逆向生成符合测量规范格式的水准测量和导线测量观测手簿数据。生成的数据在逻辑上自洽，可通过规范检核，用于教学演示而非工程应用。

项目位置：`D:\Data\Documents\模拟观测数据CeHui\`

## 核心数学框架

### 正向映射与逆向构造

水准测量和导线测量的正向映射（观测数据 -> 坐标/高程）是一个**线性商映射**：高维观测空间通过核心导出量（高差、方位角、平距）压缩到低维坐标空间。逆向构造（坐标 -> 观测数据）的解空间是一个高维仿射子空间，必须通过人为参数锁定和核空间约束来采样。

### 核空间约束（不可违反）

核空间中的扰动不改变核心导出量，是模拟数据保持数学自洽的根本条件：

- **水准测量（单面尺）**：后视和前视读数施加同向等量扰动，即 delta_a = delta_b
- **水准测量（双面尺）**：黑红面同步扰动，delta_a_black + delta_a_red = delta_b_black + delta_b_red
- **导线角度**：盘左盘右扰动保持方向值不变，delta_L = delta_R，2C = 2*delta
- **导线距离**：斜距与竖直角扰动满足 delta_S * sin(Z) + S * cos(Z) * delta_Z = 0

### 精度等级与可模拟性

RTK 典型精度（平面 1-3 cm，高程 2-5 cm）构成物理硬上限。在数学真值假设下（忽略 RTK 物理噪声），通过控制核空间扰动幅度可模拟任意精度等级。扰动幅度 sigma 是人为控制参数，与 RTK 物理噪声无关。

## 涉及的测量类型

### 水准测量（Leveling）

按等级从高到低：二等（DS05/DS1 + 因瓦尺）、三四等（DS3 + 双面木质尺）、等外/图根。

核心观测表结构：表头（日期/天气/仪器/人员） + 表体（逐站记录：后视上/下/中丝、前视上/下/中丝、视距、视距差、累积差、黑红面/基辅读数、高差中数） + 检核区。

从 RTK 高程反演需人为设定的参数：视线高 H_sight（每站独立）、视距对（前后视距）、尺型与 K 值、黑红面/基辅分划系统。

关键规范：GB/T 12897-2006（一、二等水准）、GB/T 12898-2009（三、四等水准）。

### 导线测量（Traversing）

一级导线参数：测角中误差 <= 5"，方位角闭合差 <= +/-10*sqrt(n)"，全长相对闭合差 <= 1/15000，2C 互差 <= 13"（2"级仪器），半测回较差 <= 12"，方向值较差 <= 9"。

核心观测表体系：水平角观测记录表（方向观测法/测回法） + 水平距离观测记录表 + 导线成果计算表。

从 RTK 坐标反演需人为设定的参数：度盘零位配置、左角/右角定义、仪器高/棱镜高、测回数与仪器等级。

关键规范：GB 50026-2020（工程测量标准）。

## 技术栈

- 语言：Python
- 数学计算：NumPy（随机扰动生成、矩阵运算）
- 数据输出：openpyxl（Excel 手簿）、标准输出（文本/Markdown 表格）
- 配置管理：JSON（规范参数、观测程序参数）
- 测试：pytest（正向验证器 + 端到端集成测试）

## 开发阶段（按瀑布式依赖排列）

### 阶段一：公理模型冻结 ✅ 已完成

交付物:
- `docs/axiom_leveling.md` — 水准正向模型公理 (A1-A9, 含核空间约束)
- `docs/axiom_traversing.md` — 导线正向模型公理 (A1-A9, 含核空间约束)
- `docs/error_propagation.md` — 误差传播模型 (RTK噪声传播 + 扰动设计规范)

已通过数学验证，修复了核空间维度公式、方位角噪声 sqrt(2) 因子、红面改正符号等问题。

### 阶段二：规范参数收集与配置化 ✅ 已完成

交付物:
- `config/config_leveling.json` — 水准限差与仪器参数 (二等/三等/四等/等外)
- `config/config_traversing.json` — 导线限差与仪器参数 (一级/二级/图根)
- `config/config_observation_program.json` — 度盘配置、观测顺序、默认模拟参数、输出格式

已从 kimi.md 提取全部规范参数并交叉验证。修复了导线扰动 sigma 偏差 (2.5-4x)、补充了缺失的数值保护参数 (cos(Z) guard, flat-distance epsilon)、高程基准转换控制和可行性预检参数。待人工复核 S 级规范原文。

### 阶段三：表格 Schema 与数据结构设计 ✅ 已完成

交付物:
- `src/models/common.py` — 通用类型: 枚举 (等级/尺型/盘位/角度定义)、元数据 (SurveyMetadata/RouteInfo/TraverseInfo)、精度常量、GenerationMetadata
- `src/models/leveling.py` — 水准手簿模型: RodSpec、LevelingReading (含视距计算)、LevelingStation (含视线高)、LevelingSection、LevelingWorkbook
- `src/models/traversing.py` — 导线手簿模型: DirectionReading、AngleSet (含 β_L/β_R/β_set)、StationAngleObservation、DistanceReading (含斜距/平距标记)、DistanceSet、EdgeDistanceObservation、TraversePointRecord (含三角高程)、TraverseComputation、TraversingWorkbook

已通过交叉验证: 修复了距离读数斜距/平距歧义 (DistanceSet→List[DistanceReading])、补充半测回角值字段 (β_L/β_R/β_set)、修正精度注释错误 (4dp=0.1mm非1mm)、添加视线高字段和 GenerationMetadata。

### 阶段四：正向验证器实现 ✅ 已完成

交付物:
- `src/validators/leveling_validator.py` — 水准正向验证器: 逐站高差计算 (黑/红面)、K+黑-红检核、红面高差改正 (h_red = a_red - b_red - (K_back - K_fore))、高差中数、视距差/累积差、路线闭合差、高程传递
- `src/validators/traversing_validator.py` — 导线正向验证器: 角度归算 (2C=L-(R-π)、方向值、半测回角、测回角)、方位角传递 (左角/右角)、斜距→平距改正、坐标增量传递、闭合差 (f_x/f_y/f_D/K)
- `tests/test_leveling_validator.py` — 10 个测试: 基本高差、双面尺检核、红面改正、三等路线闭合、等外水准
- `tests/test_traversing_validator.py` — 14 个测试: 角度归算、方位角传递、测回角计算、距离改正、完整导线闭合

修复了公理 A5.4 红面高差符号错误 (+ → -)，24/24 测试通过。

### 阶段五：逆向生成器实现 ✅ 已完成

交付物:
- `src/generators/__init__.py` — 生成器模块导出
- `src/generators/_utils.py` — 共享工具: 截断正态采样、单位转换 (arcsec↔rad, mm↔m)、角度归一化
- `src/generators/leveling_generator.py` — 水准逆向生成器: 支持二等(因瓦基辅)、三四等(双面尺)、等外(变动仪高法)。核空间扰动 + 末站闭合差校正。
- `src/generators/traversing_generator.py` — 导线逆向生成器: 支持一级/二级/图根导线。核空间角度扰动(同站同测回所有方向共用 delta_dir) + 精确距离(数学真值模式)。
- `tests/test_leveling_generator.py` — 16 个测试: 三等(7)、二等(2)、四等(1)、等外(2)、可复现性(2)、元数据(2)
- `tests/test_traversing_generator.py` — 9 个测试: 一级(3)、二级(1)、图根(1)、右角(1)、可复现性(2)、元数据(1)

关键技术点:
- 水准核空间: delta 同向等量施加于后视+前视, 高差 a-b 精确不变
- 导线核空间: delta_dir 所有方向共用, 水平角 = DV_fore - DV_back 精确不变
- 末站闭合差校正: 水准最后一站前视加 closure (黑红面同步), 导线距离使用精确真值
- 49/49 测试通过 (阶段四 24 + 阶段五 25)

### 阶段六：检核器与合规性验证 ✅ 已完成

交付物:
- `src/checkers/__init__.py` — 合规检核模块导出
- `src/checkers/leveling_compliance.py` — 水准合规检核: 视距长度/视距差/累积差/K+黑-红/黑红面高差之差/基辅读数差/基辅高差之差/闭合差/变动仪高较差
- `src/checkers/traversing_compliance.py` — 导线合规检核: 2C互差/半测回较差/方向值跨测回较差/距离读数差/往返测较差/方位角闭合差/全长相对闭合差
- `tests/test_leveling_compliance.py` — 15 个测试: Grade2/3/4/Extra合规 + 3个负向超限测试 + 报告结构
- `tests/test_traversing_compliance.py` — 16 个测试: Grade1/2/Root/右角合规 + 3个负向超限测试 + 报告结构

关键技术点:
- 限差参数硬编码在 _LEVELING_LIMITS / _TRAVERSING_LIMITS 字典中, 与 config JSON 保持一致
- 合规检核器内部先调用正向验证器填充计算字段, 再逐项比较
- 方向值跨测回较差: 使用逐对圆周距离 min(|a-b|, 2π-|a-b|) 避免 2π 跳变
- 图根导线 half_set_diff 限差设为 30" (根级 sigma_2c=15" 产生的自然分散)
- 补充计算字段: azimuth_closure_limit_arcsec, relative_closure_limit, max_direction_diff_across_sets_arcsec
- 80/80 测试通过 (阶段四 24 + 阶段五 25 + 阶段六 31)

### 阶段七：集成与输出格式化 ✅ 已完成

交付物:
- `src/formatters/__init__.py` — 格式化模块导出
- `src/formatters/_utils.py` — 共享工具: rad_to_dms (精确常数 180*3600/π)、format_meter/mm/arcsec、build_disclaimer
- `src/formatters/json_formatter.py` — JSON 序列化: dataclasses.asdict() + Enum/float 处理 + 自动附加教学声明
- `src/formatters/text_formatter.py` — 纯文本 (等宽对齐表格) + Markdown (管道表格): 水准/导线手簿完整输出, 按等级适配列
- `src/formatters/excel_formatter.py` — Excel (openpyxl): 表头加粗+灰底+列宽自适应(CJK双宽), 水准3Sheet/导线4Sheet
- `tests/test_formatters.py` — 24 个测试: DMS转换(5) + 格式函数(3) + 声明构建(2) + JSON(4) + Text(5) + Markdown(2) + Excel(3)
- `tests/test_e2e.py` — 18 个测试: 水准三等/二等/等外 E2E + 导线一级/二级/图根 E2E + 声明一致性 + 可复现性

关键技术点:
- DMS 转换使用精确常数 `_ARCSEC_PER_RAD = 180.0 * 3600 / math.pi` (非近似 206265), 保证 π/2 → 90°00'00.0" 恰好
- 分解前 round(total_arcsec, 1) 消除残余浮点噪声
- JSON 序列化: _clean_dict() 过滤下划线前缀字段, Enum → .value
- Excel CJK 列宽: ord(c) > 127 计 2 宽度, 确保中文字符对齐
- ExtraLevelingSection 无 station_count 字段, 用 getattr 安全访问
- 122/122 测试通过 (前阶段 80 + 阶段七 42)

### 阶段八：前置条件与边界处理 (可行性预检 ✅ 已完成)

交付物:
- `src/preconditions/__init__.py` — 前置条件模块导出
- `src/preconditions/feasibility.py` — 可行性预检: 水准(A7.1)+导线(A7.2) RTK精度vs目标等级判定
- `tests/test_feasibility.py` — 27 个测试: 水准预检(9)+导线预检(10)+辅助函数(4)+报告结构(4)

关键技术点:
- 水准 (A7.1): sigma_dh = √2 × sigma_H, 与目标每站高差中误差 × 3 比较
- 导线 (A7.2): sigma_alpha = (sigma_XY / D_min) × ρ, 与目标测角中误差 × 3 比较
- 数学真值模式: 跳过预检, 附加 mandatory_disclaimer
- 各等级判定基准硬编码: 水准 0.15/1.9/3.2/6.3 mm, 导线 5/10/25 arcsec
- 导线最短边长可从坐标自动计算或显式指定
- 结论: 默认 RTK 精度 (σ_H=3cm, σ_XY=2cm) 下, 所有水准等级不可行; 导线一级不可行(D<400m), 图根长边可行
- 149/149 测试通过 (前阶段 122 + 阶段八 27)

待完成:
- 高程基准转换（椭球高 -> 正常高, A6 公式已冻结）
- 坐标系统一致性检查

## 编码约定

- 所有物理量使用 SI 单位内部存储（米、弧度），仅在输出格式化时转换为测绘惯例（毫米、度分秒）
- 角度运算统一使用弧度制内部计算，避免浮点精度损失
- 核空间约束方程必须作为硬编码校验（assert），不可被配置关闭
- 随机数种子可配置，保证结果可复现
- 每个生成器函数必须返回元数据字典，记录所用参数和扰动强度

## 关键限制与合规声明

1. 本系统生成的数据**仅供教学演示**，不可用于工程验收或成果提交
2. 每个输出文件必须自动附加数据来源声明与精度等级标注
3. RTK 椭球高与正常高的差异（高程异常 zeta）在数公里范围内可达分米级，若未转换将导致系统性偏差
4. 构造的视距、仪器高与 RTK 测量时的实际空间位置无关，不能反推实际观测站位

## 参考规范

- GB/T 12897-2006：国家一、二等水准测量规范
- GB/T 12898-2009：国家三、四等水准测量规范
- GB 50026-2020：工程测量标准
- 参考对话记录：kimi.md（含完整数学推导与可行性分析）

## Session Startup

1. 阅读本文件了解项目背景与数学框架
2. 如需理解详细推导过程，阅读 kimi.md 对应章节
3. 检查当前开发阶段进度，从对应阶段继续工作
4. 涉及规范参数时，优先检查阶段二已锁定的 JSON 配置文件
