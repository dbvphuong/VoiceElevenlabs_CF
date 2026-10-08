"""Widget hiển thị nhật ký hoạt động thời gian thực (Log Viewer)."""

from datetime import datetime
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QPushButton, QCheckBox, QLabel, QDialog
)
from PyQt6.QtCore import pyqtSignal, QObject
from PyQt6.QtGui import QTextCursor
from loguru import logger

class LogSignalEmitter(QObject):
    log_signal = pyqtSignal(str, str)  # level, message

emitter = LogSignalEmitter()

def qt_log_sink(message):
    record = message.record
    level = record["level"].name
    msg = record["message"]
    emitter.log_signal.emit(level, msg)

class LogWidget(QWidget):
    """Khung xem Log thời gian thực có phân biệt màu sắc."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.auto_scroll = True
        self._init_ui()

        # Kết nối signal
        emitter.log_signal.connect(self.append_log)
        # Gắn sink vào loguru
        logger.add(qt_log_sink, level="INFO")

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # Header bar của Log
        top_bar = QHBoxLayout()
        title = QLabel("Nhật ký hoạt động (Logs)")
        title.setStyleSheet("font-weight: bold; color: #334155;")
        top_bar.addWidget(title)
        top_bar.addStretch()

        self.chk_autoscroll = QCheckBox("Tự động cuộn")
        self.chk_autoscroll.setChecked(True)
        self.chk_autoscroll.toggled.connect(self._on_autoscroll_toggled)
        top_bar.addWidget(self.chk_autoscroll)

        btn_clear = QPushButton("Xóa log")
        btn_clear.setFixedHeight(26)
        btn_clear.clicked.connect(self.clear_log)
        top_bar.addWidget(btn_clear)

        layout.addLayout(top_bar)

        # Khung văn bản hiển thị
        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setStyleSheet(
            "background-color: #0F172A; color: #E2E8F0; font-family: 'Consolas', monospace; "
            "font-size: 11px; border-radius: 6px; padding: 6px;"
        )
        layout.addWidget(self.text_edit)

    def _on_autoscroll_toggled(self, checked: bool):
        self.auto_scroll = checked

    def clear_log(self):
        self.text_edit.clear()

    def append_log(self, level: str, message: str):
        now_str = datetime.now().strftime("%H:%M:%S")

        color_map = {
            "DEBUG": "#64748B",
            "INFO": "#38BDF8",
            "SUCCESS": "#4ADE80",
            "WARNING": "#FACC15",
            "ERROR": "#F87171",
            "CRITICAL": "#FB7185",
        }
        color = color_map.get(level.upper(), "#E2E8F0")

        html = f"<span style='color: #64748B;'>[{now_str}]</span> <b style='color: {color};'>[{level}]</b> <span style='color: #F8FAFC;'>{message}</span><br>"
        self.text_edit.insertHtml(html)

        if self.auto_scroll:
            cursor = self.text_edit.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            self.text_edit.setTextCursor(cursor)


class LogWindow(QDialog):
    """Cửa sổ hiển thị nhật ký hoạt động thời gian thực (độc lập, có thể mở/đóng bất kỳ lúc nào)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Nhật ký hoạt động thời gian thực (Realtime Logs) - 11labs CF")
        self.resize(880, 520)
        self.setMinimumSize(640, 360)
        self._force_close = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self.log_widget = LogWidget(self)
        layout.addWidget(self.log_widget)

        # Thanh chân trang chứa ghi chú và nút đóng
        bottom_bar = QHBoxLayout()
        lbl_hint = QLabel("💡 Cửa sổ có thể đóng/mở bất kỳ lúc nào mà không làm gián đoạn tiến trình đang chạy.")
        lbl_hint.setStyleSheet("color: #64748B; font-size: 11px;")
        bottom_bar.addWidget(lbl_hint)
        bottom_bar.addStretch()

        btn_close = QPushButton("Đóng")
        btn_close.setFixedHeight(30)
        btn_close.setStyleSheet(
            "padding: 0 22px; font-weight: bold; background-color: #EDE9FE; color: #6D28D9; "
            "border: 1px solid #C4B5FD; border-radius: 4px;"
        )
        btn_close.clicked.connect(self.hide)
        bottom_bar.addWidget(btn_close)

        layout.addLayout(bottom_bar)

    def closeEvent(self, event):
        """Khi bấm nút [X], chỉ ẩn cửa sổ để không làm đứt mạch ghi log trong nền."""
        if self._force_close:
            event.accept()
        else:
            event.ignore()
            self.hide()

