"""Image downloading and WebP -> JPEG conversion.

Safety rules:

* Every write is atomic (temp file + ``os.replace``).
* The source ``.webp`` is deleted only after a valid JPEG was written.
* Transparent images are flattened onto white, never onto black.
* Original TMDB JPEG bytes are copied as-is to avoid re-compression loss.
"""

from __future__ import annotations

import os
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

import requests
from PIL import Image, ImageOps

from ..errors import CancelledError, ImageError
from ..logging_setup import get_logger
from .tmdb import USER_AGENT

logger = get_logger("images")

MAX_DOWNLOAD_BYTES = 80 * 1024 * 1024

_IGNORED_WEBP_DIRS = frozenset({
    "@eadir", "#recycle", "$recycle.bin", "system volume information",
    "lost+found", "__macosx",
})


@dataclass(slots=True)
class ConversionResult:
    converted: int = 0
    skipped: int = 0
    failed: int = 0
    #: عدد الملفات التي "سيتم" تحويلها في وضع المعاينة (dry_run).
    #: يبقى ``converted`` صفراً في المعاينة لأن شيئاً لم يُنفَّذ فعلياً.
    would_convert: int = 0

    @property
    def touched(self) -> bool:
        return self.converted > 0


def _clamp_quality(quality: int) -> int:
    try:
        return max(60, min(100, int(quality)))
    except (TypeError, ValueError):
        return 95


# ----------------------------------------------------------------------
# Conversion helpers (no network)
# ----------------------------------------------------------------------
def is_folder_writable(folder: Path | str) -> bool:
    """Return True when a new file can actually be created inside *folder*.

    ``os.access(folder, os.W_OK)`` is **not** reliable on Windows: it reports
    True for folders the current user is denied write access to (denied ACLs
    and read-only SMB shares). Creating and removing a temporary probe file is
    the only trustworthy test, and it is cheap compared to a failed download.
    """
    path = Path(folder)
    probe = path / f".{uuid.uuid4().hex}.writetest.tmp"
    try:
        with open(probe, "wb"):
            pass
    except OSError:
        return False
    finally:
        try:
            probe.unlink(missing_ok=True)
        except OSError as exc:  # pragma: no cover - rare cleanup failure
            logger.warning("تعذر حذف ملف الفحص المؤقت %s: %s", probe.name, exc)
    return True


def convert_to_jpeg(src: Path | str, dest: Path | str, quality: int = 95) -> Path:
    """Convert any Pillow-readable image to an RGB JPEG atomically."""
    source = Path(src)
    target = Path(dest)
    quality = _clamp_quality(quality)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")

    try:
        with Image.open(source) as opened:
            if getattr(opened, "is_animated", False):
                opened.seek(0)
            image = ImageOps.exif_transpose(opened)
            image.load()
            rgb = _flatten_to_rgb(image)
            save_options = {
                "format": "JPEG",
                "quality": quality,
                "optimize": True,
                "progressive": True,
                "subsampling": 0 if quality >= 100 else 1 if quality >= 90 else 2,
            }
            rgb.save(tmp, **save_options)
        os.replace(tmp, target)
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        raise ImageError(f"فشل تحويل الصورة {source.name}: {exc}") from exc
    finally:
        tmp.unlink(missing_ok=True)
    return target


def convert_webp_file(
    src: Path | str,
    dest: Path | str | None = None,
    *,
    quality: int = 95,
    overwrite: bool = False,
    delete_source: bool = True,
) -> Path | None:
    """Convert one ``.webp`` file to ``.jpg``; returns None when skipped."""
    source = Path(src)
    target = Path(dest) if dest is not None else source.with_suffix(".jpg")
    if target.exists() and not overwrite:
        logger.warning(
            "تم تخطي تحويل %s لأن %s موجود مسبقاً (فعّل تجاوز الصور للاستبدال).",
            source.name,
            target.name,
        )
        return None
    convert_to_jpeg(source, target, quality=quality)
    if delete_source:
        try:
            source.unlink()
        except OSError as exc:
            logger.warning("تم إنشاء %s لكن تعذر حذف %s: %s", target.name, source.name, exc)
    return target


def convert_webp_in_folder(
    folder: Path | str,
    *,
    quality: int = 95,
    recursive: bool = False,
    overwrite: bool = False,
    dry_run: bool = False,
) -> ConversionResult:
    result = ConversionResult()
    for source in _iter_webp(Path(folder), recursive):
        target = source.with_suffix(".jpg")
        if target.exists() and not overwrite:
            result.skipped += 1
            logger.debug("WebP موجود و JPG موجود، تخطي: %s", source)
            continue
        if dry_run:
            # المعاينة لا تُنفّذ شيئاً: نُحصي التحويل المتوقّع فقط،
            # ويبقى العدّاد converted صفراً حتى لا يُنسب تنفيذٌ لم يحدث.
            result.would_convert += 1
            logger.info("[معاينة] سيتم تحويل: %s", source)
            continue
        try:
            if convert_webp_file(
                source,
                target,
                quality=quality,
                overwrite=overwrite,
                delete_source=True,
            ):
                result.converted += 1
                logger.info("تم تحويل WebP إلى JPG: %s", target.name)
            else:
                result.skipped += 1
        except (ImageError, OSError) as exc:
            result.failed += 1
            logger.error("فشل تحويل %s: %s", source, exc)
    return result


