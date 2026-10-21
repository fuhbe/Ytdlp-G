# Current features and verification

The Windows release uses the compact interface. The classic interface is retained
in the source tree as a historical developer reference, not exposed as additional
pages in the current app.

| Feature | Behavior | Verification / limits |
| --- | --- | --- |
| Compact window | 600 × 440, Aero-inspired, readable light dropdowns | Qt UI tests, dark-palette rendering tests; manual DPI/accessibility coverage remains limited |
| Languages | English, Brazilian Portuguese, Spanish | Catalog parity and live UI switching tests |
| Link analysis | Video, audio or playlist metadata through yt-dlp | Local HTTP and controlled fixtures; external site availability varies |
| Native qualities | Source formats; common choices for accessible playlist entries | Format selection and playlist tests; formats can change after analysis |
| MP3 | Best available audio converted to 320 kbps MP3; native MP3 preserved | FFprobe bitrate/codec checks and byte-for-byte preservation tests |
| Output | Regular files or a single ZIP | SHA256/CRC verification; originals preserved on failure |
| Cancellation | Stop analysis or download workers | Task/process tests; partial media retained in destination staging directory |
| Destination | User-selected folder; collision-safe publication | Windows path, naming and concurrent publication tests |
| Windows distribution | Bundled Python/Qt, yt-dlp, FFmpeg/FFprobe and QuickJS-ng | Frozen app, extracted portable ZIP and installed app smoke tests |
| Local preferences | Installed user data or portable `data` directory | Settings validation and persistence tests |

See [VALIDATION.md](VALIDATION.md) for exact build results and downloadable evidence.
The app does not promise support for every site or bypass access restrictions.
