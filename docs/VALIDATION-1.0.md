# Historical validation — 1.0.0

This release and its downloadable artifacts have been retired. Source history
and the recorded reports remain available; use [VALIDATION.md](VALIDATION.md)
for the current release.

The archived Windows build
completed successfully on 2026-10-21:

- 62 Windows tests passed without skips; lint and formatting passed.
- An x64 GUI executable included Python and media dependencies.
- The frozen app, extracted portable ZIP and installed app passed 10 functional
  smoke checks each, with runner tools excluded from PATH.
- Inno Setup silent installation and uninstallation passed.
- Linux also passed 62 tests after the Windows fixes.

The fixes separated yt-dlp's output directory from its filename template,
replaced a racy Windows reservation lock with atomic publication and corrected
case-insensitive environment handling in the smoke driver. Tests were retained.

Original reports: [windows-build-4](validation/windows-build-4).
The build collected dependency notices, including Python, Qt/PySide/Shiboken and
the Deno runtime used at that time. Later releases switched to QuickJS-ng.

Tests used local synthetic media and automated runners. Manual Windows device,
DPI, Narrator, tray and external-service coverage was not established. Binaries
were unsigned.
