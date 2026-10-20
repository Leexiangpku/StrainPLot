"""绘图引擎
===========

不依赖 matplotlib：自己计算版式（单位 pt），把图形拆成基本的绘制指令（线、多边形、
文字），再用两种后端输出：

* **Pillow 光栅后端** —— 几何图形超采样 + LANCZOS 降采样得到平滑抗锯齿曲线，
  文字在最终分辨率上用 TrueType 直接绘制（清晰锐利）。输出 PNG / TIFF / JPG / PDF。
* **SVG 后端** —— 直接输出矢量文件，可用 Illustrator / Inkscape / Origin 继续编辑。

这样既有 Origin 风格的排版精度，也能得到真正的矢量图。
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass
from typing import Iterable, Sequence

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .style import AxisStyle, Style

# --------------------------------------------------------------------------- #
# 字体
# --------------------------------------------------------------------------- #
FONT_DIRS = [
    os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"),
    os.path.expanduser(r"~\AppData\Local\Microsoft\Windows\Fonts"),
]

# family -> (regular, bold, italic, bold_italic)
FONT_FILES: dict[str, tuple[str, str, str, str]] = {
    "Arial": ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"),
    "Arial Narrow": ("arialn.ttf", "arialnbd.ttf", "arialni.ttf", "arialnbi.ttf"),
    "Times New Roman": ("times.ttf", "timesbd.ttf", "timesi.ttf", "timesbi.ttf"),
    "Calibri": ("calibri.ttf", "calibrib.ttf", "calibrii.ttf", "calibriz.ttf"),
    "Cambria": ("cambria.ttc", "cambriab.ttf", "cambriai.ttf", "cambriaz.ttf"),
    "Segoe UI": ("segoeui.ttf", "segoeuib.ttf", "segoeuii.ttf", "segoeuiz.ttf"),
    "Tahoma": ("tahoma.ttf", "tahomabd.ttf", "tahoma.ttf", "tahomabd.ttf"),
    "Verdana": ("verdana.ttf", "verdanab.ttf", "verdanai.ttf", "verdanaz.ttf"),
    "Georgia": ("georgia.ttf", "georgiab.ttf", "georgiai.ttf", "georgiaz.ttf"),
    "Trebuchet MS": ("trebuc.ttf", "trebucbd.ttf", "trebucit.ttf", "trebucbi.ttf"),
    "Franklin Gothic Book": ("framd.ttf", "framd.ttf", "framd.ttf", "framd.ttf"),
    "Consolas": ("consola.ttf", "consolab.ttf", "consolai.ttf", "consolaz.ttf"),
    "Courier New": ("cour.ttf", "courbd.ttf", "couri.ttf", "courbi.ttf"),
    "Palatino Linotype": ("pala.ttf", "palab.ttf", "palai.ttf", "palabi.ttf"),
    "Book Antiqua": ("bkant.ttf", "bkantb.ttf", "bkanti.ttf", "bkantib.ttf"),
    "Century Gothic": ("gothic.ttf", "gothicb.ttf", "gothici.ttf", "gothicbi.ttf"),
    "Microsoft YaHei": ("msyh.ttc", "msyhbd.ttc", "msyh.ttc", "msyhbd.ttc"),
    "SimSun": ("simsun.ttc", "simsun.ttc", "simsun.ttc", "simsun.ttc"),
}

_FONT_CACHE: dict[tuple, ImageFont.FreeTypeFont] = {}
_MISSING_FONTS: set[str] = set()


def font_path(family: str, bold: bool = False, italic: bool = False) -> str | None:
    files = FONT_FILES.get(family)
    if files is None:
        # 允许直接给文件名
        for d in FONT_DIRS:
            p = os.path.join(d, family)
            if os.path.exists(p):
                return p
        return None
    idx = (1 if bold else 0) + (2 if italic else 0)
    order = [idx]
    if idx == 3:
        order += [1, 2]
    elif idx == 2:
        order += [0]
    elif idx == 1:
        order += [0]
    else:
        order += [1]
    for i in order:
        for d in FONT_DIRS:
            p = os.path.join(d, files[i])
            if os.path.exists(p):
                return p
    return None


def get_font(family: str, size_px: float, bold: bool = False, italic: bool = False):
    key = (family, round(size_px, 2), bool(bold), bool(italic))
    f = _FONT_CACHE.get(key)
    if f is not None:
        return f
    px = max(1, int(round(size_px)))
    path = font_path(family, bold, italic)
    try:
        f = ImageFont.truetype(path, px) if path else ImageFont.load_default()
    except Exception:  # noqa: BLE001
        f = ImageFont.load_default()
    _FONT_CACHE[key] = f
    return f


_MEASURE_SCALE = 8.0  # 用于测量文字尺寸的每 pt 像素数
COL_GAP = 12.0        # 图例多列时的列间距（pt）


def text_size_pt(s: str, size_pt: float, bold: bool, italic: bool, family: str) -> tuple[float, float]:
    """返回文字在版面坐标（pt）下的 (宽, 高)。"""
    if not s:
        return 0.0, 0.0
    f = get_font(family, size_pt * _MEASURE_SCALE, bold, italic)
    w = f.getlength(s) / _MEASURE_SCALE
    asc, desc = f.getmetrics()
    return w, (asc + desc) / _MEASURE_SCALE


def text_ascent_pt(size_pt: float, bold: bool, italic: bool, family: str) -> float:
    f = get_font(family, size_pt * _MEASURE_SCALE, bold, italic)
    asc, _desc = f.getmetrics()
    return asc / _MEASURE_SCALE


def available_fonts() -> list[str]:
    out = []
    for fam in FONT_FILES:
        if font_path(fam):
            out.append(fam)
    return out or ["Arial"]


# --------------------------------------------------------------------------- #
# 颜色工具
# --------------------------------------------------------------------------- #
def parse_color(c: str, alpha: float = 1.0) -> tuple[int, int, int, int]:
    c = (c or "#000000").strip()
    if c.startswith("#"):
        h = c[1:]
        if len(h) == 3:
            h = "".join(ch * 2 for ch in h)
        try:
            r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
            return (r, g, b, int(round(255 * max(0.0, min(1.0, alpha)))))
        except ValueError:
            return (0, 0, 0, int(255 * alpha))
    named = {
        "black": (0, 0, 0), "white": (255, 255, 255), "red": (255, 0, 0),
        "blue": (0, 0, 255), "green": (0, 128, 0), "gray": (128, 128, 128),
        "grey": (128, 128, 128), "none": None,
    }
    key = c.lower()
    if key in named and named[key] is not None:
        r, g, b = named[key]
        return (r, g, b, int(255 * alpha))
    return (0, 0, 0, int(255 * alpha))


# --------------------------------------------------------------------------- #
# 绘制指令
# --------------------------------------------------------------------------- #
@dataclass
class Op:
    kind: str
    data: dict


class OpList:
    def __init__(self) -> None:
        self.ops: list[Op] = []

    def line(self, pts, color, width, dash=None, clip=None) -> None:
        self.ops.append(Op("line", dict(pts=pts, color=color, width=width,
                                        dash=dash, clip=clip)))

    def rect(self, box, fill=None, outline=None, width=0.0) -> None:
        self.ops.append(Op("rect", dict(box=box, fill=fill, outline=outline, width=width)))

    def circle(self, x, y, r, fill=None, outline=None, width=0.0) -> None:
        self.ops.append(Op("circle", dict(x=x, y=y, r=r, fill=fill, outline=outline, width=width)))

    def text(self, x, y, s, size, color, bold=True, italic=False, family="Arial",
             halign="center", valign="middle", rotation=0.0) -> None:
        self.ops.append(Op("text", dict(x=x, y=y, s=s, size=size, color=color, bold=bold,
                                        italic=italic, family=family, halign=halign,
                                        valign=valign, rotation=rotation)))


# --------------------------------------------------------------------------- #
# 几何工具
# --------------------------------------------------------------------------- #
def _len_clip(p0, p1, rect):
    """Liang-Barsky 线段裁剪。rect = (x0, y0, x1, y1)。"""
    x0, y0, x1, y1 = rect
    xa, ya = p0
    xb, yb = p1
    dx, dy = xb - xa, yb - ya
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, xa - x0), (dx, x1 - xa), (-dy, ya - y0), (dy, y1 - ya)):
        if p == 0:
            if q < 0:
                return None
        else:
            r = q / p
            if p < 0:
                if r > t1:
                    return None
                t0 = max(t0, r)
            else:
                if r < t0:
                    return None
                t1 = min(t1, r)
    if t0 > t1:
        return None
    return (xa + t0 * dx, ya + t0 * dy), (xa + t1 * dx, ya + t1 * dy)


def clip_polyline(pts: np.ndarray, rect) -> list[list[tuple[float, float]]]:
    """把折线按矩形裁剪成若干段。"""
    out: list[list[tuple[float, float]]] = []
    cur: list[tuple[float, float]] = []
    n = len(pts)
    if n == 0:
        return out
    if n == 1:
        x, y = pts[0]
        if rect[0] <= x <= rect[2] and rect[1] <= y <= rect[3]:
            out.append([(x, y)])
        return out
    for i in range(n - 1):
        seg = _len_clip(tuple(pts[i]), tuple(pts[i + 1]), rect)
        if seg is None:
            if len(cur) > 1:
                out.append(cur)
            cur = []
            continue
        a, b = seg
        if not cur or (cur[-1][0] != a[0] or cur[-1][1] != a[1]):
            if len(cur) > 1:
                out.append(cur)
            cur = [a]
        cur.append(b)
    if len(cur) > 1:
        out.append(cur)
    return out


def dash_polyline(pts: Sequence[tuple[float, float]], pattern: Sequence[float]) -> list[list[tuple[float, float]]]:
    """按虚线样式（pt）把折线切成多段实线段。"""
    if not pattern or len(pts) < 2:
        return [list(pts)]
    out: list[list[tuple[float, float]]] = []
    pat = list(pattern)
    idx, remain = 0, pat[0]
    on = True
    cur = [pts[0]]
    for i in range(len(pts) - 1):
        x0, y0 = pts[i]
        x1, y1 = pts[i + 1]
        seg_len = math.hypot(x1 - x0, y1 - y0)
        if seg_len <= 1e-9:
            continue
        pos = 0.0
        while pos < seg_len - 1e-9:
            step = min(remain, seg_len - pos)
            nx0 = x0 + (x1 - x0) * (pos / seg_len)
            ny0 = y0 + (y1 - y0) * (pos / seg_len)
            pos += step
            nx1 = x0 + (x1 - x0) * (pos / seg_len)
            ny1 = y0 + (y1 - y0) * (pos / seg_len)
            if on:
                cur.append((nx1, ny1))
            else:
                if len(cur) > 1:
                    out.append(cur)
                cur = [(nx1, ny1)]
            remain -= step
            if remain <= 1e-9:
                idx = (idx + 1) % len(pat)
                remain = pat[idx]
                on = not on
    if len(cur) > 1:
        out.append(cur)
    return out


DASH_PATTERNS = {
    "solid": None,
    "dash": (7.0, 3.5),
    "dot": (0.9, 2.6),
    "dashdot": (8.0, 3.0, 1.5, 3.0),
}


def dash_array(style: str, width: float) -> tuple[float, ...] | None:
    pat = DASH_PATTERNS.get(style)
    if not pat:
        return None
    k = max(1.0, width)
    return tuple(v * k for v in pat)


# --------------------------------------------------------------------------- #
# 光栅后端
# --------------------------------------------------------------------------- #
def _draw_text_raster(img: Image.Image, op: dict, scale: float) -> None:
    s = op["s"]
    if not s:
        return
    size_px = op["size"] * scale
    f = get_font(op["family"], size_px, op["bold"], op["italic"])
    color = parse_color(op["color"])
    x = op["x"] * scale
    y = op["y"] * scale
    rot = op.get("rotation", 0.0) or 0.0
    if abs(rot) < 0.01:
        draw = ImageDraw.Draw(img)
        h = {"left": "l", "center": "m", "right": "r"}[op["halign"]]
        v = {"top": "a", "middle": "m", "bottom": "d"}[op["valign"]]
        draw.text((x, y), s, font=f, fill=color, anchor=h + v)
        return
    # 旋转文字：先画到临时图层再旋转
    w = f.getlength(s)
    asc, desc = f.getmetrics()
    pad = int(size_px)
    tmp = Image.new("RGBA", (int(w) + 2 * pad, asc + desc + 2 * pad), (0, 0, 0, 0))
    d2 = ImageDraw.Draw(tmp)
    d2.text((pad, pad + asc), s, font=f, fill=color, anchor="ls")
    tmp = tmp.rotate(rot, expand=True, resample=Image.BICUBIC)
    img.alpha_composite(tmp, (int(x - tmp.width / 2), int(y - tmp.height / 2)))


def to_image(ops: OpList, width_pt: float, height_pt: float, w_px: int, h_px: int,
             bg: str = "#FFFFFF", transparent: bool = False,
             supersample: float = 2.0) -> Image.Image:
    scale = w_px / width_pt
    ss = max(1.0, supersample)
    big_w = max(1, int(round(w_px * ss)))
    big_h = max(1, int(round(h_px * ss)))
    big_scale = big_w / width_pt
    base = Image.new("RGBA", (big_w, big_h), (255, 255, 255, 0) if transparent else parse_color(bg))
    draw = ImageDraw.Draw(base)

    for op in ops.ops:
        k, d = op.kind, op.data
        if k == "line":
            color = parse_color(d["color"])
            wpx = max(1, int(round(d["width"] * big_scale)))
            pts = d["pts"]
            arr = np.asarray(pts, float) * big_scale
            segs = [arr]
            if d.get("clip"):
                cr = d["clip"]
                segs = [np.asarray(s, float) for s in
                        clip_polyline(arr, (cr[0] * big_scale, cr[1] * big_scale,
                                            cr[2] * big_scale, cr[3] * big_scale))]
            for seg in segs:
                if len(seg) < 2:
                    continue
                xy = [tuple(p) for p in seg]
                pat = dash_array(d.get("dash") or "solid", d["width"])
                # dash 模式以 pt 为单位，而这里的坐标已换算成像素，必须同比缩放
                pats = [v * big_scale for v in pat] if pat else None
                for part in (dash_polyline(xy, pats) if pats else [xy]):
                    if len(part) < 2:
                        continue
                    draw.line(part, fill=color, width=wpx, joint="curve")
                    r = wpx / 2.0
                    for p in (part[0], part[-1]):
                        draw.ellipse([p[0] - r, p[1] - r, p[0] + r, p[1] + r], fill=color)
        elif k == "rect":
            x0, y0, x1, y1 = d["box"]
            box = [x0 * big_scale, y0 * big_scale, x1 * big_scale, y1 * big_scale]
            fill = parse_color(d["fill"]) if d.get("fill") else None
            outline = parse_color(d["outline"]) if d.get("outline") else None
            draw.rectangle(box, fill=fill, outline=outline,
                           width=max(1, int(round((d.get("width") or 0) * big_scale))) if outline else 0)
        elif k == "circle":
            r = d["r"] * big_scale
            x, y = d["x"] * big_scale, d["y"] * big_scale
            draw.ellipse([x - r, y - r, x + r, y + r],
                         fill=parse_color(d["fill"]) if d.get("fill") else None,
                         outline=parse_color(d["outline"]) if d.get("outline") else None,
                         width=max(1, int(round((d.get("width") or 0) * big_scale))) if d.get("outline") else 0)
        elif k == "text":
            # 文字延后到最终分辨率绘制，保持锐利
            continue

    if ss > 1.0:
        base = base.resize((w_px, h_px), Image.LANCZOS)
    for op in ops.ops:
        if op.kind == "text":
            _draw_text_raster(base, op.data, scale)
    return base


# --------------------------------------------------------------------------- #
# SVG 后端
# --------------------------------------------------------------------------- #
def to_svg(ops: OpList, width_pt: float, height_pt: float, bg: str = "#FFFFFF",
           transparent: bool = False) -> str:
    def col(c, alpha=1.0):
        r, g, b, a = parse_color(c, alpha)
        return f"#{r:02X}{g:02X}{b:02X}", a / 255.0

    L = [f'<?xml version="1.0" encoding="UTF-8"?>',
         f'<svg xmlns="http://www.w3.org/2000/svg" width="{width_pt:.2f}pt" '
         f'height="{height_pt:.2f}pt" viewBox="0 0 {width_pt:.2f} {height_pt:.2f}">']
    if not transparent:
        c, _ = col(bg)
        L.append(f'<rect x="0" y="0" width="{width_pt:.2f}" height="{height_pt:.2f}" fill="{c}"/>')

    for op in ops.ops:
        k, d = op.kind, op.data
        if k == "line":
            c, a = col(d["color"])
            pts = np.asarray(d["pts"], float)
            segs = [pts]
            if d.get("clip"):
                segs = [np.asarray(s, float) for s in clip_polyline(pts, d["clip"])]
            dash = dash_array(d.get("dash") or "solid", d["width"])
            dash_attr = f' stroke-dasharray="{" ".join(f"{v:.2f}" for v in dash)}"' if dash else ""
            for seg in segs:
                if len(seg) < 2:
                    continue
                path = "M " + " L ".join(f"{x:.3f},{y:.3f}" for x, y in seg)
                L.append(f'<path d="{path}" fill="none" stroke="{c}" stroke-width="{d["width"]:.3f}" '
                         f'stroke-opacity="{a:.3f}" stroke-linecap="round" stroke-linejoin="round"{dash_attr}/>')
        elif k == "rect":
            x0, y0, x1, y1 = d["box"]
            fill = d.get("fill")
            outline = d.get("outline")
            fc, fa = col(fill) if fill else ("none", 1.0)
            L.append(f'<rect x="{x0:.3f}" y="{y0:.3f}" width="{max(0.0, x1 - x0):.3f}" '
                     f'height="{max(0.0, y1 - y0):.3f}" fill="{fc}" fill-opacity="{fa:.3f}" '
                     + (f'stroke="{col(outline)[0]}" stroke-width="{d.get("width") or 0:.3f}"' if outline else "")
                     + "/>")
        elif k == "circle":
            c, a = col(d.get("fill") or d.get("outline") or "#000000")
            L.append(f'<circle cx="{d["x"]:.3f}" cy="{d["y"]:.3f}" r="{d["r"]:.3f}" '
                     f'fill="{c}" fill-opacity="{a:.3f}"'
                     + (f' stroke="{col(d["outline"])[0]}" stroke-width="{d.get("width") or 0:.3f}"' if d.get("outline") else "")
                     + "/>")
        elif k == "text":
            c, a = col(d["color"])
            anchor = {"left": "start", "center": "middle", "right": "end"}[d["halign"]]
            baseline = {"top": "text-before-edge", "middle": "central", "bottom": "text-after-edge"}[d["valign"]]
            style = "italic" if d.get("italic") else "normal"
            weight = "bold" if d.get("bold") else "normal"
            rot = d.get("rotation", 0.0) or 0.0
            tf = f' transform="rotate({-rot:.2f} {d["x"]:.3f} {d["y"]:.3f})"' if abs(rot) > 0.01 else ""
            txt = (d["s"].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
            L.append(f'<text x="{d["x"]:.3f}" y="{d["y"]:.3f}" font-family="{d["family"]}" '
                     f'font-size="{d["size"]:.2f}" font-weight="{weight}" font-style="{style}" '
                     f'fill="{c}" fill-opacity="{a:.3f}" text-anchor="{anchor}" '
                     f'dominant-baseline="{baseline}"{tf}>{txt}</text>')
    L.append("</svg>")
    return "\n".join(L)


# --------------------------------------------------------------------------- #
# 刻度计算
# --------------------------------------------------------------------------- #
NICE_MULT = (1.0, 2.0, 2.5, 5.0, 10.0)


def nice_step(span: float, target: int = 5, lo: float | None = None, hi: float | None = None) -> float:
    """返回"好看"的刻度间隔（1/2/2.5/5 × 10^n）。

    若给出 lo/hi，则按"落在区间内的刻度个数最接近 target"来挑选，
    这样不会出现 0/250/500/750 这类 Origin 不会用的刻度。
    """
    if not np.isfinite(span) or span <= 0:
        return 1.0
    raw = span / max(1, target)
    mag = 10.0 ** math.floor(math.log10(raw))
    best: tuple[float, float] | None = None
    for e in (-1, 0, 1):
        for m in (1.0, 2.0, 2.5, 5.0):
            step = m * mag * (10.0 ** e)
            if lo is not None and hi is not None:
                cnt = len(make_ticks(lo, hi, step))
            else:
                cnt = span / step
            score = abs(cnt - target) + (0.15 if m == 2.5 else 0.0)
            if best is None or score < best[0] - 1e-12:
                best = (score, step)
    return best[1] if best else raw


def make_ticks(vmin: float, vmax: float, step: float) -> np.ndarray:
    if step <= 0 or not np.isfinite(step):
        return np.array([vmin, vmax])
    start = math.ceil(vmin / step - 1e-9) * step
    n = int(math.floor((vmax - start) / step + 1e-9)) + 1
    if n <= 0:
        return np.array([vmin, vmax])
    ticks = start + step * np.arange(n)
    return ticks


def format_number(v: float, step: float, mode: str = "auto") -> str:
    if mode and mode not in ("auto",):
        try:
            return mode % v
        except (TypeError, ValueError):
            pass
    if abs(v) < 1e-12:
        return "0"
    big = max(abs(v), step if step > 0 else 0)
    if big >= 1e5 or (step > 0 and step < 1e-3):
        return f"{v:.3g}"
    if step >= 1:
        dec = 0
    else:
        dec = min(4, int(math.ceil(-math.log10(step) - 1e-9)))
    s = f"{v:.{dec}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


# --------------------------------------------------------------------------- #
# 版式
# --------------------------------------------------------------------------- #
@dataclass
class Rect:
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def w(self) -> float:
        return self.x1 - self.x0

    @property
    def h(self) -> float:
        return self.y1 - self.y0


@dataclass
class AxisRange:
    vmin: float
    vmax: float
    step: float
    ticks: np.ndarray
    minor: np.ndarray
    scale: str


def _finite(v: np.ndarray) -> np.ndarray:
    return v[np.isfinite(v)]


def compute_range(axis: AxisStyle, values: np.ndarray, target_ticks: int = 5) -> AxisRange:
    vals = _finite(np.asarray(values, float))
    scale = axis.scale
    if scale == "log":
        vals = vals[vals > 0]
    if vals.size == 0:
        vals = np.array([0.0, 1.0])
    dmin, dmax = float(vals.min()), float(vals.max())
    if axis.auto_range or not (np.isfinite(axis.vmin) and np.isfinite(axis.vmax)) or axis.vmax <= axis.vmin:
        if scale == "log":
            dmin = max(dmin, 1e-12)
            lo = 10.0 ** math.floor(math.log10(dmin))
            hi = 10.0 ** math.ceil(math.log10(max(dmax, dmin * 10)))
        else:
            span = dmax - dmin
            if span <= 0:
                span = abs(dmax) * 0.2 or 1.0
            pad = span * (axis.pad_pct / 100.0)
            lo, hi = dmin - pad, dmax + pad
    else:
        lo, hi = float(axis.vmin), float(axis.vmax)

    if scale == "log":
        lo, hi = max(lo, 1e-12), max(hi, lo * 10)
        step = 0.0
        decades = math.log10(hi) - math.log10(lo)
        majors = []
        for e in range(int(math.floor(math.log10(lo))), int(math.ceil(math.log10(hi))) + 1):
            for m in (1, 2, 5):
                v = m * 10.0 ** e
                if lo <= v <= hi:
                    majors.append(v)
        ticks = np.array(sorted(majors)) if majors else np.array([lo, hi])
        minor = np.array([])
        return AxisRange(lo, hi, step, ticks, minor, scale)

    span = hi - lo
    step = axis.major if axis.major and axis.major > 0 else nice_step(span, target_ticks, lo, hi)
    ticks = make_ticks(lo, hi, step)
    if ticks.size < 2:
        step = nice_step(span, target_ticks)
        ticks = make_ticks(lo, hi, step)
    if axis.minor_sub and axis.minor_sub > 1:
        sub = step / axis.minor_sub
        minor = make_ticks(lo, hi, sub)
        minor = np.array([v for v in minor if not np.any(np.isclose(v, ticks, rtol=1e-9, atol=step * 1e-6))])
    else:
        minor = np.array([])
    return AxisRange(lo, hi, step, ticks, minor, scale)


# --------------------------------------------------------------------------- #
# 主绘图函数
# --------------------------------------------------------------------------- #
@dataclass
class PlotSeries:
    label: str
    color: str
    width: float
    style: str
    alpha: float
    x: np.ndarray
    y: np.ndarray
    marker: str = ""
    marker_size: float = 2.0


def smooth_xy(x: np.ndarray, y: np.ndarray, window: int) -> tuple[np.ndarray, np.ndarray]:
    if not window or window < 2 or y.size < 3:
        return x, y
    w = int(window)
    if w % 2 == 0:
        w += 1
    w = min(w, y.size if y.size % 2 == 1 else y.size - 1)
    if w < 3:
        return x, y
    kernel = np.ones(w) / w
    pad = w // 2
    yy = np.pad(y, pad, mode="edge")
    ys = np.convolve(yy, kernel, mode="valid")
    return x, ys


class Figure:
    """一次绘图任务的完整描述。"""

    def __init__(self, style: Style, series: Sequence[PlotSeries], title: str = ""):
        self.style = style
        self.series = [s for s in series if s.x.size >= 1]
        self.title = title or style.figure.title

    # ------------------------------------------------------------------ #
    def _layout(self) -> tuple[Rect, float, float]:
        st = self.style
        fs = st.figure
        W, H = fs.width_in * 72.0, fs.height_in * 72.0
        fam = st.text.family

        xr = compute_range(st.xaxis, np.concatenate([s.x for s in self.series]) if self.series else np.array([0.0, 1.0]))
        yr = compute_range(st.yaxis, np.concatenate([s.y for s in self.series]) if self.series else np.array([0.0, 1.0]))
        self.xrange, self.yrange = xr, yr

        xlabels = [format_number(v, xr.step, st.xaxis.num_fmt) for v in xr.ticks]
        ylabels = [format_number(v, yr.step, st.yaxis.num_fmt) for v in yr.ticks]
        xlab_w = max([text_size_pt(s, st.xaxis.label_size, st.xaxis.label_bold, st.text.italic, fam)[0] for s in xlabels] or [0])
        xlab_h = text_size_pt("0", st.xaxis.label_size, st.xaxis.label_bold, st.text.italic, fam)[1]
        ylab_w = max([text_size_pt(s, st.yaxis.label_size, st.yaxis.label_bold, st.text.italic, fam)[0] for s in ylabels] or [0])

        def out_len(direction: str, length: float) -> float:
            return length if direction in ("out", "inout") else 0.0

        x_out_b = out_len(st.xaxis.dir_bottom, st.xaxis.major_len) if st.xaxis.ticks_bottom else 0.0
        x_out_t = out_len(st.xaxis.dir_top, st.xaxis.major_len) if st.xaxis.ticks_top else 0.0
        y_out_l = out_len(st.yaxis.dir_left, st.yaxis.major_len) if st.yaxis.ticks_left else 0.0
        y_out_r = out_len(st.yaxis.dir_right, st.yaxis.major_len) if st.yaxis.ticks_right else 0.0
        x_out, y_out = max(x_out_b, x_out_t), max(y_out_l, y_out_r)

        left = 0.0
        if st.yaxis.labels_left:
            left += ylab_w + y_out_l + st.yaxis.label_pad
        if st.yaxis.label:
            left += text_size_pt("0", st.yaxis.title_size, st.yaxis.title_bold, st.text.italic, fam)[1] + st.yaxis.title_pad
        bottom = 0.0
        if st.xaxis.labels_bottom:
            bottom += xlab_h + x_out_b + st.xaxis.label_pad
        if st.xaxis.label:
            bottom += text_size_pt("0", st.xaxis.title_size, st.xaxis.title_bold, st.text.italic, fam)[1] + st.xaxis.title_pad

        right = max(6.0, 0.052 * W)
        if st.yaxis.labels_right:
            right += ylab_w + y_out_r + st.yaxis.label_pad
        top = max(6.0, 0.049 * H)
        if st.xaxis.labels_top:
            top += xlab_h + x_out_t + st.xaxis.label_pad
        if self.title:
            top += text_size_pt("0", st.figure.title_size, True, st.text.italic, fam)[1] + st.figure.title_pad

        if not fs.margin_auto:
            left, right = fs.m_left, fs.m_right
            top, bottom = fs.m_top, fs.m_bottom

        rect = Rect(left, top, W - right, H - bottom)
        if rect.w < 20 or rect.h < 20:  # 防止极端参数
            rect = Rect(10, 10, W - 10, H - 10)
        # 版式测量结果（供 build 中放置轴标题使用）
        self._y_lab_w = ylab_w if st.yaxis.labels_left else 0.0
        self._x_lab_h = xlab_h if st.xaxis.labels_bottom else 0.0
        self._y_out = y_out
        self._x_out = x_out
        return rect, W, H

    # ------------------------------------------------------------------ #
    def build(self) -> tuple[OpList, float, float]:
        st = self.style
        fam = st.text.family
        tcol = st.text.color
        italic = st.text.italic
        ax, W, H = self._layout()
        xr, yr = self.xrange, self.yrange
        ops = OpList()

        def tx(v):
            if xr.scale == "log":
                a, b = math.log10(xr.vmin), math.log10(xr.vmax)
                return ax.x0 + (math.log10(max(v, 1e-300)) - a) / (b - a) * ax.w
            return ax.x0 + (v - xr.vmin) / (xr.vmax - xr.vmin) * ax.w

        def ty(v):
            if yr.scale == "log":
                a, b = math.log10(yr.vmin), math.log10(yr.vmax)
                return ax.y1 - (math.log10(max(v, 1e-300)) - a) / (b - a) * ax.h
            return ax.y1 - (v - yr.vmin) / (yr.vmax - yr.vmin) * ax.h

        # ---------- 网格 ----------
        for axis, rng, is_x in ((st.xaxis, xr, True), (st.yaxis, yr, False)):
            if not axis.grid:
                continue
            for v in rng.ticks:
                if is_x:
                    ops.line([(tx(v), ax.y0), (tx(v), ax.y1)], axis.grid_color, axis.grid_width,
                             dash=axis.grid_style, clip=(ax.x0, ax.y0, ax.x1, ax.y1))
                else:
                    ops.line([(ax.x0, ty(v)), (ax.x1, ty(v))], axis.grid_color, axis.grid_width,
                             dash=axis.grid_style, clip=(ax.x0, ax.y0, ax.x1, ax.y1))

        # ---------- 曲线 ----------
        for s in self.series:
            x, y = s.x, s.y
            if x.size < 1:
                continue
            if s.marker:
                for xi, yi in zip(x, y):
                    if xi is None or not np.isfinite(xi) or not np.isfinite(yi):
                        continue
                    px, py = tx(float(xi)), ty(float(yi))
                    if ax.x0 <= px <= ax.x1 and ax.y0 <= py <= ax.y1:
                        ops.circle(px, py, s.marker_size / 2.0, fill=None, outline=s.color,
                                   width=max(0.6, s.width * 0.6))
            if x.size < 2:
                continue
            pts = np.column_stack([np.array([tx(float(v)) for v in x]),
                                   np.array([ty(float(v)) for v in y])])
            ops.line(pts, s.color, s.width, dash=s.style, clip=(ax.x0, ax.y0, ax.x1, ax.y1))

        # ---------- 坐标轴与刻度 ----------
        for axis, rng, is_x in ((st.xaxis, xr, True), (st.yaxis, yr, False)):
            spine_c = axis.spine_color or tcol
            sw = axis.spine_width
            if is_x:
                if axis.spine_bottom and sw > 0:
                    ops.line([(ax.x0, ax.y1), (ax.x1, ax.y1)], spine_c, sw)
                if axis.spine_top and sw > 0:
                    ops.line([(ax.x0, ax.y0), (ax.x1, ax.y0)], spine_c, sw)
            else:
                if axis.spine_left and sw > 0:
                    ops.line([(ax.x0, ax.y0), (ax.x0, ax.y1)], spine_c, sw)
                if axis.spine_right and sw > 0:
                    ops.line([(ax.x1, ax.y0), (ax.x1, ax.y1)], spine_c, sw)

            def tick_extent(length: float, direction: str) -> tuple[float, float]:
                if direction == "in":
                    return 0.0, length
                if direction == "out":
                    return -length, 0.0
                if direction == "inout":
                    return -length / 2.0, length / 2.0
                return 0.0, 0.0

            d_bot, d_top = axis.dir_bottom, axis.dir_top
            d_left, d_right = axis.dir_left, axis.dir_right
            for vals, length, is_minor in ((rng.minor, axis.minor_len, True), (rng.ticks, axis.major_len, False)):
                if vals.size == 0 or length <= 0:
                    continue
                for v in vals:
                    if is_x:
                        px = tx(v)
                        if px < ax.x0 - 0.5 or px > ax.x1 + 0.5:
                            continue
                        if axis.ticks_bottom and (not is_minor or axis.minor_bottom):
                            a_off, b_off = tick_extent(length, d_bot)
                            # y 轴向下为正：in = 向上（朝框内），out = 向下（朝框外）
                            ops.line([(px, ax.y1 - a_off), (px, ax.y1 - b_off)], spine_c, axis.tick_width)
                        if axis.ticks_top and (not is_minor or axis.minor_top):
                            a_off, b_off = tick_extent(length, d_top)
                            ops.line([(px, ax.y0 + a_off), (px, ax.y0 + b_off)], spine_c, axis.tick_width)
                    else:
                        py = ty(v)
                        if py < ax.y0 - 0.5 or py > ax.y1 + 0.5:
                            continue
                        if axis.ticks_left and (not is_minor or axis.minor_left):
                            a_off, b_off = tick_extent(length, d_left)
                            ops.line([(ax.x0 + a_off, py), (ax.x0 + b_off, py)], spine_c, axis.tick_width)
                        if axis.ticks_right and (not is_minor or axis.minor_right):
                            a_off, b_off = tick_extent(length, d_right)
                            ops.line([(ax.x1 - b_off, py), (ax.x1 - a_off, py)], spine_c, axis.tick_width)

            # 刻度数字
            lab_size, lab_bold = axis.label_size, axis.label_bold
            pad_b = axis.label_pad + (axis.major_len if axis.dir_bottom in ("out", "inout") else 0.0)
            pad_t = axis.label_pad + (axis.major_len if axis.dir_top in ("out", "inout") else 0.0)
            pad_l = axis.label_pad + (axis.major_len if axis.dir_left in ("out", "inout") else 0.0)
            pad_r = axis.label_pad + (axis.major_len if axis.dir_right in ("out", "inout") else 0.0)
            if is_x:
                for v in rng.ticks:
                    px = tx(v)
                    if px < ax.x0 - 0.5 or px > ax.x1 + 0.5:
                        continue
                    s = format_number(v, rng.step, axis.num_fmt)
                    if axis.labels_bottom:
                        ops.text(px, ax.y1 + pad_b, s, lab_size, tcol, lab_bold, italic, fam,
                                 halign="center", valign="top")
                    if axis.labels_top:
                        ops.text(px, ax.y0 - pad_t, s, lab_size, tcol, lab_bold, italic, fam,
                                 halign="center", valign="bottom")
            else:
                for v in rng.ticks:
                    py = ty(v)
                    if py < ax.y0 - 0.5 or py > ax.y1 + 0.5:
                        continue
                    s = format_number(v, rng.step, axis.num_fmt)
                    if axis.labels_left:
                        ops.text(ax.x0 - pad_l, py, s, lab_size, tcol, lab_bold, italic, fam,
                                 halign="right", valign="middle")
                    if axis.labels_right:
                        ops.text(ax.x1 + pad_r, py, s, lab_size, tcol, lab_bold, italic, fam,
                                 halign="left", valign="middle")

            # 轴标题
            if not axis.label:
                continue
            if is_x:
                lh = self._x_lab_h
                y = ax.y1 + (lh + pad_b if axis.labels_bottom else 0.0) + axis.title_pad
                ops.text((ax.x0 + ax.x1) / 2.0, y, axis.label, axis.title_size, tcol,
                         axis.title_bold, italic, fam, halign="center", valign="top")
            else:
                lw = self._y_lab_w
                lpad = pad_l if axis.labels_left else 0.0
                th = text_size_pt("0", axis.title_size, axis.title_bold, italic, fam)[1]
                x = ax.x0 - lw - lpad - axis.title_pad - th / 2.0
                ops.text(x, (ax.y0 + ax.y1) / 2.0, axis.label, axis.title_size, tcol,
                         axis.title_bold, italic, fam, halign="center", valign="middle", rotation=90.0)

        # ---------- 图例 ----------
        if st.legend.show and self.series:
            self._legend(ops, ax, fam, tcol, italic)

        # ---------- 图标题 ----------
        if self.title:
            ops.text((ax.x0 + ax.x1) / 2.0, st.figure.title_pad * 0.5 + 2.0, self.title,
                     st.figure.title_size, tcol, True, italic, fam,
                     halign="center", valign="top")
        # ---------- 注释 ----------
        if st.note:
            ops.text(ax.x1 - 4.0, ax.y0 + 4.0, st.note, st.legend.size, tcol,
                     st.legend.bold, italic, fam, halign="right", valign="top")
        return ops, W, H

    # ------------------------------------------------------------------ #
    def _legend(self, ops: OpList, ax: Rect, fam: str, tcol: str, italic: bool) -> None:
        lg = self.style.legend
        items = [s for s in self.series]
        if lg.reverse:
            items = list(reversed(items))
        if not items:
            return
        size = lg.size
        row_h = max(text_size_pt("Ag", size, lg.bold, italic, fam)[1], size * 1.15)
        row_gap = lg.row_pad * 0.5
        widths = []
        for s in items:
            w = text_size_pt(s.label, size, lg.bold, italic, fam)[0]
            widths.append(lg.line_len + lg.handle_pad + w * 1.04 + 1.0)
        ncol = max(1, min(lg.ncol, len(items)))
        # 条目过多时自动加列，避免图例溢出坐标框
        if lg.inside:
            avail_h = max(row_h, (ax.y1 - ax.y0) - 2 * lg.y_offset)
        else:
            avail_h = max(row_h, self.style.figure.height_in * 72.0 - lg.y_offset)
        max_rows = max(1, int((avail_h + row_gap) // (row_h + row_gap)))
        while ncol < len(items) and int(math.ceil(len(items) / ncol)) > max_rows:
            ncol += 1
        nrow = int(math.ceil(len(items) / ncol))
        col_w = []
        for c in range(ncol):
            col_items = widths[c * nrow:(c + 1) * nrow]
            col_w.append(max(col_items) if col_items else 0.0)
        total_w = sum(col_w) + (ncol - 1) * COL_GAP
        total_h = nrow * row_h + (nrow - 1) * row_gap

        pad = 4.0
        if lg.inside:
            bx0 = ax.x0 + lg.x_offset
            by0 = ax.y0 + lg.y_offset
            loc = lg.loc
            if loc.startswith("lower"):
                by0 = ax.y1 - lg.y_offset - total_h
            elif loc.startswith("center") or loc.startswith("mid"):
                by0 = (ax.y0 + ax.y1) / 2.0 - total_h / 2.0
            if loc.endswith("right"):
                bx0 = ax.x1 - lg.x_offset - total_w
            elif loc.endswith("center"):
                bx0 = (ax.x0 + ax.x1) / 2.0 - total_w / 2.0
            bx1, by1 = bx0 + total_w, by0 + total_h
            if bx1 > ax.x1 - 1.0:
                bx0 = max(ax.x0 + 1.0, ax.x1 - total_w - 1.0)
                bx1 = bx0 + total_w
            if by1 > ax.y1 - 1.0:
                by0 = max(ax.y0 + 1.0, ax.y1 - total_h - 1.0)
                by1 = by0 + total_h
        else:
            bx0 = lg.x_offset
            by0 = lg.y_offset
            bx1, by1 = bx0 + total_w, by0 + total_h

        if lg.frame:
            ops.rect((bx0 - pad, by0 - pad, bx1 + pad, by1 + pad), fill="#FFFFFF",
                     outline=lg.frame_color, width=lg.frame_width)

        for i, s in enumerate(items):
            c = i // nrow
            r = i % nrow
            x = bx0 + sum(col_w[:c]) + c * COL_GAP
            y = by0 + r * (row_h + row_gap) + row_h / 2.0
            x2 = x + lg.line_len
            ops.line([(x, y), (x2, y)], s.color, s.width, dash=s.style)
            if s.marker:
                ops.circle((x + x2) / 2.0, y, s.marker_size / 2.0, fill=None,
                           outline=s.color, width=max(0.6, s.width * 0.6))
            ops.text(x2 + lg.handle_pad, y, s.label, size, lg.text_color or tcol,
                     lg.bold, italic, fam, halign="left", valign="middle")


# --------------------------------------------------------------------------- #
# 输出
# --------------------------------------------------------------------------- #
def render_image(fig: Figure, dpi: float | None = None, width_px: int | None = None,
                 max_pixels: float = 6.0e7) -> Image.Image:
    st = fig.style
    ops, W, H = fig.build()
    if width_px:
        scale = width_px / W
    else:
        scale = (dpi or st.figure.dpi) / 72.0
    w_px = max(1, int(round(W * scale)))
    h_px = max(1, int(round(H * scale)))
    ss = 2.0 if (w_px * h_px) < 1.2e7 else 1.5
    while w_px * h_px * ss * ss > max_pixels and ss > 1.0:
        ss -= 0.25
    return to_image(ops, W, H, w_px, h_px, st.figure.bg, st.figure.transparent, ss)


def save_png(fig: Figure, path: str, dpi: float | None = None) -> str:
    img = render_image(fig, dpi=dpi)
    if img.mode == "RGBA" and not fig.style.figure.transparent:
        img = img.convert("RGB")
    img.save(path, dpi=(dpi or fig.style.figure.dpi, dpi or fig.style.figure.dpi))
    return path


def save_tiff(fig: Figure, path: str, dpi: float | None = None) -> str:
    img = render_image(fig, dpi=dpi)
    if img.mode == "RGBA":
        img = img.convert("RGB")
    d = int(dpi or fig.style.figure.dpi)
    img.save(path, compression="tiff_lzw", dpi=(d, d))
    return path


def save_svg(fig: Figure, path: str) -> str:
    ops, W, H = fig.build()
    svg = to_svg(ops, W, H, fig.style.figure.bg, fig.style.figure.transparent)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(svg)
    return path


def save_pdf(fig: Figure, path: str, dpi: float | None = None) -> str:
    """输出 PDF（位图嵌入，600 dpi 足够投稿使用）。"""
    img = render_image(fig, dpi=dpi)
    if img.mode == "RGBA":
        img = img.convert("RGB")
    d = dpi or fig.style.figure.dpi
    img.save(path, "PDF", resolution=float(d))
    return path


def save_figure(fig: Figure, path: str, dpi: float | None = None) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".svg":
        return save_svg(fig, path)
    if ext in (".tif", ".tiff"):
        return save_tiff(fig, path, dpi)
    if ext == ".pdf":
        return save_pdf(fig, path, dpi)
    if ext in (".jpg", ".jpeg"):
        img = render_image(fig, dpi=dpi).convert("RGB")
        d = int(dpi or fig.style.figure.dpi)
        img.save(path, quality=95, dpi=(d, d))
        return path
    return save_png(fig, path, dpi)
