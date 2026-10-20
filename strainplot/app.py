"""StrainPlot 图形界面：一键读取文件夹数据、实时预览、全可视化调参、导出。"""

from __future__ import annotations

import os
import queue
import re
import threading
import time
import traceback
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, ttk
from tkinter import font as tkfont

import numpy as np
from PIL import Image, ImageTk

from . import dataio, palettes, presets, render
from . import variables as V
from .style import CONFIG_DIR, PRESETS, Style, reference_style

APP_TITLE = "StrainPlot · 一键数据绘图（X–Y 通用）"
BG = "#F4F5F7"
CARD = "#FFFFFF"
ACCENT = "#3F6CA8"
UI_FONT = "Microsoft YaHei UI"

CHECKED = "☑"
UNCHECKED = "☐"
PARTIAL = "◪"


# --------------------------------------------------------------------------- #
# 可滚动容器：属性页内容较多时自动出现滚动条，避免控件互相遮挡
# --------------------------------------------------------------------------- #
class ScrollFrame(ttk.Frame):
    def __init__(self, parent, bg: str = CARD) -> None:
        super().__init__(parent)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.vs = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vs.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.body = ttk.Frame(self.canvas)
        self._win = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.body._scroll_owner = self          # type: ignore[attr-defined]
        self.body.bind("<Configure>", self._on_body)
        self.canvas.bind("<Configure>", self._on_canvas)

    def _on_body(self, _e=None) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas(self, event) -> None:
        self.canvas.itemconfigure(self._win, width=event.width)

    def scroll(self, units: int) -> None:
        first, last = self.canvas.yview()
        if first <= 0.0 and last >= 1.0:
            return
        self.canvas.yview_scroll(units, "units")


def _fmt(v) -> str:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    if f.is_integer():
        return f"{int(f)}"
    return f"{f:g}"


def _fmt_num(v) -> str:
    """列表里「最大值」的显示：4 位有效数字，去掉多余的 0（1581 / 108.2 / 0.649）。"""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    if not np.isfinite(f):
        return "—"
    return f"{f:.4g}"


# --------------------------------------------------------------------------- #
# 画布尺寸预设（第一项与 Origin 导出参考图完全一致：4×3 in @600dpi = 2400×1800）
# --------------------------------------------------------------------------- #
FIGURE_PRESETS: dict[str, tuple[float, float, int]] = {
    "Origin 参考图 4×3 in @600dpi": (4.0, 3.0, 600),
    "Origin 4×3 in @300dpi": (4.0, 3.0, 300),
    "期刊单栏 3.5×2.6 in @600dpi": (3.5, 2.625, 600),
    "期刊双栏 7×5.25 in @600dpi": (7.0, 5.25, 600),
    "方图 4×4 in @600dpi": (4.0, 4.0, 600),
}


