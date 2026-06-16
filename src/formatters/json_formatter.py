# src/formatters/json_formatter.py
# JSON 格式化器
#
# 将 LevelingWorkbook / TraversingWorkbook 序列化为 JSON 字符串.
# 使用 dataclasses.asdict() + 自定义 default handler.

from __future__ import annotations

import json
import dataclasses
from enum import Enum
from typing import Any

from ..models.leveling import LevelingWorkbook
from ..models.traversing import TraversingWorkbook
from ._utils import build_disclaimer


def _default_handler(obj: Any) -> Any:
    """JSON 序列化 fallback: Enum → value, 其他 → str."""
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, float):
        if obj != obj:  # NaN
            return None
        return obj
    return str(obj)


def _clean_dict(d: dict) -> dict:
    """清理 asdict 输出: 移除内部字段 (以 _ 开头), 处理 Optional None."""
    result = {}
    for k, v in d.items():
        if k.startswith('_'):
            continue
        if isinstance(v, dict):
            v = _clean_dict(v)
        elif isinstance(v, list):
            v = [_clean_dict(item) if isinstance(item, dict) else item
                 for item in v]
        elif isinstance(v, Enum):
            v = v.value
        result[k] = v
    return result


def workbook_to_json(
    workbook,
    indent: int = 2,
    include_compliance: bool = False,
) -> str:
    """
    将手簿序列化为 JSON 字符串.

    参数:
        workbook: LevelingWorkbook 或 TraversingWorkbook
        indent: JSON 缩进 (默认 2)
        include_compliance: 是否包含合规检核结果 (需先运行检核器)

    返回:
        JSON 字符串
    """
    d = dataclasses.asdict(workbook)
    d = _clean_dict(d)

    # 添加教学声明
    d["disclaimer"] = build_disclaimer(workbook)

    return json.dumps(d, indent=indent, ensure_ascii=False, default=_default_handler)
