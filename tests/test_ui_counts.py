from __future__ import annotations

import os
from pathlib import Path

import pytest

# يجب ضبط منصة العرض قبل إنشاء QApplication (بيئة اختبار بلا شاشة).
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from app.models import ItemResult, MediaItem, MediaKind, Status  # noqa: E402


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    instance = QApplication.instance()
    if instance is None:
        instance = QApplication([])
    return instance


def make_result(tmp_path: Path, status: Status, name: str) -> ItemResult:
    folder = tmp_path / name
    folder.mkdir(parents=True, exist_ok=True)
    item = MediaItem(path=folder, kind=MediaKind.MOVIE, title=name, year=2020)
    return ItemResult(item=item, status=status, message="اختبار")


def test_ui_counts_match_table_rows(qapp: QApplication, tmp_path: Path) -> None:
    """مجموع عدّادات الواجهة يجب أن يساوي عدد صفوف النتائج دائماً.

    الغرض: منع انحراف صامت بين ملخّص المحرك وملخّص الواجهة عند إضافة
    حالات جديدة لاحقاً (مثل PREVIEW).
    """
    from app.ui.main_window import MainWindow

    window = MainWindow()
    try:
        results = [
            make_result(tmp_path, Status.OK, "نجاح"),
            make_result(tmp_path, Status.PREVIEW, "معاينة"),
            make_result(tmp_path, Status.ERROR, "خطأ"),
            make_result(tmp_path, Status.SKIPPED, "متخطى"),
            make_result(tmp_path, Status.NOT_FOUND, "غير موجود"),
        ]
        for result in results:
            window._on_item(result)

        assert window.table.rowCount() == len(results)
        assert sum(window._counts.values()) == window.table.rowCount()
        assert window._counts["succeeded"] == 1
        assert window._counts["preview"] == 1
        assert window._counts["errors"] == 1
        assert window._counts["skipped"] == 1
        assert window._counts["not_found"] == 1
    finally:
        # close() يفصل QtLogHandler عن المسجّل (closeEvent)؛ deleteLater وحده
        # يُبقيه مربوطاً فيقتل أي سجل بعد موت النافذة.
        window.close()
