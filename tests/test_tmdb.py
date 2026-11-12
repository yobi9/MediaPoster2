from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from app.models import MediaItem, MediaKind
from app.services.title_cleaner import normalize_for_match
from app.services.tmdb import (
    TMDBClient,
    image_url,
    is_bearer_token,
    score_candidate,
    to_match,
)


def movie(**overrides):
    base = {
        "id": 1,
        "title": "The Matrix",
        "original_title": "The Matrix",
        "release_date": "1999-03-31",
        "poster_path": "/poster.jpg",
        "backdrop_path": "/backdrop.jpg",
        "popularity": 100.0,
        "vote_average": 8.2,
        "overview": "",
    }
    base.update(overrides)
    return base


def tv(**overrides):
    base = {
        "id": 2,
        "name": "Breaking Bad",
        "original_name": "Breaking Bad",
        "first_air_date": "2008-01-20",
        "poster_path": "/poster.jpg",
        "backdrop_path": None,
        "popularity": 200.0,
        "vote_average": 9.0,
    }
    base.update(overrides)
    return base


def test_exact_title_beats_fuzzy() -> None:
    exact = score_candidate(movie(), "movie", "the matrix", 1999)
    fuzzy = score_candidate(
        movie(title="The Matrix Reloaded", original_title="The Matrix Reloaded"),
        "movie",
        "the matrix",
        1999,
    )
    unrelated = score_candidate(
        movie(title="Totally Different", original_title="Totally Different"),
        "movie",
        "the matrix",
        1999,
    )
    assert exact > fuzzy > 0
    assert unrelated == 0


def test_year_breaks_ties() -> None:
    right = score_candidate(movie(title="Dune", release_date="2021-01-01"), "movie", "dune", 2021)
    wrong = score_candidate(movie(title="Dune", release_date="1984-01-01"), "movie", "dune", 2021)
    assert right > wrong


def test_arabic_title_is_normalized() -> None:
    score = score_candidate(
        movie(
            title="أهلاً بالعالم",
            original_title="أهلاً بالعالم",
            release_date="2020-01-01",
        ),
        "movie",
        "اهلا بالعالم",
        2020,
    )
    assert score >= 100


def test_to_match_reads_tv_fields() -> None:
    match = to_match(tv(), "tv")
    assert match.is_series
    assert match.title == "Breaking Bad"
    assert match.year == 2008
    assert match.backdrop_path is None


def test_image_url() -> None:
    assert image_url("/abc.jpg") == "https://image.tmdb.org/t/p/original/abc.jpg"
    assert image_url(None) is None
    assert image_url("https://example.com/x.jpg") == "https://example.com/x.jpg"


# ----------------------------------------------------------------------
# أحجام الصور (A1)
# ----------------------------------------------------------------------
def test_image_url_uses_the_requested_size() -> None:
    """A1-1: الحجم المطلوب يظهر في الرابط."""
    url = image_url("abc.jpg", "w500")

    assert url is not None
    assert "/t/p/w500/abc.jpg" in url


def test_image_url_supports_original() -> None:
    """A1-2: original ما زال مدعوماً."""
    url = image_url("abc.jpg", "original")

    assert url is not None
    assert "/t/p/original/abc.jpg" in url


def test_default_image_sizes(tmp_path: Path) -> None:
    """A1-3: الافتراضيات w500 للملصق وw780 للخلفية."""
    from app.config import AppConfig

    config = AppConfig()

    assert config.poster_size == "w500"
    assert config.backdrop_size == "w780"


def test_invalid_poster_size_is_rejected() -> None:
    """A1-4: حجم غير مسموح ⇒ ValueError برسالة عربية."""
    from app.config import AppConfig

    with pytest.raises(ValueError) as excinfo:
        AppConfig(poster_size="huge")

    assert "poster_size" in str(excinfo.value)
    assert "w500" in str(excinfo.value)


def test_bearer_detection() -> None:
    assert not is_bearer_token("0123456789abcdef0123456789abcdef")
    assert is_bearer_token("a" * 80)
    assert is_bearer_token(("a" * 30) + "." + ("b" * 30) + "." + ("c" * 30))
    assert not is_bearer_token("aaa.bbb.ccc")


