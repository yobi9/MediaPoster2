"""Application entry point: GUI by default, CLI with ``--cli``."""

from __future__ import annotations

import sys

from .config import APP_NAME, VERSION


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass

    if "--cli" in args or "-h" in args or "--help" in args or "--version" in args:
        from .cli import cli_main

        return cli_main(args + ["--cli"] if "--cli" not in args else args)

    return launch_gui()


def launch_gui() -> int:
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QFont
    from PyQt6.QtWidgets import QApplication, QMessageBox

    from .logging_setup import get_logger, setup_logging
    from .ui.main_window import MainWindow
    from .ui.theme import STYLESHEET, make_app_icon

    setup_logging(console=True)
    logger = get_logger("app")

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(VERSION)
    app.setOrganizationName("MediaArt")
    app.setStyle("Fusion")
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    app.setFont(QFont("Segoe UI", 10))
    app.setStyleSheet(STYLESHEET)
    app.setWindowIcon(make_app_icon())

    def _excepthook(exc_type, exc_value, exc_tb):  # type: ignore[no-untyped-def]
        logger.exception("استثناء غير معالج", exc_info=(exc_type, exc_value, exc_tb))
        try:
            QMessageBox.critical(
                None,
                "خطأ غير متوقع",
                f"حدث خطأ غير متوقع:\n{exc_value}\n\nراجع ملف السجل للمزيد من التفاصيل.",
            )
        except Exception:  # pragma: no cover - the app is already failing
            pass

    sys.excepthook = _excepthook

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
