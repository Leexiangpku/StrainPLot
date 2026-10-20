"""生成应用图标：icon.png / icon.ico / icon.icns。

图形语言与程序输出一致：白底、深灰轴框、两条不同颜色的应力-应变曲线。
"""
from __future__ import annotations

import struct
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent
S = 1024
BG = "#FFFFFF"
INK = "#333333"
C1 = "#56BED7"
C2 = "#F3A085"


def draw(size: int) -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # 圆角底板
    r = int(S * 0.22)
    d.rounded_rectangle([0, 0, S - 1, S - 1], radius=r, fill=BG, outline="#E3E6EB", width=int(S * 0.012))

    # 坐标框
    x0, y0, x1, y1 = int(S * 0.20), int(S * 0.17), int(S * 0.82), int(S * 0.80)
    lw = int(S * 0.030)
    d.rectangle([x0, y0, x1, y1], outline=INK, width=lw)

    # 刻度
    tl = int(S * 0.035)
    for i in range(1, 4):
        x = x0 + (x1 - x0) * i / 4
        d.line([(x, y0), (x, y0 + tl)], fill=INK, width=int(lw * 0.8))
        d.line([(x, y1 - tl), (x, y1)], fill=INK, width=int(lw * 0.8))
        y = y0 + (y1 - y0) * i / 4
        d.line([(x0, y), (x0 + tl, y)], fill=INK, width=int(lw * 0.8))
        d.line([(x1 - tl, y), (x1, y)], fill=INK, width=int(lw * 0.8))

    def curve(pts, color, width):
        xy = [(x0 + (x1 - x0) * px, y1 - (y1 - y0) * py) for px, py in pts]
        d.line(xy, fill=color, width=width, joint="curve")

    # 两条应力-应变曲线（蓝线到峰值后断裂骤降，橙线继续爬升）
    curve([(0.04, 0.02), (0.34, 0.28), (0.66, 0.72), (0.94, 1.00)], C2, int(S * 0.038))
    curve([(0.04, 0.02), (0.26, 0.18), (0.46, 0.40), (0.58, 0.52),
           (0.58, 0.12)], C1, int(S * 0.038))

    if size != S:
        img = img.resize((size, size), Image.LANCZOS)
    return img


def main() -> None:
    base = draw(S)
    base.save(OUT / "icon.png")

    sizes = [256, 128, 64, 48, 32, 16]
    imgs = [draw(n) for n in sizes]
    imgs[0].save(OUT / "icon.ico", sizes=[(n, n) for n in sizes])

    # ICNS：直接嵌入 PNG 数据（ic07=128, ic08=256, ic09=512, ic10=1024）
    chunks = []
    for kind, n in (("ic07", 128), ("ic08", 256), ("ic09", 512), ("ic10", 1024)):
        png = draw(n)
        buf = Path(OUT / f".tmp_{kind}.png")
        png.save(buf)
        data = buf.read_bytes()
        buf.unlink()
        chunks.append(kind.encode("ascii") + struct.pack(">I", len(data) + 8) + data)
    body = b"".join(chunks)
    (OUT / "icon.icns").write_bytes(b"icns" + struct.pack(">I", len(body) + 8) + body)
    print("icons ok", (OUT / "icon.ico").stat().st_size, (OUT / "icon.icns").stat().st_size)


if __name__ == "__main__":
    main()
