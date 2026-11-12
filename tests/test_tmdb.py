from __future__ import annotations

from pathlib import Path

from app.models import MediaItem, MediaKind
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
