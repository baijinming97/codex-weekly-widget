$ErrorActionPreference = 'Stop'
try {
    $codexPackage = Get-AppxPackage -Name 'OpenAI.Codex' | Select-Object -First 1
    if (-not $codexPackage) { throw 'Codex unavailable' }
    $codexManifest = Get-AppxPackageManifest -Package $codexPackage.PackageFullName
    $codexApplication = $codexManifest.Package.Applications.Application | Where-Object { $_.Id -eq 'App' } | Select-Object -First 1
    if (-not $codexApplication) { throw 'Codex unavailable' }
    $codexAppId = $codexPackage.PackageFamilyName + '!' + $codexApplication.Id
    Start-Process -FilePath (Join-Path $env:WINDIR 'explorer.exe') -ArgumentList @('shell:AppsFolder\' + $codexAppId) -WindowStyle Hidden
    & (Join-Path $PSScriptRoot 'Start-Widget.ps1')
} catch {
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show('Codex could not be started. Confirm that the existing Codex app is installed. No software was installed or changed.', 'Codex + Quota') | Out-Null
}
