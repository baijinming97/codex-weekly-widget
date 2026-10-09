# 第三方组件

安装版附带应用专用的 CPython 3.12 与 Tcl/Tk 运行组件。它们只放在本工具的 `runtime` 文件夹，不注册系统 Python、不修改 PATH。

- Python、其标准库及包含的底层组件：完整许可见 `runtime/LICENSE.txt`。
- Tcl/Tk：许可见上述文件的 Tcl/Tk 部分及 `runtime/tcl/tk8.6/license.terms`。
- Microsoft 运行库：适用条款包含在 `runtime/LICENSE.txt` 的 Windows 二进制组件部分。安装版仅面向 Windows。

本项目的 MIT 许可证仅适用于本项目源码；第三方组件保留各自的版权、许可条件与免责条款。使用附带组件须遵守上述原始条款。Windows 自带的 .NET Framework、PowerShell 和已安装的 Codex 不随本工具分发。

构建时只复制明确列出的运行库文件与标准库，不复制 site-packages、用户配置、账号文件或开发者电脑的认证资料。
