"""اختبارات تصفية السجل: مستوى QtLogHandler والتنقيح المشترك (A6/P6)."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

import pytest

import app.logging_setup as logging_setup
from app.logging_setup import get_logger, setup_logging
from app.ui.worker import QtLogHandler


def _isolated_logger(handler: logging.Handler) -> logging.Logger:
    """سجل مستقل تماماً (propagate=False) حتى لا نلوّث سجل التطبيق."""
    logger = logging.getLogger(f"mediaart.tests.{uuid.uuid4().hex}")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    logger.addHandler(handler)
    return logger


def _collect(handler: QtLogHandler) -> list[tuple[str, str]]:
    received: list[tuple[str, str]] = []
    handler.emitter.message.connect(lambda level, text: received.append((level, text)))
    return received


def test_debug_is_not_forwarded_to_qt_handler() -> None:
    """L1: سجل DEBUG لا يصل إلى سجل الواجهة (المستوى INFO مفعّل)."""
    handler = QtLogHandler()
    received = _collect(handler)
    logger = _isolated_logger(handler)
    try:
        logger.debug("تفصيل داخلي يجب ألا يظهر")
        logger.info("رسالة/info للمستخدم")
    finally:
        logger.removeHandler(handler)

    texts = [text for _, text in received]
    assert "تفصيل داخلي يجب ألا يظهر" not in texts
    assert "رسالة/info للمستخدم" in texts


def test_info_is_forwarded_to_qt_handler() -> None:
    """L2: سجل INFO يصل طبيعياً إلى سجل الواجهة."""
    handler = QtLogHandler()
    received = _collect(handler)
    logger = _isolated_logger(handler)
    try:
        logger.info("رسالة/info للمستخدم")
    finally:
        logger.removeHandler(handler)

    assert ("INFO", "رسالة/info للمستخدم") in received


def test_qt_handler_level_can_be_overridden() -> None:
    """المستوى قابل للتجاوز عبر المُنشئ (بلا كسر أي مستهلك حالي)."""
    handler = QtLogHandler(level=logging.DEBUG)
    received = _collect(handler)
    logger = _isolated_logger(handler)
    try:
        logger.debug("تفصيل ب_debug")
    finally:
        logger.removeHandler(handler)

    assert [text for _, text in received] == ["تفصيل ب_debug"]


def test_secret_is_redacted_in_qt_handler() -> None:
    """L3: رسالة فيها api_key=SECRET تصل منقّاة إلى سجل الواجهة."""
    handler = QtLogHandler()
    received = _collect(handler)
    logger = _isolated_logger(handler)
    try:
        logger.info("فشل الطلب: api_key=SECRET123 لا يعمل")
    finally:
        logger.removeHandler(handler)

    texts = [text for _, text in received]
    assert any("api_key=***" in text for text in texts)
    assert not any("SECRET123" in text for text in texts)


def test_secret_is_redacted_in_log_file(tmp_path: Path) -> None:
    """L4: نفس الرسالة عبر مسار ملف السجل — سلوك متّسق بلا تكرار."""
    log_file = tmp_path / "app_log.txt"
    logging_setup._configured = False
    logger = setup_logging(log_path=log_file, console=False)
    try:
        logger.info("فشل الطلب: api_key=FILESECRET456")
        for handler in logger.handlers:
            handler.flush()
        content = log_file.read_text(encoding="utf-8")
    finally:
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()
        logging_setup._configured = False

    assert "api_key=***" in content
    assert "FILESECRET456" not in content


def test_bearer_token_is_redacted_in_qt_handler() -> None:
    """حالة ثانية للتنقيح: ترويسة Bearer."""
    handler = QtLogHandler()
    received = _collect(handler)
    logger = _isolated_logger(handler)
    try:
        logger.info("Authorization: Bearer ABCDEFGHIJKLMNOP")
    finally:
        logger.removeHandler(handler)

    texts = [text for _, text in received]
    assert any("Bearer ***" in text for text in texts)
    assert not any("ABCDEFGHIJKLMNOP" in text for text in texts)


def test_redaction_filter_is_shared_instance_type() -> None:
    """الفلتر المستخدم في QtLogHandler هو نفسه المستخدم في السجل الآخر."""
    handler = QtLogHandler()
    filters = [f for f in handler.filters if isinstance(f, logging_setup.RedactionFilter)]
    assert filters, "QtLogHandler يجب أن يحمل RedactionFilter نفسه"
