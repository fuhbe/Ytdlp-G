$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
python -m venv build/lite-env
$p = 'build/lite-env/Scripts/python.exe'
& $p -m pip install PySide6-Essentials==6.12.0 pyinstaller==6.22.3 pytest==9.1.1
& $p -m PyInstaller --paths src --paths lite --workpath build/pyinstaller --clean --noconfirm --windowed --onefile --name Ytdlp-G-Lite --icon assets/icons/app.ico lite/entry.py
$pkg = 'build/Ytdlp-G-Lite'
New-Item -ItemType Directory "$pkg/tools","$pkg/licenses",artifacts -Force | Out-Null
Copy-Item dist/Ytdlp-G-Lite.exe $pkg
Copy-Item lite/README.txt,LICENSE $pkg
Copy-Item assets/licenses/Qt*.txt "$pkg/licenses"
curl.exe -fsSL https://raw.githubusercontent.com/denoland/deno/v2.9.8/LICENSE.md -o "$pkg/licenses/Deno.txt"
curl.exe -fsSL https://raw.githubusercontent.com/pyinstaller/pyinstaller/v6.22.3/COPYING.txt -o "$pkg/licenses/PyInstaller.txt"
& $p scripts/collect_licenses.py "$pkg/licenses"
function Fetch($url,$hash,$out) {
    curl.exe -fLsS --retry 2 $url -o $out
    if ((Get-FileHash $out).Hash -ne $hash) { throw "Checksum mismatch $out" }
}
$ff = (Get-Content scripts/dependencies.json -Raw | ConvertFrom-Json).ffmpeg
Fetch $ff.url $ff.sha256 build/ff.zip
Expand-Archive build/ff.zip build/ff
$bin = (Get-ChildItem build/ff -Recurse -Filter ffmpeg.exe)[0].Directory.FullName
Copy-Item "$bin/*.dll","$bin/ffmpeg.exe","$bin/ffprobe.exe" "$pkg/tools"
Get-ChildItem build/ff -Recurse -File | Where-Object Name -match '(?i)license|copying' | Copy-Item -Destination "$pkg/licenses" -Force
Fetch https://github.com/yt-dlp/yt-dlp/releases/download/2026.11.23/yt-dlp.exe 622ed48023cac1daa52a3bf3a6ac38f03514de214b5f0fa069389fd0f6d17e5c "$pkg/tools/yt-dlp.exe"
Fetch https://github.com/denoland/deno/releases/download/v2.9.8/deno-x86_64-pc-windows-msvc.zip cba84b26e0df5ae7f74fc66b86a95b866872a86292ebd84fa1e959927edd93bf build/deno.zip
Expand-Archive build/deno.zip "$pkg/tools"
foreach ($name in 'LICENSE','THIRD_PARTY_LICENSES.txt') {
    curl.exe -fsSL "https://raw.githubusercontent.com/yt-dlp/yt-dlp/2026.11.23/$name" -o "$pkg/licenses/yt-dlp-$name.txt"
}
$env:PYTHONPATH = "src;lite"
$env:LITE_TEST_TOOLS = (Resolve-Path "$pkg/tools").Path
Fetch https://github.com/yt-dlp/yt-dlp/releases/download/2026.10.26/yt-dlp.exe f5389d3698ecde4ef06f4e6b1ce0294fe9ac1396228c8990b8d3416d6d177a7d build/old.exe
$env:LITE_OLD_ENGINE = (Resolve-Path build/old.exe).Path
& $p -m pytest lite/test_edition.py -q --junitxml=artifacts/tests.xml
& $p lite/capture.py artifacts
Copy-Item "$pkg/Ytdlp-G-Lite.exe" artifacts
Compress-Archive $pkg artifacts/Ytdlp-G-Lite-portable.zip
& "${env:ProgramFiles(x86)}/Inno Setup 6/ISCC.exe" lite/setup.iss
$install = Join-Path $env:RUNNER_TEMP 'Teste Lite'
$setup = Start-Process artifacts/Ytdlp-G-Lite-Setup.exe -ArgumentList "/VERYSILENT /NORESTART /DIR=`"$install`"" -Wait -PassThru
if ($setup.ExitCode) { throw 'Install failed' }
$savedPath = $env:PATH
$env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
$env:PYTHONHOME = Join-Path $env:RUNNER_TEMP 'absent-python'
$portable = Join-Path $env:RUNNER_TEMP 'Portable Lite'
Expand-Archive artifacts/Ytdlp-G-Lite-portable.zip $portable
foreach ($case in @(@("installed", "$install/Ytdlp-G-Lite.exe"), @("portable", "$portable/Ytdlp-G-Lite/Ytdlp-G-Lite.exe"))) {
    $report = Join-Path (Resolve-Path artifacts) ($case[0] + "-smoke.json")
    $smoke = Start-Process $case[1] -ArgumentList "--smoke-test `"$report`"" -PassThru
    if (-not $smoke.WaitForExit(60000)) {
        Get-Process -Name Ytdlp-G-Lite | Select-Object Id,MainWindowTitle | Out-Host
        taskkill /F /T /PID $smoke.Id
        throw "Timeout opening $($case[0]) UI"
    }
    if (Test-Path $report) { Get-Content $report }
    if ($smoke.ExitCode -ne 0 -or -not (Test-Path $report)) { throw "UI smoke failed ($($smoke.ExitCode))" }
}
Remove-Item Env:PYTHONHOME
$env:PATH = $savedPath
@"
Ytdlp-G Lite 0.1.0 Beta 1 — validação
Sistema: $([System.Environment]::OSVersion.VersionString), Windows x64, GitHub Actions.
Build: https://github.com/$env:GITHUB_REPOSITORY/actions/runs/$env:GITHUB_RUN_ID
Código: $env:GITHUB_SHA

Suíte automatizada aprovada. Casos individuais e tempos em tests.xml.
Downloads individuais, múltiplos links e playlists foram testados com mídia HTTP local.
A suíte verifica MP4 H.264/AAC, MP3, AV1, VP9, HEVC, HDR, 1080p60, Fast Start,
cópia de streams, conversão só do áudio, perfil antigo, falha de playlist e cancelamento.
O atualizador foi exercitado com executável antigo e release oficial, e com falha
simulada depois da troca para verificar a restauração. Capturas: light.png e dark.png.
Instalação por usuário e abertura da janela do EXE instalado: aprovadas com
Python fora do PATH e PYTHONHOME apontando para um diretório inexistente.
O runner possui Python instalado. Windows 10 e 11 de consumidor limpos não foram testados.
YouTube: o proxy do ambiente de desenvolvimento retornou HTTP 403. Sem validação online.
Projetor HY300: sem teste físico. Retomada depende da fonte e da disponibilidade dos fragmentos.

Python $(& $p -c "import platform;print(platform.python_version())")
PySide6 / Shiboken 6.12.0
yt-dlp $(& "$pkg/tools/yt-dlp.exe" --version)
$((& "$pkg/tools/ffmpeg.exe" -version)[0])
$((& "$pkg/tools/ffprobe.exe" -version)[0])
$((& "$pkg/tools/deno.exe" --version)[0])
"@ | Set-Content artifacts/RELATORIO.txt -Encoding utf8
git archive --format=zip --output=artifacts/Ytdlp-G-Lite-source.zip HEAD
Get-ChildItem artifacts -File | ForEach-Object { "$((Get-FileHash $_).Hash.ToLower())  $($_.Name)" } | Set-Content artifacts/SHA256SUMS.txt
