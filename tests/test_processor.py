from __future__ import annotations

import io
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from PIL import Image

from app.config import AppConfig
from app.models import MediaItem, MediaKind, RunSummary, Status, TMDBMatch
from app.services.images import ImageService
from app.services.processor import Processor


@pytest.fixture()
def image_server(tmp_path: Path):
    buffer = io.BytesIO()
    Image.new("RGB", (120, 180), (30, 60, 90)).save(buffer, format="JPEG")
    jpeg = buffer.getvalue()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            if self.path in {"/poster.jpg", "/backdrop.jpg"}:
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(jpeg)))
                self.end_headers()
                self.wfile.write(jpeg)
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, *args):  # silence
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


class FakeClient:
    def __init__(self, match: TMDBMatch | None) -> None:
        self.match = match
        self.calls = 0

    def find_match(self, item: MediaItem) -> TMDBMatch | None:
        self.calls += 1
        return self.match

    def close(self) -> None:
        pass


def make_item(tmp_path: Path, name: str = "Inception (2010)") -> MediaItem:
    folder = tmp_path / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "Inception.2010.1080p.mkv").write_bytes(b"")
    return MediaItem(path=folder, kind=MediaKind.MOVIE, title="Inception", year=2010)


def make_match(base_url: str) -> TMDBMatch:
    return TMDBMatch(
        tmdb_id=27205,
        media_type="movie",
        title="Inception",
        original_title="Inception",
        year=2010,
        poster_path=f"{base_url}/poster.jpg",
        backdrop_path=f"{base_url}/backdrop.jpg",
    )


