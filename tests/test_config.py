from __future__ import annotations

import json
import time
from pathlib import Path

from app.config import AppConfig, load_config, save_config
from app.services.cache import JsonCache


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
