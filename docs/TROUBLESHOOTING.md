# Troubleshooting

## The app does not start

For the portable edition, extract the entire ZIP. Do not move `Ytdlp-G.exe` away
from `_internal` and the other files. Use a short path in a writable folder.
Windows 10/11 x64 is required; Windows 7 is not supported despite the Aero style.
The installer and portable archive include Python and the media tools.

Current binaries are unsigned, so SmartScreen may display a warning. Checksums
are available on the [release page](https://github.com/fuhbe/Ytdlp-G/releases/latest).
If startup still fails, report your Windows version, app version and package type
using the [bug template](https://github.com/fuhbe/Ytdlp-G/issues/new/choose).

## A download fails or no quality is available

Open the link on its original site to check whether the content still exists and
is accessible. Private, removed, DRM-protected or blocked content is not bypassed.
Site changes can also affect yt-dlp extraction. The packages include QuickJS-ng
and EJS for extractors that need JavaScript.

Analyze the URL again: source formats can change. The app does not invent missing
streams or silently replace a selected native quality. For playlists, native choices
must be shared by every accessible item; a mixed playlist may have few common
choices. Large playlists take longer because the app checks individual items.

## MP3 quality

After analysis, choose **Audio only → Quality → MP3 · High quality**. This downloads
the best available audio and converts it to MP3 at 320 kbps. Existing MP3 sources
are preserved. A higher output bitrate cannot restore detail absent from the source;
conversion between lossy formats can introduce additional loss.

## Cancellation and ZIP output

Cancel stops the worker and its media processes. It does not guarantee resumable
work. Partial files remain under `.ytdlp-g` in the destination; interrupted
post-processing may need to run again.

ZIP output needs temporary disk space in addition to space for the final archive.
Media already uses compression, so a ZIP may not be much smaller than its inputs.
Failures, permission errors and cancellation preserve downloaded media. Existing
files are never silently overwritten; duplicate names receive suffixes.

## Preferences and logs

Installed application data is in `%LOCALAPPDATA%\Ytdlp-G`. Portable data is in the
`data` directory beside the executable. Diagnostic logs are local. Remove private
URLs, personal paths and other sensitive details before attaching logs to an issue.

## Manual Windows checks for contributors

1. Install without elevation, launch using the shortcut and confirm no console opens.
2. Switch English, Portuguese and Spanish while fields are filled; verify saved preferences.
3. Check 100%, 150% and 200% display scaling, dark Windows settings, keyboard focus and Narrator.
4. Analyze authorized media, choose a native quality and verify the downloaded file.
5. Convert a single link and a playlist to MP3; test regular files and one ZIP.
6. Cancel during analysis, download and conversion; check partial-file preservation and process cleanup.
7. Test an unwritable destination and insufficient space; confirm originals remain intact.
8. Uninstall and confirm downloaded media and user data are preserved.

Automated runner tests do not establish all of these manual checks or support
for every external service. See [VALIDATION.md](VALIDATION.md) for recorded evidence.
