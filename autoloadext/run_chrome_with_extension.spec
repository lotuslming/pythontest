# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

block_cipher = None

project_dir = Path(globals().get("SPECPATH", ".")).resolve()

# Bundle conf.ini into the one-file executable. At runtime it is available at:
#   Path(sys._MEIPASS) / "conf.ini"
datas = [(str(project_dir / "conf.ini"), ".")]

a = Analysis(
    ["run_chrome_with_extension.py"],
    pathex=[str(project_dir)],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="run_chrome_with_extension",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)
