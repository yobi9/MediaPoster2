from __future__ import annotations

import os
from pathlib import Path

import pytest

# يجب ضبط منصة العرض قبل إنشاء QApplication (بيئة اختبار بلا شاشة).
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from app.config import AppConfig  # noqa: E402


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    instance = QApplication.instance()
    if instance is None:
        instance = QApplication([])
    return instance


@pytest.fixture(scope="module")
def window(qapp: QApplication):
    """نافذة واحدة للوحدة كلها، بلا أي كتابة على config.json الحقيقي.

    نافذة MainWindow تسجّل QtLogHandler يحمل LogEmitter؛ حذفها بـdeleteLater
    يُبقي المعالج مربوطاً بالمسجّل فيقتل أي سجل لاحق ("wrapped C/C++ object
    ... has been deleted"). لذلك نُغلقها بـclose() الذي يفصل المعالج (نفس
    مسار closeEvent في التطبيق الحقيقي).
    """
    from app.ui.main_window import MainWindow

    original_save = AppConfig.save
    AppConfig.save = lambda self, path=None: None
    win = MainWindow()
    try:
        yield win
    finally:
        win.close()
        AppConfig.save = original_save


def test_output_root_round_trips_through_the_field(
    window, tmp_path: Path
) -> None:
    """حقل مجلد الإخراج يعرض الإعداد المحفوظ ويكتبه مرة أخرى."""
    output = tmp_path / "Artwork"
    window.config.output_root = str(output)

    window._restore_state()
    assert window.output_edit.text() == str(output)

    other = tmp_path / "Posters"
    window.output_edit.setText(str(other))
    window._sync_config_from_ui()

    assert Path(window.config.output_root).name == "Posters"
    assert other.is_dir()


def test_unusable_output_root_is_not_persisted(
    window, tmp_path: Path
) -> None:
    """مسار إخراج غير قابل للإنشاء لا يُحفظ في الإعدادات (ولا يكسر الواجهة)."""
    blocker = tmp_path / "blocked"
    blocker.write_text("ليس مجلداً", encoding="utf-8")
    window.config.output_root = ""

    window.output_edit.setText(str(blocker / "Artwork"))
    window._sync_config_from_ui()

    assert window.config.output_root == ""


def test_clearing_output_root_restores_source_writes(
    window, tmp_path: Path
) -> None:
    """ترك الحقل فارغاً يعيد الكتابة داخل المكتبة."""
    window.config.output_root = str(tmp_path / "Old")

    window.output_edit.setText("")
    window._sync_config_from_ui()

    assert window.config.output_root == ""


def test_image_type_checkboxes_reflect_config(window) -> None:
    """UI1: ثلاث رقائق (Poster/Fanart/Background) تُقرأ من AppConfig."""
    window.config.download_poster = True
    window.config.download_fanart = True
    window.config.download_background = False

    window._restore_state()

    assert window.poster_chip.isChecked() is True
    assert window.fanart_chip.isChecked() is True
    assert window.background_chip.isChecked() is False


def test_image_type_checkboxes_write_back(window) -> None:
    """UI2: تغيير الرقائق يُحدّث AppConfig عبر _sync_config_from_ui."""
    window.poster_chip.setChecked(False)
    window.fanart_chip.setChecked(True)
    window.background_chip.setChecked(True)

    window._sync_config_from_ui()

    assert window.config.download_poster is False
    assert window.config.download_fanart is True
    assert window.config.download_background is True


def test_all_image_types_off_shows_a_visual_warning(window) -> None:
    """تعطيل الأنواع الثلاثة يُظهر تحذيراً بصرياً (ولا يمنع التشغيل)."""
    window.poster_chip.setChecked(False)
    window.fanart_chip.setChecked(False)
    window.background_chip.setChecked(False)

    assert window.images_warning.isHidden() is False

    window.poster_chip.setChecked(True)

    assert window.images_warning.isHidden() is True


def test_no_cross_type_fallback_option_in_ui_or_client(window) -> None:
    """AC-12: لا يوجد خيار cross_type_fallback في واجهة المستخدم أو عميل TMDB."""
    import inspect

    from app.services.tmdb import TMDBClient

    sig = inspect.signature(TMDBClient.__init__)
    assert "cross_type_fallback" not in sig.parameters

    # لا يوجد عنصر واجهة للتحكم في cross_type_fallback
    assert not hasattr(window, "cross_type_fallback_chip")
    assert not hasattr(window, "cross_type_fallback_combo")
