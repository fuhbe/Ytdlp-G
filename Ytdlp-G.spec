# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules
from PySide6.QtCore import QLibraryInfo

root = Path(SPECPATH)
yt_data = collect_data_files('yt_dlp', include_py_files=False)
yt_binaries = []
yt_hidden = collect_submodules('yt_dlp', filter=lambda name: not name.startswith('yt_dlp.__pyinstaller'))
ejs_data, ejs_binaries, ejs_hidden = collect_all('yt_dlp_ejs')
bin_dir = root / 'build' / 'dependencies' / 'bin'
helpers = [(str(path), 'bin') for path in bin_dir.iterdir() if path.suffix.lower() == '.dll' or path.name.lower() in {'ffmpeg.exe', 'ffprobe.exe', 'qjs.exe'}]
data = [(str(root / 'src/ytdlp_g/i18n'), 'ytdlp_g/i18n'), (str(root / 'src/ytdlp_g/resources'), 'ytdlp_g/resources')]
for language in ('pt_BR', 'es'):
    translation = Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)) / f'qtbase_{language}.qm'
    if translation.exists():
        data.append((str(translation), 'ytdlp_g/resources/translations'))
analysis = Analysis(
    [str(root / 'scripts/entry.py')], pathex=[str(root / 'src')],
    binaries=helpers + yt_binaries + ejs_binaries,
    datas=data + yt_data + ejs_data,
    hiddenimports=yt_hidden + ejs_hidden + collect_submodules('ytdlp_g', filter=lambda name: name not in {'ytdlp_g.main_classic', 'ytdlp_g.ui.window'}),
    hookspath=[], hooksconfig={}, runtime_hooks=[str(root / 'scripts/runtime_hook.py')],
    excludes=['ytdlp_g.main_classic', 'ytdlp_g.ui.window', 'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'PySide6.QtQml', 'PySide6.QtQuick', 'tkinter'],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
exe = EXE(pyz, analysis.scripts, [], exclude_binaries=True, name='Ytdlp-G',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
          console=False, disable_windowed_traceback=False,
          icon=str(root / 'assets/icons/app.ico'), version=str(root / 'installer/version.txt'))
coll = COLLECT(exe, analysis.binaries, analysis.datas, strip=False, upx=False, name='Ytdlp-G')
