"""B1: توازٍ محدود مع حفظ ترتيب النتائج وقفل manifest."""

from __future__ import annotations

import threading
import time
from pathlib import Path

from app.config import AppConfig
from app.models import MediaItem, MediaKind, Status
from app.services.images import ImageService
from app.services.manifest import OutputManifest
from app.services.processor import Processor


class SlowClient:
    """عميل TMDB وهمي بتأخير مصطنع: يقيس التوازي بلا شبكة."""

    def __init__(
        self, latency: float = 0.05, fail_titles: tuple[str, ...] = ()
    ) -> None:
        self.latency = latency
        self.fail_titles = fail_titles
        self.calls = 0
        self._lock = threading.Lock()

    def find_match(self, item: MediaItem):
        with self._lock:
            self.calls += 1
        time.sleep(self.latency)
        if item.title in self.fail_titles:
            raise RuntimeError("فشل مصطنع")
        return None

    def close(self) -> None:
        pass


def make_items(root: Path, count: int) -> list[MediaItem]:
    items: list[MediaItem] = []
    for index in range(count):
        title = f"Movie {index:02d}"
        folder = root / title
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{title}.mkv").write_bytes(b"")
        items.append(
            MediaItem(path=folder, kind=MediaKind.MOVIE, title=title, year=2020)
        )
    return items


def _run(
    items: list[MediaItem],
    workers: int,
    *,
    latency: float = 0.05,
    fail_titles: tuple[str, ...] = (),
    on_item=None,
):
    config = AppConfig(max_workers=workers)
    processor = Processor(
        config, client=SlowClient(latency, fail_titles), images=ImageService()
    )
    started = time.monotonic()
    summary = processor.run(items, on_item=on_item)
    elapsed = time.monotonic() - started
    processor.close()
    return summary, elapsed


def test_parallel_is_faster_than_serial(tmp_path: Path) -> None:
    """B1-1: 10 عناصر × 50ms ⇒ 3 خيوط أسرع بوضوح من التسلسلي."""
    items = make_items(tmp_path / "library", 10)

    serial, serial_elapsed = _run(items, 1)
    parallel, parallel_elapsed = _run(items, 3)

    assert serial.total == parallel.total == 10
    assert parallel_elapsed < serial_elapsed * 0.75


def test_results_keep_input_order(tmp_path: Path) -> None:
    """B1-2: الترتيب في الملخص وفي إشارات الواجهة = ترتيب الإدخال."""
    items = make_items(tmp_path / "library", 10)
    seen: list[str] = []

    summary, _ = _run(items, 3, on_item=lambda result: seen.append(result.item.title))

    assert [result.item.title for result in summary.results] == [
        item.title for item in items
    ]
    assert seen == [item.title for item in items]


def test_one_failure_does_not_stop_others(tmp_path: Path) -> None:
    """B1-3: فشل العنصر الثاني لا يمنع الأول والثالث."""
    items = make_items(tmp_path / "library", 3)

    summary, _ = _run(items, 3, fail_titles=("Movie 01",))

    assert [result.status for result in summary.results] == [
        Status.NOT_FOUND,
        Status.ERROR,
        Status.NOT_FOUND,
    ]


def test_single_worker_matches_serial_behaviour(tmp_path: Path) -> None:
    """B1-4: max_workers=1 ⇒ نفس الترتيب والملخص (تراجعي)."""
    items = make_items(tmp_path / "library", 5)

    summary, _ = _run(items, 1, latency=0.01)

    assert summary.cancelled is False
    assert summary.total == 5
    assert summary.errors == 0
    assert [result.item.title for result in summary.results] == [
        item.title for item in items
    ]
    assert [result.status for result in summary.results] == [Status.NOT_FOUND] * 5


def test_manifest_survives_concurrent_updates(tmp_path: Path) -> None:
    """B1-6: 10 خيوط تحدّث 10 مدخلات ⇒ لا فقدان ولا ملف تالف."""
    manifest = OutputManifest(tmp_path)
    barrier = threading.Barrier(10)

    def worker(index: int) -> None:
        barrier.wait()
        manifest.update_entry(f"Movie {index:02d}", ["poster.jpg"], "ok")

    threads = [
        threading.Thread(target=worker, args=(index,)) for index in range(10)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    reloaded = OutputManifest(tmp_path)

    assert len(manifest) == 10
    assert len(reloaded) == 10
    assert reloaded.entry("Movie 07")["files"] == ["poster.jpg"]
