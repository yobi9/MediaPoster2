"""Application specific exceptions."""

from __future__ import annotations


class MediaArtError(Exception):
    """Base class for all expected application errors."""


class TMDBError(MediaArtError):
    """Generic TMDB communication error."""


class TMDBAuthError(TMDBError):
    """The supplied TMDB key/token was rejected (HTTP 401)."""


class TMDBRateLimitError(TMDBError):
    """TMDB kept returning HTTP 429 after all retries."""


class ImageError(MediaArtError):
    """Downloading or converting an image failed."""


class CancelledError(MediaArtError):
    """The user asked to stop the current operation."""
