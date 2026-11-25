# -*- mode: python ; coding: utf-8 -*-
# Build with:  pyinstaller build.spec        ->  dist/AMT.exe
#
# Name, version and author come from src/brand.py, so the file's Properties
# dialog in Explorer always matches the app's own About text.
import os
import sys

sys.path.insert(0, os.path.abspath(SPECPATH))
from src import brand  # noqa: E402

from PyInstaller.utils.win32.versioninfo import (  # noqa: E402
    FixedFileInfo, StringFileInfo, StringStruct, StringTable,
    VarFileInfo, VarStruct, VSVersionInfo,
)

_v = tuple(int(p) for p in brand.VERSION.split(".")) + (0,)
version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=_v, prodvers=_v),
    kids=[
        StringFileInfo([StringTable("040904B0", [
            StringStruct("ProductName", brand.APP_NAME),
            StringStruct("FileDescription", brand.APP_NAME),
            StringStruct("CompanyName", brand.AUTHOR),
            StringStruct("LegalCopyright", f"{brand.COPYRIGHT} · {brand.LICENSE_NAME}"),
            StringStruct("OriginalFilename", f"{brand.APP_SHORT}.exe"),
            StringStruct("FileVersion", brand.VERSION),
            StringStruct("ProductVersion", brand.VERSION),
        ])]),
        VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
    ],
)

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('assets/fonts', 'assets/fonts'),     # bundled Inter + JetBrains Mono
           ('assets/amt.ico', 'assets'),          # window / taskbar icon
           ('docs/GUIDE.md', 'docs'),             # the in-app Help page
           ('docs/images', 'docs/images')],
    hiddenimports=[
        'pynput.keyboard._win32',
        'pynput.mouse._win32',
        'PyQt6.sip',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name=brand.APP_SHORT,   # AMT.exe
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,              # UPX-packed files trip antivirus heuristics more often
    runtime_tmpdir=None,
    console=False,          # no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/amt.ico',
    version=version_info,
)
