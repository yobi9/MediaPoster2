from __future__ import annotations

import json
import logging
import time
from contextlib import contextmanager
from pathlib import Path

import pytest

from app.config import AppConfig, load_config, resolve_token, save_config
from app.services.cache import JsonCache

ENV_TOKEN_VARS = ("TMDB_API_KEY", "TMDB_READ_ACCESS_TOKEN", "TMDB_TOKEN")


@contextmanager
def captured_records(logger_name: str):
    """التقط سجلات logger محدّد (لأن mediaart.propagate=False)."""
    logger = logging.getLogger(logger_name)
    records: list[logging.LogRecord] = []

    class Collector(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = Collector()
    logger.addHandler(handler)
    try:
        yield records
    finally:
        logger.removeHandler(handler)


@pytest.fixture(autouse=True)
def _clean_token_env(monkeypatch: pytest.MonkeyPatch):
    """أزل متغيرات المفتاح قبل كل اختبار حتى لا تتسرّب من البيئة."""
    for name in ENV_TOKEN_VARS:
        monkeypatch.delenv(name, raising=False)
    yield


def test_config_roundtrip_and_clamping(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    cfg = AppConfig(
        tmdb_api_key=" key ",
        library_path=" D:/Media ",
        jpeg_quality=500,
        request_timeout=1,
        media_filter="nonsense",
    )
    cfg.save(config_path)

    loaded = load_config(config_path)
    assert loaded.tmdb_api_key == "key"
    assert loaded.library_path == "D:/Media"
    assert loaded.jpeg_quality == 100
    assert loaded.request_timeout == 5
    assert loaded.media_filter == "all"


def test_load_missing_config_returns_defaults(tmp_path: Path) -> None:
    assert load_config(tmp_path / "missing.json") == AppConfig()


def test_load_broken_config_returns_defaults(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text("{not json", encoding="utf-8")
    assert load_config(path) == AppConfig()


def test_cache_ttl_and_flush(tmp_path: Path) -> None:
    path = tmp_path / "cache.json"
    cache = JsonCache(path, ttl_days=30)
    cache.set("a", {"value": 1})
    assert cache.get("a") == {"value": 1}
    cache.flush()
    assert path.is_file()

    reloaded = JsonCache(path, ttl_days=30)
    assert reloaded.get("a") == {"value": 1}

    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["a"]["ts"] = time.time() - 31 * 86_400
    path.write_text(json.dumps(raw), encoding="utf-8")
    expired = JsonCache(path, ttl_days=30)
    assert expired.get("a") is None


def test_disabled_cache(tmp_path: Path) -> None:
    cache = JsonCache(tmp_path / "cache.json", enabled=False)
    cache.set("a", {"value": 1})
    assert cache.get("a") is None
    cache.flush()
    assert not (tmp_path / "cache.json").exists()


def test_failed_flush_keeps_pending_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P2: فشل كتابة الكاش يُبقي التغييرات معلّقة بدل إسقاطها بصمت."""
    import app.services.cache as cache_module

    cache = JsonCache(tmp_path / "cache.json", ttl_days=30)
    cache.set("a", {"value": 1})

    def boom(*args, **kwargs):  # noqa: ANN002, ANN003
        raise OSError(" القرص ممتلئ")

    monkeypatch.setattr(cache_module.os, "replace", boom)
    cache.flush()

    assert cache._dirty is True
    assert not (tmp_path / "cache.json").exists()


# ---------------------------------------------------------------------------
# resolve_token — أولوية المفتاح الممرّر صراحةً (P2/A7)
# ---------------------------------------------------------------------------
def test_cli_token_wins_over_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """R1: --token يتقدّم على TMDB_API_KEY مع تحذير واضح."""
    monkeypatch.setenv("TMDB_API_KEY", "ENV456")
    config = AppConfig(tmdb_api_key="CFG789")

    with captured_records("mediaart.config") as records:
        token = resolve_token(config, cli_token="CLI123")

    assert token == "CLI123"
    warnings = [r for r in records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    message = warnings[0].getMessage()
    assert "TMDB_API_KEY" in message
    assert "أستخدم --token" in message


def test_environment_used_without_cli_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """R2: بلا --token يُستخدم مفتاح البيئة بلا أي تحذير."""
    monkeypatch.setenv("TMDB_API_KEY", "ENV456")
    config = AppConfig(tmdb_api_key="CFG789")

    with captured_records("mediaart.config") as records:
        token = resolve_token(config)

    assert token == "ENV456"
    assert not [r for r in records if r.levelno == logging.WARNING]


def test_cli_token_used_without_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """R3: --token وحده بلا بيئة ⇒ يُستخدم بلا تحذير."""
    config = AppConfig(tmdb_api_key="CFG789")

    with captured_records("mediaart.config") as records:
        token = resolve_token(config, cli_token="CLI123")

    assert token == "CLI123"
    assert not [r for r in records if r.levelno == logging.WARNING]


def test_config_key_used_as_last_resort(monkeypatch: pytest.MonkeyPatch) -> None:
    """R4: بلا --token وبلا بيئة ⇒ مفتاح config.json (سلوك محفوظ)."""
    config = AppConfig(tmdb_api_key="CFG789")

    assert resolve_token(config) == "CFG789"


def test_conflict_warning_is_emitted_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """R5: تحذير واحد فقط عند التعارض."""
    monkeypatch.setenv("TMDB_API_KEY", "ENV456")
    config = AppConfig()

    with captured_records("mediaart.config") as records:
        token = resolve_token(config, cli_token="CLI123")

    assert token == "CLI123"
    assert len([r for r in records if r.levelno == logging.WARNING]) == 1


def test_read_access_token_env_is_used(monkeypatch: pytest.MonkeyPatch) -> None:
    """سلوك متغيّرات البيئة الأخرى محفوظ."""
    monkeypatch.setenv("TMDB_READ_ACCESS_TOKEN", "READTOKEN")

    assert resolve_token(AppConfig(tmdb_api_key="CFG")) == "READTOKEN"


# ---------------------------------------------------------------------------
# أنواع الصور المستقلة (A-types)
# ---------------------------------------------------------------------------
def test_defaults_download_only_posters() -> None:
    """الافتراضي الجديد: الملصق فقط (fanart/background اختياريتان)."""
    config = AppConfig()

    assert config.download_poster is True
    assert config.download_fanart is False
    assert config.download_background is False


@pytest.mark.parametrize(
    "poster,fanart,background",
    [
        (False, False, False),
        (False, False, True),
        (False, True, False),
        (False, True, True),
        (True, False, False),
        (True, False, True),
        (True, True, False),
        (True, True, True),
    ],
)
def test_every_image_type_combination_roundtrips(
    poster: bool, fanart: bool, background: bool
) -> None:
    """C000–C111: كل تركيب يُحفظ ويُقرأ دون انحراف."""
    config = AppConfig(
        download_poster=poster,
        download_fanart=fanart,
        download_background=background,
    )

    restored = AppConfig.from_dict(config.to_dict())

    assert (
        config.download_poster,
        config.download_fanart,
        config.download_background,
    ) == (poster, fanart, background)
    assert (
        restored.download_poster,
        restored.download_fanart,
        restored.download_background,
    ) == (poster, fanart, background)


def test_all_image_types_disabled_warns_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """C000: تعطيل الكل يُسجّل تحذيراً واحداً (لا يمنع التشغيل)."""
    with caplog.at_level(logging.WARNING, logger="mediaart.config"):
        AppConfig(
            download_poster=False,
            download_fanart=False,
            download_background=False,
        )

    messages = [
        record.getMessage()
        for record in caplog.records
        if "كل أنواع الصور معطّلة" in record.getMessage()
    ]
    assert len(messages) == 1


# ---------------------------------------------------------------------------
# حدّ الكاش السلبي (A2 / N5)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("value", [0, -1, 366, 1000])
def test_negative_cache_ttl_out_of_range_is_rejected(value: int) -> None:
    """N5: قيمة خارج [1, 365] ⇒ ValueError (لا قصّ صامت)."""
    with pytest.raises(ValueError):
        AppConfig(negative_cache_ttl_days=value)


@pytest.mark.parametrize("value", [1, 30, 365])
def test_negative_cache_ttl_valid_range_is_accepted(value: int) -> None:
    assert AppConfig(negative_cache_ttl_days=value).negative_cache_ttl_days == value


def test_invalid_negative_ttl_in_config_file_is_ignored(tmp_path: Path) -> None:
    """قيمة تالفة في config.json تُهمَل دون فقدان بقية الإعدادات."""
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "library_path": "D:/Media",
                "negative_cache_ttl_days": 999,
            }
        ),
        encoding="utf-8",
    )

    loaded = load_config(path)

    assert loaded.negative_cache_ttl_days == 30
    assert loaded.library_path == "D:/Media"


# ---------------------------------------------------------------------------
# Fanart toggle — توافق الإعدادات القديمة والاستمرارية (استكمال)
# ---------------------------------------------------------------------------
def test_old_config_without_download_fanart_defaults_to_false(tmp_path: Path) -> None:
    """إعداد قديم بلا download_fanart يُحمّل معطّلاً مع الحفاظ على بقية الحقول."""
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "library_path": "D:/Media/Old",
                "download_poster": True,
                "download_background": True,
                "language": "ar",
            }
        ),
        encoding="utf-8",
    )

    loaded = load_config(path)

    assert loaded.download_fanart is False
    assert loaded.library_path == "D:/Media/Old"
    assert loaded.download_poster is True
    assert loaded.download_background is True
    assert loaded.language == "ar"


def test_download_fanart_persists_across_save_and_reload(tmp_path: Path) -> None:
    """حفظ اختيار download_fanart في الملف واستعادته بعد إعادة التحميل (إعادة تشغيل)."""
    path = tmp_path / "config.json"

    enabled = AppConfig(download_fanart=True)
    enabled.save(path)
    reloaded_enabled = load_config(path)
    assert reloaded_enabled.download_fanart is True

    disabled = AppConfig(download_fanart=False)
    disabled.save(path)
    reloaded_disabled = load_config(path)
    assert reloaded_disabled.download_fanart is False
