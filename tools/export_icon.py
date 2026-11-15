r"""Export the application icon to assets/icon.ico.

The icon is not a new artwork: it is the mark the application already draws at
runtime (app.ui.theme.make_app_icon), rendered once at 256 px and downscaled,
so the installer icon and the running window show the same design.

The export runs headless (QT_QPA_PLATFORM=offscreen). That platform ships an
empty font database, so Segoe UI is loaded explicitly from the Windows font
folder - otherwise the letter "M" is drawn as a missing-glyph box. The script
fails instead of writing a broken icon.

Run from the project root:
    .venv\Scripts\python.exe tools\export_icon.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# Must be set before the Qt application is created: the export runs headless.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image  # noqa: E402
from PyQt6.QtGui import QFont, QFontDatabase, QFontInfo  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ui.theme import make_app_icon  # noqa: E402

SIZES = (16, 32, 48, 256)
MASTER = 256
FONT_FAMILY = "Segoe UI"
FONT_FILES = ("segoeui.ttf", "segoeuib.ttf")


def load_font_family() -> None:
    """Register Segoe UI so the headless render can draw the letter."""
    fonts_dir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    loaded = []
    for name in FONT_FILES:
        path = fonts_dir / name
        if not path.is_file():
            raise SystemExit(f"[X] font not found: {path}")
        font_id = QFontDatabase.addApplicationFont(str(path))
        if font_id < 0:
            raise SystemExit(f"[X] cannot load font: {path}")
        loaded.extend(QFontDatabase.applicationFontFamilies(font_id))
    if FONT_FAMILY not in loaded:
        raise SystemExit(f"[X] family {FONT_FAMILY!r} not registered (got {loaded})")


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    out = root / "assets" / "icon.ico"
    out.parent.mkdir(parents=True, exist_ok=True)

    app = QApplication.instance() or QApplication([])
    load_font_family()

    resolved = QFontInfo(QFont(FONT_FAMILY, int(MASTER * 0.38), QFont.Weight.Bold)).family()
    if resolved != FONT_FAMILY:
        raise SystemExit(f"[X] font not resolved: {resolved!r} != {FONT_FAMILY!r}")

    icon = make_app_icon(MASTER)
    pixmap = icon.pixmap(MASTER)

    with tempfile.TemporaryDirectory() as tmp:
        png = Path(tmp) / "master.png"
        pixmap.save(str(png), "PNG")
        master = Image.open(png).convert("RGBA")

    master.save(out, format="ICO", sizes=[(s, s) for s in SIZES])
    print(f"wrote {out} ({out.stat().st_size} bytes)")
    print("sizes:", sorted(Image.open(out).ico.sizes()))
    print("font:", resolved)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
