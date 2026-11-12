"""P9-4: زر «إيقاف» في الواجهة يعمل أثناء فحص المكتبة."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from app.config import AppConfig  # noqa: E402
from app.models import MediaItem, MediaKind  # noqa: E402


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    instance = QApplication.instance()
    if instance is None:
        instance = QApplication([])
    return instance


def test_stop_button_cancels_during_scan(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """RunWorker يمرّر should_cancel للفحص ويُنهي بحالة ملغاة."""
    from app.ui import worker as worker_module

    folder = tmp_path / "Movie"
    folder.mkdir()
    (folder / "movie.mkv").write_bytes(b"")
    item = MediaItem(path=folder, kind=MediaKind.MOVIE, title="Movie", year=2020)

    worker = worker_module.RunWorker(
        AppConfig(library_path=str(tmp_path)), tmp_path, "TESTTOKEN"
    )
    captured: dict[str, object] = {}
    # QThread.requestInterruption() لا يُسجّل الطلب إلا أثناء تشغيل فعلي،
    # فنُحاكي ما يراه العامل داخل الخيط عند ضغط «إيقاف».
    stopped = {"requested": False}
    monkeypatch.setattr(
        worker, "isInterruptionRequested", lambda: stopped["requested"]
    )

    def fake_discover(root, media_filter="all", *, should_cancel=None):
        captured["should_cancel"] = should_cancel
        assert should_cancel is not None and should_cancel() is False
        stopped["requested"] = True  # المستخدم ضغط «إيقاف» أثناء الفحص
        assert should_cancel() is True
        return [item]

    monkeypatch.setattr(worker_module, "discover_media", fake_discover)
    worker.finished_ok.connect(
        lambda summary: captured.__setitem__("summary", summary)
    )

    worker.run()

    summary = captured["summary"]
    assert summary.cancelled is True
    assert summary.total == 1
