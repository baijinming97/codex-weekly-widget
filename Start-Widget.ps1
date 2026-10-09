$ErrorActionPreference = 'Stop'
try {
    $bundledPython = Join-Path $PSScriptRoot 'runtime\pythonw.exe'
    $pythonCommand = Get-Command pythonw.exe -ErrorAction SilentlyContinue
    $pythonExecutable = if (Test-Path -LiteralPath $bundledPython -PathType Leaf) { $bundledPython } elseif ($pythonCommand) { $pythonCommand.Source } else { $null }
    if (-not $pythonExecutable) {
        $pythonFolder = Join-Path $env:LOCALAPPDATA 'Programs\Python'
        $pythonExecutable = Get-ChildItem -LiteralPath $pythonFolder -Directory -ErrorAction SilentlyContinue |
            ForEach-Object { Join-Path $_.FullName 'pythonw.exe' } |
            Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } |
            Select-Object -First 1
    }
    if (-not $pythonExecutable) { throw 'Python unavailable' }
    if ($pythonExecutable -eq $bundledPython) {
        $env:TCL_LIBRARY = Join-Path $PSScriptRoot 'runtime\tcl\tcl8.6'
        $env:TK_LIBRARY = Join-Path $PSScriptRoot 'runtime\tcl\tk8.6'
    }
    $widgetScript = Join-Path $PSScriptRoot 'tray.py'
    Start-Process -FilePath $pythonExecutable -ArgumentList @('-B', ('"' + $widgetScript + '"')) -WorkingDirectory $PSScriptRoot -WindowStyle Hidden
} catch {
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show('Existing Python was not found, or the widget could not start. See README.md. No software was installed.', 'Codex Weekly Widget') | Out-Null
}
