"""科研绘图配色方案
==================

每个配色方案都是一组按顺序取用的颜色。默认方案 ``Origin Pastel`` 取自用户提供的
Origin 参考图（1T.png / 2T.png / 1平行.png）中实测的四条曲线颜色。

为了让相邻曲线一眼可辨，除参考图、单色渐变、灰度三种方案外，其余方案的取色顺序
都在 CIELAB 空间里按「最大化相邻色差」重排过（见 :func:`order_distinct`）；
曲线数超过方案色数时，重复使用的颜色会自动改变明度，避免两条线同色。
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Palette:
    name: str
    colors: tuple[str, ...]
    note: str = ""

    def color(self, i: int) -> str:
        return colors_for(self.name, i + 1)[i]


# --------------------------------------------------------------------------- #
# 颜色工具：sRGB -> CIELAB，色差、明度调整
# --------------------------------------------------------------------------- #
def _parse(hex_color: str) -> tuple[float, float, float]:
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))  # type: ignore[return-value]


def _to_hex(rgb: tuple[float, float, float]) -> str:
    return "#" + "".join(f"{max(0, min(255, round(c * 255))):02X}" for c in rgb)


def _srgb_to_lab(hex_color: str) -> tuple[float, float, float]:
    def lin(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (lin(c) for c in _parse(hex_color))
    x = r * 0.4124564 + g * 0.3575761 + b * 0.1804375
    y = r * 0.2126729 + g * 0.7151522 + b * 0.0721750
    z = r * 0.0193339 + g * 0.1191920 + b * 0.9503041
    xn, yn, zn = 0.95047, 1.0, 1.08883

    def f(t: float) -> float:
        return t ** (1.0 / 3.0) if t > 0.008856 else 7.787 * t + 16.0 / 116.0

    fx, fy, fz = f(x / xn), f(y / yn), f(z / zn)
    return 116.0 * fy - 16.0, 500.0 * (fx - fy), 200.0 * (fy - fz)


def _dist(c1: str, c2: str) -> float:
    a, b = _srgb_to_lab(c1), _srgb_to_lab(c2)
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))


def dedupe(colors: list[str], min_d: float = 11.0) -> list[str]:
    """去掉与已有颜色过于接近（ΔE < min_d）的色，保证每色都能分辨。"""
    out: list[str] = []
    for c in colors:
        if all(_dist(c, o) >= min_d for o in out):
            out.append(c)
    return out or list(colors)


def order_distinct(colors: list[str]) -> list[str]:
    """保持第一个颜色不变，其余按「与已选颜色最小色差最大」的顺序重排。"""
    if len(colors) <= 2:
        return list(colors)
    rest = list(colors[1:])
    out = [colors[0]]
    while rest:
        best_i, best_d = 0, -1.0
        for i, c in enumerate(rest):
            d = min(_dist(c, o) for o in out)
            if d > best_d:
                best_i, best_d = i, d
        out.append(rest.pop(best_i))
    return out


def shade(hex_color: str, factor: float) -> str:
    """factor > 0 向白色混合，< 0 向黑色混合，范围 -1..1。"""
    r, g, b = _parse(hex_color)
    if factor >= 0:
        mix = lambda c: c + (1.0 - c) * factor  # noqa: E731
    else:
        mix = lambda c: c * (1.0 + factor)  # noqa: E731
    return _to_hex((mix(r), mix(g), mix(b)))


# --------------------------------------------------------------------------- #
# 配色方案定义
# --------------------------------------------------------------------------- #
PALETTES: dict[str, Palette] = {}


def _add(name: str, colors: str, note: str = "", order: bool = True) -> None:
    cols = [c.strip() for c in colors.split() if c.strip()]
    if order:
        cols = order_distinct(dedupe(cols))
    PALETTES[name] = Palette(name, tuple(cols), note)


# 参考图实测色（1T.png / 2T.png / 1平行.png）——顺序刻意与参考图一致，不重排
_add(
    "Origin Pastel（参考图）",
    "#56BED7 #0DA58D #465D8E #F3A085 #9B7EBD #D4A24C #6B8E23 #C96A6A",
    "与示例 Origin 图完全一致的柔和粉彩配色",
    order=False,
)
_add(
    "Nature NPG",
    "#E64B35 #4DBBD5 #00A087 #3C5488 #F39B7F #8491B4 #91D1C2 #DC0000 #7E6148 #B09C85",
    "Nature 系列期刊常用配色",
)
_add(
    "Science AAAS",
    "#3B4992 #EE0000 #008B45 #631879 #008280 #BB0021 #5F559B #A20056 #808180 #1B1919",
    "Science 系期刊配色，印刷友好",
)
_add(
    "Cell / JCO",
    "#0073C2 #EFC000 #868686 #CD534C #7AA6DC #003C67 #8F7700 #3B3B3B #A73030 #4A6990",
    "Cell、JCO 常用配色",
)
_add(
    "Lancet",
    "#00468B #ED0000 #42B540 #0099B4 #925E9F #FDAF91 #AD002A #ADB6B6 #1B1919 #6F99AD",
    "The Lancet 常用配色",
)
_add(
    "NEJM",
    "#BC3C29 #0072B5 #E18727 #20854E #7876B1 #6F99AD #FFDC91 #EE4C97 #B5A02A #3C5488",
    "New England J. Med. 常用配色",
)
_add(
    "高区分度（9 色）",
    "#E4002B #0072B2 #009E73 #F2A600 #8E44AD #00BFC4 #D55E00 #C2185B #2B2B2B",
    "相邻曲线色差最大，线条多时首选",
)
_add(
    "Pastel Soft",
    "#8ECFC9 #FFBE7A #FA7F6F #82B0D2 #BEB8DC #E7DAD2 #A1C9F4 #FF9F9B #B2D8B2 #D8C4E6",
    "低饱和柔和粉彩，适合大面积曲线",
)
_add(
    "Morandi",
    "#7E9AA8 #C9A98F #9BAE8C #B98F9C #8E8FA8 #C4B183 #7FA8A0 #A89C8E",
    "莫兰迪灰调，安静高级",
)
_add(
    "Okabe-Ito（色盲友好）",
    "#E69F00 #56B4E9 #009E73 #F0E442 #0072B2 #D55E00 #CC79A7 #000000 #999999 #44AA99",
    "色盲/灰度打印均可区分",
)
_add(
    "Deep Jewel",
    "#1F4E79 #C00000 #2E7D32 #B8860B #4B0082 #006D6F #8B3A3A #4A4A4A",
    "深色调，强视觉冲击",
)
_add(
    "Blue Mono",
    "#C9E4F0 #9CC9E0 #6BA8CE #3F86B5 #22658F #0F4467 #08283D",
    "单色蓝渐层，适合有序变量",
    order=False,
)
_add(
    "Grayscale",
    "#1A1A1A #4D4D4D #737373 #999999 #B3B3B3 #C9C9C9 #E0E0E0",
    "黑白印刷 / 灰度投稿",
    order=False,
)

DEFAULT_PALETTE = "Origin Pastel（参考图）"


def palette_names() -> list[str]:
    return list(PALETTES.keys())


def get_palette(name: str) -> Palette:
    return PALETTES.get(name) or PALETTES[DEFAULT_PALETTE]


def colors_for(name: str, n: int) -> list[str]:
    """取 n 个颜色；超出方案色数时，重复色自动改变明度以免撞色。"""
    pal = get_palette(name)
    cols = list(pal.colors)
    if n <= 0:
        return []
    if n <= len(cols):
        return cols[:n]
    out: list[str] = []
    cycle = 0
    while len(out) < n:
        for c in cols:
            if len(out) >= n:
                break
            if cycle == 0:
                out.append(c)
            else:
                f = 0.18 * (cycle + 1) / 2.0
                out.append(shade(c, f if cycle % 2 else -f))
        cycle += 1
    return out
