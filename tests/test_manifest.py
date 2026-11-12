from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

from app.services.manifest import MANIFEST_NAME, MANIFEST_VERSION, OutputManifest


def _write(path: Path, version: object, entries: dict | None = None) -> Path:
    """اكتب ملف manifest خاماً (بلا المرور عبر OutputManifest)."""
    path.mkdir(parents=True, exist_ok=True)
    target = path / MANIFEST_NAME
    target.write_text(
        json.dumps(
            {"version": version, "entries": entries or {}},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return target


def test_unknown_version_is_rejected_and_reported(
    tmp_path: Path, caplog: logging.LogRecord
) -> None:
    """M1: إصدار غير معروف ⇒ readonly + تحذير واحد يذكر الإصدارين."""
    _write(tmp_path, 99)

    with caplog.at_level(logging.WARNING, logger="mediaart.manifest"):
        manifest = OutputManifest(tmp_path)

    assert manifest._readonly is True
    messages = [
        record.getMessage()
        for record in caplog.records
        if "إصدار manifest" in record.getMessage()
    ]
    assert len(messages) == 1
    assert "99" in messages[0]
    assert str(MANIFEST_VERSION) in messages[0]


def test_readonly_manifest_is_never_rewritten(tmp_path: Path) -> None:
    """M2: بعد الرفض، update_entry + flush لا يغيّران الملف بايتاً واحداً."""
    target = _write(tmp_path, 99)
    before = hashlib.sha256(target.read_bytes()).hexdigest()

    manifest = OutputManifest(tmp_path)
    manifest.update_entry("Inception (2010)", ["poster.jpg"], "ok")
    manifest.flush()

    after = hashlib.sha256(target.read_bytes()).hexdigest()
    assert before == after


def test_current_version_loads_normally(tmp_path: Path) -> None:
    """M3: الإصدار الحالي يُقرأ ويكتب فوقه كالمعتاد."""
    _write(
        tmp_path,
        MANIFEST_VERSION,
        {"Inception (2010)": {"files": ["poster.jpg"], "status": "ok"}},
    )

    manifest = OutputManifest(tmp_path)

    assert manifest._readonly is False
    assert len(manifest) == 1
    assert manifest.entry("Inception (2010)")["status"] == "ok"
