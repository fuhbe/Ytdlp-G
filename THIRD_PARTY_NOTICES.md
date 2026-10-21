# Third-party notices

Ytdlp-G's own code and icon use the MIT license. This does **not** change the
licenses of its dependencies. Packages include replaceable executables/DLLs in
`_internal`, notices in `licenses/`, versions in `build-metadata.json` and the
source/hash manifest in `licenses/dependencies.json`.

| Component | License / source |
| --- | --- |
| Python 3.12 | PSF — https://www.python.org/downloads/source/ |
| PySide6/Shiboken6, Qt 6 | LGPLv3/GPLv3 or commercial, depending on the module — https://www.qt.io/licensing/open-source-lgpl-obligations ; https://download.qt.io/official_releases/QtForPython/ |
| yt-dlp | Unlicense; associated components retain their own licenses — https://github.com/yt-dlp/yt-dlp |
| yt-dlp-ejs | See the license included in the package — https://github.com/yt-dlp/ejs |
| FFmpeg and libraries in the BtbN GPL shared build | GPLv3 or later — https://ffmpeg.org/legal.html ; https://github.com/BtbN/FFmpeg-Builds |
| QuickJS-ng 0.17.0 | MIT — https://github.com/quickjs-ng/quickjs/tree/v0.17.0 |
| Requests, urllib3, certifi, Brotli, mutagen, PyCryptodome, websockets and other packages | Original notices collected in `licenses/python/manifest.json` |
| PyInstaller bootloader | GPL with an exception permitting application distribution — https://pyinstaller.org/en/stable/license.html |

FFmpeg runs as a separate process and is not linked into the Python code. The
selected build enables GPL libraries, including x264/x265; `ffmpeg -version`
reports its configuration. This FFmpeg binary is not represented as LGPL.
Compatible Qt and FFmpeg DLLs can be substituted; there is no prohibition on
debugging or reverse engineering to modify LGPL libraries. The build scripts
use neither UPX nor obfuscation.

When redistributing, retain all notices and meet the corresponding-source
obligations for the exact FFmpeg, library and Qt versions, including modifications
and build scripts. The manifest records the exact upstream build and the origin
of its scripts. Upstream links alone do not replace the corresponding-source
delivery obligations of a distribution. The application's source ZIP contains
Ytdlp-G code; it is not a complete source bundle for all third-party dependencies.

The build collects LICENSE/COPYING/NOTICE files from installed Python packages
and notices available in the FFmpeg archive. `requirements-build.lock` pins
package versions and `scripts/dependencies.json` pins helper executable SHA256
hashes. A hash mismatch stops the build before a downloaded dependency runs.
Dependencies do not update themselves.

PySide/Qt/Shiboken 6.12.0 and QuickJS-ng 0.17.0 license texts are explicitly included
in `licenses/upstream/`, even when a wheel lacks LICENSE files. Origins and SHA256
hashes are recorded in `assets/licenses/PROVENANCE.json`. Windows packages also
include the PSF license for the bundled Python runtime.
