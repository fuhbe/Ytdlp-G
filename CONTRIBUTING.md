# Contributing to Ytdlp-G

Thanks for helping make Ytdlp-G simple and reliable. The current app is a compact
Windows downloader: link, available quality, regular files or ZIP, and optional
high-quality MP3. Changes should preserve this focused interface.

## Report a bug or suggest an improvement

Use the [issue templates](https://github.com/fuhbe/Ytdlp-G/issues/new/choose).
For bugs, include the app version, Windows version, installer or portable edition,
reproduction steps and exact error text. Attach a screenshot if it helps. Remove
private URLs, cookies, tokens, usernames and personal paths from shared logs.

For feature requests, describe the problem and how the change could fit the
compact workflow. Check existing issues first to avoid duplicate reports.

## Work on the code

See the [build guide](docs/BUILD_WINDOWS.md) to install dependencies and run the
app. Use Python 3.12 x64, PySide6 and the documented yt-dlp Python API. Keep user
interface text in all three catalogs under `src/ytdlp_g/i18n/`.

Before submitting a pull request:

```bash
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
```

On Windows, also run `scripts/build_windows.ps1` for changes affecting packaging,
media tools or the frozen app. Linux checks cannot establish Windows packaging
success. Describe which tests you actually ran and any known limits in your PR.

Preserve source files when operations fail. Keep progress tied to real work,
keep downloaded tools pinned and hash-verified, and retain third-party notices.
Use local synthetic media for repeatable tests. Add meaningful regression coverage
for behavior changes; documentation-only changes do not need new tests.

Small pull requests with a clear problem, resulting behavior and validation are
easier to review. Do not include generated packages, credentials or personal logs.