def _iter_webp(folder: Path, recursive: bool) -> Iterator[Path]:
    if not recursive:
        try:
            children = list(folder.iterdir())
        except OSError as exc:
            logger.error("تعذر قراءة المجلد %s: %s", folder, exc)
            return
        for child in children:
            try:
                if child.is_file() and child.suffix.lower() == ".webp":
                    yield child
            except OSError:
                continue
        return

    def _on_error(exc: OSError) -> None:
        logger.warning("تعذر الوصول إلى مجلد أثناء البحث عن WebP: %s", exc)

    for dirpath, dirnames, filenames in os.walk(folder, topdown=True, onerror=_on_error):
        dirnames[:] = [
            name for name in dirnames
            if not name.startswith((".", "@", "$")) and name.lower() not in _IGNORED_WEBP_DIRS
        ]
        for filename in filenames:
            if filename.lower().endswith(".webp"):
                yield Path(dirpath) / filename


def copy_image(src: Path, dest: Path, *, overwrite: bool = False) -> bool:
    if dest.exists() and not overwrite:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f".{dest.name}.{uuid.uuid4().hex}.tmp")
    try:
        shutil.copy2(src, tmp)
        os.replace(tmp, dest)
        return True
    except OSError as exc:
        raise ImageError(f"تعذر نسخ {src.name} إلى {dest.name}: {exc}") from exc
    finally:
        tmp.unlink(missing_ok=True)


# ----------------------------------------------------------------------
# Downloading
# ----------------------------------------------------------------------
class ImageService:
    def __init__(
        self,
        *,
        quality: int = 95,
        timeout: int = 20,
        session: requests.Session | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> None:
        self.quality = _clamp_quality(quality)
        self.timeout = max(5, int(timeout))
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self.cancel_check = cancel_check

    def close(self) -> None:
        self.session.close()

    # ------------------------------------------------------------------
    def save_image(
        self,
        url: str,
        folder: Path | str,
        names: tuple[str, ...] | list[str],
        *,
        overwrite: bool = False,
    ) -> list[Path]:
        """Download *url* once as ``names[0]`` then mirror it to other names."""
        if not names:
            return []
        folder_path = Path(folder)
        targets = [folder_path / name for name in names]
        primary = targets[0]
        written: list[Path] = []

        if not primary.exists() or overwrite:
            self._download_to(url, primary)
            written.append(primary)
        else:
            logger.debug("الصورة موجودة، لن يتم تنزيلها: %s", primary)

        for extra in targets[1:]:
            if copy_image(primary, extra, overwrite=overwrite):
                written.append(extra)
        return written

    def _download_to(self, url: str, dest: Path) -> None:
        if not url:
            raise ImageError("رابط الصورة فارغ.")
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(f".{dest.name}.{uuid.uuid4().hex}.part")
        last_error = "فشل تنزيل الصورة."

        try:
            for attempt in range(1, 3):
                try:
                    with self.session.get(
                        url,
                        stream=True,
                        timeout=(5, self.timeout),
                    ) as response:
                        if response.status_code != 200:
                            raise ImageError(f"خادم الصور أعاد HTTP {response.status_code}.")
                        content_type = (response.headers.get("Content-Type") or "").lower()
                        if content_type and not (
                            content_type.startswith("image/")
                            or content_type.startswith("application/octet-stream")
                        ):
                            raise ImageError(f"نوع محتوى غير متوقع: {content_type}")
                        declared = _int_header(response.headers.get("Content-Length"))
                        if declared > MAX_DOWNLOAD_BYTES:
                            raise ImageError("حجم الصورة أكبر من الحد المسموح (80MB).")

                        written = 0
                        with open(tmp, "wb") as handle:
                            for chunk in response.iter_content(chunk_size=256 * 1024):
                                if self.cancel_check and self.cancel_check():
                                    raise CancelledError("تم إلغاء تنزيل الصورة.")
                                if not chunk:
                                    continue
                                written += len(chunk)
                                if written > MAX_DOWNLOAD_BYTES:
                                    raise ImageError("تجاوز حجم الصورة الحد المسموح.")
                                handle.write(chunk)
                    if written == 0:
                        raise ImageError("الملف الذي تم تنزيله فارغ.")
                    _finalize_download(tmp, dest, self.quality)
                    return
                except CancelledError:
                    raise
                except requests.RequestException as exc:
                    # Network / timeout problems are the only transient ones.
                    last_error = str(exc)
                    tmp.unlink(missing_ok=True)
                    if attempt < 2:
                        logger.warning("إعادة محاولة تنزيل الصورة (%s)...", exc)
                        continue
                except OSError as exc:
                    # Local write failures (permissions, disk) never recover
                    # on their own: fail fast instead of downloading again.
                    raise ImageError(f"تعذر حفظ الصورة في {dest}: {exc}") from exc
                except ImageError:
                    # Bad content type / oversized image: not transient.
                    raise
            raise ImageError(last_error)
        finally:
            tmp.unlink(missing_ok=True)


def _finalize_download(tmp: Path, dest: Path, quality: int) -> None:
    """Validate the download and either keep JPEG bytes or re-encode."""
    try:
        with Image.open(tmp) as opened:
            image_format = (opened.format or "").upper()
            mode = opened.mode
            animated = bool(getattr(opened, "is_animated", False))
            if image_format == "JPEG" and mode in {"RGB", "L"} and not animated:
                opened.verify()
                os.replace(tmp, dest)
                return
        convert_to_jpeg(tmp, dest, quality=quality)
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        raise ImageError(f"الصورة التي تم تنزيلها غير صالحة: {exc}") from exc


def _flatten_to_rgb(image: Image.Image) -> Image.Image:
    if image.mode in {"RGBA", "LA"} or (image.mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
    if image.mode != "RGB":
        return image.convert("RGB")
    return image


def _int_header(value: str | None) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
