from __future__ import annotations

import io
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from PIL import Image

from app.config import AppConfig
from app.models import MediaItem, MediaKind, Status, TMDBMatch
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


def test_dry_run_does_not_write_files(tmp_path: Path, image_server: str) -> None:
    item = make_item(tmp_path)
    config = AppConfig(dry_run=True)
    processor = Processor(config, client=FakeClient(make_match(image_server)), images=ImageService())

    result = processor.process_item(item)

    assert result.status is Status.OK
    assert result.dry_run
    assert not (item.path / "poster.jpg").exists()
    assert not (item.path / "fanart.jpg").exists()
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
