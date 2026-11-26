# Windows validation — Ytdlp-G 1.2.0

Recorded on **2026-10-21** for the current release.

- Windows build #10 (before repository migration): **success**.
- Built code: `be57c65022763818982e7cc77543cc315e537441`.
- Runner: `windows-latest`, Python 3.12.10 x64.
- Bundled tools: yt-dlp 2026.08.19, QuickJS-ng 0.17.0,
  FFmpeg/FFprobe n8.1.3-20-gc8de997cb1.
- Release publication before repository migration: **success**.

| Check | Result / evidence |
| --- | --- |
| Ruff lint and formatting | Passed in Windows build |
| Pytest | **78 passed**, no failures, errors or skips — [JUnit](validation/windows-build-10/test-results.xml) |
| Frozen x64 GUI executable | **19 smoke checks passed** — [report](validation/windows-build-10/packaged-smoke.json) |
| Portable ZIP extracted into a path with spaces | **19 smoke checks passed** — [report](validation/windows-build-10/portable-smoke.json) |
| Inno Setup installer | Built successfully; silent installation passed |
| Installed app | **19 smoke checks passed** — [report](validation/windows-build-10/installed-smoke.json) |
| Silent uninstallation | Passed |
| Release assets and checksums | Uploaded and verified |

The smoke tests execute the frozen executable and its workers with the runner's
Python and media tools excluded from PATH. They check the x64 GUI subsystem,
bundled runtime/tools, UI startup, real conversion/remux operations, ZIP integrity,
and downloads from a local HTTP server using generated media.

Version 1.2.0 adds coverage for best-audio MP3 conversion at 320 kbps (verified
with FFprobe), preserving native MP3 bytes, playlist MP3/ZIP output, cancellation,
and readable dropdowns under a dark palette. The Linux suite also passed all
78 tests during release development. The reports record the executable's SHA256
and dependency versions.

## Downloads

[Latest release](https://github.com/fuhbe/Ytdlp-G/releases/latest) includes the
installer, portable ZIP, source snapshot, validation reports and SHA256 checksums.
The portable archive contains `Ytdlp-G.exe` and its required adjacent files.
Older release downloads have been retired; their development history remains in Git.

## Scope and limitations

These are automated Windows runner results, not manual certification on every
Windows 10/11 device. Manual accessibility, DPI and device coverage, and support
for every external website, have not been established. The media tests use local
synthetic content, not live third-party website downloads. The binaries are unsigned.

Documentation-only updates after this build do not change the verified release
binaries or extend these test claims.
