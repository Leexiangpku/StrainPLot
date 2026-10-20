"""数据读取模块
=================

v2 起采用"两段式"读取：

1. :func:`scan_tables` 把每个文件解析成 :class:`Table`（保留**所有**数值列，并猜测每列的量类型），
   结果缓存在内存里 —— 换 X/Y 变量时不需要重新读文件，立即出图；
2. :func:`build_series` 按当前的 X/Y 映射（:class:`XYMap`）从表里挑列，生成 :class:`Series`。

支持的数据源
------------
* ``.csv`` / ``.txt`` / ``.dat`` / ``.tsv``：逗号 / 制表符 / 分号 / 竖线分隔的文本表格，
  自动识别 UTF-8、UTF-8-BOM、UTF-16、GBK。适用于 Instron Bluehill 的
  ``*_RawData\\Specimen_RawData_*.csv``、TA / Mettler 的导出文本等。
* ``.xlsx`` / ``.xlsm``：Excel 表格，兼容"表头行 + 单位行 + 样品名行"这种多行表头，
  以及"多块 Stress/Strain 并排"的排版（每块单独出一条曲线）。

列匹配
------
不再写死 strain / stress：所有列交给 :mod:`strainplot.variables` 按别名 + 单位猜类型，
再由用户在界面里选"组合预设"或"自定义两列"。
"""
from __future__ import annotations

import csv
import io
import os
import re
from dataclasses import dataclass, field
from typing import Iterable, Sequence

import numpy as np

from . import variables as V

TEXT_EXT = {".csv", ".txt", ".dat", ".tsv"}
EXCEL_EXT = {".xlsx", ".xlsm"}
SKIP_DIR_HINTS = ("__macosx",)

# 文件名里带这些词的通常是手工复制出来的副本，会重复计数（"Specimen_RawData_5 - 副本.csv"）
COPY_HINTS = ("副本", "copy", "backup", "备份", "- 副")

# 只认这些"纯单位"字符串，避免把 `(%)`、`(kPa)`、`\` 当成列名显示在界面上
_UNIT_WORDS = {
    "%", "‰", "s", "ms", "min", "h", "hour", "mm", "cm", "m", "nm", "um", "μm", "°c", "c", "k",
    "n", "kn", "g", "mg", "kg", "ml", "l", "μl", "ul", "v", "mv", "kv", "ma", "a", "ω", "ohm",
    "hz", "khz", "mhz", "ppm", "kpa", "mpa", "gpa", "pa", "bar", "psi", "mol/l", "mmol/l",
    "wt%", "vol%", "a.u.", "au", "deg", "°", "1/s", "rad/s", "ph", "-", "\\", "kpa/s", "mm/min",
    "mm/s", "n/m", "mj/m3", "mj/m³", "j/g", "w/g", "eu", "counts", "cps",
}


def _looks_like_unit(text: str) -> bool:
    """这一格更像单位而不是列名（`(%)`、`kPa`、`\\` 之类）。"""
    s = (text or "").strip()
    if not s:
        return True
    core = s.strip("()[] ").strip().lower()
    return core in _UNIT_WORDS
_UNIT_RE = re.compile(r"^\(?\s*[%a-zA-Zμµ°²³⁻¹/·\.\d]+\s*\)?$")


# --------------------------------------------------------------------------- #
# 数据结构
# --------------------------------------------------------------------------- #
@dataclass
class Column:
    """表里的一列。"""

    index: int
    header: str                     # 原始表头文字
    unit: str = ""
    kind: str = "plain"             # variables.Kind.id
    score: int = 0
    sample: str = ""                # 多块 Excel 里这一列所属样品名

    @property
    def display(self) -> str:
        u = f" ({self.unit})" if self.unit else ""
        return f"{self.header or f'列{self.index + 1}'}{u}"

    @property
    def key(self) -> str:
        """跨文件稳定的列标识：表头 + 序号。"""
        return f"{self.header}#{self.index}"


