"""Background Qt workers: one for a full library run, one for key testing."""

from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from ..config import AppConfig
from ..logging_setup import get_logger
from ..models import RunSummary
from ..services.images import ImageService
from ..services.processor import Processor
from ..services.scanner import discover_media
from ..services.tmdb import TMDBClient

logger = get_logger("worker")


class LogEmitter(QObject):
    message = pyqtSignal(str, str)  # level, text


class QtLogHandler(logging.Handler):
    """Forward ``mediaart`` log records to the GUI console (thread-safe)."""

    def __init__(self) -> None:
        super().__init__()
        self.emitter = LogEmitter()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            text = self.format(record)
        except Exception:  # pragma: no cover - defensive
            text = record.getMessage()
        self.emitter.message.emit(record.levelname, text)


class RunWorker(QThread):
    progress = pyqtSignal(int, int, str)
    item_done = pyqtSignal(object)
    finished_ok = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, config: AppConfig, root: Path, token: str) -> None:
        super().__init__()
        self.config = config
        self.root = root
        self.token = token

    def run(self) -> None:  # noqa: D401 - Qt entry point
        client: TMDBClient | None = None
        processor: Processor | None = None
        try:
            self.progress.emit(0, 0, "جارٍ فحص المجلدات...")
            items = discover_media(self.root, self.config.media_filter)
            logger.info("تم العثور على %d عنصر قابل للمعالجة.", len(items))

            if self.isInterruptionRequested():
                self.finished_ok.emit(RunSummary(total=len(items), cancelled=True))
                return
            if not items:
                self.finished_ok.emit(RunSummary(total=0))
                return

            if not self.config.convert_only:
                client = TMDBClient(
                    self.token,
                    language=self.config.language,
                    timeout=self.config.request_timeout,
                    min_interval=self.config.min_request_interval,
                    max_retries=self.config.max_retries,
                    use_cache=self.config.use_cache,
                    cache_ttl_days=self.config.cache_ttl_days,
                    prefer_localized_artwork=self.config.prefer_localized_artwork,
                )

            images = ImageService(
                quality=self.config.jpeg_quality,
                timeout=self.config.request_timeout,
                cancel_check=self.isInterruptionRequested,
            )
            processor = Processor(self.config, client=client, images=images)
            summary = processor.run(
                items,
                should_cancel=self.isInterruptionRequested,
                on_item=self.item_done.emit,
                on_progress=self.progress.emit,
            )
            self.finished_ok.emit(summary)
        except Exception as exc:  # pragma: no cover - fatal guard, tested manually
            logger.exception("فشل التشغيل")
            self.failed.emit(_friendly_error(exc))
        finally:
            if processor is not None:
                processor.close()
            elif client is not None:
                client.close()


class PingWorker(QThread):
    result = pyqtSignal(bool, str)

    def __init__(self, token: str, language: str, timeout: int = 15) -> None:
        super().__init__()
        self.token = token
        self.language = language
        self.timeout = timeout

    def run(self) -> None:
        client: TMDBClient | None = None
        try:
            client = TMDBClient(
                self.token,
                language=self.language,
                timeout=self.timeout,
                use_cache=False,
                prefer_localized_artwork=False,
            )
            client.test_connection()
            self.result.emit(True, "تم الاتصال بـ TMDB بنجاح.")
        except Exception as exc:
            self.result.emit(False, str(exc))
        finally:
            if client is not None:
                client.close()


def _friendly_error(exc: Exception) -> str:
    message = str(exc).strip()
    if message:
        return message
    return f"{exc.__class__.__name__}: خطأ غير متوقع."
