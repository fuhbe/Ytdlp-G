# Building Ytdlp-G for Windows

The supported distribution target is **Windows 10/11 x64**. Build with Python
3.12 x64 (including the `py` launcher), PowerShell and Inno Setup 6. End users
need none of these tools: the packages include the runtime and media dependencies.

## Build all packages

Run from the repository root on Windows:

```powershell
.\scripts\build_windows.ps1
```

The scripts stop on errors:

1. `bootstrap_windows.ps1` creates a virtual environment, installs pinned packages
   from `requirements-build.lock` and installs the project.
2. `fetch_dependencies.ps1` downloads pinned FFmpeg/FFprobe and QuickJS-ng binaries,
   verifies SHA256 before execution and collects notices.
3. `test_windows.ps1` runs Ruff, format checks, pytest and the source UI/worker smoke test.
4. `build_portable.ps1` uses PyInstaller to bundle the windowed app, translations,
   yt-dlp extractors/EJS, Python, Qt, media tools and DLLs. It tests the frozen app,
   creates the portable ZIP, extracts it into a path containing spaces and tests it again.
5. `build_installer.ps1` builds the per-user Inno Setup installer with shortcuts
   and an uninstaller. The portable marker is excluded from the installation.

Outputs in `artifacts/` include `Ytdlp-G-portable.zip`, `Ytdlp-G-Setup.exe` and
`SHA256SUMS.txt`. The unpacked app is in `dist/Ytdlp-G/`. Generated binaries and
build directories are excluded from Git.

## Run from source

On Windows:

```powershell
.\scripts\bootstrap_windows.ps1
.\scripts\fetch_dependencies.ps1
$env:PATH = "$((Resolve-Path '.\build\dependencies\bin').Path);$env:PATH"
.\.venv\Scripts\python.exe -m ytdlp_g.main
```

For Linux/macOS development, install Python 3.12, FFmpeg/FFprobe and QuickJS-ng
on your PATH, then:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m ytdlp_g.main
```

Running or building on Linux does not produce a Windows executable.

## GitHub Actions

[Windows build](../.github/workflows/windows.yml) runs on `windows-latest` with
Python 3.12 x64. In addition to package tests, CI installs the installer silently,
tests the installed app and uninstalls it. The frozen smoke tests run with a PATH
that excludes the runner's Python and media tools, checking the bundled dependencies.

Successful builds upload versioned Windows artifacts. Validation reports are
uploaded even after failures; a validation report alone is not a working package.
Artifacts expire after 30 days. Published release assets provide the user-facing
downloads. The [release workflow](../.github/workflows/release.yml) publishes
assets from a successful build and verifies their checksums.

To build a fork, enable Actions and choose **Windows build → Run workflow**, or:

```bash
gh workflow run windows.yml
gh run list --workflow windows.yml
gh run download <RUN_ID> --dir artifacts-ci
```

The current distribution is **1.2.0**; older releases and downloadable artifacts
have been retired. Source history remains available in Git.
See [VALIDATION.md](VALIDATION.md) for the exact tested build and limits.

## Dependencies and reproducibility

`requirements-build.lock` pins Python packages. `scripts/dependencies.json` pins
binary URLs, hashes and source provenance. Review upstream sources, licenses and
hashes before changing these files, then run the full Windows build again.
An unavailable download or hash mismatch fails the build; there is no silent
fallback to an unpinned release. The distributed app does not run pip or update
itself remotely.

The recipes are versioned, but timestamps, runners and toolchains mean builds
are not promised to be byte-for-byte reproducible. No signing secret is configured;
current binaries are unsigned. Keep bundled notices and comply with the source
distribution obligations described in [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md)
when redistributing dependencies.