@dataclass
class Table:
    """一个文件（或 Excel 的一个 sheet）解析出的原始表。"""

    key: str
    source: str                     # 文件路径
    group: str
    label: str
    kind: str = "csv"               # csv / xlsx
    sheet: str = ""
    columns: list[Column] = field(default_factory=list)
    data: dict[int, np.ndarray] = field(default_factory=dict)

    @property
    def ncol(self) -> int:
        return len(self.columns)

    def column(self, index: int) -> Column | None:
        for c in self.columns:
            if c.index == index:
                return c
        return None

    def kind_columns(self, kind_id: str) -> list[Column]:
        return [c for c in self.columns if c.kind == kind_id]

    def numeric_columns(self) -> list[Column]:
        return [c for c in self.columns if c.index in self.data]


@dataclass
class Series:
    """一条可绘制的曲线（某一对列的 X / Y）。"""

    key: str
    label: str
    group: str
    source: str
    x: np.ndarray
    y: np.ndarray
    x_unit: str = ""
    y_unit: str = ""
    kind: str = "csv"
    selected: bool = True
    x_header: str = ""
    y_header: str = ""

    # ---- 派生量 -----------------------------------------------------------
    @property
    def n(self) -> int:
        return int(self.x.size)

    @property
    def x_max(self) -> float:
        return float(np.nanmax(self.x)) if self.n else 0.0

    @property
    def y_max(self) -> float:
        return float(np.nanmax(self.y)) if self.n else 0.0

    def summary(self) -> str:
        if not self.n:
            return "空"
        return (f"n={self.n}  x={self.x_max:g}{self.x_unit}  "
                f"y={self.y_max:g}{self.y_unit}")


@dataclass
class XYMap:
    """当前"画哪两列"的设定。"""

    x_kind: str = "strain"
    y_kind: str = "stress"
    x_col: str = ""                 # 自定义模式：列 key（空 = 按类型自动找）
    y_col: str = ""
    x_label: str = ""               # 空 = 用 variables.axis_label 自动生成
    y_label: str = ""
    x_unit: str | None = None       # None = 用量类型的默认单位
    y_unit: str | None = None

    def copy(self) -> "XYMap":
        return XYMap(**self.__dict__)

    def swapped(self) -> "XYMap":
        """反转 X / Y：量类型、自定义列、标题、单位一起换。"""
        m = self.copy()
        m.x_kind, m.y_kind = self.y_kind, self.x_kind
        m.x_col, m.y_col = self.y_col, self.x_col
        m.x_label, m.y_label = self.y_label, self.x_label
        m.x_unit, m.y_unit = self.y_unit, self.x_unit
        return m

    def x_axis_label(self, unit: str = "") -> str:
        if self.x_label:
            return self.x_label
        return V.axis_label(self.x_kind, self.x_unit, self.x_col.split("#")[0])

    def y_axis_label(self, unit: str = "") -> str:
        if self.y_label:
            return self.y_label
        return V.axis_label(self.y_kind, self.y_unit, self.y_col.split("#")[0])


@dataclass
class ScanResult:
    series: list[Series] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    tables: list = field(default_factory=list)
    xmap: XYMap | None = None

    def add_warning(self, msg: str) -> None:
        if msg not in self.warnings:
            self.warnings.append(msg)