# ----------------------------------------------------------------------
# Search language fallback
# ----------------------------------------------------------------------
class _FakeTMDB(TMDBClient):
    """Serves canned search payloads per requested language (no network)."""

    def __init__(self, payloads: dict[str, list[dict]], language: str = "ar") -> None:
        super().__init__("0" * 32, language=language, use_cache=False)
        self.payloads = payloads
        self.search_languages: list[str] = []

    def _get_json(self, path: str, params: dict) -> dict:
        if path.endswith("/images"):
            return {"posters": [], "backdrops": []}
        language = str(params.get("language") or "")
        self.search_languages.append(language)
        return {"results": self.payloads.get(language, [])}


def _item(title: str) -> MediaItem:
    return MediaItem(
        path=Path("C:/library") / title,
        kind=MediaKind.MOVIE,
        title=title,
    )


def test_falls_back_to_english_when_primary_language_finds_nothing() -> None:
    """A title with no translation in the user's language is found in English."""
    client = _FakeTMDB(
        {
            "ar": [],
            "en": [
                movie(
                    title="Humint",
                    original_title="Humint",
                    release_date="2026-01-01",
                )
            ],
        }
    )

    match = client.find_match(_item("Humint"))

    assert match is not None
    assert match.title == "Humint"
    assert client.search_languages == ["ar", "en"]


def test_no_english_fallback_when_primary_language_succeeds() -> None:
    """When the user's language already matches, English is never requested."""
    client = _FakeTMDB(
        {
            "ar": [
                movie(
                    title="Panda Plan",
                    original_title="Panda Plan",
                    release_date="2024-01-01",
                )
            ],
            "en": [
                movie(
                    title="Totally Different",
                    original_title="Totally Different",
                    release_date="2024-01-01",
                )
            ],
        }
    )

    match = client.find_match(_item("Panda Plan"))

    assert match is not None
    assert match.title == "Panda Plan"
    assert client.search_languages == ["ar"]


def test_english_fallback_loses_to_a_better_primary_language_candidate() -> None:
    """A weak primary-language result does not block the English fallback."""
    client = _FakeTMDB(
        {
            # "Before" is only a substring of the query -> base score 42,
            # below MIN_ACCEPT_SCORE, so it must not stop the English retry.
            "ar": [
                movie(
                    title="Before",
                    original_title="Before",
                    release_date="2019-01-01",
                )
            ],
            "en": [
                movie(
                    title="Me Before Me",
                    original_title="Me Before Me",
                    release_date="2026-01-01",
                )
            ],
        }
    )

    match = client.find_match(_item("Me Before Me"))

    assert match is not None
    assert match.title == "Me Before Me"
    assert client.search_languages == ["ar", "en"]


# ----------------------------------------------------------------------
# Negative cache (A2)
# ----------------------------------------------------------------------
class _CountingTMDB(TMDBClient):
    """TMDB client with a real cache and a counter of network round-trips."""

    def __init__(self, tmp_path: Path, results: dict[str, list[dict]]) -> None:
        super().__init__(
            "0" * 32,
            language="ar",
            use_cache=True,
            cache_path=tmp_path / "cache.json",
            negative_cache_path=tmp_path / "cache_neg.json",
            negative_cache_ttl_days=30,
        )
        self.results = results
        self.by_query: dict[str, list[dict]] = {}
        self.calls = 0

    def _get_json(self, path: str, params: dict) -> dict:
        self.calls += 1
        if path.endswith("/images"):
            return {"posters": [], "backdrops": []}
        language = str(params.get("language") or "")
        if self.by_query:
            return {"results": self.by_query.get(str(params.get("query") or ""), [])}
        return {"results": self.results.get(language, [])}


def _negative_key(title: str) -> str:
    return "|".join(
        ("neg-v1", "movie", "ar", "1", normalize_for_match(title), "")
    )


