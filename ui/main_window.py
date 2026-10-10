"""Cửa sổ chính của ứng dụng Desktop PyQt6 (MainWindow)."""

import sys
import os
from pathlib import Path
from typing import List, Dict, Optional

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QLabel, QPushButton, QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox,
    QCheckBox, QTableWidget, QTableWidgetItem, QHeaderView, QProgressBar,
    QFileDialog, QMessageBox, QGroupBox, QFrame, QInputDialog, QMenu,
    QApplication
)
from PyQt6.QtCore import Qt, pyqtSlot, QPoint
from PyQt6.QtGui import QColor, QFont, QIcon, QAction, QKeySequence, QShortcut
from loguru import logger

from config.constants import MODEL_IDS
from config.settings import AppSettings, VoiceTemplate, FolderVoiceProfile, FileVoiceProfile
from core.file_scanner import collect_txt_files
from core.text_splitter import split_text_by_sentences
from ui.settings_dialog import SettingsDialog
from ui.voice_dialog import VoiceSearchDialog
from ui.log_widget import LogWidget, LogWindow
from ui.bridge import PipelineBridgeThread, ProfileWarmerThread
from network.voice_service import voice_service
from network.tts_client import is_v4_model
from captcha.profile_manager import profile_manager, PROFILES_DUNG_DIR

