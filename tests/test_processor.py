from __future__ import annotations

import io
import json
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


@pytest.fixture()
def counting_server():
    """خادم صور يعدّ الطلبات لكل نوع (poster / backdrop)."""
    buffer = io.BytesIO()
    Image.new("RGB", (120, 180), (30, 60, 90)).save(buffer, format="JPEG")
    jpeg = buffer.getvalue()
    counts = {"poster": 0, "backdrop": 0}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            if self.path == "/poster.jpg":
                counts["poster"] += 1
            elif self.path == "/backdrop.jpg":
                counts["backdrop"] += 1
            else:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(jpeg)))
            self.end_headers()
            self.wfile.write(jpeg)

        def log_message(self, *args):  # silence
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", counts
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
    config = AppConfig(jpeg_quality=95, download_fanart=True, download_background=True)
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


def test_existing_background_is_kept_when_fanart_is_downloaded(
    tmp_path: Path, image_server: str
) -> None:
    """T4_safety: background.jpg القائمة لا تُحذف ولا تُستبدل عند تنزيل fanart.

    حالة واقعية: المستخدم لديه background.jpg بدقة منخفضة من تشغيل سابق،
    والآن يُنزَّل fanart.jpg جديد بدقة أعلى — يجب ألا تُلمس النسخة القديمة.
    """
    item = make_item(tmp_path)
    (item.path / "background.jpg").write_bytes(b"OLD_BG")
    client = FakeClient(make_match(image_server))
    processor = Processor(AppConfig(download_fanart=True), client=client, images=ImageService())

    result = processor.process_item(item)

    assert result.backdrop_saved
    assert (item.path / "fanart.jpg").is_file()
    assert (item.path / "background.jpg").read_bytes() == b"OLD_BG"
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
    processor = Processor(AppConfig(download_fanart=True), client=client, images=ImageService())

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
    processor = Processor(AppConfig(download_fanart=True), client=client, images=ImageService())

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
    processor = Processor(
        AppConfig(download_fanart=True, download_background=True),
        client=client,
        images=ImageService(),
    )

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
        AppConfig(download_fanart=True),
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


# ----------------------------------------------------------------------
# output_root — المكتبات للقراءة فقط (B2/P13)
# ----------------------------------------------------------------------
def _output_config(library: Path, output: Path | None, **overrides) -> AppConfig:
    return AppConfig(
        library_path=str(library),
        output_root=str(output) if output is not None else "",
        **overrides,
    )


def _manifest_path(output: Path) -> Path:
    return output / ".mediaart_manifest.json"


def test_output_root_mirrors_library_relative_path(
    tmp_path: Path, image_server: str
) -> None:
    """B2-1: الصور تُكتب في output_root/<المسار النسبي>، والمصدر يبقى سليماً."""
    item = make_item(tmp_path)
    output = tmp_path / "out"
    config = _output_config(
        tmp_path, output, download_fanart=True, download_background=True
    )
    processor = Processor(
        config, client=FakeClient(make_match(image_server)), images=ImageService(quality=95)
    )

    summary = processor.run([item])

    target = output / item.path.name
    assert summary.ok == 1
    assert (target / "poster.jpg").is_file()
    assert (target / "fanart.jpg").is_file()
    assert (target / "background.jpg").is_file()
    # Source untouched: no image was written next to the media files.
    assert not (item.path / "poster.jpg").exists()
    assert not (item.path / "fanart.jpg").exists()
    processor.close()


