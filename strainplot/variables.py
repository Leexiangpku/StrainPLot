"""变量词典与常见 X–Y 组合预设
=================================

v2 起，程序不再把"应变 → 应力"写死，而是把所有可绘制的物理量抽象成 :class:`Kind`，
每条曲线的 X / Y 从表的列里按"量类型"（kind）自动匹配，也可以自定义任意两列。

一个 :class:`Kind` 提供三样东西：

* ``id``     内部标识（存进样式模板 JSON）
* ``label``  英文轴标题（Arial，全英文）
* ``unit``   默认单位；``aliases`` 用于从表头/单位行猜测列的类型

:data:`PRESETS` 收录化学 / 高分子 / 材料 / 物理里最常用的 X–Y 组合，界面里按分类分组显示。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


# --------------------------------------------------------------------------- #
# 物理量
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Kind:
    id: str
    label: str
    unit: str
    aliases: tuple[str, ...] = ()
    group: str = "其他"
    desc: str = ""


KINDS: tuple[Kind, ...] = (
    # ---------------- 力学 ----------------
    Kind("strain", "Strain", "%",
         ("应变", "strain", "elongation", "extension", "拉伸应变", "工程应变", "变形"),
         "力学", "拉伸/压缩应变"),
    Kind("stress", "Stress", "kPa",
         ("应力", "stress", "拉伸应力", "真应力", "断裂应力", "σ"),
         "力学", "拉伸/压缩应力"),
    Kind("load", "Load", "N",
         ("载荷", "负荷", "力", "load", "force", "拉伸力", "力值"),
         "力学", "力传感器读数"),
    Kind("displacement", "Displacement", "mm",
         ("位移", "displacement", "extension", "变形量", "行程", "横梁"),
         "力学", "横梁位移"),
    Kind("modulus", "Modulus", "MPa",
         ("模量", "modulus", "young", "储能模量", "损耗模量", "g'", "g''", "g*",
          "storage", "loss", "e'", "e''"),
         "力学", "杨氏/储能/损耗模量"),
    Kind("strain_rate", "Strain rate", "s⁻¹",
         ("应变速率", "strainrate", "拉伸速率"), "力学", "加载速率"),
    Kind("pressure", "Pressure", "MPa",
         ("压力", "pressure", "压差"), "力学", "压力"),
    Kind("toughness", "Toughness", "MJ/m³",
         ("韧性", "toughness", "断裂能", "功"), "力学", "断裂韧性"),
    Kind("contact_angle", "Contact angle", "°",
         ("接触角", "contactangle", "润湿角"), "力学", "润湿性"),

    # ---------------- 时间 / 温度 ----------------
    Kind("time", "Time", "s",
         ("时间", "time", "测试时间", "t(s)"), "时间温度", "时间轴"),
    Kind("temperature", "Temperature", "°C",
         ("温度", "temperature", "temp", "t(℃)"), "时间温度", "程序升温"),
    Kind("cycle", "Cycle number", "",
         ("循环", "cycle", "圈数", "次"), "时间温度", "循环序号"),

    # ---------------- 热分析 ----------------
    Kind("mass", "Mass", "%",
         ("质量", "mass", "weight", "重量", "失重", "残留", "tg", "tga", "w%"),
         "热分析", "TGA 质量 / 失重"),
    Kind("heat_flow", "Heat flow", "mW/mg",
         ("热流", "heatflow", "dsc", "热焓"), "热分析", "DSC 热流"),
    Kind("heat_capacity", "Heat capacity", "J/(g·K)",
         ("热容", "heatcapacity", "cp"), "热分析", "比热容"),

    # ---------------- 光谱 ----------------
    Kind("wavelength", "Wavelength", "nm",
         ("波长", "wavelength", "λ", "nm"), "光谱", "UV-Vis / PL 波长"),
    Kind("wavenumber", "Wavenumber", "cm⁻¹",
         ("波数", "wavenumber", "拉曼位移", "ramanshift"), "光谱", "FTIR / Raman 波数"),
    Kind("absorbance", "Absorbance", "",
         ("吸光度", "absorbance", "abs", "od", "光密度"), "光谱", "UV-Vis 吸光度"),
    Kind("transmittance", "Transmittance", "%",
         ("透过率", "transmittance", "transmission", "透光率"), "光谱", "透过率"),
    Kind("intensity", "Intensity", "a.u.",
         ("强度", "intensity", "counts", "cps", "信号强度"), "光谱", "XRD / Raman 强度"),
    Kind("two_theta", "2θ", "°",
         ("2theta", "2θ", "衍射角", "theta"), "光谱", "XRD 衍射角"),
    Kind("emission", "Emission", "a.u.",
         ("发射", "emission", "pl", "荧光"), "光谱", "荧光发射"),

    # ---------------- 流变 ----------------
    Kind("frequency", "Frequency", "rad/s",
         ("频率", "frequency", "ω", "角频率", "hz"), "流变", "频率扫描"),
    Kind("viscosity", "Viscosity", "Pa·s",
         ("黏度", "粘度", "viscosity", "eta", "η"), "流变", "剪切黏度"),
    Kind("shear_rate", "Shear rate", "s⁻¹",
         ("剪切速率", "shearrate", "γ̇"), "流变", "剪切速率"),
    Kind("shear_stress", "Shear stress", "Pa",
         ("剪切应力", "shearstress", "τ"), "流变", "剪切应力"),

    # ---------------- 电化学 ----------------
    Kind("potential", "Potential", "V",
         ("电位", "电势", "potential", "voltage", "电压", "e(v)"), "电化学", "电位 / 电压"),
    Kind("current", "Current", "A",
         ("电流", "current", "i(a)", "amperage"), "电化学", "电流"),
    Kind("capacity", "Capacity", "mAh/g",
         ("容量", "capacity", "比容量"), "电化学", "比容量"),
    Kind("coulombic", "Coulombic efficiency", "%",
         ("库仑效率", "coulombic", "ce"), "电化学", "库仑效率"),
    Kind("conductivity", "Conductivity", "S/m",
         ("电导率", "conductivity", "σ(s/m)"), "电化学", "离子电导率"),
    Kind("resistance", "Resistance", "Ω",
         ("电阻", "resistance", "阻抗", "impedance", "z'", "z''"), "电化学", "电阻 / 阻抗"),

    # ---------------- 化学 / 其他 ----------------
    Kind("concentration", "Concentration", "mg/mL",
         ("浓度", "concentration", "c(mg", "含量", "添加量", "wt%", "质量分数"),
         "化学", "浓度 / 配比"),
    Kind("ph", "pH", "",
         ("ph", "酸碱度"), "化学", "pH 值"),
    Kind("volume", "Volume", "mL",
         ("体积", "volume", "滴加", "进样"), "化学", "体积"),
    Kind("conversion", "Conversion", "%",
         ("转化率", "conversion", "产率", "yield"), "化学", "反应转化率"),
    Kind("angle", "Angle", "°",
         ("角度", "angle", "衍射角", "散射角"), "化学", "角度"),
    Kind("signal", "Signal", "a.u.",
         ("信号", "signal", "response", "响应值", "电流响应"), "化学", "一般响应信号"),
    Kind("swelling", "Swelling ratio", "g/g",
         ("溶胀", "swelling", "吸水率", "含水率"), "化学", "溶胀比"),
    Kind("plain", "Value", "",
         ("value", "数值", "y"), "其他", "无类型（任意数值列）"),
)

BY_ID: dict[str, Kind] = {k.id: k for k in KINDS}
CUSTOM = "custom"          # 自定义列：直接指定列名


def kind(kid: str) -> Kind:
    return BY_ID.get(kid, BY_ID["plain"])


def axis_label(kid: str, unit: str | None = None, custom: str = "") -> str:
    """生成轴标题：``Strain (%)``。单位为空则只留量名。"""
    if kid == CUSTOM and custom:
        return f"{custom} ({unit})" if unit else custom
    k = kind(kid)
    u = k.unit if unit is None else unit
    return f"{k.label} ({u})" if u else k.label


def identify(header: str, unit: str = "") -> tuple[str, int]:
    """从表头（可选单位）猜测量类型，返回 ``(kind_id, score)``。"""
    h = _norm(header)
    u = _norm(unit)
    best, best_score = "plain", 0
    for k in KINDS:
        score = 0
        for alias in k.aliases:
            a = _norm(alias)
            if not a:
                continue
            if h == a:
                score = max(score, 100 + len(a))
            elif a in h:
                score = max(score, 40 + len(a))
            elif h and h in a and len(h) >= 2:
                score = max(score, 20 + len(h))
        if score and u and _norm(k.unit) and _norm(k.unit) in u:
            score += 8
        if score > best_score:
            best, best_score = k.id, score
    return best, best_score


def _norm(text) -> str:
    s = str(text or "").lower()
    for ch in " \t\r\n_-·.:,;()（）[]【】":
        s = s.replace(ch, "")
    return s


# --------------------------------------------------------------------------- #
# 常见组合
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Preset:
    id: str
    name: str            # 界面显示（中英混排，短）
    x: str               # X 量 kind id
    y: str               # Y 量 kind id
    group: str = "力学"
    note: str = ""

    @property
    def x_label(self) -> str:
        return kind(self.x).label

    @property
    def y_label(self) -> str:
        return kind(self.y).label


PRESETS: tuple[Preset, ...] = (
    # 力学
    Preset("tensile", "拉伸 · 应变–应力", "strain", "stress", "力学", "Instron / 万能试验机"),
    Preset("compress", "压缩 · 位移–载荷", "displacement", "load", "力学", "压缩 / 三点弯"),
    Preset("relax", "应力松弛 · 时间–应力", "time", "stress", "力学", "松弛 / 蠕变"),
    Preset("creep", "蠕变 · 时间–应变", "time", "strain", "力学", "恒载蠕变"),
    Preset("cyclic", "循环 · 时间–应力", "time", "stress", "力学", "循环加载"),
    Preset("modulus_strain", "振幅扫描 · 应变–模量", "strain", "modulus", "力学", "应变扫描"),
    Preset("rheology_freq", "频率扫描 · 频率–模量", "frequency", "modulus", "力学", "G′ / G″"),
    Preset("flow_curve", "流动曲线 · 剪切速率–黏度", "shear_rate", "viscosity", "力学", "稳态剪切"),

    # 热分析
    Preset("tga", "TGA · 温度–质量", "temperature", "mass", "热分析", "失重曲线"),
    Preset("dsc", "DSC · 温度–热流", "temperature", "heat_flow", "热分析", "熔融 / 结晶"),
    Preset("dma", "DMA · 温度–模量", "temperature", "modulus", "热分析", "温度扫描"),
    Preset("isothermal", "等温 · 时间–质量", "time", "mass", "热分析", "恒温失重"),

    # 光谱
    Preset("uvvis", "UV-Vis · 波长–吸光度", "wavelength", "absorbance", "光谱", "吸收光谱"),
    Preset("uvvis_t", "UV-Vis · 波长–透过率", "wavelength", "transmittance", "光谱", "透射光谱"),
    Preset("ftir", "FTIR · 波数–透过率", "wavenumber", "transmittance", "光谱", "红外光谱"),
    Preset("raman", "Raman · 波数–强度", "wavenumber", "intensity", "光谱", "拉曼光谱"),
    Preset("xrd", "XRD · 2θ–强度", "two_theta", "intensity", "光谱", "衍射谱"),
    Preset("pl", "PL · 波长–发射强度", "wavelength", "emission", "光谱", "荧光光谱"),

    # 电化学
    Preset("cv", "CV · 电位–电流", "potential", "current", "电化学", "循环伏安"),
    Preset("gcd", "充放电 · 时间–电压", "time", "potential", "电化学", "恒流充放电"),
    Preset("cap_v", "充放电 · 容量–电压", "capacity", "potential", "电化学", "容量-电压"),
    Preset("cycle_cap", "循环性能 · 圈数–容量", "cycle", "capacity", "电化学", "循环寿命"),
    Preset("eis", "EIS · Z′–Z″", "resistance", "resistance", "电化学", "阻抗谱（需自行改名）"),

    # 化学
    Preset("beer", "标准曲线 · 浓度–吸光度", "concentration", "absorbance", "化学", "Beer–Lambert"),
    Preset("titration", "滴定 · 体积–电位", "volume", "potential", "化学", "电位滴定"),
    Preset("ph_cond", "pH–电导率", "ph", "conductivity", "化学", "酸碱响应"),
    Preset("swell", "溶胀 · 时间–溶胀比", "time", "swelling", "化学", "溶胀动力学"),
    Preset("contact", "润湿 · 浓度–接触角", "concentration", "contact_angle", "化学", "润湿性"),
    Preset("custom", "自定义（任选两列）", "plain", "plain", "自定义", "手动指定 X / Y 列"),
)

PRESET_BY_ID: dict[str, Preset] = {p.id: p for p in PRESETS}
PRESET_GROUPS: tuple[str, ...] = ("力学", "热分析", "光谱", "电化学", "化学", "自定义")


def preset_labels() -> list[str]:
    """给下拉框用的分组标签：``力学 / 拉伸 · 应变–应力``。"""
    return [f"{p.group} / {p.name}" for p in PRESETS]


def preset_from_label(label: str) -> Preset:
    for p in PRESETS:
        if label in (f"{p.group} / {p.name}", p.name):
            return p
    return PRESET_BY_ID["tensile"]


DEFAULT_PRESET = "tensile"