def test_missing_title_is_searched_only_once(tmp_path: Path) -> None:
    """N1: العنصر غير الموجود يُبحث عنه مرة واحدة فقط (كاش سلبي)."""
    client = _CountingTMDB(tmp_path, {"ar": [], "en": []})

    assert client.find_match(_item("Unknown Film")) is None
    first_calls = client.calls
    assert first_calls > 0

    assert client.find_match(_item("Unknown Film")) is None
    assert client.calls == first_calls, "الكاش السلبي يجب أن يمنع طلب الشبكة الثاني"


def test_force_refresh_bypasses_negative_cache(tmp_path: Path) -> None:
    """N2: force_refresh يتجاوز الكاش السلبي ويطلق طلب شبكة جديداً."""
    client = _CountingTMDB(tmp_path, {"ar": [], "en": []})
    client.find_match(_item("Unknown Film"))
    before = client.calls

    assert client.find_match(_item("Unknown Film"), force_refresh=True) is None
    assert client.calls > before


def test_late_arrival_needs_a_refresh(tmp_path: Path) -> None:
    """N3: فشل → ظهور لاحق في TMDB → نجاح (يتطلّب تجاوز الكاش السلبي)."""
    client = _CountingTMDB(tmp_path, {"ar": [], "en": []})

    # 1) لا يوجد في TMDB ⇒ نتيجة None + كاش سلبي.
    assert client.find_match(_item("The Matrix")) is None
    calls_after_failure = client.calls

    # 2) العنصر يظهر في TMDB الآن.
    client.results = {
        "ar": [movie(title="The Matrix", original_title="The Matrix")],
        "en": [],
    }

    # 3) بدون تجاوز ⇒ يبقى الكاش السلبي قائماً.
    assert client.find_match(_item("The Matrix")) is None
    assert client.calls == calls_after_failure

    # 4) مع تجاوز ⇒ يُعثر عليه ويُكتب الكاش الإيجابي.
    match = client.find_match(_item("The Matrix"), force_refresh=True)
    assert match is not None
    assert match.title == "The Matrix"

    # 5) 호출 تالٍ بلا تجاوز ⇒ من الكاش الإيجابي.
    again = client.find_match(_item("The Matrix"))
    assert again is not None
    assert again.title == "The Matrix"


def test_expired_negative_entry_triggers_a_new_search(tmp_path: Path) -> None:
    """N4: مدخل كاش سلبي منتهٍ الصلاحية ⇒ بحث شبكة جديد."""
    negative_file = tmp_path / "cache_neg.json"
    old_ts = time.time() - 31 * 86_400
    negative_file.write_text(
        json.dumps(
            {
                _negative_key("The Matrix"): {
                    "ts": old_ts,
                    "value": {"ts": old_ts, "reason": "not_found"},
                }
            }
        ),
        encoding="utf-8",
    )
    client = _CountingTMDB(tmp_path, {"ar": [], "en": []})

    assert client.find_match(_item("The Matrix")) is None
    assert client.calls > 0, "المدخل المنتهي يجب ألا يمنع البحث"


def test_negative_cache_is_disabled_with_no_cache(tmp_path: Path) -> None:
    """مع use_cache=False لا يُخزَّن كاش سلبي ولا يُقرأ."""
    client = _CountingTMDB(tmp_path, {"ar": [], "en": []})
    client.neg_cache.enabled = False

    assert client.find_match(_item("Unknown Film")) is None
    before = client.calls
    assert client.find_match(_item("Unknown Film")) is None
    assert client.calls > before


