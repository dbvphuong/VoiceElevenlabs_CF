"""Hộp thoại cấu hình hệ thống (Settings Dialog)."""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit, QTextEdit,
    QSpinBox, QDoubleSpinBox, QCheckBox, QPushButton, QLabel, QGroupBox, QMessageBox
)
from PyQt6.QtCore import Qt
from config.settings import AppSettings

class SettingsDialog(QDialog):
    """Cửa sổ cấu hình hệ thống, đồng bộ với SettingsForm của C#."""

    def __init__(self, settings: AppSettings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Cấu hình hệ thống")
        self.setFixedSize(560, 640)
        self._init_ui()
        self._load_data()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(14)
        main_layout.setContentsMargins(18, 18, 18, 18)

        # 1. Nhóm ElevenLabs API
        group_api = QGroupBox("ElevenLabs API (Tùy chọn)")
        form_api = QFormLayout(group_api)
        self.txt_api_key = QLineEdit()
        self.txt_api_key.setPlaceholderText("sk_... (Tùy chọn cho Official API Key, để trống nếu dùng hCaptcha)")
        form_api.addRow("API Key:", self.txt_api_key)
        main_layout.addWidget(group_api)

        # 2. Nhóm Proxy
        group_proxy = QGroupBox("Cấu hình Proxy")
        layout_proxy = QVBoxLayout(group_proxy)
        
        lbl_static = QLabel("Proxy tĩnh (Chỉ dùng khi có IP cố định dạng host:port:user:pass - để trống nếu dùng Proxy xoay):")
        layout_proxy.addWidget(lbl_static)
        self.txt_static_proxies = QTextEdit()
        self.txt_static_proxies.setFixedHeight(65)
        self.txt_static_proxies.setPlaceholderText("Để trống nếu bạn dùng Proxy xoay hoặc dùng IP mạng nhà (IP gốc)\nVí dụ định dạng nếu có: 103.152.22.1:8080:user:pass")
        layout_proxy.addWidget(self.txt_static_proxies)

        lbl_rotating = QLabel("Proxy xoay (Dán API key proxyxoay.shop vào đây - tự động cấp IP cho cả Trình duyệt & TTS):")
        layout_proxy.addWidget(lbl_rotating)
        self.txt_rotating_proxies = QTextEdit()
        self.txt_rotating_proxies.setFixedHeight(75)
        self.txt_rotating_proxies.setPlaceholderText("Dán API key proxyxoay.shop (mỗi dòng 1 key, ví dụ: FhGCLyWKIGuhNDajgPvfSA)\nTool sẽ tự gọi API lấy IP mới và xoay luân phiên cho toàn bộ hệ thống.")
        layout_proxy.addWidget(self.txt_rotating_proxies)

        main_layout.addWidget(group_proxy)

        # 3. Nhóm Tham số xử lý
        group_params = QGroupBox("Tham số xử lý âm thanh & Hàng đợi")
        form_params = QFormLayout(group_params)

        self.num_threads = QSpinBox()
        self.num_threads.setRange(1, 20)
        form_params.addRow("Số luồng xử lý (Threads):", self.num_threads)

        self.num_chunk_size = QSpinBox()
        self.num_chunk_size.setRange(50, 1000)
        self.num_chunk_size.setSingleStep(50)
        form_params.addRow("Độ dài đoạn tối đa (Ký tự):", self.num_chunk_size)

        silence_layout = QHBoxLayout()
        self.chk_silence = QCheckBox("Chèn khoảng lặng giữa các đoạn")
        self.num_silence = QDoubleSpinBox()
        self.num_silence.setRange(0.0, 5.0)
        self.num_silence.setSingleStep(0.1)
        self.num_silence.setSuffix(" giây")
        silence_layout.addWidget(self.chk_silence)
        silence_layout.addWidget(self.num_silence)
        form_params.addRow("Khoảng lặng (Silence):", silence_layout)

        self.txt_suffix = QLineEdit()
        self.txt_suffix.setPlaceholderText("Ví dụ: _voice (để trống nếu cùng tên file text)")
        form_params.addRow("Hậu tố tệp đầu ra:", self.txt_suffix)

        self.chk_continue_blocking = QCheckBox("Tiếp tục thử lại tối đa 10 lần khi gặp lỗi chặn (WAF / Unusual)")
        form_params.addRow(self.chk_continue_blocking)

        main_layout.addWidget(group_params)

        # Nút bấm hành động
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.btn_save = QPushButton("Lưu cấu hình")
        self.btn_save.setFixedHeight(34)
        self.btn_save.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_save.setStyleSheet("""
            QPushButton {
                background-color: #2563EB; color: white; font-weight: bold; padding: 0 16px;
                border: 1px solid #1D4ED8; border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #3B82F6; border: 1px solid #93C5FD;
            }
            QPushButton:pressed {
                background-color: #1D4ED8; padding-top: 2px;
            }
        """)
        self.btn_save.clicked.connect(self._on_save)
        btn_layout.addWidget(self.btn_save)

        self.btn_cancel = QPushButton("Hủy bỏ")
        self.btn_cancel.setFixedHeight(34)
        self.btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_cancel)

        main_layout.addLayout(btn_layout)

    def _load_data(self):
        self.txt_api_key.setText(self.settings.eleven_labs_api_key)
        self.txt_static_proxies.setText(self.settings.static_proxies)
        self.txt_rotating_proxies.setText(self.settings.rotating_proxies)
        self.num_threads.setValue(self.settings.thread_count)
        self.num_chunk_size.setValue(self.settings.chunk_size)
        self.chk_silence.setChecked(self.settings.silence_enabled)
        self.num_silence.setValue(self.settings.silence_value)
        self.txt_suffix.setText(self.settings.output_file_suffix)
        self.chk_continue_blocking.setChecked(self.settings.continue_worker_on_blocking_errors)

    def _on_save(self):
        self.settings.eleven_labs_api_key = self.txt_api_key.text().strip()
        self.settings.static_proxies = self.txt_static_proxies.toPlainText().strip()
        self.settings.rotating_proxies = self.txt_rotating_proxies.toPlainText().strip()
        self.settings.thread_count = self.num_threads.value()
        self.settings.chunk_size = self.num_chunk_size.value()
        self.settings.silence_enabled = self.chk_silence.isChecked()
        self.settings.silence_value = self.num_silence.value()
        self.settings.output_file_suffix = self.txt_suffix.text().strip()
        self.settings.continue_worker_on_blocking_errors = self.chk_continue_blocking.isChecked()

        self.settings.save()
        QMessageBox.information(self, "Thông báo", "Đã lưu cài đặt thành công!")
        self.accept()
