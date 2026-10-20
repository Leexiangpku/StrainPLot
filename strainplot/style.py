"""图表样式定义
================

所有"可视化可编辑"的属性都集中在这里，``Style`` 可序列化成 JSON 以便保存/调用模板。
默认值来自用户提供的 Origin 参考图实测结果：

* 页面 4×3 in，导出 600 dpi → 2400×1800 px（与参考图一致）
* 字体 Arial Bold，刻度字号 11，坐标轴标题字号 12
* 文字/坐标轴颜色 #333333（Origin 默认"黑色"实际为 51,51,51）
* 坐标框四条边、刻度朝内、主刻度 3.5 pt、次刻度 1.6 pt、线宽 1.0 pt
* 图例左上角、无边框、单行图例线段长 18 pt
"""
from __future__ import annotations

import copy
import json
import os
from dataclasses import asdict, dataclass, field
from typing import Any

TEXT_COLOR = "#333333"

# 角色（字体/字号的不同用途）
ROLES = ("tick", "title", "legend", "note")


@dataclass
class AxisStyle:
    """单条坐标轴的属性。"""

    label: str = "Strain (%)"
    scale: str = "linear"          # linear | log
    auto_range: bool = True        # 自动范围（按数据 + 留白）
    vmin: float = 0.0
    vmax: float = 100.0
    pad_pct: float = 10.0          # 自动留白（% 数据跨度，单侧）
    major: float = 0.0             # 主刻度间隔，0 = 自动
    minor_sub: int = 5             # 每两个主刻度之间的次刻度数，0/1 = 不画
    num_fmt: str = "auto"          # auto | %.0f | %.1f | %.2f | %.3g | sci

    # 刻度线
    tick_dir: str = "in"           # 统一方向 in | out | inout（仅供参考，渲染用下面每边方向）
    major_len: float = 3.5
    minor_len: float = 1.6
    tick_width: float = 1.0

    # 显示哪几条边（轴线 / 刻度线 / 刻度数字 分开控制，与 Origin 一致）
    spine_left: bool = True
    spine_right: bool = True
    spine_top: bool = True
    spine_bottom: bool = True
    ticks_left: bool = True
    ticks_right: bool = True
    ticks_top: bool = True
    ticks_bottom: bool = True
    minor_left: bool = True
    minor_right: bool = True
    minor_top: bool = True
    minor_bottom: bool = True
    labels_left: bool = True
    labels_right: bool = False
    labels_top: bool = False
    labels_bottom: bool = True

    # 每边刻度朝向
    dir_left: str = "in"
    dir_right: str = "in"
    dir_top: str = "in"
    dir_bottom: str = "in"

    # 文字
    label_size: float = 11.0
    label_bold: bool = True
    label_pad: float = 2.5         # 刻度数字与轴线的距离
    title_size: float = 12.0
    title_bold: bool = True
    title_pad: float = 5.0         # 轴标题与刻度数字的距离

    # 轴线
    spine_width: float = 1.0
    spine_color: str = TEXT_COLOR

    # 网格
    grid: bool = False
    grid_color: str = "#D9D9D9"
    grid_width: float = 0.6
    grid_style: str = "solid"      # solid | dash | dot


@dataclass
class FigureStyle:
    width_in: float = 4.0
    height_in: float = 3.0
    dpi: int = 600
    bg: str = "#FFFFFF"
    transparent: bool = False
    margin_auto: bool = True
    m_left: float = 44.0
    m_right: float = 15.0
    m_top: float = 11.0
    m_bottom: float = 36.0
    title: str = ""
    title_size: float = 12.0
    title_pad: float = 6.0


@dataclass
class LegendStyle:
    show: bool = True
    loc: str = "upper left"        # Origin: left-top，与参考图一致
    inside: bool = True
    frame: bool = False
    frame_color: str = "#333333"
    frame_width: float = 0.8
    x_offset: float = 6.5          # 相对锚点的内边距 (pt)
    y_offset: float = 7.0
    size: float = 9.0
    bold: bool = True
    line_len: float = 15.0
    handle_pad: float = 5.6
    row_pad: float = 1.0
    ncol: int = 1
    reverse: bool = False
    text_color: str = TEXT_COLOR


@dataclass
class SeriesStyle:
    """单条曲线的属性。"""

    label: str = ""
    color: str = "#56BED7"
    width: float = 1.0
    style: str = "solid"           # solid | dash | dot | dashdot
    alpha: float = 1.0
    visible: bool = True
    smooth: int = 0                # 滑动平均窗口（0 = 不平滑）
    marker: str = ""               # "" | o | s | ^ | d
    marker_size: float = 2.0


@dataclass
class TextStyle:
    family: str = "Arial"
    color: str = TEXT_COLOR
    italic: bool = False


