"""TMDB v3 API client with throttling, retries, matching and image selection.

Supports both credential styles:

* v3 API key (32 chars)  -> sent as ``api_key`` query parameter.
* v4 Read Access Token   -> sent as ``Authorization: Bearer ...``.

The token is never written to the log; :class:`RedactionFilter` additionally
scrubs ``api_key=...`` and ``Bearer ...`` patterns from every log record.
"""

from __future__ import annotations

import random
import threading
import time
from difflib import SequenceMatcher
from pathlib import Path

import requests

from ..config import (
    CACHE_PATH,
    DEFAULT_BACKDROP_SIZE,
    DEFAULT_POSTER_SIZE,
    NEGATIVE_CACHE_PATH,
)
from ..errors import TMDBError, TMDBAuthError, TMDBRateLimitError
from ..logging_setup import get_logger
from ..models import MediaItem, TMDBMatch
from .cache import JsonCache
from .title_cleaner import normalize_for_match

BASE_URL = "https://api.themoviedb.org/3"
IMAGE_BASE = "https://image.tmdb.org/t/p"
USER_AGENT = "MediaArtAutoSync/1.0.2 (+https://www.themoviedb.org/)"

# A match below this score is considered "not found" rather than "wrong movie".
MIN_ACCEPT_SCORE = 55.0
# Second language tried when the user's language returns no acceptable match.
FALLBACK_LANGUAGE = "en"
#: Default lifetime of a "not found" entry (mirrors ``AppConfig`` default).
DEFAULT_NEGATIVE_CACHE_TTL_DAYS = 30

logger = get_logger("tmdb")


def image_url(path: str | None, size: str = "original") -> str | None:
    if not path:
        return None
    if path.startswith("http://") or path.startswith("https://"):
        return path
    return f"{IMAGE_BASE}/{size}/{path.lstrip('/')}"


def is_bearer_token(token: str) -> bool:
    token = (token or "").strip()
    if not token:
        return False
    if token.count(".") == 2 and len(token) > 60:
        return True
    return len(token) > 50


