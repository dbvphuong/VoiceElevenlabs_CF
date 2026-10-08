"""Hộp thoại tìm kiếm và duyệt danh sách giọng đọc ElevenLabs (Voice Dialog)."""

from typing import List, Dict, Any, Optional
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QComboBox, QMessageBox,
    QApplication
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QFont

from network.voice_service import voice_service

class FetchVoicesWorker(QThread):
    """Luồng phụ lấy danh sách giọng từ ElevenLabs API để không đơ UI."""
    finished_signal = pyqtSignal(list)
    error_signal = pyqtSignal(str)

    def __init__(self, api_key: str, proxy_url: str = ""):
        super().__init__()
        self.api_key = api_key
        self.proxy_url = proxy_url

    def run(self):
        try:
            voices = voice_service.fetch_all_voices(self.api_key, self.proxy_url)
            self.finished_signal.emit(voices)
        except Exception as e:
            self.error_signal.emit(str(e))

class VoiceSearchDialog(QDialog):
    """Cửa sổ tra cứu, tìm kiếm và lựa chọn giọng đọc từ ElevenLabs."""

    def __init__(self, api_key: str = "", current_voice_id: str = "", parent=None):
        super().__init__(parent)
        self.api_key = api_key
        self.current_voice_id = current_voice_id.strip()
        self.selected_voice: Optional[Dict[str, Any]] = None
        self.all_voices: List[Dict[str, Any]] = []
        self.worker: Optional[FetchVoicesWorker] = None

        self.setWindowTitle("Danh sách & Tìm kiếm giọng đọc ElevenLabs")
        self.resize(860, 560)
        self.setMinimumSize(720, 440)

        self._init_ui()
        self._load_initial_data()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(14, 14, 14, 14)

        # 1. Hàng tìm kiếm & Bộ lọc
        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("Tìm kiếm:"))

        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("Nhập tên giọng, Voice ID, giới tính (male/female), chất giọng...")
        self.txt_search.textChanged.connect(self._apply_filter)
        filter_layout.addWidget(self.txt_search, 3)

        filter_layout.addWidget(QLabel("Phân loại:"))
        self.combo_category = QComboBox()
        self.combo_category.addItems(["Tất cả", "premade (Mặc định)", "professional (Chuyên nghiệp)", "cloned (Nhân bản)", "custom (Khác)"])
        self.combo_category.currentIndexChanged.connect(self._apply_filter)
        filter_layout.addWidget(self.combo_category, 1)

        self.btn_refresh = QPushButton("🔄 Tải lại từ 11labs")
        self.btn_refresh.setToolTip("Đồng bộ danh sách giọng mới nhất từ tài khoản ElevenLabs qua API Key")
        self.btn_refresh.clicked.connect(self._refresh_from_api)
        filter_layout.addWidget(self.btn_refresh)

        self.btn_search_community = QPushButton("🌐 Tìm Thư viện")
        self.btn_search_community.setToolTip("Tìm kiếm giọng trong thư viện cộng đồng ElevenLabs (Shared Library)")
        self.btn_search_community.clicked.connect(self._search_community)
        filter_layout.addWidget(self.btn_search_community)

        layout.addLayout(filter_layout)

        # 2. Bảng hiển thị danh sách giọng
        self.table_voices = QTableWidget(0, 5)
        self.table_voices.setHorizontalHeaderLabels(["STT", "Tên giọng (Voice Name)", "Voice ID", "Phân loại", "Đặc điểm / Nhãn"])
        self.table_voices.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table_voices.setColumnWidth(0, 45)
        self.table_voices.setColumnWidth(2, 210)
        self.table_voices.setColumnWidth(3, 110)
        self.table_voices.setColumnWidth(4, 260)
        self.table_voices.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table_voices.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table_voices.cellDoubleClicked.connect(self._on_table_double_clicked)
        self.table_voices.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self.table_voices, 1)

        # 3. Thông tin chi tiết giọng đang chọn
        self.lbl_selected_detail = QLabel("Chọn 1 giọng trong bảng để xem chi tiết.")
        self.lbl_selected_detail.setStyleSheet("color: #475569; font-size: 12px; padding: 4px;")
        layout.addWidget(self.lbl_selected_detail)

        # 4. Thanh nút hành động
        btn_layout = QHBoxLayout()
        self.lbl_count = QLabel("Tổng số: 0 giọng")
        self.lbl_count.setStyleSheet("font-weight: bold; color: #1E293B;")
        btn_layout.addWidget(self.lbl_count)

        btn_layout.addStretch()

        self.btn_select = QPushButton("✔ Chọn giọng này")
        self.btn_select.setFixedHeight(34)
        self.btn_select.setEnabled(False)
        self.btn_select.setStyleSheet("background-color: #2563EB; color: white; font-weight: bold; padding: 0 18px; border-radius: 4px;")
        self.btn_select.clicked.connect(self._on_select_clicked)
        btn_layout.addWidget(self.btn_select)

        btn_cancel = QPushButton("Đóng")
        btn_cancel.setFixedHeight(34)
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)

        layout.addLayout(btn_layout)

    def _load_initial_data(self):
        # Nạp dữ liệu có sẵn từ cache ngay tức thì
        self.all_voices = voice_service.fetch_all_voices(api_key=None)
        self._apply_filter()

        # Nếu có API key, tự động chạy tải mới ngầm trong nền
        if self.api_key and self.api_key.strip():
            self._refresh_from_api()

    def _refresh_from_api(self):
        if not self.api_key or not self.api_key.strip():
            QMessageBox.information(
                self,
                "Chưa cấu hình API Key",
                "Bạn chưa nhập ElevenLabsApiKey trong phần Cấu hình hệ thống.\n"
                "Hệ thống đang hiển thị danh sách giọng mẫu cục bộ."
            )
            return

        self.btn_refresh.setEnabled(False)
        self.btn_refresh.setText("⏳ Đang đồng bộ...")
        self.worker = FetchVoicesWorker(self.api_key)
        self.worker.finished_signal.connect(self._on_fetch_success)
        self.worker.error_signal.connect(self._on_fetch_error)
        self.worker.start()

    def _on_fetch_success(self, voices: List[Dict[str, Any]]):
        self.btn_refresh.setEnabled(True)
        self.btn_refresh.setText("🔄 Tải lại từ 11labs")
        self.all_voices = voices
        self._apply_filter()

    def _on_fetch_error(self, err_msg: str):
        self.btn_refresh.setEnabled(True)
        self.btn_refresh.setText("🔄 Tải lại từ 11labs")
        QMessageBox.warning(self, "Lỗi kết nối", f"Không thể lấy danh sách giọng từ ElevenLabs: {err_msg}")

    def _search_community(self):
        query = self.txt_search.text().strip()
        if not query:
            QMessageBox.information(self, "Chú ý", "Vui lòng nhập từ khóa tìm kiếm!")
            return
        if not self.api_key or not self.api_key.strip():
            QMessageBox.warning(self, "Cần API Key", "Tính năng tìm kiếm Thư viện cộng đồng ElevenLabs cần có ElevenLabsApiKey trong phần Cài đặt.")
            return

        self.btn_search_community.setEnabled(False)
        self.btn_search_community.setText("⏳ Đang tìm...")
        QApplication.processEvents()
        try:
            shared = voice_service.search_shared_voices(query, self.api_key)
            if shared:
                existing_ids = {v.get("voice_id") for v in self.all_voices}
                added_count = 0
                for sv in shared:
                    if sv.get("voice_id") not in existing_ids:
                        self.all_voices.append(sv)
                        added_count += 1
                self._apply_filter()
                QMessageBox.information(self, "Kết quả", f"Đã tìm thấy và thêm {len(shared)} giọng từ Thư viện cộng đồng ({added_count} giọng mới)!")
            else:
                QMessageBox.information(self, "Kết quả", f"Không tìm thấy giọng cộng đồng nào khớp với '{query}'.")
        finally:
            self.btn_search_community.setEnabled(True)
            self.btn_search_community.setText("🌐 Tìm Thư viện")

    def _apply_filter(self):
        query = self.txt_search.text().strip().lower()
        cat_idx = self.combo_category.currentIndex()
        cat_filter = ["", "premade", "professional", "cloned", "custom"][cat_idx]

        self.table_voices.setRowCount(0)
        displayed_row = 0
        matched_target_row = -1

        for v in self.all_voices:
            vid = v.get("voice_id", "")
            name = v.get("name", "")
            cat = v.get("category", "")
            labels = v.get("labels", {})
            label_text = ", ".join([f"{k}: {val}" for k, val in labels.items()]) if isinstance(labels, dict) else str(labels)

            # Lọc theo Category
            if cat_filter and cat.lower() != cat_filter.lower():
                continue

            # Lọc theo Query text
            search_corpus = f"{name} {vid} {cat} {label_text}".lower()
            if query and query not in search_corpus:
                continue

            row = self.table_voices.rowCount()
            self.table_voices.insertRow(row)

            item_stt = QTableWidgetItem(str(row + 1))
            item_stt.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table_voices.setItem(row, 0, item_stt)

            item_name = QTableWidgetItem(name)
            font = QFont()
            font.setBold(True)
            item_name.setFont(font)
            self.table_voices.setItem(row, 1, item_name)

            item_id = QTableWidgetItem(vid)
            self.table_voices.setItem(row, 2, item_id)

            item_cat = QTableWidgetItem(cat)
            self.table_voices.setItem(row, 3, item_cat)

            item_labels = QTableWidgetItem(label_text)
            self.table_voices.setItem(row, 4, item_labels)

            # Đính kèm dict voice vào cột 0
            item_stt.setData(Qt.ItemDataRole.UserRole, v)

            if vid == self.current_voice_id:
                matched_target_row = row

            displayed_row += 1

        self.lbl_count.setText(f"Hiển thị: {displayed_row}/{len(self.all_voices)} giọng")

        if matched_target_row >= 0:
            self.table_voices.selectRow(matched_target_row)

    def _on_selection_changed(self):
        selected_rows = self.table_voices.selectionModel().selectedRows()
        if not selected_rows:
            self.btn_select.setEnabled(False)
            self.selected_voice = None
            self.lbl_selected_detail.setText("Chọn 1 giọng trong bảng để xem chi tiết.")
            return

        row = selected_rows[0].row()
        item = self.table_voices.item(row, 0)
        if item:
            voice = item.data(Qt.ItemDataRole.UserRole)
            self.selected_voice = voice
            self.btn_select.setEnabled(True)

            name = voice.get("name", "")
            vid = voice.get("voice_id", "")
            cat = voice.get("category", "")
            labels = voice.get("labels", {})
            label_text = ", ".join([f"{k}: {val}" for k, val in labels.items()]) if isinstance(labels, dict) else str(labels)
            desc = voice.get("description", "")
            detail = f"<b>{name}</b> (ID: <code>{vid}</code>) | Phân loại: <b>{cat}</b> | {label_text}"
            if desc:
                detail += f"<br>Mô tả: <i>{desc}</i>"
            self.lbl_selected_detail.setText(detail)

    def _on_table_double_clicked(self, row: int, col: int):
        self._on_selection_changed()
        if self.selected_voice:
            self.accept()

    def _on_select_clicked(self):
        if self.selected_voice:
            self.accept()
