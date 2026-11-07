from __future__ import annotations

import pytest

from app.services.title_cleaner import clean_title, normalize_for_match


@pytest.mark.parametrize(
    ("raw", "title", "year"),
    [
        ("Breaking.Bad.S01.1080p.BluRay.x264-Arabic", "Breaking Bad", None),
        ("[YTS] Interstellar (2014) [1080p] [BluRay] [5.1]", "Interstellar", 2014),
        ("The.Matrix.1999.2160p.UHD.BluRay.x265.10bit.HDR.DTS-HD.MA.5.1-GROUP", "The Matrix", 1999),
        ("Spider-Man.No.Way.Home.2021.1080p.WEB-DL.DDP5.1.H264-CMRG", "Spider-Man No Way Home", 2021),
        ("Oppenheimer 2023 2160p WEB-DL DDP5.1 Atmos HDR x265-SMURF", "Oppenheimer", 2023),
        ("Friends.S01.Complete.720p.BluRay", "Friends", None),
        ("Dune Part Two (2024) {imax}", "Dune Part Two", 2024),
        ("Blade Runner 2049 (2017)", "Blade Runner 2049", 2017),
        ("1917.2019.1080p.BluRay.x264", "1917", 2019),
        ("The Office (US) S01-S09 1080p", "The Office", None),
        ("www.example.com - The Movie 2020 1080p", "The Movie", 2020),
        ("Mission-Impossible.1996.1080p", "Mission-Impossible", 1996),
        ("Charlotte's Web (2006)", "Charlotte's Web", 2006),
        ("A Complete Unknown (2024)", "A Complete Unknown", 2024),
        ("Movie.Name.2020.Extended.1080p.BluRay-GROUP", "Movie Name", 2020),
        ("Show.S01E01.720p.WEB-DL", "Show", None),
    ],
)
def test_clean_title(raw: str, title: str, year: int | None) -> None:
    result = clean_title(raw)
    assert result.title == title
    assert result.year == year


def test_year_only_title_is_preserved() -> None:
    result = clean_title("2012")
    assert result.title == "2012"
    assert result.year is None


def test_video_extension_is_removed() -> None:
    assert clean_title("Inception.2010.1080p.BluRay.mkv").title == "Inception"


def test_arabic_tags_removed() -> None:
    result = clean_title("فيلم The Godfather 1972 مترجم 1080p")
    assert result.title == "The Godfather"
    assert result.year == 1972


def test_arabic_series_and_season_tags_removed() -> None:
    result = clean_title("مسلسل Breaking Bad الموسم الأول الحلقة 1")
    assert result.title == "Breaking Bad"


def test_empty_input() -> None:
    assert not clean_title("")


def test_normalize_for_match_handles_arabic() -> None:
    assert normalize_for_match("أهلاً بالعالم") == normalize_for_match("اهلا بالعالم")
    assert normalize_for_match("Spider-Man: No Way Home") == "spider man no way home"
    assert normalize_for_match("Fast & Furious") == "fast and furious"
