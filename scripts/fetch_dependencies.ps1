. "$PSScriptRoot/common.ps1"
$Manifest = Get-Content 'scripts/dependencies.json' -Raw | ConvertFrom-Json
$DependencyRoot = Join-Path $ProjectRoot 'build\dependencies'
$BinRoot = Join-Path $DependencyRoot 'bin'
$LicenseRoot = Join-Path $DependencyRoot 'licenses'
New-Item -ItemType Directory -Force $BinRoot, $LicenseRoot | Out-Null
foreach ($Name in @('ffmpeg', 'quickjs')) {
    $Entry = $Manifest.$Name
    $Extension = if ($Name -eq 'quickjs') { 'exe' } else { 'zip' }
    $Archive = Join-Path $DependencyRoot "$Name.$Extension"
    if (-not (Test-Path $Archive)) { Invoke-WebRequest -Uri $Entry.url -OutFile $Archive }
    $Actual = (Get-FileHash $Archive -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($Actual -ne $Entry.sha256) {
        Remove-Item $Archive
        throw "SHA256 mismatch for $Name. Refusing to extract or execute. Update the manifest only after independently verifying the upstream release."
    }
    $Extract = Join-Path $DependencyRoot $Name
    if (Test-Path $Extract) { Remove-Item $Extract -Recurse -Force }
    if ($Name -eq 'ffmpeg') { Expand-Archive $Archive $Extract }
    if ($Name -eq 'ffmpeg') {
        $Executable = Get-ChildItem $Extract -Recurse -Filter 'ffmpeg.exe' | Select-Object -First 1
        if (-not $Executable) { throw 'FFmpeg executable absent from archive.' }
        Copy-Item (Join-Path $Executable.Directory.FullName 'ffmpeg.exe') $BinRoot -Force
        Copy-Item (Join-Path $Executable.Directory.FullName 'ffprobe.exe') $BinRoot -Force
        Get-ChildItem $Executable.Directory.FullName -Filter '*.dll' | Copy-Item -Destination $BinRoot -Force
        $NoticeDir = Join-Path $LicenseRoot 'ffmpeg'
        New-Item -ItemType Directory -Force $NoticeDir | Out-Null
        Get-ChildItem $Extract -Recurse -File | Where-Object { $_.Name -match '(?i)license|copying|readme' } | ForEach-Object {
            Copy-Item $_.FullName (Join-Path $NoticeDir $_.Name) -Force
        }
    } else {
        Copy-Item $Archive (Join-Path $BinRoot 'qjs.exe') -Force
    }
}
Copy-Item 'scripts/dependencies.json' $LicenseRoot -Force
Invoke-Checked (Join-Path $BinRoot 'ffmpeg.exe') @('-version')
Invoke-Checked (Join-Path $BinRoot 'ffprobe.exe') @('-version')
Invoke-Checked (Join-Path $BinRoot 'qjs.exe') @('-e', 'console.log(6 * 7)')
Write-Host 'Dependencies downloaded with pinned SHA256 checks.'