@dataclass
class Style:
    figure: FigureStyle = field(default_factory=FigureStyle)
    xaxis: AxisStyle = field(default_factory=AxisStyle)
    yaxis: AxisStyle = field(default_factory=lambda: AxisStyle(label="Stress (kPa)"))
    legend: LegendStyle = field(default_factory=LegendStyle)
    text: TextStyle = field(default_factory=TextStyle)
    palette: str = "Origin Pastel（参考图）"
    series: dict[str, SeriesStyle] = field(default_factory=dict)
    note: str = ""                 # 图内附加文字（可留空）

    # ------------------------------------------------------------------ #
    # 复制 / 序列化
    # ------------------------------------------------------------------ #
    def clone(self) -> "Style":
        return copy.deepcopy(self)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Style":
        st = cls()
        for name in ("figure", "xaxis", "yaxis", "legend", "text"):
            sub = data.get(name)
            if isinstance(sub, dict):
                obj = getattr(st, name)
                for k, v in sub.items():
                    if hasattr(obj, k):
                        setattr(obj, k, v)
        st.palette = data.get("palette", st.palette)
        st.note = data.get("note", "")
        raw = data.get("series") or {}
        for key, val in raw.items():
            s = SeriesStyle()
            for k, v in val.items():
                if hasattr(s, k):
                    setattr(s, k, v)
            st.series[key] = s
        return st

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, path: str) -> "Style":
        with open(path, "r", encoding="utf-8") as fh:
            return cls.from_dict(json.load(fh))

    # ------------------------------------------------------------------ #
    # 曲线样式维护
    # ------------------------------------------------------------------ #
    def ensure_series(self, keys: list[str], labels: dict[str, str] | None = None) -> None:
        """为新出现的曲线补上默认样式（按配色方案顺序取色）。"""
        from .palettes import colors_for

        labels = labels or {}
        missing = [k for k in keys if k not in self.series]
        if not missing:
            # 已有曲线也同步一次 label（用户手动改过的保留）
            for k in keys:
                if k in self.series and not self.series[k].label:
                    self.series[k].label = labels.get(k, "")
            return
        colors = colors_for(self.palette, len(keys))
        for i, k in enumerate(keys):
            st = self.series.get(k) or SeriesStyle()
            if k in missing:
                st.color = colors[i]
                st.label = labels.get(k, "")
            self.series[k] = st

    def apply_palette(self, name: str, keys: list[str]) -> None:
        from .palettes import colors_for

        self.palette = name
        colors = colors_for(name, max(1, len(keys)))
        for i, k in enumerate(keys):
            if k in self.series:
                self.series[k].color = colors[i % len(colors)]

    def ensure_one(self, key: str, label: str = "") -> SeriesStyle:
        """取单条曲线的样式，缺失时按当前配色新建。"""
        if key not in self.series:
            from .palettes import colors_for

            colors = colors_for(self.palette, max(1, len(self.series) + 1))
            self.series[key] = SeriesStyle(label=label,
                                           color=colors[len(self.series) % len(colors)])
        elif label and not self.series[key].label:
            self.series[key].label = label
        return self.series[key]

    def set_all(self, attr: str, value: Any) -> None:
        for s in self.series.values():
            if hasattr(s, attr):
                setattr(s, attr, value)


# --------------------------------------------------------------------------- #
# 预设
# --------------------------------------------------------------------------- #
def reference_style() -> Style:
    """完全复刻用户提供参考图（Origin 导出）的样式。"""
    st = Style()
    st.figure = FigureStyle(width_in=4.0, height_in=3.0, dpi=600, margin_auto=True)
    st.xaxis = AxisStyle(label="Strain (%)", pad_pct=10.0, major=0.0, minor_sub=5)
    st.yaxis = AxisStyle(label="Stress (kPa)", pad_pct=10.0, major=0.0, minor_sub=5)
    # 上、右两条轴边默认只画轴线，不画刻度线（与用户 Origin 图的常见做法一致）
    st.xaxis.ticks_top = False
    st.yaxis.ticks_right = False
    st.legend = LegendStyle(show=True, loc="upper left", inside=True, frame=False,
                            x_offset=6.5, y_offset=7.0, size=9.0, bold=True, line_len=15.0)
    st.text = TextStyle(family="Arial", color=TEXT_COLOR)
    st.palette = "Origin Pastel（参考图）"
    st.series = {}
    return st


def journal_style() -> Style:
    """更接近常规期刊排版的紧凑样式（字号略小、线更细）。"""
    st = Style()
    st.figure = FigureStyle(width_in=3.5, height_in=2.8, dpi=600, margin_auto=True)
    st.xaxis = AxisStyle(label="Strain (%)", label_size=9.0, title_size=10.0,
                         major_len=3.0, minor_len=1.4, spine_width=0.8, tick_width=0.8)
    st.yaxis = AxisStyle(label="Stress (kPa)", label_size=9.0, title_size=10.0,
                         major_len=3.0, minor_len=1.4, spine_width=0.8, tick_width=0.8)
    st.legend = LegendStyle(size=9.0, line_len=16.0, handle_pad=5.0, row_pad=2.0)
    st.palette = "Nature NPG"
    st.set_all("width", 1.0)
    return st


def minimal_style() -> Style:
    """极简风格：只留左、下轴线，无次刻度。"""
    st = reference_style()
    st.xaxis.ticks_right = False
    st.xaxis.ticks_top = False
    st.yaxis.ticks_right = False
    st.yaxis.ticks_top = False
    st.xaxis.minor_sub = 0
    st.yaxis.minor_sub = 0
    st.xaxis.spine_width = 1.2
    st.yaxis.spine_width = 1.2
    st.legend.frame = False
    st.legend.loc = "upper left"
    return st


PRESETS: dict[str, Any] = {
    "参考图样式（默认）": reference_style,
    "期刊紧凑样式": journal_style,
    "极简样式": minimal_style,
}

CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".strainplot")
