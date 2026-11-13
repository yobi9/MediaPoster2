from __future__ import annotations

from pathlib import Path

from app.models import MediaKind
from app.services.scanner import (
    discover_media,
    has_episode_marker,
    looks_like_episode_dir,
    looks_like_season_dir,
)


def touch(base: Path, relative: str, content: bytes = b"") -> Path:
    target = base / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return target


def test_discovers_movies_and_series_without_duplicates(tmp_path: Path) -> None:
    touch(tmp_path, "Movies/Inception (2010)/Inception.2010.1080p.mkv")
    touch(tmp_path, "Movies/Inception (2010)/sample.mkv")
    touch(tmp_path, "Movies/[YTS] Interstellar (2014)/Interstellar.2014.mkv")
    touch(tmp_path, "TV/Breaking Bad (2008)/Season 1/S01E01.mkv")
    touch(tmp_path, "TV/Breaking Bad (2008)/Season 2/S02E01.mkv")
    touch(tmp_path, "TV/Friends/Friends.S01E01.mkv")
    touch(tmp_path, "TV/Friends/S01E02.mkv")

    items = discover_media(tmp_path)
    by_title = {item.title: item for item in items}

    assert set(by_title) == {"Inception", "Interstellar", "Breaking Bad", "Friends"}
    assert by_title["Inception"].kind is MediaKind.MOVIE
    assert by_title["Inception"].year == 2010
    assert by_title["Breaking Bad"].kind is MediaKind.SERIES
    assert by_title["Breaking Bad"].year == 2008
    assert by_title["Friends"].kind is MediaKind.SERIES

    # Series are processed once at the parent folder, never at season folders.
    series_paths = [item.path for item in items if item.kind is MediaKind.SERIES]
    assert all("Season" not in path.name for path in series_paths)


def test_selected_movie_folder_is_itself_an_item(tmp_path: Path) -> None:
    movie = tmp_path / "Inception (2010)"
    touch(movie, "Inception.2010.1080p.mkv")
    items = discover_media(movie)
    assert len(items) == 1
    assert items[0].kind is MediaKind.MOVIE
    assert items[0].title == "Inception"


def test_selected_season_folder_is_rejected(tmp_path: Path) -> None:
    season = tmp_path / "Season 1"
    touch(season, "S01E01.mkv")
    assert discover_media(season) == []


def test_flat_library_is_skipped(tmp_path: Path) -> None:
    touch(tmp_path, "Loose Movie 2020.mkv")
    touch(tmp_path, "Another Movie 2021.mkv")
    assert discover_media(tmp_path) == []


def test_media_filter(tmp_path: Path) -> None:
    touch(tmp_path, "Movies/Inception (2010)/Inception.mkv")
    touch(tmp_path, "TV/Show/Season 1/S01E01.mkv")

    movies = discover_media(tmp_path, media_filter="movies")
    series = discover_media(tmp_path, media_filter="series")

    assert [item.kind for item in movies] == [MediaKind.MOVIE]
    assert [item.kind for item in series] == [MediaKind.SERIES]


def test_helpers() -> None:
    assert looks_like_season_dir("Season 1")
    assert looks_like_season_dir("S02")
    assert looks_like_season_dir("الموسم الأول")
    assert not looks_like_season_dir("Se7en")

    assert looks_like_episode_dir("S01E01")
    assert looks_like_episode_dir("1x03")
    assert not looks_like_episode_dir("Season 1")

    assert has_episode_marker("Show.S01E02.1080p.mkv")
    assert has_episode_marker("Show 1x02.mkv")
    assert not has_episode_marker("Movie.2020.mkv")


def test_media_filter_movies_only_excludes_series(tmp_path: Path) -> None:
    """AC-3: media_filter="movies" يستبعد المسلسلات من الماسح، فلا تصل إلى TMDB."""
    touch(tmp_path, "Movies/Inception (2010)/Inception.mkv")
    touch(tmp_path, "TV/Show/Season 1/S01E01.mkv")

    movies = discover_media(tmp_path, media_filter="movies")

    assert [item.kind for item in movies] == [MediaKind.MOVIE]
    assert all(item.kind is MediaKind.MOVIE for item in movies)


def test_media_filter_series_only_excludes_movies(tmp_path: Path) -> None:
    """AC-4: media_filter="series" يستبعد الأفلام من الماسح، فلا تصل إلى TMDB."""
    touch(tmp_path, "Movies/Inception (2010)/Inception.mkv")
    touch(tmp_path, "TV/Show/Season 1/S01E01.mkv")

    series = discover_media(tmp_path, media_filter="series")

    assert [item.kind for item in series] == [MediaKind.SERIES]
    assert all(item.kind is MediaKind.SERIES for item in series)
