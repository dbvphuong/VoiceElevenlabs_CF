"""Điểm khởi chạy ứng dụng Desktop PyQt6 (Entry Point)."""

import sys
from pathlib import Path

# Fix Unicode console cho Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QFont
from loguru import logger

from utils.logger import setup_application_logger
from ui.main_window import MainWindow

MODERN_QSS = """
QMainWindow {
    background-color: #F8FAFC;
}

QWidget {
    font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, Roboto, sans-serif;
    font-size: 12px;
    color: #1E293B;
}

QGroupBox {
    font-weight: bold;
    border: 1px solid #CBD5E1;
    border-radius: 6px;
    margin-top: 10px;
    padding-top: 12px;
    background-color: #FFFFFF;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    padding: 0 4px;
    color: #2563EB;
}

QLineEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    background-color: #FFFFFF;
    border: 1px solid #CBD5E1;
    border-radius: 4px;
    padding: 4px 6px;
    selection-background-color: #2563EB;
}

QLineEdit:focus, QTextEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border: 1px solid #2563EB;
}

QPushButton {
    background-color: #F8FAFC;
    border: 1px solid #CBD5E1;
    border-radius: 5px;
    padding: 5px 14px;
    font-weight: 600;
    color: #1E293B;
}

QPushButton:hover {
    background-color: #EEF2FF;
    border: 1px solid #6366F1;
    color: #4338CA;
}

QPushButton:pressed {
    background-color: #E0E7FF;
    border: 1px solid #4F46E5;
    color: #3730A3;
    padding-top: 6px;
    padding-bottom: 4px;
}

QPushButton:disabled {
    background-color: #F1F5F9;
    border: 1px solid #E2E8F0;
    color: #94A3B8;
}

QTableWidget {
    background-color: #FFFFFF;
    border: 1px solid #CBD5E1;
    border-radius: 4px;
    gridline-color: #F1F5F9;
    alternate-background-color: #F8FAFC;
    selection-background-color: #EFF6FF;
    selection-color: #1E293B;
}

QHeaderView::section {
    background-color: #EDE9FE;
    color: #4C1D95;
    font-weight: bold;
    border: none;
    border-right: 1px solid #DDD6FE;
    border-bottom: 2px solid #C4B5FD;
    padding: 7px 6px;
}

QHeaderView::section:horizontal {
    background-color: #EDE9FE;
    color: #4C1D95;
    font-weight: bold;
    border: none;
    border-right: 1px solid #DDD6FE;
    border-bottom: 2px solid #C4B5FD;
    padding: 7px 6px;
}

QTableCornerButton::section {
    background-color: #EDE9FE;
    border: none;
    border-right: 1px solid #DDD6FE;
    border-bottom: 2px solid #C4B5FD;
}

QProgressBar {
    background-color: #E2E8F0;
    border: none;
    border-radius: 4px;
    text-align: center;
    color: #1E293B;
    font-weight: bold;
}

QProgressBar::chunk {
    background-color: #16A34A;
    border-radius: 4px;
}
"""

def main():
    setup_application_logger()
    try:
        app = QApplication(sys.argv)
        app.setStyleSheet(MODERN_QSS)

        font = QFont("Segoe UI", 9)
        app.setFont(font)

        window = MainWindow()
        window.show()

        logger.info("Khởi động ứng dụng 11labs CF Desktop GUI thành công.")
        sys.exit(app.exec())
    except Exception as e:
        logger.critical(f"Lỗi nghiêm trọng khi khởi chạy ứng dụng GUI: {e}")
        raise

if __name__ == "__main__":
    main()