class MainWindow(QMainWindow):
    """Giao diện chính mô phỏng và nâng cấp toàn diện từ C# WinForms Form1."""

    def __init__(self, settings_path: Optional[Path | str] = None):
        super().__init__()
        self.setWindowTitle("11labs CF - Python Desktop")
        self.resize(1180, 840)
        self.setMinimumSize(1020, 720)

        if settings_path:
            self.settings_path = Path(settings_path)
        else:
            if getattr(sys, "frozen", False):
                self.settings_path = Path(sys.executable).parent / "settings.json"
            else:
                self.settings_path = Path("settings.json")
        self.settings = AppSettings.load(self.settings_path)
        self.bridge_thread: Optional[PipelineBridgeThread] = None
        self.warmer_thread: Optional[ProfileWarmerThread] = None

        self.file_list: List[Path] = []
        self.file_chunks_cache: Dict[int, List[dict]] = {}
        self.selected_file_index: int = -1
        self._is_loading_ui: bool = False

        self.chunk_page_size: int = 50
        self.chunk_current_page: int = 1
        self.chunk_total_pages: int = 1

        self.log_window = LogWindow(self)
        self._init_ui()
        self._load_settings_to_ui()
        self._update_profile_count_display()
        self._rescan_files()

    def _init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(14, 12, 14, 12)
        main_layout.setSpacing(10)

        # 1. Header (Tiêu đề & Nút Cài đặt)
        header_layout = QHBoxLayout()
        logo_label = QLabel("11")
        logo_label.setFixedSize(42, 42)
        logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_label.setStyleSheet("background-color: #2563EB; color: white; font-weight: bold; font-size: 18px; border-radius: 6px;")
        header_layout.addWidget(logo_label)

        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        lbl_title = QLabel("11labs CF Automation")
        lbl_title.setStyleSheet("font-size: 16px; font-weight: bold; color: #0F172A;")
        lbl_sub = QLabel("Chuyển văn bản thành giọng nói ElevenLabs tự động (Bypass hCaptcha & Anonymous Stream)")
        lbl_sub.setStyleSheet("font-size: 12px; color: #64748B;")
        title_box.addWidget(lbl_title)
        title_box.addWidget(lbl_sub)
        header_layout.addLayout(title_box)

        header_layout.addStretch()

        self.btn_view_log = QPushButton("📋 Xem Log")
        self.btn_view_log.setFixedHeight(36)
        self.btn_view_log.setStyleSheet(
            "font-weight: bold; padding: 0 14px; background-color: #EDE9FE; color: #6D28D9; "
            "border: 1px solid #C4B5FD; border-radius: 4px;"
        )
        self.btn_view_log.setToolTip("Mở cửa sổ theo dõi nhật ký hoạt động thời gian thực")
        self.btn_view_log.clicked.connect(self._open_log_window)
        header_layout.addWidget(self.btn_view_log)

        btn_settings = QPushButton("⚙ Cấu hình hệ thống")
        btn_settings.setFixedHeight(36)
        btn_settings.setStyleSheet("font-weight: bold; padding: 0 14px;")
        btn_settings.clicked.connect(self._open_settings)
        header_layout.addWidget(btn_settings)

        main_layout.addLayout(header_layout)

        # 2. Bảng cấu hình Giọng đọc (Voice Controls)
        group_voice = QGroupBox("Cấu hình giọng đọc (Voice Parameters)")
        voice_layout = QVBoxLayout(group_voice)
        voice_layout.setSpacing(8)

        # Hàng 1: Voice ID & Tra cứu giọng trên ElevenLabs
        row_voice = QHBoxLayout()
        row_voice.addWidget(QLabel("Voice ID:"))
        self.txt_voice_id = QLineEdit()
        self.txt_voice_id.setPlaceholderText("Nhập Voice ID (ví dụ: j9jfwdrw7BRfcR43Qohk hoặc 21m00Tcm4TlvDq8ikWAM)")
        self.txt_voice_id.editingFinished.connect(self._on_voice_id_editing_finished)
        row_voice.addWidget(self.txt_voice_id, 3)

        self.btn_check_voice = QPushButton("🔍 Kiểm tra Voice")
        self.btn_check_voice.setToolTip("Kiểm tra thông tin và tên của Voice ID này trên 11labs")
        self.btn_check_voice.setStyleSheet("font-weight: bold; padding: 4px 10px;")
        self.btn_check_voice.clicked.connect(self._on_check_voice_clicked)
        row_voice.addWidget(self.btn_check_voice)

        self.btn_browse_voices = QPushButton("📚 Danh sách giọng")
        self.btn_browse_voices.setToolTip("Mở danh sách các giọng ElevenLabs để tìm kiếm & chọn")
        self.btn_browse_voices.setStyleSheet("background-color: #0284C7; color: white; font-weight: bold; padding: 4px 12px; border-radius: 4px;")
        self.btn_browse_voices.clicked.connect(self._on_browse_voices_clicked)
        row_voice.addWidget(self.btn_browse_voices)

        self.lbl_voice_name = QLabel("🎙 Tên giọng: Chưa xác định")
        self.lbl_voice_name.setStyleSheet("background-color: #F1F5F9; color: #334155; padding: 4px 10px; border-radius: 4px; font-weight: bold;")
        row_voice.addWidget(self.lbl_voice_name, 3)

        voice_layout.addLayout(row_voice)

        # Hàng 2: Mẫu giọng (Voice Templates) & Model & Ngôn ngữ
        row_tmpl = QHBoxLayout()
        row_tmpl.addWidget(QLabel("Mẫu giọng:"))
        self.combo_templates = QComboBox()
        self.combo_templates.currentIndexChanged.connect(self._on_template_selected)
        row_tmpl.addWidget(self.combo_templates, 3)

        self.btn_save_template = QPushButton("💾 Lưu mẫu")
        self.btn_save_template.setToolTip("Lưu toàn bộ thông số giọng hiện tại thành mẫu mới hoặc cập nhật mẫu đã chọn")
        self.btn_save_template.setStyleSheet("font-weight: bold; padding: 4px 10px;")
        self.btn_save_template.clicked.connect(self._on_save_template_clicked)
        row_tmpl.addWidget(self.btn_save_template)

        self.btn_delete_template = QPushButton("🗑 Xóa mẫu")
        self.btn_delete_template.setToolTip("Xóa mẫu giọng đang chọn")
        self.btn_delete_template.setStyleSheet("padding: 4px 10px;")
        self.btn_delete_template.clicked.connect(self._on_delete_template_clicked)
        row_tmpl.addWidget(self.btn_delete_template)

        row_tmpl.addSpacing(12)

        row_tmpl.addWidget(QLabel("Model:"))
        self.combo_model = QComboBox()
        self.combo_model.addItems(MODEL_IDS)
        self.combo_model.currentIndexChanged.connect(self._on_model_changed)
        row_tmpl.addWidget(self.combo_model, 2)

        row_tmpl.addWidget(QLabel("Ngôn ngữ:"))
        self.combo_lang = QComboBox()
        self.combo_lang.addItems(["Tự động", "English (en)", "Tiếng Việt (vi)", "Japanese (ja)", "Chinese (zh)"])
        self.combo_lang.currentIndexChanged.connect(self._on_voice_param_changed)
        row_tmpl.addWidget(self.combo_lang, 2)

        voice_layout.addLayout(row_tmpl)

        # Hàng 3: Sliders & Spinboxes (Speed, Stability, Similarity, Style, Boost)
        row_params = QHBoxLayout()
        row_params.addWidget(QLabel("Tốc độ:"))
        self.num_speed = QDoubleSpinBox()
        self.num_speed.setRange(0.7, 1.2)
        self.num_speed.setSingleStep(0.05)
        self.num_speed.valueChanged.connect(self._on_voice_param_changed)
        row_params.addWidget(self.num_speed)

        row_params.addWidget(QLabel("Ổn định (Stability):"))
        self.num_stab = QSpinBox()
        self.num_stab.setRange(0, 100)
        self.num_stab.setSuffix("%")
        self.num_stab.valueChanged.connect(self._on_voice_param_changed)
        row_params.addWidget(self.num_stab)

        row_params.addWidget(QLabel("Tương đồng (Similarity):"))
        self.num_sim = QSpinBox()
        self.num_sim.setRange(0, 100)
        self.num_sim.setSuffix("%")
        self.num_sim.valueChanged.connect(self._on_voice_param_changed)
        row_params.addWidget(self.num_sim)

        row_params.addWidget(QLabel("Phong cách (Style):"))
        self.num_style = QSpinBox()
        self.num_style.setRange(0, 100)
        self.num_style.setSuffix("%")
        self.num_style.valueChanged.connect(self._on_voice_param_changed)
        row_params.addWidget(self.num_style)

        self.chk_boost = QCheckBox("Khuếch đại (Boost)")
        self.chk_boost.toggled.connect(self._on_voice_param_changed)
        row_params.addWidget(self.chk_boost)
        row_params.addStretch()

        voice_layout.addLayout(row_params)
        main_layout.addWidget(group_voice)

        # 3. Khu vực Bảng Files & Chunks (QSplitter)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Khung bên trái: Danh sách Files
        left_box = QWidget()
        left_layout = QVBoxLayout(left_box)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)

        file_actions = QHBoxLayout()
        btn_add_folder = QPushButton("Thêm folder")
        btn_add_folder.clicked.connect(self._add_folder)
        file_actions.addWidget(btn_add_folder)

        btn_add_file = QPushButton("Thêm file .txt")
        btn_add_file.clicked.connect(self._add_file)
        file_actions.addWidget(btn_add_file)

        self.btn_delete_file = QPushButton("🗑 Xóa row")
        self.btn_delete_file.setToolTip("Xóa các hàng tệp .txt đã chọn khỏi danh sách (Phím tắt: Delete / Backspace)")
        self.btn_delete_file.setStyleSheet(
            "color: #DC2626; font-weight: bold; padding: 4px 10px; border: 1px solid #FECACA; "
            "background-color: #FEF2F2; border-radius: 4px;"
        )
        self.btn_delete_file.clicked.connect(self._delete_selected_files)
        file_actions.addWidget(self.btn_delete_file)

        self.chk_subfolders = QCheckBox("Gồm folder con")
        self.chk_subfolders.setChecked(self.settings.scan_subfolders)
        self.chk_subfolders.toggled.connect(self._on_subfolders_toggled)
        file_actions.addWidget(self.chk_subfolders)

        btn_rescan = QPushButton("Quét lại")
        btn_rescan.clicked.connect(self._rescan_files)
        file_actions.addWidget(btn_rescan)

        btn_open_out = QPushButton("📂 Thư mục Output")
        btn_open_out.setToolTip("Mở thư mục chứa file MP3 đầu ra của tệp đang chọn trong Explorer")
        btn_open_out.clicked.connect(self._open_selected_output_folder)
        file_actions.addWidget(btn_open_out)

        left_layout.addLayout(file_actions)

        lbl_files_title = QLabel("Danh sách tệp văn bản:")
        lbl_files_title.setStyleSheet("font-weight: bold; color: #5B21B6; background-color: #F5F3FF; padding: 4px 8px; border-radius: 4px; border: 1px solid #DDD6FE;")
        left_layout.addWidget(lbl_files_title)

        self.table_files = QTableWidget(0, 5)
        self.table_files.setHorizontalHeaderLabels(["STT", "Đường dẫn file", "Mẫu giọng áp dụng", "Tiến độ", "Tệp đầu ra (Output)"])
        self.table_files.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table_files.setColumnWidth(0, 45)
        self.table_files.setColumnWidth(2, 210)
        self.table_files.setColumnWidth(3, 90)
        self.table_files.setColumnWidth(4, 185)
        self.table_files.verticalHeader().setVisible(False)
        self.table_files.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table_files.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.table_files.cellClicked.connect(self._on_file_selected)
        self.table_files.cellDoubleClicked.connect(self._on_file_double_clicked)
        self.table_files.currentCellChanged.connect(self._on_current_cell_changed)
        self.table_files.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table_files.customContextMenuRequested.connect(self._on_files_context_menu)
        self.table_files.keyPressEvent = self._table_files_key_press

        shortcut_del = QShortcut(QKeySequence(Qt.Key.Key_Delete), self.table_files)
        shortcut_del.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        shortcut_del.activated.connect(self._delete_selected_files)

        shortcut_bksp = QShortcut(QKeySequence(Qt.Key.Key_Backspace), self.table_files)
        shortcut_bksp.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        shortcut_bksp.activated.connect(self._delete_selected_files)

        left_layout.addWidget(self.table_files)

        splitter.addWidget(left_box)

        # Khung bên phải: Chi tiết Chunks của file đang chọn
        right_box = QWidget()
        right_layout = QVBoxLayout(right_box)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)

        chunk_header_box = QHBoxLayout()
        self.lbl_selected_file = QLabel("Chi tiết đoạn văn bản (Chọn 1 file bên trái để xem)")
        self.lbl_selected_file.setStyleSheet("font-weight: bold; color: #5B21B6; background-color: #F5F3FF; padding: 4px 8px; border-radius: 4px; border: 1px solid #DDD6FE;")
        chunk_header_box.addWidget(self.lbl_selected_file, 1)

        self.btn_play_output = QPushButton("▶ Nghe MP3 đầu ra")
        self.btn_play_output.setStyleSheet("background-color: #16A34A; color: white; font-weight: bold; padding: 4px 10px; border-radius: 4px;")
        self.btn_play_output.setToolTip("Mở / Phát tệp MP3 hoàn chỉnh của file này")
        self.btn_play_output.clicked.connect(self._play_selected_output_file)
        chunk_header_box.addWidget(self.btn_play_output)
        right_layout.addLayout(chunk_header_box)

        self.table_chunks = QTableWidget(0, 4)
        self.table_chunks.setHorizontalHeaderLabels(["STT", "Nội dung đoạn", "Trạng thái", "Ghi chú"])
        self.table_chunks.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table_chunks.setColumnWidth(0, 45)
        self.table_chunks.setColumnWidth(2, 100)
        self.table_chunks.setColumnWidth(3, 130)
        self.table_chunks.verticalHeader().setVisible(False)
        self.table_chunks.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        right_layout.addWidget(self.table_chunks)

        # Thanh phân trang cho bảng Chunks (tối đa 50 dòng/trang)
        chunk_pagination_box = QHBoxLayout()
        chunk_pagination_box.setContentsMargins(2, 2, 2, 2)
        chunk_pagination_box.setSpacing(6)

        btn_page_style = """
            QPushButton {
                background-color: #EDE9FE;
                color: #5B21B6;
                font-weight: bold;
                font-size: 11px;
                border: 1px solid #C4B5FD;
                border-radius: 4px;
                padding: 4px 10px;
            }
            QPushButton:hover {
                background-color: #DDD6FE;
            }
            QPushButton:disabled {
                background-color: #F3F4F6;
                color: #9CA3AF;
                border: 1px solid #E5E7EB;
            }
        """

        self.btn_first_chunk_page = QPushButton("« Đầu")
        self.btn_first_chunk_page.setFixedHeight(26)
        self.btn_first_chunk_page.setStyleSheet(btn_page_style)
        self.btn_first_chunk_page.setToolTip("Về trang đầu tiên (đoạn 1–50)")
        self.btn_first_chunk_page.clicked.connect(self._first_chunk_page)
        chunk_pagination_box.addWidget(self.btn_first_chunk_page)

        self.btn_prev_chunk_page = QPushButton("◀ Trước")
        self.btn_prev_chunk_page.setFixedHeight(26)
        self.btn_prev_chunk_page.setStyleSheet(btn_page_style)
        self.btn_prev_chunk_page.setToolTip("Trang trước (50 đoạn trước)")
        self.btn_prev_chunk_page.clicked.connect(self._prev_chunk_page)
        chunk_pagination_box.addWidget(self.btn_prev_chunk_page)

        self.lbl_chunk_page_info = QLabel("Trang 1/1 (0 đoạn)")
        self.lbl_chunk_page_info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_chunk_page_info.setStyleSheet(
            "font-size: 11px; font-weight: bold; color: #4B5563; padding: 2px 6px; "
            "background-color: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 4px;"
        )
        chunk_pagination_box.addWidget(self.lbl_chunk_page_info, 1)

        self.btn_next_chunk_page = QPushButton("Sau ▶")
        self.btn_next_chunk_page.setFixedHeight(26)
        self.btn_next_chunk_page.setStyleSheet(btn_page_style)
        self.btn_next_chunk_page.setToolTip("Trang tiếp theo (50 đoạn kế)")
        self.btn_next_chunk_page.clicked.connect(self._next_chunk_page)
        chunk_pagination_box.addWidget(self.btn_next_chunk_page)

        self.btn_last_chunk_page = QPushButton("Cuối »")
        self.btn_last_chunk_page.setFixedHeight(26)
        self.btn_last_chunk_page.setStyleSheet(btn_page_style)
        self.btn_last_chunk_page.setToolTip("Đến trang cuối cùng")
        self.btn_last_chunk_page.clicked.connect(self._last_chunk_page)
        chunk_pagination_box.addWidget(self.btn_last_chunk_page)

        right_layout.addLayout(chunk_pagination_box)

        splitter.addWidget(right_box)
        splitter.setSizes([600, 460])
        main_layout.addWidget(splitter, 2)

        # 4. Thanh điều khiển & Tiến độ (Controls & Progress)
        ctrl_box = QVBoxLayout()
        ctrl_box.setSpacing(6)

        # Hàng nút 1: 3 nút chính + Dừng + Tùy chọn Profile
        btn_row = QHBoxLayout()

        # Nút 1: Nuôi Profile
        self.btn_warm_profile = QPushButton("🛠 Nuôi Profile Mới")
        self.btn_warm_profile.setFixedHeight(38)
        self.btn_warm_profile.setToolTip("Khởi tạo và nuôi 1 Profile Chrome mới (YouTube -> VnExpress -> hCaptcha Demo) để tăng điểm uy tín")
        self.btn_warm_profile.setStyleSheet("background-color: #7C3AED; color: white; font-weight: bold; font-size: 13px; border-radius: 4px; padding: 0 16px;")
        self.btn_warm_profile.clicked.connect(lambda: self._start_warming_profile(continuous=False))
        btn_row.addWidget(self.btn_warm_profile)

        # Nút 2: Tạo Voice
        self.btn_start_voice = QPushButton("▶ Tạo Voice")
        self.btn_start_voice.setFixedHeight(38)
        self.btn_start_voice.setToolTip("Xử lý danh sách văn bản .txt thành giọng nói bằng Profile đã nuôi sẵn")
        self.btn_start_voice.setStyleSheet("background-color: #16A34A; color: white; font-weight: bold; font-size: 13px; border-radius: 4px; padding: 0 18px;")
        self.btn_start_voice.clicked.connect(self._start_voice_only)
        btn_row.addWidget(self.btn_start_voice)

        # Nút 3: Tạo Voice + Nuôi Khép kín
        self.btn_start_both = QPushButton("⚡ Tạo Voice + Nuôi (Khép kín)")
        self.btn_start_both.setFixedHeight(38)
        self.btn_start_both.setToolTip("Quy trình khép kín 1 luồng: Dùng cùng 1 IP để Nuôi Profile trước -> Rồi tạo Voice ngay trên chính IP đó để tối đa hóa trust hCaptcha")
        self.btn_start_both.setStyleSheet("background-color: #D97706; color: white; font-weight: bold; font-size: 13px; border-radius: 4px; padding: 0 16px;")
        self.btn_start_both.clicked.connect(self._start_both)
        btn_row.addWidget(self.btn_start_both)

        # Nút Dừng
        self.btn_stop = QPushButton("⏹ Dừng lại")
        self.btn_stop.setFixedHeight(38)
        self.btn_stop.setEnabled(False)
        self.btn_stop.setStyleSheet("background-color: #DC2626; color: white; font-weight: bold; font-size: 13px; border-radius: 4px; padding: 0 16px;")
        self.btn_stop.clicked.connect(self._stop_processing)
        btn_row.addWidget(self.btn_stop)

        btn_row.addSpacing(10)

        # Checkbox hiện cửa sổ khi nuôi
        self.chk_show_warm_browser = QCheckBox("Hiện cửa sổ khi nuôi")
        self.chk_show_warm_browser.setToolTip("Mặc định tắt (cửa sổ dịch ra ngoài màn hình không vướng mắt). Bật nếu muốn quan sát trực tiếp.")
        btn_row.addWidget(self.chk_show_warm_browser)

        btn_row.addSpacing(10)

        # Điều khiển số luồng chạy song song
        lbl_threads = QLabel("Số luồng:")
        lbl_threads.setStyleSheet("font-weight: bold; color: #334155;")
        btn_row.addWidget(lbl_threads)

        self.spn_thread_count = QSpinBox()
        self.spn_thread_count.setRange(1, 20)
        self.spn_thread_count.setValue(self.settings.thread_count)
        self.spn_thread_count.setFixedHeight(30)
        self.spn_thread_count.setFixedWidth(55)
        self.spn_thread_count.setToolTip("Số luồng chạy song song đồng thời cho cả Tạo Voice và Nuôi Profile (1 đến 20 luồng)")
        self.spn_thread_count.valueChanged.connect(self._on_thread_count_changed)
        btn_row.addWidget(self.spn_thread_count)

        btn_row.addStretch()

        # Nhãn đếm profile và nút mở thư mục
        self.lbl_profile_count = QLabel("Kho Profile: 0")
        self.lbl_profile_count.setStyleSheet("background-color: #F3E8FF; color: #6B21A8; font-weight: bold; padding: 4px 8px; border-radius: 4px;")
        btn_row.addWidget(self.lbl_profile_count)

        btn_open_profile = QPushButton("📂 Thư mục Profile")
        btn_open_profile.setFixedHeight(32)
        btn_open_profile.clicked.connect(self._open_profile_dir)
        btn_row.addWidget(btn_open_profile)

        ctrl_box.addLayout(btn_row)

        # Hàng 2: Progress Bar và Thống kê
        prog_row = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(24)
        self.progress_bar.setValue(0)
        prog_row.addWidget(self.progress_bar, 2)

        self.lbl_stats = QLabel("Tổng: 0 đoạn | Hoàn thành: 0")
        self.lbl_stats.setStyleSheet("font-weight: bold; color: #475569;")
        prog_row.addWidget(self.lbl_stats)

        self.lbl_warmer_status = QLabel("Trạng thái nuôi: Sẵn sàng")
        self.lbl_warmer_status.setStyleSheet("color: #7C3AED; font-weight: bold; padding-left: 10px;")
        prog_row.addWidget(self.lbl_warmer_status, 1)

        self.btn_bottom_log = QPushButton("📋 Xem Log")
        self.btn_bottom_log.setFixedHeight(28)
        self.btn_bottom_log.setStyleSheet(
            "font-weight: bold; padding: 0 14px; background-color: #EDE9FE; color: #6D28D9; "
            "border: 1px solid #C4B5FD; border-radius: 4px;"
        )
        self.btn_bottom_log.setToolTip("Mở cửa sổ theo dõi nhật ký hoạt động thời gian thực")
        self.btn_bottom_log.clicked.connect(self._open_log_window)
        prog_row.addWidget(self.btn_bottom_log)

        ctrl_box.addLayout(prog_row)
        main_layout.addLayout(ctrl_box)

    def _open_log_window(self):
        """Mở hoặc kích hoạt cửa sổ xem log thời gian thực."""
        if self.log_window.isVisible():
            self.log_window.raise_()
            self.log_window.activateWindow()
        else:
            self.log_window.show()
            self.log_window.raise_()
            self.log_window.activateWindow()

    def _populate_templates_combo(self):
        """Đổ danh sách mẫu giọng vào dropdown."""
        self.combo_templates.blockSignals(True)
        self.combo_templates.clear()
        self.combo_templates.addItem("(Tùy chỉnh / Thủ công)")

        target_idx = 0
        for idx, tmpl in enumerate(self.settings.voice_templates):
            self.combo_templates.addItem(f"📁 {tmpl.name}")
            if tmpl.name == self.settings.selected_voice_template_name:
                target_idx = idx + 1

        self.combo_templates.setCurrentIndex(target_idx)
        self.combo_templates.blockSignals(False)

    def _load_settings_to_ui(self):
        # 1. Khởi tạo template mẫu nếu danh sách đang trống
        if not self.settings.voice_templates:
            self.settings.voice_templates = [
                VoiceTemplate(
                    name="Frederick Surrey (Vũ trụ)",
                    voice_id="j9jfwdrw7BRfcR43Qohk",
                    model_index=0,
                    lang_index=0,
                    speed=0.95,
                    style=34,
                    stability=47,
                    similarity=38,
                    speaker_boost=False
                ),
                VoiceTemplate(
                    name="Rachel (Nữ Mỹ tự nhiên)",
                    voice_id="21m00Tcm4TlvDq8ikWAM",
                    model_index=0,
                    lang_index=0,
                    speed=0.90,
                    style=30,
                    stability=50,
                    similarity=40,
                    speaker_boost=False
                ),
                VoiceTemplate(
                    name="Adam (Nam trầm tự tin)",
                    voice_id="bfGb7JTLUnZebZRiFYyq",
                    model_index=0,
                    lang_index=0,
                    speed=0.90,
                    style=25,
                    stability=55,
                    similarity=45,
                    speaker_boost=False
                ),
                VoiceTemplate(
                    name="George (Nam Anh kể chuyện)",
                    voice_id="JBFqnCBsd6RMkjVDRZzb",
                    model_index=0,
                    lang_index=0,
                    speed=0.90,
                    style=20,
                    stability=60,
                    similarity=50,
                    speaker_boost=False
                ),
                VoiceTemplate(
                    name="Sarah (Nữ tự tin truyền cảm)",
                    voice_id="EXAVITQu4vr4xnSDxMaL",
                    model_index=0,
                    lang_index=0,
                    speed=0.95,
                    style=30,
                    stability=50,
                    similarity=40,
                    speaker_boost=False
                )
            ]
            if not self.settings.selected_voice_template_name:
                self.settings.selected_voice_template_name = "Frederick Surrey (Vũ trụ)"
            self.settings.save()

        self._is_loading_ui = True
        try:
            # 2. Nạp danh sách mẫu vào combobox
            self._populate_templates_combo()

            # 3. Nạp thông số vào các ô nhập
            self.txt_voice_id.setText(self.settings.voice_id)
            self.combo_model.setCurrentIndex(max(0, min(len(MODEL_IDS) - 1, self.settings.model_index)))
            self.combo_lang.setCurrentIndex(max(0, min(4, self.settings.lang_index)))
            self.num_speed.setValue(self.settings.speed)
            self.num_stab.setValue(self.settings.stability)
            self.num_sim.setValue(self.settings.similarity)
            self.num_style.setValue(self.settings.style)
            self.chk_boost.setChecked(self.settings.speaker_boost)

            # 4. Cập nhật nhãn Tên giọng
            self._update_voice_info_display(self.settings.voice_id)
        finally:
            self._is_loading_ui = False

    def _save_settings(self):
        """Lưu cấu hình hệ thống ra file JSON theo self.settings_path."""
        if hasattr(self, 'file_list'):
            excluded_set = {str(Path(ex).resolve()).lower() for ex in self.settings.excluded_files}
            customs = []
            for f in self.file_list:
                f_str = str(f.resolve())
                if f_str.lower() not in excluded_set and f_str not in customs:
                    customs.append(f_str)
            self.settings.custom_files = customs

        self.settings.save(self.settings_path)

    def _save_ui_to_settings(self):
        self.settings.voice_id = self.txt_voice_id.text().strip()
        self.settings.model_index = self.combo_model.currentIndex()
        self.settings.lang_index = self.combo_lang.currentIndex()
        self.settings.speed = self.num_speed.value()
        self.settings.stability = self.num_stab.value()
        self.settings.similarity = self.num_sim.value()
        self.settings.style = self.num_style.value()
        self.settings.speaker_boost = self.chk_boost.isChecked()
        self.settings.scan_subfolders = self.chk_subfolders.isChecked()
        if hasattr(self, 'spn_thread_count'):
            self.settings.thread_count = self.spn_thread_count.value()
        self._save_settings()

    def _update_voice_name_badge(self, voice_info: Optional[dict]):
        if voice_info:
            name = voice_info.get("name", "Không rõ")
            cat = voice_info.get("category", "")
            labels = voice_info.get("labels", {})
            parts = []
            if cat:
                parts.append(cat)
            if isinstance(labels, dict):
                for k in ["accent", "gender", "descriptive"]:
                    if k in labels and labels[k]:
                        parts.append(labels[k])
            extra = f" ({' | '.join(parts)})" if parts else ""
            self.lbl_voice_name.setText(f"✓ Tên giọng: {name}{extra}")
            self.lbl_voice_name.setStyleSheet(
                "background-color: #ECFDF5; color: #065F46; padding: 4px 10px; border-radius: 4px; font-weight: bold; border: 1px solid #A7F3D0;"
            )
            self.lbl_voice_name.setToolTip(f"Voice ID: {voice_info.get('voice_id')}\nTên giọng: {name}\nĐặc điểm: {extra}")
        else:
            self.lbl_voice_name.setText("⚠ Chưa xác định được tên giọng")
            self.lbl_voice_name.setStyleSheet(
                "background-color: #FFFBEB; color: #92400E; padding: 4px 10px; border-radius: 4px; font-weight: bold; border: 1px solid #FDE68A;"
            )
            self.lbl_voice_name.setToolTip("Voice ID chưa có trong danh mục hoặc API key chưa được cấu hình để tra cứu online.")

    def _update_voice_info_display(self, voice_id: str):
        vid = voice_id.strip()
        if not vid:
            self.lbl_voice_name.setText("🎙 Tên giọng: Chưa xác định")
            self.lbl_voice_name.setStyleSheet("background-color: #F1F5F9; color: #334155; padding: 4px 10px; border-radius: 4px; font-weight: bold;")
            return

        cached = voice_service.get_cached_voice(vid)
        if cached:
            self._update_voice_name_badge(cached)
        else:
            self.lbl_voice_name.setText(f"🎙 Voice ID: {vid} (Bấm 'Kiểm tra' để tra tên)")
            self.lbl_voice_name.setStyleSheet("background-color: #F1F5F9; color: #475569; padding: 4px 10px; border-radius: 4px;")

    def _on_voice_id_editing_finished(self):
        vid = self.txt_voice_id.text().strip()
        if not vid:
            self.lbl_voice_name.setText("🎙 Tên giọng: Chưa xác định")
            self.lbl_voice_name.setStyleSheet("background-color: #F1F5F9; color: #334155; padding: 4px 10px; border-radius: 4px; font-weight: bold;")
            return

        cached = voice_service.get_cached_voice(vid)
        if cached:
            self._update_voice_name_badge(cached)
        else:
            self._update_voice_info_display(vid)

    def _on_check_voice_clicked(self):
        """Bấm nút Kiểm tra Voice: tra cứu tên giọng trên ElevenLabs."""
        vid = self.txt_voice_id.text().strip()
        if not vid:
            QMessageBox.warning(self, "Chú ý", "Vui lòng nhập Voice ID cần kiểm tra!")
            return

        self.btn_check_voice.setEnabled(False)
        self.btn_check_voice.setText("⏳ Đang tra...")
        self.lbl_voice_name.setText("⏳ Đang tra cứu trên ElevenLabs...")
        self.lbl_voice_name.setStyleSheet("background-color: #EFF6FF; color: #1E40AF; padding: 4px 10px; border-radius: 4px;")
        QApplication.processEvents()

        info = voice_service.fetch_voice_by_id(
            voice_id=vid,
            api_key=self.settings.eleven_labs_api_key
        )
        self.btn_check_voice.setEnabled(True)
        self.btn_check_voice.setText("🔍 Kiểm tra Voice")

        if info:
            self._update_voice_name_badge(info)
            name = info.get("name", vid)
            cat = info.get("category", "")
            labels = info.get("labels", {})
            label_text = ", ".join([f"{k}: {val}" for k, val in labels.items()]) if isinstance(labels, dict) else str(labels)
            
            s = info.get("settings", {})
            msg = f"Đã tìm thấy giọng đọc trên ElevenLabs!\n\n• Tên giọng: {name}\n• Phân loại: {cat}"
            if label_text:
                msg += f"\n• Đặc điểm: {label_text}"

            if s:
                reply = QMessageBox.question(
                    self,
                    "Tìm thấy giọng đọc",
                    f"{msg}\n\nBạn có muốn tự động áp dụng thông số cài đặt mặc định của giọng này không?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if reply == QMessageBox.StandardButton.Yes:
                    if "stability" in s:
                        self.num_stab.setValue(int(float(s["stability"]) * 100))
                    if "similarity_boost" in s:
                        self.num_sim.setValue(int(float(s["similarity_boost"]) * 100))
                    if "style" in s:
                        self.num_style.setValue(int(float(s["style"]) * 100))
                    if "use_speaker_boost" in s:
                        self.chk_boost.setChecked(bool(s["use_speaker_boost"]))
                    if "speed" in s:
                        self.num_speed.setValue(float(s["speed"]))
                    self._save_ui_to_settings()
            else:
                QMessageBox.information(self, "Tìm thấy giọng đọc", msg)
        else:
            self._update_voice_name_badge(None)
            QMessageBox.warning(
                self,
                "Không tìm thấy giọng",
                f"Không tìm thấy thông tin giọng cho Voice ID:\n{vid}\n\n"
                f"Gợi ý:\n"
                f"1. Kiểm tra xem Voice ID có bị gõ thừa/thiếu ký tự không.\n"
                f"2. Nếu đây là giọng riêng/nhân bản trong tài khoản, hãy đảm bảo đã cấu hình ElevenLabsApiKey trong 'Cấu hình hệ thống' để tra cứu online."
            )

    def _on_browse_voices_clicked(self):
        """Mở hộp thoại tìm kiếm và duyệt danh sách giọng ElevenLabs."""
        dlg = VoiceSearchDialog(
            api_key=self.settings.eleven_labs_api_key,
            current_voice_id=self.txt_voice_id.text().strip(),
            parent=self
        )
        if dlg.exec() and dlg.selected_voice:
            v = dlg.selected_voice
            self.txt_voice_id.setText(v.get("voice_id", ""))
            self._update_voice_name_badge(v)

            s = v.get("settings", {})
            if s:
                if "stability" in s:
                    self.num_stab.setValue(int(float(s["stability"]) * 100))
                if "similarity_boost" in s:
                    self.num_sim.setValue(int(float(s["similarity_boost"]) * 100))
                if "style" in s:
                    self.num_style.setValue(int(float(s["style"]) * 100))
                if "use_speaker_boost" in s:
                    self.chk_boost.setChecked(bool(s["use_speaker_boost"]))
                if "speed" in s:
                    self.num_speed.setValue(float(s["speed"]))

            self._save_ui_to_settings()
            self._update_files_table()

    def _on_template_selected(self, index: int):
        """Khi người dùng chọn một mẫu giọng từ combobox."""
        if self._is_loading_ui:
            return

        if index <= 0:
            self.settings.selected_voice_template_name = ""
            return

        tmpl_idx = index - 1
        if 0 <= tmpl_idx < len(self.settings.voice_templates):
            tmpl = self.settings.voice_templates[tmpl_idx]
            self.settings.selected_voice_template_name = tmpl.name

            # Đổ dữ liệu mẫu vào giao diện
            self._is_loading_ui = True
            try:
                self.txt_voice_id.setText(tmpl.voice_id)
                self.combo_model.setCurrentIndex(max(0, min(len(MODEL_IDS) - 1, tmpl.model_index)))
                self.combo_lang.setCurrentIndex(max(0, min(4, tmpl.lang_index)))
                self.num_speed.setValue(tmpl.speed)
                self.num_style.setValue(tmpl.style)
                self.num_stab.setValue(tmpl.stability)
                self.num_sim.setValue(tmpl.similarity)
                self.chk_boost.setChecked(tmpl.speaker_boost)
            finally:
                self._is_loading_ui = False

            # Cập nhật tên giọng
            cached = voice_service.get_cached_voice(tmpl.voice_id)
            if cached:
                self._update_voice_name_badge(cached)
            else:
                self._update_voice_info_display(tmpl.voice_id)

            self._save_ui_to_settings()
            self._update_files_table()

    def _on_model_changed(self, index: int):
        """Khi người dùng thay đổi Model trên giao diện."""
        if self._is_loading_ui:
            return

        if not (0 <= index < len(MODEL_IDS)):
            return

        m_id = MODEL_IDS[index]
        self.settings.model_index = index

        # Cảnh báo khi người dùng chọn Model v4 mà không có gói trả phí
        if m_id in ("eleven_v4", "eleven_v4_turbo"):
            QMessageBox.warning(
                self,
                "Lưu ý Model v4",
                f"Mô hình '{m_id}' yêu cầu tài khoản trả phí (Paid Plan) kèm API Key của ElevenLabs.\n\n"
                "Cơ chế tạo miễn phí (Free) qua hCaptcha không hỗ trợ Model v4.\n"
                "👉 Nếu dùng Free, vui lòng chọn 'eleven_multilingual_v2' (chuẩn nhất cho tiếng Việt/Anh) hoặc 'eleven_flash_v2' / 'eleven_turbo_v2'."
            )

        # Cập nhật model_index cho template đang chọn (nếu có)
        active_tmpl_name = self.settings.selected_voice_template_name
        if active_tmpl_name:
            for vt in self.settings.voice_templates:
                if vt.name.lower() == active_tmpl_name.lower():
                    vt.model_index = index
                    break

        # Đồng bộ model_index cho các tệp đang dùng template này hoặc chưa có template riêng
        for fvp in self.settings.file_voice_profiles:
            if not fvp.voice.name or (active_tmpl_name and fvp.voice.name.lower() == active_tmpl_name.lower()) or fvp.voice.name in ("Mặc định", "Tùy chỉnh"):
                fvp.voice.model_index = index

        self._save_settings()
        self._update_files_table()

    def _on_voice_param_changed(self):
        """Khi người dùng thay đổi bất kỳ thông số giọng nào (ngôn ngữ, tốc độ, ổn định, tương đồng, style, boost)."""
        if self._is_loading_ui:
            return

        self.settings.lang_index = self.combo_lang.currentIndex()
        self.settings.speed = self.num_speed.value()
        self.settings.stability = self.num_stab.value()
        self.settings.similarity = self.num_sim.value()
        self.settings.style = self.num_style.value()
        self.settings.speaker_boost = self.chk_boost.isChecked()

        active_tmpl_name = self.settings.selected_voice_template_name
        if active_tmpl_name:
            for vt in self.settings.voice_templates:
                if vt.name.lower() == active_tmpl_name.lower():
                    vt.lang_index = self.settings.lang_index
                    vt.speed = self.settings.speed
                    vt.stability = self.settings.stability
                    vt.similarity = self.settings.similarity
                    vt.style = self.settings.style
                    vt.speaker_boost = self.settings.speaker_boost
                    break

        self._save_settings()

    def _on_save_template_clicked(self):
        """Lưu toàn bộ thông số giọng hiện tại thành mẫu mới hoặc cập nhật mẫu đã có."""
        current_name = self.settings.selected_voice_template_name or ""
        name, ok = QInputDialog.getText(
            self,
            "Lưu mẫu giọng (Voice Template)",
            "Nhập tên mẫu giọng:",
            text=current_name
        )
        if not ok or not name.strip():
            return

        name = name.strip()
        vid = self.txt_voice_id.text().strip()
        if not vid:
            QMessageBox.warning(self, "Chú ý", "Voice ID đang trống, vui lòng nhập Voice ID trước khi lưu mẫu!")
            return

        existing = next((t for t in self.settings.voice_templates if t.name.lower() == name.lower()), None)
        if existing:
            reply = QMessageBox.question(
                self,
                "Xác nhận ghi đè",
                f"Mẫu '{name}' đã tồn tại trong danh sách. Bạn có muốn cập nhật lại thông số cho mẫu này không?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

            existing.voice_id = vid
            existing.model_index = self.combo_model.currentIndex()
            existing.lang_index = self.combo_lang.currentIndex()
            existing.speed = self.num_speed.value()
            existing.style = self.num_style.value()
            existing.stability = self.num_stab.value()
            existing.similarity = self.num_sim.value()
            existing.speaker_boost = self.chk_boost.isChecked()
        else:
            new_tmpl = VoiceTemplate(
                name=name,
                voice_id=vid,
                model_index=self.combo_model.currentIndex(),
                lang_index=self.combo_lang.currentIndex(),
                speed=self.num_speed.value(),
                style=self.num_style.value(),
                stability=self.num_stab.value(),
                similarity=self.num_sim.value(),
                speaker_boost=self.chk_boost.isChecked()
            )
            self.settings.voice_templates.append(new_tmpl)

        self.settings.selected_voice_template_name = name
        self.settings.save()
        self._populate_templates_combo()
        self._update_files_table()
        QMessageBox.information(self, "Thành công", f"Đã lưu mẫu giọng '{name}' thành công!")

    def _on_delete_template_clicked(self):
        """Xóa mẫu giọng đang chọn."""
        idx = self.combo_templates.currentIndex()
        if idx <= 0:
            QMessageBox.warning(self, "Chú ý", "Vui lòng chọn một mẫu giọng cụ thể trong danh sách để xóa.")
            return

        tmpl_idx = idx - 1
        if 0 <= tmpl_idx < len(self.settings.voice_templates):
            tmpl = self.settings.voice_templates[tmpl_idx]
            reply = QMessageBox.question(
                self,
                "Xác nhận xóa",
                f"Bạn có chắc chắn muốn xóa mẫu giọng '{tmpl.name}' không?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                del self.settings.voice_templates[tmpl_idx]
                self.settings.selected_voice_template_name = ""
                self.settings.save()
                self._populate_templates_combo()
                self._update_files_table()
                QMessageBox.information(self, "Đã xóa", f"Đã xóa mẫu giọng '{tmpl.name}'.")

    def _get_current_active_voice_template(self) -> VoiceTemplate:
        """Lấy cấu hình mẫu giọng đang được chọn/thiết lập trên giao diện tại thời điểm hiện tại."""
        sel_name = self.settings.selected_voice_template_name
        tmpl_match = None
        if sel_name:
            for vt in self.settings.voice_templates:
                if vt.name == sel_name:
                    tmpl_match = vt
                    break

        vid = self.txt_voice_id.text().strip() or self.settings.voice_id
        name = tmpl_match.name if tmpl_match else (sel_name or "")
        if not name:
            cached = voice_service.get_cached_voice(vid)
            name = cached.get("name", "Tùy chỉnh") if cached else "Tùy chỉnh"

        return VoiceTemplate(
            name=name,
            voice_id=vid,
            model_index=self.combo_model.currentIndex(),
            lang_index=self.combo_lang.currentIndex(),
            speed=self.num_speed.value(),
            style=self.num_style.value(),
            stability=self.num_stab.value(),
            similarity=self.num_sim.value(),
            speaker_boost=self.chk_boost.isChecked()
        )

    def _assign_voice_to_file(self, file_path: Path, voice: VoiceTemplate, save: bool = True):
        """Gán cố định một mẫu giọng cho tệp cụ thể."""
        target_str = str(file_path.resolve()).lower()
        self.settings.file_voice_profiles = [
            f for f in self.settings.file_voice_profiles
            if str(Path(f.file_path).resolve()).lower() != target_str
        ]
        self.settings.file_voice_profiles.append(
            FileVoiceProfile(
                file_path=str(file_path.resolve()),
                voice=voice.model_copy()
            )
        )
        if save:
            self._save_settings()

    def _has_file_voice(self, file_path: Path) -> bool:
        """Kiểm tra tệp đã có cấu hình mẫu giọng riêng chưa."""
        target_str = str(file_path.resolve()).lower()
        for f in self.settings.file_voice_profiles:
            try:
                if str(Path(f.file_path).resolve()).lower() == target_str:
                    return True
            except Exception:
                pass
        return False

    def _assign_voice_to_multiple_files(self, files: List[Path], template: VoiceTemplate):
        """Gán mẫu giọng hàng loạt cho nhiều tệp đang chọn."""
        for f in files:
            self._assign_voice_to_file(f, template, save=False)
        self._save_settings()
        self._update_files_table()
        msg = (
            f"Đã gán mẫu giọng '{template.name}' cho {len(files)} tệp."
            if len(files) > 1
            else f"Đã gán mẫu giọng '{template.name}' cho tệp {files[0].name}."
        )
        QMessageBox.information(self, "Thành công", msg)

    def _assign_model_to_multiple_files(self, files: List[Path], model_index: int):
        """Gán Model cho danh sách tệp cụ thể."""
        target_resolved = {str(f.resolve()).lower(): f for f in files}
        for fvp in self.settings.file_voice_profiles:
            if fvp.file_path and str(Path(fvp.file_path).resolve()).lower() in target_resolved:
                fvp.voice.model_index = model_index

        for f in files:
            if not self._has_file_voice(f):
                prof = self._resolve_voice_profile_for_file(f).model_copy()
                prof.model_index = model_index
                self._assign_voice_to_file(f, prof, save=False)

        self._save_settings()
        self._update_files_table()
        m_name = MODEL_IDS[model_index] if 0 <= model_index < len(MODEL_IDS) else str(model_index)
        QMessageBox.information(self, "Đã đổi Model", f"Đã áp dụng Model '{m_name}' cho {len(files)} tệp.")

    def _apply_model_to_all_files(self, model_index: int):
        """Áp dụng Model cho toàn bộ tệp trong danh sách."""
        if not self.file_list:
            QMessageBox.information(self, "Thông báo", "Danh sách tệp đang trống.")
            return
        self._assign_model_to_multiple_files(self.file_list, model_index)

    def _apply_voice_to_all_files(self, voice: VoiceTemplate):
        """Áp dụng mẫu giọng cho toàn bộ tệp trong danh sách."""
        if not self.file_list:
            QMessageBox.information(self, "Thông báo", "Danh sách tệp đang trống.")
            return
        self._assign_voice_to_multiple_files(self.file_list, voice)

    def _table_files_key_press(self, event):
        """Xử lý phím tắt khi người dùng tương tác trên bảng danh sách tệp (Delete / Backspace để xóa hàng)."""
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self._delete_selected_files()
            event.accept()
        else:
            QTableWidget.keyPressEvent(self.table_files, event)

    def _delete_selected_files(self):
        """Xóa các hàng tệp .txt đang được chọn khỏi danh sách xử lý."""
        if self.bridge_thread and self.bridge_thread.isRunning():
            QMessageBox.warning(
                self,
                "Chú ý",
                "Tiến trình tạo voice đang chạy. Vui lòng dừng tiến trình trước khi xóa tệp khỏi danh sách!"
            )
            return

        selected_rows = sorted(list(set(item.row() for item in self.table_files.selectedItems())), reverse=True)
        if not selected_rows:
            cur_row = self.table_files.currentRow()
            if 0 <= cur_row < len(self.file_list):
                selected_rows = [cur_row]
            else:
                QMessageBox.information(
                    self,
                    "Thông báo",
                    "Vui lòng chọn ít nhất một hàng tệp .txt trong bảng để xóa!\n\n"
                    "(Mẹo: Bạn có thể click chọn 1 hàng hoặc giữ Ctrl / Shift để chọn nhiều hàng, sau đó bấm 'Xóa row' hoặc phím Delete)"
                )
                return

        candidate_idx = min(selected_rows) if selected_rows else 0
        target_files = [self.file_list[r] for r in selected_rows if 0 <= r < len(self.file_list)]
        if not target_files:
            return

        self._remove_multiple_files_from_list(target_files, next_selected_index=candidate_idx)

    def _clear_all_files(self):
        """Xóa toàn bộ danh sách tệp .txt trong bảng."""
        if self.bridge_thread and self.bridge_thread.isRunning():
            QMessageBox.warning(
                self,
                "Chú ý",
                "Tiến trình tạo voice đang chạy. Vui lòng dừng tiến trình trước khi làm trống danh sách!"
            )
            return

        if not self.file_list:
            QMessageBox.information(self, "Thông báo", "Danh sách tệp đang trống sẵn!")
            return

        reply = QMessageBox.question(
            self,
            "Xác nhận xóa tất cả",
            f"Bạn có chắc chắn muốn xóa toàn bộ {len(self.file_list)} tệp .txt khỏi danh sách không?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            excluded_set = {str(Path(ex).resolve()).lower() for ex in self.settings.excluded_files}
            for f in self.file_list:
                f_str = str(f.resolve())
                if f_str.lower() not in excluded_set:
                    self.settings.excluded_files.append(f_str)
                    excluded_set.add(f_str.lower())
            self.file_list.clear()
            if hasattr(self.settings, 'custom_files'):
                self.settings.custom_files.clear()
            self._save_settings()
            self._update_files_table()

    def _delete_files_from_disk(self, files: List[Path]):
        """Xóa vĩnh viễn các tệp .txt đã chọn trên ổ cứng máy tính."""
        if self.bridge_thread and self.bridge_thread.isRunning():
            QMessageBox.warning(
                self,
                "Chú ý",
                "Tiến trình tạo voice đang chạy. Vui lòng dừng tiến trình trước khi xóa tệp!"
            )
            return

        file_names = "\n".join([f"• {f.name}" for f in files[:5]])
        if len(files) > 5:
            file_names += f"\n... và {len(files) - 5} tệp khác"

        reply = QMessageBox.warning(
            self,
            "CẢNH BÁO: XÓA TỆP TRÊN Ổ CỨNG",
            f"Bạn có CHẮC CHẮN muốn XÓA VĨNH VIỄN {len(files)} tệp .txt sau đây trên ổ cứng không?\n\n"
            f"{file_names}\n\n"
            f"⚠ Lưu ý: Tệp sẽ bị xóa hoàn toàn khỏi máy tính và không thể khôi phục!",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        deleted_count = 0
        failed_count = 0
        for f in files:
            try:
                if f.exists():
                    f.unlink()
                deleted_count += 1
            except Exception as e:
                logger.error(f"Lỗi khi xóa tệp {f} trên ổ cứng: {e}")
                failed_count += 1

        # Xóa cả trong excluded_files nếu có
        target_resolved = {str(f.resolve()).lower() for f in files}
        self.settings.excluded_files = [
            ex for ex in self.settings.excluded_files
            if str(Path(ex).resolve()).lower() not in target_resolved
        ]

        self._remove_multiple_files_from_list(files)
        if failed_count == 0:
            QMessageBox.information(self, "Đã xóa tệp", f"Đã xóa thành công {deleted_count} tệp .txt trên ổ cứng.")
        else:
            QMessageBox.warning(self, "Kết quả xóa", f"Đã xóa {deleted_count} tệp, gặp lỗi {failed_count} tệp (có thể do tệp đang mở).")

    def _remove_multiple_files_from_list(self, files: List[Path], next_selected_index: Optional[int] = None):
        """Xóa nhiều tệp khỏi danh sách, ghi nhớ vào excluded_files và xóa cấu hình voice riêng."""
        target_resolved = {str(f.resolve()).lower() for f in files}
        self.file_list = [
            f for f in self.file_list
            if str(f.resolve()).lower() not in target_resolved
        ]
        self.settings.file_voice_profiles = [
            fvp for fvp in self.settings.file_voice_profiles
            if str(Path(fvp.file_path).resolve()).lower() not in target_resolved
        ]
        if hasattr(self.settings, 'custom_files'):
            self.settings.custom_files = [
                cf for cf in self.settings.custom_files
                if str(Path(cf).resolve()).lower() not in target_resolved
            ]

        # Ghi nhớ các file này vào danh sách loại trừ để khi mở lại app không bị quét nạp lại
        excluded_set = {str(Path(ex).resolve()).lower() for ex in self.settings.excluded_files}
        for f in files:
            f_str = str(f.resolve())
            if f_str.lower() not in excluded_set:
                self.settings.excluded_files.append(f_str)
                excluded_set.add(f_str.lower())

        self._save_settings()
        if next_selected_index is not None:
            self.selected_file_index = next_selected_index
        self._update_files_table()

    def _on_current_cell_changed(self, current_row: int, current_col: int, previous_row: int, previous_col: int):
        """Khi con trỏ ô hoặc hàng thay đổi (qua click chuột hoặc phím mũi tên)."""
        if 0 <= current_row < len(self.file_list) and current_row != self.selected_file_index:
            self._on_file_selected(current_row, current_col)

    def _prompt_change_voice_for_file(self, file_path: Path):
        """Mở hộp thoại chọn mẫu giọng nhanh cho tệp khi nhấp đúp vào cột giọng."""
        options = []
        for t in self.settings.voice_templates:
            options.append(f"Mẫu: {t.name}")
        options.append("Áp dụng thông số giọng hiện tại trên giao diện")

        current_prof = self._resolve_voice_profile_for_file(file_path)
        cur_opt = f"Mẫu: {current_prof.name}" if f"Mẫu: {current_prof.name}" in options else options[0]
        cur_idx = options.index(cur_opt) if cur_opt in options else 0

        chosen, ok = QInputDialog.getItem(
            self,
            "Đổi mẫu giọng cho tệp",
            f"Chọn mẫu giọng áp dụng cho tệp:\n{file_path.name}",
            options,
            cur_idx,
            False
        )
        if ok and chosen:
            if chosen == "Áp dụng thông số giọng hiện tại trên giao diện":
                self._assign_voice_to_file(file_path, self._get_current_active_voice_template(), save=True)
            else:
                tmpl_name = chosen.replace("Mẫu: ", "").strip()
                for t in self.settings.voice_templates:
                    if t.name == tmpl_name:
                        self._assign_voice_to_file(file_path, t, save=True)
                        break
            self._update_files_table()

    def _resolve_voice_profile_for_file(self, file_path: Path) -> VoiceTemplate:
        """Xác định cấu hình giọng cho từng file theo tệp, theo thư mục hoặc fallback."""
        file_resolved = str(file_path.resolve()).lower()

        # 1. Ưu tiên cao nhất: FileVoiceProfiles (mẫu giọng gán cho file tại thời điểm thêm)
        for fvp in self.settings.file_voice_profiles:
            if fvp.file_path:
                try:
                    if str(Path(fvp.file_path).resolve()).lower() == file_resolved:
                        if fvp.voice.name:
                            for vt in self.settings.voice_templates:
                                if vt.name.lower() == fvp.voice.name.lower():
                                    return vt
                        return fvp.voice
                except Exception:
                    if fvp.file_path.lower() == file_resolved:
                        if fvp.voice.name:
                            for vt in self.settings.voice_templates:
                                if vt.name.lower() == fvp.voice.name.lower():
                                    return vt
                        return fvp.voice

        # 2. Kiểm tra FolderVoiceProfiles
        file_dir = str(file_path.parent.resolve()).lower()
        for fvp in self.settings.folder_voice_profiles:
            if fvp.folder_path:
                try:
                    p_folder = str(Path(fvp.folder_path).resolve()).lower()
                    if file_dir == p_folder or file_dir.startswith(p_folder + "\\") or file_dir.startswith(p_folder + "/"):
                        if fvp.voice.name:
                            for vt in self.settings.voice_templates:
                                if vt.name.lower() == fvp.voice.name.lower():
                                    return vt
                        return fvp.voice
                except Exception:
                    pass

        # 3. Fallback: Nếu file chưa có mẫu riêng thì dùng mẫu đang chọn trên UI
        if self.settings.selected_voice_template_name:
            for vt in self.settings.voice_templates:
                if vt.name.lower() == self.settings.selected_voice_template_name.lower():
                    return vt.model_copy()

        return VoiceTemplate(
            name="Mặc định",
            voice_id=self.settings.voice_id,
            model_index=self.combo_model.currentIndex(),
            lang_index=self.combo_lang.currentIndex(),
            speed=self.num_speed.value(),
            style=self.num_style.value(),
            stability=self.num_stab.value(),
            similarity=self.num_sim.value(),
            speaker_boost=self.chk_boost.isChecked()
        )

    def _get_output_mp3_path(self, file_path: Path) -> Path:
        """Xác định đường dẫn file MP3 đầu ra theo cấu hình hậu tố (output_file_suffix)."""
        suffix = self.settings.output_file_suffix or ""
        if suffix.lower().endswith(".mp3"):
            suffix = suffix[:-4]
        return file_path.parent / f"{file_path.stem}{suffix}.mp3"

    def _on_file_double_clicked(self, row: int, col: int):
        """Nhấp đúp chuột vào hàng:
        - Nếu nhấp cột 'Mẫu giọng áp dụng' (col == 2): Đổi mẫu giọng cho tệp này.
        - Các cột khác: Mở file MP3 kết quả nếu có, hoặc mở thư mục chứa.
        """
        if not (0 <= row < len(self.file_list)):
            return

        file_path = self.file_list[row]
        if col == 2:
            self._prompt_change_voice_for_file(file_path)
            return

        out_mp3 = self._get_output_mp3_path(file_path)
        if out_mp3.exists() and out_mp3.stat().st_size > 0:
            os.startfile(str(out_mp3))
        else:
            os.startfile(str(file_path.parent))

    def _play_selected_output_file(self):
        """Mở/Phát file MP3 kết quả của tệp đang chọn."""
        if 0 <= self.selected_file_index < len(self.file_list):
            file_path = self.file_list[self.selected_file_index]
            out_mp3 = self._get_output_mp3_path(file_path)
            if out_mp3.exists() and out_mp3.stat().st_size > 0:
                os.startfile(str(out_mp3))
            else:
                QMessageBox.information(
                    self,
                    "Thông báo",
                    f"Tệp MP3 đầu ra chưa hoàn thành hoặc chưa được tạo:\n{out_mp3.name}"
                )
        else:
            QMessageBox.information(self, "Thông báo", "Vui lòng chọn 1 tệp trong bảng danh sách.")

    def _open_selected_output_folder(self):
        """Mở thư mục chứa file MP3 đầu ra của tệp đang chọn trong Windows Explorer."""
        if 0 <= self.selected_file_index < len(self.file_list):
            file_path = self.file_list[self.selected_file_index]
            os.startfile(str(file_path.parent))
        elif self.file_list:
            os.startfile(str(self.file_list[0].parent))
        elif self.settings.folder and Path(self.settings.folder).exists():
            os.startfile(str(self.settings.folder))
        else:
            QMessageBox.information(self, "Thông báo", "Chưa có thư mục hoặc tệp nào được chọn.")

    def _on_files_context_menu(self, pos: QPoint):
        """Menu chuột phải trên bảng danh sách tệp (hỗ trợ chọn 1 hoặc nhiều tệp)."""
        selected_rows = sorted(list(set(item.row() for item in self.table_files.selectedItems())))
        clicked_row = self.table_files.rowAt(pos.y())
        if clicked_row >= 0 and clicked_row not in selected_rows:
            selected_rows = [clicked_row]
        if not selected_rows:
            return

        target_files = [self.file_list[r] for r in selected_rows if 0 <= r < len(self.file_list)]
        if not target_files:
            return

        file_path = target_files[0]
        out_mp3 = self._get_output_mp3_path(file_path)
        out_exists = out_mp3.exists() and out_mp3.stat().st_size > 0

        menu = QMenu(self)

        # 1. Phát/Mở file MP3 kết quả (nếu chọn 1 file và đã có)
        if len(target_files) == 1 and out_exists:
            action_play = menu.addAction(f"▶ Mở / Nghe file MP3 ({out_mp3.name})")
            action_play.triggered.connect(lambda: os.startfile(str(out_mp3)))
            menu.addSeparator()

        # 2. Đổi mẫu giọng cho (các) tệp đang chọn
        label_target = f"tệp '{file_path.name}'" if len(target_files) == 1 else f"{len(target_files)} tệp đang chọn"
        sub_menu_voice = menu.addMenu(f"🎙 Đổi mẫu giọng cho {label_target}")
        for tmpl in self.settings.voice_templates:
            action = sub_menu_voice.addAction(f"Mẫu: {tmpl.name}")
            action.triggered.connect(lambda checked, t=tmpl, flist=target_files: self._assign_voice_to_multiple_files(flist, t))

        action_curr = sub_menu_voice.addAction("Áp dụng thông số giọng hiện tại trên giao diện")
        action_curr.triggered.connect(lambda checked, flist=target_files: self._assign_voice_to_multiple_files(flist, self._get_current_active_voice_template()))

        menu.addSeparator()

        # 2b. Đổi Model cho (các) tệp đang chọn
        curr_model_idx = self.combo_model.currentIndex()
        curr_model_name = MODEL_IDS[curr_model_idx] if 0 <= curr_model_idx < len(MODEL_IDS) else "eleven_multilingual_v2"
        sub_menu_model = menu.addMenu(f"⚡ Đổi Model cho {label_target}")
        act_curr_model = sub_menu_model.addAction(f"Áp dụng Model trên thanh công cụ ({curr_model_name})")
        act_curr_model.triggered.connect(lambda checked, flist=target_files, midx=curr_model_idx: self._assign_model_to_multiple_files(flist, midx))
        sub_menu_model.addSeparator()
        for idx, m_name in enumerate(MODEL_IDS):
            act_m = sub_menu_model.addAction(m_name)
            act_m.triggered.connect(lambda checked, flist=target_files, midx=idx: self._assign_model_to_multiple_files(flist, midx))

        # 2c. Áp dụng cho TOÀN BỘ danh sách tệp
        if len(self.file_list) > 1:
            active_tmpl_name = self.settings.selected_voice_template_name or "Mặc định"
            act_all_model = menu.addAction(f"⚡ Áp dụng Model '{curr_model_name}' cho TOÀN BỘ tệp")
            act_all_model.triggered.connect(lambda checked, midx=curr_model_idx: self._apply_model_to_all_files(midx))
            act_all_voice = menu.addAction(f"🎙 Áp dụng Mẫu giọng '{active_tmpl_name}' cho TOÀN BỘ tệp")
            act_all_voice.triggered.connect(lambda checked: self._apply_voice_to_all_files(self._get_current_active_voice_template()))

        menu.addSeparator()

        # 3. Gán mẫu giọng cho thư mục chứa file
        sub_menu_assign = menu.addMenu(f"📁 Gán mẫu giọng cho toàn bộ thư mục: {file_path.parent.name}")
        for tmpl in self.settings.voice_templates:
            action = sub_menu_assign.addAction(f"Áp dụng: {tmpl.name}")
            action.triggered.connect(lambda checked, t=tmpl, p=file_path.parent: self._assign_folder_template(p, t))

        action_clear_folder = sub_menu_assign.addAction("Hủy gán riêng thư mục (Dùng mẫu tệp/chung)")
        action_clear_folder.triggered.connect(lambda: self._clear_folder_template(file_path.parent))

        menu.addSeparator()

        # 4. Mở thư mục
        action_open_dir = menu.addAction("📂 Mở thư mục chứa file trong Explorer")
        action_open_dir.triggered.connect(lambda: os.startfile(str(file_path.parent)))

        menu.addSeparator()

        # 5. Xóa file khỏi danh sách
        action_remove = menu.addAction(f"🗑 Xóa {label_target} khỏi danh sách (Delete)")
        action_remove.triggered.connect(lambda: self._remove_multiple_files_from_list(target_files))

        # 6. Xóa toàn bộ danh sách
        if len(self.file_list) > 1:
            action_clear = menu.addAction("🧹 Xóa toàn bộ danh sách (Làm trống bảng)")
            action_clear.triggered.connect(self._clear_all_files)

        # 6b. Khôi phục các tệp đã xóa khỏi danh sách
        if self.settings.excluded_files:
            action_restore = menu.addAction(f"🔄 Khôi phục {len(self.settings.excluded_files)} tệp đã xóa khỏi danh sách...")
            action_restore.triggered.connect(self._restore_excluded_files)

        menu.addSeparator()

        # 7. Xóa vĩnh viễn tệp trên đĩa
        action_del_disk = menu.addAction(f"❌ Xóa vĩnh viễn {label_target} trên ổ đĩa...")
        action_del_disk.triggered.connect(lambda: self._delete_files_from_disk(target_files))

        menu.exec(self.table_files.viewport().mapToGlobal(pos))

    def _restore_excluded_files(self):
        """Khôi phục lại các tệp đã xóa khỏi danh sách và quét lại từ thư mục."""
        count = len(self.settings.excluded_files)
        reply = QMessageBox.question(
            self,
            "Khôi phục tệp",
            f"Bạn có muốn khôi phục lại {count} tệp đã xóa khỏi danh sách trước đây không?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.settings.excluded_files.clear()
            self._save_settings()
            self._rescan_files()
            QMessageBox.information(self, "Đã khôi phục", "Đã khôi phục và nạp lại toàn bộ tệp từ thư mục.")

    def _assign_folder_template(self, folder_path: Path, template: VoiceTemplate):
        folder_str = str(folder_path.resolve())
        # Xóa profile cũ nếu có
        self.settings.folder_voice_profiles = [
            f for f in self.settings.folder_voice_profiles
            if Path(f.folder_path).resolve() != folder_path.resolve()
        ]
        self.settings.folder_voice_profiles.append(
            FolderVoiceProfile(folder_path=folder_str, voice=template)
        )
        self._save_settings()
        self._update_files_table()
        QMessageBox.information(
            self,
            "Đã gán mẫu giọng",
            f"Thư mục '{folder_path.name}' đã được gán mẫu giọng '{template.name}'!"
        )

    def _clear_folder_template(self, folder_path: Path):
        self.settings.folder_voice_profiles = [
            f for f in self.settings.folder_voice_profiles
            if Path(f.folder_path).resolve() != folder_path.resolve()
        ]
        self._save_settings()
        self._update_files_table()
        QMessageBox.information(
            self,
            "Thông báo",
            f"Đã hủy cấu hình giọng riêng cho thư mục '{folder_path.name}'."
        )

    def _remove_file_from_list(self, row: int):
        if 0 <= row < len(self.file_list):
            self._remove_multiple_files_from_list([self.file_list[row]])

    def _open_settings(self):
        self._save_ui_to_settings()
        dlg = SettingsDialog(self.settings, self)
        if dlg.exec():
            self._load_settings_to_ui()

    def _on_subfolders_toggled(self, checked: bool):
        self.settings.scan_subfolders = checked
        self._rescan_files()

    def _add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Chọn thư mục chứa tệp .txt")
        if folder:
            if folder not in self.settings.folders:
                self.settings.folders.append(folder)
            self.settings.folder = folder
            self._save_settings()

            active_voice = self._get_current_active_voice_template()
            new_files = collect_txt_files(
                folders=[folder],
                include_subfolders=self.chk_subfolders.isChecked(),
                excluded_files=self.settings.excluded_files
            )
            for f in new_files:
                p = Path(f).resolve()
                if p not in self.file_list:
                    self.file_list.append(p)
                if not self._has_file_voice(p):
                    self._assign_voice_to_file(p, active_voice, save=False)
            self._save_settings()
            self._update_files_table()

    def _add_file(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Chọn tệp văn bản .txt", "", "Text Files (*.txt)")
        if files:
            active_voice = self._get_current_active_voice_template()
            added_set = {str(Path(f).resolve()).lower() for f in files}
            # Nếu người dùng chủ động nạp tệp bằng tay, gỡ bỏ tệp đó khỏi danh sách loại trừ
            self.settings.excluded_files = [
                ex for ex in self.settings.excluded_files
                if str(Path(ex).resolve()).lower() not in added_set
            ]
            for f in files:
                p = Path(f).resolve()
                if p not in self.file_list:
                    self.file_list.append(p)
                f_str = str(p)
                if f_str not in self.settings.custom_files:
                    self.settings.custom_files.append(f_str)
                # Mỗi lần thêm file lẻ, gán mẫu giọng tại thời điểm thêm
                self._assign_voice_to_file(p, active_voice, save=False)
            self._save_settings()
            self._update_files_table()

    def _rescan_files(self, clear_excluded: bool = False):
        if clear_excluded:
            self.settings.excluded_files.clear()
            self._save_settings()

        excluded_set = {str(Path(ex).resolve()).lower() for ex in self.settings.excluded_files}

        # 1. Thu thập tất cả các thư mục hợp lệ (loại bỏ thư mục temp)
        candidate_folders = []
        if self.settings.folders:
            for f in self.settings.folders:
                if f and Path(f).exists() and Path(f).is_dir():
                    f_res = str(Path(f).resolve())
                    if f_res not in candidate_folders:
                        candidate_folders.append(f_res)
        if self.settings.folder and Path(self.settings.folder).exists() and Path(self.settings.folder).is_dir():
            f_res = str(Path(self.settings.folder).resolve())
            if f_res not in candidate_folders:
                candidate_folders.append(f_res)

        self.settings.folders = candidate_folders

        scanned = []
        if candidate_folders:
            scanned = collect_txt_files(
                folders=candidate_folders,
                include_subfolders=self.chk_subfolders.isChecked(),
                excluded_files=self.settings.excluded_files
            )

        # 2. Thu thập các tệp lẻ đã thêm (từ custom_files và file_voice_profiles)
        extra_files = []
        if hasattr(self.settings, 'custom_files') and self.settings.custom_files:
            for cf in self.settings.custom_files:
                p = Path(cf)
                if p.exists() and p.is_file() and str(p.resolve()).lower() not in excluded_set:
                    p_res = p.resolve()
                    if p_res not in extra_files:
                        extra_files.append(p_res)

        for fvp in self.settings.file_voice_profiles:
            if fvp.file_path:
                p = Path(fvp.file_path)
                if p.exists() and p.is_file() and str(p.resolve()).lower() not in excluded_set:
                    p_res = p.resolve()
                    if p_res not in extra_files:
                        extra_files.append(p_res)

        # 3. Giữ lại các file đang có nếu hợp lệ
        existing_valid = [f for f in self.file_list if f.exists() and str(f.resolve()).lower() not in excluded_set]

        # 4. Hợp nhất tất cả các tệp
        all_files = []
        for p in scanned:
            if p not in all_files:
                all_files.append(p)
        for p in extra_files:
            if p not in all_files:
                all_files.append(p)
        for p in existing_valid:
            if p not in all_files:
                all_files.append(p)

        self.file_list = all_files

        # 5. Gán voice profile nếu file chưa có
        active_voice = self._get_current_active_voice_template()
        for p in self.file_list:
            if not self._has_file_voice(p):
                self._assign_voice_to_file(p, active_voice, save=False)

        self._save_settings()
        self._update_files_table()

    def _get_file_chunks(self, file_idx: int, file_path: Path) -> List[dict]:
        """Lấy danh sách các đoạn (chunks) và trạng thái tệp MP3 đã tồn tại."""
        if file_idx in self.file_chunks_cache:
            return self.file_chunks_cache[file_idx]

        cache = []
        try:
            content = file_path.read_text(encoding="utf-8-sig", errors="replace")
            chunks = split_text_by_sentences(content, max_length=self.settings.chunk_size)
            chunk_dir = file_path.parent / file_path.stem
            out_mp3 = self._get_output_mp3_path(file_path)
            out_exists = out_mp3.exists() and out_mp3.stat().st_size > 0

            for c_idx, text in enumerate(chunks):
                stt = c_idx + 1
                part_path = chunk_dir / f"{stt}.mp3"
                if not part_path.exists():
                    old_candidates = [
                        chunk_dir / f"part_{c_idx}.mp3",
                        chunk_dir / f"part_{stt}.mp3",
                        chunk_dir / f"Part_{c_idx}.mp3",
                        chunk_dir / f"Part_{stt}.mp3",
                    ]
                    for old_p in old_candidates:
                        if old_p.exists() and old_p.stat().st_size > 0:
                            try:
                                old_p.rename(part_path)
                                break
                            except Exception:
                                pass

                part_exists = part_path.exists() and part_path.stat().st_size > 0
                is_done = out_exists or part_exists
                note = "Đã có trong tệp MP3 hoàn chỉnh." if out_exists else ("Đoạn MP3 đã có sẵn." if part_exists else "")
                cache.append({
                    "text": text,
                    "status": "Hoàn thành" if is_done else "Đang chờ",
                    "note": note
                })
        except Exception as e:
            logger.error(f"Lỗi khi đọc file {file_path}: {e}")

        self.file_chunks_cache[file_idx] = cache
        return cache

    def _update_files_table(self):
        self.table_files.setRowCount(0)
        self.file_chunks_cache.clear()

        for idx, file_path in enumerate(self.file_list):
            row = self.table_files.rowCount()
            self.table_files.insertRow(row)

            # Cột 0: STT
            item_stt = QTableWidgetItem(str(idx + 1))
            item_stt.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table_files.setItem(row, 0, item_stt)

            # Cột 1: Đường dẫn file (dài nhất, hiển thị trọn vẹn path)
            item_path = QTableWidgetItem(str(file_path))
            item_path.setToolTip(str(file_path))
            self.table_files.setItem(row, 1, item_path)

            # Cột 2: Mẫu giọng áp dụng
            voice_prof = self._resolve_voice_profile_for_file(file_path)
            tmpl_name = voice_prof.name if voice_prof.name else (self.settings.selected_voice_template_name or "Mặc định")
            m_idx = voice_prof.model_index
            m_id = MODEL_IDS[m_idx] if 0 <= m_idx < len(MODEL_IDS) else "eleven_multilingual_v2"
            short_model = "v2" if m_id == "eleven_multilingual_v2" else ("v4" if m_id == "eleven_v4" else m_id.replace("eleven_", ""))

            item_voice = QTableWidgetItem(f"🎙 {tmpl_name} [{short_model}]")
            if is_v4_model(m_idx):
                item_voice.setForeground(QColor("#D97706"))
            else:
                item_voice.setForeground(QColor("#4C1D95"))

            item_voice.setToolTip(
                f"Mẫu giọng: {tmpl_name}\n"
                f"Model: {m_id} (Index {m_idx})\n"
                f"Voice ID: {voice_prof.voice_id}\n"
                f"Tốc độ: {voice_prof.speed}x | Ổn định: {voice_prof.stability}% | Tương đồng: {voice_prof.similarity}%\n"
                f"(Nhấp đúp chuột hoặc click chuột phải để đổi mẫu giọng hoặc Model)"
            )
            self.table_files.setItem(row, 2, item_voice)

            # Cột 3 & 4: Tiến độ & Tệp đầu ra (Output)
            chunks = self._get_file_chunks(idx, file_path)
            total_chunks = len(chunks)
            out_mp3 = self._get_output_mp3_path(file_path)
            out_exists = out_mp3.exists() and out_mp3.stat().st_size > 0

            if out_exists:
                completed_count = total_chunks
            else:
                completed_count = sum(1 for c in chunks if c.get("status") == "Hoàn thành")

            prog_str = f"{completed_count}/{total_chunks}"
            item_prog = QTableWidgetItem(prog_str)
            item_prog.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            font = item_prog.font()
            font.setBold(True)
            item_prog.setFont(font)

            if total_chunks > 0 and completed_count == total_chunks:
                item_prog.setForeground(QColor("#16A34A"))
                item_prog.setToolTip("Đã hoàn thành toàn bộ")
            elif completed_count > 0:
                item_prog.setForeground(QColor("#2563EB"))
                item_prog.setToolTip(f"Đã hoàn thành {completed_count}/{total_chunks} đoạn")
            else:
                item_prog.setForeground(QColor("#64748B"))
                item_prog.setToolTip("Chưa xử lý")

            self.table_files.setItem(row, 3, item_prog)

            # Cột 4: Tệp đầu ra (Output)
            if out_exists:
                size_mb = out_mp3.stat().st_size / (1024 * 1024)
                item_out = QTableWidgetItem(f"🔊 {out_mp3.name} ({size_mb:.1f} MB)")
                item_out.setForeground(QColor("#16A34A"))
                item_out.setToolTip(f"Đã có file MP3 đầu ra hoàn chỉnh:\n{out_mp3}\nNhấp đúp chuột để nghe/mở file.")
            else:
                item_out = QTableWidgetItem(f"⏳ Chưa có ({out_mp3.name})")
                item_out.setForeground(QColor("#94A3B8"))
                item_out.setToolTip(f"Tệp MP3 đầu ra dự kiến:\n{out_mp3}")

            self.table_files.setItem(row, 4, item_out)

        if self.file_list:
            target_idx = max(0, min(self.selected_file_index, len(self.file_list) - 1))
            self.selected_file_index = target_idx
            self.table_files.blockSignals(True)
            self.table_files.selectRow(target_idx)
            self.table_files.setCurrentCell(target_idx, 0)
            self.table_files.blockSignals(False)
            self._on_file_selected(target_idx, 0)
        else:
            self.selected_file_index = -1
            self.table_chunks.setRowCount(0)
            self.chunk_current_page = 1
            self.chunk_total_pages = 1
            self._update_chunk_pagination_controls(0)
            self.lbl_selected_file.setText("Chi tiết đoạn văn bản (Danh sách đang trống)")
            self.lbl_stats.setText("Tổng: 0 đoạn | Hoàn thành: 0")
            self.progress_bar.setValue(0)

    def _on_file_selected(self, row: int, col: int):
        if 0 <= row < len(self.file_list):
            if row != self.selected_file_index:
                self.chunk_current_page = 1
            self.selected_file_index = row
            file_path = self.file_list[row]
            self.lbl_selected_file.setText(f"Chi tiết các đoạn: {file_path.name}")
            self._render_chunks_for_file(row)

    def _first_chunk_page(self):
        if self.chunk_current_page > 1:
            self._render_chunks_for_file(self.selected_file_index, page=1)

    def _prev_chunk_page(self):
        if self.chunk_current_page > 1:
            self._render_chunks_for_file(self.selected_file_index, page=self.chunk_current_page - 1)

    def _next_chunk_page(self):
        if self.chunk_current_page < self.chunk_total_pages:
            self._render_chunks_for_file(self.selected_file_index, page=self.chunk_current_page + 1)

    def _last_chunk_page(self):
        if self.chunk_current_page < self.chunk_total_pages:
            self._render_chunks_for_file(self.selected_file_index, page=self.chunk_total_pages)

    def _update_chunk_pagination_controls(self, total_chunks: int):
        if total_chunks <= 0:
            self.lbl_chunk_page_info.setText("Trang 1/1 (0 đoạn)")
            self.btn_first_chunk_page.setEnabled(False)
            self.btn_prev_chunk_page.setEnabled(False)
            self.btn_next_chunk_page.setEnabled(False)
            self.btn_last_chunk_page.setEnabled(False)
            return

        start_num = (self.chunk_current_page - 1) * self.chunk_page_size + 1
        end_num = min(self.chunk_current_page * self.chunk_page_size, total_chunks)

        self.lbl_chunk_page_info.setText(
            f"Trang {self.chunk_current_page}/{self.chunk_total_pages} (Đoạn {start_num}–{end_num} / {total_chunks})"
        )
        self.btn_first_chunk_page.setEnabled(self.chunk_current_page > 1)
        self.btn_prev_chunk_page.setEnabled(self.chunk_current_page > 1)
        self.btn_next_chunk_page.setEnabled(self.chunk_current_page < self.chunk_total_pages)
        self.btn_last_chunk_page.setEnabled(self.chunk_current_page < self.chunk_total_pages)

    def _render_chunks_for_file(self, file_idx: int, page: Optional[int] = None):
        self.table_chunks.setRowCount(0)
        if not (0 <= file_idx < len(self.file_list)):
            self.chunk_current_page = 1
            self.chunk_total_pages = 1
            self._update_chunk_pagination_controls(0)
            return

        cached_chunks = self._get_file_chunks(file_idx, self.file_list[file_idx])
        total_chunks = len(cached_chunks)

        self.chunk_total_pages = max(1, (total_chunks + self.chunk_page_size - 1) // self.chunk_page_size) if total_chunks > 0 else 1
        if page is not None:
            self.chunk_current_page = max(1, min(page, self.chunk_total_pages))
        else:
            self.chunk_current_page = max(1, min(self.chunk_current_page, self.chunk_total_pages))

        self._update_chunk_pagination_controls(total_chunks)

        if total_chunks == 0:
            return

        start_idx = (self.chunk_current_page - 1) * self.chunk_page_size
        end_idx = min(start_idx + self.chunk_page_size, total_chunks)

        for c_idx in range(start_idx, end_idx):
            chunk_info = cached_chunks[c_idx]
            r = self.table_chunks.rowCount()
            self.table_chunks.insertRow(r)

            item_c_stt = QTableWidgetItem(str(c_idx + 1))
            item_c_stt.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table_chunks.setItem(r, 0, item_c_stt)

            self.table_chunks.setItem(r, 1, QTableWidgetItem(chunk_info["text"]))

            item_status = QTableWidgetItem(chunk_info["status"])
            if chunk_info["status"] == "Hoàn thành":
                item_status.setForeground(QColor("#16A34A"))
            elif chunk_info["status"] == "Đang xử lý":
                item_status.setForeground(QColor("#2563EB"))
            elif chunk_info["status"] == "Lỗi":
                item_status.setForeground(QColor("#DC2626"))
            self.table_chunks.setItem(r, 2, item_status)

            self.table_chunks.setItem(r, 3, QTableWidgetItem(chunk_info["note"]))

    def _update_profile_count_display(self):
        """Cập nhật nhãn số lượng profile có sẵn trong profiles_dung."""
        cnt = profile_manager.count_available_profiles()
        self.lbl_profile_count.setText(f"Kho Profile: {cnt}")
        if cnt > 0:
            self.lbl_profile_count.setStyleSheet("background-color: #DCFCE7; color: #166534; font-weight: bold; padding: 4px 8px; border-radius: 4px;")
        else:
            self.lbl_profile_count.setStyleSheet("background-color: #FEF3C7; color: #92400E; font-weight: bold; padding: 4px 8px; border-radius: 4px;")

    def _open_profile_dir(self):
        """Mở thư mục profiles_dung trong Windows Explorer."""
        profile_manager.ensure_dirs()
        os.startfile(str(PROFILES_DUNG_DIR))

    def _on_thread_count_changed(self, val: int):
        """Cập nhật và lưu số luồng cấu hình."""
        self.settings.thread_count = val
        self.settings.save()

    def _start_warming_profile(self, continuous: bool = False):
        """Khởi động luồng nuôi Profile mới."""
        if self.warmer_thread and self.warmer_thread.isRunning():
            QMessageBox.information(self, "Thông báo", "Tiến trình nuôi profile đang chạy rồi!")
            return

        proxy_list = []
        if self.settings.rotating_proxies and self.settings.rotating_proxies.strip():
            proxy_list = [line.strip() for line in self.settings.rotating_proxies.splitlines() if line.strip() and line.strip().lower() != "null"]
        elif self.settings.static_proxies and self.settings.static_proxies.strip():
            proxy_list = [line.strip() for line in self.settings.static_proxies.splitlines() if line.strip() and line.strip().lower() != "null"]

        proxy_raw = proxy_list[0] if proxy_list else None
        show_win = self.chk_show_warm_browser.isChecked()
        thread_cnt = max(1, self.spn_thread_count.value())
        self.settings.thread_count = thread_cnt

        self.btn_warm_profile.setEnabled(False)
        self.btn_start_both.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.lbl_warmer_status.setText(f"Trạng thái nuôi: Đang khởi động {thread_cnt} luồng Chrome song song...")

        self.warmer_thread = ProfileWarmerThread(
            thread_count=thread_cnt,
            proxy_raw=proxy_raw,
            proxy_list=proxy_list,
            show_window=show_win,
            loop_continuous=continuous,
            parent=self
        )
        self.warmer_thread.status_signal.connect(self._on_warmer_status)
        self.warmer_thread.finished_signal.connect(self._on_warmer_finished)
        self.warmer_thread.start()

    def _start_voice_only(self):
        """Chạy riêng tiến trình tạo giọng nói (sử dụng Profile đã nuôi sẵn)."""
        if not self.file_list:
            QMessageBox.warning(self, "Chú ý", "Không có tệp .txt nào trong danh sách!")
            return

        all_completed = True
        for fp in self.file_list:
            out_p = self._get_output_mp3_path(fp)
            if not (out_p.exists() and out_p.stat().st_size > 0):
                all_completed = False
                break

        if all_completed:
            QMessageBox.information(
                self,
                "Đã hoàn thành",
                "Tất cả các tệp trong danh sách đều đã tạo xong file MP3 hoàn chỉnh!\n"
                "Không có đoạn nào cần tạo mới. Tiến trình sẽ không khởi chạy."
            )
            return

        self._save_ui_to_settings()
        self.btn_start_voice.setEnabled(False)
        self.btn_start_both.setEnabled(False)
        self.btn_warm_profile.setEnabled(False)
        self.btn_delete_file.setEnabled(False)
        self.btn_stop.setEnabled(True)

        self.lbl_warmer_status.setText("Trạng thái: Đang tạo voice bằng Profile sẵn có...")

        show_win = self.chk_show_warm_browser.isChecked()
        self.bridge_thread = PipelineBridgeThread(
            self.settings,
            self.file_list,
            parent=self,
            warm_and_voice=False,
            show_browser=show_win
        )
        self.bridge_thread.chunk_status_signal.connect(self._on_chunk_status_update)
        self.bridge_thread.file_progress_signal.connect(self._on_file_progress_update)
        self.bridge_thread.overall_progress_signal.connect(self._on_overall_progress_update)
        self.bridge_thread.finished_signal.connect(self._on_processing_finished)

        self.bridge_thread.start()

    def _start_both(self):
        """Chạy quy trình khép kín: Nuôi Profile trực tiếp trên IP xoay -> Tạo Voice ngay trên chính IP đó."""
        if not self.file_list:
            QMessageBox.warning(self, "Chú ý", "Không có tệp .txt nào trong danh sách để tạo voice!")
            return

        all_completed = True
        for fp in self.file_list:
            out_p = self._get_output_mp3_path(fp)
            if not (out_p.exists() and out_p.stat().st_size > 0):
                all_completed = False
                break

        if all_completed:
            QMessageBox.information(
                self,
                "Đã hoàn thành",
                "Tất cả các tệp trong danh sách đều đã tạo xong file MP3 hoàn chỉnh!\n"
                "Không có đoạn nào cần tạo mới. Tiến trình sẽ không khởi chạy."
            )
            return

        self._save_ui_to_settings()
        self.btn_start_voice.setEnabled(False)
        self.btn_start_both.setEnabled(False)
        self.btn_warm_profile.setEnabled(False)
        self.btn_delete_file.setEnabled(False)
        self.btn_stop.setEnabled(True)

        self.lbl_warmer_status.setText("Trạng thái: Đang chạy quy trình khép kín (Nuôi IP -> Tạo Voice)...")

        show_win = self.chk_show_warm_browser.isChecked()
        self.bridge_thread = PipelineBridgeThread(
            self.settings,
            self.file_list,
            parent=self,
            warm_and_voice=True,
            show_browser=show_win
        )
        self.bridge_thread.chunk_status_signal.connect(self._on_chunk_status_update)
        self.bridge_thread.file_progress_signal.connect(self._on_file_progress_update)
        self.bridge_thread.overall_progress_signal.connect(self._on_overall_progress_update)
        self.bridge_thread.finished_signal.connect(self._on_processing_finished)

        self.bridge_thread.start()

    def _stop_processing(self):
        """Dừng tất cả các tiến trình đang chạy."""
        if self.bridge_thread and self.bridge_thread.isRunning():
            self.bridge_thread.stop()
        if self.warmer_thread and self.warmer_thread.isRunning():
            self.warmer_thread.stop()
        self.lbl_warmer_status.setText("Trạng thái: Đã dừng tiến trình")
        self.btn_delete_file.setEnabled(True)
        self.btn_stop.setEnabled(False)

    @pyqtSlot(str)
    def _on_warmer_status(self, msg: str):
        self.lbl_warmer_status.setText(f"Nuôi Profile: {msg[:45]}...")

    @pyqtSlot(bool, str)
    def _on_warmer_finished(self, success: bool, msg: str):
        self.btn_warm_profile.setEnabled(True)
        if not (self.bridge_thread and self.bridge_thread.isRunning()):
            self.btn_start_both.setEnabled(True)
            self.btn_stop.setEnabled(False)

        self._update_profile_count_display()
        if success:
            self.lbl_warmer_status.setText(f"Trạng thái nuôi: Hoàn tất ({Path(msg).name})")
        else:
            self.lbl_warmer_status.setText("Trạng thái nuôi: Đã dừng hoặc gặp sự cố")

    @pyqtSlot(int, int, str, str)
    def _on_chunk_status_update(self, file_idx: int, chunk_idx: int, status: str, note: str):
        self._update_profile_count_display()
        # Cập nhật cache
        if file_idx in self.file_chunks_cache:
            cache = self.file_chunks_cache[file_idx]
            if 0 <= chunk_idx < len(cache):
                cache[chunk_idx]["status"] = status
                cache[chunk_idx]["note"] = note

        # Nếu file đang được chọn trên màn hình, cập nhật trực tiếp dòng bảng trên trang hiện tại
        if file_idx == self.selected_file_index:
            start_idx = (self.chunk_current_page - 1) * self.chunk_page_size
            end_idx = start_idx + self.chunk_page_size
            if start_idx <= chunk_idx < end_idx:
                table_row = chunk_idx - start_idx
                if table_row < self.table_chunks.rowCount():
                    item_status = QTableWidgetItem(status)
                    if status == "Hoàn thành":
                        item_status.setForeground(QColor("#16A34A"))
                    elif status == "Đang xử lý":
                        item_status.setForeground(QColor("#2563EB"))
                    elif status == "Lỗi":
                        item_status.setForeground(QColor("#DC2626"))
                    self.table_chunks.setItem(table_row, 2, item_status)
                    self.table_chunks.setItem(table_row, 3, QTableWidgetItem(note))

    @pyqtSlot(int, int, int, str)
    def _on_file_progress_update(self, file_idx: int, completed: int, total: int, status_text: str):
        if 0 <= file_idx < self.table_files.rowCount():
            if total <= 0:
                cached = self.file_chunks_cache.get(file_idx)
                if cached:
                    total = len(cached)
                    if "đã có output" in status_text.lower() or "bỏ qua" in status_text.lower() or "xong" in status_text.lower():
                        completed = total

            prog_str = f"{completed}/{total}" if total > 0 else "0/0"

            item = QTableWidgetItem(prog_str)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            font = item.font()
            font.setBold(True)
            item.setFont(font)
            item.setToolTip(f"{status_text} ({completed}/{total})")

            if completed >= total and total > 0:
                item.setForeground(QColor("#16A34A"))
            elif completed > 0:
                item.setForeground(QColor("#2563EB"))
            elif "lỗi" in status_text.lower():
                item.setForeground(QColor("#DC2626"))

            self.table_files.setItem(file_idx, 3, item)

            # Cập nhật cột 4: Tệp đầu ra (Output)
            if 0 <= file_idx < len(self.file_list):
                file_p = self.file_list[file_idx]
                out_mp3 = self._get_output_mp3_path(file_p)
                if out_mp3.exists() and out_mp3.stat().st_size > 0:
                    size_mb = out_mp3.stat().st_size / (1024 * 1024)
                    item_out = QTableWidgetItem(f"🔊 {out_mp3.name} ({size_mb:.1f} MB)")
                    item_out.setForeground(QColor("#16A34A"))
                    item_out.setToolTip(f"Đã có file MP3 đầu ra hoàn chỉnh:\n{out_mp3}\nNhấp đúp chuột để nghe/mở file.")
                    self.table_files.setItem(file_idx, 4, item_out)

    @pyqtSlot(int, int)
    def _on_overall_progress_update(self, completed: int, total: int):
        self.progress_bar.setMaximum(max(1, total))
        self.progress_bar.setValue(completed)
        self.lbl_stats.setText(f"Tổng: {total} đoạn | Hoàn thành: {completed}")

    @pyqtSlot(bool)
    def _on_processing_finished(self, success: bool):
        self.btn_start_voice.setEnabled(True)
        self.btn_warm_profile.setEnabled(True)
        self.btn_delete_file.setEnabled(True)
        if not (self.warmer_thread and self.warmer_thread.isRunning()):
            self.btn_start_both.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self._update_profile_count_display()
        self.lbl_warmer_status.setText("Trạng thái: Sẵn sàng")
        self._update_files_table()

        if success:
            QMessageBox.information(self, "Thành công", "Đã hoàn thành toàn bộ danh sách tệp!")
        else:
            QMessageBox.warning(self, "Thông báo", "Tiến trình đã dừng (hoặc còn một số đoạn chưa hoàn tất).")

    def closeEvent(self, event):
        self._save_ui_to_settings()
        if hasattr(self, 'log_window') and self.log_window:
            self.log_window._force_close = True
            self.log_window.close()
        if self.bridge_thread and self.bridge_thread.isRunning():
            self.bridge_thread.stop()
            self.bridge_thread.wait(2000)
        if self.warmer_thread and self.warmer_thread.isRunning():
            self.warmer_thread.stop()
            self.warmer_thread.wait(2000)
        event.accept()
