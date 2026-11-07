"""Headless command line mode (useful for NAS sync jobs and AI agents)."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .config import (
    MEDIA_FILTERS,
    AppConfig,
    VERSION,
    load_config,
    resolve_token,
)
from .logging_setup import get_logger, setup_logging
from .models import MediaKind
from .services.images import ImageService
from .services.processor import Processor
from .services.scanner import discover_media
from .services.tmdb import TMDBClient


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mediaart",
        description="MediaArt Auto-Sync — تنزيل الملصقات والخلفيات من TMDB (وضع سطر الأوامر).",
    )
    parser.add_argument("--cli", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("-p", "--path", help="مجلد المكتبة الجذري.")
    parser.add_argument("-t", "--token", help="مفتاح TMDB v3 أو v4 (يفضل متغير البيئة TMDB_API_KEY).")
    parser.add_argument("--language", help="لغة البيانات والصور، مثل ar أو en.")
    parser.add_argument("--quality", type=int, help="جودة JPG من 60 إلى 100 (افتراضي 95).")
    parser.add_argument("--media", choices=[key for key, _ in MEDIA_FILTERS], help="نوع الوسائط.")
    parser.add_argument("--limit", type=int, help="معالجة أول N عنصر فقط (للتجربة).")
    parser.add_argument("--overwrite", action="store_true", help="استبدال الصور الموجودة.")
    parser.add_argument("--dry-run", action="store_true", help="بحث فقط بدون تنزيل أو تحويل.")
    parser.add_argument("--convert-only", action="store_true", help="تحويل WebP إلى JPG فقط بدون TMDB.")
    parser.add_argument("--no-cache", action="store_true", help="تعطيل كاش TMDB لهذه الجلسة.")
    parser.add_argument("--verbose", action="store_true", help="سجل تفصيلي.")
    parser.add_argument("--version", action="version", version=VERSION)
    return parser


def run_cli(args: argparse.Namespace) -> int:
    config = load_config()

    if args.path:
        config.library_path = args.path
    if args.token:
        config.tmdb_api_key = args.token
    if args.language:
        config.language = args.language
    if args.quality is not None:
        config.jpeg_quality = args.quality
    if args.media:
        config.media_filter = args.media
    config.overwrite_images = bool(args.overwrite or config.overwrite_images)
    config.dry_run = bool(args.dry_run)
    config.convert_only = bool(args.convert_only)
    config.use_cache = not args.no_cache

    setup_logging(console=True, level=logging.DEBUG if args.verbose else logging.INFO)
    logger = get_logger("cli")

    root = Path(config.library_path).expanduser() if config.library_path else None
    if root is None or not root.is_dir():
        logger.error("مسار المكتبة غير صالح. استخدم --path أو احفظ المسار من الواجهة.")
        return 2

    token = resolve_token(config)
    if not config.convert_only and not token:
        logger.error("مفتاح TMDB مطلوب. استخدم --token أو متغير TMDB_API_KEY.")
        return 2

    logger.info("MediaArt Auto-Sync v%s", VERSION)
    logger.info("المكتبة: %s", root)
    logger.info(
        "الوضع: %s | اللغة: %s | النوع: %s",
        "تحويل WebP فقط" if config.convert_only else ("معاينة" if config.dry_run else "تنزيل كامل"),
        config.language,
        config.media_filter,
    )

    try:
        items = discover_media(root, config.media_filter)
    except OSError as exc:
        logger.error("تعذر فحص المكتبة: %s", exc)
        return 2

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
            )
        images = ImageService(quality=config.jpeg_quality, timeout=config.request_timeout)
        processor = Processor(config, client=client, images=images)

        def on_progress(done: int, total: int, title: str) -> None:
            if done:
                logger.info("[%d/%d] %s", done, total, title)

        summary = processor.run(items, on_progress=on_progress)
    except KeyboardInterrupt:
        logger.warning("تم الإلغاء بواسطة المستخدم.")
        return 130
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
    return 1 if summary.errors else 0


def cli_main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return run_cli(args)
    except Exception:
        get_logger("cli").exception("فشل غير متوقع في سطر الأوامر")
        return 1


__all__ = ["build_parser", "run_cli", "cli_main", "MediaKind"]
