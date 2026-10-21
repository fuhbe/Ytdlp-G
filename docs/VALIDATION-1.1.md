# Historical validation — 1.1.0

This release and its downloadable artifacts have been retired. Use
[VALIDATION.md](VALIDATION.md) for the current release.

The archived Windows build
completed successfully on `windows-latest`, from commit
`e7d835228c32606cf5a73737540adc47e57dd736`.

- 71 tests passed without failures, errors or skips.
- Ruff, formatting and Qt startup checks passed.
- Frozen, portable and installed packages passed 16 smoke checks each.
- Checks covered local HTTP links/playlists, native AAC extraction, ZIP integrity,
  conversion, remuxing and trimming.
- Inno Setup silent installation and uninstallation passed.
- Bundled Python 3.12.10, yt-dlp 2026.08.19, QuickJS-ng 0.17.0 and FFmpeg/FFprobe
  8.1.3 were recognized inside the packaged app.

| Historical file | Bytes | SHA256 |
| --- | ---: | --- |
| Ytdlp-G-Setup.exe | 153067658 | 5cf8d35a63a51f7dccd883acc81dab78044faa492be4b9d6f0d4d312f6b10251 |
| Ytdlp-G-portable.zip | 218772070 | 471cd8f58ae51cc4b177c41f3509acdac5021faacd976a026611f635f97b99f8 |
| Ytdlp-G.exe | — | 84efa1da478c79e1bee74c1599d24b06b60a3407f3d161c73eb17c3d082f6029 |

The portable ZIP was 17.1% smaller than 1.0.0; the installer was 16.7% smaller.
Downloaded files were checked against CI hashes. The executable requires the
other files in its package directory.

Original reports: [windows-build-6](validation/windows-build-6).
Build #5 was superseded to fix selection of individual videos embedded on the
same page. Build #6 verified that correction. The native quality selection uses
actual formats shared by accessible entries and does not silently fall back
when a selected quality disappears.

Validation was automated on Windows runners and Linux, using local synthetic
media. It did not establish manual Windows device or external-site coverage.
Binaries were unsigned. PyInstaller warnings about optional WebAssembly modules
and uninstalled integrations did not prevent the recorded functional tests.
