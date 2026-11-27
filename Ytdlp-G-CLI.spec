from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_submodules, collect_data_files, copy_metadata

root = Path(SPECPATH)
ejs_data, ejs_bins, ejs_hidden = collect_all('yt_dlp_ejs')
data = collect_data_files('yt_dlp') + ejs_data + copy_metadata('yt-dlp') + copy_metadata('yt-dlp-ejs')
for src, dst in [('src/ytdlp_g/i18n/*.json','ytdlp_g/i18n'),('LICENSE','licenses'),('THIRD_PARTY_NOTICES.md','licenses'),('assets/licenses','licenses/upstream'),('build/dependencies/licenses','licenses/external'),('build/cli-licenses','licenses/python')]:
    data.append((str(root / src),dst))
a = Analysis(['scripts/cli_entry.py'],pathex=['src'],binaries=[(str(p),'bin') for p in (root/'build/dependencies/bin').iterdir() if p.is_file()]+ejs_bins,datas=data,hiddenimports=ejs_hidden+collect_submodules('yt_dlp',filter=lambda n:'__pyinstaller' not in n),excludes=['PySide6','tkinter','PyQt6'],runtime_hooks=['scripts/runtime_hook.py'])
pyz = PYZ(a.pure)
opts=dict(console=True,upx=False,icon=str(root/'assets/icons/app.ico'))
single=EXE(pyz,a.scripts,a.binaries,a.datas,[],name='Ytdlp-G-CLI',**opts)
portable=EXE(pyz,a.scripts,[],exclude_binaries=True,name='ytdlp-g',**opts)
coll=COLLECT(portable,a.binaries,a.datas,upx=False,name='cli-portable')
