from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from app.services.images import (
    convert_to_jpeg,
    convert_webp_file,
    convert_webp_in_folder,
    is_folder_writable,
)


def make_webp(path: Path, size: tuple[int, int] = (40, 60)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGBA", size, (255, 0, 0, 128))
    image.save(path, format="WEBP")
    return path


def test_convert_webp_deletes_source(tmp_path: Path) -> None:
    source = make_webp(tmp_path / "poster.webp")
    target = convert_webp_file(source, quality=95, delete_source=True)

    assert target == tmp_path / "poster.jpg"
    assert target.is_file()
    assert not source.exists()
    with Image.open(target) as image:
        assert image.format == "JPEG"
        assert image.mode == "RGB"
        assert image.size == (40, 60)


def test_existing_jpg_is_not_overwritten_by_default(tmp_path: Path) -> None:
    source = make_webp(tmp_path / "poster.webp")
    existing = tmp_path / "poster.jpg"
    Image.new("RGB", (10, 10), (0, 0, 255)).save(existing, format="JPEG")

    assert convert_webp_file(source, quality=95, overwrite=False) is None
    assert source.exists()
    with Image.open(existing) as image:
        assert image.size == (10, 10)


def test_convert_folder_recursive_and_dry_run(tmp_path: Path) -> None:
    first = make_webp(tmp_path / "poster.webp")
    nested = make_webp(tmp_path / "Season 1" / "season.webp")

    preview = convert_webp_in_folder(tmp_path, recursive=True, dry_run=True)
    assert preview.converted == 2
    assert first.exists() and nested.exists()

    result = convert_webp_in_folder(tmp_path, recursive=True)
    assert result.converted == 2
    assert (tmp_path / "poster.jpg").is_file()
    assert (tmp_path / "Season 1" / "season.jpg").is_file()
    assert not first.exists() and not nested.exists()


def test_convert_to_jpeg_accepts_png(tmp_path: Path) -> None:
    source = tmp_path / "image.png"
    Image.new("RGBA", (30, 20), (0, 255, 0, 50)).save(source, format="PNG")
    target = convert_to_jpeg(source, tmp_path / "image.jpg", quality=100)
    assert target.is_file()
    with Image.open(target) as image:
        assert image.mode == "RGB"


def test_writable_folder_is_detected(tmp_path: Path) -> None:
    assert is_folder_writable(tmp_path) is True
    # the probe file must not survive the check
    assert list(tmp_path.iterdir()) == []


def test_missing_folder_is_not_writable(tmp_path: Path) -> None:
    assert is_folder_writable(tmp_path / "does-not-exist") is False


def test_unwritable_folder_is_detected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A folder that refuses new files must be reported as unwritable."""

    def deny(*args: object, **kwargs: object) -> None:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr("builtins.open", deny)
    assert is_folder_writable(tmp_path) is False
