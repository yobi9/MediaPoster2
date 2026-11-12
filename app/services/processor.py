"""Orchestrates one library run: convert -> search -> download -> report."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from ..config import (
    AppConfig,
    DEFAULT_BACKDROP_NAME,
    DEFAULT_POSTER_NAME,
    ALTERNATE_BACKDROP_NAME,
    FOLDER_THUMB_NAME,
)
from ..errors import CancelledError, ImageError, MediaArtError
from ..logging_setup import get_logger, log_success
from ..models import ItemResult, MediaItem, MediaKind, RunSummary, Status
from .images import ConversionResult, ImageService, convert_webp_in_folder, copy_image, is_folder_writable
from .tmdb import TMDBClient

logger = get_logger("processor")

ProgressCallback = Callable[[int, int, str], None]
ItemCallback = Callable[[ItemResult], None]
CancelCheck = Callable[[], bool]


class Processor:
    def __init__(
        self,
        config: AppConfig,
        *,
        client: TMDBClient | None = None,
        images: ImageService | None = None,
    ) -> None:
        self.config = config
        self.client = client
        self.images = images or ImageService(
            quality=config.jpeg_quality,
            timeout=config.request_timeout,
        )

    # ------------------------------------------------------------------
    def run(
        self,
        items: list[MediaItem],
        *,
        should_cancel: CancelCheck | None = None,
        on_item: ItemCallback | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> RunSummary:
        started = time.monotonic()
        summary = RunSummary(total=len(items))
        if should_cancel is not None:
            self.images.cancel_check = should_cancel

        total = len(items)
        for index, item in enumerate(items, start=1):
            if should_cancel and should_cancel():
                summary.cancelled = True
                break
            if on_progress:
                on_progress(index - 1, total, item.title)

            try:
                result = self.process_item(item)
            except CancelledError:
                summary.results.append(
                    ItemResult(item=item, status=Status.CANCELLED, message="تم الإلغاء.")
                )
                summary.cancelled = True
                break
            except MediaArtError as exc:
                logger.error("فشل معالجة '%s': %s", item.title, exc)
                result = ItemResult(item=item, status=Status.ERROR, message=str(exc))
            except Exception as exc:  # pragma: no cover - unexpected bug guard
                logger.exception("خطأ غير متوقع أثناء معالجة '%s'", item.title)
                result = ItemResult(
                    item=item,
                    status=Status.ERROR,
                    message=f"خطأ غير متوقع: {exc.__class__.__name__}: {exc}",
                )

            summary.results.append(result)
            summary.webp_converted += result.webp_converted
            summary.webp_would_convert += result.webp_would_convert
            if on_item:
                on_item(result)
            if on_progress:
                on_progress(index, total, item.title)
            if should_cancel and should_cancel():
                summary.cancelled = True
                break

        summary.duration = time.monotonic() - started
        if summary.cancelled:
            logger.warning("تم إيقاف المعالجة يدوياً بعد %d من %d عنصر.", len(summary.results), total)
        else:
            log_success(logger, "انتهت المعالجة: %s", summary.summary_text())
        return summary

    # ------------------------------------------------------------------
    def process_item(self, item: MediaItem) -> ItemResult:
        folder = item.path
        cfg = self.config

        # One writability probe per work, before any network traffic: an
        # unwritable target would otherwise waste a full download per image.
        # (When `output_root` lands in v1.1, the "read-only share" case
        # disappears because the images are written to a different tree.)
        if not is_folder_writable(folder):
            message = f"مجلد الهدف غير قابل للكتابة: {folder}"
            logger.error("%s: %s", item.title, message)
            return ItemResult(
                item=item,
                status=Status.ERROR,
                message=message,
                target_writable=False,
            )

        conversion = ConversionResult()

        if cfg.convert_existing_webp:
            conversion = convert_webp_in_folder(
                folder,
                quality=cfg.jpeg_quality,
                recursive=(cfg.convert_nested_webp and item.kind is MediaKind.SERIES),
                overwrite=cfg.overwrite_images,
                dry_run=cfg.dry_run,
            )
            if conversion.converted:
                logger.info(
                    "%s: تم تحويل %d ملف WebP إلى JPG.",
                    item.title,
                    conversion.converted,
                )
            elif conversion.would_convert:
                logger.info(
                    "%s: [معاينة] سيتم تحويل %d ملف WebP إلى JPG.",
                    item.title,
                    conversion.would_convert,
                )

        if cfg.convert_only:
            return self._conversion_only_result(item, conversion)

        poster_names = [DEFAULT_POSTER_NAME]
        backdrop_names = [DEFAULT_BACKDROP_NAME]
        if cfg.create_background_copy:
            backdrop_names.append(ALTERNATE_BACKDROP_NAME)

        if not cfg.dry_run:
            self._mirror_backdrops(folder, backdrop_names)

        poster_path = folder / DEFAULT_POSTER_NAME
        has_poster = _is_non_empty_file(poster_path)
        has_backdrop = any(_is_non_empty_file(folder / name) for name in backdrop_names)
        need_poster = cfg.overwrite_images or not has_poster
        need_backdrop = cfg.overwrite_images or not has_backdrop

        if not need_poster and not need_backdrop:
            self._ensure_folder_thumbnail(folder)
            message = "الصور القياسية موجودة مسبقاً."
            if cfg.dry_run:
                if conversion.would_convert:
                    message = (
                        f"[معاينة] سيتم تحويل {conversion.would_convert} ملف WebP إلى JPG. "
                        f"{message}"
                    )
            elif conversion.converted:
                message = f"تم تحويل {conversion.converted} ملف WebP. {message}"
            return ItemResult(
                item=item,
                status=Status.SKIPPED,
                message=message,
                webp_converted=conversion.converted,
                webp_would_convert=conversion.would_convert,
            )

        if self.client is None:
            raise MediaArtError("مفتاح TMDB مطلوب، لكنه غير متوفر.")

        match = self.client.find_match(item)
        if match is None:
            return ItemResult(
                item=item,
                status=Status.NOT_FOUND,
                message="لم يتم العثور على تطابق في TMDB.",
                webp_converted=conversion.converted,
                webp_would_convert=conversion.would_convert,
            )

        if not match.poster_path and not match.backdrop_path:
            return ItemResult(
                item=item,
                status=Status.NOT_FOUND,
                message=f"تم العثور على '{match.title}' لكن بدون ملصق أو خلفية.",
                matched_title=match.title,
                webp_converted=conversion.converted,
                webp_would_convert=conversion.would_convert,
            )

        if cfg.dry_run:
            plans = []
            if need_poster and match.poster_path:
                plans.append("الملصق")
            if need_backdrop and match.backdrop_path:
                plans.append("الخلفية")
            detail = " و".join(plans) if plans else "لا توجد صور ناقصة"
            message = (
                f"[معاينة] تطابق: {match.title} ({match.year or '؟'}) "
                f"— سيتم تنزيل: {detail}"
            )
            if conversion.would_convert:
                message += (
                    f" — وسيتم تحويل {conversion.would_convert} ملف WebP إلى JPG"
                )
            return ItemResult(
                item=item,
                status=Status.PREVIEW,
                message=message,
                matched_title=match.title,
                webp_converted=conversion.converted,
                webp_would_convert=conversion.would_convert,
                dry_run=True,
            )

        errors: list[str] = []
        poster_saved = False
        backdrop_saved = False

        if need_poster and match.poster_path:
            try:
                written = self.images.save_image(
                    _require_url(match.poster_path),
                    folder,
                    poster_names,
                    overwrite=cfg.overwrite_images,
                )
                poster_saved = bool(written)
                if not written and not has_poster:
                    errors.append("تعذر حفظ الملصق")
            except ImageError as exc:
                errors.append(f"الملصق: {exc}")
                logger.error("%s: فشل تنزيل الملصق — %s", item.title, exc)
        elif need_poster:
            errors.append("لا يوجد رابط ملصق في TMDB")

        if need_backdrop and match.backdrop_path:
            try:
                written = self.images.save_image(
                    _require_url(match.backdrop_path),
                    folder,
                    backdrop_names,
                    overwrite=cfg.overwrite_images,
                )
                backdrop_saved = bool(written)
                if not written and not has_backdrop:
                    errors.append("تعذر حفظ الخلفية")
            except ImageError as exc:
                errors.append(f"الخلفية: {exc}")
                logger.error("%s: فشل تنزيل الخلفية — %s", item.title, exc)
        elif need_backdrop:
            errors.append("لا يوجد رابط خلفية في TMDB")

        self._ensure_folder_thumbnail(folder)

        final_poster = _is_non_empty_file(poster_path)
        final_backdrop = any(_is_non_empty_file(folder / name) for name in backdrop_names)
        required_ok = (not need_poster or final_poster) and (not need_backdrop or final_backdrop)

        if required_ok:
            status = Status.PARTIAL if errors else Status.OK
        elif final_poster or final_backdrop:
            status = Status.PARTIAL
        else:
            status = Status.ERROR

        saved_labels = []
        if poster_saved:
            saved_labels.append("الملصق")
        if backdrop_saved:
            saved_labels.append("الخلفية")
        message = (
            "تم تنزيل " + " و".join(saved_labels)
            if saved_labels
            else "لم يتم حفظ صور جديدة"
        )
        if errors:
            message += " — " + "؛ ".join(errors)
        if conversion.converted:
            message = f"تحويل WebP: {conversion.converted}. " + message

        if status is Status.OK:
            log_success(logger, "%s: %s", item.title, message)
        elif status is Status.PARTIAL:
            logger.warning("%s: %s", item.title, message)
        else:
            logger.error("%s: %s", item.title, message)

        return ItemResult(
            item=item,
            status=status,
            message=message,
            matched_title=match.title,
            poster_saved=poster_saved,
            backdrop_saved=backdrop_saved,
            webp_converted=conversion.converted,
            webp_would_convert=conversion.would_convert,
        )

    # ------------------------------------------------------------------
    def _conversion_only_result(self, item: MediaItem, conversion: ConversionResult) -> ItemResult:
        dry_run = self.config.dry_run
        if conversion.failed and not conversion.converted:
            status = Status.ERROR
            message = f"فشل تحويل {conversion.failed} ملف WebP."
        elif dry_run:
            if conversion.would_convert:
                status = Status.PREVIEW
                message = (
                    f"[معاينة] سيتم تحويل {conversion.would_convert} ملف WebP إلى JPG."
                )
            else:
                status = Status.SKIPPED
                message = "لا توجد ملفات WebP قابلة للتحويل."
        elif conversion.converted:
            status = Status.OK
            message = f"تم تحويل {conversion.converted} ملف WebP إلى JPG."
        else:
            status = Status.SKIPPED
            message = "لا توجد ملفات WebP قابلة للتحويل."
        return ItemResult(
            item=item,
            status=status,
            message=message,
            webp_converted=conversion.converted,
            webp_would_convert=conversion.would_convert,
            dry_run=dry_run,
        )

    def _mirror_backdrops(self, folder: Path, names: list[str]) -> None:
        existing = [folder / name for name in names if _is_non_empty_file(folder / name)]
        if not existing:
            return
        primary = existing[0]
        for name in names:
            target = folder / name
            if target == primary:
                continue
            try:
                if copy_image(primary, target, overwrite=False):
                    logger.debug("تم إنشاء نسخة خلفية إضافية: %s", target.name)
            except ImageError as exc:
                logger.warning("تعذر نسخ %s إلى %s: %s", primary.name, target.name, exc)

    def _ensure_folder_thumbnail(self, folder: Path) -> None:
        if not self.config.create_folder_thumbnail:
            return
        poster = folder / DEFAULT_POSTER_NAME
        if not _is_non_empty_file(poster):
            return
        try:
            if copy_image(poster, folder / FOLDER_THUMB_NAME, overwrite=self.config.overwrite_images):
                logger.debug("تم إنشاء %s", FOLDER_THUMB_NAME)
        except ImageError as exc:
            logger.warning("تعذر إنشاء %s: %s", FOLDER_THUMB_NAME, exc)

    def close(self) -> None:
        try:
            if self.client:
                self.client.close()
        finally:
            self.images.close()


def _is_non_empty_file(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def _require_url(path: str) -> str:
    from .tmdb import image_url

    url = image_url(path)
    if not url:
        raise ImageError("رابط الصورة غير صالح.")
    return url
