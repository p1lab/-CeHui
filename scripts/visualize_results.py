#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
可视化成果文件中的水准与导线数据。

本脚本为独立工具，仅读取 output/*.md 成果文件并生成静态图表，
不修改项目源码，也不依赖项目的内部模块。
运行方式：
    py -3.8 scripts/visualize_results.py
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional

import matplotlib.pyplot as plt
import pandas as pd


# 配置中文字体（Windows 常见字体）
plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "Arial Unicode MS"]
plt.rcParams["axes.unicode_minus"] = False


# ---------------------------------------------------------------------------
# Markdown 解析辅助函数
# ---------------------------------------------------------------------------
def read_markdown_file(path: Path) -> str:
    with path.open("r", encoding="utf-8") as f:
        return f.read()


def extract_section_lines(md_text: str, section_header: str) -> Optional[List[str]]:
    """从 Markdown 文本中提取指定二级标题后的表格行。"""
    lines = md_text.splitlines()
    in_section = False
    section_lines: List[str] = []
    for line in lines:
        if line.strip().startswith(f"## {section_header}"):
            in_section = True
            continue
        if in_section:
            if line.strip().startswith("## ") and not line.strip().startswith("## |"):
                break
            section_lines.append(line)
    return section_lines if section_lines else None


def parse_markdown_table(section_lines: List[str]) -> pd.DataFrame:
    """解析 Markdown 管道表为 pandas DataFrame。"""
    table_lines = [ln for ln in section_lines if ln.strip().startswith("|")]
    if not table_lines:
        raise ValueError("未找到 Markdown 表格")

    rows = []
    for line in table_lines:
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        rows.append(cells)

    header = rows[0]
    # 跳过分隔行（如 | --- | --- | ）
    data_rows = [r for r in rows[1:] if not all(re.fullmatch(r"-+", c) for c in r)]
    return pd.DataFrame(data_rows, columns=header)


# ---------------------------------------------------------------------------
# 水准可视化
# ---------------------------------------------------------------------------
def visualize_leveling(df: pd.DataFrame, output_dir: Path, base_name: str) -> Path:
    """生成水准测量成果图表：高程剖面 + 改正数分布。"""
    numeric_cols = ["距离(km)", "观测高差(m)", "改正数(mm)", "改正后高差(m)", "高程(m)"]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    fig, axes = plt.subplots(2, 1, figsize=(10, 10), constrained_layout=True)
    fig.suptitle(f"{base_name} — 水准测量成果可视化", fontsize=14)

    # 高程剖面
    ax = axes[0]
    ax.plot(df["距离(km)"], df["高程(m)"], marker="o", linestyle="-", color="steelblue", label="高程")
    for i, row in df.iterrows():
        ax.annotate(row["点名"], (row["距离(km)"], row["高程(m)"]), textcoords="offset points", xytext=(0, 8), ha="center", fontsize=8)
    ax.set_xlabel("累积距离 (km)")
    ax.set_ylabel("高程 (m)")
    ax.set_title("路线高程剖面")
    ax.grid(True, linestyle="--", alpha=0.6)
    ax.legend()

    # 改正数
    ax = axes[1]
    colors = ["coral" if v < 0 else "seagreen" for v in df["改正数(mm)"]]
    ax.bar(df["点名"], df["改正数(mm)"], color=colors)
    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_xlabel("点名")
    ax.set_ylabel("改正数 (mm)")
    ax.set_title("各点平差改正数")
    ax.tick_params(axis="x", rotation=45)
    ax.grid(True, axis="y", linestyle="--", alpha=0.6)

    out_path = output_dir / f"{base_name}_visualization.png"
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return out_path


# ---------------------------------------------------------------------------
# 导线可视化
# ---------------------------------------------------------------------------
def visualize_traversing(df: pd.DataFrame, output_dir: Path, base_name: str) -> Path:
    """生成导线测量成果图表：平面图 + 方位角变化 + 改正向量。"""
    numeric_cols = ["距离(m)", "Δx(m)", "Δy(m)", "v_x(mm)", "v_y(mm)", "Δx改(m)", "Δy改(m)", "X(m)", "Y(m)"]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    points = df.dropna(subset=["X(m)", "Y(m)"]).copy()
    edges = df[df["点名"].astype(str).str.contains("edge")].copy()

    fig, axes = plt.subplots(1, 3, figsize=(18, 6), constrained_layout=True)
    fig.suptitle(f"{base_name} — 导线测量成果可视化", fontsize=14)

    # 1. 导线平面图
    ax = axes[0]
    ax.plot(points["X(m)"], points["Y(m)"], marker="o", linestyle="-", color="navy", label="导线")
    for _, row in points.iterrows():
        ax.annotate(row["点名"], (row["X(m)"], row["Y(m)"]), textcoords="offset points", xytext=(5, 5), fontsize=8)
    ax.set_xlabel("X (m)")
    ax.set_ylabel("Y (m)")
    ax.set_title("导线点平面图")
    ax.axis("equal")
    ax.grid(True, linestyle="--", alpha=0.6)
    ax.legend()

    # 2. 各边距离
    ax = axes[1]
    edge_names = edges["点名"].astype(str).str.replace("edge_", "").str.replace("_", "→")
    ax.barh(edge_names, edges["距离(m)"], color="teal")
    ax.set_xlabel("距离 (m)")
    ax.set_title("各边边长")
    ax.grid(True, axis="x", linestyle="--", alpha=0.6)

    # 3. 坐标改正数对比
    ax = axes[2]
    x = range(len(edges))
    width = 0.35
    ax.bar([i - width / 2 for i in x], edges["v_x(mm)"], width, label="v_x", color="darkred")
    ax.bar([i + width / 2 for i in x], edges["v_y(mm)"], width, label="v_y", color="darkblue")
    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_xticks(x)
    ax.set_xticklabels(edge_names, rotation=45, ha="right", fontsize=7)
    ax.set_ylabel("改正数 (mm)")
    ax.set_title("各边坐标增量改正数")
    ax.legend()
    ax.grid(True, axis="y", linestyle="--", alpha=0.6)

    out_path = output_dir / f"{base_name}_visualization.png"
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return out_path


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
def main() -> None:
    project_root = Path(__file__).resolve().parent.parent
    output_dir = project_root / "output"
    viz_dir = output_dir / "visualization"
    viz_dir.mkdir(exist_ok=True)

    results: List[Path] = []

    # 水准
    leveling_md = output_dir / "二等水准观测手簿.md"
    if leveling_md.exists():
        text = read_markdown_file(leveling_md)
        lines = extract_section_lines(text, "成果计算")
        if lines:
            df = parse_markdown_table(lines)
            path = visualize_leveling(df, viz_dir, "二等水准")
            results.append(path)

    # 导线
    traversing_md = output_dir / "一级导线观测手簿.md"
    if traversing_md.exists():
        text = read_markdown_file(traversing_md)
        lines = extract_section_lines(text, "成果计算")
        if lines:
            df = parse_markdown_table(lines)
            path = visualize_traversing(df, viz_dir, "一级导线")
            results.append(path)

    if results:
        print("可视化图表已生成：")
        for p in results:
            print(f"  {p}")
    else:
        print("未生成任何图表，请检查 output/ 目录下的 Markdown 成果文件。")


if __name__ == "__main__":
    main()