def make_webp(path: Path, size: tuple[int, int] = (40, 60)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", size, (255, 0, 0, 128)).save(path, format="WEBP")
    return path


def test_process_downloads_poster_and_both_backdrops(tmp_path: Path, image_server: str) -> None:
    item = make_item(tmp_path)
    client = FakeClient(make_match(image_server))
    config = AppConfig(jpeg_quality=95, create_background_copy=True)
    processor = Processor(config, client=client, images=ImageService(quality=95))

    result = processor.process_item(item)

    assert result.status is Status.OK
    assert result.poster_saved and result.backdrop_saved
    assert (item.path / "poster.jpg").is_file()
    assert (item.path / "fanart.jpg").is_file()
    assert (item.path / "background.jpg").is_file()
    assert client.calls == 1
    processor.close()


def test_existing_images_are_skipped_without_api_call(tmp_path: Path) -> None:
    item = make_item(tmp_path)
    Image.new("RGB", (10, 10)).save(item.path / "poster.jpg", format="JPEG")
    Image.new("RGB", (10, 10)).save(item.path / "fanart.jpg", format="JPEG")
    client = FakeClient(None)
    config = AppConfig()
    processor = Processor(config, client=client, images=ImageService())

    result = processor.process_item(item)

    assert result.status is Status.SKIPPED
    assert client.calls == 0
    processor.close()


def test_not_found(tmp_path: Path) -> None:
    item = make_item(tmp_path)
    config = AppConfig()
    processor = Processor(config, client=FakeClient(None), images=ImageService())

    result = processor.process_item(item)

    assert result.status is Status.NOT_FOUND
    processor.close()


def test_background_only_does_not_replace_standard_fanart(
    tmp_path: Path, image_server: str
) -> None:
    """T1: background.jpg وحده لا يكفي — يجب تنزيل fanart.jpg القياسي."""
    item = make_item(tmp_path)
    Image.new("RGB", (10, 10), (0, 0, 255)).save(item.path / "background.jpg", format="JPEG")
    client = FakeClient(make_match(image_server))
    processor = Processor(AppConfig(), client=client, images=ImageService())

    result = processor.process_item(item)

    assert result.status is Status.OK
    assert result.backdrop_saved
    assert client.calls == 1
    # الملف القياسي يجب أن يكون النسخة المنزّلة (120x180 من الخادم)،
    # لا مجرد نسخة من background.jpg (10x10).
    with Image.open(item.path / "fanart.jpg") as downloaded:
        assert downloaded.size == (120, 180)
    assert "موجودة مسبقاً" not in result.message
    processor.close()


def test_existing_fanart_is_not_downloaded_again(
    tmp_path: Path, image_server: str
) -> None:
    """T2: وجود fanart.jpg يمنع تنزيل الخلفية مجدداً."""
    item = make_item(tmp_path)
    Image.new("RGB", (10, 10), (0, 0, 255)).save(item.path / "fanart.jpg", format="JPEG")
    before = (item.path / "fanart.jpg").read_bytes()
    client = FakeClient(make_match(image_server))
    processor = Processor(AppConfig(), client=client, images=ImageService())

    result = processor.process_item(item)

    assert result.backdrop_saved is False
    assert (item.path / "fanart.jpg").read_bytes() == before
    with Image.open(item.path / "fanart.jpg") as kept:
        assert kept.size == (10, 10)
    processor.close()


def test_existing_fanart_and_background_skip_download(
    tmp_path: Path, image_server: str
) -> None:
    """T3: fanart.jpg مع background.jpg — لا تنزيل مكرر للخلفيات."""
    item = make_item(tmp_path)
    Image.new("RGB", (10, 10), (0, 0, 255)).save(item.path / "fanart.jpg", format="JPEG")
    Image.new("RGB", (10, 10), (0, 255, 0)).save(item.path / "background.jpg", format="JPEG")
    fanart_before = (item.path / "fanart.jpg").read_bytes()
    background_before = (item.path / "background.jpg").read_bytes()
    client = FakeClient(make_match(image_server))
    processor = Processor(AppConfig(), client=client, images=ImageService())

    result = processor.process_item(item)

    assert result.backdrop_saved is False
    assert (item.path / "fanart.jpg").read_bytes() == fanart_before
    assert (item.path / "background.jpg").read_bytes() == background_before
    processor.close()


def test_dry_run_does_not_write_files(tmp_path: Path, image_server: str) -> None:
    item = make_item(tmp_path)
    config = AppConfig(dry_run=True)
    processor = Processor(config, client=FakeClient(make_match(image_server)), images=ImageService())

    result = processor.process_item(item)

    assert result.status is Status.PREVIEW
    assert result.dry_run
    assert not (item.path / "poster.jpg").exists()
    assert not (item.path / "fanart.jpg").exists()
    processor.close()


def test_dry_run_convert_only_reports_preview_not_success(tmp_path: Path) -> None:
    """وضع المعاينة + تحويل فقط: لا تنفيذ، ورسالة بصيغة المستقبل."""
    item = make_item(tmp_path)
    make_webp(item.path / "poster.webp")
    config = AppConfig(dry_run=True, convert_only=True, convert_existing_webp=True)
    processor = Processor(config, client=None, images=ImageService())

    result = processor.process_item(item)

    assert result.status is Status.PREVIEW
    assert result.status is not Status.OK
    assert result.webp_converted == 0
    assert result.webp_would_convert == 1
    assert "سيتم" in result.message
    assert "[معاينة]" in result.message
    # لا شيء كُتب على القرص: لا JPG جديد ولا حذف لمصدر WebP
    assert not (item.path / "poster.jpg").exists()
    assert (item.path / "poster.webp").exists()
    processor.close()


def test_dry_run_summary_separates_planned_from_done(tmp_path: Path) -> None:
    """الملخص لا ينسب تحويلات لم تُنفّذ إلى الوضع الحقيقي."""
    item = make_item(tmp_path)
    make_webp(item.path / "poster.webp")
    config = AppConfig(dry_run=True, convert_only=True, convert_existing_webp=True)
    processor = Processor(config, client=None, images=ImageService())

    summary = processor.run([item])

    assert summary.webp_converted == 0
    assert summary.webp_would_convert == 1
    assert summary.preview == 1
    assert summary.ok == 0
    assert "معاينة: 1" in summary.summary_text()
    assert "سيتم تحويل WebP: 1" in summary.summary_text()
    processor.close()


def test_summary_status_counts_cover_every_processed_item(
    tmp_path: Path, image_server: str
) -> None:
    """مجموع حالات الملخص يجب أن يغطي كل عنصر مُعالَج بلا نقص أو تداخل."""
    results = []

    # نجاح كامل
    ok_item = make_item(tmp_path, "Ok Movie (2010)")
    ok_processor = Processor(
        AppConfig(), client=FakeClient(make_match(image_server)), images=ImageService()
    )
    results.append(ok_processor.process_item(ok_item))
    ok_processor.close()

    # معاينة (dry-run)
    preview_item = make_item(tmp_path, "Preview Movie (2011)")
    preview_processor = Processor(
        AppConfig(dry_run=True),
        client=FakeClient(make_match(image_server)),
        images=ImageService(),
    )
    results.append(preview_processor.process_item(preview_item))
    preview_processor.close()

    # غير موجود في TMDB
    missing_item = make_item(tmp_path, "Missing Movie (2012)")
    missing_processor = Processor(
        AppConfig(), client=FakeClient(None), images=ImageService()
    )
    results.append(missing_processor.process_item(missing_item))
    missing_processor.close()

    # متخطى: الصور موجودة مسبقاً
    skipped_item = make_item(tmp_path, "Existing Movie (2013)")
    Image.new("RGB", (10, 10)).save(skipped_item.path / "poster.jpg", format="JPEG")
    Image.new("RGB", (10, 10)).save(skipped_item.path / "fanart.jpg", format="JPEG")
    skipped_processor = Processor(
        AppConfig(), client=FakeClient(None), images=ImageService()
    )
    results.append(skipped_processor.process_item(skipped_item))
    skipped_processor.close()

    summary = RunSummary(total=len(results), results=results)
    counted = (
        summary.ok
        + summary.partial
        + summary.skipped
        + summary.not_found
        + summary.errors
        + summary.cancelled_count
        + summary.preview
    )

    assert counted == summary.total == len(results)
    assert summary.ok == 1
    assert summary.preview == 1
    assert summary.not_found == 1
    assert summary.skipped == 1


def test_summary_text_hides_preview_section_without_previews(
    tmp_path: Path, image_server: str
) -> None:
    """لا يظهر قسم «معاينة» في الملخص إذا لم توجد عناصر معروضة."""
    item = make_item(tmp_path)
    processor = Processor(
        AppConfig(), client=FakeClient(make_match(image_server)), images=ImageService()
    )

    summary = processor.run([item])

    assert summary.preview == 0
    assert "معاينة:" not in summary.summary_text()
    processor.close()


def test_partial_when_poster_fails(tmp_path: Path, image_server: str) -> None:
    item = make_item(tmp_path)
    match = make_match(image_server)
    match.poster_path = f"{image_server}/missing.jpg"
    processor = Processor(
        AppConfig(),
        client=FakeClient(match),
        images=ImageService(quality=95),
    )

    result = processor.process_item(item)

    assert result.status is Status.PARTIAL
    assert not (item.path / "poster.jpg").exists()
    assert (item.path / "fanart.jpg").is_file()
    processor.close()


def test_unwritable_target_fails_before_any_network_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unwritable work folder must not trigger a single download."""
    item = make_item(tmp_path)
    client = FakeClient(None)
    monkeypatch.setattr(
        "app.services.processor.is_folder_writable", lambda folder: False
    )
    processor = Processor(AppConfig(), client=client, images=ImageService())

    result = processor.process_item(item)

    assert result.status is Status.ERROR
    assert result.target_writable is False
    assert "غير قابل للكتابة" in result.message
    assert client.calls == 0
    assert not (item.path / "poster.jpg").exists()
    processor.close()


def test_permission_error_is_not_retried(
    tmp_path: Path,
    image_server: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A denied write must fail fast: no second download attempt."""
    item = make_item(tmp_path)

    def deny(*args: object, **kwargs: object) -> None:
        raise PermissionError(13, "Permission denied")

    # the preflight probe is allowed to pass, so the failure happens in the
    # download step itself (the folder became unwritable mid-run).
    monkeypatch.setattr(
        "app.services.processor.is_folder_writable", lambda folder: True
    )
    monkeypatch.setattr("app.services.images.open", deny, raising=False)
    processor = Processor(
        AppConfig(),
        client=FakeClient(make_match(image_server)),
        images=ImageService(quality=95),
    )

    with caplog.at_level(logging.WARNING, logger="mediaart.images"):
        result = processor.process_item(item)

    assert "إعادة محاولة" not in caplog.text
    assert result.status is Status.ERROR
    assert "تعذر حفظ الصورة" in result.message
    processor.close()
