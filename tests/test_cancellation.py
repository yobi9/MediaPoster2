"""P9: إلغاء مُعمَّم للفحص وتحويل WebP وإشارة Ctrl+C في الـCLI."""

from __future__ import annotations

import logging
import signal
from pathlib import Path

from PIL import Image

from app import cli
from app.config import AppConfig


def make_library(root: Path, count: int) -> list[Path]:
    folders: list[Path] = []
    for index in range(count):
        folder = root / f"Movie {index:02d}"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"movie{index}.mkv").write_bytes(b"")
        folders.append(folder)
    return folders


def test_scan_stops_after_cancellation(tmp_path: Path) -> None:
    """P9-1: الإلغاء بعد 3 مجلدات من 10 ⇒ 3 عناصر فقط بلا استثناء."""
    from app.services.scanner import discover_media

    library = tmp_path / "library"
    make_library(library, 10)
    state = {"calls": 0}

    def should_cancel() -> bool:
        # يُستدعى مرة قبل الجذر ثم مرة قبل كل مجلد: 4 نداءات = 3 عناصر.
        state["calls"] += 1
        return state["calls"] > 4

    items = discover_media(library, "all", should_cancel=should_cancel)

    assert len(items) == 3
    assert state["calls"] > 4


def test_webp_conversion_stops_between_files(tmp_path: Path) -> None:
    """P9-2: الإلغاء بعد ملف واحد ⇒ converted=1 بلا خطأ + cancelled=True."""
    from app.services.images import convert_webp_in_folder

    folder = tmp_path / "item"
    folder.mkdir()
    for index in range(3):
        Image.new("RGB", (8, 8), (index * 40, 0, 0)).save(
            folder / f"img{index}.webp", format="WEBP"
        )
    state = {"calls": 0}

    def should_cancel() -> bool:
        state["calls"] += 1
        return state["calls"] > 1

    result = convert_webp_in_folder(folder, should_cancel=should_cancel)

    assert result.converted == 1
    assert result.cancelled is True
    assert len(list(folder.glob("*.jpg"))) == 1


def test_cli_sigint_returns_130_with_message(
    monkeypatch, tmp_path: Path
) -> None:
    """P9-3: Ctrl+C أثناء الفحص ⇒ رمز 130 ورسالة بعدد العناصر."""
    library = tmp_path / "library"
    make_library(library, 2)

    messages: list[str] = []
    logger = logging.getLogger("mediaart.cli")

    class Collector(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            messages.append(record.getMessage())

    handler = Collector()
    logger.addHandler(handler)

    def fake_discover(root, media_filter="all", *, should_cancel=None):
        assert should_cancel is not None
        signal.raise_signal(signal.SIGINT)
        return []

    monkeypatch.setattr(
        cli,
        "load_config",
        lambda: AppConfig(library_path=str(library), convert_only=True),
    )
    monkeypatch.setattr(cli, "discover_media", fake_discover)
    try:
        code = cli.run_cli(
            cli.build_parser().parse_args(
                ["--cli", "--path", str(library), "--convert-only"]
            )
        )
    finally:
        logger.removeHandler(handler)

    assert code == 130
    assert any(
        "تم الإلغاء بواسطة المستخدم" in message and "0 عنصر" in message
        for message in messages
    )
