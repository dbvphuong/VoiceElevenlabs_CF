"""Kiểm thử đơn vị cho tính năng phân trang bảng Chunks (tối đa 50 dòng/trang)."""

import sys
import tempfile
from pathlib import Path
import pytest
from PyQt6.QtWidgets import QApplication

from ui.main_window import MainWindow

app = QApplication.instance()
if app is None:
    app = QApplication(sys.argv)

@pytest.fixture(autouse=True)
def isolate_settings(tmp_path, monkeypatch):
    test_settings_file = tmp_path / "isolated_settings.json"
    orig_init = MainWindow.__init__
    def patched_init(self, settings_path=None, *args, **kwargs):
        if settings_path is None:
            settings_path = test_settings_file
        orig_init(self, settings_path=settings_path, *args, **kwargs)
    monkeypatch.setattr(MainWindow, "__init__", patched_init)


def test_chunk_pagination_flow():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        test_file = tmp_path / "sample.txt"
        test_file.write_text("Dữ liệu mẫu", encoding="utf-8")

        win = MainWindow()
        win.file_list = [test_file]

        # Giả lập 125 chunks trong cache
        chunks = [
            {"text": f"Nội dung đoạn số {i}", "status": "Đang chờ", "note": ""}
            for i in range(125)
        ]
        win.file_chunks_cache[0] = chunks

        # Render file 0
        win.selected_file_index = 0
        win._render_chunks_for_file(0)

        # 1. Trang 1: Phải có đúng 50 dòng
        assert win.chunk_total_pages == 3
        assert win.chunk_current_page == 1
        assert win.table_chunks.rowCount() == 50
        assert win.table_chunks.item(0, 0).text() == "1"
        assert win.table_chunks.item(49, 0).text() == "50"
        assert "1/3" in win.lbl_chunk_page_info.text()
        assert win.btn_prev_chunk_page.isEnabled() is False
        assert win.btn_first_chunk_page.isEnabled() is False
        assert win.btn_next_chunk_page.isEnabled() is True
        assert win.btn_last_chunk_page.isEnabled() is True

        # 2. Chuyển sang Trang 2
        win._next_chunk_page()
        assert win.chunk_current_page == 2
        assert win.table_chunks.rowCount() == 50
        assert win.table_chunks.item(0, 0).text() == "51"
        assert win.table_chunks.item(49, 0).text() == "100"
        assert "2/3" in win.lbl_chunk_page_info.text()
        assert win.btn_prev_chunk_page.isEnabled() is True
        assert win.btn_first_chunk_page.isEnabled() is True
        assert win.btn_next_chunk_page.isEnabled() is True
        assert win.btn_last_chunk_page.isEnabled() is True

        # 3. Chuyển sang Trang cuối (Trang 3)
        win._last_chunk_page()
        assert win.chunk_current_page == 3
        # 125 - 100 = 25 dòng
        assert win.table_chunks.rowCount() == 25
        assert win.table_chunks.item(0, 0).text() == "101"
        assert win.table_chunks.item(24, 0).text() == "125"
        assert "3/3" in win.lbl_chunk_page_info.text()
        assert win.btn_next_chunk_page.isEnabled() is False
        assert win.btn_last_chunk_page.isEnabled() is False
        assert win.btn_prev_chunk_page.isEnabled() is True
        assert win.btn_first_chunk_page.isEnabled() is True

        # 4. Quay lại trang đầu
        win._first_chunk_page()
        assert win.chunk_current_page == 1
        assert win.table_chunks.rowCount() == 50
        assert win.table_chunks.item(0, 0).text() == "1"


def test_chunk_status_update_with_pagination():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        test_file = tmp_path / "sample.txt"
        test_file.write_text("Dữ liệu mẫu", encoding="utf-8")

        win = MainWindow()
        win.file_list = [test_file]

        chunks = [
            {"text": f"Đoạn {i}", "status": "Đang chờ", "note": ""}
            for i in range(80)
        ]
        win.file_chunks_cache[0] = chunks

        win.selected_file_index = 0
        win._render_chunks_for_file(0)

        # Cập nhật chunk 5 (nằm trên trang 1, table_row = 5)
        win._on_chunk_status_update(0, 5, "Hoàn thành", "Tải xong 45KB")
        assert win.table_chunks.item(5, 2).text() == "Hoàn thành"
        assert win.table_chunks.item(5, 3).text() == "Tải xong 45KB"
        assert win.file_chunks_cache[0][5]["status"] == "Hoàn thành"

        # Cập nhật chunk 60 (nằm trên trang 2) trong khi đang ở trang 1
        win._on_chunk_status_update(0, 60, "Hoàn thành", "Tải xong 38KB")
        # Cache được cập nhật
        assert win.file_chunks_cache[0][60]["status"] == "Hoàn thành"

        # Khi chuyển sang trang 2, chunk 60 (table_row = 10) phải hiển thị đúng
        win._next_chunk_page()
        assert win.chunk_current_page == 2
        assert win.table_chunks.item(10, 0).text() == "61"
        assert win.table_chunks.item(10, 2).text() == "Hoàn thành"
        assert win.table_chunks.item(10, 3).text() == "Tải xong 38KB"


def test_empty_chunks_pagination():
    win = MainWindow()
    win.file_list = []
    win._update_files_table()

    assert win.table_chunks.rowCount() == 0
    assert win.chunk_current_page == 1
    assert win.chunk_total_pages == 1
    assert win.btn_prev_chunk_page.isEnabled() is False
    assert win.btn_next_chunk_page.isEnabled() is False
