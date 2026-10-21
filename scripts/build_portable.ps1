. "$PSScriptRoot/common.ps1"
$Python = Get-ProjectPython
if (-not (Test-Path 'build/dependencies/bin/ffmpeg.exe')) { throw 'Run scripts/fetch_dependencies.ps1 first.' }
Invoke-Checked $Python @('-m', 'PyInstaller', '--clean', '--noconfirm', 'Ytdlp-G.spec')
Copy-Item 'README.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md', 'CHANGELOG.md' 'dist/Ytdlp-G/' -Force
Copy-Item 'docs' 'dist/Ytdlp-G/docs' -Recurse -Force
Copy-Item 'build/dependencies/licenses' 'dist/Ytdlp-G/licenses' -Recurse -Force
Copy-Item 'assets/licenses' 'dist/Ytdlp-G/licenses/upstream' -Recurse -Force
Invoke-Checked $Python @('scripts/collect_licenses.py', 'dist/Ytdlp-G/licenses/python')
$Metadata = @{ version = '1.2.0'; built_utc = [DateTime]::UtcNow.ToString('o'); commit = $env:GITHUB_SHA; signed = $false }
$Metadata | ConvertTo-Json | Set-Content 'dist/Ytdlp-G/build-metadata.json' -Encoding UTF8
Invoke-Checked $Python @('scripts/smoke_packaged.py', 'dist/Ytdlp-G', '--report', 'build/packaged-smoke.json')
New-Item -ItemType Directory -Force 'artifacts' | Out-Null
# The marker belongs only to the portable copy; the installed app uses LocalAppData.
Set-Content 'dist/Ytdlp-G/portable.flag' ''
Compress-Archive -Path 'dist/Ytdlp-G' -DestinationPath 'artifacts/Ytdlp-G-portable.zip' -Force
Remove-Item 'dist/Ytdlp-G/portable.flag'
# Verify the exact distributed ZIP after relocation to a path containing spaces.
$Relocated = Join-Path $ProjectRoot 'build\portable extraction smoke'
if (Test-Path $Relocated) { Remove-Item $Relocated -Recurse -Force }
Expand-Archive 'artifacts/Ytdlp-G-portable.zip' $Relocated
Invoke-Checked $Python @('scripts/smoke_packaged.py', (Join-Path $Relocated 'Ytdlp-G'), '--report', 'build/portable-smoke.json')
Write-Host 'Portable artifact: artifacts/Ytdlp-G-portable.zip'
