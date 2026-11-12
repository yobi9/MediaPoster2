# -*- mode: python ; coding: utf-8 -*-

import os

# Build mode is chosen by the BUILD_MODE environment variable:
#   "gui" (default) -> MediaArtAutoSync.exe       (windowed, no console)
#   "cli"           -> MediaArtAutoSync-cli.exe   (console, for automation)
BUILD_MODE = os.environ.get("BUILD_MODE", "gui").strip().lower()
IS_CLI = BUILD_MODE == "cli"
EXE_NAME = "MediaArtAutoSync-cli" if IS_CLI else "MediaArtAutoSync"

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('README.md', '.')],
    hiddenimports=['PyQt6'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=EXE_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=IS_CLI,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
