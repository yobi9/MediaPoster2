"""اختبارات وضع سطر الأوامر: رموز الخروج و--fail-on-not-found (P14/A8).

كل الاختبارات بلا شبكة حقيقية: تُستبدل discover_media وTMDBClient وProcessor
ببدائل محلية.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

from app import cli
from app.config import AppConfig
from app.models import ItemResult, MediaItem, MediaKind, RunSummary, Status

REPO_ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def _collect_cli_records():
    """التقط سجلات logger "mediaart.cli" (mediaart.propagate=False)."""
    logger = logging.getLogger("mediaart.cli")
    records: list[logging.LogRecord] = []

    class Collector(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = Collector()
    logger.addHandler(handler)
    try:
        yield records
    finally:
        logger.removeHandler(handler)


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
    client_cls=None,
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
    monkeypatch.setattr(cli, "TMDBClient", client_cls or FakeClient)
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


def run_and_capture_config(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *extra_args: str,
) -> tuple[int, AppConfig]:
    """نفّذ run_cli وأعد رمز الخروج مع كائن الإعدادات بعد معالجته."""
    library = tmp_path / "Library"
    library.mkdir(parents=True, exist_ok=True)
    item_folder = library / "Movie"
    item_folder.mkdir(parents=True, exist_ok=True)

    captured: dict[str, AppConfig] = {}

    def fake_load_config() -> AppConfig:
        config = AppConfig(library_path=str(library))
        captured["config"] = config
        return config

    monkeypatch.setattr(cli, "load_config", fake_load_config)
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
            make_summary(item_folder, Status.OK)
        )
    )
    monkeypatch.setenv("TMDB_API_KEY", "TESTTOKEN")

    args = cli.build_parser().parse_args(
        ["--cli", "--path", str(library), *extra_args]
    )
    code = cli.run_cli(args)
    return code, captured["config"]


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


# ---------------------------------------------------------------------------
# --quality: تحقق فوري (D6)
# ---------------------------------------------------------------------------
def test_quality_above_range_is_rejected(capsys: pytest.CaptureFixture[str]) -> None:
    """Q1: --quality 500 ⇒ parser.error (خروج 2) مع رسالة عربية واضحة."""
    with pytest.raises(SystemExit) as excinfo:
        cli.build_parser().parse_args(["--cli", "--quality", "500"])

    assert excinfo.value.code == 2
    captured = capsys.readouterr()
    assert "جودة الصور يجب أن تكون بين 60 و 100" in captured.err


def test_quality_below_range_is_rejected(capsys: pytest.CaptureFixture[str]) -> None:
    """Q2: --quality 0 ⇒ parser.error (خروج 2)."""
    with pytest.raises(SystemExit) as excinfo:
        cli.build_parser().parse_args(["--cli", "--quality", "0"])

    assert excinfo.value.code == 2
    assert "جودة الصور يجب أن تكون بين 60 و 100" in capsys.readouterr().err


def test_valid_quality_is_accepted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Q3: --quality 95 ⇒ لا خطأ، والقيمة تصل إلى AppConfig."""
    code, config = run_and_capture_config(
        monkeypatch, tmp_path, "--quality", "95"
    )

    assert code == 0
    assert config.jpeg_quality == 95


def test_quality_upper_bound_is_accepted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Q4: --quality 100 (الحد العلوي) و92 ⇒ لا خطأ."""
    code, config = run_and_capture_config(
        monkeypatch, tmp_path, "--quality", "100"
    )
    assert code == 0
    assert config.jpeg_quality == 100

    code, config = run_and_capture_config(monkeypatch, tmp_path, "--quality", "92")
    assert code == 0
    assert config.jpeg_quality == 92


def test_quality_default_is_95(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Q5: بلا --quality ⇒ القيمة الافتراضية 95."""
    code, config = run_and_capture_config(monkeypatch, tmp_path)

    assert code == 0
    assert config.jpeg_quality == 95


# ---------------------------------------------------------------------------
# أحجام الصور (A1)
# ---------------------------------------------------------------------------
def test_poster_size_option_reaches_the_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A1-5: --poster-size w342 ⇒ AppConfig.poster_size = w342."""
    code, config = run_and_capture_config(
        monkeypatch, tmp_path, "--poster-size", "w342"
    )

    assert code == 0
    assert config.poster_size == "w342"


def test_poster_size_option_rejects_unknown_value(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A1-6: --poster-size bogus ⇒ parser.error (خروج 2)."""
    with pytest.raises(SystemExit) as excinfo:
        cli.build_parser().parse_args(["--cli", "--poster-size", "bogus"])

    assert excinfo.value.code == 2
    assert "poster-size" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# --localized-artwork (A3)
