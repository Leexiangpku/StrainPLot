// StrainPlot 启动器：双击后以无控制台方式拉起自带的 Python 运行时。
// 用 .NET Framework 的 csc.exe 编译：
//   csc /target:winexe /optimize+ /out:StrainPlot.exe /win32icon:icon.ico Launcher.cs
using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

internal static class Launcher
{
    [STAThread]
    private static void Main()
    {
        string dir = AppDomain.CurrentDomain.BaseDirectory;
        string pyw = Path.Combine(dir, Path.Combine("runtime", "pythonw.exe"));
        string app = Path.Combine(dir, Path.Combine("app", "run_app.py"));

        if (!File.Exists(pyw) || !File.Exists(app))
        {
            MessageBox.Show(
                "程序文件不完整，找不到：\n\n" + pyw + "\n" + app +
                "\n\n请重新解压完整的 StrainPlot 压缩包。",
                "StrainPlot 启动失败",
                MessageBoxButtons.OK, MessageBoxIcon.Error);
            return;
        }

        try
        {
            ProcessStartInfo psi = new ProcessStartInfo(pyw, "\"" + app + "\"");
            psi.WorkingDirectory = dir;
            psi.UseShellExecute = false;
            psi.CreateNoWindow = true;
            Process.Start(psi);
        }
        catch (Exception ex)
        {
            MessageBox.Show(
                "启动失败：" + ex.Message + "\n\n可尝试直接运行 runtime\\python.exe app\\run_app.py",
                "StrainPlot 启动失败",
                MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }
}
