$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
python -m venv build/lite-env
$p = 'build/lite-env/Scripts/python.exe'
& $p -m pip install PySide6-Essentials==6.12.0 pyinstaller==6.22.3 pytest==9.1.1
& $p -m PyInstaller --paths src --clean --noconfirm --windowed --onefile --name Ytdlp-G-Lite --icon assets/icons/app.ico lite/app.py
$pkg = 'build/Ytdlp-G-Lite'
New-Item -ItemType Directory "$pkg/tools","$pkg/licenses",artifacts -Force | Out-Null
Copy-Item dist/Ytdlp-G-Lite.exe $pkg
Copy-Item lite/README.txt,LICENSE,THIRD_PARTY_NOTICES.md $pkg
Copy-Item assets/licenses/* "$pkg/licenses"
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
& $p -m pytest lite/test_edition.py -q --junitxml=artifacts/tests.xml
& $p lite/capture.py artifacts
Copy-Item "$pkg/Ytdlp-G-Lite.exe" artifacts
Compress-Archive $pkg artifacts/Ytdlp-G-Lite-portable.zip
& "${env:ProgramFiles(x86)}/Inno Setup 6/ISCC.exe" lite/setup.iss
$install = Join-Path $env:RUNNER_TEMP 'Teste Lite'
$setup = Start-Process artifacts/Ytdlp-G-Lite-Setup.exe -ArgumentList "/VERYSILENT /NORESTART /DIR=`"$install`"" -Wait -PassThru
if ($setup.ExitCode) { throw 'Install failed' }
$smoke = Start-Process "$install/Ytdlp-G-Lite.exe" -PassThru
try {
    $ready = $false
    foreach ($i in 1..90) {
        Start-Sleep 1
        if ((Get-Process -Name Ytdlp-G-Lite -ErrorAction SilentlyContinue | Where-Object MainWindowTitle -eq 'Ytdlp-G Lite')) { $ready = $true; break }
        if ($smoke.HasExited) { break }
    }
    if (-not $ready) { throw 'Installed UI did not open' }
} finally { if (-not $smoke.HasExited) { taskkill /F /T /PID $smoke.Id } }
git archive --format=zip --output=artifacts/Ytdlp-G-Lite-source.zip HEAD
Get-ChildItem artifacts -File | ForEach-Object { "$((Get-FileHash $_).Hash.ToLower())  $($_.Name)" } | Set-Content artifacts/SHA256SUMS.txt
