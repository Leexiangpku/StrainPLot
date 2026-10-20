"""StrainPlot —— 一键数据绘图（X–Y 通用）工具。

v2 起不再把"应变–应力"写死：``variables`` 里定义了可绘制的物理量与常见组合，
``dataio`` 两段式读表（scan_tables → build_series），界面里换 X/Y 不用重新读文件。
"""
from . import presets, variables
from .dataio import (Column, ScanResult, Series, Table, XYMap, build_series, scan_folder,
                     scan_tables)
from .render import Figure, PlotSeries, render_image, save_figure
from .style import SeriesStyle, Style, reference_style

__version__ = "2.0.0"
__all__ = [
    "Series", "ScanResult", "Table", "Column", "XYMap", "scan_folder", "scan_tables",
    "build_series", "variables", "presets", "Style", "SeriesStyle", "reference_style",
    "Figure", "PlotSeries", "render_image", "save_figure", "__version__",
]