class TMDBClient:
    def __init__(
        self,
        token: str,
        language: str = "ar",
        *,
        timeout: int = 20,
        min_interval: float = 0.35,
        max_retries: int = 3,
        use_cache: bool = True,
        cache_ttl_days: int = 30,
        cache_path: Path | None = None,
        prefer_localized_artwork: bool = True,
        negative_cache_ttl_days: int | None = None,
        negative_cache_path: Path | None = None,
        refresh_negatives: bool = False,
        poster_size: str | None = None,
        backdrop_size: str | None = None,
    ) -> None:
        token = (token or "").strip()
        if not token:
            raise TMDBAuthError("مفتاح TMDB مطلوب لتنفيذ البحث.")
        self.language = language or "ar"
        self.timeout = timeout
        self.min_interval = max(0.0, min_interval)
        self.max_retries = max(1, max_retries)
        self.prefer_localized_artwork = prefer_localized_artwork
        # Image sizes are explicit parameters: the client never reads
        # ``config.json`` itself (that would make a network object depend on the
        # user's disk and would let a stale/unwritable config change requests
        # behind the caller's back).
        self.poster_size = poster_size or DEFAULT_POSTER_SIZE
        self.backdrop_size = backdrop_size or DEFAULT_BACKDROP_SIZE

        self._bearer = is_bearer_token(token)
        self._token = token
        self._session = requests.Session()
        headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
        if self._bearer:
            headers["Authorization"] = f"Bearer {token}"
        self._session.headers.update(headers)

        self._throttle_lock = threading.Lock()
        self._last_request = 0.0
        self.cache = JsonCache(
            cache_path if cache_path is not None else CACHE_PATH,
            ttl_days=cache_ttl_days,
            enabled=use_cache,
        )
        # Negative cache: titles already known to be absent from TMDB, so a
        # re-run does not pay for the same fruitless searches. It lives in its
        # own file with its own TTL (JsonCache has one TTL per instance).
        if negative_cache_ttl_days is None:
            negative_cache_ttl_days = DEFAULT_NEGATIVE_CACHE_TTL_DAYS
        self.refresh_negatives = refresh_negatives
        self.neg_cache = JsonCache(
            negative_cache_path
            if negative_cache_path is not None
            else NEGATIVE_CACHE_PATH,
            ttl_days=negative_cache_ttl_days,
            enabled=use_cache,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def test_connection(self) -> dict:
        return self._get_json("/configuration", {})

    def find_match(self, item: MediaItem, force_refresh: bool = False) -> TMDBMatch | None:
        title = (item.title or "").strip()
        if not title:
            return None

        scope = (
            item.kind.value,
            self.language,
            "1" if self.prefer_localized_artwork else "0",
            normalize_for_match(title),
            str(item.year or ""),
        )
        cache_key = "|".join(("match-v2", *scope))
        negative_key = "|".join(("neg-v1", *scope))

        cached = self.cache.get(cache_key)
        if cached:
            if cached.get("media_type") != item.kind.tmdb_type:
                # مدخل كاش قديم لنوع مختلف عن نوع العنصر المطلوب: رفضه وحذفه فردياً
                self.cache.delete(cache_key)
                logger.debug(
                    "تم رفض مدخل كاش قديم لنوع غير مطابق (%s ≠ %s): %s",
                    cached.get("media_type"),
                    item.kind.tmdb_type,
                    title,
                )
                cached = None
            if cached:
                logger.debug("نتيجة من الكاش: %s", title)
                return TMDBMatch.from_cache(cached)

        # Negative cache: a title known to be absent is not searched again
        # until the entry expires (or the user asks for a refresh).
        if not (force_refresh or self.refresh_negatives):
            negative = self.neg_cache.get(negative_key)
            if negative and negative.get("reason") == "not_found":
                logger.debug("لا مطابقة (كاش سلبي): %s", title)
                return None

        primary = item.kind.tmdb_type
        best = self._best_candidate(primary, title, item.year)

        if best is None or best[0] < MIN_ACCEPT_SCORE:
            self.neg_cache.set(
                negative_key,
                {"ts": time.time(), "reason": "not_found"},
            )
            return None

        score, match, language_used = best
        self._enrich_images(match)
        if match.media_type != item.kind.tmdb_type:
            # رفض تخزين نتيجة من نوع مخالف لنوع العنصر المطلوب
            logger.warning(
                "تم رفض نتيجة '%s' لأن media_type (%s) لا يطابق نوع العنصر (%s).",
                match.title,
                match.media_type,
                item.kind.tmdb_type,
            )
            return None
        self.cache.set(cache_key, match.to_cache())
        # A success neutralises any earlier negative entry for the same title
        # (the item may have been added to TMDB in the meantime).
        self.neg_cache.set(
            negative_key,
            {"ts": time.time(), "reason": "resolved"},
        )
        logger.debug(
            "تم اختيار '%s' (%s) بدرجة %.1f [لغة البحث: %s]",
            match.title,
            match.year or "?",
            score,
            language_used,
        )
        return match

    def close(self) -> None:
        try:
            self.cache.flush()
            self.neg_cache.flush()
        finally:
            self._session.close()

    def __enter__(self) -> "TMDBClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # ------------------------------------------------------------------
    # HTTP
    # ------------------------------------------------------------------
    def _get_json(self, path: str, params: dict) -> dict:
        url = f"{BASE_URL}{path}"
        merged = dict(params or {})
        if not self._bearer:
            merged["api_key"] = self._token

        last_error = "تعذر الاتصال بـ TMDB."
        for attempt in range(1, self.max_retries + 1):
            self._throttle()
            try:
                response = self._session.get(
                    url,
                    params=merged,
                    timeout=(5, self.timeout),
                )
            except requests.Timeout:
                last_error = "انتهت مهلة الاتصال بـ TMDB."
                self._backoff(attempt)
                continue
            except requests.RequestException as exc:
                last_error = f"خطأ شبكة أثناء الاتصال بـ TMDB ({exc.__class__.__name__})."
                self._backoff(attempt)
                continue

            status = response.status_code
            if status == 401:
                raise TMDBAuthError("مفتاح TMDB غير صالح أو منتهي (HTTP 401).")
            if status == 404:
                return {}
            if status == 429:
                if attempt >= self.max_retries:
                    raise TMDBRateLimitError("TMDB يرفض الطلبات مؤقتاً (HTTP 429).")
                wait = _retry_after(response, default=2.0 * attempt)
                logger.warning("تجاوز حد الطلبات، انتظار %.1f ثانية...", wait)
                time.sleep(wait)
                continue
            if 500 <= status < 600:
                last_error = f"خادم TMDB غير متاح مؤقتاً (HTTP {status})."
                self._backoff(attempt)
                continue
            if status >= 400:
                detail = _extract_error(response)
                raise TMDBError(f"رفض TMDB الطلب (HTTP {status}): {detail}")

            try:
                data = response.json()
            except ValueError as exc:
                raise TMDBError("رد غير صالح من TMDB (ليس JSON).") from exc
            if not isinstance(data, dict):
                raise TMDBError("رد TMDB غير متوقع.")
            return data

        raise TMDBError(last_error)

    def _throttle(self) -> None:
        with self._throttle_lock:
            now = time.monotonic()
            wait = self.min_interval - (now - self._last_request)
            if wait > 0:
                time.sleep(wait)
            self._last_request = time.monotonic()

    @staticmethod
    def _backoff(attempt: int) -> None:
        delay = min(8.0, (1.5 ** attempt) + random.uniform(0.0, 0.4))
        time.sleep(delay)

    # ------------------------------------------------------------------
    # Search & scoring
    # ------------------------------------------------------------------
    def _search_languages(self) -> tuple[str, ...]:
        """Languages to try, in order: the user's language, then English.

        TMDB's ``/search`` endpoint matches the query against the *displayed*
        titles, so an English folder name returns nothing when ``language`` is
        a language that has no translation for that title (recent Asian films
        with ``language=ar``, for example). Retrying in English afterwards
        recovers those catalogue entries, while titles that only exist in the
        user's language still match on the first attempt.
        """
        if self.language == FALLBACK_LANGUAGE:
            return (self.language,)
        return (self.language, FALLBACK_LANGUAGE)

    def _best_candidate(
        self, media_type: str, title: str, year: int | None
    ) -> tuple[float, TMDBMatch, str] | None:
        """Return ``(score, match, language)`` for the best candidate found.

        The user's language is searched first; English is only tried when that
        search produced nothing acceptable. The returned language is the one
        that actually produced the candidate.
        """
        weakest: tuple[float, TMDBMatch, str] | None = None
        for language in self._search_languages():
            scored = self._search_scored(media_type, title, year, language)
            if not scored and year:
                scored = self._search_scored(media_type, title, None, language)
            if not scored:
                continue
            score, match = scored[0]
            if score >= MIN_ACCEPT_SCORE:
                if language != self.language:
                    logger.debug(
                        "تعذر البحث بلغة '%s' لـ '%s'؛ نجح البديل بـ '%s'.",
                        self.language,
                        title,
                        language,
                    )
                return score, match, language
            if weakest is None or score > weakest[0]:
                weakest = (score, match, language)
        return weakest

    def _search_scored(
        self,
        media_type: str,
        title: str,
        year: int | None,
        language: str | None = None,
    ) -> list[tuple[float, TMDBMatch]]:
        results = self._search(media_type, title, year, language)
        query_norm = normalize_for_match(title)
        scored: list[tuple[float, TMDBMatch]] = []
        for result in results:
            score = score_candidate(result, media_type, query_norm, year)
            if score > 0:
                scored.append(
                    (
                        score,
                        to_match(
                            result,
                            media_type,
                            poster_size=self.poster_size,
                            backdrop_size=self.backdrop_size,
                        ),
                    )
                )
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return scored

    def _search(
        self,
        media_type: str,
        title: str,
        year: int | None,
        language: str | None = None,
    ) -> list[dict]:
        params: dict[str, object] = {
            "query": title,
            "language": language or self.language,
            "include_adult": "false",
            "page": 1,
        }
        if year:
            params["year" if media_type == "movie" else "first_air_date_year"] = year
        data = self._get_json(f"/search/{media_type}", params)
        results = data.get("results") or []
        return [item for item in results if isinstance(item, dict)]

    def _enrich_images(self, match: TMDBMatch) -> None:
        needs_images = not (match.poster_path and match.backdrop_path)
        wants_localized = self.prefer_localized_artwork and self.language != "en"
        if not needs_images and not wants_localized:
            return
        try:
            data = self._get_json(
                f"/{match.media_type}/{match.tmdb_id}/images",
                {"include_image_language": f"{self.language},en,null"},
            )
        except TMDBError as exc:
            logger.debug("تعذر جلب صور إضافية لـ '%s': %s", match.title, exc)
            return

        poster = _pick_image(data.get("posters"), self.language, textless_first=False)
        backdrop = _pick_image(data.get("backdrops"), self.language, textless_first=True)
        if poster:
            match.poster_path = image_url(poster, self.poster_size)
        if backdrop:
            match.backdrop_path = image_url(backdrop, self.backdrop_size)


# ----------------------------------------------------------------------
# Helpers exported for unit tests
# ----------------------------------------------------------------------
def score_candidate(
    result: dict,
    media_type: str,
    query_norm: str,
    year: int | None,
) -> float:
    if not query_norm or not isinstance(result, dict):
        return 0.0

    if media_type == "movie":
        names = (result.get("title"), result.get("original_title"))
    else:
        names = (result.get("name"), result.get("original_name"))

    title_score = 0.0
    for raw_name in names:
        name_norm = normalize_for_match(raw_name or "")
        if not name_norm:
            continue
        if name_norm == query_norm:
            candidate = 100.0
        elif name_norm.startswith(query_norm) or query_norm.startswith(name_norm):
            candidate = 58.0
        elif query_norm in name_norm or name_norm in query_norm:
            candidate = 42.0
        else:
            ratio = SequenceMatcher(None, query_norm, name_norm).ratio()
            candidate = ratio * 58.0 if ratio >= 0.72 else 0.0
        title_score = max(title_score, candidate)

    if title_score <= 0:
        return 0.0

    result_year = extract_result_year(result, media_type)
    if year and result_year:
        delta = abs(year - result_year)
        if delta == 0:
            title_score += 35.0
        elif delta == 1:
            title_score += 18.0
        elif delta <= 2:
            title_score += 4.0
        else:
            title_score -= 25.0

    popularity = _as_float(result.get("popularity"))
    vote = _as_float(result.get("vote_average"))
    title_score += min(popularity / 300.0, 6.0)
    title_score += min(vote / 4.0, 2.5)
    return title_score


def extract_result_year(result: dict, media_type: str) -> int | None:
    raw = result.get("release_date") if media_type == "movie" else result.get("first_air_date")
    if not raw and media_type == "tv":
        raw = result.get("release_date")
    if not raw or not isinstance(raw, str) or len(raw) < 4:
        return None
    try:
        return int(raw[:4])
    except ValueError:
        return None


def to_match(
    result: dict,
    media_type: str,
    poster_size: str = "original",
    backdrop_size: str = "original",
) -> TMDBMatch:
    title = result.get("title") or result.get("name") or ""
    original = result.get("original_title") or result.get("original_name") or title
    return TMDBMatch(
        tmdb_id=int(result.get("id") or 0),
        media_type=media_type,
        title=str(title),
        original_title=str(original),
        year=extract_result_year(result, media_type),
        poster_path=image_url(result.get("poster_path"), poster_size),
        backdrop_path=image_url(result.get("backdrop_path"), backdrop_size),
        popularity=_as_float(result.get("popularity")),
        vote_average=_as_float(result.get("vote_average")),
        overview=str(result.get("overview") or ""),
    )


def _pick_image(images: object, language: str, *, textless_first: bool) -> str | None:
    if not isinstance(images, list):
        return None
    candidates = [image for image in images if isinstance(image, dict) and image.get("file_path")]
    if not candidates:
        return None

    def rank(image: dict) -> tuple[int, float, int]:
        lang = image.get("iso_639_1")
        if textless_first:
            language_rank = 0 if lang is None else 1 if lang == language else 2 if lang == "en" else 3
        else:
            language_rank = 0 if lang == language else 1 if lang is None else 2 if lang == "en" else 3
        vote = _as_float(image.get("vote_average"))
        width = int(image.get("width") or 0)
        return (language_rank, -vote, -width)

    candidates.sort(key=rank)
    return str(candidates[0]["file_path"])


def _retry_after(response: requests.Response, default: float) -> float:
    raw = response.headers.get("Retry-After", "")
    try:
        return min(30.0, max(1.0, float(raw)))
    except (TypeError, ValueError):
        return default


def _extract_error(response: requests.Response) -> str:
    try:
        data = response.json()
        message = data.get("status_message") or data.get("message")
        if message:
            return str(message)[:200]
    except ValueError:
        pass
    return response.reason or "خطأ غير معروف"


def _as_float(value: object) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
