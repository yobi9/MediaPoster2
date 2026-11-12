"""Headless command line mode (useful for NAS sync jobs and AI agents)."""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import threading
from contextlib import contextmanager
from pathlib import Path

from .config import (
    BACKDROP_SIZES,
    DEFAULT_MAX_WORKERS,
    IMAGE_TYPES,
    MAX_JPEG_QUALITY,
    MAX_MAX_WORKERS,
    MEDIA_FILTERS,
    MIN_JPEG_QUALITY,
    MIN_MAX_WORKERS,
    POSTER_SIZES,
    AppConfig,
    VERSION,
    ensure_output_root,
    load_config,
    resolve_token,
)
from .logging_setup import get_logger, setup_logging
from .models import MediaKind
from .services.images import ImageService
from .services.processor import Processor
from .services.scanner import discover_media
from .services.tmdb import TMDBClient


def _quality_value(text: str) -> int:
    """قابل لـ--quality: يرفض فوراً أي قيمة خارج النطاق (لا قصّ صامت)."""
    try:
        value = int(text)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError(
            "جودة الصور يجب أن تكون عدداً صحيحاً بين "
            f"{MIN_JPEG_QUALITY} و {MAX_JPEG_QUALITY}."
        ) from None
    if not (MIN_JPEG_QUALITY <= value <= MAX_JPEG_QUALITY):
        raise argparse.ArgumentTypeError(
            f"جودة الصور يجب أن تكون بين {MIN_JPEG_QUALITY} و {MAX_JPEG_QUALITY}."
        )
    return value


def _images_value(text: str) -> tuple[str, ...]:
    """قابل لـ--images: CSV من أنواع الصور، و"" تعني لا صور إطلاقاً."""
    tokens = [
        token.strip().lower()
        for token in (text or "").split(",")
        if token.strip()
    ]
    unknown = [token for token in tokens if token not in IMAGE_TYPES]
    if unknown:
        raise argparse.ArgumentTypeError(
            "أنواع الصور يجب أن تكون من: " + "، ".join(IMAGE_TYPES) + "."
        )
    return tuple(dict.fromkeys(tokens))


def _max_workers_value(text: str) -> int:
    """قابل لـ--max-workers: يرفض فوراً أي قيمة خارج 1–8."""
    try:
        value = int(text)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError(
            f"عدد المهام المتوازية يجب أن يكون عدداً صحيحاً بين {MIN_MAX_WORKERS} "
            f"و {MAX_MAX_WORKERS}."
        ) from None
    if not (MIN_MAX_WORKERS <= value <= MAX_MAX_WORKERS):
        raise argparse.ArgumentTypeError(
            f"عدد المهام المتوازية يجب أن يكون بين {MIN_MAX_WORKERS} "
            f"و {MAX_MAX_WORKERS}."
        )
    return value


