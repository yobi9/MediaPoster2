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
    excludes=[
        # Pillow's AVIF decoder is 7.9 MB and the app only reads .webp and
        # writes .jpg. ICC/PDF helpers are unused as well.
        'PIL._avif',
        'PIL.AvifImagePlugin',
        'PIL.ImageCms',
        'PIL.PdfParser',
    ],
    noarchive=False,
    optimize=2,
)

# --- size: drop the Qt translation files the app cannot use ---------------
# The app never installs a QTranslator - every visible string comes from the
# code - so Qt's per-locale .qm files are dead weight (99 files, ~7 MB before
# compression). Only the Arabic and English base files are kept.
_KEEP_QM = {"qtbase_ar.qm", "qtbase_en.qm"}

# --- size: drop Qt binaries the app never loads ----------------------------
# opengl32sw.dll is the Mesa software-OpenGL fallback (20.6 MB) and is only
# loaded by qwindows.dll when no hardware OpenGL is available; this app is
# plain QtWidgets with raster painting, so it never asks for it.
# Qt6Network.dll / Qt6Svg.dll have no static import from Qt6Gui, Qt6Widgets
# or any kept plugin, and the app imports neither PyQt6.QtNetwork nor
# PyQt6.QtSvg. The image-format plugins kept are qjpeg, qwebp and qico
# (the app handles .webp and .jpg), plus qwindows/qoffscreen/qminimal for
# the platform and the modern Windows style.
_DROP_BINARIES = {
    'opengl32sw.dll',
    'Qt6Network.dll',
    'Qt6Svg.dll',
    'qtiff.dll',
    'qgif.dll',
    'qicns.dll',
    'qtga.dll',
    'qwbmp.dll',
    'qsvg.dll',
    'qsvgicon.dll',
    'qtuiotouchplugin.dll',
}


def _norm(name):
    return name.replace("\\", "/")


def _is_unused_translation(name):
    n = _norm(name)
    if not n.startswith("PyQt6/Qt6/translations/"):
        return False
    return os.path.basename(n) not in _KEEP_QM


def _is_dropped_binary(name):
    return os.path.basename(_norm(name)) in _DROP_BINARIES


a.binaries = [
    b for b in a.binaries
    if not _is_unused_translation(b[0]) and not _is_dropped_binary(b[0])
]
a.datas = [d for d in a.datas if not _is_unused_translation(d[0])]

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
    # UPX was measured and rejected: it saved only ~2.9 MB but added ~20 MB of
    # RAM (the packed DLLs are expanded in memory at load time) and can trigger
    # SmartScreen warnings on other machines.
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
