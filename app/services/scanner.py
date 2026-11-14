"""Recursive library scanner with movie / series detection.

Rules (keep these in sync with docs/DEVELOPER_GUIDE.md):

* A folder that directly contains video files is a media item.
* If it also contains season/episode sub-folders, or its own video files carry
  SxxEyy markers, it is a **series root** and is never descended into.
* A series is processed exactly once: artwork goes to the series root only.
* Loose video files inside "category" folders (a flat library) are skipped with
  a warning, because there is no safe place to write per-title artwork.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Callable

from ..logging_setup import get_logger
from ..models import MediaItem, MediaKind
from .title_cleaner import clean_title

VIDEO_EXTENSIONS = frozenset({
    ".mkv", ".mp4", ".avi", ".mov", ".m4v", ".wmv", ".flv", ".webm",
    ".mpg", ".mpeg", ".m2ts", ".ts", ".vob", ".iso",
})

MAX_DEPTH = 15
logger = get_logger("scanner")

_IGNORED_DIRS = frozenset({
    "@eadir", "#recycle", "$recycle.bin", "system volume information",
    "lost+found", "sample", "samples", "trailer", "trailers", "featurettes",
    "featurette", "behind the scenes", "deleted scenes", "interviews",
    "subtitles", "subs", "artwork", "posters", "backdrops", "metadata", "nfo",
    # "Specials" is a very common *extras* folder inside a movie folder: it is
    # not a season, and treating it as one would misclassify the movie as a
    # series (and hide its videos from the scan).
    "specials", "special",
    ".actors", ".deletedbyttmm",
})

_GENERIC_DIRS = frozenset({
    "movies", "movie", "films", "film", "tv", "tv shows", "tvshows", "shows",
    "series", "media", "library", "libraries", "downloads", "download",
    "video", "videos", "أفلام", "افلام", "مسلسلات", "مكتبة", "تنزيلات",
})

_SAMPLE_RE = re.compile(
    r"(?i)(?:^|[\s._-])(?:sample|trailer|teaser|featurette|"
    r"behind[\s._-]?the[\s._-]?scenes)(?:$|[\s._-])"
)
_EPISODE_MARKER_RE = re.compile(
    r"(?i)(?<![\w])(?:s\d{1,2}(?:e\d{1,3})?|\d{1,2}x\d{1,3}|"
    r"(?:episode|ep|الحلقة|حلقة)\s*[._-]?\s*\d{1,3})(?![\w])"
)
_SEASON_DIR_RE = re.compile(
    r"""(?ix)^
    (?:
        (?:season|series|s|الموسم)\s*[._-]?\s*
        (?:\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten|
           الأول|الأولي|الثاني|الثالث|الرابع|الخامس|السادس|السابع|الثامن|التاسع|العاشر)
    )
    (?:[\s._-].*)?$
    """
)
_EPISODE_DIR_RE = re.compile(
    r"""(?ix)^(?:
        s\d{1,2}(?:e\d{1,3})?
      | \d{1,2}x\d{1,3}
      | (?:episode|ep|حلقة|الحلقة)\s*[._-]?\s*\d{1,3}
    )$
    """
)


def is_video_file(name: str) -> bool:
    return Path(name).suffix.lower() in VIDEO_EXTENSIONS


def is_probably_sample(name: str) -> bool:
    return bool(_SAMPLE_RE.search(Path(name).stem))


def looks_like_season_dir(name: str) -> bool:
    return bool(_SEASON_DIR_RE.match(name.strip()))


def looks_like_episode_dir(name: str) -> bool:
    return bool(_EPISODE_DIR_RE.match(name.strip()))


def has_episode_marker(name: str) -> bool:
    return bool(_EPISODE_MARKER_RE.search(Path(name).stem))


def discover_media(
    root: Path | str,
    media_filter: str = "all",
    *,
    should_cancel: Callable[[], bool] | None = None,
) -> list[MediaItem]:
    """Return artwork targets under *root*.

    ``media_filter`` is one of ``all``, ``movies`` or ``series``.
    When ``should_cancel`` returns True the walk stops between folders and the
    items discovered so far are returned (a NAS scan can take minutes).
    """
    root_path = Path(root).expanduser().resolve()
    if not root_path.is_dir():
        raise NotADirectoryError(f"ليس مجلداً صالحاً: {root_path}")

    if looks_like_season_dir(root_path.name) or looks_like_episode_dir(root_path.name):
        logger.warning(
            "المسار المحدد يبدو أنه مجلد موسم/حلقة (%s). اختر مجلد المسلسل الأب.",
            root_path.name,
        )
        return []

    include_movies = media_filter in {"all", "movies"}
    include_series = media_filter in {"all", "series"}
    items: list[MediaItem] = []
    visited: set[Path] = set()

    for dirpath, dirnames, filenames in os.walk(root_path, topdown=True, followlinks=False):
        if should_cancel is not None and should_cancel():
            logger.info("تم إيقاف الفحص يدوياً بعد %d عنصر.", len(items))
            break
        current = Path(dirpath)

        try:
            real_path = current.resolve()
        except OSError:
            real_path = current
        if real_path in visited:
            dirnames[:] = []
            continue
        visited.add(real_path)

        try:
            depth = len(current.relative_to(root_path).parts)
        except ValueError:
            depth = 0
        if depth > MAX_DEPTH:
            logger.warning("تم تجاهل مجلد عميق جداً: %s", current)
            dirnames[:] = []
            continue

        dirnames[:] = sorted(
            name for name in dirnames
            if not _should_ignore_dir(name) and name.lower() not in _IGNORED_DIRS
        )

        videos = _main_videos(current, filenames)
        season_children = [
            name for name in dirnames
            if looks_like_season_dir(name) or looks_like_episode_dir(name)
        ]
        is_series = bool(season_children or (videos and any(has_episode_marker(v.name) for v in videos)))

        if is_series:
            if include_series:
                item = _build_item(current, MediaKind.SERIES, videos)
                if item:
                    items.append(item)
            else:
                logger.debug("تخطي مسلسل حسب الفلتر: %s", current)
            dirnames[:] = []
            continue

        if videos:
            if _is_generic_folder(current.name) or (current == root_path and len(videos) > 1):
                logger.warning(
                    "تم تجاهل %d ملف(ات) فيديو مباشرة داخل '%s'. المكتبة المسطحة غير مدعومة؛ "
                    "ضع كل فيلم في مجلد مستقل.",
                    len(videos), current,
                )
                continue
            if include_movies:
                item = _build_item(current, MediaKind.MOVIE, videos)
                if item:
                    items.append(item)
            else:
                logger.debug("تخطي فيلم حسب الفلتر: %s", current)
            dirnames[:] = []
            continue

        # No direct videos: container folder, keep walking.

    items.sort(key=lambda item: str(item.path).casefold())
    logger.info("اكتمل الفحص: %d عنصر قابل للمعالجة في %s", len(items), root_path)
    return items


def _should_ignore_dir(name: str) -> bool:
    lowered = name.lower()
    return (
        name.startswith(".")
        or name.startswith("$")
        or name.startswith("@")
        or lowered in _IGNORED_DIRS
        or lowered == "__macosx"
    )


def _is_generic_folder(name: str) -> bool:
    return name.strip().casefold() in _GENERIC_DIRS


def _main_videos(folder: Path, filenames: list[str]) -> list[Path]:
    videos: list[Path] = []
    for filename in sorted(filenames):
        if is_video_file(filename) and not is_probably_sample(filename):
            videos.append(folder / filename)
    return videos


def _build_item(folder: Path, kind: MediaKind, videos: list[Path]) -> MediaItem | None:
    cleaned = clean_title(folder.name)
    if not cleaned.title and videos:
        cleaned = clean_title(videos[0].name)
    if not cleaned.title:
        logger.warning("تعذر استخراج عنوان من: %s", folder)
        return None
    return MediaItem(
        path=folder,
        kind=kind,
        title=cleaned.title,
        year=cleaned.year,
        raw_name=folder.name,
    )
