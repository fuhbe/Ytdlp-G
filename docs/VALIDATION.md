# Validation — Ytdlp-G 1.3.0

The Windows build workflow gates stable publication on lint, formatting, the full pytest suite, three frozen executable smoke runs (package, relocated portable ZIP and installed application), and successful installer/uninstaller execution. Reports are attached to the release as `Ytdlp-G-validation.zip` and retained as Actions artifacts.

The development suite passed 90 tests on Linux with FFmpeg/FFprobe. New coverage verifies:

- Official stable yt-dlp + matching EJS update installation, SHA256 rejection, traversal rejection, Python compatibility, daily cadence, concurrent-update locking, offline fallback and worker import precedence.
- Available source resolutions, exclusion of silent video, MP4 choices shared across different source codecs.
- Real separate VP9/Vorbis streams downloaded over local HTTP, merged and converted to MP4 H.264/AAC; FFprobe verifies video, audio and selected resolution.
- Audio-only MP3 at 320 kbps, original MP3 preservation, playlists and ZIP integrity.
- The Windows smoke script forces an actual PyPI engine installation, starts a fresh frozen worker and asserts that it uses the managed engine before exercising media downloads.

A live YouTube test using yt-dlp 2026.11.23 and QuickJS-ng 0.17.0 was attempted. The development network proxy rejected the YouTube connection with HTTP 403; live YouTube support could not be verified here. Automated media downloads use generated authorized fixtures on a local HTTP server. These checks do not certify every external site or Windows device.

The bundled engine is yt-dlp 2026.11.23. Runtime updates may be newer, as recorded in the Windows smoke reports. Updates use immutable per-user directories, with atomic activation and fallback when a new engine cannot load. The media toolchain remains bundled and pinned by the app release.

For earlier release evidence see [1.2.0 validation](VALIDATION-1.2.md).
