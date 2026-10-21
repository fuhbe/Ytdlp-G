$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$ProjectRoot = Split-Path $PSScriptRoot -Parent
Set-Location $ProjectRoot
function Invoke-Checked {
    param([string]$Program, [string[]]$Arguments)
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Program failed with exit code $LASTEXITCODE" }
}
function Get-ProjectPython {
    $Candidate = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path $Candidate)) { throw 'Run scripts/bootstrap_windows.ps1 first (Python 3.12 x64 is required for development).' }
    return $Candidate
}
