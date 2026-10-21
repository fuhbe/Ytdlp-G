. "$PSScriptRoot/common.ps1"
if (-not (Get-Command py -ErrorAction SilentlyContinue)) { throw 'Install Python 3.12 x64 from python.org, including the Python launcher.' }
if (-not (Test-Path '.venv\Scripts\python.exe')) {
    Invoke-Checked 'py' @('-3.12', '-m', 'venv', '.venv')
}
$Python = Get-ProjectPython
Invoke-Checked $Python @('-c', 'import sys, struct; assert sys.version_info[:2] == (3,12) and struct.calcsize(chr(80)) == 8')
Invoke-Checked $Python @('-m', 'pip', 'install', '-r', 'requirements-build.lock')
Invoke-Checked $Python @('-m', 'pip', 'install', '--no-deps', '-e', '.')
Write-Host 'Environment ready. Run scripts/build_windows.ps1 to test and build.'
