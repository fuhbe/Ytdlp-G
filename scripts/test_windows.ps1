. "$PSScriptRoot/common.ps1"
$Python = Get-ProjectPython
$env:QT_QPA_PLATFORM = 'offscreen'
$env:PATH = (Join-Path $ProjectRoot 'build\dependencies\bin') + ';' + $env:PATH
Invoke-Checked $Python @('-m', 'ruff', 'check', '.')
Invoke-Checked $Python @('-m', 'ruff', 'format', '--check', '.')
Invoke-Checked $Python @('-m', 'pytest', '-q', '--junitxml=build/test-results.xml')
Invoke-Checked $Python @('-m', 'ytdlp_g.main', '--smoke-test')
