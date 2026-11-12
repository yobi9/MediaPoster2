"""اختبارات وضع سطر الأوامر: رموز الخروج و--fail-on-not-found (P14/A8).

كل الاختبارات بلا شبكة حقيقية: تُستبدل discover_media وTMDBClient وProcessor
ببدائل محلية.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app import cli
from app.config import AppConfig
from app.models import ItemResult, MediaItem, MediaKind, RunSummary, Status


class FakeProcessor:
    """يعيد ملخّصاً جاهزاً بدل تنفيذ حقيقي."""

    def __init__(self, summary: RunSummary) -> None:
        self.summary = summary

    def run(self, items, **kwargs) -> RunSummary:  # noqa: ANN001, ANN003
        return self.summary

    def close(self) -> None:
        pass


class FakeClient:
    def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        pass

    def close(self) -> None:
        pass


def make_summary(folder: Path, *statuses: Status) -> RunSummary:
    item = MediaItem(path=folder, kind=MediaKind.MOVIE, title="عنصر", year=2020)
    results = [
        ItemResult(item=item, status=status, message="اختبار") for status in statuses
    ]
    return RunSummary(total=len(results), results=results)


def run_with(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *statuses: Status,
    extra_args: tuple[str, ...] = (),
) -> int:
    library = tmp_path / "Library"
    library.mkdir(parents=True, exist_ok=True)
    item_folder = library / "Movie"
    item_folder.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(cli, "load_config", lambda: AppConfig(library_path=str(library)))
    monkeypatch.setattr(
        cli,
        "discover_media",
        lambda root, media_filter="all": [
            MediaItem(path=item_folder, kind=MediaKind.MOVIE, title="عنصر", year=2020)
        ],
    )
    monkeypatch.setattr(cli, "TMDBClient", FakeClient)
    monkeypatch.setattr(
        cli, "Processor", lambda config, client=None, images=None: FakeProcessor(
            make_summary(item_folder, *statuses)
        )
    )
    monkeypatch.setenv("TMDB_API_KEY", "TESTTOKEN")

    args = cli.build_parser().parse_args(
        ["--cli", "--path", str(library), *extra_args]
    )
    return cli.run_cli(args)


def test_success_returns_zero(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """E1: كل العناصر ناجحة ⇒ رمز 0."""
    assert run_with(monkeypatch, tmp_path, Status.OK, Status.OK) == 0


def test_error_returns_one(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """E2: خطأ فعلي ⇒ رمز 1."""
    assert run_with(monkeypatch, tmp_path, Status.OK, Status.ERROR) == 1


def test_not_found_without_flag_returns_zero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """E3: NOT_FOUND بلا --fail-on-not-found ⇒ رمز 0 (توافق خلفي)."""
    assert run_with(monkeypatch, tmp_path, Status.NOT_FOUND) == 0


def test_not_found_with_flag_returns_three(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """E4: NOT_FOUND مع --fail-on-not-found ⇒ رمز 3."""
    assert (
        run_with(
            monkeypatch,
            tmp_path,
            Status.OK,
            Status.NOT_FOUND,
            extra_args=("--fail-on-not-found",),
        )
        == 3
    )


def test_errors_take_precedence_over_not_found(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """E5: خطأ + NOT_FOUND مع الـflag ⇒ رمز 1 (الأخطاء تتفوّق)."""
    assert (
        run_with(
            monkeypatch,
            tmp_path,
            Status.ERROR,
            Status.NOT_FOUND,
            extra_args=("--fail-on-not-found",),
        )
        == 1
    )


def test_help_documents_exit_codes() -> None:
    """E6: --help يوضّح رموز الخروج ومنها 3."""
    help_text = cli.build_parser().format_help()

    assert "أكواد الخروج" in help_text
    assert "3" in help_text
    assert "غير موجودة" in help_text
    assert "--fail-on-not-found" in help_text


def test_flag_is_optional(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """القيمة الافتراضية للسمة false (توافق خلفي)."""
    args = cli.build_parser().parse_args(["--cli"])
    assert args.fail_on_not_found is False
