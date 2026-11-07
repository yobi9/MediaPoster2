"""Smart file/folder name cleaner (regex based, no network).

The cleaner is intentionally data driven: add a new release tag to
``_TAG_TERMS`` (and a unit test) instead of writing another one-off regex.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date

MAX_YEAR = date.today().year + 2
MIN_YEAR = 1888


@dataclass(frozen=True, slots=True)
class CleanedTitle:
    title: str
    year: int | None = None

    def __bool__(self) -> bool:
        return bool(self.title)


# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------
# Removed as standalone words. Longest entries win because the alternation is
# sorted by length, so "dts hd ma" is consumed before "dts".
_TAG_TERMS: tuple[str, ...] = (
    # resolution / dynamic range
    "2160p", "1080p", "720p", "480p", "4k", "8k", "uhd", "fhd", "fullhd",
    "full hd", "hd", "sd", "hdr10+", "hdr10", "hdr", "dolby vision", "dovi", "sdr",
    # sources
    "bluray", "blu-ray", "bdrip", "brrip", "bdremux", "remux", "web-dl", "web dl",
    "webdl", "webrip", "web rip", "hdtv", "hdrip", "dvdrip", "dvdscr", "dvd",
    "hdcam", "hdts", "camrip", "telesync", "telecine", "hdlight", "amzn", "dsnp",
    "hmax", "atvp", "nf",
    # video codecs
    "x264", "x265", "h264", "h265", "hevc", "avc", "av1", "vp9", "xvid", "divx",
    "10bit", "10 bit", "8bit", "8 bit", "12bit", "hi10p",
    # audio codecs / channels
    "dts-hd ma", "dts hd ma", "dts-hd", "dts hd", "truehd", "atmos", "eac3", "ac3",
    "ddp", "dd+", "aac", "flac", "opus", "mp3", "5 1", "7 1", "2 0",
    "dual audio", "multi audio",
    # language / subtitle markers
    "arabic", "english", "french", "spanish", "german", "italian", "turkish",
    "hindi", "korean", "japanese", "russian", "multi", "subs", "subtitles",
    "subbed", "dubbed", "مترجم", "مترجمة", "مدبلج", "مدبلجة", "عربي", "عربية",
    # release jargon
    "proper", "repack", "remastered", "unrated", "uncut", "directors cut",
    "director s cut", "imax", "complete series", "complete season",
    "complete collection", "limited", "internal", "retail", "criterion",
    "anniversary", "edition", "extended cut", "extended edition",
    # common release groups
    "yts mx", "yts", "yify", "eztv", "rarbg", "galaxyrg", "cmrg", "smurf", "evo",
    "ntb", "psa", "qxr", "tigole", "megusta", "fgt", "ion10", "playready", "flux",
    "kogi", "successfulcrab",
)

_TAG_RE = re.compile(
    r"(?i)(?<![\w])(?:" + "|".join(re.escape(term) for term in sorted(_TAG_TERMS, key=len, reverse=True)) + r")(?![\w])"
)

_YEAR_RE = re.compile(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)")
_BRACKETS_RE = re.compile(r"[\[\(\{][^\[\]\(\)\{\}]*[\]\)\}]")
_SITE_PREFIX_RE = re.compile(
    r"(?i)^\s*(?:www\.)?[a-z0-9][a-z0-9-]*\.(?:com|net|org|me|tv|co|info|xyz)\s*[-–]\s*"
)
_EPISODE_RE = re.compile(
    r"""(?ix)
    (?<![\w])
    (?:
        s\d{1,2}(?:\s*[-–]\s*s?\d{1,2})?(?:e\d{1,4})?
      | e\d{1,4}
      | \d{1,2}\s*x\s*\d{1,4}
      | (?:season|series|episode|ep|الموسم|الحلقة|حلقة)\s*[._-]?\s*
        (?:\d{1,4}|الأول|الأولي|الثاني|الثالث|الرابع|الخامس|السادس|السابع|الثامن|التاسع|العاشر|الحادي\s+عشر|الثاني\s+عشر)
    )
    (?![\w])
    """
)
_AUDIO_CHANNEL_RE = re.compile(
    r"(?i)(?<![\w])(?:dd|ddp|aac|ac3|eac3|dts|truehd|atmos|flac|opus|mp3)"
    r"\s*[+\-]?\s*[257]\s*[._]?\s*1(?!\d)"
)
_DIMENSIONS_RE = re.compile(r"(?i)(?<![\w])\d{3,4}\s*x\s*\d{3,4}(?![\w])")
_BITRATE_RE = re.compile(r"(?i)(?<![\w])\d{2,4}\s*kbps(?![\w])")
_H26X_RE = re.compile(r"(?i)(?<![\w])[hx]\s*[._]?\s*26[45](?![\w])")
_RELEASE_HINT_RE = re.compile(
    r"(?i)(?<![\w])(?:\d{3,4}p|[48]k|uhd|bluray|blu-ray|web-dl|webrip|web dl|hdtv|"
    r"dvdrip|remux|x264|x265|h264|h265|hevc|avc|aac|ac3|eac3|dts|truehd|atmos|hdr|10bit)(?![\w])"
)
_GROUP_TAIL_DASH_RE = re.compile(r"(?<![\w])[-–@]\s*[A-Za-z0-9][\w.@-]{1,24}\s*$")
_GROUP_TAIL_UPPER_RE = re.compile(r"^[A-Z][A-Z0-9@._-]{1,14}$")
_UPPER_WHITELIST = {
    "USA", "UK", "US", "UAE", "NYC", "LA", "TV", "II", "III", "IV", "V", "VI",
    "VII", "VIII", "IX", "X", "DC", "MCU", "UHD",
}
_SERIES_HINT_RE = re.compile(
    r"(?i)(?<![\w])(?:s\d{1,2}(?:e\d{1,4})?|\d{1,2}x\d{1,4}|season|episode|"
    r"الموسم|الحلقة|حلقة)(?![\w])"
)
_SERIES_ONLY_TAG_RE = re.compile(r"(?i)(?<![\w])(?:complete|كامل|كاملة)(?![\w])")
_RELEASE_ONLY_TAG_RE = re.compile(r"(?i)(?<![\w])(?:extended|uncut|unrated)(?![\w])")
_ARABIC_PREFIX_RE = re.compile(r"^(?:فيلم|مسلسل)\s+", re.IGNORECASE)

_ARABIC_FOLD = str.maketrans({
    "أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا",
    "ى": "ي", "ئ": "ي", "ؤ": "و",
    "ة": "ه", "ﻻ": "لا", "ﻷ": "لا", "ﻹ": "لا", "ﻵ": "لا",
})


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def clean_title(raw: str) -> CleanedTitle:
    """Turn a folder/file name into a searchable title + optional year.

    >>> clean_title("Breaking.Bad.S01.1080p.BluRay.x264-Arabic").title
    'Breaking Bad'
    >>> clean_title("[YTS] Interstellar (2014) [1080p] [BluRay]").year
    2014
    """
    stem = _strip_extension((raw or "").strip())
    if not stem:
        return CleanedTitle("")

    result = _clean_impl(stem, extract_year=True)
    if not result.title and result.year is not None:
        # The name was only a year ("2012"): keep it as the title.
        fallback = _clean_impl(stem, extract_year=False)
        if fallback.title:
            return CleanedTitle(fallback.title, None)
    return result


def clean_folder_name(name: str) -> str:
    return clean_title(name).title


def normalize_for_match(value: str) -> str:
    """Normalise Latin + Arabic text so exact TMDB comparisons are reliable."""
    if not value:
        return ""
    text = unicodedata.normalize("NFKD", value)
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.translate(_ARABIC_FOLD)
    text = re.sub(r"[\u064B-\u065F\u0670]", "", text)  # Arabic diacritics
    text = text.casefold()
    text = text.replace("&", " and ")
    text = re.sub(r"['’`´]", "", text)
    text = re.sub(r"[^\w]+", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------
def _strip_extension(name: str) -> str:
    lowered = name.lower()
    for extension in (
        ".mkv", ".mp4", ".avi", ".mov", ".m4v", ".wmv", ".flv", ".webm",
        ".mpg", ".mpeg", ".m2ts", ".ts", ".vob", ".iso",
    ):
        if lowered.endswith(extension):
            return name[: -len(extension)]
    return name


def _clean_impl(text: str, *, extract_year: bool) -> CleanedTitle:
    text = _SITE_PREFIX_RE.sub(" ", text)
    text = text.replace("_", " ").replace(".", " ").replace("+", " ")

    year: int | None = None
    if extract_year:
        match = _find_year(text)
        if match:
            year = int(match.group(1))
            text = f"{text[:match.start()]} {text[match.end():]}"

    text = _BRACKETS_RE.sub(" ", text)
    has_series_hint = bool(_SERIES_HINT_RE.search(text))
    text = _EPISODE_RE.sub(" ", text)
    if has_series_hint:
        text = _SERIES_ONLY_TAG_RE.sub(" ", text)

    had_release_hint = bool(_RELEASE_HINT_RE.search(text))
    if had_release_hint:
        text = _RELEASE_ONLY_TAG_RE.sub(" ", text)
    text = _H26X_RE.sub(" ", text)
    text = _AUDIO_CHANNEL_RE.sub(" ", text)
    text = _DIMENSIONS_RE.sub(" ", text)
    text = _BITRATE_RE.sub(" ", text)
    text = _TAG_RE.sub(" ", text)

    if had_release_hint:
        text = _GROUP_TAIL_DASH_RE.sub(" ", text)
        text = _strip_uppercase_group_tail(text)

    text = _ARABIC_PREFIX_RE.sub("", text.strip())
    text = re.sub(r"[\[\](){},;:_|/\\]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    text = text.strip(" \t-–—@.·•*!\"'`")

    # Let clean_title() retry without year extraction (e.g. the movie "2012").
    if not text:
        return CleanedTitle("", year)

    if len(text) > 200:
        text = text[:200].rstrip()
    return CleanedTitle(text, year)


def _find_year(text: str) -> re.Match[str] | None:
    candidates = [
        match
        for match in _YEAR_RE.finditer(text)
        if MIN_YEAR <= int(match.group(1)) <= MAX_YEAR
    ]
    return candidates[-1] if candidates else None


def _strip_uppercase_group_tail(text: str) -> str:
    parts = text.split()
    if len(parts) < 3:
        return text
    last = parts[-1]
    if _GROUP_TAIL_UPPER_RE.fullmatch(last) and last.upper() not in _UPPER_WHITELIST:
        return " ".join(parts[:-1])
    return text
