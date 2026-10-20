"""可编辑的"数据读取方式"预设（5 个槽位）
=========================================

界面里只保留 5 个预设槽位，和第 1 个默认的"拉伸应力–应变"。
每个槽位存的是**怎么读数据**，而不是数据本身：

* X / Y 的物理量类型（``kind``），或
* X / Y 直接指定的列（按**第一行表头**匹配），
* 轴标题与单位的覆盖值。

用户改好一套映射后按「保存到预设」写进当前槽位，下次点一下就回来；
槽位可以重命名、清空，全部存到 ``~/.strainplot/presets.json``。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from . import variables as V
from .dataio import XYMap
from .style import CONFIG_DIR

SLOT_COUNT = 5
SLOTS_FILE = os.environ.get("STRAINPLOT_PRESETS") or os.path.join(CONFIG_DIR, "presets.json")

# 第 1 个槽位的出厂值：就是这套程序原本的用途
FACTORY_NAME = "拉伸 · 应变–应力"
FACTORY_X, FACTORY_Y = "strain", "stress"


@dataclass
class Slot:
    """一个读取方式预设。"""

    name: str = ""
    x_kind: str = ""
    y_kind: str = ""
    x_col: str = ""
    y_col: str = ""
    x_label: str = ""
    y_label: str = ""
    x_unit: str | None = None
    y_unit: str | None = None

    # ---- 状态 -------------------------------------------------------------
    def is_blank(self) -> bool:
        """空槽位：什么都没设。"""
        return not (self.x_kind or self.y_kind or self.x_col or self.y_col
                    or self.x_label or self.y_label)

    def is_custom(self) -> bool:
        return bool(self.x_col or self.y_col)

    def display(self) -> str:
        if self.is_blank():
            return "（空）"
        if self.name:
            return self.name
        if self.is_custom():
            return f"{self.x_col or 'X'} – {self.y_col or 'Y'}"
        return f"{V.kind(self.x_kind).label} – {V.kind(self.y_kind).label}"

    # ---- 与 XYMap 互转 -----------------------------------------------------
    def to_xymap(self) -> XYMap:
        return XYMap(
            x_kind=self.x_kind or ("plain" if self.x_col else "strain"),
            y_kind=self.y_kind or ("plain" if self.y_col else "stress"),
            x_col=self.x_col,
            y_col=self.y_col,
            x_label=self.x_label,
            y_label=self.y_label,
            x_unit=self.x_unit,
            y_unit=self.y_unit,
        )

    @classmethod
    def from_xymap(cls, xmap: XYMap, name: str = "") -> "Slot":
        return cls(
            name=name,
            x_kind=xmap.x_kind or "",
            y_kind=xmap.y_kind or "",
            x_col=xmap.x_col,
            y_col=xmap.y_col,
            x_label=xmap.x_label,
            y_label=xmap.y_label,
            x_unit=xmap.x_unit,
            y_unit=xmap.y_unit,
        )

    # ---- JSON -------------------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "x_kind": self.x_kind,
            "y_kind": self.y_kind,
            "x_col": self.x_col,
            "y_col": self.y_col,
            "x_label": self.x_label,
            "y_label": self.y_label,
            "x_unit": self.x_unit,
            "y_unit": self.y_unit,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Slot":
        valid = {k.id for k in V.KINDS}
        xk = str(data.get("x_kind") or "")
        yk = str(data.get("y_kind") or "")

        def unit(v):
            if v is None:
                return None
            v = str(v)
            return v or None

        return cls(
            name=str(data.get("name") or ""),
            x_kind=xk if xk in valid else "",
            y_kind=yk if yk in valid else "",
            x_col=str(data.get("x_col") or ""),
            y_col=str(data.get("y_col") or ""),
            x_label=str(data.get("x_label") or ""),
            y_label=str(data.get("y_label") or ""),
            x_unit=unit(data.get("x_unit")),
            y_unit=unit(data.get("y_unit")),
        )


def factory_slots() -> list[Slot]:
    """出厂预设：第 1 个是应力–应变，其余 4 个空白。"""
    slots = [Slot(name=FACTORY_NAME, x_kind=FACTORY_X, y_kind=FACTORY_Y)]
    slots += [Slot() for _ in range(SLOT_COUNT - 1)]
    return slots


def slot_label(index: int, slot: Slot) -> str:
    return f"{index + 1} · {slot.display()}"


def load(path: str = SLOTS_FILE) -> list[Slot]:
    """读用户预设；文件缺失或损坏时退回出厂值。"""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        items = raw.get("slots") if isinstance(raw, dict) else raw
        slots = [Slot.from_dict(d) for d in (items or []) if isinstance(d, dict)]
    except Exception:                                    # noqa: BLE001
        return factory_slots()
    if not slots:
        return factory_slots()
    slots = slots[:SLOT_COUNT]
    while len(slots) < SLOT_COUNT:
        slots.append(Slot())
    return slots


def save(slots: list[Slot], path: str = SLOTS_FILE) -> str:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    data = {"version": 1, "slots": [s.to_dict() for s in slots[:SLOT_COUNT]]}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    return path
