"""Manifest of everything written into an ``output_root`` tree.

When the library itself is read-only (NAS shares, mounted snapshots), the
images are written to a separate tree instead. That tree is invisible to the
library, so a small JSON sidecar records what was produced, when, and whether
the item is complete. It is flushed after every item so an interrupted run
(closed window, killed process, dropped share) never loses the completed work.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..logging_setup import get_logger

logger = get_logger("manifest")

MANIFEST_NAME = ".mediaart_manifest.json"
MANIFEST_VERSION = 1


class OutputManifest:
    """Read/modify/write wrapper around ``<output_root>/.mediaart_manifest.json``."""

    def __init__(self, output_root: Path | str) -> None:
        self.path = Path(output_root) / MANIFEST_NAME
        self._entries: dict[str, dict[str, Any]] = {}
        #: ملف بإصدار غير معروف لا يُقرأ ولا يُكتب فوقه أبداً.
        self._readonly = False
        #: المعالج المتوازي يحدّث السجل من عدة خيوط؛ القفل يحمي القراءة/الكتابة
        #: (RLock لأن update_entry يستدعي flush).
        self._lock = threading.RLock()
        self._load()

    # ------------------------------------------------------------------
    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def entry(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            return self._entries.get(key)

    def update_entry(self, key: str, files: list[str], status: str) -> bool:
        """Record one item. Returns True when the manifest actually changed.

        An unchanged entry keeps its original timestamp, so re-running over an
        already-complete tree leaves the manifest byte-identical.
        """
        if self._readonly:
            return False
        files = sorted(set(files))
        with self._lock:
            previous = self._entries.get(key)
            if (
                previous is not None
                and previous.get("files") == files
                and previous.get("status") == status
            ):
                return False
            self._entries[key] = {
                "files": files,
                "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "status": status,
            }
            self.flush()
        return True

    # ------------------------------------------------------------------
    def flush(self) -> None:
        with self._lock:
            if self._readonly:
                return
            payload = {"version": MANIFEST_VERSION, "entries": self._entries}
            text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
            fd, tmp_name = tempfile.mkstemp(
                prefix=".manifest-", suffix=".tmp", dir=str(self.path.parent)
            )
            tmp = Path(tmp_name)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(text)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(tmp, self.path)
            except OSError as exc:
                logger.warning("تعذر تحديث manifest: %s", exc)
            finally:
                tmp.unlink(missing_ok=True)

    def _load(self) -> None:
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return
        except OSError as exc:
            logger.warning("تعذر قراءة manifest %s: %s", self.path, exc)
            return
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("ملف manifest تالف، سيُعاد بناؤه: %s", self.path)
            return
        if not isinstance(data, dict):
            return
        version = data.get("version")
        if version != MANIFEST_VERSION:
            # Written by another tool or a newer format: reading it would apply
            # unknown semantics, and the next flush would silently replace the
            # whole file with our own version.
            logger.warning(
                "إصدار manifest غير مدعوم (%s ≠ %s)؛ لن يُقرأ ولن "
                "يُكتب فوقه: %s. لتفعيل idempotency، احذف الملف أو "
                "أعد تسميته.",
                version,
                MANIFEST_VERSION,
                self.path,
            )
            self._readonly = True
            return
        entries = data.get("entries")
        if isinstance(entries, dict):
            self._entries = {
                str(key): value for key, value in entries.items() if isinstance(value, dict)
            }
