"""Configuration, storage locations and persistence.

The GUI and the CLI share the same :class:`AppConfig` object which is stored as
JSON next to the log file (``%LOCALAPPDATA%/MediaArtAutoSync`` on Windows).
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, get_type_hints

APP_NAME = "MediaArt Auto-Sync"
APP_SLUG = "MediaArtAutoSync"
VERSION = "1.0.0"

# Uses the stdlib logger directly: ``logging_setup`` imports this module, so
# importing it back would create a circular dependency.
logger = logging.getLogger("mediaart.config")

SUPPORTED_LANGUAGES: tuple[tuple[str, str], ...] = (
    ("ar", "العربية"),
    ("en", "English"),
    ("fr", "Français"),
    ("de", "Deutsch"),
    ("es", "Español"),
    ("tr", "Türkçe"),
    ("ja", "日本語"),
    ("ko", "한국어"),
)

# حدود جودة JPEG المعتمدة في التطبيق (نفس حدود _clamp_quality في images.py).
MIN_JPEG_QUALITY = 60
MAX_JPEG_QUALITY = 100
DEFAULT_JPEG_QUALITY = 95

# أحجام صور TMDB المتاحة (https://image.tmdb.org/t/p/{size}/{file_path}).
POSTER_SIZES: tuple[str, ...] = ("w185", "w342", "w500", "w780", "original")
BACKDROP_SIZES: tuple[str, ...] = ("w300", "w780", "w1280", "original")
DEFAULT_POSTER_SIZE = "w500"
DEFAULT_BACKDROP_SIZE = "w780"

MEDIA_FILTERS: tuple[tuple[str, str], ...] = (
    ("all", "الكل (أفلام + مسلسلات)"),
    ("movies", "أفلام فقط"),
    ("series", "مسلسلات فقط"),
)


def get_data_dir() -> Path:
    """Return a writable per-user folder for config, cache and logs."""
    override = os.environ.get("MEDIAART_DATA_DIR", "").strip()
    if override:
        path = Path(override).expanduser()
    elif os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        path = Path(base) / APP_SLUG
    else:
        base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
        path = Path(base) / APP_SLUG
    path.mkdir(parents=True, exist_ok=True)
    return path


DATA_DIR = get_data_dir()
CONFIG_PATH = DATA_DIR / "config.json"
LOG_PATH = DATA_DIR / "app_log.txt"
CACHE_PATH = DATA_DIR / "tmdb_cache.json"
NEGATIVE_CACHE_PATH = DATA_DIR / "tmdb_cache_neg.json"

DEFAULT_POSTER_NAME = "poster.jpg"
DEFAULT_BACKDROP_NAME = "fanart.jpg"
ALTERNATE_BACKDROP_NAME = "background.jpg"
FOLDER_THUMB_NAME = "folder.jpg"


@dataclass(slots=True)
class AppConfig:
    """Everything the user can tweak. Unknown JSON keys are ignored."""

    tmdb_api_key: str = ""
    library_path: str = ""
    language: str = "ar"

    jpeg_quality: int = 95
    overwrite_images: bool = False
    create_background_copy: bool = True
    create_folder_thumbnail: bool = False

    convert_existing_webp: bool = True
    convert_nested_webp: bool = False
    #: جلب صور بلغة المستخدم (يرفع عدد الطلبات بنحو 50%).
    prefer_localized_artwork: bool = False
    #: أحجام الصور المطلوبة من TMDB ("original" = الدقة الكاملة، وحجمها
    #: يقارب عشرة أضعاف).
    poster_size: str = DEFAULT_POSTER_SIZE
    backdrop_size: str = DEFAULT_BACKDROP_SIZE

    dry_run: bool = False
    convert_only: bool = False
    media_filter: str = "all"  # all | movies | series

    request_timeout: int = 20
    min_request_interval: float = 0.35
    max_retries: int = 3
    use_cache: bool = True
    cache_ttl_days: int = 30
    #: عمر الكاش السلبي (عناصر غير موجودة في TMDB) بالأيام.
    negative_cache_ttl_days: int = 30

    def __post_init__(self) -> None:
        self.tmdb_api_key = (self.tmdb_api_key or "").strip()
        self.library_path = (self.library_path or "").strip()
        self.language = (self.language or "ar").strip() or "ar"
        self.jpeg_quality = _clamp_int(
            self.jpeg_quality, MIN_JPEG_QUALITY, MAX_JPEG_QUALITY, DEFAULT_JPEG_QUALITY
        )
        self.request_timeout = _clamp_int(self.request_timeout, 5, 120, 20)
        self.max_retries = _clamp_int(self.max_retries, 1, 10, 3)
        self.cache_ttl_days = _clamp_int(self.cache_ttl_days, 1, 3650, 30)
        # Unlike the other knobs (which are clamped), an out-of-range negative
        # cache TTL is a configuration error and must be reported, not hidden.
        try:
            negative_ttl = int(self.negative_cache_ttl_days)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "negative_cache_ttl_days يجب أن يكون عدداً بين 1 و 365."
            ) from exc
        if not 1 <= negative_ttl <= 365:
            raise ValueError("negative_cache_ttl_days يجب أن يكون بين 1 و 365.")
        self.negative_cache_ttl_days = negative_ttl
        if self.poster_size not in POSTER_SIZES:
            raise ValueError(
                "poster_size يجب أن يكون أحد: "
                + "، ".join(POSTER_SIZES)
                + "."
            )
        if self.backdrop_size not in BACKDROP_SIZES:
            raise ValueError(
                "backdrop_size يجب أن يكون أحد: "
                + "، ".join(BACKDROP_SIZES)
                + "."
            )
        try:
            self.min_request_interval = min(5.0, max(0.0, float(self.min_request_interval)))
        except (TypeError, ValueError):
            self.min_request_interval = 0.35
        if self.media_filter not in {"all", "movies", "series"}:
            self.media_filter = "all"

    # ------------------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppConfig":
        hints = get_type_hints(cls)
        known = {f.name: hints.get(f.name, str) for f in fields(cls)}
        cleaned: dict[str, Any] = {}
        for key, value in (data or {}).items():
            if key not in known:
                continue
            expected = known[key]
            try:
                if expected is bool:
                    cleaned[key] = _as_bool(value)
                elif expected is int:
                    cleaned[key] = int(value)
                elif expected is float:
                    cleaned[key] = float(value)
                else:
                    cleaned[key] = str(value)
            except (TypeError, ValueError):
                continue
        # A single invalid value must not discard the whole configuration.
        negative_ttl = cleaned.get("negative_cache_ttl_days")
        if negative_ttl is not None and not (1 <= int(negative_ttl) <= 365):
            cleaned.pop("negative_cache_ttl_days")
        if cleaned.get("poster_size") not in POSTER_SIZES:
            cleaned.pop("poster_size", None)
        if cleaned.get("backdrop_size") not in BACKDROP_SIZES:
            cleaned.pop("backdrop_size", None)
        return cls(**cleaned)

    def save(self, path: Path | None = None) -> None:
        save_config(self, path or CONFIG_PATH)


def _clamp_int(value: Any, low: int, high: int, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes", "on", "نعم"}


def load_config(path: Path | None = None) -> AppConfig:
    target = path or CONFIG_PATH
    try:
        raw = target.read_text(encoding="utf-8")
        data = json.loads(raw)
        if isinstance(data, dict):
            return AppConfig.from_dict(data)
    except FileNotFoundError:
        pass
    except (OSError, json.JSONDecodeError):
        # A broken config must never prevent the app from starting.
        pass
    return AppConfig()


def save_config(config: AppConfig, path: Path | None = None) -> None:
    target = path or CONFIG_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(config.to_dict(), ensure_ascii=False, indent=2)
    fd, tmp_name = tempfile.mkstemp(prefix=".config-", suffix=".tmp", dir=str(target.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)


def resolve_token(config: AppConfig, cli_token: str | None = None) -> str:
    """Resolve the TMDB token.

    Order of precedence:

    1. ``cli_token`` — a token passed explicitly on the command line
       (``--token``) always wins, even over the environment.
    2. Environment variables (``TMDB_API_KEY``, ``TMDB_READ_ACCESS_TOKEN``,
       ``TMDB_TOKEN``).
    3. The key stored in ``config.json`` (``config.tmdb_api_key``).
    """
    env_name, env_value = _first_env_token()
    explicit = (cli_token or "").strip()
    if explicit:
        if env_value:
            logger.warning(
                "تحذير: --token الممرّر يتعارض مع %s في البيئة؛ أستخدم --token.",
                env_name,
            )
        return explicit
    if env_value:
        return env_value
    return (config.tmdb_api_key or "").strip()


def _first_env_token() -> tuple[str, str]:
    """Return the first environment token as ``(name, value)``."""
    for env_name in ("TMDB_API_KEY", "TMDB_READ_ACCESS_TOKEN", "TMDB_TOKEN"):
        value = os.environ.get(env_name, "").strip()
        if value:
            return env_name, value
    return "", ""


def env_token_present() -> bool:
    return any(
        os.environ.get(name, "").strip()
        for name in ("TMDB_API_KEY", "TMDB_READ_ACCESS_TOKEN", "TMDB_TOKEN")
    )