# --------------------------------------------------------------------------- #
# 主窗口
# --------------------------------------------------------------------------- #
class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1520x940")
        self.minsize(1200, 760)
        self.configure(bg=BG)
        self._setup_style()

        # ---------------- 状态 ----------------
        self.style: Style = reference_style()
        self.series_list: list[dataio.Series] = []
        self.checked: set[str] = set()
        self.groups: dict[str, list[str]] = {}
        self._iid_key: dict[str, str] = {}
        self._iid_group: dict[str, str] = {}
        self._render_job = None
        self._photo: ImageTk.PhotoImage | None = None
        self._q: queue.Queue = queue.Queue()
        self._axis_side = tk.StringVar(value="X")
        self._unidir = tk.StringVar(value="in")
        self.tables: list[dataio.Table] = []
        self.slots: list[presets.Slot] = presets.load()
        self.slot_index = 0
        self.xmap = dataio.XYMap()
        if not self.slots[0].is_blank():
            self.xmap = self.slots[0].to_xymap()
        self._col_catalog: list[tuple[str, str, str]] = []
        self._scan_warnings: list[str] = []
        self._scan_skipped: list[str] = []
        self.xy_preset_var = tk.StringVar(value=presets.slot_label(0, self.slots[0]))
        self.xcol_var = tk.StringVar()
        self.ycol_var = tk.StringVar()
        self.path_var = tk.StringVar(value=self._default_folder())
        self.rule_var = tk.StringVar(value="auto")
        self.status_var = tk.StringVar(value="就绪：请选择数据文件夹")
        self.preview_quality = tk.StringVar(value="快速")

        self._build_ui()
        self.after(60, self._poll_queue)
        self.after(250, lambda: self.load_folder(self.path_var.get(), silent=True))

    # ------------------------------------------------------------------ #
    @staticmethod
    def _default_folder() -> str:
        here = os.path.dirname(os.path.abspath(__file__))          # .../strainplot
        outer = os.path.dirname(here)                              # 源码根 或 打包后的 app/
        roots = [outer, os.path.dirname(outer)]                    # 打包后多探一层（安装根目录）
        for root in roots:
            for name in ("示例", "data", "数据", "SampleData"):
                p = os.path.join(root, name)
                if os.path.isdir(p):
                    return p
        home = os.path.expanduser("~")
        docs = os.path.join(home, "Documents")
        return docs if os.path.isdir(docs) else home

    def _setup_style(self) -> None:
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
            try:
                tkfont.nametofont(name).configure(family=UI_FONT, size=9)
            except tk.TclError:
                pass
        st = ttk.Style(self)
        try:
            st.theme_use("clam")
        except tk.TclError:
            pass
        st.configure(".", background=BG, font=(UI_FONT, 9))
        st.configure("TFrame", background=BG)
        st.configure("Card.TFrame", background=CARD)
        st.configure("Preview.TFrame", background=CARD)
        st.configure("TLabel", background=CARD, foreground="#222222")
        st.configure("Head.TLabel", background=CARD, font=(UI_FONT, 10, "bold"), foreground="#1F2937")
        st.configure("Hint.TLabel", background=CARD, foreground="#6B7280", font=(UI_FONT, 8))
        st.configure("Status.TLabel", background=BG, foreground="#4B5563", font=(UI_FONT, 8))
        st.configure("Treeview", background=CARD, fieldbackground=CARD, rowheight=22)
        st.configure("Treeview.Heading", font=(UI_FONT, 8))
        st.configure("TNotebook", background=CARD, borderwidth=0)
        st.configure("TNotebook.Tab", padding=(6, 3), font=(UI_FONT, 9))
        st.configure("TCheckbutton", background=CARD)
        st.configure("TRadiobutton", background=CARD)

    # ------------------------------------------------------------------ #
    # 界面搭建
    # ------------------------------------------------------------------ #
    def _build_ui(self) -> None:
        self.columnconfigure(1, weight=1)
        self.rowconfigure(1, weight=1)
        self._build_toolbar()
        self._build_left()
        self._build_center()
        self._build_right()
        self._build_status()
        self.bind_all("<MouseWheel>", self._on_wheel, add="+")

    def _build_toolbar(self) -> None:
        bar = ttk.Frame(self, style="Card.TFrame", padding=(8, 6))
        bar.grid(row=0, column=0, columnspan=3, sticky="ew", padx=8, pady=(8, 4))

        ttk.Button(bar, text="① 选择数据文件夹", command=self.pick_folder).pack(side="left")
        ent = ttk.Entry(bar, textvariable=self.path_var, width=46)
        ent.pack(side="left", padx=6)
        ent.bind("<Return>", lambda _e: self.load_folder(self.path_var.get()))

        ttk.Button(bar, text="重新扫描", command=lambda: self.load_folder(self.path_var.get())).pack(side="left")

        ttk.Label(bar, text="导入规则").pack(side="left", padx=(12, 3))
        ttk.Combobox(bar, textvariable=self.rule_var, width=6, state="readonly",
                     values=["auto", "all", "xlsx", "csv"]).pack(side="left")
        ttk.Label(bar, text="auto = 全部读取（推荐）", style="Hint.TLabel").pack(side="left", padx=6)

        ttk.Button(bar, text="⑤ 导出图片", command=self.open_export).pack(side="right")
        ttk.Button(bar, text="载入样式", command=self.load_style).pack(side="right", padx=4)
        ttk.Button(bar, text="保存样式", command=self.save_style).pack(side="right")

    def _build_left(self) -> None:
        wrap = ttk.Frame(self, style="Card.TFrame", width=316)
        wrap.grid(row=1, column=0, sticky="nsw", padx=(8, 4), pady=(0, 4))
        wrap.pack_propagate(False)

        head = ttk.Frame(wrap, style="Card.TFrame", padding=(8, 8, 8, 0))
        head.pack(fill="x")
        ttk.Label(head, text="② 数据曲线", style="Head.TLabel").pack(side="left")
        self.count_label = ttk.Label(head, text="", style="Hint.TLabel")
        self.count_label.pack(side="right")

        btns = ttk.Frame(wrap, style="Card.TFrame", padding=(8, 4, 8, 2))
        btns.pack(fill="x")
        for text, cmd in (("全选", lambda: self._check_all(True)),
                          ("全不选", lambda: self._check_all(False)),
                          ("反选", self.invert_checked)):
            ttk.Button(btns, text=text, width=6, command=cmd).pack(side="left", padx=(0, 4))

        holder = ttk.Frame(wrap, style="Card.TFrame", padding=(6, 2, 6, 2))
        holder.pack(fill="both", expand=True)
        cols = ("show", "curve", "info")
        self.tree = ttk.Treeview(holder, columns=cols, show="tree headings", selectmode="extended")
        self.tree.heading("#0", text="数据源")
        self.tree.heading("show", text="显示")
        self.tree.heading("curve", text="曲线")
        self.tree.heading("info", text="最大值")
        self.tree.column("#0", width=104, minwidth=60, stretch=False)
        self.tree.column("show", width=30, minwidth=26, anchor="center", stretch=False)
        self.tree.column("curve", width=98, minwidth=70, anchor="w")
        self.tree.column("info", width=66, minwidth=50, anchor="e", stretch=False)
        sb = ttk.Scrollbar(holder, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<Button-1>", self._on_tree_click)
        self.tree.bind("<space>", self._toggle_selected)
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._refresh_series_tab())

        ttk.Label(wrap, text="点击 ☐/☑ 切换显示，空格键同样有效；数据源行可整组开关",
                  style="Hint.TLabel", wraplength=292, justify="left").pack(
            fill="x", padx=10, pady=(0, 8))

    def _build_center(self) -> None:
        wrap = ttk.Frame(self, style="Card.TFrame")
        wrap.grid(row=1, column=1, sticky="nsew", pady=(0, 4))
        wrap.rowconfigure(1, weight=1)
        wrap.columnconfigure(0, weight=1)

        head = ttk.Frame(wrap, style="Card.TFrame", padding=(8, 6, 8, 2))
        head.grid(row=0, column=0, sticky="ew")
        ttk.Label(head, text="③ 实时预览", style="Head.TLabel").pack(side="left")
        ttk.Label(head, text="（右侧任意属性修改后立即重绘）", style="Hint.TLabel").pack(side="left", padx=8)
        q = ttk.Combobox(head, textvariable=self.preview_quality, width=6, state="readonly",
                         values=["快速", "精细"])
        q.pack(side="right")
        q.bind("<<ComboboxSelected>>", lambda _e: self.schedule_render(0))
        ttk.Label(head, text="预览质量", style="Hint.TLabel").pack(side="right", padx=4)

        holder = ttk.Frame(wrap, style="Preview.TFrame", padding=6)
        holder.grid(row=1, column=0, sticky="nsew")
        holder.rowconfigure(0, weight=1)
        holder.columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(holder, bg="#FFFFFF", highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.canvas.bind("<Configure>", lambda _e: self.schedule_render(260))
        self.canvas.bind("<Double-Button-1>", lambda _e: self.open_export())

    def _build_right(self) -> None:
        wrap = ttk.Frame(self, style="Card.TFrame", width=346)
        wrap.grid(row=1, column=2, sticky="nse", padx=(4, 8), pady=(0, 4))
        wrap.pack_propagate(False)

        head = ttk.Frame(wrap, style="Card.TFrame", padding=(8, 8, 8, 2))
        head.pack(fill="x")
        ttk.Label(head, text="④ 图形属性（全可视化编辑）", style="Head.TLabel").pack(side="left")

        self.nb = ttk.Notebook(wrap)
        self.nb.pack(fill="both", expand=True, padx=4, pady=4)
        self.tab_var = ScrollFrame(self.nb)
        self.tab_palette = ScrollFrame(self.nb)
        self.tab_fig = ScrollFrame(self.nb)
        self.tab_axis = ScrollFrame(self.nb)
        self.tab_font = ScrollFrame(self.nb)
        self.tab_legend = ScrollFrame(self.nb)
        self.tab_series = ScrollFrame(self.nb)
        for tab, text in ((self.tab_var, "变量"), (self.tab_palette, "配色"),
                          (self.tab_fig, "图表"), (self.tab_axis, "坐标轴"),
                          (self.tab_font, "字体"), (self.tab_legend, "图例"),
                          (self.tab_series, "曲线")):
            self.nb.add(tab, text=text)

        self._build_variable_tab()
        self._build_palette_tab()
        self._build_figure_tab()
        self._build_axis_tab()
        self._build_font_tab()
        self._build_legend_tab()
        self._build_series_tab()

    def _build_status(self) -> None:
        bar = ttk.Frame(self, style="TFrame")
        bar.grid(row=2, column=0, columnspan=3, sticky="ew", padx=10, pady=(0, 6))
        ttk.Label(bar, textvariable=self.status_var, style="Status.TLabel").pack(side="left")
        self.size_status = ttk.Label(bar, text="", style="Status.TLabel")
        self.size_status.pack(side="right")

    # ------------------------------------------------------------------ #
    # 控件工厂
    # ------------------------------------------------------------------ #
    def _row(self, parent) -> ttk.Frame:
        row = ttk.Frame(parent)
        row.pack(fill="x", padx=8, pady=1)
        return row

    def _sep(self, parent, title: str) -> None:
        ttk.Separator(parent, orient="horizontal").pack(fill="x", padx=8, pady=(8, 0))
        ttk.Label(parent, text=title, style="Head.TLabel").pack(anchor="w", padx=8, pady=(4, 2))

    def add_check(self, parent, label: str, obj, attr: str, on_change=None) -> None:
        var = tk.BooleanVar(value=bool(getattr(obj, attr)))

        def cmd():
            setattr(obj, attr, var.get())
            if on_change is not None:
                on_change()
            self.schedule_render()

        ttk.Checkbutton(parent, text=label, variable=var, command=cmd).pack(anchor="w", padx=10, pady=1)

    def add_spin(self, parent, label: str, obj, attr: str, lo: float, hi: float,
                 step: float = 1.0, width: int = 8) -> None:
        row = self._row(parent)
        ttk.Label(row, text=label, width=12, anchor="w").pack(side="left")
        var = tk.StringVar(value=_fmt(getattr(obj, attr)))
        sp = ttk.Spinbox(row, from_=lo, to=hi, increment=step, width=width, textvariable=var)
        sp.pack(side="left")

        def commit(*_a):
            try:
                val = float(var.get())
            except ValueError:
                var.set(_fmt(getattr(obj, attr)))
                return
            val = max(lo, min(hi, val))
            cur = getattr(obj, attr)
            setattr(obj, attr, int(round(val)) if isinstance(cur, int) else val)
            var.set(_fmt(getattr(obj, attr)))
            self.schedule_render()

        sp.bind("<Return>", commit)
        sp.bind("<FocusOut>", commit)
        return sp

    def add_entry(self, parent, label: str, obj, attr: str) -> None:
        row = self._row(parent)
        ttk.Label(row, text=label, width=12, anchor="w").pack(side="left")
        var = tk.StringVar(value=str(getattr(obj, attr)))

        def commit(*_a):
            setattr(obj, attr, var.get())
            self.schedule_render()

        ent = ttk.Entry(row, textvariable=var)
        ent.pack(side="left", fill="x", expand=True)
        ent.bind("<Return>", commit)
        ent.bind("<FocusOut>", commit)

    def add_combo(self, parent, label: str, obj, attr: str, values) -> None:
        row = self._row(parent)
        ttk.Label(row, text=label, width=12, anchor="w").pack(side="left")
        var = tk.StringVar(value=str(getattr(obj, attr)))
        cb = ttk.Combobox(row, textvariable=var, values=list(values), state="readonly", width=10)
        cb.pack(side="left")

        def commit(*_a):
            setattr(obj, attr, var.get())
            self.schedule_render()

        cb.bind("<<ComboboxSelected>>", commit)

    def add_color(self, parent, label: str, obj, attr: str) -> None:
        row = self._row(parent)
        ttk.Label(row, text=label, width=12, anchor="w").pack(side="left")
        btn = tk.Button(row, width=4, bg=str(getattr(obj, attr)), relief="flat", bd=1,
                        activebackground=str(getattr(obj, attr)))
        btn.pack(side="left")

        def pick():
            cur = str(getattr(obj, attr))
            _rgb, code = colorchooser.askcolor(color=cur, parent=self)
            if code:
                setattr(obj, attr, code)
                btn.configure(bg=code, activebackground=code)
                self.schedule_render()

        btn.configure(command=pick)
        ttk.Label(row, text="点击换色", style="Hint.TLabel").pack(side="left", padx=6)

    # ------------------------------------------------------------------ #
    # 变量页（v2 核心）
    # ------------------------------------------------------------------ #
    def _slot_label(self, i: int) -> str:
        """槽位在界面上的名字：一律写表头原文；按量类型存的旧槽位用当前文件夹补全。"""
        s = self.slots[i]
        if s.is_blank():
            return f"{i + 1} · （空置）"
        if s.name:
            return f"{i + 1} · {s.name}"
        x = s.x_col or self._first_col_of_kind(s.x_kind) or "?"
        y = s.y_col or self._first_col_of_kind(s.y_kind) or "?"
        return f"{i + 1} · {x} → {y}"

    def _refresh_slot_box(self) -> None:
        self.preset_box.configure(values=[self._slot_label(i) for i in range(presets.SLOT_COUNT)])
        self.xy_preset_var.set(self._slot_label(self.slot_index))

    def _build_variable_tab(self) -> None:
        tab = self.tab_var.body
        ttk.Label(tab, text="画哪两列（X → Y）", style="Head.TLabel").pack(
            anchor="w", padx=8, pady=(8, 0))
        ttk.Label(tab, text="5 个预设槽位，可改、可存、可清空；换变量不会重新读文件",
                  style="Hint.TLabel").pack(anchor="w", padx=8, pady=(0, 4))

        ttk.Label(tab, text="读取方式预设", style="Head.TLabel").pack(anchor="w", padx=8, pady=(6, 0))
        self.preset_box = ttk.Combobox(tab, textvariable=self.xy_preset_var, state="readonly",
                                       values=[self._slot_label(i) for i in range(presets.SLOT_COUNT)],
                                       width=30)
        self.preset_box.pack(fill="x", padx=8, pady=(2, 0))
        self.preset_box.bind("<<ComboboxSelected>>", lambda _e: self._on_slot())
        self.preset_note = ttk.Label(tab, text="", style="Hint.TLabel", wraplength=290,
                                    justify="left")
        self.preset_note.pack(anchor="w", padx=8)

        srow = ttk.Frame(tab)
        srow.pack(fill="x", padx=8, pady=(4, 2))
        ttk.Button(srow, text="保存到预设", width=10,
                   command=self._save_slot).pack(side="left")
        ttk.Button(srow, text="重命名", width=7,
                   command=self._rename_slot).pack(side="left", padx=4)
        ttk.Button(srow, text="清空", width=6,
                   command=self._clear_slot).pack(side="left")
        ttk.Button(srow, text="恢复默认", width=8,
                   command=self._reset_slots).pack(side="left", padx=4)

        self._kind_labels = [f"{k.label}  {k.desc}" for k in V.KINDS]

        for axis in ("x", "y"):
            self._sep(tab, f"{'X 轴' if axis == 'x' else 'Y 轴'}变量")
            var = self.xcol_var if axis == "x" else self.ycol_var
            box = ttk.Combobox(tab, textvariable=var, state="readonly",
                               values=[], width=30)
            box.pack(fill="x", padx=8, pady=2)
            box.bind("<<ComboboxSelected>>",
                     lambda _e, a=axis: self._on_col_axis(a))
            if axis == "x":
                self.xcol_box = box
            else:
                self.ycol_box = box

            row = ttk.Frame(tab)
            row.pack(fill="x", padx=8, pady=2)
            ttk.Label(row, text="单位", width=5).pack(side="left")
            ent = ttk.Entry(row, width=10)
            ent.pack(side="left")
            ent.bind("<Return>", lambda _e, a=axis, w=ent: self._on_unit(a, w.get()))
            ttk.Label(row, text="空 = 用默认", style="Hint.TLabel").pack(side="left", padx=6)
            if axis == "x":
                self.xunit_entry = ent
            else:
                self.yunit_entry = ent

            row2 = ttk.Frame(tab)
            row2.pack(fill="x", padx=8, pady=2)
            ttk.Label(row2, text="轴标题", width=5).pack(side="left")
            lent = ttk.Entry(row2, width=22)
            lent.pack(side="left", fill="x", expand=True, padx=(4, 0))
            lent.bind("<Return>", lambda _e, a=axis, w=lent: self._on_label(a, w.get()))
            lent.bind("<FocusOut>", lambda _e, a=axis, w=lent: self._on_label(a, w.get()))
            if axis == "x":
                self.xlabel_entry = lent
            else:
                self.ylabel_entry = lent

        act = ttk.Frame(tab)
        act.pack(fill="x", padx=8, pady=(8, 2))
        ttk.Button(act, text="⇄  反转 X–Y", width=14,
                   command=self.swap_xy).pack(side="left")
        ttk.Button(act, text="重载当前预设", width=12,
                   command=self._on_slot).pack(side="left", padx=6)

        self._sep(tab, "检测到的列")
        self.col_hint = ttk.Label(tab, text="（扫描后显示）", style="Hint.TLabel",
                                  justify="left", wraplength=290)
        self.col_hint.pack(anchor="w", padx=8, pady=(0, 8))

        self._sync_var_widgets()

    # ---- 变量页事件 ----
    def _on_slot(self) -> None:
        """把当前选中槽位的映射套到界面上。"""
        self.slot_index = self._slot_index_from_label(self.xy_preset_var.get())
        slot = self.slots[self.slot_index]
        if slot.is_blank():
            self.preset_note.configure(text="空预设：选好 X/Y 后点「保存到预设」")
            self._refresh_slot_box()
            return
        self.xmap = slot.to_xymap()
        self._resolve_columns()
        self._sync_var_widgets()
        self._apply_mapping()

    def _slot_index_from_label(self, label: str) -> int:
        for i in range(len(self.slots)):
            if self._slot_label(i) == label:
                return i
        for i in range(len(self.slots)):
            if label.startswith(f"{i + 1} · "):
                return i
        return 0

    def _save_slot(self) -> None:
        i = self.slot_index
        self.slots[i] = presets.Slot.from_xymap(self.xmap, name=self.slots[i].name)
        self._refresh_slot_box()
        self.preset_note.configure(text=f"已保存到预设 {i + 1}：{self.slots[i].display()}")
        try:
            presets.save(self.slots)
            self.status_var.set(f"已保存读取方式到预设 {i + 1}")
        except Exception as exc:                     # noqa: BLE001
            self.status_var.set(f"预设已生效，但写入磁盘失败：{exc}")

    def _rename_slot(self) -> None:
        from tkinter import simpledialog

        i = self.slot_index
        cur = self.slots[i].name or self.slots[i].display()
        name = simpledialog.askstring("重命名预设", f"预设 {i + 1} 的名称：", initialvalue=cur,
                                      parent=self)
        if name is None:
            return
        self.slots[i].name = name.strip()
        try:
            presets.save(self.slots)
        except Exception:                            # noqa: BLE001
            pass
        self._refresh_slot_box()

    def _clear_slot(self) -> None:
        i = self.slot_index
        self.slots[i] = presets.Slot()
        try:
            presets.save(self.slots)
        except Exception:                            # noqa: BLE001
            pass
        self._refresh_slot_box()
        self.preset_note.configure(text=f"预设 {i + 1} 已清空")

    def _reset_slots(self) -> None:
        if not messagebox.askyesno("恢复默认预设",
                                   "把 5 个预设恢复成出厂状态？\n（预设 1 = 拉伸应力–应变，其余为空）",
                                   parent=self):
            return
        self.slots = presets.factory_slots()
        try:
            presets.save(self.slots)
        except Exception:                            # noqa: BLE001
            pass
        self.slot_index = 0
        self._refresh_slot_box()
        self._on_slot()

    def _on_col_axis(self, axis: str) -> None:
        """下拉框选的是**表头原文**，直接当作列名。"""
        var = self.xcol_var if axis == "x" else self.ycol_var
        key = var.get().strip()
        kind = self._kind_of_col(key)
        if axis == "x":
            self.xmap.x_col, self.xmap.x_kind = key, kind
            self.xmap.x_label = self._col_title(key)
        else:
            self.xmap.y_col, self.xmap.y_kind = key, kind
            self.xmap.y_label = self._col_title(key)
        self._resolve_columns()
        self._sync_var_widgets()
        self._apply_mapping()

    def _on_unit(self, axis: str, text: str) -> None:
        text = text.strip()
        if axis == "x":
            self.xmap.x_unit = text or None
            base = re.sub(r"\s*\([^()]*\)\s*$", "", self.xmap.x_label).strip()
            self.xmap.x_label = f"{base} ({text})" if (text and base) else base
        else:
            self.xmap.y_unit = text or None
            base = re.sub(r"\s*\([^()]*\)\s*$", "", self.xmap.y_label).strip()
            self.xmap.y_label = f"{base} ({text})" if (text and base) else base
        self._apply_mapping()

    def _on_label(self, axis: str, text: str) -> None:
        text = text.strip()
        if axis == "x":
            self.xmap.x_label = text
        else:
            self.xmap.y_label = text
        self._apply_mapping()

    def _col_title(self, header: str) -> str:
        """按表头找到列，给出轴标题：认识这个量就用英文量名，否则用表头原文。"""
        for t in self.tables:
            for c in t.columns:
                if (c.header or "").strip() == header:
                    if c.kind and c.kind != "plain":
                        return V.axis_label(c.kind, c.unit or None)
                    u = (c.unit or "").strip()
                    return f"{header} ({u})" if u else header
        return header

    def _kind_of_col(self, header: str) -> str:
        """查一个表头对应的量类型；认不出返回 "plain"。"""
        for t in self.tables:
            for c in t.columns:
                if (c.header or "").strip() == header and c.kind:
                    return c.kind
        return "plain"

    def _first_col_of_kind(self, kind: str) -> str:
        """按量类型找第一个满足条件的表头（预设跨文件夹复用用）。"""
        if not kind or kind == "plain":
            return ""
        for t in self.tables:
            for c in t.columns:
                if c.kind == kind and (c.header or "").strip():
                    return c.header.strip()
        return ""

    def _resolve_columns(self) -> None:
        """把 xmap 的列落实成当前文件夹里真正存在的表头。

        预设可能是按「量类型」存的（换文件夹后表头变了），也可能是按旧表头存的，
        这里统一解析一次，界面上永远显示文件里的原文。
        """
        heads = {c[0] for c in self._col_catalog}
        m = self.xmap
        for attr_col, attr_kind, attr_label in (("x_col", "x_kind", "x_label"),
                                                ("y_col", "y_kind", "y_label")):
            col = getattr(m, attr_col).strip()
            kind = getattr(m, attr_kind)
            if col and col in heads:
                if not kind or kind == "plain":
                    setattr(m, attr_kind, self._kind_of_col(col))
                if not getattr(m, attr_label):
                    setattr(m, attr_label, self._col_title(col))
                continue
            alt = col if col in heads else self._first_col_of_kind(kind)
            if alt:
                setattr(m, attr_col, alt)
                setattr(m, attr_kind, self._kind_of_col(alt))
                setattr(m, attr_label, self._col_title(alt))

    def swap_xy(self) -> None:
        self.xmap = self.xmap.swapped()
        self._sync_var_widgets()
        self._apply_mapping()

    def _sync_var_widgets(self) -> None:
        """把 xmap 的当前状态写回界面控件。"""
        m = self.xmap
        self.xunit_entry.delete(0, "end")
        self.xunit_entry.insert(0, "" if m.x_unit is None else m.x_unit)
        self.yunit_entry.delete(0, "end")
        self.yunit_entry.insert(0, "" if m.y_unit is None else m.y_unit)
        self.xlabel_entry.delete(0, "end")
        self.xlabel_entry.insert(0, m.x_label)
        self.ylabel_entry.delete(0, "end")
        self.ylabel_entry.insert(0, m.y_label)
        self.xcol_var.set(m.x_col)
        self.ycol_var.set(m.y_col)
        self._update_preset_note()

    def _update_preset_note(self) -> None:
        m = self.xmap
        if not (m.x_col or m.y_col):
            self.preset_note.configure(
                text="还没选列 —— 在下面选好 X / Y（表头原文），或选一个预设")
            return
        self.preset_note.configure(
            text=(f"取列：{m.x_col or '—'} → {m.y_col or '—'}\n"
                  f"绘图轴标题：{self.xmap.x_axis_label()} / {self.xmap.y_axis_label()}"))

    # ------------------------------------------------------------------ #
    # 配色页
    # ------------------------------------------------------------------ #
    def _build_palette_tab(self) -> None:
        tab = self.tab_palette.body
        names = palettes.palette_names()
        ttk.Label(tab, text="科研配色方案", style="Head.TLabel").pack(anchor="w", padx=8, pady=(8, 0))
        ttk.Label(tab, text="默认方案取自参考图实测颜色", style="Hint.TLabel").pack(anchor="w", padx=8)

        self.palette_list = tk.Listbox(tab, height=12, activestyle="none", exportselection=False,
                                       font=(UI_FONT, 9), bd=1, relief="solid", highlightthickness=0)
        for name in names:
            self.palette_list.insert("end", name)
        self.palette_list.pack(fill="x", padx=8, pady=6)
        if self.style.palette in names:
            idx = names.index(self.style.palette)
            self.palette_list.selection_set(idx)
            self.palette_list.see(idx)

        self.swatch = tk.Canvas(tab, height=46, bg=CARD, highlightthickness=0)
        self.swatch.pack(fill="x", padx=8)

        def apply_palette():
            sel = self.palette_list.curselection()
            if not sel:
                return
            name = self.palette_list.get(sel[0])
            self.style.apply_palette(name, [s.key for s in self.series_list])
            self.style.palette = name
            self._draw_swatches()
            self._refresh_series_tab()
            self.schedule_render()

        ttk.Button(tab, text="应用该配色", command=apply_palette).pack(fill="x", padx=8, pady=(6, 2))
        self.palette_list.bind("<Double-Button-1>", lambda _e: apply_palette())
        self.palette_list.bind("<<ListboxSelect>>", lambda _e: self._draw_swatches())

        self._sep(tab, "整体预设")
        row = ttk.Frame(tab)
        row.pack(fill="x", padx=8, pady=4)
        self.preset_var = tk.StringVar(value=list(PRESETS)[0])
        cb = ttk.Combobox(row, textvariable=self.preset_var, values=list(PRESETS), state="readonly")
        cb.pack(side="left", fill="x", expand=True)

        def apply_preset():
            factory = PRESETS.get(self.preset_var.get())
            if not factory:
                return
            new = factory()
            new.series = self.style.series
            new.palette = self.style.palette
            self.style = new
            self._rebuild_all_tabs()
            self.schedule_render()

        ttk.Button(row, text="套用", width=6, command=apply_preset).pack(side="left", padx=4)

        self._sep(tab, "线条默认值")
        line_row = ttk.Frame(tab)
        line_row.pack(fill="x", padx=8, pady=4)
        ttk.Label(line_row, text="全部曲线线宽", width=12, anchor="w").pack(side="left")
        self._all_width = tk.StringVar(value="1.0")
        sp = ttk.Spinbox(line_row, from_=0.2, to=10, increment=0.2, width=8, textvariable=self._all_width)
        sp.pack(side="left")

        def apply_width():
            try:
                w = float(self._all_width.get())
            except ValueError:
                return
            self.style.set_all("width", w)
            self._refresh_series_tab()
            self.schedule_render()

        sp.bind("<Return>", lambda _e: apply_width())
        sp.bind("<FocusOut>", lambda _e: apply_width())
        self._draw_swatches()

    def _draw_swatches(self) -> None:
        sel = self.palette_list.curselection()
        name = self.palette_list.get(sel[0]) if sel else self.style.palette
        pal = palettes.get_palette(name)
        self.swatch.delete("all")
        w = max(1, self.swatch.winfo_width() or 300)
        n = max(1, len(pal.colors))
        cw = max(6, int(w / n))
        for i, c in enumerate(pal.colors):
            self.swatch.create_rectangle(i * cw, 2, (i + 1) * cw - 2, 24, fill=c, outline="")
        self.swatch.create_text(2, 28, anchor="nw", text=f"{n} 色 · {pal.note}",
                                fill="#6B7280", font=(UI_FONT, 7))

    # ------------------------------------------------------------------ #
    # 图表页
    # ------------------------------------------------------------------ #
    def _build_figure_tab(self) -> None:
        tab = self.tab_fig.body
        f = self.style.figure
        ttk.Label(tab, text="画布尺寸", style="Head.TLabel").pack(anchor="w", padx=8, pady=(8, 2))

        prow = ttk.Frame(tab)
        prow.pack(fill="x", padx=8, pady=2)
        ttk.Label(prow, text="尺寸预设", width=12, anchor="w").pack(side="left")
        self.size_preset = tk.StringVar(value=self._match_preset(f))
        cb = ttk.Combobox(prow, textvariable=self.size_preset, state="readonly", width=17,
                          values=list(FIGURE_PRESETS) + ["自定义"])
        cb.pack(side="left")
        cb.bind("<<ComboboxSelected>>", lambda _e: self._apply_size_preset())

        self.add_spin(tab, "宽 (inch)", f, "width_in", 1.0, 40.0, 0.5)
        self.add_spin(tab, "高 (inch)", f, "height_in", 1.0, 40.0, 0.5)
        self.add_spin(tab, "导出 dpi", f, "dpi", 72, 2400, 50)
        row = ttk.Frame(tab)
        row.pack(fill="x", padx=8, pady=2)
        ttk.Label(row, text="像素尺寸", width=12, anchor="w").pack(side="left")
        self.size_hint = ttk.Label(row, text="", style="Hint.TLabel")
        self.size_hint.pack(side="left")
        ttk.Label(tab, text="参考图即 4 × 3 inch，600 dpi 导出为 2400 × 1800 px",
                  style="Hint.TLabel").pack(anchor="w", padx=12)

        self.add_entry(tab, "图标题", f, "title")
        self.add_spin(tab, "标题字号", f, "title_size", 4, 72, 1)
        self.add_color(tab, "背景色", f, "bg")
        self.add_check(tab, "导出透明背景", f, "transparent")

        self._sep(tab, "页边距（pt）")
        self.add_check(tab, "自动计算边距", f, "margin_auto",
                       on_change=self._update_margin_state)
        self.margin_spins = []
        for attr, label in (("m_left", "左边距"), ("m_right", "右边距"),
                            ("m_top", "上边距"), ("m_bottom", "下边距")):
            self.margin_spins.append(self.add_spin(tab, label, f, attr, 0, 300, 1))
        self._update_margin_state()
        self._update_size_hint()

    def _update_margin_state(self) -> None:
        """自动计算边距时，四个边距输入框置灰。"""
        st = "disabled" if self.style.figure.margin_auto else "normal"
        for sp in getattr(self, "margin_spins", []):
            try:
                sp.configure(state=st)
            except tk.TclError:
                pass

    @staticmethod
    def _match_preset(f) -> str:
        for name, (w, h, dpi) in FIGURE_PRESETS.items():
            if abs(f.width_in - w) < 1e-6 and abs(f.height_in - h) < 1e-6 and int(f.dpi) == dpi:
                return name
        return "自定义"

    def _apply_size_preset(self) -> None:
        name = self.size_preset.get()
        if name not in FIGURE_PRESETS:
            return
        w, h, dpi = FIGURE_PRESETS[name]
        f = self.style.figure
        f.width_in, f.height_in, f.dpi = w, h, dpi
        self._rebuild_all_tabs()
        self.schedule_render()

    def _update_size_hint(self) -> None:
        f = self.style.figure
        text = f"{int(round(f.width_in * f.dpi))} × {int(round(f.height_in * f.dpi))} px"
        if hasattr(self, "size_hint"):
            self.size_hint.configure(text=text)
        if hasattr(self, "size_status"):
            self.size_status.configure(text=text)

    # ------------------------------------------------------------------ #
    # 坐标轴页
    # ------------------------------------------------------------------ #
    def _build_axis_tab(self) -> None:
        top = ttk.Frame(self.tab_axis.body)
        top.pack(fill="x", padx=8, pady=(8, 4))
        ttk.Label(top, text="编辑").pack(side="left")
        for side, text in (("X", "X 轴"), ("Y", "Y 轴")):
            ttk.Radiobutton(top, text=text, value=side, variable=self._axis_side,
                            command=self._rebuild_axis_tab).pack(side="left", padx=3)
        self.axis_body = ttk.Frame(self.tab_axis.body)
        self.axis_body.pack(fill="both", expand=True)
        self._rebuild_axis_tab()

    def _set_attr(self, obj, attr: str, value) -> None:
        setattr(obj, attr, value)
        self.schedule_render()

    def _apply_unidir(self, ax) -> None:
        d = self._unidir.get()
        for s in ("bottom", "top", "left", "right"):
            setattr(ax, f"dir_{s}", d)
        self._rebuild_axis_tab()
        self.schedule_render()

    def _rebuild_axis_tab(self) -> None:
        for w in self.axis_body.winfo_children():
            w.destroy()
        body = self.axis_body
        is_x = self._axis_side.get() == "X"
        ax = self.style.xaxis if is_x else self.style.yaxis

        self._sep(body, "轴标题与范围")
        self.add_entry(body, "轴标题", ax, "label")
        self.add_combo(body, "坐标尺度", ax, "scale", ["linear", "log"])
        self.add_check(body, "自动范围", ax, "auto_range")
        self.add_spin(body, "最小值", ax, "vmin", -1e9, 1e9, 1)
        self.add_spin(body, "最大值", ax, "vmax", -1e9, 1e9, 1)
        self.add_spin(body, "留白 (%)", ax, "pad_pct", 0, 60, 1)
        self.add_spin(body, "主刻度间隔", ax, "major", 0, 1e7, 1)
        ttk.Label(body, text="主刻度间隔填 0 表示按数据自动", style="Hint.TLabel").pack(anchor="w", padx=12)
        self.add_spin(body, "次刻度数", ax, "minor_sub", 0, 20, 1)
        self.add_combo(body, "数字格式", ax, "num_fmt",
                       ["auto", "%.0f", "%.1f", "%.2f", "%.3f", "%.3g"])

        self._sep(body, "轴线 · 刻度 · 数字（按边独立设置）")
        uni = ttk.Frame(body)
        uni.pack(fill="x", padx=8, pady=(2, 0))
        ttk.Label(uni, text="刻度朝向", width=8, anchor="w").pack(side="left")
        ttk.Combobox(uni, textvariable=self._unidir, values=["in", "out", "inout"],
                     width=6, state="readonly").pack(side="left")
        ttk.Button(uni, text="应用到两条边", width=13,
                   command=lambda: self._apply_unidir(ax)).pack(side="left", padx=4)
        ttk.Label(body, text="in 朝内 · out 朝外 · inout 双向", style="Hint.TLabel").pack(anchor="w", padx=12)

        grid_w = ttk.Frame(body)
        grid_w.pack(fill="x", padx=10, pady=(6, 2))
        heads = ("轴线", "主刻度", "次刻度", "数字")
        ttk.Label(grid_w, text="边", width=3, style="Hint.TLabel").grid(row=0, column=0, sticky="w")
        for j, h in enumerate(heads):
            ttk.Label(grid_w, text=h, style="Hint.TLabel", anchor="center").grid(
                row=0, column=j + 1, padx=1, sticky="ew")
        ttk.Label(grid_w, text="朝向", style="Hint.TLabel").grid(row=0, column=5, padx=2, sticky="ew")

        sides = (("下", "bottom"), ("上", "top")) if is_x else (("左", "left"), ("右", "right"))
        for i, (cn, en) in enumerate(sides, start=1):
            ttk.Label(grid_w, text=cn, width=3).grid(row=i, column=0, sticky="w", pady=2)
            for j, attr in enumerate((f"spine_{en}", f"ticks_{en}", f"minor_{en}", f"labels_{en}")):
                var = tk.BooleanVar(value=bool(getattr(ax, attr)))
                ttk.Checkbutton(grid_w, variable=var, takefocus=0,
                                command=lambda a=attr, v=var: self._set_attr(ax, a, v.get())
                                ).grid(row=i, column=j + 1, padx=1, pady=2)
            dvar = tk.StringVar(value=getattr(ax, f"dir_{en}"))
            ttk.Combobox(grid_w, textvariable=dvar, values=["in", "out", "inout"],
                         width=6, state="readonly").grid(row=i, column=5, padx=2, pady=2, sticky="ew")
            dvar.trace_add("write", lambda *_a, s=en, v=dvar: self._set_attr(ax, f"dir_{s}", v.get()))

        self._sep(body, "刻度线尺寸")
        self.add_spin(body, "主刻度长", ax, "major_len", 0, 30, 0.5)
        self.add_spin(body, "次刻度长", ax, "minor_len", 0, 30, 0.5)
        self.add_spin(body, "刻度线宽", ax, "tick_width", 0, 10, 0.2)

        self._sep(body, "轴线与网格")
        self.add_spin(body, "轴线宽", ax, "spine_width", 0, 10, 0.2)
        self.add_color(body, "轴线颜色", ax, "spine_color")
        self.add_check(body, "显示网格", ax, "grid")
        self.add_combo(body, "网格线型", ax, "grid_style", ["solid", "dash", "dot"])
        self.add_spin(body, "网格线宽", ax, "grid_width", 0.1, 5, 0.1)
        self.add_color(body, "网格颜色", ax, "grid_color")

        self._sep(body, "文字")
        self.add_spin(body, "刻度字号", ax, "label_size", 3, 72, 0.5)
        self.add_check(body, "刻度加粗", ax, "label_bold")
        self.add_spin(body, "刻度间距", ax, "label_pad", 0, 40, 0.5)
        self.add_spin(body, "标题字号", ax, "title_size", 3, 72, 0.5)
        self.add_check(body, "标题加粗", ax, "title_bold")
        self.add_spin(body, "标题间距", ax, "title_pad", 0, 60, 0.5)

    # ------------------------------------------------------------------ #
    # 字体页
    # ------------------------------------------------------------------ #
    def _build_font_tab(self) -> None:
        tab = self.tab_font.body
        t = self.style.text
        ttk.Label(tab, text="全局字体", style="Head.TLabel").pack(anchor="w", padx=8, pady=(8, 2))
        row = ttk.Frame(tab)
        row.pack(fill="x", padx=8, pady=2)
        ttk.Label(row, text="字体", width=12, anchor="w").pack(side="left")
        var = tk.StringVar(value=t.family)
        cb = ttk.Combobox(row, textvariable=var, values=render.available_fonts(),
                          state="readonly", width=16)
        cb.pack(side="left")

        def commit(*_a):
            t.family = var.get()
            self.schedule_render()

        cb.bind("<<ComboboxSelected>>", commit)
        self.add_color(tab, "文字颜色", t, "color")
        self.add_check(tab, "斜体", t, "italic")
        ttk.Label(tab, text="参考图使用 Arial + 加粗，全部英文标注", style="Hint.TLabel").pack(
            anchor="w", padx=12, pady=(6, 0))

        self._sep(tab, "字号快捷设置")
        srow = ttk.Frame(tab)
        srow.pack(fill="x", padx=8, pady=4)
        ttk.Label(srow, text="基准字号", width=12, anchor="w").pack(side="left")
        self._scale_font = tk.StringVar(value="11")
        ttk.Spinbox(srow, from_=4, to=48, increment=0.5, width=8,
                    textvariable=self._scale_font).pack(side="left")
        ttk.Button(srow, text="应用", width=6,
                   command=self._apply_font_scale).pack(side="left", padx=4)
        ttk.Label(tab, text="同时设置刻度、轴标题与图例字号，并保持原有比例",
                  style="Hint.TLabel", wraplength=300, justify="left").pack(anchor="w", padx=12)

    def _apply_font_scale(self) -> None:
        try:
            base = float(self._scale_font.get())
        except ValueError:
            return
        st = self.style
        st.xaxis.label_size = st.yaxis.label_size = base
        st.xaxis.title_size = st.yaxis.title_size = base + 1.0
        st.legend.size = max(4.0, base - 2.0)
        self._rebuild_all_tabs()
        self.schedule_render()

    # ------------------------------------------------------------------ #
    # 图例页
    # ------------------------------------------------------------------ #
    def _build_legend_tab(self) -> None:
        tab = self.tab_legend.body
        lg = self.style.legend
        ttk.Label(tab, text="图例", style="Head.TLabel").pack(anchor="w", padx=8, pady=(8, 2))
        self.add_check(tab, "显示图例", lg, "show")
        self.add_check(tab, "位于坐标框内", lg, "inside")
        self.add_combo(tab, "位置", lg, "loc",
                       ["upper left", "upper right", "upper center",
                        "lower left", "lower right", "lower center"])
        self.add_spin(tab, "水平偏移", lg, "x_offset", -200, 400, 0.5)
        self.add_spin(tab, "垂直偏移", lg, "y_offset", -300, 400, 0.5)
        self.add_spin(tab, "字号", lg, "size", 3, 40, 0.5)
        self.add_check(tab, "文字加粗", lg, "bold")
        self.add_spin(tab, "线段长", lg, "line_len", 0, 80, 0.5)
        self.add_spin(tab, "线文间距", lg, "handle_pad", 0, 40, 0.5)
        self.add_spin(tab, "行距", lg, "row_pad", 0, 30, 0.5)
        self.add_spin(tab, "列数", lg, "ncol", 0, 6, 1)
        ttk.Label(tab, text="列数填 0 表示自动分列", style="Hint.TLabel").pack(anchor="w", padx=12)
        self.add_check(tab, "倒序显示", lg, "reverse")
        self.add_check(tab, "图例边框", lg, "frame")
        self.add_color(tab, "边框颜色", lg, "frame_color")

    # ------------------------------------------------------------------ #
    # 曲线页
    # ------------------------------------------------------------------ #
    def _build_series_tab(self) -> None:
        self.series_body = ttk.Frame(self.tab_series.body)
        self.series_body.pack(fill="both", expand=True)
        self._refresh_series_tab()

    def _refresh_series_tab(self) -> None:
        body = getattr(self, "series_body", None)
        if body is None:
            return
        for w in body.winfo_children():
            w.destroy()
        items = [s for s in self.series_list if s.key in self.checked]
        ttk.Label(body, text=f"已选 {len(items)} 条曲线", style="Head.TLabel").pack(
            anchor="w", padx=8, pady=(8, 2))
        bar = ttk.Frame(body)
        bar.pack(fill="x", padx=8, pady=(0, 4))
        ttk.Button(bar, text="线型轮换", width=10,
                   command=self.cycle_line_styles).pack(side="left")
        ttk.Button(bar, text="全部实线", width=10,
                   command=self.reset_line_styles).pack(side="left", padx=4)
        if not items:
            ttk.Label(body, text="在左侧勾选曲线后，可在这里单独调整颜色、线宽与图例名称",
                      style="Hint.TLabel", wraplength=300, justify="left").pack(anchor="w", padx=8, pady=6)
            return

        head = ttk.Frame(body)
        head.pack(fill="x", padx=8, pady=(2, 0))
        ttk.Label(head, text="色", width=3, style="Hint.TLabel").pack(side="left")
        ttk.Label(head, text="图例名称", width=14, style="Hint.TLabel").pack(side="left")
        ttk.Label(head, text="线宽", width=5, style="Hint.TLabel").pack(side="left")
        ttk.Label(head, text="线型", width=8, style="Hint.TLabel").pack(side="left")

        for s in items:
            ss = self.style.ensure_one(s.key, s.label)
            row = ttk.Frame(body)
            row.pack(fill="x", padx=8, pady=1)

            def pick(key=s.key) -> None:
                st = self.style.series[key]
                _rgb, code = colorchooser.askcolor(color=st.color, parent=self)
                if code:
                    st.color = code
                    self.schedule_render()
                    self._refresh_series_tab()

            tk.Button(row, width=2, bg=ss.color, relief="flat", bd=1, command=pick).pack(side="left")

            nvar = tk.StringVar(value=ss.label)

            def commit_name(*_a, key=s.key, v=nvar):
                self.style.series[key].label = v.get()
                self.schedule_render()

            ent = ttk.Entry(row, textvariable=nvar, width=14)
            ent.pack(side="left", padx=3)
            ent.bind("<Return>", commit_name)
            ent.bind("<FocusOut>", commit_name)

            wvar = tk.StringVar(value=_fmt(ss.width))

            def commit_w(*_a, key=s.key, v=wvar):
                try:
                    self.style.series[key].width = float(v.get())
                except ValueError:
                    return
                self.schedule_render()

            sp = ttk.Spinbox(row, from_=0.2, to=10, increment=0.2, width=4, textvariable=wvar)
            sp.pack(side="left", padx=2)
            sp.bind("<Return>", commit_w)
            sp.bind("<FocusOut>", commit_w)

            svar = tk.StringVar(value=ss.style)
            cb = ttk.Combobox(row, textvariable=svar, values=list(render.DASH_PATTERNS),
                              state="readonly", width=8)
            cb.pack(side="left", padx=2)

            def commit_s(*_a, key=s.key, v=svar):
                self.style.series[key].style = v.get()
                self.schedule_render()

            cb.bind("<<ComboboxSelected>>", commit_s)

    def cycle_line_styles(self) -> None:
        """按勾选顺序循环分配 实线/虚线/点线/点划线，配色相近时也能区分。"""
        order = ["solid", "dash", "dot", "dashdot"]
        items = [s for s in self.series_list if s.key in self.checked]
        for i, s in enumerate(items):
            self.style.ensure_one(s.key, s.label).style = order[i % len(order)]
        self._refresh_series_tab()
        self.schedule_render()

    def reset_line_styles(self) -> None:
        for s in self.series_list:
            if s.key in self.checked:
                self.style.ensure_one(s.key, s.label).style = "solid"
        self._refresh_series_tab()
        self.schedule_render()

    # ------------------------------------------------------------------ #
    # 数据加载
    # ------------------------------------------------------------------ #
    def pick_folder(self) -> None:
        path = filedialog.askdirectory(initialdir=self.path_var.get() or os.getcwd(),
                                       title="选择包含拉伸测试数据的文件夹")
        if path:
            self.path_var.set(path)
            self.load_folder(path)

    def load_folder(self, path: str, silent: bool = False) -> None:
        if not path or not os.path.isdir(path):
            if not silent:
                messagebox.showwarning("路径无效", f"文件夹不存在：\n{path}")
            return
        rule = self.rule_var.get()          # 必须在主线程读取 Tk 变量
        self.status_var.set(f"正在扫描：{path} ……")
        self.update_idletasks()

        def worker() -> None:
            try:
                res = dataio.scan_tables(path, prefer=rule)
                self._q.put(("tables", res))
            except Exception as exc:         # pragma: no cover
                self._q.put(("error", exc))

        threading.Thread(target=worker, daemon=True).start()

    def _poll_queue(self) -> None:
        try:
            while True:
                kind, payload = self._q.get_nowait()
                if kind in ("tables", "scan"):
                    self._apply_tables(payload)
                else:
                    self.status_var.set(f"读取失败：{payload}")
                    messagebox.showerror("读取失败", str(payload))
        except queue.Empty:
            pass
        self.after(80, self._poll_queue)

    # ------------------------------------------------------------------ #
    # 扫描结果 → 表 → 曲线
    # ------------------------------------------------------------------ #
    def _apply_tables(self, res) -> None:
        self.tables = list(getattr(res, "tables", []) or [])
        self._scan_skipped = list(getattr(res, "skipped", []) or [])
        self._scan_warnings = list(getattr(res, "warnings", []) or [])
        self._col_catalog = dataio.column_catalog(self.tables)
        self._refresh_col_catalog()
        self._rebuild_series()

    def _refresh_col_catalog(self) -> None:
        values = [c[0] for c in self._col_catalog]
        for box in (getattr(self, "xcol_box", None), getattr(self, "ycol_box", None)):
            if box is not None:
                box.configure(values=values)
        if not self._col_catalog:
            self.col_hint.configure(text="（没有扫描到可绘制的数值列）")
            return
        cnt: dict[str, int] = {}
        for t in self.tables:
            for c in t.columns:
                if c.index in t.data:
                    h = (c.header or "").strip()
                    if h:
                        cnt[h] = cnt.get(h, 0) + 1
        lines = [f"· {head} × {cnt.get(head, 1)}" for head, _lbl, _k in self._col_catalog]
        if len(lines) > 14:
            lines = lines[:14] + [f"… 还有 {len(self._col_catalog) - 14} 个列名"]
        self.col_hint.configure(
            text=(f"{len(self.tables)} 个数据表，第一行共 {len(self._col_catalog)} 个列名\n"
                  + "\n".join(lines)))
        # 预设里的「量类型」按当前文件夹落实成真实表头，再把槽位名刷新成原文
        self._resolve_columns()
        try:
            self._refresh_slot_box()
            self._sync_var_widgets()
        except Exception:                        # noqa: BLE001
            pass

    def _apply_mapping(self) -> None:
        """X/Y 映射变了：同步轴标题、刷新曲线（不重新读文件）。"""
        self._rebuild_series()

    def _rebuild_series(self) -> None:
        series, warns = dataio.build_series(self.tables, self.xmap)
        self.series_list = series
        keys = [s.key for s in series]
        self.checked &= set(keys)

        st = self.style
        st.xaxis.label = self.xmap.x_axis_label()
        st.yaxis.label = self.xmap.y_axis_label()
        try:
            self._rebuild_axis_tab()
        except Exception:                        # 界面还没建好时忽略
            pass

        self._fill_tree()
        if not self.checked and series:
            if len(self.groups) > 1:
                self.checked = {ks[0] for ks in self.groups.values() if ks}
            else:
                self.checked = set(keys)
        self._sync_tree()
        self._refresh_series_tab()
        self.schedule_render(0)
        self._update_size_hint()

        warn = (warns + self._scan_warnings)[0] if (warns or self._scan_warnings) else ""
        extra = f" · {warn}" if warn else ""
        if series:
            self.status_var.set(
                f"已载入 {len(series)} 条曲线（{len(self.groups)} 个数据源），"
                f"当前显示 {len(self.checked)} 条 · "
                f"X={V.kind(self.xmap.x_kind).label} / Y={V.kind(self.xmap.y_kind).label}{extra}")
        else:
            self.status_var.set(warn or "没有可绘制的曲线")

    def _fill_tree(self) -> None:
        cur = {self._iid_group[i] for i in self.tree.get_children()
               if i in self._iid_group and self.tree.item(i, "open")}
        self.tree.delete(*self.tree.get_children())
        self._iid_key.clear()
        self._iid_group.clear()
        self.groups.clear()
        for s in self.series_list:
            self.groups.setdefault(s.group or s.label, []).append(s.key)
        self.style.ensure_series([s.key for s in self.series_list],
                                 {s.key: s.label for s in self.series_list})
        for gname, keys in self.groups.items():
            gid = f"g::{gname}"
            self._iid_group[gid] = gname
            self.tree.insert("", "end", iid=gid, text=gname,
                             open=(gname in cur) if cur else True,
                             values=(PARTIAL, f"{len(keys)} 条", ""), tags=("group",))
            for key in keys:
                s = next((x for x in self.series_list if x.key == key), None)
                if s is None:
                    continue
                iid = f"k::{key}"
                self._iid_key[iid] = key
                self.tree.insert(gid, "end", iid=iid, text="",
                                 values=(UNCHECKED, s.label, _fmt_num(s.y_max)), tags=("curve",))
        self.tree.tag_configure("group", font=(UI_FONT, 9, "bold"))

    def _sync_tree(self) -> None:
        for iid, key in self._iid_key.items():
            vals = list(self.tree.item(iid, "values"))
            if vals:
                vals[0] = CHECKED if key in self.checked else UNCHECKED
                self.tree.item(iid, values=vals)
        for gid, gname in self._iid_group.items():
            keys = self.groups.get(gname, [])
            on = sum(1 for k in keys if k in self.checked)
            mark = CHECKED if keys and on == len(keys) else (PARTIAL if on else UNCHECKED)
            vals = list(self.tree.item(gid, "values"))
            if vals:
                vals[0] = mark
                self.tree.item(gid, values=vals)
        self.count_label.configure(text=f"{len(self.series_list)} 条曲线")

    def _on_tree_click(self, event):
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        col = self.tree.identify_column(event.x)
        region = self.tree.identify_region(event.x, event.y)
        if col == "#1" or (region == "tree" and iid in self._iid_group):
            self._toggle_one(iid)
            return "break"

    def _toggle_one(self, iid: str) -> None:
        if iid in self._iid_key:
            key = self._iid_key[iid]
            if key in self.checked:
                self.checked.discard(key)
            else:
                self.checked.add(key)
        elif iid in self._iid_group:
            keys = self.groups.get(self._iid_group[iid], [])
            all_on = all(k in self.checked for k in keys)
            for k in keys:
                if all_on:
                    self.checked.discard(k)
                else:
                    self.checked.add(k)
        self._sync_tree()
        self._refresh_series_tab()
        self.schedule_render()

    def _toggle_selected(self, _e=None):
        for iid in self.tree.selection():
            self._toggle_one(iid)
        return "break"

    def _check_all(self, on: bool) -> None:
        self.checked = {s.key for s in self.series_list} if on else set()
        self._sync_tree()
        self._refresh_series_tab()
        self.schedule_render()

    def invert_checked(self) -> None:
        all_keys = {s.key for s in self.series_list}
        self.checked = all_keys - self.checked
        self._sync_tree()
        self._refresh_series_tab()
        self.schedule_render()

    # ------------------------------------------------------------------ #
    # 渲染
    # ------------------------------------------------------------------ #
    def _on_wheel(self, event) -> None:
        try:
            w = self.winfo_containing(event.x_root, event.y_root)
        except Exception:
            return
        while w is not None and not hasattr(w, "_scroll_owner"):
            w = getattr(w, "master", None)
        if w is None:
            return
        w._scroll_owner.scroll(-1 if event.delta > 0 else 1)

    def schedule_render(self, delay: int = 90) -> None:
        if self._render_job is not None:
            try:
                self.after_cancel(self._render_job)
            except Exception:
                pass
        self._render_job = self.after(delay, self.render_preview)

    def _make_figure(self, max_points: int | None = None):
        st = self.style
        ps = []
        for s in self.series_list:
            if s.key not in self.checked:
                continue
            ss = st.series.get(s.key)
            if ss is None:
                continue
            x, y = s.x, s.y
            if getattr(ss, "smooth", 0) and int(ss.smooth) > 1:
                x, y = render.smooth_xy(x, y, int(ss.smooth))
            if max_points:
                x, y = render.decimate_xy(x, y, max_points)
            ps.append(render.PlotSeries(ss.label or s.label, ss.color, ss.width, ss.style,
                                        ss.alpha, x, y, ss.marker, ss.marker_size))
        return render.Figure(st, ps, title=st.figure.title)

    def render_preview(self) -> None:
        self._render_job = None
        t0 = time.time()
        cw = max(360, self.canvas.winfo_width() - 10)
        ch = max(260, self.canvas.winfo_height() - 10)
        f = self.style.figure
        if not self.checked:
            self.canvas.delete("all")
            self.canvas.create_text(cw // 2, ch // 2, text="请在左侧勾选至少一条曲线",
                                    fill="#9CA3AF", font=(UI_FONT, 12))
            self._photo = None
            self.status_var.set("当前未显示任何曲线")
            return
        dpi = min(cw / f.width_in, ch / f.height_in)
        if self.preview_quality.get() == "精细":
            dpi *= 2.0
        dpi = max(30.0, dpi)
        budget = 20000 if self.preview_quality.get() == "精细" else max(1200, int(cw * 2.5))
        try:
            img = render.render_image(self._make_figure(max_points=budget), dpi=dpi)
        except Exception as exc:            # pragma: no cover
            self.status_var.set(f"渲染失败：{exc}")
            traceback.print_exc()
            return
        if img.width > cw or img.height > ch:
            ratio = min(cw / img.width, ch / img.height)
            img = img.resize((max(1, int(img.width * ratio)), max(1, int(img.height * ratio))),
                             Image.LANCZOS)
        self._photo = ImageTk.PhotoImage(img)
        self.canvas.delete("all")
        self.canvas.create_image(cw // 2, ch // 2, image=self._photo)
        final_w = int(round(f.width_in * f.dpi))
        final_h = int(round(f.height_in * f.dpi))
        self.status_var.set(f"预览已更新 · {len(self.checked)} 条曲线 · 导出尺寸 "
                            f"{final_w}×{final_h} px · {int((time.time() - t0) * 1000)} ms")

    # ------------------------------------------------------------------ #
    # 样式存取
    # ------------------------------------------------------------------ #
    def save_style(self) -> None:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        path = filedialog.asksaveasfilename(
            title="保存样式模板", defaultextension=".json", initialdir=CONFIG_DIR,
            initialfile="strainplot_style.json", filetypes=[("样式模板", "*.json")])
        if not path:
            return
        try:
            self.style.save(path)
            self.status_var.set(f"样式已保存：{path}")
        except Exception as exc:
            messagebox.showerror("保存失败", str(exc))

    def load_style(self) -> None:
        path = filedialog.askopenfilename(title="载入样式模板", initialdir=CONFIG_DIR,
                                          filetypes=[("样式模板", "*.json"), ("全部文件", "*.*")])
        if not path:
            return
        try:
            self.style = Style.load(path)
            self.style.ensure_series([s.key for s in self.series_list],
                                     {s.key: s.label for s in self.series_list})
            self._rebuild_all_tabs()
            self.schedule_render()
            self.status_var.set(f"已载入样式：{path}")
        except Exception as exc:
            messagebox.showerror("载入失败", str(exc))

    def _rebuild_all_tabs(self) -> None:
        for tab, builder in ((self.tab_fig, self._build_figure_tab),
                             (self.tab_axis, self._build_axis_tab),
                             (self.tab_font, self._build_font_tab),
                             (self.tab_legend, self._build_legend_tab)):
            for w in tab.body.winfo_children():
                w.destroy()
            builder()
        self._refresh_series_tab()
        self._update_size_hint()

    def open_export(self) -> None:
        ExportDialog(self)


# --------------------------------------------------------------------------- #
# 导出对话框
# --------------------------------------------------------------------------- #
class ExportDialog(tk.Toplevel):
    def __init__(self, app: App) -> None:
        super().__init__(app)
        self.app = app
        self.title("导出图片")
        self.geometry("580x540")
        self.configure(bg=BG)
        self.transient(app)

        f = app.style.figure
        body = ttk.Frame(self, style="Card.TFrame", padding=12)
        body.pack(fill="both", expand=True, padx=10, pady=10)

        self.out_var = tk.StringVar(value=os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "输出"))
        self.fmt_var = tk.StringVar(value="PNG")
        self.dpi_var = tk.StringVar(value=str(int(f.dpi)))
        self.group_var = tk.BooleanVar(value=False)
        self.only_checked = tk.BooleanVar(value=True)

        ttk.Label(body, text="输出文件夹", width=10, anchor="w").grid(row=0, column=0, sticky="w", pady=3)
        ttk.Entry(body, textvariable=self.out_var).grid(row=0, column=1, sticky="ew", pady=3)
        ttk.Button(body, text="…", width=3,
                   command=lambda: self.out_var.set(filedialog.askdirectory() or self.out_var.get())
                   ).grid(row=0, column=2, padx=3)

        ttk.Label(body, text="格式", width=10, anchor="w").grid(row=1, column=0, sticky="w", pady=3)
        ttk.Combobox(body, textvariable=self.fmt_var, values=["PNG", "SVG", "TIFF", "PDF", "JPG"],
                     state="readonly", width=8).grid(row=1, column=1, sticky="w", pady=3)

        ttk.Label(body, text="dpi", width=10, anchor="w").grid(row=2, column=0, sticky="w", pady=3)
        ttk.Combobox(body, textvariable=self.dpi_var, values=["150", "300", "600", "1200"],
                     width=8).grid(row=2, column=1, sticky="w", pady=3)

        ttk.Checkbutton(body, text="每个数据源分别导出为一张图", variable=self.group_var).grid(
            row=3, column=0, columnspan=3, sticky="w", pady=3)
        ttk.Checkbutton(body, text="只导出当前勾选的曲线", variable=self.only_checked).grid(
            row=4, column=0, columnspan=3, sticky="w")

        self.log = tk.Text(body, height=12, wrap="word", font=(UI_FONT, 8))
        self.log.grid(row=5, column=0, columnspan=3, sticky="nsew", pady=(8, 4))
        body.columnconfigure(1, weight=1)
        body.rowconfigure(5, weight=1)

        btns = ttk.Frame(body)
        btns.grid(row=6, column=0, columnspan=3, sticky="e")
        ttk.Button(btns, text="关闭", command=self.destroy).pack(side="right", padx=4)
        ttk.Button(btns, text="开始导出", command=self.run).pack(side="right")

    def _series_keys(self) -> list:
        if self.only_checked.get():
            return [s.key for s in self.app.series_list if s.key in self.app.checked]
        return [s.key for s in self.app.series_list]

    def run(self) -> None:
        out_dir = self.out_var.get()
        os.makedirs(out_dir, exist_ok=True)
        ext = self.fmt_var.get().lower()
        try:
            dpi = int(float(self.dpi_var.get()))
        except ValueError:
            dpi = int(self.app.style.figure.dpi)
        self.log.delete("1.0", "end")
        keys = self._series_keys()
        if not keys:
            self.log.insert("end", "没有可导出的曲线。\n")
            return
        groups: dict[str, list] = {}
        for s in self.app.series_list:
            if s.key in keys:
                groups.setdefault(s.group or s.label, []).append(s.key)
        try:
            if self.group_var.get():
                for gname, gkeys in groups.items():
                    stem = os.path.splitext(gname)[0]
                    safe = re.sub(r'[\\/:*?"<>|]+', "_", stem).strip() or "figure"
                    path = os.path.join(out_dir, f"{safe}.{ext}")
                    self._export(path, dpi, set(gkeys))
                    self.log.insert("end", f"OK  {path}\n")
            else:
                path = os.path.join(out_dir, f"strain_curves.{ext}")
                self._export(path, dpi, set(keys))
                self.log.insert("end", f"OK  {path}\n")
        except Exception as exc:
            self.log.insert("end", f"FAIL  {exc}\n")
        self.log.see("end")

    def _export(self, path: str, dpi: int, keys: set) -> None:
        app = self.app
        saved = app.checked
        try:
            app.checked = set(keys)
            render.save_figure(app._make_figure(), path, dpi=dpi)
        finally:
            app.checked = saved


# --------------------------------------------------------------------------- #
def main() -> None:
    try:
        app = App()
        app.mainloop()
    except Exception:
        tb = traceback.format_exc()
        try:
            log = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "error.log")
            with open(log, "w", encoding="utf-8") as fh:
                fh.write(tb)
        except Exception:
            pass
        try:
            messagebox.showerror("StrainPlot 启动失败", tb[-1500:])
        except Exception:
            print(tb)


if __name__ == "__main__":
    main()