# ---------------------------------------------------------------------------
def test_localized_artwork_flag_enables_the_option(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A3-5: --localized-artwork ⇒ prefer_localized_artwork = True."""
    code, config = run_and_capture_config(
        monkeypatch, tmp_path, "--localized-artwork"
    )

    assert code == 0
    assert config.prefer_localized_artwork is True


def test_localized_artwork_is_disabled_by_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """بلا flag ⇒ يبقى False (سلوك أقل طلبات)."""
    code, config = run_and_capture_config(monkeypatch, tmp_path)

    assert code == 0
    assert config.prefer_localized_artwork is False


def test_localized_artwork_reaches_the_client(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A3-6 (تكامل): الخيار يصل إلى TMDBClient فيُفعّل Enrich."""
    recorded: dict[str, object] = {}

    class RecordingClient(FakeClient):
        def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
            recorded.update(kwargs)
            super().__init__()

    run_with(
        monkeypatch,
        tmp_path,
        Status.OK,
        extra_args=("--localized-artwork",),
        client_cls=RecordingClient,
    )

    assert recorded.get("prefer_localized_artwork") is True


# ---------------------------------------------------------------------------
# --refresh-negatives (A2 / N6)
# ---------------------------------------------------------------------------
def test_refresh_negatives_reaches_the_client(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """N6: --refresh-negatives يُمرَّر إلى TMDBClient."""
    recorded: dict[str, object] = {}

    class RecordingClient(FakeClient):
        def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
            recorded.update(kwargs)
            super().__init__()

    monkeypatch.setattr(cli, "TMDBClient", RecordingClient)
    run_with(
        monkeypatch,
        tmp_path,
        Status.OK,
        extra_args=("--refresh-negatives",),
        client_cls=RecordingClient,
    )

    assert recorded.get("refresh_negatives") is True


def test_refresh_negatives_is_off_by_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """بلا flag ⇒ refresh_negatives=False."""
    recorded: dict[str, object] = {}

    class RecordingClient(FakeClient):
        def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
            recorded.update(kwargs)
            super().__init__()

    monkeypatch.setattr(cli, "TMDBClient", RecordingClient)
    run_with(monkeypatch, tmp_path, Status.OK, client_cls=RecordingClient)

    assert recorded.get("refresh_negatives") is False


# ---------------------------------------------------------------------------
# نقطة الدخول python -m app (P1 / B1-B4)
# ---------------------------------------------------------------------------
def _run_module(*args: str, data_dir: Path | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    if data_dir is not None:
        env["MEDIAART_DATA_DIR"] = str(data_dir)
    return subprocess.run(
        [sys.executable, "-m", "app", *args],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )


def test_module_help_exits_zero_and_lists_options(tmp_path: Path) -> None:
    """B1: python -m app --cli --help ⇒ خرج 0 مع ذكر الخيارات."""
    result = _run_module("--cli", "--help", data_dir=tmp_path)

    assert result.returncode == 0
    assert "--path" in result.stdout
    assert "--token" in result.stdout


def test_module_help_writes_nothing_to_stderr(tmp_path: Path) -> None:
    """B2: لا traceback ولا أخطاء على stderr."""
    result = _run_module("--cli", "--help", data_dir=tmp_path)

    assert result.stderr.strip() == ""
    assert "Traceback" not in result.stdout


def test_module_without_path_fails_with_arabic_message(tmp_path: Path) -> None:
    """B3: python -m app --cli بلا مسار ⇒ خرج غير صفري برسالة عربية."""
    result = _run_module("--cli", data_dir=tmp_path)

    assert result.returncode != 0
    assert "Traceback" not in result.stderr
    assert "Traceback" not in result.stdout
    assert "مسار المكتبة" in (result.stderr + result.stdout)


def test_main_routes_to_gui_without_cli_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B4: main.main() بلا --cli ⇒ يطلق launch_gui (بلا نافذة فعلية)."""
    from app import main as app_main

    called: list[bool] = []

    def fake_launch_gui() -> int:
        called.append(True)
        return 0

    monkeypatch.setattr(app_main, "launch_gui", fake_launch_gui)
    monkeypatch.setattr(sys, "argv", ["prog"])

    assert app_main.main() == 0
    assert called == [True]


# ---------------------------------------------------------------------------
# تغطية cli_main / main.main / __main__ (D7)
# ---------------------------------------------------------------------------
def test_cli_main_help_exits_zero() -> None:
    """F1: cli_main(['--help']) ⇒ خرج 0 (argparse يطبع المساعدة)."""
    with pytest.raises(SystemExit) as excinfo:
        cli.cli_main(["--help"])

    assert excinfo.value.code == 0


def test_cli_main_with_missing_path_reports_arabic_error(tmp_path: Path) -> None:
    """F2: مسار غير موجود ⇒ رسالة عربية واضحة بلا traceback."""
    missing = tmp_path / "nope" / "missing"

    with _collect_cli_records() as records:
        code = cli.cli_main(["--cli", "--path", str(missing)])

    assert code == 2
    errors = [r.getMessage() for r in records if r.levelno >= logging.ERROR]
    assert any("مسار المكتبة" in message for message in errors)
    assert not any("Traceback" in message for message in errors)


def test_cli_main_accepts_repeated_cli_flag(tmp_path: Path) -> None:
    """F3: --cli مرتين ⇒ argparse يقبله (store_true) والسلوك واحد."""
    args = cli.build_parser().parse_args(["--cli", "--cli"])
    assert args.cli is True

    missing = tmp_path / "missing-library"

    with _collect_cli_records() as records:
        code = cli.cli_main(["--cli", "--cli", "--path", str(missing)])

    assert code == 2
    assert not any("Traceback" in r.getMessage() for r in records)


def test_main_routes_to_cli_with_cli_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F4: main.main() مع --cli ⇒ يستدعي cli_main (بلا تنفيذ حقيقي)."""
    from app import main as app_main

    recorded: list[list[str]] = []

    def fake_cli_main(argv: list[str]) -> int:
        recorded.append(list(argv))
        return 0

    monkeypatch.setattr("app.cli.cli_main", fake_cli_main)
    monkeypatch.setattr(sys, "argv", ["prog", "--cli", "--path", "X"])

    assert app_main.main() == 0
    assert recorded and "--cli" in recorded[0]


def test_module_entry_point_matches_main(
    tmp_path: Path,
) -> None:
    """F6: `python -m app` (أي __main__.py) يمرّ عبر main.main()."""
    source = (REPO_ROOT / "app" / "__main__.py").read_text(encoding="utf-8")

    assert "from .main import main" in source
    assert "raise SystemExit(main())" in source

    # والتحقق الفعلي: نفس التوجيه عبر python -m app
    result = _run_module("--cli", "--help", data_dir=tmp_path)
    assert result.returncode == 0
    assert "--path" in result.stdout


def test_cli_main_converts_unexpected_errors_to_exit_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F7: استثناء غير متوقع داخل cli_main ⇒ رمز 1 بلا traceback."""
    def boom(*args, **kwargs) -> int:  # noqa: ANN002, ANN003
        raise RuntimeError("فشل غير متوقع")

    monkeypatch.setattr(cli, "run_cli", boom)

    assert cli.cli_main(["--cli"]) == 1


# ---------------------------------------------------------------------------
# --output-root (B2/P13)
# ---------------------------------------------------------------------------
def test_output_root_option_reaches_the_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """B2-8: --output-root PATH ⇒ AppConfig.output_root ومجلد قابل للكتابة."""
    output = tmp_path / "artwork"

    code, config = run_and_capture_config(
        monkeypatch, tmp_path, "--output-root", str(output)
    )

    assert code == 0
    assert Path(config.output_root).name == "artwork"
    assert output.is_dir()


def test_output_root_option_rejects_unwritable_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """B2-9: مسار إخراج غير قابل للإنشاء ⇒ خروج 2 برسالة عربية."""
    blocker = tmp_path / "blocked"
    blocker.write_text("ليس مجلداً", encoding="utf-8")

    code, _config = run_and_capture_config(
        monkeypatch, tmp_path, "--output-root", str(blocker / "artwork")
    )

    assert code == 2
