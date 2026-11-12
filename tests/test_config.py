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
