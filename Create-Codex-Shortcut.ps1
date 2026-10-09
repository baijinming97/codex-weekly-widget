$ErrorActionPreference = 'Stop'
$shortcutTitle = 'Codex' + [char]0xFF08 + [char]0x542B + [char]0x989D + [char]0x5EA6 + [char]0xFF09
$codexPackage = Get-AppxPackage -Name 'OpenAI.Codex' | Select-Object -First 1
if (-not $codexPackage) { throw 'Existing Codex app not found' }
$codexManifest = Get-AppxPackageManifest -Package $codexPackage.PackageFullName
$codexApplication = $codexManifest.Package.Applications.Application | Where-Object { $_.Id -eq 'App' } | Select-Object -First 1
$codexExecutable = Join-Path $codexPackage.InstallLocation $codexApplication.Executable
# Copy only the icon resource into the tool's own folder; never modify installed files.
Add-Type -AssemblyName System.Drawing
$codexIcon = [System.Drawing.Icon]::ExtractAssociatedIcon($codexExecutable)
$iconDestination = Join-Path $PSScriptRoot 'codex.ico'
if ($codexIcon) {
    $iconStream = [System.IO.File]::Create($iconDestination)
    try { $codexIcon.Save($iconStream) } finally { $iconStream.Dispose(); $codexIcon.Dispose() }
}
$shortcutShell = New-Object -ComObject WScript.Shell
$desktopShortcut = Join-Path ([Environment]::GetFolderPath('Desktop')) ($shortcutTitle + '.lnk')
$shortcut = $shortcutShell.CreateShortcut($desktopShortcut)
$shortcut.TargetPath = Join-Path $env:WINDIR 'System32\wscript.exe'
$shortcut.Arguments = '"' + (Join-Path $PSScriptRoot 'Start-Codex-With-Quota.vbs') + '"'
$shortcut.WorkingDirectory = $PSScriptRoot
$shortcut.Description = 'Start the existing Codex app with the weekly quota tray icon'
$shortcut.WindowStyle = 7
if (Test-Path -LiteralPath $iconDestination) { $shortcut.IconLocation = $iconDestination + ',0' }
$shortcut.Save()
Write-Output $desktopShortcut