def test_negative_cache_is_bound_to_the_title(tmp_path: Path) -> None:
    """N7: الكاش السلبي مربوط بعنوان المجلد لا بالعنصر.

    تغيير اسم المجلد ينشئ مفتاحاً جديداً ⇒ العنصر الجديد غير محجوب،
    بينما يبقى العنصر القديم محجوباً بكاشه الخاص.
    """
    client = _CountingTMDB(tmp_path, {"ar": [], "en": []})

    # 1) "Alpha" غير موجود ⇒ مدخل كاش سلبي تحت "Alpha".
    assert client.find_match(_item("Alpha")) is None

    # 2) "Beta" له مفتاح خاص به ⇒ لا يُحجب بالعنصر السابق.
    client.by_query = {
        "Alpha": [movie(title="Alpha", original_title="Alpha")],
        "Beta": [movie(title="Beta", original_title="Beta")],
    }
    match_beta = client.find_match(_item("Beta"))
    assert match_beta is not None
    assert match_beta.title == "Beta"

    # 3) "Alpha" ما زال محجوباً بكاشه (تسمية "Beta" لم تمسّه).
    assert client.find_match(_item("Alpha")) is None

    # 4) تجاوز الكاش ⇒ "Alpha" يُعثر عليه (ويُحايد مفتاحه).
    match_alpha = client.find_match(_item("Alpha"), force_refresh=True)
    assert match_alpha is not None
    assert match_alpha.title == "Alpha"


def test_match_uses_the_configured_sizes(tmp_path: Path) -> None:
    """A1-7: find_match يبني الروابط بالحجم المطلوب."""
    client = _CountingTMDB(tmp_path, {"ar": [], "en": []})
    client.poster_size = "w342"
    client.backdrop_size = "w1280"
    client.by_query = {
        "Matrix": [movie(title="Matrix", original_title="Matrix")],
    }

    match = client.find_match(_item("Matrix"))

    assert match is not None
    assert match.poster_path is not None
    assert "/w342/" in match.poster_path
    assert match.backdrop_path is not None
    assert "/w1280/" in match.backdrop_path


# ----------------------------------------------------------------------
# تخطّي الـenrich (A3)
# ----------------------------------------------------------------------
def _client_with_artwork(
    tmp_path: Path,
    *,
    language: str = "ar",
    prefer_localized: bool = False,
    with_poster: bool = True,
) -> _CountingTMDB:
    client = _CountingTMDB(tmp_path, {"ar": [], "en": []})
    client.language = language
    client.prefer_localized_artwork = prefer_localized
    payload = movie(title="Matrix", original_title="Matrix")
    if not with_poster:
        payload["poster_path"] = None
    client.by_query = {"Matrix": [payload]}
    return client


def test_enrichment_is_skipped_when_images_are_present(tmp_path: Path) -> None:
    """A3-1: صور موجودة + الافتراضي ⇒ طلب واحد فقط (بلا enrich)."""
    client = _client_with_artwork(tmp_path)

    match = client.find_match(_item("Matrix"))

    assert match is not None
    assert client.calls == 1


def test_enrichment_runs_when_poster_is_missing(tmp_path: Path) -> None:
    """A3-2: غياب الملصق ⇒ enrich (طلبان) حتى مع الافتراضي."""
    client = _client_with_artwork(tmp_path, with_poster=False)

    match = client.find_match(_item("Matrix"))

    assert match is not None
    assert client.calls == 2


def test_localized_artwork_forces_enrichment(tmp_path: Path) -> None:
    """A3-3: prefer_localized_artwork=True مع لغة غير إنجليزية ⇒ enrich."""
    client = _client_with_artwork(tmp_path, prefer_localized=True)

    match = client.find_match(_item("Matrix"))

    assert match is not None
    assert client.calls == 2


def test_localized_artwork_is_noop_for_english(tmp_path: Path) -> None:
    """A3-4: مع اللغة الإنجليزية لا يوجد enrich حتى مع تفعيل الخيار."""
    client = _client_with_artwork(tmp_path, language="en", prefer_localized=True)

    match = client.find_match(_item("Matrix"))

    assert match is not None
    assert client.calls == 1


def test_enrichment_saves_requests(tmp_path: Path) -> None:
    """A3-6: مقارنة مباشرة — بلا enrich طلب واحد، ومعه طلبان."""
    plain = _client_with_artwork(tmp_path)
    plain.find_match(_item("Matrix"))

    localized_dir = tmp_path / "second"
    localized_dir.mkdir()
    localized = _client_with_artwork(localized_dir, prefer_localized=True)
    localized.find_match(_item("Matrix"))

    assert plain.calls == 1
    assert localized.calls == 2
    assert localized.calls > plain.calls
