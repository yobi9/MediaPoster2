"""Plain data objects shared by the core, the CLI and the GUI."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class MediaKind(str, Enum):
    MOVIE = "movie"
    SERIES = "series"

    @property
    def label_ar(self) -> str:
        return "فيلم" if self is MediaKind.MOVIE else "مسلسل"

    @property
    def tmdb_type(self) -> str:
        return "movie" if self is MediaKind.MOVIE else "tv"


class Status(str, Enum):
    OK = "ok"
    PARTIAL = "partial"
    SKIPPED = "skipped"
    NOT_FOUND = "not_found"
    ERROR = "error"
    CANCELLED = "cancelled"
    PREVIEW = "preview"

    @property
    def label_ar(self) -> str:
        return {
            Status.OK: "تم بنجاح",
            Status.PARTIAL: "تم جزئياً",
            Status.SKIPPED: "تم التخطي",
            Status.NOT_FOUND: "غير موجود",
            Status.ERROR: "خطأ",
            Status.CANCELLED: "ملغى",
            Status.PREVIEW: "معاينة",
        }[self]


class ImageType(str, Enum):
    POSTER = "poster"
    BACKDROP = "backdrop"


@dataclass(slots=True)
class MediaItem:
    """A single movie folder or a series root folder."""

    path: Path
    kind: MediaKind
    title: str
    year: int | None = None
    raw_name: str = ""

    def __post_init__(self) -> None:
        self.path = Path(self.path)
        if not self.raw_name:
            self.raw_name = self.path.name


@dataclass(slots=True)
class TMDBMatch:
    tmdb_id: int
    media_type: str  # "movie" | "tv"
    title: str
    original_title: str
    year: int | None
    poster_path: str | None = None
    backdrop_path: str | None = None
    popularity: float = 0.0
    vote_average: float = 0.0
    overview: str = ""

    @property
    def is_series(self) -> bool:
        return self.media_type == "tv"

    def to_cache(self) -> dict:
        return {
            "tmdb_id": self.tmdb_id,
            "media_type": self.media_type,
            "title": self.title,
            "original_title": self.original_title,
            "year": self.year,
            "poster_path": self.poster_path,
            "backdrop_path": self.backdrop_path,
            "popularity": self.popularity,
            "vote_average": self.vote_average,
            "overview": self.overview,
        }

    @classmethod
    def from_cache(cls, data: dict) -> "TMDBMatch":
        return cls(
            tmdb_id=int(data.get("tmdb_id") or 0),
            media_type=str(data.get("media_type") or "movie"),
            title=str(data.get("title") or ""),
            original_title=str(data.get("original_title") or ""),
            year=int(data["year"]) if data.get("year") else None,
            poster_path=data.get("poster_path") or None,
            backdrop_path=data.get("backdrop_path") or None,
            popularity=float(data.get("popularity") or 0.0),
            vote_average=float(data.get("vote_average") or 0.0),
            overview=str(data.get("overview") or ""),
        )


@dataclass(slots=True)
class ItemResult:
    item: MediaItem
    status: Status
    message: str = ""
    matched_title: str | None = None
    poster_saved: bool = False
    backdrop_saved: bool = False
    webp_converted: int = 0
    #: عدد ملفات WebP التي "سيتم" تحويلها (وضع المعاينة فقط).
    webp_would_convert: int = 0
    dry_run: bool = False
    target_writable: bool = True

    @property
    def is_success(self) -> bool:
        return self.status in (Status.OK, Status.PARTIAL)


@dataclass(slots=True)
class RunSummary:
    total: int = 0
    results: list[ItemResult] = field(default_factory=list)
    duration: float = 0.0
    cancelled: bool = False
    webp_converted: int = 0
    webp_would_convert: int = 0

    def _count(self, *statuses: Status) -> int:
        return sum(1 for result in self.results if result.status in statuses)

    @property
    def ok(self) -> int:
        return self._count(Status.OK)

    @property
    def partial(self) -> int:
        return self._count(Status.PARTIAL)

    @property
    def succeeded(self) -> int:
        return self.ok + self.partial

    @property
    def skipped(self) -> int:
        return self._count(Status.SKIPPED)

    @property
    def not_found(self) -> int:
        return self._count(Status.NOT_FOUND)

    @property
    def errors(self) -> int:
        return self._count(Status.ERROR)

    @property
    def cancelled_count(self) -> int:
        return self._count(Status.CANCELLED)

    @property
    def preview(self) -> int:
        return self._count(Status.PREVIEW)

    def summary_text(self) -> str:
        parts = [
            f"الإجمالي: {self.total}",
            f"نجح: {self.succeeded}",
            f"متخطى: {self.skipped}",
            f"غير موجود: {self.not_found}",
            f"أخطاء: {self.errors}",
        ]
        if self.preview:
            parts.append(f"معاينة: {self.preview}")
        if self.webp_converted:
            parts.append(f"WebP→JPG: {self.webp_converted}")
        if self.webp_would_convert:
            parts.append(f"سيتم تحويل WebP: {self.webp_would_convert}")
        if self.cancelled:
            parts.append("تم الإيقاف يدوياً")
        return " • ".join(parts)
