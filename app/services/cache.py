"""Small JSON cache used to avoid repeating identical TMDB searches."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from ..logging_setup import get_logger

logger = get_logger("cache")
MAX_ENTRIES = 5000


class JsonCache:
    def __init__(self, path: Path | None, ttl_days: int = 30, enabled: bool = True) -> None:
        self.path = path
        self.ttl_seconds = max(1, ttl_days) * 86_400
        self.enabled = enabled and path is not None
        self._lock = threading.Lock()
        self._data: dict[str, dict[str, Any]] = {}
        self._dirty = False
        if self.enabled:
            self._load()

    # ------------------------------------------------------------------
    def get(self, key: str) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        with self._lock:
            entry = self._data.get(key)
            if not entry:
                return None
            if time.time() - float(entry.get("ts", 0)) > self.ttl_seconds:
                self._data.pop(key, None)
                self._dirty = True
                return None
            value = entry.get("value")
            return value if isinstance(value, dict) else None

    def set(self, key: str, value: dict[str, Any]) -> None:
        if not self.enabled:
            return
        with self._lock:
            self._data[key] = {"ts": time.time(), "value": value}
            if len(self._data) > MAX_ENTRIES:
                oldest = sorted(self._data, key=lambda k: self._data[k].get("ts", 0))
                for stale in oldest[: len(self._data) - MAX_ENTRIES]:
                    self._data.pop(stale, None)
            self._dirty = True

    def delete(self, key: str) -> None:
        """حذف مدخل كاش فردي بشكل آمن مع القفل، دون التأثير على بقية المدخلات."""
        if not self.enabled:
            return
        with self._lock:
            if key in self._data:
                self._data.pop(key, None)
                self._dirty = True

    # ------------------------------------------------------------------
    def _load(self) -> None:
        assert self.path is not None
        try:
            raw = self.path.read_text(encoding="utf-8")
            data = json.loads(raw)
            if not isinstance(data, dict):
                return
            now = time.time()
            for key, entry in data.items():
                if not isinstance(entry, dict):
                    continue
                if now - float(entry.get("ts", 0)) <= self.ttl_seconds:
                    self._data[key] = entry
        except FileNotFoundError:
            return
        except (OSError, ValueError, TypeError) as exc:
            logger.warning("تعذر قراءة كاش TMDB، سيتم تجاهله: %s", exc)
            self._data = {}

    def flush(self) -> None:
        if not self.enabled or not self._dirty:
            return
        assert self.path is not None
        with self._lock:
            payload = json.dumps(self._data, ensure_ascii=False)
            self._dirty = False
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(
                prefix=".tmdb-cache-", suffix=".tmp", dir=str(self.path.parent)
            )
            tmp = Path(tmp_name)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(payload)
                os.replace(tmp, self.path)
            finally:
                tmp.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("تعذر حفظ كاش TMDB: %s", exc)
