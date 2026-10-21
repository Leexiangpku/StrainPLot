"""PyInstaller 入口：冻结后直接调用图形界面主函数。

另外支持一个无界面的自检模式，用来验证打包后的 .app 里
"读数据 → 建图 → 出图" 整条链路是否正常：

    StrainPlot.app/Contents/MacOS/StrainPlot --selftest [数据目录] [输出 png]

窗口化打包时 stdout 可能为空，所以自检结果同时写到 <输出 png>.log。
"""

import os
import sys
import tempfile
import traceback


def _selftest(argv: list[str]) -> int:
    lines: list[str] = []

    def say(msg: str) -> None:
        lines.append(str(msg))
        try:
            print(msg, flush=True)
        except Exception:          # 窗口化 app 里 stdout 可能为 None
            pass

    out = argv[1] if len(argv) > 1 else os.path.join(tempfile.gettempdir(),
                                                     "strainplot-selftest.png")
    log = out + ".log"
    code = 1
    try:
        from strainplot import dataio, render
        from strainplot import style as S

        folder = argv[0] if argv else None
        if folder is None:
            from strainplot.app import App
            folder = App._default_folder()

        say(f"folder : {folder}")
        res = dataio.scan_folder(folder)
        say(f"series : {len(res.series)} tables: {len(res.tables)}")
        if not res.series:
            say("FAIL: 没有读到曲线")
            raise RuntimeError("no series")

        st = S.reference_style()
        st.ensure_series([s.key for s in res.series], {s.key: s.label for s in res.series})
        plots = []
        for s in res.series:
            ss = st.series.get(s.key)
            if ss is None or not ss.visible:
                continue
            plots.append(render.PlotSeries(ss.label or s.label, ss.color, ss.width, ss.style,
                                           ss.alpha, s.x, s.y, ss.marker, ss.marker_size))
        fig = render.Figure(st, plots, title=st.figure.title)
        render.save_figure(fig, out, dpi=150)
        say(f"export : {out} {os.path.getsize(out)} bytes")
        say("OK")
        code = 0
    except Exception:
        say("FAIL:\n" + traceback.format_exc())
    finally:
        try:
            with open(log, "w", encoding="utf-8") as fh:
                fh.write("\n".join(lines) + "\n")
        except Exception:
            pass
    return code


def _run() -> None:
    if "--selftest" in sys.argv:
        args = [a for a in sys.argv[1:] if not a.startswith("--")]
        sys.exit(_selftest(args))
    from strainplot.app import main
    main()


if __name__ == "__main__":
    _run()
