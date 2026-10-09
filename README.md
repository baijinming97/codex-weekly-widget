# Codex Weekly Widget · Codex 周额度托盘图标

Windows 系统托盘中的 Codex 周额度数字图标，使用本机官方 Codex App Server。安装版已包含运行组件，无需另装 Python。这是独立的社区工具，与 OpenAI 无官方关联。源码采用 [MIT 许可证](LICENSE)。

## 在另一台电脑使用

推荐使用 **Windows 10/11 x64 安装版**。需要已安装并登录、支持 App Server 额度接口的官方 Codex；工具不会替你安装 Codex 或登录。

1. 从 [最新 Release](https://github.com/baijinming97/codex-weekly-widget/releases/latest) 下载 **CodexWeeklyWidget-Setup-v1.2.1-x64.exe**。
2. 双击，点击 **安装并启动**。无需解压、运行命令或安装 Python，也无需管理员权限。
3. 之后双击桌面 **Codex（含额度）**；也可以在开始菜单 **Codex 周额度 → 仅启动额度图标** 中单独启动图标。

安装界面中的 **登录 Windows 后自动启动额度图标** 默认勾选，可以取消。该启动项只启动额度图标，配合 Codex 已有的自启动设置；Codex 是否自启由它自己的设置控制。不会再次启动 Codex，也不添加常驻监视器。需要改变选项时，重新运行安装器并选择即可。

安装位置为当前用户的 `%LOCALAPPDATA%\CodexWeeklyWidget`，运行组件放在其 `runtime` 子目录，不注册系统 Python、不修改 PATH。升级时双击新版安装器；会先关闭这份安装版的图标，再更新文件。卸载请在开始菜单 **Codex 周额度 → 卸载** 中操作，会移除本工具文件、快捷方式与启动项，保留你额外放入的文件。

安装器目前未签名，Windows 可能显示未知发布者。请确认文件来自本仓库的 Release，可核对 Release 中的 SHA-256。安装流程已在本机隔离目录验证，尚未在第二台电脑实测。

每台电脑读取自己的 Codex 登录账户；不用复制账号或认证文件。统一入口根据本机安装清单寻找 Codex 应用，不依赖开发者电脑的用户名、盘符或安装版本。

### 从源码运行

源码版需要已有 **Python 3.12 或更新版本（包含 tkinter）**，在 Python 3.12 上验证。下载源码 ZIP，完整解压到固定文件夹，然后双击 **Start-Widget.vbs**。源码版不会创建开机启动项。可选创建与 Codex 一起启动的桌面入口：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Create-Codex-Shortcut.ps1
```

移动源码文件夹后，请重新创建快捷方式。

## 操作

启动后仅在 Windows 右下角系统托盘显示一个数字图标，例如 **98** 代表周额度剩余 **98%**，无控制台窗口。重复启动同一份工具不会创建多个图标。

创建 **Codex（含额度）** 快捷方式后，从这个入口启动 Codex 时，会同时启动额度托盘图标。也可以双击本目录的 **Start-Codex-With-Quota.vbs**。启动器通过本机已注册的 Codex 应用 ID 打开官方应用，兼容安装路径随更新变化。

“跟随 Codex 启动”通过统一入口实现；登录 Windows 时的启动由安装界面的独立选项控制。

- 鼠标悬停：显示准确剩余百分比、距离额度**重置**还有几天几小时、具体重置时间及数据更新时间。
- **左键单击图标立即刷新**；读取中再点击不会发起重复请求，也不会打开菜单。默认每 **1 分钟自动刷新**，右键菜单仍可手动刷新。
- 右键：**刷新额度 / 查看明细 / 退出**。“查看明细”和双击图标通过 `codex://settings` 打开 **Codex 应用内设置**，再点击 **用量（Usage）** 查看详情。本机版本没有直达用量页的深链接；不打开浏览器或本地明细窗口。入口说明见 [官方深链接文档](https://learn.chatgpt.com/docs/app/commands#deep-links)。
- 右键选择刷新后菜单关闭；左键单击直接刷新。只有新的右键操作才打开菜单，菜单打开时的左键关闭操作不会额外刷新。
- 彻底关闭请在托盘右键选择 **退出**。
- 如果 Windows 把新图标收进右下角 **^** 隐藏区域，可将它拖到外面的托盘区域。程序不修改任务栏设置。

图标空间有限，小数百分比向下取整显示；不到 1% 时显示 **<1**，鼠标悬停显示完整百分比。读取中或暂不可用时图标显示 **--**，悬停可查看状态；不显示旧数字或模拟数据。

如果系统禁用 Windows Script Host，可以在 PowerShell 运行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Start-Widget.ps1
```

启动时读取一次，此后每 **1 分钟**在后台自动读取额度；左键单击或右键选择刷新均可立即读取。手动刷新会重新计算下个自动刷新时间。读取未完成时不重复请求；失败后清除数字并显示“暂不可用”，等下个周期重试。电脑休眠后恢复时，若已到周期会读取一次，不补发休眠期间的请求。悬停倒计时在本机随时间更新，额度百分比来自最近一次成功读取，并显示“几分钟前更新”。到重置时间时清除旧数字并自动读取。退出工具后停止刷新。

## 数据来源与周窗口

```text
本机 codex.exe app-server --listen stdio://
  → initialize → initialized → account/rateLimits/read
  → 选择 codex 额度桶中唯一的 10080 分钟窗口
  → 剩余百分比 = clamp(100 - usedPercent, 0, 100)
  → Windows Shell_NotifyIcon 数字图标与悬停提示
```

`rate_limits.py` 负责短时 JSON-RPC 会话、超时、取消及字段校验。`tray.py` 通过 `ctypes` 调用 Windows 原生托盘与 GDI 接口绘制数字图标，隐藏的 Tk 主循环负责线程结果与事件调度。`widget.py` 保留早期可拖动、始终置顶窗口及共用函数。PowerShell/VBS 负责无控制台启动和可选桌面快捷方式。

使用本机现有 `codex.exe app-server --listen stdio://`，按官方协议发送 `initialize` → `initialized` → `account/rateLimits/read`。不创建聊天、不运行模型。

优先选择 `rateLimitsByLimitId.codex`；旧版接口无该字段时使用 `rateLimits`。只接受 `windowDurationMins = 10080`（7 天），会检查 `primary` 与 `secondary`，不假定周窗口在哪一个字段。缺失、存在多个周窗口、格式无效或已过重置时间时，显示 **暂不可用**。剩余百分比 = `100 - usedPercent`，限制到 0–100；重置时间来自接口的 Unix 秒时间戳。

重置时间明确按 **Africa/Johannesburg（南非时间，UTC+02:00）** 显示，无需 Windows 安装时区数据库。

程序只调用官方 App Server。工具源码不打开认证文件、不读取/输出令牌、不调用登录/注销接口；认证由 Codex 自己使用其现有登录状态完成。stderr 丢弃，RPC 错误只转换为固定提示，不记录原始消息、账户或环境内容。

不会修改 Codex 安装文件、读取认证文件、修改注册表或创建计划任务。安装版仅在你保留自启勾选时创建当前用户的启动文件夹快捷方式；卸载时移除。源码版退出后删除目录即可移除工具。

## 检查与测试

使用本机已有 Python 3.12 与 Tk 8.6，仅依赖标准库。

可先运行 `python .\check_environment.py`，仅检查 Windows、Python、Tk 和 Codex 可执行文件，不联网或请求登录。如果已有 Python 但隐藏启动器未找到，可在终端用 `python .\tray.py` 启动（终端会保留）。

```powershell
# 实测接口：只输出筛选后的周窗口字段，无原始消息或账户数据。
python .\rate_limits.py

# 数据选择、失效处理与协议行为测试。
python -m unittest discover -s .\tests -v

# 在真实 Tk 窗口中检查置顶、拖动、刷新、失效及关闭。
python .\tests\check_ui.py

# 在原生系统托盘中检查真实数据、倒计时、右键菜单、官方明细跳转与退出。
python .\tests\check_tray.py

# 检查双击启动器、重复启动与关闭（测试时会关闭本工具）。
python .\tests\check_launcher.py

# 构建安装器，并验证隔离安装、真实额度、升级、自启快捷方式和卸载。
python .\build_installer.py
python .\tests\check_installer.py
```

运行界面始终使用真实接口数据。自动测试中的数据样例仅用于验证字段选择和错误处理，不连接运行界面。界面测试中的百分比来自真实接口；错误/过期测试会清空读数。

读取失败时，托盘悬停显示 **暂不可用** 和固定原因。没有登录或本机版本不支持时，请先决定是否登录/更新 Codex；工具不会自动替你执行这些操作。查看明细使用 Codex 自身的登录状态，工具不读取或传递登录令牌。链接关联失效时显示固定错误，不回退到浏览器。

官方字段说明：[Codex App Server](https://learn.chatgpt.com/docs/app-server#6-rate-limits-chatgpt)。

## 打包与 GitHub 开源

```powershell
python .\build_release.py
python .\build_installer.py
```

分别输出 `dist\codex-weekly-widget-v1.2.1.zip` 和 `dist\CodexWeeklyWidget-Setup-v1.2.1-x64.exe`。源码 ZIP 使用明确的文件清单，不包含本机验证记录、截图、提取的 Codex 图标、缓存、认证文件或其他项目。源码启动器的桌面快捷方式图标在使用者电脑上从已有 Codex 只读提取，不随源码分发。

安装器构建需要已有的 Windows x64 CPython 3.12（含 Tk）和 Windows .NET Framework C# 编译器，不自动安装任何依赖。`build_installer.py` 只复制明确列出的 CPython/Tcl/Tk 运行文件和标准库，不复制第三方 site-packages 或用户配置；运行时用 `python312._pth` 隔离系统 Python 与用户模块。附带组件的原始许可证见 [第三方组件说明](THIRD-PARTY-NOTICES.md)。安装器源码为 `windows/Desktop.cs`。

将 ZIP 解压到独立目录后，可把其中源码上传到自己的 GitHub 仓库，并把 ZIP 放到 Release 供其他电脑下载。MIT 许可证允许使用、修改和分发这些源码；OpenAI/Codex 名称及原应用图标不属于本项目的许可内容。

单元测试不读取真实账户，不需要 GitHub 或 Codex 登录。本机 UI/托盘及安装器集成检查需要 Windows 图形桌面与已有 Codex 登录。安装器测试使用临时目录和隔离的桌面/开始菜单/启动目录，不修改本机实际启动项；它验证隐藏启动、单实例、升级、取消自启、路径越界拒绝及卸载保留额外文件，不关闭 Codex。
