. "$PSScriptRoot/common.ps1"
if (-not (Test-Path 'dist/Ytdlp-G/Ytdlp-G.exe')) { throw 'Run scripts/build_portable.ps1 first.' }
$Compiler = Get-Command 'ISCC.exe' -ErrorAction SilentlyContinue
if ($Compiler) { $CompilerPath = $Compiler.Source }
else { $CompilerPath = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" }
if (-not (Test-Path $CompilerPath)) { throw 'Inno Setup 6 was not found. Install it from jrsoftware.org and retry.' }
Invoke-Checked $CompilerPath @('installer/Ytdlp-G.iss')
if (-not (Test-Path 'artifacts/Ytdlp-G-Setup.exe')) { throw 'Installer output is missing.' }
Write-Host 'Installer artifact: artifacts/Ytdlp-G-Setup.exe (unsigned)'