@contextmanager
def _sigint_cancellation(event: threading.Event):
    """حوّل Ctrl+C إلى طلب إلغاء تعاوني بدل استثناء في منتصف الكتابة."""
    try:
        previous = signal.signal(signal.SIGINT, lambda _signum, _frame: event.set())
    except (ValueError, OSError):  # ليس الخيط الرئيسي: يبقى KeyboardInterrupt
        previous = None
    try:
        yield
    finally:
        if previous is not None:
            try:
                signal.signal(signal.SIGINT, previous)
            except (ValueError, OSError):  # pragma: no cover - defensive
                pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mediaart",
        description="MediaArt Auto-Sync — تنزيل الملصقات والخلفيات من TMDB (وضع سطر الأوامر).",
        epilog=(
            "أكواد الخروج: 0 = نجاح كامل، 1 = أخطاء أثناء العمل، "
            "2 = إعداد غير صالح، 3 = عناصر غير موجودة (مع --fail-on-not-found فقط)."
        ),
    )
    parser.add_argument("--cli", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("-p", "--path", help="مجلد المكتبة الجذري.")
    parser.add_argument(
        "--output-root",
        help=(
            "مجلد إخراج بديل للصور (للمكتبات للقراءة فقط، مثل مجلدات NAS): "
            "يُعاد إنشاء المسار النسبي من جذر المكتبة بداخله."
        ),
    )
    parser.add_argument("-t", "--token", help="مفتاح TMDB v3 أو v4 (يفضل متغير البيئة TMDB_API_KEY).")
    parser.add_argument("--language", help="لغة البيانات والصور، مثل ar أو en.")
    parser.add_argument(
        "--quality",
        type=_quality_value,
        help=f"جودة JPG من {MIN_JPEG_QUALITY} إلى {MAX_JPEG_QUALITY} (افتراضي 95).",
    )
    parser.add_argument("--media", choices=[key for key, _ in MEDIA_FILTERS], help="نوع الوسائط.")
    parser.add_argument("--limit", type=int, help="معالجة أول N عنصر فقط (للتجربة).")
    parser.add_argument("--overwrite", action="store_true", help="استبدال الصور الموجودة.")
    parser.add_argument("--dry-run", action="store_true", help="بحث فقط بدون تنزيل أو تحويل.")
    parser.add_argument("--convert-only", action="store_true", help="تحويل WebP إلى JPG فقط بدون TMDB.")
    parser.add_argument("--no-cache", action="store_true", help="تعطيل كاش TMDB لهذه الجلسة.")
    parser.add_argument(
        "--images",
        type=_images_value,
        metavar="poster,fanart,background",
        help=(
            "أنواع الصور المراد تنزيلها كقائمة CSV (الافتراضي من الإعدادات: "
            "poster). اتركها فارغة (--images \"\") لتعطيل كل الصور."
        ),
    )
    parser.add_argument(
        "--max-workers",
        type=_max_workers_value,
        help=(
            f"عدد المهام المتوازية ({MIN_MAX_WORKERS}–{MAX_MAX_WORKERS}، "
            f"الافتراضي {DEFAULT_MAX_WORKERS}؛ 1 = تسلسلي تماماً)."
        ),
    )
    parser.add_argument(
        "--fail-on-not-found",
        action="store_true",
        help="إنهاء التشغيل برمز 3 إذا وُجد عنصر غير موجود في TMDB (الافتراضي: رمز 0).",
    )
    parser.add_argument(
        "--refresh-negatives",
        action="store_true",
        help="تجاهل الكاش السلبي وأعد البحث عن العناصر غير الموجودة في TMDB.",
    )
    parser.add_argument(
        "--poster-size",
        choices=list(POSTER_SIZES),
        help="حجم الملصق المطلوب من TMDB (original = الدقة الكاملة وحجمها أكبر بعشر مرات).",
    )
    parser.add_argument(
        "--backdrop-size",
        choices=list(BACKDROP_SIZES),
        help="حجم الخلفية المطلوبة من TMDB (original = الدقة الكاملة وحجمها أكبر بعشر مرات).",
    )
    parser.add_argument(
        "--localized-artwork",
        action="store_true",
        help="جلب صور باللغة المختارة بدل الافتراضية (يرفع عدد الطلبات بنحو 50%%).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="سجل تفصيلي.",
    )
    parser.add_argument("--version", action="version", version=VERSION)
    return parser


def run_cli(args: argparse.Namespace) -> int:
    config = load_config()

    if args.path:
        config.library_path = args.path
    cli_token = (args.token or "").strip()
    if cli_token:
        config.tmdb_api_key = cli_token
    if args.language:
        config.language = args.language
    if args.quality is not None:
        config.jpeg_quality = args.quality
    if args.media:
        config.media_filter = args.media
    if args.poster_size:
        config.poster_size = args.poster_size
    if args.backdrop_size:
        config.backdrop_size = args.backdrop_size
    config.overwrite_images = bool(args.overwrite or config.overwrite_images)
    config.prefer_localized_artwork = bool(
        args.localized_artwork or config.prefer_localized_artwork
    )
    config.dry_run = bool(args.dry_run)
    config.convert_only = bool(args.convert_only)
    config.use_cache = not args.no_cache
    if args.max_workers is not None:
        config.max_workers = args.max_workers
    if args.images is not None:
        selected = set(args.images)
        config.download_poster = "poster" in selected
        config.download_fanart = "fanart" in selected
        config.download_background = "background" in selected

    setup_logging(console=True, level=logging.DEBUG if args.verbose else logging.INFO)
    logger = get_logger("cli")

    if args.output_root:
        try:
            config.output_root = str(ensure_output_root(args.output_root))
        except ValueError as exc:
            logger.error("%s", exc)
            return 2
    root = Path(config.library_path).expanduser() if config.library_path else None
    if root is None or not root.is_dir():
        logger.error("مسار المكتبة غير صالح. استخدم --path أو احفظ المسار من الواجهة.")
        return 2

    token = resolve_token(config, cli_token or None)
    if not config.convert_only and not token:
        logger.error("مفتاح TMDB مطلوب. استخدم --token أو متغير TMDB_API_KEY.")
        return 2

    logger.info("MediaArt Auto-Sync v%s", VERSION)
    logger.info("المكتبة: %s", root)
    if config.output_root:
        logger.info("مجلد الإخراج: %s", config.output_root)
    logger.info(
        "الوضع: %s | اللغة: %s | النوع: %s",
        "تحويل WebP فقط" if config.convert_only else ("معاينة" if config.dry_run else "تنزيل كامل"),
        config.language,
        config.media_filter,
    )

    cancel_event = threading.Event()
    try:
        with _sigint_cancellation(cancel_event):
            return _run_library(config, args, root, token, cancel_event)
    except KeyboardInterrupt:
        # SIGINT قبل تركيب المعالج (أو في خيط غير رئيسي).
        logger.warning("تم الإلغاء بواسطة المستخدم.")
        return 130


def _run_library(
    config: AppConfig,
    args: argparse.Namespace,
    root: Path,
    token: str,
    cancel_event: threading.Event,
) -> int:
    logger = get_logger("cli")
    try:
        items = discover_media(
            root, config.media_filter, should_cancel=cancel_event.is_set
        )
    except OSError as exc:
        logger.error("تعذر فحص المكتبة: %s", exc)
        return 2

    if cancel_event.is_set():
        logger.warning("تم الإلغاء بواسطة المستخدم. 0 عنصر مُعالَج قبل الإلغاء.")
        return 130

    if args.limit and args.limit > 0:
        items = items[: args.limit]
    if not items:
        logger.warning("لم يتم العثور على مجلدات أفلام أو مسلسلات قابلة للمعالجة.")
        return 0

    client: TMDBClient | None = None
    processor: Processor | None = None
    try:
        if not config.convert_only:
            client = TMDBClient(
                token,
                language=config.language,
                timeout=config.request_timeout,
                min_interval=config.min_request_interval,
                max_retries=config.max_retries,
                use_cache=config.use_cache,
                cache_ttl_days=config.cache_ttl_days,
                prefer_localized_artwork=config.prefer_localized_artwork,
                negative_cache_ttl_days=config.negative_cache_ttl_days,
                refresh_negatives=bool(args.refresh_negatives),
                poster_size=config.poster_size,
                backdrop_size=config.backdrop_size,
            )
        images = ImageService(quality=config.jpeg_quality, timeout=config.request_timeout)
        processor = Processor(config, client=client, images=images)

        def on_progress(done: int, total: int, title: str) -> None:
            if done:
                logger.info("[%d/%d] %s", done, total, title)

        summary = processor.run(
            items,
            should_cancel=cancel_event.is_set,
            on_progress=on_progress,
        )
    finally:
        if processor:
            processor.close()
        elif client:
            client.close()

    print()
    print("=" * 60)
    print(summary.summary_text())
    print("=" * 60)
    if summary.total and summary.results:
        print("\nالتفاصيل:")
        for result in summary.results:
            print(
                f"- [{result.status.label_ar}] {result.item.title}"
                f" ({result.item.kind.label_ar}) — {result.message}"
            )
    if summary.cancelled or cancel_event.is_set():
        logger.warning(
            "تم الإلغاء بواسطة المستخدم. %d عنصر مُعالَج قبل الإلغاء.",
            len(summary.results),
        )
        return 130
    if summary.errors:
        return 1
    if getattr(args, "fail_on_not_found", False) and summary.not_found:
        return 3
    return 0


def cli_main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return run_cli(args)
    except Exception:
        get_logger("cli").exception("فشل غير متوقع في سطر الأوامر")
        return 1


__all__ = ["build_parser", "run_cli", "cli_main", "MediaKind"]
