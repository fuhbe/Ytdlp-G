param([switch]$SkipBootstrap)
$ErrorActionPreference = 'Stop'
if (-not $IsWindows -and $PSVersionTable.PSEdition -eq 'Core') { throw 'Run this script on Windows 10/11 x64.' }
if (-not $SkipBootstrap) { & "$PSScriptRoot/bootstrap_windows.ps1" }
& "$PSScriptRoot/fetch_dependencies.ps1"
& "$PSScriptRoot/test_windows.ps1"
& "$PSScriptRoot/build_portable.ps1"
& "$PSScriptRoot/build_installer.ps1"
Get-ChildItem "$PSScriptRoot/../artifacts" -File | ForEach-Object {
    $Hash = (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    "$Hash  $($_.Name)"
} | Set-Content "$PSScriptRoot/../artifacts/SHA256SUMS.txt" -Encoding ASCII