def test_output_root_succeeds_with_read_only_source(
    tmp_path: Path, image_server: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B2-2: مصدر للقراءة فقط + output_root قابل للكتابة ⇒ نجاح لا ERROR."""
    item = make_item(tmp_path)
    output = tmp_path / "out"
    source = item.path.resolve()

    def writable_only_outside_source(folder: object) -> bool:
        return Path(folder).resolve() != source

    monkeypatch.setattr(
        "app.services.processor.is_folder_writable", writable_only_outside_source
    )
    config = _output_config(tmp_path, output)
    processor = Processor(
        config, client=FakeClient(make_match(image_server)), images=ImageService(quality=95)
    )

    result = processor.process_item(item)

    assert result.status is Status.OK
    assert (output / item.path.name / "poster.jpg").is_file()
    processor.close()


def test_output_root_second_run_is_idempotent(
    tmp_path: Path, image_server: str
) -> None:
    """B2-3: تشغيل ثانٍ لا يعيد الكتابة ولا يغيّر manifest."""
    item = make_item(tmp_path)
    output = tmp_path / "out"

    first = Processor(
        _output_config(tmp_path, output),
        client=FakeClient(make_match(image_server)),
        images=ImageService(quality=95),
    )
    first.run([item])
    first.close()
    before = _manifest_path(output).read_text(encoding="utf-8")
    poster_mtime = (output / item.path.name / "poster.jpg").stat().st_mtime_ns

    second_client = FakeClient(make_match(image_server))
    second = Processor(
        _output_config(tmp_path, output),
        client=second_client,
        images=ImageService(quality=95),
    )
    summary = second.run([item])
    second.close()

    assert second_client.calls == 0
    assert summary.skipped == 1
    assert (output / item.path.name / "poster.jpg").stat().st_mtime_ns == poster_mtime
    assert _manifest_path(output).read_text(encoding="utf-8") == before


def test_output_root_warns_about_untracked_files(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """B2-4: ملفات موجودة في output_root بلا سجل ⇒ تخطٍّ مع تحذير."""
    item = make_item(tmp_path)
    output = tmp_path / "out"
    target = output / item.path.name
    target.mkdir(parents=True)
    Image.new("RGB", (10, 10)).save(target / "poster.jpg", format="JPEG")
    Image.new("RGB", (10, 10)).save(target / "fanart.jpg", format="JPEG")
    client = FakeClient(None)
    processor = Processor(
        _output_config(tmp_path, output), client=client, images=ImageService()
    )

    with caplog.at_level(logging.WARNING, logger="mediaart.processor"):
        result = processor.process_item(item)

    assert result.status is Status.SKIPPED
    assert client.calls == 0
    assert "بلا سجل" in caplog.text
    processor.close()


def test_output_root_writes_manifest_structure(
    tmp_path: Path, image_server: str
) -> None:
    """B2-5: بنية manifest صحيحة بعد النجاح (version/entries/files/ts/status)."""
    item = make_item(tmp_path)
    output = tmp_path / "out"
    processor = Processor(
        _output_config(tmp_path, output, download_fanart=True),
        client=FakeClient(make_match(image_server)),
        images=ImageService(quality=95),
    )

    processor.run([item])
    processor.close()

    payload = json.loads(_manifest_path(output).read_text(encoding="utf-8"))
    assert payload["version"] == 1
    entry = payload["entries"][item.path.name]
    assert entry["status"] == "ok"
    assert "poster.jpg" in entry["files"]
    assert "fanart.jpg" in entry["files"]
    # ISO-8601 timestamp
    assert "T" in entry["ts"]


def test_without_output_root_behaves_as_before(
    tmp_path: Path, image_server: str
) -> None:
    """B2-6: بلا output_root ⇒ لا manifest والكتابة في المصدر (تراجعي)."""
    item = make_item(tmp_path)
    processor = Processor(
        AppConfig(), client=FakeClient(make_match(image_server)), images=ImageService(quality=95)
    )

    result = processor.process_item(item)
    processor.close()

    assert result.status is Status.OK
    assert (item.path / "poster.jpg").is_file()
    assert list(tmp_path.glob("**/.mediaart_manifest.json")) == []


def test_output_root_equal_to_library_is_ignored(
    tmp_path: Path, image_server: str
) -> None:
    """B2-7: output_root == library_path ⇒ سلوك as-if-None (لا manifest)."""
    item = make_item(tmp_path)
    processor = Processor(
        _output_config(tmp_path, tmp_path),
        client=FakeClient(make_match(image_server)),
        images=ImageService(quality=95),
    )

    result = processor.process_item(item)
    processor.close()

    assert processor.manifest is None
    assert result.status is Status.OK
    assert (item.path / "poster.jpg").is_file()
    assert list(tmp_path.glob("**/.mediaart_manifest.json")) == []


# ----------------------------------------------------------------------
# أنواع الصور المستقلة (A-types)
# ----------------------------------------------------------------------
#: (poster, fanart, background) ⇒ (الملفات المتوقعة، طلبات poster، طلبات backdrop)
_IMAGE_CASES = [
    (False, False, False, set(), 0, 0),
    (False, False, True, {"background.jpg"}, 0, 1),
    (False, True, False, {"fanart.jpg"}, 0, 1),
    (False, True, True, {"fanart.jpg", "background.jpg"}, 0, 1),
    (True, False, False, {"poster.jpg"}, 1, 0),
    (True, False, True, {"poster.jpg", "background.jpg"}, 1, 1),
    (True, True, False, {"poster.jpg", "fanart.jpg"}, 1, 1),
    (True, True, True, {"poster.jpg", "fanart.jpg", "background.jpg"}, 1, 1),
]


@pytest.mark.parametrize(
    "poster,fanart,background,present,poster_requests,backdrop_requests",
    _IMAGE_CASES,
)
def test_image_types_are_independent(
    tmp_path: Path,
    counting_server,
    poster: bool,
    fanart: bool,
    background: bool,
    present: set[str],
    poster_requests: int,
    backdrop_requests: int,
) -> None:
    """C000–C111: كل نوع يُنزَّل ويُكتب بذاته، والخلفية بطلب واحد فقط."""
    base, counts = counting_server
    item = make_item(tmp_path)
    config = AppConfig(
        download_poster=poster,
        download_fanart=fanart,
        download_background=background,
        jpeg_quality=95,
    )
    processor = Processor(
        config, client=FakeClient(make_match(base)), images=ImageService(quality=95)
    )

    result = processor.process_item(item)
    processor.close()

    found = {
        name
        for name in ("poster.jpg", "fanart.jpg", "background.jpg")
        if (item.path / name).is_file()
    }
    assert found == present
    assert counts == {"poster": poster_requests, "backdrop": backdrop_requests}
    expected = Status.SKIPPED if not present else Status.OK
    assert result.status is expected


def test_existing_poster_is_not_downloaded_again(
    tmp_path: Path, counting_server
) -> None:
    """X1: poster.jpg موجود مسبقاً ⇒ لا طلب ملصق إطلاقاً."""
    base, counts = counting_server
    item = make_item(tmp_path)
    Image.new("RGB", (10, 10)).save(item.path / "poster.jpg", format="JPEG")
    processor = Processor(
        AppConfig(download_poster=True),
        client=FakeClient(make_match(base)),
        images=ImageService(),
    )

    result = processor.process_item(item)
    processor.close()

    assert result.status is Status.SKIPPED
    assert counts == {"poster": 0, "backdrop": 0}


def test_missing_background_is_downloaded_not_copied(
    tmp_path: Path, counting_server
) -> None:
    """X2: fanart موجود + background مطلوب ⇒ تنزيل جديد لا نسخ من fanart."""
    base, counts = counting_server
    item = make_item(tmp_path)
    Image.new("RGB", (10, 10), (0, 0, 255)).save(
        item.path / "fanart.jpg", format="JPEG"
    )
    fanart_before = (item.path / "fanart.jpg").read_bytes()
    processor = Processor(
        AppConfig(download_poster=False, download_fanart=False, download_background=True),
        client=FakeClient(make_match(base)),
        images=ImageService(quality=95),
    )

    processor.process_item(item)
    processor.close()

    with Image.open(item.path / "background.jpg") as downloaded:
        assert downloaded.size == (120, 180)
    assert (item.path / "fanart.jpg").read_bytes() == fanart_before
    assert counts["backdrop"] == 1


def test_disabling_a_type_keeps_the_existing_file(
    tmp_path: Path, counting_server
) -> None:
    """X3: إطفاء fanart بعد إنشائه ⇒ الملف يبقى ولا يُحذف."""
    base, counts = counting_server
    item = make_item(tmp_path)
    first = Processor(
        AppConfig(download_poster=False, download_fanart=True),
        client=FakeClient(make_match(base)),
        images=ImageService(),
    )
    first.process_item(item)
    first.close()
    before = (item.path / "fanart.jpg").read_bytes()

    second = Processor(
        AppConfig(download_poster=False, download_fanart=False),
        client=FakeClient(make_match(base)),
        images=ImageService(),
    )
    result = second.process_item(item)
    second.close()

    assert result.status is Status.SKIPPED
    assert (item.path / "fanart.jpg").read_bytes() == before
    assert counts["backdrop"] == 1


def test_missing_backdrop_is_skipped_not_error(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """X4: فيلم قديم بلا خلفية ⇒ تحذير + SKIPPED (لا ERROR)."""
    item = make_item(tmp_path)
    match = make_match("http://127.0.0.1:1")
    match.backdrop_path = None
    processor = Processor(
        AppConfig(download_poster=False, download_fanart=True),
        client=FakeClient(match),
        images=ImageService(),
    )

    with caplog.at_level(logging.WARNING, logger="mediaart.processor"):
        result = processor.process_item(item)
    processor.close()

    assert result.status is Status.SKIPPED
    assert "لا يوجد رابط خلفية" in result.message
    assert "لا يوجد رابط خلفية" in caplog.text


def test_failed_requested_type_with_only_unrequested_file_is_error(
    tmp_path: Path, image_server: str
) -> None:
    """X5: فشل النوع المطلوب وحده ⇒ ERROR، لا PARTIAL بفضل ملف غير مطلوب.

    fanart.jpg موجود من تشغيل سابق لكن النوع المطلوب هو background فقط؛ فشل
    تنزيله لا يجوز أن يُحتسب «نجاحاً جزئياً» ولا أن يُخرج رمز 0 من CLI.
    """
    item = make_item(tmp_path)
    Image.new("RGB", (10, 10), (0, 0, 255)).save(
        item.path / "fanart.jpg", format="JPEG"
    )
    match = make_match(image_server)
    match.backdrop_path = f"{image_server}/missing.jpg"
    processor = Processor(
        AppConfig(download_poster=False, download_background=True),
        client=FakeClient(match),
        images=ImageService(),
    )

    result = processor.process_item(item)
    processor.close()

    assert result.status is Status.ERROR
    assert "الخلفية" in result.message
    assert not (item.path / "background.jpg").exists()


def test_output_root_warns_about_untracked_background(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """B2-4b: background.jpg وحده بلا سجل ⇒ تحذير «بلا سجل» ثم تخطٍّ."""
    item = make_item(tmp_path)
    output = tmp_path / "out"
    target = output / item.path.name
    target.mkdir(parents=True)
    Image.new("RGB", (10, 10)).save(target / "background.jpg", format="JPEG")
    client = FakeClient(None)
    processor = Processor(
        _output_config(
            tmp_path, output, download_poster=False, download_background=True
        ),
        client=client,
        images=ImageService(),
    )

    with caplog.at_level(logging.WARNING, logger="mediaart.processor"):
        result = processor.process_item(item)

    assert result.status is Status.SKIPPED
    assert client.calls == 0
    assert "بلا سجل" in caplog.text
    assert "background.jpg" in caplog.text
    processor.close()


# ----------------------------------------------------------------------
# فشل مبكر لـoutput_root + رسائل D2 (D1/D2)
# ----------------------------------------------------------------------
BAD_OUTPUT_ROOT = "Z:/nonexistent_xyz_123"


def test_unusable_output_root_fails_at_config_construction(tmp_path: Path) -> None:
    """F4-1: مسار إخراج غير قابل للإنشاء ⇒ ValueError يذكر المسار الفعلي."""
    with pytest.raises(ValueError) as excinfo:
        AppConfig(output_root=BAD_OUTPUT_ROOT)

    message = str(excinfo.value)
    # المسار الفعلي بعد تطبيع Path (فواصل Windows على هذه المنصة).
    assert str(Path(BAD_OUTPUT_ROOT)) in message
    assert "غير قابل للإنشاء" in message


def test_unusable_output_root_fails_before_any_processing(tmp_path: Path) -> None:
    """F4-2: مجلد صالح عند بناء config ثم اختفى ⇒ Processor يفشل فوراً.

    هذا هو الفراغ الزمني بين `AppConfig.__post_init__` وبناء المعالج (انقطاع
    شبكة أو نزع قرص)؛ بدونه كان الفشل يظهر ERROR لكل عنصر.
    """
    config = AppConfig()
    config.output_root = BAD_OUTPUT_ROOT

    with pytest.raises(ValueError) as excinfo:
        Processor(config, client=FakeClient(None), images=ImageService())

    assert str(Path(BAD_OUTPUT_ROOT)) in str(excinfo.value)


def test_webp_conversion_is_disabled_once_with_output_root(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """F5/D2: output_root ⇒ لا تحويل، تحذير واحد، SKIPPED، webp_converted=0."""
    item = make_item(tmp_path)
    webp = make_webp(item.path / "poster.webp")
    output = tmp_path / "out"
    processor = Processor(
        _output_config(tmp_path, output, convert_only=True),
        client=FakeClient(None),
        images=ImageService(),
    )

    with caplog.at_level(logging.WARNING, logger="mediaart.processor"):
        summary = processor.run([item])
    processor.close()

    result = summary.results[0]
    assert result.status is Status.SKIPPED
    assert summary.webp_converted == 0
    assert webp.is_file()  # المصدر لم يُلمس
    warnings = [
        record.getMessage()
        for record in caplog.records
        if "تم تعطيل تحويل WebP" in record.getMessage()
    ]
    assert len(warnings) == 1


def test_processor_rejects_mismatched_media_type(tmp_path: Path) -> None:
    """AC-7: المعالج يرفض نتيجة TMDB إذا لم يتطابق media_type مع نوع العنصر."""
    item = MediaItem(
        path=tmp_path / "Show (2024)",
        kind=MediaKind.SERIES,
        title="Show",
        year=2024,
    )
    item.path.mkdir(parents=True, exist_ok=True)
    (item.path / "S01E01.mkv").write_bytes(b"")

    # نتيجة فيلم لنفس العنوان (نوع مخالف)
    mismatched_match = TMDBMatch(
        tmdb_id=12345,
        media_type="movie",
        title="Show",
        original_title="Show",
        year=2024,
        poster_path="/poster.jpg",
        backdrop_path="/backdrop.jpg",
    )
    client = FakeClient(mismatched_match)

    config = AppConfig()
    config.library_path = str(tmp_path)
    config.download_poster = True
    config.download_fanart = False
    config.download_background = False

    processor = Processor(config, client=client, images=ImageService())
    summary = processor.run([item])
    processor.close()

    result = summary.results[0]
    assert result.status is Status.NOT_FOUND
    assert "نوع العمل غير متطابق" in result.message


# ----------------------------------------------------------------------
# Fanart toggle — استكمال حالات القبول (استقلالية/منع تنزيل/عدم اكتمال)
# ----------------------------------------------------------------------
def test_fanart_disabled_background_enabled_downloads_only_background(
    tmp_path: Path, counting_server
) -> None:
    """Fanart معطّل + Background مفعّل ⇒ حفظ background.jpg فقط من backdrop (طلب واحد)."""
    base, counts = counting_server
    item = make_item(tmp_path)
    processor = Processor(
        AppConfig(download_poster=False, download_fanart=False, download_background=True),
        client=FakeClient(make_match(base)),
        images=ImageService(quality=95),
    )

    result = processor.process_item(item)
    processor.close()

    assert result.status is Status.OK
    assert not (item.path / "fanart.jpg").exists()
    assert (item.path / "background.jpg").is_file()
    assert not (item.path / "poster.jpg").exists()
    assert counts == {"poster": 0, "backdrop": 1}


def test_fanart_and_background_disabled_do_not_download_backdrop(
    tmp_path: Path, counting_server
) -> None:
    """Fanart وBackground معطّلان ⇒ لا تنزيل/حفظ لصورة الخلفية ولا poster."""
    base, counts = counting_server
    item = make_item(tmp_path)
    processor = Processor(
        AppConfig(download_poster=False, download_fanart=False, download_background=False),
        client=FakeClient(make_match(base)),
        images=ImageService(),
    )

    result = processor.process_item(item)
    processor.close()

    assert result.status is Status.SKIPPED
    assert not (item.path / "fanart.jpg").exists()
    assert not (item.path / "background.jpg").exists()
    assert not (item.path / "poster.jpg").exists()
    assert counts == {"poster": 0, "backdrop": 0}


def test_existing_fanart_kept_when_disabled_even_with_overwrite(
    tmp_path: Path, image_server: str
) -> None:
    """Fanart معطّل + overwrite_images=True ⇒ لا حذف/استبدال لـ fanart.jpg الموجود."""
    item = make_item(tmp_path)
    fanart_file = item.path / "fanart.jpg"
    Image.new("RGB", (10, 10), (10, 20, 30)).save(fanart_file, format="JPEG")
    before = fanart_file.read_bytes()

    processor = Processor(
        AppConfig(
            download_poster=True,
            download_fanart=False,
            download_background=False,
            overwrite_images=True,
        ),
        client=FakeClient(make_match(image_server)),
        images=ImageService(quality=95),
    )

    result = processor.process_item(item)
    processor.close()

    assert fanart_file.read_bytes() == before
    with Image.open(fanart_file) as kept:
        assert kept.size == (10, 10)
    assert (item.path / "poster.jpg").is_file()
    assert result.status in (Status.OK, Status.PARTIAL)


def test_poster_and_background_continue_independently_when_fanart_disabled(
    tmp_path: Path, image_server: str
) -> None:
    """تعطيل Fanart لا يؤثر على تنزيل Poster وBackground واستقلالهما."""
    item = make_item(tmp_path)
    processor = Processor(
        AppConfig(
            download_poster=True,
            download_fanart=False,
            download_background=True,
            jpeg_quality=95,
        ),
        client=FakeClient(make_match(image_server)),
        images=ImageService(quality=95),
    )

    result = processor.process_item(item)
    processor.close()

    assert result.status is Status.OK
    assert (item.path / "poster.jpg").is_file()
    assert (item.path / "background.jpg").is_file()
    assert not (item.path / "fanart.jpg").exists()


def test_disabled_fanart_not_required_for_completion_when_others_ok(
    tmp_path: Path, image_server: str
) -> None:
    """غياب fanart.jpg لا يجعل العمل ناقصاً إذا كان Fanart معطّلاً والأنواع المطلوبة مكتملة."""
    item = make_item(tmp_path)
    processor = Processor(
        AppConfig(download_poster=True, download_fanart=False, download_background=False),
        client=FakeClient(make_match(image_server)),
        images=ImageService(quality=95),
    )

    result = processor.process_item(item)
    processor.close()

    assert result.status is Status.OK
    assert (item.path / "poster.jpg").is_file()
    assert not (item.path / "fanart.jpg").exists()


def test_disabled_fanart_missing_does_not_force_incomplete_when_requested_images_exist(
    tmp_path: Path,
) -> None:
    """عدم اكتمال Fanart غير مطلوب لا يُعد نقصاً: الصور المطلوبة موجودة ⇒ SKIPPED طبيعي."""
    item = make_item(tmp_path)
    Image.new("RGB", (10, 10)).save(item.path / "poster.jpg", format="JPEG")
    Image.new("RGB", (10, 10)).save(item.path / "background.jpg", format="JPEG")
    client = FakeClient(None)
    processor = Processor(
        AppConfig(download_poster=True, download_fanart=False, download_background=True),
        client=client,
        images=ImageService(),
    )

    result = processor.process_item(item)
    processor.close()

    assert result.status is Status.SKIPPED
    assert client.calls == 0
    assert not (item.path / "fanart.jpg").exists()
    assert "الصور المطلوبة موجودة مسبقاً" in result.message
