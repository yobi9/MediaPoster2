"""Dark, modern Qt stylesheet and programmatically drawn app icon."""

from __future__ import annotations

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QIcon,
    QLinearGradient,
    QPainter,
    QPixmap,
)

from ..models import Status

ACCENT = "#6D5EF9"
ACCENT_HOVER = "#7F72FF"
BACKGROUND = "#0E1016"
CARD = "#151923"
BORDER = "#242B39"
TEXT = "#E7EAF3"
MUTED = "#A3ADC2"

STATUS_COLORS: dict[Status, str] = {
    Status.OK: "#4ADE80",
    Status.PARTIAL: "#FBBF24",
    Status.SKIPPED: "#94A3B8",
    Status.NOT_FOUND: "#FB923C",
    Status.ERROR: "#F87171",
    Status.CANCELLED: "#94A3B8",
    Status.PREVIEW: "#A78BFA",
}

LEVEL_COLORS: dict[str, str] = {
    "DEBUG": "#6B7280",
    "INFO": "#B6C0D4",
    "SUCCESS": "#4ADE80",
    "WARNING": "#FBBF24",
    "ERROR": "#F87171",
    "CRITICAL": "#F87171",
}


STYLESHEET = """
* {
    outline: none;
}
QMainWindow, QWidget#Root {
    background-color: #0E1016;
}
QWidget {
    color: #E7EAF3;
    font-family: "Segoe UI";
    font-size: 10pt;
}
QToolTip {
    background-color: #1D2330;
    color: #E7EAF3;
    border: 1px solid #2C3445;
    border-radius: 6px;
    padding: 6px;
}
QFrame#Card {
    background-color: #151923;
    border: 1px solid #242B39;
    border-radius: 14px;
}
QFrame#StatBox {
    background-color: #10141C;
    border: 1px solid #222A38;
    border-radius: 10px;
}
QLabel#AppTitle {
    font-size: 19pt;
    font-weight: 700;
    color: #F4F6FB;
}
QLabel#Subtitle {
    color: #A3ADC2;
    font-size: 9.5pt;
}
QLabel#CardTitle {
    font-size: 11.5pt;
    font-weight: 600;
    color: #EEF1F8;
}
QLabel#Muted {
    color: #A3ADC2;
}
QLabel#FieldLabel {
    color: #B9C1D3;
    font-weight: 500;
}
QLabel#StatusLabel {
    color: #C8D0E0;
    font-size: 10pt;
}
QLabel#StatValue {
    font-size: 17pt;
    font-weight: 700;
}
QLabel#StatCaption {
    color: #9AA3B8;
    font-size: 9.5pt;
}
QLabel#Logo {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #6D5EF9, stop:1 #38BDF8);
    color: #FFFFFF;
    border-radius: 13px;
    font-size: 22pt;
    font-weight: 800;
}
QLabel#Badge {
    background-color: #1C2333;
    border: 1px solid #2C3445;
    border-radius: 10px;
    color: #AEB6CB;
    font-size: 9pt;
    padding: 6px 12px;
}
QLineEdit, QComboBox {
    background-color: #0F131B;
    border: 1px solid #2A3140;
    border-radius: 8px;
    padding: 8px 10px;
    selection-background-color: #6D5EF9;
    color: #E7EAF3;
    min-height: 22px;
}
QLineEdit:focus, QComboBox:focus, QPushButton:focus {
    border: 2px solid #6D5EF9;
}
QLineEdit:disabled, QComboBox:disabled {
    color: #8B93A7;
    background-color: #12161F;
    border-color: #1E2430;
}
QLineEdit::placeholder {
    color: #8B93A7;
}
QComboBox::drop-down {
    border: none;
    width: 24px;
}
QComboBox::down-arrow {
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid #A3ADC2;
    margin-right: 8px;
}
QComboBox QAbstractItemView {
    background-color: #171C27;
    border: 1px solid #2A3140;
    border-radius: 8px;
    selection-background-color: #6D5EF9;
    selection-color: #FFFFFF;
    padding: 4px;
    outline: none;
}
QPushButton {
    background-color: #1D2330;
    border: 1px solid #2C3445;
    border-radius: 8px;
    padding: 10px 16px;
    min-height: 28px;
    color: #DDE3EF;
    font-weight: 500;
}
QPushButton:hover {
    background-color: #252D3D;
    border-color: #3A4459;
}
QPushButton:pressed {
    background-color: #171C27;
}
QPushButton:disabled {
    background-color: #141922;
    border-color: #1F2634;
    color: #7A8296;
}
QPushButton#Primary {
    background-color: #6D5EF9;
    border: none;
    color: #FFFFFF;
    font-weight: 600;
    padding: 11px 24px;
    min-height: 32px;
}
QPushButton#Primary:hover {
    background-color: #7F72FF;
}
QPushButton#Primary:disabled {
    background-color: #322F55;
    color: #8A86A8;
}
QPushButton#Danger {
    background-color: #3A1D26;
    border: 1px solid #6B2C3C;
    color: #FF9AAE;
    padding: 11px 20px;
    min-height: 32px;
}
QPushButton#Danger:hover {
    background-color: #4A2430;
}
QPushButton#Danger:disabled {
    background-color: #1B1418;
    border-color: #2A1C22;
    color: #6B4A52;
}
QPushButton#Chip {
    background-color: #121722;
    border: 1px solid #283041;
    border-radius: 14px;
    padding: 8px 14px;
    min-height: 26px;
    color: #AEB6CB;
    font-size: 9.5pt;
}
QPushButton#Chip:hover {
    border-color: #3A4459;
    color: #C9D1E0;
}
QPushButton#Chip:checked {
    background-color: #241F4A;
    border-color: #6D5EF9;
    color: #CFC8FF;
}
QPushButton#Chip:disabled {
    color: #7A8296;
    border-color: #232A38;
}
QPushButton#LinkButton {
    background: transparent;
    border: none;
    color: #A79CFF;
    padding: 8px 10px;
    min-height: 24px;
}
QPushButton#LinkButton:hover {
    color: #B8B2FF;
}
QPushButton#Ghost {
    background-color: transparent;
    border: 1px solid #283041;
    color: #BCC4D6;
    padding: 9px 14px;
    min-height: 28px;
    font-size: 9.5pt;
}
QPushButton#Ghost:hover {
    background-color: #1A2130;
}
QProgressBar {
    background-color: #0F131B;
    border: 1px solid #232A38;
    border-radius: 8px;
    min-height: 16px;
    max-height: 16px;
    text-align: center;
    color: transparent;
}
QProgressBar::chunk {
    border-radius: 8px;
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #6D5EF9, stop:1 #38BDF8);
}
QTextEdit#Console {
    background-color: #0A0D13;
    border: 1px solid #222A38;
    border-radius: 10px;
    padding: 8px;
    color: #C3CADB;
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 9pt;
    selection-background-color: #3B3466;
}
QTableWidget {
    background-color: #10141C;
    alternate-background-color: #121722;
    border: 1px solid #222A38;
    border-radius: 10px;
    gridline-color: #1B2130;
    selection-background-color: #232B47;
    selection-color: #FFFFFF;
}
QTableWidget::item {
    padding: 6px 8px;
    border-bottom: 1px solid #171D29;
}
QHeaderView::section {
    background-color: #171C27;
    color: #9AA3B8;
    padding: 8px;
    border: none;
    border-bottom: 1px solid #242B39;
    font-weight: 600;
    font-size: 9pt;
}
QTableCornerButton::section {
    background-color: #171C27;
    border: none;
}
QSplitter::handle {
    background-color: #232A38;
    height: 6px;
}
QScrollBar:vertical {
    background: transparent;
    width: 12px;
    margin: 4px 2px;
}
QScrollBar::handle:vertical {
    background: #323B50;
    min-height: 28px;
    border-radius: 4px;
}
QScrollBar::handle:vertical:hover {
    background: #3A4459;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QScrollBar:horizontal {
    background: transparent;
    height: 10px;
    margin: 2px 4px;
}
QScrollBar::handle:horizontal {
    background: #2B3345;
    min-width: 24px;
    border-radius: 4px;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0;
}
QStatusBar {
    background-color: #0B0E14;
    color: #A3ADC2;
    border-top: 1px solid #1D2432;
    font-size: 9pt;
}
QMessageBox {
    background-color: #151923;
}
QMessageBox QLabel {
    color: #E7EAF3;
}
QScrollArea {
    background-color: #0E1016;
    border: none;
}
QScrollArea > QWidget > QWidget {
    background-color: #0E1016;
}
"""


def make_app_icon(size: int = 64) -> QIcon:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    gradient = QLinearGradient(0, 0, size, size)
    gradient.setColorAt(0.0, QColor(ACCENT))
    gradient.setColorAt(1.0, QColor("#38BDF8"))
    painter.setBrush(QBrush(gradient))
    painter.setPen(Qt.PenStyle.NoPen)
    radius = size * 0.24
    painter.drawRoundedRect(QRectF(2, 2, size - 4, size - 4), radius, radius)
    painter.setPen(QColor("#FFFFFF"))
    painter.setFont(QFont("Segoe UI", int(size * 0.38), QFont.Weight.Bold))
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "M")
    painter.end()
    return QIcon(pixmap)
