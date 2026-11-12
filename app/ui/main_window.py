"""Main window: Arabic RTL dark UI, live console, results table, progress."""

from __future__ import annotations

import html
import logging
import os
import sys
import time
from pathlib import Path

from PyQt6.QtCore import QSettings, Qt, QTime, QTimer, QUrl
from PyQt6.QtGui import QColor, QDesktopServices, QFont
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..config import (
    APP_NAME,
    DATA_DIR,
    LOG_PATH,
    MEDIA_FILTERS,
    SUPPORTED_LANGUAGES,
    VERSION,
    ensure_output_root,
    env_token_present,
    load_config,
    resolve_token,
)
from ..logging_setup import get_logger, setup_logging
from ..models import ItemResult, RunSummary, Status
from .theme import LEVEL_COLORS, STATUS_COLORS, make_app_icon
from .worker import PingWorker, QtLogHandler, RunWorker

logger = get_logger("gui")
TMDB_KEYS_URL = "https://www.themoviedb.org/settings/api"


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        setup_logging()
        self.config = load_config()
        self._settings = QSettings("MediaArt", "AutoSync")
        self.worker: RunWorker | None = None
        self.ping_worker: PingWorker | None = None
        self._log_handler: QtLogHandler | None = None
        self._started_at = 0.0
        self._running = False
        self._dark_titlebar_done = False
        self._counts = {"succeeded": 0, "skipped": 0, "not_found": 0, "errors": 0, "preview": 0}
        self._last_summary: RunSummary | None = None

        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(make_app_icon())
        self.setMinimumSize(1000, 740)
        self.resize(1220, 900)
        self.setAcceptDrops(True)

        self._build_ui()
        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._tick)

        self._restore_state()
        self._install_log_bridge()
        self._update_mode_hint()
        self._set_running(False)
        logger.info("MediaArt Auto-Sync v%s جاهز. مجلد البيانات: %s", VERSION, DATA_DIR)

    # ==================================================================
    # UI construction
    # ==================================================================
    def _build_ui(self) -> None:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setCentralWidget(scroll)

        root = QWidget()
        root.setObjectName("Root")
        scroll.setWidget(root)

        outer = QVBoxLayout(root)
        outer.setContentsMargins(22, 18, 22, 12)
        outer.setSpacing(13)
        outer.addLayout(self._build_header())
        outer.addWidget(self._build_settings_card())
        outer.addWidget(self._build_progress_card())

        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.addWidget(self._build_console_card())
        self.splitter.addWidget(self._build_results_card())
        # متوازن: لا يفضّل السجل ولا النتائج، مع قابلية السحب للحاجة
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([260, 300])
        outer.addWidget(self.splitter, 1)
        outer.addLayout(self._build_footer())

        self.statusBar().setSizeGripEnabled(False)
        self.statusBar().showMessage("جاهز")

    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(14)

        logo = QLabel("M")
        logo.setObjectName("Logo")
        logo.setFixedSize(50, 50)
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)

        titles = QVBoxLayout()
        titles.setSpacing(1)
        title = QLabel(APP_NAME)
        title.setObjectName("AppTitle")
        subtitle = QLabel("المنظّم الذكي لملصقات وخلفيات مكتبة الوسائط — مدعوم بـ TMDB")
        subtitle.setObjectName("Subtitle")
        titles.addWidget(title)
        titles.addWidget(subtitle)

        badge = QLabel(f"TMDB API  •  v{VERSION}")
        badge.setObjectName("Badge")
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)

        row.addWidget(logo)
        row.addLayout(titles)
        row.addWidget(badge)
        row.addStretch(1)
        return row

    def _build_settings_card(self) -> QFrame:
        card, layout = self._new_card()
        heading = QHBoxLayout()
        heading.addWidget(self._card_title("المكتبة والإعدادات"))
        heading.addStretch(1)
        keys_link = QPushButton("كيف أحصل على مفتاح TMDB؟")
        keys_link.setObjectName("LinkButton")
        keys_link.setCursor(Qt.CursorShape.PointingHandCursor)
        keys_link.clicked.connect(self._open_tmdb_keys)
        heading.addWidget(keys_link)
        layout.addLayout(heading)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(9)
        grid.setColumnStretch(0, 0)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 0)

        path_label = QLabel("مجلد المكتبة *")
        path_label.setObjectName("FieldLabel")
        path_label.setToolTip("حقل مطلوب في جميع الأوضاع.")
        self.path_edit = QLineEdit()
        self.path_edit.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.path_edit.setPlaceholderText(r"D:\Media\Library  or  \\NAS\Media")
        self.path_edit.setClearButtonEnabled(True)
        self.path_edit.setToolTip("يمكنك أيضاً سحب مجلد وإفلاته داخل النافذة.")
        self.browse_btn = QPushButton("تصفح…")
        self.browse_btn.setObjectName("Ghost")
        self.browse_btn.clicked.connect(self._browse)
        grid.addWidget(path_label, 0, 0)
        grid.addWidget(self.path_edit, 0, 1)
        grid.addWidget(self.browse_btn, 0, 2)

        token_label = QLabel("مفتاح TMDB")
        token_label.setObjectName("FieldLabel")
        token_label.setToolTip("مطلوب ما لم يكن وضع «تحويل WebP فقط» مفعّلاً.")
        self.token_edit = QLineEdit()
        self.token_edit.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.token_edit.setPlaceholderText("API Key (v3) or Read Access Token (v4)")
        self.token_edit.setClearButtonEnabled(True)
        self.show_token_btn = QPushButton("إظهار")
        self.show_token_btn.setObjectName("Ghost")
        self.show_token_btn.setCheckable(True)
        self.show_token_btn.clicked.connect(self._toggle_token)
        self.test_btn = QPushButton("اختبار الاتصال")
        self.test_btn.setObjectName("Ghost")
        self.test_btn.clicked.connect(self._test_connection)
        token_actions = QHBoxLayout()
        token_actions.setSpacing(6)
        token_actions.addWidget(self.show_token_btn)
        token_actions.addWidget(self.test_btn)
        grid.addWidget(token_label, 1, 0)
        grid.addWidget(self.token_edit, 1, 1)
        grid.addLayout(token_actions, 1, 2)

        output_label = QLabel("مجلد إخراج الصور")
        output_label.setObjectName("FieldLabel")
        output_label.setToolTip("اختياري: للمكتبات للقراءة فقط (NAS). اتركه فارغاً للكتابة في المكتبة.")
        self.output_edit = QLineEdit()
        self.output_edit.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.output_edit.setPlaceholderText(r"(اختياري) E:\Posters  —  للمكتبات للقراءة فقط")
        self.output_edit.setClearButtonEnabled(True)
        self.output_edit.setToolTip(
            "إذا مُلئ، تُكتب poster/fanart/background في هذا المجلد بنفس المسار النسبي "
            "من جذر المكتبة، مع ملف .mediaart_manifest.json. المصدر لا يُلمس."
        )
        self.output_browse_btn = QPushButton("تصفح…")
        self.output_browse_btn.setObjectName("Ghost")
        self.output_browse_btn.clicked.connect(self._browse_output)
        grid.addWidget(output_label, 2, 0)
        grid.addWidget(self.output_edit, 2, 1)
        grid.addWidget(self.output_browse_btn, 2, 2)

        options = QGridLayout()
        options.setHorizontalSpacing(12)
        options.setVerticalSpacing(4)
        options.setColumnStretch(0, 1)
        options.setColumnStretch(1, 1)
        options.setColumnStretch(2, 1)
        self.lang_combo = QComboBox()
        for code, name in SUPPORTED_LANGUAGES:
            self.lang_combo.addItem(f"{name}", code)
        self.lang_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.quality_combo = QComboBox()
        for value in sorted({80, 85, 90, 95, 100, self.config.jpeg_quality}):
            self.quality_combo.addItem(f"{value}%", value)
        self.quality_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.media_combo = QComboBox()
        for key, label in MEDIA_FILTERS:
            self.media_combo.addItem(label, key)
        self.media_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        options.addWidget(self._field_label("اللغة"), 0, 0)
        options.addWidget(self._field_label("جودة JPG"), 0, 1)
        options.addWidget(self._field_label("نوع الوسائط"), 0, 2)
        options.addWidget(self.lang_combo, 1, 0)
        options.addWidget(self.quality_combo, 1, 1)
        options.addWidget(self.media_combo, 1, 2)
        grid.addLayout(options, 3, 0, 1, 3)

        chips = QGridLayout()
        chips.setHorizontalSpacing(8)
        chips.setVerticalSpacing(8)
        chips.setColumnStretch(0, 1)
        chips.setColumnStretch(1, 1)
        chips.setColumnStretch(2, 1)
        self.overwrite_chip = self._chip(
            "استبدال الصور الموجودة",
            "إعادة تنزيل الملصق والخلفية حتى لو كانا موجودين.",
        )
        self.poster_chip = self._chip(
            "Poster",
            "تنزيل poster.jpg (الملصق القياسي).",
        )
        self.fanart_chip = self._chip(
            "Fanart",
            "تنزيل fanart.jpg (الخلفية الأفقية القياسية).",
        )
        self.background_chip = self._chip(
            "Background",
            "تنزيل background.jpg من نفس بيانات الخلفية (متوافق مع مشغلات مختلفة).",
        )
        self.convert_chip = self._chip(
            "تحويل WebP الموجود",
            "تحويل أي ملفات .webp داخل مجلد العمل إلى .jpg عالي الجودة.",
        )
        self.nested_chip = self._chip(
            "تحويل WebP داخل المواسم",
            "للمسلسلات فقط: تحويل ملفات WebP الموجودة داخل مجلدات المواسم أيضاً.",
        )
        self.dry_chip = self._chip(
            "معاينة فقط",
            "البحث في TMDB وعرض النتائج دون تنزيل أو كتابة أي ملف.",
        )
        self.convert_only_chip = self._chip(
            "تحويل WebP فقط",
            "وضع بدون إنترنت: تحويل الصور الموجودة فقط، دون الاتصال بـ TMDB.",
        )
        chip_list = (
            self.overwrite_chip,
            self.poster_chip,
            self.fanart_chip,
            self.background_chip,
            self.convert_chip,
            self.nested_chip,
            self.dry_chip,
            self.convert_only_chip,
        )
        for index, chip in enumerate(chip_list):
            row_index, col_index = divmod(index, 3)
            chips.addWidget(chip, row_index, col_index)
        grid.addLayout(chips, 4, 0, 1, 3)

        self.images_warning = QLabel(
            "تحذير: كل أنواع الصور معطّلة — لن يُنزَّل أي ملف صورة."
        )
        self.images_warning.setObjectName("Muted")
        self.images_warning.setWordWrap(True)
        self.images_warning.setStyleSheet("color: #f0a53a;")
        self.images_warning.setVisible(False)
        grid.addWidget(self.images_warning, 5, 0, 1, 3)

        self.mode_hint = QLabel()
        self.mode_hint.setObjectName("Muted")
        self.mode_hint.setWordWrap(True)
        grid.addWidget(self.mode_hint, 6, 0, 1, 3)

        for chip in (self.poster_chip, self.fanart_chip, self.background_chip):
            chip.toggled.connect(self._update_images_warning)
        self.dry_chip.toggled.connect(self._update_mode_hint)
        self.convert_only_chip.toggled.connect(self._update_mode_hint)

        layout.addLayout(grid)
        return card

    def _build_progress_card(self) -> QFrame:
        card, layout = self._new_card()

        top = QHBoxLayout()
        top.setSpacing(10)
        top.addWidget(self._card_title("التقدم والنتائج"))
        self.elapsed_label = QLabel("00:00")
        self.elapsed_label.setObjectName("Muted")
        self.elapsed_label.setToolTip("الوقت المنقضي")
        top.addWidget(self.elapsed_label)
        self.start_btn = QPushButton("بدء المعالجة")
        self.start_btn.setObjectName("Primary")
        self.start_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.start_btn.clicked.connect(self._start)
        top.addWidget(self.start_btn)
        self.stop_btn = QPushButton("إيقاف")
        self.stop_btn.setObjectName("Danger")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop)
        top.addWidget(self.stop_btn)
        top.addStretch(1)
        layout.addLayout(top)

        stats = QHBoxLayout()
        stats.setSpacing(10)
        self.stat_ok, self.stat_ok_value = self._make_stat("نجح", "#4ADE80")
        self.stat_skipped, self.stat_skipped_value = self._make_stat("متخطى", "#94A3B8")
        self.stat_not_found, self.stat_not_found_value = self._make_stat("غير موجود", "#FB923C")
        self.stat_errors, self.stat_errors_value = self._make_stat("أخطاء", "#F87171")
        self.stat_preview, self.stat_preview_value = self._make_stat("معاينة", "#A78BFA")
        for box in (
            self.stat_ok,
            self.stat_skipped,
            self.stat_not_found,
            self.stat_errors,
            self.stat_preview,
        ):
            stats.addWidget(box)
        layout.addLayout(stats)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)

        self.status_label = QLabel("جاهز للبدء")
        self.status_label.setObjectName("StatusLabel")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        return card

    def _build_console_card(self) -> QFrame:
        card, layout = self._new_card()
        card.setMinimumHeight(150)
        layout.setSpacing(8)

        head = QHBoxLayout()
        head.addWidget(self._card_title("السجل الحي"))
        head.addStretch(1)
        clear_btn = QPushButton("مسح")
        clear_btn.setObjectName("Ghost")
        clear_btn.setMinimumHeight(32)
        clear_btn.clicked.connect(self._clear_console)
        open_logs = QPushButton("فتح مجلد السجلات")
        open_logs.setObjectName("Ghost")
        open_logs.setMinimumHeight(32)
        open_logs.clicked.connect(self._open_data_dir)
        head.addWidget(clear_btn)
        head.addWidget(open_logs)
        layout.addLayout(head)

        self.console = QTextEdit()
        self.console.setObjectName("Console")
        self.console.setReadOnly(True)
        self.console.setAcceptRichText(True)
        self.console.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.console.document().setMaximumBlockCount(4000)
        self.console.setPlaceholderText("ستظهر هنا رسائل البدء والتنزيل والأخطاء…")
        layout.addWidget(self.console, 1)
        return card

    def _build_results_card(self) -> QFrame:
        card, layout = self._new_card()
        card.setMinimumHeight(180)
        layout.setSpacing(8)

        head = QHBoxLayout()
        head.addWidget(self._card_title("النتائج"))
        self.results_hint = QLabel("لم تبدأ المعالجة بعد")
        self.results_hint.setObjectName("Muted")
        head.addWidget(self.results_hint)
        head.addStretch(1)
        layout.addLayout(head)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["الحالة", "العنوان", "النوع", "المسار"])
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.table.setCursor(Qt.CursorShape.PointingHandCursor)
        self.table.doubleClicked.connect(self._open_result_folder)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(1, 280)
        layout.addWidget(self.table, 1)
        return card

    def _build_footer(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        # عزل اتجاه المسار (LTR) داخل نص RTL حتى لا ينعكس بالخطأ
        self.storage_label = QLabel(f"السجلات والإعدادات: \u2066{DATA_DIR}\u2069")
        self.storage_label.setObjectName("Muted")
        self.storage_label.setToolTip(str(LOG_PATH))
        self.storage_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.storage_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        row.addWidget(self.storage_label)
        row.addStretch(1)
        readme_btn = QPushButton("دليل الاستخدام")
        readme_btn.setObjectName("Ghost")
        readme_btn.clicked.connect(self._open_readme)
        data_btn = QPushButton("فتح مجلد البيانات")
        data_btn.setObjectName("Ghost")
        data_btn.clicked.connect(self._open_data_dir)
        row.addWidget(readme_btn)
        row.addWidget(data_btn)
        return row

    # ------------------------------------------------------------------
    def _new_card(self) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("Card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 15, 18, 15)
        layout.setSpacing(11)
        return card, layout

    def _card_title(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("CardTitle")
        return label

    def _field_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("FieldLabel")
        return label

    def _chip(self, text: str, tooltip: str = "") -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("Chip")
        button.setCheckable(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        button.setMinimumHeight(34)
        if tooltip:
            button.setToolTip(tooltip)
        return button

    def _make_stat(self, caption: str, color: str) -> tuple[QFrame, QLabel]:
        box = QFrame()
        box.setObjectName("StatBox")
        box.setMinimumHeight(62)
        layout = QVBoxLayout(box)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(0)
        value = QLabel("0")
        value.setObjectName("StatValue")
        value.setStyleSheet(f"color: {color};")
        label = QLabel(caption)
        label.setObjectName("StatCaption")
        layout.addWidget(value)
        layout.addWidget(label)
        return box, value

    # ==================================================================
    # State / config
    # ==================================================================
    def _restore_state(self) -> None:
        cfg = self.config
        self.path_edit.setText(cfg.library_path)
        self.output_edit.setText(cfg.output_root)
        self.token_edit.setText(cfg.tmdb_api_key)
        if env_token_present() and not cfg.tmdb_api_key:
            self.token_edit.setPlaceholderText("يُستخدم مفتاح من متغير البيئة TMDB_API_KEY")
        self._select_combo(self.lang_combo, cfg.language)
        self._select_combo(self.quality_combo, cfg.jpeg_quality)
        self._select_combo(self.media_combo, cfg.media_filter)

        self.overwrite_chip.setChecked(cfg.overwrite_images)
        self.poster_chip.setChecked(cfg.download_poster)
        self.fanart_chip.setChecked(cfg.download_fanart)
        self.background_chip.setChecked(cfg.download_background)
        self.convert_chip.setChecked(cfg.convert_existing_webp)
        self.nested_chip.setChecked(cfg.convert_nested_webp)
        self.dry_chip.setChecked(cfg.dry_run)
        self.convert_only_chip.setChecked(cfg.convert_only)

        geometry = self._settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)
        splitter_state = self._settings.value("splitter")
        if splitter_state:
            self.splitter.restoreState(splitter_state)

    @staticmethod
    def _select_combo(combo: QComboBox, value: object) -> None:
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _sync_config_from_ui(self) -> None:
        cfg = self.config
        cfg.library_path = self.path_edit.text().strip()
        # An unusable output folder must not be persisted (from_dict would drop
        # it silently on the next start); _start reports it instead.
        output_root = self.output_edit.text().strip()
        if output_root:
            try:
                output_root = str(ensure_output_root(output_root))
            except ValueError:
                output_root = ""
        cfg.output_root = output_root
        cfg.tmdb_api_key = self.token_edit.text().strip()
        language = self.lang_combo.currentData()
        if language:
            cfg.language = str(language)
        quality = self.quality_combo.currentData()
        if quality is not None:
            cfg.jpeg_quality = int(quality)
        media_filter = self.media_combo.currentData()
        if media_filter:
            cfg.media_filter = str(media_filter)
        cfg.overwrite_images = self.overwrite_chip.isChecked()
        cfg.download_poster = self.poster_chip.isChecked()
        cfg.download_fanart = self.fanart_chip.isChecked()
        cfg.download_background = self.background_chip.isChecked()
        cfg.convert_existing_webp = self.convert_chip.isChecked()
        cfg.convert_nested_webp = self.nested_chip.isChecked()
        cfg.dry_run = self.dry_chip.isChecked()
        cfg.convert_only = self.convert_only_chip.isChecked()
        try:
            cfg.save()
        except OSError as exc:
            logger.warning("تعذر حفظ الإعدادات: %s", exc)

    def _update_images_warning(self) -> None:
        """تحذير بصري فقط عند تعطيل الأنواع الثلاثة — لا منع للتشغيل."""
        all_off = not (
            self.poster_chip.isChecked()
            or self.fanart_chip.isChecked()
            or self.background_chip.isChecked()
        )
        self.images_warning.setVisible(all_off)

    def _update_mode_hint(self) -> None:
        if self.convert_only_chip.isChecked():
            text = "وضع التحويل فقط: تحويل ملفات WebP الموجودة إلى JPG دون الاتصال بـ TMDB."
        elif self.dry_chip.isChecked():
            text = "وضع المعاينة: سيتم البحث في TMDB وعرض المطابقات فقط، دون تنزيل أو كتابة أي ملف."
        elif self.overwrite_chip.isChecked():
            text = "سيتم استبدال الملصقات والخلفيات الموجودة، مع تحويل ملفات WebP عند تفعيله."
        else:
            text = "سيتم تنزيل أنواع الصور المحددة عند غيابها، مع تحويل ملفات WebP الموجودة."
        self.mode_hint.setText(text)
        self._update_images_warning()
        if not self._running:
            enabled = not self.convert_only_chip.isChecked()
            self.token_edit.setEnabled(enabled)
            self.show_token_btn.setEnabled(enabled)
            self.test_btn.setEnabled(enabled)

    # ==================================================================
    # Actions
    # ==================================================================
    def _browse(self) -> None:
        start = self.path_edit.text().strip() or str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, "اختر مجلد المكتبة", start)
        if folder:
            self.path_edit.setText(folder)

    def _browse_output(self) -> None:
        start = (
            self.output_edit.text().strip()
            or self.path_edit.text().strip()
            or str(Path.home())
        )
        folder = QFileDialog.getExistingDirectory(self, "اختر مجلد إخراج الصور", start)
        if folder:
            self.output_edit.setText(folder)

    def _toggle_token(self) -> None:
        if self.show_token_btn.isChecked():
            self.token_edit.setEchoMode(QLineEdit.EchoMode.Normal)
            self.show_token_btn.setText("إخفاء")
        else:
            self.token_edit.setEchoMode(QLineEdit.EchoMode.Password)
            self.show_token_btn.setText("إظهار")

    def _test_connection(self) -> None:
        if self.ping_worker is not None and self.ping_worker.isRunning():
            return
        self._sync_config_from_ui()
        token = resolve_token(self.config)
        if not token:
            QMessageBox.warning(
                self,
                "مفتاح مطلوب",
                "ألصق مفتاح TMDB أولاً، أو اضبط متغير البيئة TMDB_API_KEY.",
            )
            self.token_edit.setFocus()
            return
        language = self.lang_combo.currentData() or "ar"
        self.test_btn.setEnabled(False)
        self.test_btn.setText("جارٍ الاختبار…")
        ping = PingWorker(token, str(language), timeout=min(20, self.config.request_timeout))
        self.ping_worker = ping
        ping.result.connect(self._on_ping_result)
        ping.finished.connect(self._on_ping_finished)
        ping.start()

    def _on_ping_result(self, ok: bool, message: str) -> None:
        if ok:
            logger.info("اختبار اتصال TMDB: ناجح.")
            QMessageBox.information(self, "الاتصال ناجح", message)
        else:
            logger.warning("اختبار اتصال TMDB فشل: %s", message)
            QMessageBox.warning(self, "تعذر الاتصال", message)

    def _on_ping_finished(self) -> None:
        worker = self.ping_worker
        self.ping_worker = None
        if worker is not None:
            worker.deleteLater()
        self.test_btn.setText("اختبار الاتصال")
        self.test_btn.setEnabled(not self._running and not self.convert_only_chip.isChecked())

    def _start(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            return
        self._sync_config_from_ui()
        cfg = self.config

        typed_output = self.output_edit.text().strip()
        if typed_output:
            try:
                cfg.output_root = str(ensure_output_root(typed_output))
            except ValueError as exc:
                QMessageBox.warning(self, "مجلد إخراج غير صالح", str(exc))
                self.output_edit.setFocus()
                return
        else:
            cfg.output_root = ""

        root = Path(cfg.library_path).expanduser()
        if not cfg.library_path or not root.is_dir():
            QMessageBox.warning(
                self,
                "مسار غير صالح",
                "اختر مجلد مكتبة موجوداً أولاً. يمكنك أيضاً سحب المجلد وإفلاته هنا.",
            )
            self.path_edit.setFocus()
            return

        token = resolve_token(cfg)
        if not cfg.convert_only and not token:
            QMessageBox.warning(
                self,
                "مفتاح TMDB مطلوب",
                "ألصق مفتاح TMDB أو اضبط متغير البيئة TMDB_API_KEY قبل البدء.",
            )
            self.token_edit.setFocus()
            return

        self._clear_results()
        self.console.clear()
        self._started_at = time.monotonic()
        self.elapsed_label.setText("00:00")
        self.status_label.setText("جارٍ تجهيز الفحص…")
        self.progress.setRange(0, 0)
        self._timer.start()

        worker = RunWorker(cfg, root, token)
        self.worker = worker
        worker.progress.connect(self._on_progress)
        worker.item_done.connect(self._on_item)
        worker.finished_ok.connect(self._on_finished)
        worker.failed.connect(self._on_failed)
        worker.finished.connect(self._on_thread_finished)
        self._set_running(True)
        worker.start()

    def _stop(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            self.worker.requestInterruption()
            self.stop_btn.setEnabled(False)
            self.status_label.setText("جارٍ الإيقاف بعد إنهاء العملية الحالية…")
            logger.info("تم طلب إيقاف المعالجة.")

    def _clear_console(self) -> None:
        self.console.clear()

    def _open_data_dir(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(DATA_DIR)))

    def _open_tmdb_keys(self) -> None:
        QDesktopServices.openUrl(QUrl(TMDB_KEYS_URL))

    def _open_readme(self) -> None:
        # In a PyInstaller one-file build the sources live in a temporary
        # folder (sys._MEIPASS); the README is bundled next to them.
        base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
        readme = base / "README.md"
        if readme.is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(readme)))
        else:
            QMessageBox.information(
                self,
                "دليل الاستخدام",
                "ملف README.md غير موجود بجانب التطبيق.",
            )

    def _open_result_folder(self, index) -> None:  # type: ignore[no-untyped-def]
        item = self.table.item(index.row(), 0)
        if item is None:
            return
        path = item.data(Qt.ItemDataRole.UserRole)
        if path and Path(path).is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    # ==================================================================
    # Worker callbacks
    # ==================================================================
    def _on_progress(self, done: int, total: int, title: str) -> None:
        if total <= 0:
            self.progress.setRange(0, 0)
            self.status_label.setText(title)
            return
        if self.progress.minimum() != 0 or self.progress.maximum() != total:
            self.progress.setRange(0, total)
        self.progress.setValue(min(done, total))
        self.status_label.setText(f"{title}  •  {done}/{total}")

    def _on_item(self, result: ItemResult) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)

        status_item = QTableWidgetItem(result.status.label_ar)
        status_item.setForeground(QColor(STATUS_COLORS.get(result.status, "#E7EAF3")))
        status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        status_item.setData(Qt.ItemDataRole.UserRole, str(result.item.path))

        display_title = result.matched_title or result.item.title
        title_item = QTableWidgetItem(display_title)
        title_item.setToolTip(
            f"العنوان الأصلي: {result.item.title}\n"
            f"السنة: {result.item.year or 'غير معروفة'}\n"
            f"{result.message}"
        )
        type_item = QTableWidgetItem(result.item.kind.label_ar)
        type_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        path_item = QTableWidgetItem(str(result.item.path))
        path_item.setToolTip(str(result.item.path))

        self.table.setItem(row, 0, status_item)
        self.table.setItem(row, 1, title_item)
        self.table.setItem(row, 2, type_item)
        self.table.setItem(row, 3, path_item)
        self.table.scrollToBottom()

        if result.status in (Status.OK, Status.PARTIAL):
            self._counts["succeeded"] += 1
        elif result.status is Status.SKIPPED:
            self._counts["skipped"] += 1
        elif result.status is Status.NOT_FOUND:
            self._counts["not_found"] += 1
        elif result.status is Status.ERROR:
            self._counts["errors"] += 1
        elif result.status is Status.PREVIEW:
            self._counts["preview"] += 1
        self._update_stats()

    def _on_finished(self, summary: object) -> None:
        if not isinstance(summary, RunSummary):
            return
        self._last_summary = summary
        self._timer.stop()
        elapsed = summary.duration if summary.duration > 0 else (time.monotonic() - self._started_at)
        self.elapsed_label.setText(_format_duration(elapsed))

        if summary.total == 0 and not summary.cancelled:
            self.progress.setRange(0, 100)
            self.progress.setValue(0)
            self.status_label.setText(
                "لم يتم العثور على عناصر. تأكد أن كل فيلم داخل مجلد مستقل، "
                "وأن المسلسل يحتوي على مجلد مواسم."
            )
            self.results_hint.setText("لا نتائج")
            QMessageBox.information(
                self,
                "لا توجد عناصر",
                "لم يتم العثور على مجلدات أفلام أو مسلسلات مطابقة.\n\n"
                "تذكر: المكتبة المسطحة (ملفات فيديو مباشرة داخل المجلد) غير مدعومة؛ "
                "ضع كل فيلم داخل مجلد يحمل اسمه.",
            )
            return

        done = len(summary.results)
        total = max(summary.total, done, 1)
        self.progress.setRange(0, total)
        self.progress.setValue(done if not summary.cancelled else done)

        text = summary.summary_text()
        if summary.cancelled:
            self.status_label.setText("تم الإيقاف يدوياً — " + text)
            color = "#FBBF24"
        elif summary.errors:
            self.status_label.setText(text)
            color = "#FB923C"
        else:
            self.status_label.setText(text)
            color = "#4ADE80"
        self.status_label.setStyleSheet(f"color: {color};")
        self.results_hint.setText(text)
        self.statusBar().showMessage(text, 20000)

    def _on_failed(self, message: str) -> None:
        self._timer.stop()
        self.elapsed_label.setText(_format_duration(time.monotonic() - self._started_at))
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.status_label.setText("فشلت العملية: " + message)
        self.status_label.setStyleSheet("color: #F87171;")
        QMessageBox.critical(self, "تعذر إكمال العملية", message)

    def _on_thread_finished(self) -> None:
        worker = self.worker
        self.worker = None
        if worker is not None:
            worker.deleteLater()
        self._timer.stop()
        self._set_running(False)

    # ==================================================================
    # Helpers
    # ==================================================================
    def _set_running(self, running: bool) -> None:
        self._running = running
        for widget in (
            self.path_edit,
            self.browse_btn,
            self.output_edit,
            self.output_browse_btn,
            self.token_edit,
            self.show_token_btn,
            self.test_btn,
            self.lang_combo,
            self.quality_combo,
            self.media_combo,
            self.overwrite_chip,
            self.poster_chip,
            self.fanart_chip,
            self.background_chip,
            self.convert_chip,
            self.nested_chip,
            self.dry_chip,
            self.convert_only_chip,
        ):
            widget.setEnabled(not running)
        self.start_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)
        if not running:
            self._update_mode_hint()
        else:
            self.mode_hint.setText("المعالجة جارية… يمكنك متابعة السجل والنتائج، أو الضغط على إيقاف.")

    def _clear_results(self) -> None:
        self.table.setRowCount(0)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self._counts = {"succeeded": 0, "skipped": 0, "not_found": 0, "errors": 0, "preview": 0}
        self._update_stats()
        self.results_hint.setText("جارٍ المعالجة…")
        self.elapsed_label.setText("00:00")
        self.status_label.setStyleSheet("")
        self.status_label.setText("جارٍ تجهيز الفحص…")

    def _update_stats(self) -> None:
        self.stat_ok_value.setText(str(self._counts["succeeded"]))
        self.stat_skipped_value.setText(str(self._counts["skipped"]))
        self.stat_not_found_value.setText(str(self._counts["not_found"]))
        self.stat_errors_value.setText(str(self._counts["errors"]))
        self.stat_preview_value.setText(str(self._counts["preview"]))

    def _tick(self) -> None:
        if not self._running:
            return
        self.elapsed_label.setText(_format_duration(time.monotonic() - self._started_at))

    def _install_log_bridge(self) -> None:
        handler = QtLogHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        handler.emitter.message.connect(self._append_log)
        logging.getLogger("mediaart").addHandler(handler)
        self._log_handler = handler

    def _append_log(self, level: str, message: str) -> None:
        color = LEVEL_COLORS.get(level, "#B6C0D4")
        timestamp = QTime.currentTime().toString("HH:mm:ss")
        safe = html.escape(message).replace("\n", "<br>")
        self.console.append(
            f'<span style="color:#4B5563">[{timestamp}]</span> '
            f'<span style="color:{color}">{safe}</span>'
        )
        bar = self.console.verticalScrollBar()
        bar.setValue(bar.maximum())

    # ==================================================================
    # Drag & drop / close
    # ==================================================================
    def dragEnterEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        for url in event.mimeData().urls():
            if url.isLocalFile() and Path(url.toLocalFile()).is_dir():
                event.acceptProposedAction()
                return
        event.ignore()

    def dropEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        for url in event.mimeData().urls():
            if url.isLocalFile() and Path(url.toLocalFile()).is_dir():
                self.path_edit.setText(url.toLocalFile())
                event.acceptProposedAction()
                return
        event.ignore()

    def showEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().showEvent(event)
        if not self._dark_titlebar_done:
            self._dark_titlebar_done = True
            _set_dark_titlebar(self)

    def closeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if self.worker is not None and self.worker.isRunning():
            answer = QMessageBox.question(
                self,
                "معالجة جارية",
                "المعالجة لم تنتهِ بعد. هل تريد إيقافها والخروج؟",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.worker.requestInterruption()
            if not self.worker.wait(8000):
                logger.warning("لم يتوقف العامل خلال المهلة، سيتم إنهاؤه قسرياً.")
                self.worker.terminate()
                self.worker.wait(1500)

        if self.ping_worker is not None and self.ping_worker.isRunning():
            if not self.ping_worker.wait(2500):
                self.ping_worker.terminate()
                self.ping_worker.wait(1000)

        self._sync_config_from_ui()
        self._settings.setValue("geometry", self.saveGeometry())
        self._settings.setValue("splitter", self.splitter.saveState())

        if self._log_handler is not None:
            logging.getLogger("mediaart").removeHandler(self._log_handler)
            self._log_handler = None

        event.accept()


def _format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _set_dark_titlebar(window: QMainWindow) -> None:
    if os.name != "nt":
        return
    try:
        import ctypes

        hwnd = int(window.winId())
        value = ctypes.c_int(20)  # DWMWA_USE_IMMERSIVE_DARK_MODE
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd,
            20,
            ctypes.byref(value),
            ctypes.sizeof(value),
        )
    except Exception:  # pragma: no cover - cosmetic only
        pass
