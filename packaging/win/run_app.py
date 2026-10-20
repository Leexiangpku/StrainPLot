"""打包版入口：把 stdout/stderr 重定向到日志，出错时弹窗而不是静默退出。"""
import os
import sys
import traceback

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
_LOG = os.path.join(_ROOT, "strainplot.log")


class _Tee:
    def __init__(self, path):
        self._f = open(path, "a", encoding="utf-8", buffering=1)

    def write(self, s):
        try:
            self._f.write(s)
        except Exception:
            pass

    def flush(self):
        try:
            self._f.flush()
        except Exception:
            pass


def _install_log() -> None:
    try:
        tee = _Tee(_LOG)
        sys.stdout = tee
        sys.stderr = tee
    except Exception:
        pass


def main() -> None:
    _install_log()
    try:
        from strainplot.app import main as run
        run()
    except Exception:
        tb = traceback.format_exc()
        sys.stderr.write(tb)
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("StrainPlot 启动失败",
                                 tb[-1500:] + "\n\n完整日志：" + _LOG)
            root.destroy()
        except Exception:
            pass
        raise SystemExit(1)


if __name__ == "__main__":
    main()