# --------------------------------------------------------------------------- #
# 基础工具
# --------------------------------------------------------------------------- #
def decode_bytes(raw: bytes) -> str:
    """尽量无损地把表格文件解码成字符串。"""
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        try:
            return raw.decode("utf-16")
        except UnicodeDecodeError:
            pass
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig", errors="replace")
    for enc in ("utf-8", "gb18030", "big5", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def to_float(cell) -> float | None:
    """把任意单元格内容解析成 float，失败返回 None。"""
    if cell is None:
        return None
    if isinstance(cell, (int, float)) and not isinstance(cell, bool):
        v = float(cell)
        return v if np.isfinite(v) else None
    s = str(cell).strip().strip('"').strip("'").replace("\u2212", "-").replace("−", "-")
    if not s:
        return None
    s = s.replace(" ", "")
    try:
        v = float(s)
    except ValueError:
        if re.fullmatch(r"-?\d{1,3}(,\d{3})+(\.\d+)?", s):
            try:
                v = float(s.replace(",", ""))
            except ValueError:
                return None
        elif re.fullmatch(r"-?\d+,\d+", s):
            try:
                v = float(s.replace(",", "."))
            except ValueError:
                return None
        else:
            return None
    return v if np.isfinite(v) else None


def _clean_unit(text) -> str:
    s = str(text or "").strip().strip('"')
    return s.strip("()（）").strip()


def _guess_unit(unit_cell, fallback: str = "") -> str:
    u = _clean_unit(unit_cell)
    if u and len(u) <= 12 and not re.search(r"[0-9]{4}", u):
        return u
    # 表头里常写成 "Stress (kPa)"
    m = re.search(r"[（(]\s*([^()（）]{1,12})\s*[)）]\s*$", str(unit_cell or ""))
    if m:
        return m.group(1).strip()
    return fallback


def _split_header_unit(header: str) -> tuple[str, str]:
    """``拉伸应力 (kPa)`` → ``("拉伸应力", "kPa")``。"""
    m = re.search(r"[（(]\s*([^()（）]{1,12})\s*[)）]\s*$", header or "")
    if m and not re.search(r"\d", m.group(1)):
        return (header[: m.start()].strip(), m.group(1).strip())
    return (header or "").strip(), ""


def _clean_label(stem: str) -> str:
    s = stem.strip()
    low = s.lower()
    for suffix in (".is_tens_rawdata", ".is_comp_rawdata", "_rawdata", ".is_tens", ".is_comp",
                   ".id_tens", ".is_flex", "_results"):
        while low.endswith(suffix):
            s = s[: -len(suffix)]
            low = s.lower()
    s = re.sub(r"(?i)^specimen[_\-\s]?rawdata[_\-\s]?", "", s)
    s = s.replace("  ", " ").strip(" -")
    return s or stem


def _natural_key(s: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


# --------------------------------------------------------------------------- #
# 表头识别
# --------------------------------------------------------------------------- #
def _row_kind_hits(row: Sequence) -> int:
    """这一行里有多少个单元格能识别成已知物理量。"""
    hits = 0
    for cell in row:
        if cell is None:
            continue
        text = str(cell).strip()
        if not text or to_float(text) is not None:
            continue
        kid, score = V.identify(text)
        if kid != "plain" and score >= 40:
            hits += 1
    return hits


def _is_numeric_row(row: Sequence) -> bool:
    vals = [c for c in row if str(c).strip()]
    if not vals:
        return False
    nums = sum(1 for c in vals if to_float(c) is not None)
    return nums >= max(1, int(len(vals) * 0.6))


def _find_header(rows: Sequence[Sequence], max_scan: int = 25) -> int:
    """找表头行：优先"最多列能被识别成物理量"的那行。"""
    best_idx, best_hits = -1, 0
    for i, row in enumerate(rows[:max_scan]):
        if _is_numeric_row(row):
            continue
        hits = _row_kind_hits(row)
        if hits > best_hits:
            best_idx, best_hits = i, hits
    if best_hits >= 2:
        return best_idx
    # 退路：第一行"文本居多、且下一行是数字"的行
    for i, row in enumerate(rows[:max_scan]):
        texts = [str(c).strip() for c in row]
        if not any(texts):
            continue
        if _is_numeric_row(row):
            continue
        if i + 1 < len(rows) and _is_numeric_row(rows[i + 1]):
            return i
    return -1


def _make_columns(header_row: Sequence, unit_row: Sequence | None,
                  sample_row: Sequence | None) -> list[Column]:
    cols: list[Column] = []
    width = max(len(header_row), len(unit_row or ()), len(sample_row or ()))
    for i in range(width):
        raw = str(header_row[i]).strip() if i < len(header_row) and header_row[i] is not None else ""
        if not raw:
            continue
        name, unit = _split_header_unit(raw)
        if unit_row is not None and i < len(unit_row):
            u2 = _guess_unit(unit_row[i])
            if u2:
                unit = u2
        sample = ""
        if sample_row is not None and i < len(sample_row):
            sample = str(sample_row[i] or "").strip()
        kid, score = V.identify(name, unit)
        cols.append(Column(index=i, header=name or raw, unit=unit, kind=kid,
                           score=score, sample=sample))
    return cols


def _extract_data(rows: Sequence[Sequence], start: int, cols: list[Column]) -> dict[int, np.ndarray]:
    """把每列的数值抽成数组（各列独立，跳过空值）。"""
    out: dict[int, list[float]] = {c.index: [] for c in cols}
    for row in rows[start:]:
        if not row:
            continue
        for c in cols:
            if c.index < len(row):
                v = to_float(row[c.index])
                if v is not None:
                    out[c.index].append(v)
    result: dict[int, np.ndarray] = {}
    for idx, vals in out.items():
        if len(vals) >= 2:
            result[idx] = np.asarray(vals, float)
    return result


# --------------------------------------------------------------------------- #
# 文本表格（CSV / TXT）
# --------------------------------------------------------------------------- #
def _split_lines(text: str) -> list[list[str]]:
    sample = text[:8000]
    delim, best = ",", -1
    for cand in (",", "\t", ";", "|"):
        cnt = sample.count(cand)
        if cnt > best:
            best, delim = cnt, cand
    reader = csv.reader(io.StringIO(text), delimiter=delim)
    rows: list[list[str]] = []
    for row in reader:
        rows.append([c.strip() for c in row])
        if len(rows) > 500000:
            break
    return rows


def parse_text_tables(path: str) -> list[Table]:
    """解析一个文本表格，返回 1 个 :class:`Table`（含全部数值列）。"""
    with open(path, "rb") as fh:
        text = decode_bytes(fh.read())
    rows = _split_lines(text)
    if len(rows) < 3:
        raise ValueError("文件内容太少")

    hdr = _find_header(rows)
    if hdr < 0:
        raise ValueError("找不到表头行（没有可识别的列名）")

    unit_row = None
    sample_row = None
    data_start = hdr + 1
    for k in range(hdr + 1, min(hdr + 4, len(rows))):
        row = rows[k]
        nonempty = [c for c in row if str(c).strip()]
        if not nonempty:
            data_start = k + 1
            continue
        if _is_numeric_row(row):
            data_start = k
            break
        if unit_row is None and all(
            (not str(c).strip()) or _UNIT_RE.match(str(c).strip()) or len(str(c).strip()) <= 6
            for c in nonempty
        ):
            unit_row = row
            data_start = k + 1
            continue
        if sample_row is None:
            sample_row = row
            data_start = k + 1
            continue
        data_start = k
        break

    cols = _make_columns(rows[hdr], unit_row, sample_row)
    if len(cols) < 2:
        raise ValueError("表头里的列太少")
    data = _extract_data(rows, data_start, cols)
    if len([c for c in cols if c.index in data]) < 2:
        raise ValueError("有效数值列少于 2 列")

    parent = os.path.basename(os.path.dirname(os.path.abspath(path)))
    stem = os.path.splitext(os.path.basename(path))[0]
    group = _clean_label(parent) if parent else "数据"
    label = stem
    if parent.lower().endswith(("_rawdata", "_raw")):
        token = re.sub(r"(?i)^specimen[_\-\s]?rawdata[_\-\s]?", "", stem) or stem
        label = f"{group} #{token}"
    return [Table(key=path, source=path, group=group, label=_clean_label(label),
                  kind="csv", columns=cols, data=data)]


# --------------------------------------------------------------------------- #
# Excel
# --------------------------------------------------------------------------- #
def _row_texts(row) -> list[str]:
    return ["" if c is None else (c if isinstance(c, str) else str(c)) for c in row]


def parse_excel_tables(path: str) -> list[Table]:
    from openpyxl import load_workbook

    wb = load_workbook(path, read_only=True, data_only=True)
    out: list[Table] = []
    try:
        for ws in wb.worksheets:
            rows: list[list] = []
            for r_i, row in enumerate(ws.iter_rows(values_only=True)):
                rows.append(list(row))
                if r_i > 200000:
                    break
            if len(rows) < 3:
                continue
            t = _table_from_sheet(rows, ws.title, path)
            if t is not None:
                out.append(t)
    finally:
        wb.close()
    if not out:
        raise ValueError("Excel 中没有找到可绘制的数值列")
    return out


def _table_from_sheet(rows: list[list], sheet: str, path: str) -> Table | None:
    hdr = -1
    for i, row in enumerate(rows[:25]):
        if _is_numeric_row(row):
            continue
        if _row_kind_hits(row) >= 2:
            hdr = i
            break
    if hdr < 0:
        for i, row in enumerate(rows[:25]):
            texts = [t for t in _row_texts(row) if t.strip()]
            if len(texts) >= 2 and not _is_numeric_row(row):
                hdr = i
                break
    if hdr < 0:
        return None

    header = _row_texts(rows[hdr])
    unit_row = None
    name_row = None
    data_start = hdr + 1
    for k in range(hdr + 1, min(hdr + 4, len(rows))):
        row = rows[k]
        nonempty = [t for t in _row_texts(row) if t.strip()]
        if not nonempty:
            data_start = k + 1
            continue
        if _is_numeric_row(row):
            data_start = k
            break
        texts = _row_texts(row)
        if unit_row is None and all(
            (not t.strip()) or _UNIT_RE.match(t.strip()) or len(t.strip()) <= 6 for t in nonempty
        ):
            unit_row = texts
            data_start = k + 1
            continue
        if name_row is None:
            name_row = texts
            data_start = k + 1
            continue
        data_start = k
        break

    cols = _make_columns(header, unit_row, name_row)
    data = _extract_data(rows, data_start, cols)
    cols = [c for c in cols if c.index in data]
    if len(cols) < 2:
        return None

    group = sheet if sheet.upper() not in ("SHEET1", "") else os.path.basename(path)
    return Table(key=f"{path}::{sheet}", source=path, group=group, label=group,
                 kind="xlsx", sheet=sheet, columns=cols, data=data)


# --------------------------------------------------------------------------- #
# 选列 / 生成曲线
# --------------------------------------------------------------------------- #
def _match(col: Column, want: str) -> bool:
    return bool(want) and (col.key == want or col.header == want)


def _pick(table: Table, kind_id: str, want_col: str = "", exclude: set[int] | None = None,
          pool: Sequence[Column] | None = None) -> Column | None:
    """在表里挑一列：优先自定义列名，其次同类型里得分最高的。"""
    exclude = exclude or set()
    cands = [c for c in (pool if pool is not None else table.columns)
             if c.index in table.data and c.index not in exclude]
    if not cands:
        return None
    if want_col:
        for c in cands:
            if _match(c, want_col):
                return c
        return None
    typed = [c for c in cands if c.kind == kind_id]
    if kind_id in ("plain", ""):
        typed = [c for c in cands if c.kind in ("plain", "")]
    if not typed:
        return None
    return max(typed, key=lambda c: (c.score, -c.index))


def _pair_in(table: Table, xm: XYMap, pool: Sequence[Column] | None = None
             ) -> list[tuple[Column, Column]]:
    """在表（或一组列）里找出所有 (X, Y) 列对。

    多块排版（Stress,Strain,Stress,Strain…）会把每个 Y 列与**最近的** X 列配对，
    因此一个 Excel sheet 会输出多条曲线。
    """
    cols = list(pool if pool is not None else table.columns)
    numeric = [c for c in cols if c.index in table.data]
    if len(numeric) < 2:
        return []

    x_custom, y_custom = xm.x_col, xm.y_col
    if x_custom or y_custom:
        x = _pick(table, xm.x_kind, x_custom, pool=numeric)
        y = _pick(table, xm.y_kind, y_custom, pool=numeric, exclude={x.index} if x else set())
        if x and y:
            return [(x, y)]
        # 自定义列名在别的表里，退回按类型
        if x and not y:
            y = _pick(table, xm.y_kind, "", pool=numeric, exclude={x.index})
            return [(x, y)] if y else []
        if y and not x:
            x = _pick(table, xm.x_kind, "", pool=numeric, exclude={y.index})
            return [(x, y)] if x else []
        return []

    ys = [c for c in numeric if c.kind == xm.y_kind]
    if not ys:
        return []
    pairs: list[tuple[Column, Column]] = []
    used: set[int] = set()
    for y in ys:
        best, best_d = None, 99
        for x in numeric:
            if x.kind != xm.x_kind or x.index in used or x.index == y.index:
                continue
            d = abs(x.index - y.index)
            if d < best_d:
                best, best_d = x, d
        if best is not None:
            pairs.append((best, y))
            used.add(best.index)
            used.add(y.index)
        elif best_d == 99:
            # 没找到同类型的 X 列：允许退到"同表任意数值列"太危险，直接跳过
            continue
    return pairs


def _series_from_pair(table: Table, x: Column, y: Column, idx: int, total: int) -> Series | None:
    xv, yv = table.data.get(x.index), table.data.get(y.index)
    if xv is None or yv is None:
        return None
    n = min(xv.size, yv.size)
    if n < 2:
        return None
    label = table.label
    if table.kind == "xlsx":
        sample = (y.sample or x.sample or "").strip()
        if sample:
            label = sample
        elif total > 1:
            label = f"{table.label}-{idx + 1}"
    elif total > 1:
        label = f"{table.label} #{idx + 1}"
    return Series(
        key=f"{table.key}::{x.index}->{y.index}",
        label=label,
        group=table.group,
        source=table.source,
        x=xv[:n], y=yv[:n],
        x_unit=x.unit, y_unit=y.unit,
        kind=table.kind,
        x_header=x.display, y_header=y.display,
    )


def build_series(tables: Iterable[Table], xmap: XYMap) -> tuple[list[Series], list[str]]:
    """按 X/Y 映射把所有表转成曲线列表，返回 ``(series, warnings)``。"""
    series: list[Series] = []
    warnings: list[str] = []
    missing_x = missing_y = 0
    for t in tables:
        pairs = _pair_in(t, xmap)
        if not pairs:
            if xmap.x_col or xmap.y_col:
                continue
            if not t.kind_columns(xmap.x_kind):
                missing_x += 1
            if not t.kind_columns(xmap.y_kind):
                missing_y += 1
            continue
        for i, (x, y) in enumerate(pairs):
            s = _series_from_pair(t, x, y, i, len(pairs))
            if s is not None:
                series.append(s)
    if not series:
        xl = V.kind(xmap.x_kind).label
        yl = V.kind(xmap.y_kind).label
        if xmap.x_col or xmap.y_col:
            warnings.append(f"没有文件同时包含所选的两列（X={xmap.x_col} / Y={xmap.y_col}）")
        elif missing_x and not missing_y:
            warnings.append(f"没有找到「{xl}」这一列，换个 X 变量试试")
        elif missing_y and not missing_x:
            warnings.append(f"没有找到「{yl}」这一列，换个 Y 变量试试")
        else:
            warnings.append(f"没有文件同时包含「{xl}」和「{yl}」，换个组合预设试试")
    series.sort(key=lambda s: (_natural_key(s.group), _natural_key(s.label)))
    return series, warnings


# --------------------------------------------------------------------------- #
# 文件夹扫描
# --------------------------------------------------------------------------- #
_TABLE_CACHE: dict[tuple, list[Table]] = {}


def _cache_key(path: str) -> tuple:
    try:
        st = os.stat(path)
        return (path, st.st_size, int(st.st_mtime))
    except OSError:
        return (path, 0, 0)


def _load_file(path: str) -> list[Table]:
    key = _cache_key(path)
    hit = _TABLE_CACHE.get(key)
    if hit is not None:
        return hit
    ext = os.path.splitext(path)[1].lower()
    tables = parse_excel_tables(path) if ext in EXCEL_EXT else parse_text_tables(path)
    if len(_TABLE_CACHE) > 256:
        _TABLE_CACHE.clear()
    _TABLE_CACHE[key] = tables
    return tables


def clear_cache() -> None:
    _TABLE_CACHE.clear()


def scan_tables(root: str, prefer: str = "auto", recursive: bool = True,
                min_points: int = 10) -> ScanResult:
    """扫描文件夹，把每个数据文件解析成 :class:`Table`（不做 X/Y 选择）。"""
    res = ScanResult()
    if not root or not os.path.isdir(root):
        res.warnings.append(f"文件夹不存在：{root}")
        return res

    text_files: list[str] = []
    excel_files: list[str] = []
    iterator = os.walk(root) if recursive else [(root, [], os.listdir(root))]
    for dirpath, dirnames, filenames in iterator:
        dirnames[:] = sorted(
            [d for d in dirnames if not d.startswith(".") and d.lower() not in SKIP_DIR_HINTS],
            key=_natural_key,
        )
        for fn in sorted(filenames, key=_natural_key):
            if fn.startswith("~$") or fn.startswith("."):
                continue
            ext = os.path.splitext(fn)[1].lower()
            full = os.path.join(dirpath, fn)
            if ext in TEXT_EXT:
                text_files.append(full)
            elif ext in EXCEL_EXT:
                excel_files.append(full)

    def load(files: Iterable[str]) -> None:
        for f in files:
            name = os.path.basename(f).lower()
            if any(tag in name for tag in ("results", "summary", "汇总")):
                res.skipped.append(f"{os.path.basename(f)}: 统计汇总表，已跳过")
                continue
            if any(tag in name for tag in COPY_HINTS):
                res.skipped.append(f"{os.path.basename(f)}: 文件名含「副本/copy」，已跳过")
                continue
            try:
                for t in _load_file(f):
                    biggest = max((len(v) for v in t.data.values()), default=0)
                    if biggest < min_points:
                        res.skipped.append(
                            f"{os.path.basename(f)}: 数据点过少（{biggest}），已跳过")
                        continue
                    res.tables.append(t)
            except Exception as exc:                    # noqa: BLE001
                res.skipped.append(f"{os.path.basename(f)}: {exc}")

    mode = (prefer or "auto").lower()
    if mode == "csv":
        load(text_files)
    elif mode in ("xlsx", "excel"):
        load(excel_files)
    elif mode in ("all", "auto"):
        # 通用模式：文本表与 Excel 全部读入（同一份数据导出两份时由「仅 Excel / 仅 CSV」控制）
        load(excel_files)
        load(text_files)
    else:
        load(excel_files)
        load(text_files)

    res.tables.sort(key=lambda t: (_natural_key(t.group), _natural_key(t.label)))
    return res


def scan_folder(root: str, prefer: str = "auto", recursive: bool = True,
                xmap: XYMap | None = None) -> ScanResult:
    """扫描并按 given X/Y 映射生成曲线（兼容旧接口）。"""
    res = scan_tables(root, prefer, recursive)
    xm = xmap or XYMap()
    res.xmap = xm
    series, warns = build_series(res.tables, xm)
    res.series = series
    for w in warns:
        res.add_warning(w)
    return res


def column_catalog(tables: Iterable[Table]) -> list[tuple[str, str, str]]:
    """所有出现过的列，只按**第一行表头**归类。

    返回 ``(判据, 显示名, 猜测类型)``：判据 = 表头原文（自定义模式直接拿它去找列），
    显示名 = 表头原文（不再附加单位/类型后缀），同一个表头只出现一次。
    """
    counter: dict[str, tuple[int, Column]] = {}
    for t in tables:
        for c in t.columns:
            if c.index not in t.data:
                continue
            head = (c.header or "").strip()
            if not head or _looks_like_unit(head):
                continue
            rec = counter.get(head)
            counter[head] = (rec[0] + 1 if rec else 1, c)
    items = sorted(counter.items(), key=lambda kv: (-kv[1][0], _natural_key(kv[0])))
    return [(head, head, col.kind) for head, (cnt, col) in items]


def folder_preview(root: str, limit: int = 400) -> list[str]:
    """列出文件夹内的数据文件（给界面显示用）。"""
    out: list[str] = []
    if not os.path.isdir(root):
        return out
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for fn in sorted(filenames, key=_natural_key):
            if os.path.splitext(fn)[1].lower() in TEXT_EXT | EXCEL_EXT:
                rel = os.path.relpath(os.path.join(dirpath, fn), root)
                out.append(rel)
                if len(out) >= limit:
                    return out
    return out
