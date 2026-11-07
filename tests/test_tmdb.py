from __future__ import annotations

from app.services.tmdb import (
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
