"""Orchestrates one library run: convert -> search -> download -> report."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

from ..config import (
    AppConfig,
    DEFAULT_BACKDROP_NAME,
    DEFAULT_POSTER_NAME,
    ALTERNATE_BACKDROP_NAME,
    FOLDER_THUMB_NAME,
    ensure_output_root,
)
from ..errors import CancelledError, ImageError, MediaArtError
from ..logging_setup import get_logger, log_success
from ..models import ItemResult, MediaItem, MediaKind, RunSummary, Status
from .images import ConversionResult, ImageService, convert_webp_in_folder, copy_image, is_folder_writable
from .manifest import OutputManifest
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
        # Fail before any item is touched: the folder was valid when the config
        # was built, but a dropped share or unplugged drive must not turn into
        # one ERROR per item at `target.mkdir()`.
        if (config.output_root or "").strip():
            ensure_output_root(config.output_root)
        # ``--images ""`` and the GUI checkboxes change the flags *after*
        # AppConfig.__post_init__, so warn once per run here as well.
        if not (
            config.download_poster
            or config.download_fanart
            or config.download_background
        ):
            logger.warning(
                "تحذير: كل أنواع الصور معطّلة — لن يُنزَّل أي ملف صورة."
            )
        self.config = config
        self.client = client
        self.images = images or ImageService(
            quality=config.jpeg_quality,
            timeout=config.request_timeout,
        )
        self.output_root = _resolve_output_root(config)
        self.library_root = _resolve_library_root(config)
        self.manifest = OutputManifest(self.output_root) if self.output_root else None
        self._warned_webp_skip = False
        self._warn_lock = threading.Lock()

    # ------------------------------------------------------------------
    # output_root helpers (B2/P13)
    def _rel_path(self, folder: Path) -> str | None:
        """Path of *folder* relative to the library root, POSIX-style."""
        if self.library_root is None:
            return None
        try:
            relative = folder.resolve().relative_to(self.library_root.resolve())
        except (ValueError, OSError):
            return None
        text = relative.as_posix()
        return text if text != "." else ""

    def _manifest_key(self, folder: Path) -> str:
        relative = self._rel_path(folder)
        return relative if relative else folder.name

    def _target_dir(self, folder: Path) -> Path:
        """Where the images of *folder* must be written.

        Without ``output_root`` this is the item folder itself (the historical
        behaviour). With it, the library-relative path is mirrored inside the
        output tree, so the source library is never written to.
        """
        if self.output_root is None:
            return folder
        relative = self._rel_path(folder)
        if not relative:
            logger.warning(
                "'%s' خارج جذر المكتبة؛ سيُكتب داخل المصدر نفسه.", folder
            )
            return folder
        return self.output_root / relative

    def _warn_untracked_files(
        self,
        folder: Path,
        target: Path,
        has_poster: bool,
        has_backdrop: bool,
    ) -> None:
        """Report images already in the output tree that our manifest lacks."""
        if self.manifest is None:
            return
        key = self._manifest_key(folder)
        if self.manifest.entry(key) is not None:
            return
        for name, present in (
            (DEFAULT_POSTER_NAME, has_poster),
            (DEFAULT_BACKDROP_NAME, has_backdrop),
        ):
            if present:
                logger.warning(
                    "تخطّي: الملف موجود مسبقاً بلا سجل: %s/%s", key, name
                )

    def _record_manifest(self, item: MediaItem, result: ItemResult) -> None:
        if self.manifest is None:
            return
        if result.status in (Status.PREVIEW, Status.NOT_FOUND, Status.CANCELLED):
            return
        target = self._target_dir(item.path)
        present = [
            name
            for name in (
                DEFAULT_POSTER_NAME,
                DEFAULT_BACKDROP_NAME,
                ALTERNATE_BACKDROP_NAME,
                FOLDER_THUMB_NAME,
            )
            if _is_non_empty_file(target / name)
        ]
        if result.status is Status.ERROR:
            status = "error"
        elif result.status is Status.PARTIAL:
            status = "partial"
        else:
            status = "ok" if present else "partial"
        self.manifest.update_entry(self._manifest_key(item.path), present, status)

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

        workers = _workers_for(self.config)
        if workers > 1:
            return self._run_items_parallel(
                items, workers, should_cancel, on_item, on_progress
            )

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
            self._record_manifest(item, result)
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

    def _run_items_parallel(
        self,
        items: list[MediaItem],
        workers: int,
        should_cancel: CancelCheck | None,
        on_item: ItemCallback | None,
        on_progress: ProgressCallback | None,
    ) -> RunSummary:
        """Process items on a small thread pool, reporting in input order.

        Results are collected by submitting in order and then waiting on each
        future in that same order, so the table never jumps. A failing item is
        isolated inside its own task and cannot abort the rest of the run.
        """
        started = time.monotonic()
        summary = RunSummary(total=len(items))
        total = len(items)
        cancelled = False

        with ThreadPoolExecutor(
            max_workers=workers, thread_name_prefix="mediaart"
        ) as pool:
            futures = [
                pool.submit(self._process_isolated, item, should_cancel)
                for item in items
            ]
            try:
                for index, (item, future) in enumerate(
                    zip(items, futures), start=1
                ):
                    if should_cancel and should_cancel():
                        cancelled = True
                        break
                    if on_progress:
                        on_progress(index - 1, total, item.title)
                    result = future.result()
                    summary.results.append(result)
                    self._record_manifest(item, result)
                    summary.webp_converted += result.webp_converted
                    summary.webp_would_convert += result.webp_would_convert
                    if on_item:
                        on_item(result)
                    if result.status is Status.CANCELLED:
                        cancelled = True
                        break
                    if on_progress:
                        on_progress(index, total, item.title)
                    if should_cancel and should_cancel():
                        cancelled = True
                        break
            finally:
                for future in futures:
                    future.cancel()

        summary.cancelled = cancelled
        summary.duration = time.monotonic() - started
        if summary.cancelled:
            logger.warning(
                "تم إيقاف المعالجة يدوياً بعد %d من %d عنصر.",
                len(summary.results),
                total,
            )
        else:
            log_success(logger, "انتهت المعالجة: %s", summary.summary_text())
        return summary

    def _process_isolated(
        self, item: MediaItem, should_cancel: CancelCheck | None
    ) -> ItemResult:
        """One task of a parallel run: never raises into the pool."""
        if should_cancel and should_cancel():
            return ItemResult(item=item, status=Status.CANCELLED, message="تم الإلغاء.")
        try:
            return self.process_item(item)
        except CancelledError:
            return ItemResult(item=item, status=Status.CANCELLED, message="تم الإلغاء.")
        except MediaArtError as exc:
            logger.error("فشل معالجة '%s': %s", item.title, exc)
            return ItemResult(item=item, status=Status.ERROR, message=str(exc))
        except Exception as exc:  # pragma: no cover - unexpected bug guard
            logger.exception("خطأ غير متوقع أثناء معالجة '%s'", item.title)
            return ItemResult(
                item=item,
                status=Status.ERROR,
                message=f"خطأ غير متوقع: {exc.__class__.__name__}: {exc}",
            )

    # ------------------------------------------------------------------
    def process_item(self, item: MediaItem) -> ItemResult:
        folder = item.path
        cfg = self.config
        target = self._target_dir(folder)
        if self.output_root is not None and not cfg.dry_run:
            try:
                target.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                message = f"تعذر إنشاء مجلد الإخراج: {target} ({exc})"
                logger.error("%s: %s", item.title, message)
                return ItemResult(item=item, status=Status.ERROR, message=message)

        # One writability probe per work, before any network traffic: an
        # unwritable target would otherwise waste a full download per image.
        # With `output_root` the source may be read-only on purpose, so the
        # probe and every write below use the output tree instead.
        if not is_folder_writable(target):
            message = f"مجلد الهدف غير قابل للكتابة: {target}"
            logger.error("%s: %s", item.title, message)
            return ItemResult(
                item=item,
                status=Status.ERROR,
                message=message,
                target_writable=False,
            )

        conversion = ConversionResult()

        if cfg.convert_existing_webp:
            if self.output_root is not None:
                # Converting WebP rewrites files next to the source images, so
                # it cannot run against a read-only library.
                with self._warn_lock:
                    if not self._warned_webp_skip:
                        logger.warning(
                            "تم تعطيل تحويل WebP لأن output_root مُعيَّن (التحويل "
                            "يكتب بجوار المصدر). حوّل ملفات WebP يدوياً قبل التشغيل، "
                            "أو شغّل بلا --output-root."
                        )
                        self._warned_webp_skip = True
                cfg_convert_webp = False
            else:
                cfg_convert_webp = True
        else:
            cfg_convert_webp = False

        if cfg_convert_webp:
            conversion = convert_webp_in_folder(
                folder,
                quality=cfg.jpeg_quality,
                recursive=(cfg.convert_nested_webp and item.kind is MediaKind.SERIES),
                overwrite=cfg.overwrite_images,
                dry_run=cfg.dry_run,
                should_cancel=self.images.cancel_check,
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

        if conversion.cancelled:
            logger.warning("%s: أُلغي تحويل WebP.", item.title)
            return ItemResult(item=item, status=Status.CANCELLED, message="تم الإلغاء.")

        if cfg.convert_only:
            return self._conversion_only_result(item, conversion)

        want_poster = bool(cfg.download_poster)
        want_fanart = bool(cfg.download_fanart)
        want_background = bool(cfg.download_background)
        want_backdrop = want_fanart or want_background

        poster_path = target / DEFAULT_POSTER_NAME
        fanart_path = target / DEFAULT_BACKDROP_NAME
        background_path = target / ALTERNATE_BACKDROP_NAME

        has_poster = _is_non_empty_file(poster_path)
        has_fanart = _is_non_empty_file(fanart_path)
        has_background = _is_non_empty_file(background_path)

        # كل نوع يُفحص مستقلاً: وجود poster.jpg لا يعني تخطّي fanart.jpg.
        need_poster = want_poster and (cfg.overwrite_images or not has_poster)
        need_fanart = want_fanart and (cfg.overwrite_images or not has_fanart)
        need_background = want_background and (
            cfg.overwrite_images or not has_background
        )
        need_backdrop = need_fanart or need_background

        if self.output_root is not None and (
            has_poster or has_fanart or has_background
        ):
            self._warn_untracked_files(folder, target, has_poster, has_fanart)

        if not want_poster and not want_backdrop:
            message = "كل أنواع الصور معطّلة — لم يُنزَّل أي ملف."
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

        if not need_poster and not need_backdrop:
            self._ensure_folder_thumbnail(target)
            message = "الصور المطلوبة موجودة مسبقاً."
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

        # لا شيء من الأنواع المطلوبة متوفر في TMDB: هذا SKIPPED لا ERROR
        # (حالة شائعة: فيلم قديم بلا خلفية).
        if not (
            (need_poster and match.poster_path)
            or (need_backdrop and match.backdrop_path)
        ):
            missing: list[str] = []
            if need_poster and not match.poster_path:
                missing.append("لا يوجد رابط ملصق في TMDB")
            if need_backdrop and not match.backdrop_path:
                missing.append("لا يوجد رابط خلفية في TMDB")
            message = f"'{match.title}' — " + "؛ ".join(missing)
            logger.warning("%s: %s", item.title, message)
            return ItemResult(
                item=item,
                status=Status.SKIPPED,
                message=message,
                matched_title=match.title,
                webp_converted=conversion.converted,
                webp_would_convert=conversion.would_convert,
            )

        if cfg.dry_run:
            plans = []
            if need_poster and match.poster_path:
                plans.append("الملصق")
            if need_fanart and match.backdrop_path:
                plans.append("fanart.jpg")
            if need_background and match.backdrop_path:
                plans.append("background.jpg")
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
        warnings_list: list[str] = []
        poster_saved = False
        fanart_saved = False
        background_saved = False
        backdrop_saved = False

        if need_poster:
            if match.poster_path:
                try:
                    written = self.images.save_image(
                        _require_url(match.poster_path),
                        target,
                        [DEFAULT_POSTER_NAME],
                        overwrite=cfg.overwrite_images,
                    )
                    poster_saved = bool(written)
                    if not written and not has_poster:
                        errors.append("تعذر حفظ الملصق")
                except ImageError as exc:
                    errors.append(f"الملصق: {exc}")
                    logger.error("%s: فشل تنزيل الملصق — %s", item.title, exc)
            else:
                warnings_list.append("لا يوجد رابط ملصق في TMDB")
                logger.warning("%s: لا يوجد رابط ملصق في TMDB.", item.title)

        if need_backdrop:
            if match.backdrop_path:
                # طلب واحد فقط: يُنزَّل إلى أول اسم مطلوب ثم يُنسخ من نفس
                # البيانات للأسماء الأخرى (لا قراءة من fanart.jpg ولا طلب ثانٍ).
                names: list[str] = []
                if need_fanart:
                    names.append(DEFAULT_BACKDROP_NAME)
                if need_background:
                    names.append(ALTERNATE_BACKDROP_NAME)
                try:
                    written = self.images.save_image(
                        _require_url(match.backdrop_path),
                        target,
                        names,
                        overwrite=cfg.overwrite_images,
                    )
                    backdrop_saved = bool(written)
                    fanart_saved = need_fanart and _is_non_empty_file(fanart_path)
                    background_saved = need_background and _is_non_empty_file(
                        background_path
                    )
                    if not written and not (fanart_saved or background_saved):
                        errors.append("تعذر حفظ الخلفية")
                except ImageError as exc:
                    errors.append(f"الخلفية: {exc}")
                    logger.error("%s: فشل تنزيل الخلفية — %s", item.title, exc)
            else:
                warnings_list.append("لا يوجد رابط خلفية في TMDB")
                logger.warning("%s: لا يوجد رابط خلفية في TMDB.", item.title)

        self._ensure_folder_thumbnail(target)

        final_poster = _is_non_empty_file(poster_path)
        final_fanart = _is_non_empty_file(fanart_path)
        final_background = _is_non_empty_file(background_path)

        required_ok = True
        if need_poster and match.poster_path:
            required_ok = required_ok and final_poster
        if need_fanart and match.backdrop_path:
            required_ok = required_ok and final_fanart
        if need_background and match.backdrop_path:
            required_ok = required_ok and final_background

        if required_ok:
            status = Status.PARTIAL if (errors or warnings_list) else Status.OK
        elif final_poster or final_fanart or final_background:
            status = Status.PARTIAL
        else:
            status = Status.ERROR

        saved_labels: list[str] = []
        if poster_saved:
            saved_labels.append("الملصق")
        if fanart_saved:
            saved_labels.append("fanart.jpg")
        if background_saved:
            saved_labels.append("background.jpg")
        message = (
            "تم تنزيل " + " و".join(saved_labels)
            if saved_labels
            else "لم يتم حفظ صور جديدة"
        )
        if errors or warnings_list:
            message += " — " + "؛ ".join(errors + warnings_list)
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


def _workers_for(config: AppConfig) -> int:
    """Number of parallel item tasks (AppConfig already clamps it to 1..8)."""
    try:
        value = int(getattr(config, "max_workers", 1) or 1)
    except (TypeError, ValueError):
        return 1
    return max(1, min(8, value))


def _resolve_output_root(config: AppConfig) -> Path | None:
    raw = (config.output_root or "").strip()
    if not raw:
        return None
    root = Path(raw).expanduser()
    library = (config.library_path or "").strip()
    if library:
        try:
            if root.resolve() == Path(library).expanduser().resolve():
                # Same tree: behave as if the option was never set.
                logger.info("output_root يطابق مجلد المكتبة؛ سيُتجاهل.")
                return None
        except OSError:  # pragma: no cover - unresolvable path on Windows
            pass
    return root


def _resolve_library_root(config: AppConfig) -> Path | None:
    library = (config.library_path or "").strip()
    return Path(library).expanduser() if library else None


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
