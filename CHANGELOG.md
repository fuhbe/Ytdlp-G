# Changelog

## 1.3.0 — Updating engine, MP4 with sound and MP3-only audio

- Refresh the FFmpeg 8.1 shared build after the former upstream asset expired; verify its published checksum and GitHub asset digest.
- Bundle yt-dlp 2026.11.23 and check for stable engine updates daily before network operations.
- Add an **Update engine** button; verify downloads with SHA256 and install matching EJS scripts atomically in user data. Retain a working engine when offline or an update cannot load.
- Show only actual video resolutions with audio, including separate adaptive streams, and always deliver MP4. Normalize incompatible codecs to H.264/AAC when necessary.
- Offer MP3 as the only audio output: prefer existing MP3; otherwise convert the best available audio to MP3 at 320 kbps.
- Test mixed-codec adaptive streams, playlists, ZIPs, update integrity and frozen engine activation.

## 1.2.0 — High-quality MP3 and readable menus

- Add **MP3 · High quality** to the audio quality menu: download the best
  available audio and convert it to MP3 at 320 kbps. Preserve existing MP3 sources
  without re-encoding. Conversion does not improve source quality.
- Support MP3 with single links, playlists, regular files and ZIP output.
- Keep dropdown lists readable with a dark Windows palette using a light
  background, dark text and a blue selection with white text.
- Preserve the compact window's appearance and control layout.
- Verify Windows packages with 78 tests and 19 functional smoke checks per
  distribution, portable extraction and installation; see [validation](docs/VALIDATION.md).
- Publish English project documentation, contribution guides and issue templates.
- Retire earlier release downloads while preserving source history.

## 1.1.0 — Compact interface (retired release)

- Introduce a 600 × 440 window inspired by Windows 7 Aero.
- Analyze real source formats and show native quality choices shared by
  accessible playlist entries.
- Offer regular files or one verified ZIP, with cancelable analysis and downloads.
- Preserve native audio without re-encoding.
- Replace the bundled Deno runtime with QuickJS-ng to reduce download size.
- Verify Windows and Linux with 71 tests and packaged application smoke tests.

## 1.0.0 — Initial release (retired release)

- Introduce the classic PySide6 interface, three languages, yt-dlp downloads,
  SQLite queue/history and isolated workers.
- Add FFmpeg conversion, remuxing and trimming, verified ZIP creation,
  scheduling while the app is open, profiles and opt-in clipboard monitoring.
- Build Windows packages with PyInstaller and Inno Setup, including real media
  tests, installer checks and bundled dependency notices.

The classic implementation remains in the source tree for development. Its
advanced interface is not the default interface in the current Windows packages.
