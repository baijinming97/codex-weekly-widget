using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Windows.Forms;

[assembly: AssemblyTitle("Codex Weekly Widget")]
[assembly: AssemblyVersion("1.2.1.0")]
[assembly: AssemblyFileVersion("1.2.1.0")]

static class Desktop
{
    const string Product = "CodexWeeklyWidget";
    const string Marker = ".codex-weekly-widget";
    const string Owner = "codex-weekly-widget-managed-v1";
    const string Manifest = "installed-files.txt";
    const string Shortcut = "Codex（含额度）.lnk";
    const string Title = "Codex 周额度";
    static string TestShellRoot;

    static string Quote(string value) { return "\"" + value + "\""; }
    static string DefaultRoot() { return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), Product); }
    static bool Has(string[] args, string option) { return args.Contains(option); }
    static string Root(string[] args)
    {
        int index = Array.IndexOf(args, "--test-root");
        if (index >= 0 && index + 1 >= args.Length) throw new IOException("Missing test directory");
        string root = ValidateRoot(index >= 0 ? args[index + 1] : DefaultRoot());
        // Integration tests never write to the user's real desktop or Startup folder.
        if (index >= 0) TestShellRoot = Path.Combine(Path.GetDirectoryName(root), "shell-test");
        return root;
    }
    static string ValidateRoot(string value)
    {
        string root = Path.GetFullPath(value).TrimEnd(Path.DirectorySeparatorChar);
        if (!String.Equals(Path.GetFileName(root), Product, StringComparison.Ordinal)) throw new IOException("Invalid product directory");
        if (Directory.Exists(root) && (File.GetAttributes(root) & FileAttributes.ReparsePoint) != 0) throw new IOException("Linked directory refused");
        return root;
    }
    static string Inside(string root, string relative)
    {
        if (String.IsNullOrWhiteSpace(relative) || Path.IsPathRooted(relative)) throw new IOException("Invalid relative path");
        string full = Path.GetFullPath(Path.Combine(root, relative.Replace('/', Path.DirectorySeparatorChar)));
        string prefix = Path.GetFullPath(root).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
        if (!full.StartsWith(prefix, StringComparison.OrdinalIgnoreCase)) throw new IOException("Path leaves product directory");
        for (string parent = Path.GetDirectoryName(full); parent.Length >= prefix.Length; parent = Path.GetDirectoryName(parent))
            if (Directory.Exists(parent) && (File.GetAttributes(parent) & FileAttributes.ReparsePoint) != 0) throw new IOException("Linked directory refused");
        if (File.Exists(full) && (File.GetAttributes(full) & FileAttributes.ReparsePoint) != 0) throw new IOException("Linked file refused");
        return full;
    }
    static void CheckOwner(string root)
    {
        if (!File.Exists(Inside(root, Marker)) || File.ReadAllText(Inside(root, Marker)).Trim() != Owner) throw new IOException("Unmanaged directory refused");
    }
    static ProcessStartInfo Hidden(string file, string arguments, string root)
    {
        return new ProcessStartInfo(file, arguments) { WorkingDirectory = root, UseShellExecute = false, CreateNoWindow = true, WindowStyle = ProcessWindowStyle.Hidden, RedirectStandardOutput = true, RedirectStandardError = true };
    }
    static int Run(string file, string arguments, string root, int timeout)
    {
        using (Process process = Process.Start(Hidden(file, arguments, root)))
        {
            process.OutputDataReceived += delegate { };
            process.ErrorDataReceived += delegate { };
            process.BeginOutputReadLine(); process.BeginErrorReadLine();
            if (!process.WaitForExit(timeout)) { process.Kill(); throw new IOException("Helper timed out"); }
            return process.ExitCode;
        }
    }
    static string PowerShell() { return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), @"WindowsPowerShell\v1.0\powershell.exe"); }
    static bool HasCodex()
    {
        return Run(PowerShell(), "-NoProfile -NonInteractive -Command " + Quote("if (Get-AppxPackage -Name 'OpenAI.Codex') { exit 0 } else { exit 1 }"), Path.GetTempPath(), 15000) == 0;
    }
    static void StopTray(string root)
    {
        string python = Inside(root, @"runtime\python.exe");
        string control = Inside(root, "control.py");
        if (File.Exists(python) && File.Exists(control) && Run(python, "-B " + Quote(control), root, 15000) != 0) throw new IOException("Tray did not close");
    }
    static void Launch(string root, bool trayOnly)
    {
        string script = Inside(root, trayOnly ? "Start-Widget.ps1" : "Start-Codex-With-Quota.ps1");
        var info = new ProcessStartInfo(PowerShell(), "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File " + Quote(script)) { WorkingDirectory = root, UseShellExecute = false, CreateNoWindow = true, WindowStyle = ProcessWindowStyle.Hidden };
        Process.Start(info);
    }
    static void SaveShortcut(string path, string executable, string root, string arguments)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(path));
        dynamic shell = Activator.CreateInstance(Type.GetTypeFromProgID("WScript.Shell"));
        dynamic link = shell.CreateShortcut(path);
        link.TargetPath = executable; link.Arguments = arguments; link.WorkingDirectory = root;
        link.Description = "Codex Weekly Widget"; link.IconLocation = executable + ",0";
        link.Save();
        Marshal.FinalReleaseComObject(link); Marshal.FinalReleaseComObject(shell);
    }
    static string ShellFolder(Environment.SpecialFolder folder, string testName)
    {
        return TestShellRoot == null ? Environment.GetFolderPath(folder) : Path.Combine(TestShellRoot, testName);
    }
    static string DesktopRoot() { return ShellFolder(Environment.SpecialFolder.DesktopDirectory, "desktop"); }
    static string MenuRoot() { return Path.Combine(ShellFolder(Environment.SpecialFolder.Programs, "programs"), "Codex 周额度"); }
    static string StartupShortcut() { return Path.Combine(ShellFolder(Environment.SpecialFolder.Startup, "startup"), "Codex 周额度.lnk"); }
    static IEnumerable<string> ShortcutPaths()
    {
        yield return Path.Combine(DesktopRoot(), Shortcut);
        yield return Path.Combine(MenuRoot(), Shortcut);
        yield return Path.Combine(MenuRoot(), "仅启动额度图标.lnk");
        yield return Path.Combine(MenuRoot(), "卸载.lnk");
        yield return StartupShortcut();
    }
    static void CreateShortcuts(string root)
    {
        string launcher = Inside(root, "Launcher.exe");
        SaveShortcut(Path.Combine(DesktopRoot(), Shortcut), launcher, root, "");
        SaveShortcut(Path.Combine(MenuRoot(), Shortcut), launcher, root, "");
        SaveShortcut(Path.Combine(MenuRoot(), "仅启动额度图标.lnk"), launcher, root, "--tray-only");
        SaveShortcut(Path.Combine(MenuRoot(), "卸载.lnk"), Inside(root, "Uninstall.exe"), root, "");
    }
    static void RemoveShortcut(string root, string path)
    {
        if (!File.Exists(path)) return;
        dynamic shell = Activator.CreateInstance(Type.GetTypeFromProgID("WScript.Shell"));
        dynamic link = shell.CreateShortcut(path);
        string target = link.TargetPath;
        Marshal.FinalReleaseComObject(link); Marshal.FinalReleaseComObject(shell);
        if (target.StartsWith(root + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase)) File.Delete(path);
    }
    static void SetStartup(string root, bool enabled)
    {
        if (enabled) SaveShortcut(StartupShortcut(), Inside(root, "Launcher.exe"), root, "--tray-only");
        else RemoveShortcut(root, StartupShortcut());
    }
    static void RemoveShortcuts(string root)
    {
        foreach (string path in ShortcutPaths()) RemoveShortcut(root, path);
        if (Directory.Exists(MenuRoot()) && !Directory.EnumerateFileSystemEntries(MenuRoot()).Any()) Directory.Delete(MenuRoot(), false);
    }
    // Delete only manifest-owned files, never an unchecked recursive directory.
    static void RemoveFiles(string root, IEnumerable<string> names)
    {
        var directories = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (string name in names)
        {
            string file = Inside(root, name);
            if (File.Exists(file)) File.Delete(file);
            for (string dir = Path.GetDirectoryName(file); dir.Length > root.Length; dir = Path.GetDirectoryName(dir)) directories.Add(dir);
        }
        foreach (string dir in directories.OrderByDescending(p => p.Length))
            if (Directory.Exists(dir) && !Directory.EnumerateFileSystemEntries(dir).Any()) Directory.Delete(dir, false);
        if (Directory.Exists(root) && !Directory.EnumerateFileSystemEntries(root).Any()) Directory.Delete(root, false);
    }
    static void Install(string root, bool shortcuts, bool launch, bool startup)
    {
        WithInstallLock(delegate { InstallCore(root, shortcuts, launch, startup); });
    }
    static void WithInstallLock(Action action)
    {
        using (var gate = new Mutex(false, @"Local\CodexWeeklyWidgetInstall"))
        {
            if (!gate.WaitOne(0)) throw new IOException("Another installation is active");
            try { action(); } finally { gate.ReleaseMutex(); }
        }
    }
    static void InstallCore(string root, bool shortcuts, bool launch, bool startup)
    {
        if (!HasCodex()) throw new InvalidOperationException("请先安装并登录官方 Codex。本工具不会替你安装 Codex 或登录。");
        if (Directory.Exists(root) && Directory.EnumerateFileSystemEntries(root).Any()) { CheckOwner(root); StopTray(root); }
        Directory.CreateDirectory(root);
        File.WriteAllText(Inside(root, Marker), Owner, Encoding.UTF8);
        var names = new List<string>();
        using (Stream payload = Assembly.GetExecutingAssembly().GetManifestResourceStream("payload.zip"))
        using (ZipArchive archive = new ZipArchive(payload, ZipArchiveMode.Read))
        {
            // Validate every destination before writing any entry.
            foreach (ZipArchiveEntry entry in archive.Entries) Inside(root, entry.FullName);
            foreach (ZipArchiveEntry entry in archive.Entries)
            {
                string target = Inside(root, entry.FullName);
                Directory.CreateDirectory(Path.GetDirectoryName(target));
                using (Stream input = entry.Open()) using (Stream output = File.Create(target)) input.CopyTo(output);
                names.Add(entry.FullName);
            }
        }
        File.WriteAllText(Inside(root, Marker), Owner, Encoding.UTF8);
        names.Add(Marker); names.Add(Manifest);
        File.WriteAllLines(Inside(root, Manifest), names, Encoding.UTF8);
        if (shortcuts) CreateShortcuts(root);
        SetStartup(root, startup);
        if (launch) Launch(root, false);
    }
    static void Uninstall(string root, bool shortcuts)
    {
        WithInstallLock(delegate { UninstallCore(root, shortcuts); });
    }
    static void UninstallCore(string root, bool shortcuts)
    {
        CheckOwner(root); StopTray(root);
        string[] names = File.ReadAllLines(Inside(root, Manifest));
        foreach (string name in names) Inside(root, name);
        if (shortcuts) RemoveShortcuts(root);
        else RemoveShortcut(root, StartupShortcut());
        RemoveFiles(root, names);
    }
    static void InstallerUi(string root, string preview, bool launch, bool testUi)
    {
        var form = new Form { Text = Title + "安装", ClientSize = new Size(540, 295), StartPosition = FormStartPosition.CenterScreen, FormBorderStyle = FormBorderStyle.FixedDialog, MaximizeBox = false, Font = new Font("Microsoft YaHei UI", 10), AutoScaleMode = AutoScaleMode.Dpi };
        var heading = new Label { Text = "Codex 周额度", Location = new Point(24, 22), Size = new Size(480, 35), Font = new Font("Microsoft YaHei UI", 16, FontStyle.Bold) };
        var content = new Label { Text = "安装后双击桌面“Codex（含额度）”即可使用。\n已包含运行组件，无需安装 Python 或运行命令。\n当前用户安装，无需管理员权限。\n请确保官方 Codex 已安装并登录；额度每 1 分钟更新。", Location = new Point(24, 68), Size = new Size(490, 105) };
        var startup = new CheckBox { Text = "登录 Windows 后自动启动额度图标", Checked = true, Location = new Point(24, 177), Size = new Size(490, 29) };
        var hint = new Label { Text = "配合 Codex 自启；此选项只启动额度图标。", Location = new Point(44, 210), Size = new Size(470, 26), ForeColor = SystemColors.GrayText };
        var status = new Label { Text = "准备就绪", Location = new Point(24, 249), Size = new Size(300, 28) };
        var button = new Button { Text = "安装并启动", Location = new Point(348, 241), Size = new Size(165, 38) };
        bool done = false;
        bool installing = false;
        string uiError = null;
        form.FormClosing += delegate(object sender, FormClosingEventArgs e) { if (installing) e.Cancel = true; };
        button.Click += delegate {
            if (done) { form.Close(); return; }
            bool enableStartup = startup.Checked;
            installing = true; button.Enabled = false; startup.Enabled = false; status.Text = "正在安装，请稍候…";
            var worker = new Thread(delegate() {
                string error = null;
                try { Install(root, true, launch, enableStartup); }
                catch (InvalidOperationException e) { error = e.Message; }
                catch { error = "暂不可用：安装未完成，请关闭额度图标后重试。"; }
                if (!form.IsDisposed) form.BeginInvoke(new Action(delegate {
                    installing = false; button.Enabled = true;
                    if (error == null) { done = true; status.Text = "安装完成，桌面快捷方式已创建"; button.Text = "完成"; }
                    else { startup.Enabled = true; status.Text = "安装未完成"; if (!testUi) MessageBox.Show(form, error, Title); }
                    if (testUi) { uiError = error; form.Close(); }
                }));
            });
            worker.SetApartmentState(ApartmentState.STA); worker.Start();
        };
        form.Controls.AddRange(new Control[] { heading, content, startup, hint, status, button });
        form.AcceptButton = button;
        if (preview != null)
        {
            form.ShowInTaskbar = false; form.StartPosition = FormStartPosition.Manual;
            form.Location = new Point(-32000, -32000); form.Show(); form.Refresh();
            using (var bitmap = new Bitmap(form.Width, form.Height)) { form.DrawToBitmap(bitmap, new Rectangle(0, 0, bitmap.Width, bitmap.Height)); bitmap.Save(preview, System.Drawing.Imaging.ImageFormat.Png); }
            form.Close(); form.Dispose(); return;
        }
        if (testUi)
        {
            form.ShowInTaskbar = false; form.StartPosition = FormStartPosition.Manual; form.Location = new Point(-32000, -32000);
            form.Shown += delegate { button.PerformClick(); };
        }
        Application.Run(form);
        if (uiError != null) throw new IOException("Installer UI check failed");
    }
    [STAThread]
    static int Main(string[] args)
    {
        Application.EnableVisualStyles();
        try
        {
#if INSTALLER
            string root = Root(args);
            int previewIndex = Array.IndexOf(args, "--preview");
            if (Has(args, "--test-ui") && !Has(args, "--test-root")) throw new IOException("UI check requires a test directory");
            if (previewIndex >= 0) InstallerUi(root, args[previewIndex + 1], false, false);
            else if (Has(args, "--test-ui")) InstallerUi(root, null, !Has(args, "--no-launch"), true);
            else if (Has(args, "--quiet")) Install(root, !Has(args, "--no-shortcuts"), !Has(args, "--no-launch"), !Has(args, "--no-startup"));
            else InstallerUi(root, null, !Has(args, "--no-launch"), false);
#elif LAUNCHER
            Launch(Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location), Has(args, "--tray-only"));
#elif UNINSTALLER
            if (Has(args, "--test-root")) Root(args);
            int index = Array.IndexOf(args, "--cleanup");
            if (index >= 0)
            {
                string root = ValidateRoot(args[index + 1]);
                Thread.Sleep(500);
                Uninstall(root, !Has(args, "--no-shortcuts"));
            }
            else
            {
                string root = Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location);
                CheckOwner(root);
                if (!Has(args, "--quiet") && MessageBox.Show("卸载 Codex 周额度工具及其快捷方式？", Title, MessageBoxButtons.YesNo) != DialogResult.Yes) return 0;
                string helper = Path.Combine(Path.GetTempPath(), "CodexWeeklyWidget-Uninstall-" + Guid.NewGuid().ToString("N") + ".exe");
                File.Copy(Assembly.GetExecutingAssembly().Location, helper);
                string testArgs = Has(args, "--test-root") ? " --test-root " + Quote(root) : "";
                var info = new ProcessStartInfo(helper, "--cleanup " + Quote(root) + testArgs + (Has(args, "--no-shortcuts") ? " --no-shortcuts" : "") + (Has(args, "--quiet") ? " --quiet" : "")) { UseShellExecute = false, CreateNoWindow = true, WindowStyle = ProcessWindowStyle.Hidden };
                Process.Start(info);
            }
#endif
            return 0;
        }
        catch
        {
            if (!Has(args, "--quiet")) MessageBox.Show("暂不可用：操作未完成，请关闭额度图标后重试。", Title);
            return 1;
        }
    }
}
