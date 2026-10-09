"""Kiểm thử đơn vị cho tính năng xóa row file txt trong MainWindow."""

import sys
import tempfile
from pathlib import Path
from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtCore import Qt, QEvent
from PyQt6.QtGui import QKeyEvent

from ui.main_window import MainWindow
from config.settings import AppSettings, FileVoiceProfile, VoiceTemplate

# Khởi tạo QApplication cho môi trường test nếu chưa có
app = QApplication.instance()
if app is None:
    app = QApplication(sys.argv)

def test_delete_single_file_from_table():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        f1 = tmp_path / "file1.txt"
        f2 = tmp_path / "file2.txt"
        f3 = tmp_path / "file3.txt"
        f1.write_text("Nội dung 1", encoding="utf-8")
        f2.write_text("Nội dung 2", encoding="utf-8")
        f3.write_text("Nội dung 3", encoding="utf-8")

        win = MainWindow()
        win.file_list = [f1, f2, f3]
        win._update_files_table()

        assert win.table_files.rowCount() == 3

        # Chọn hàng thứ 1 (f2)
        win.table_files.setCurrentCell(1, 0)
        win.table_files.selectRow(1)

        # Thực hiện xóa row đã chọn
        win._delete_selected_files()

        # Kiểm tra f2 đã bị xóa khỏi file_list và bảng
        assert len(win.file_list) == 2
        assert f1 in win.file_list
        assert f3 in win.file_list
        assert f2 not in win.file_list
        assert win.table_files.rowCount() == 2

        # Con trỏ tự động chuyển sang tệp kế tiếp (f3 tại index 1)
        assert win.selected_file_index == 1
        assert "file3.txt" in win.lbl_selected_file.text()

def test_delete_multiple_files_from_table():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        f1 = tmp_path / "file1.txt"
        f2 = tmp_path / "file2.txt"
        f3 = tmp_path / "file3.txt"
        f4 = tmp_path / "file4.txt"
        for f in (f1, f2, f3, f4):
            f.write_text("Nội dung mẫu", encoding="utf-8")

        win = MainWindow()
        win.file_list = [f1, f2, f3, f4]
        win._update_files_table()

        # Chọn hàng 0 và hàng 2 (f1 và f3)
        win.table_files.selectRow(0)
        win.table_files.selectRow(2)

        # Gọi xóa nhiều file
        win._remove_multiple_files_from_list([f1, f3])

        assert len(win.file_list) == 2
        assert win.file_list == [f2, f4]
        assert win.table_files.rowCount() == 2

def test_delete_key_shortcut(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        f1 = tmp_path / "file1.txt"
        f2 = tmp_path / "file2.txt"
        f1.write_text("A", encoding="utf-8")
        f2.write_text("B", encoding="utf-8")

        win = MainWindow()
        win.file_list = [f1, f2]
        win._update_files_table()

        win.table_files.selectRow(0)

        # Giả lập bấm phím Delete trên bàn phím
        del_event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Delete, Qt.KeyboardModifier.NoModifier)
        win.table_files.keyPressEvent(del_event)

        assert len(win.file_list) == 1
        assert win.file_list[0] == f2
        assert win.table_files.rowCount() == 1

def test_backspace_key_shortcut():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        f1 = tmp_path / "file1.txt"
        f2 = tmp_path / "file2.txt"
        f1.write_text("A", encoding="utf-8")
        f2.write_text("B", encoding="utf-8")

        win = MainWindow()
        win.file_list = [f1, f2]
        win._update_files_table()

        win.table_files.selectRow(1)

        # Giả lập bấm phím Backspace trên bàn phím
        bksp_event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Backspace, Qt.KeyboardModifier.NoModifier)
        win.table_files.keyPressEvent(bksp_event)

        assert len(win.file_list) == 1
        assert win.file_list[0] == f1
        assert win.table_files.rowCount() == 1

def test_clear_all_files(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        f1 = tmp_path / "file1.txt"
        f2 = tmp_path / "file2.txt"
        f1.write_text("A", encoding="utf-8")
        f2.write_text("B", encoding="utf-8")

        win = MainWindow()
        win.file_list = [f1, f2]
        win._update_files_table()

        assert win.table_files.rowCount() == 2

        # Mock hộp thoại xác nhận Yes
        monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)

        win._clear_all_files()

        assert len(win.file_list) == 0
        assert win.table_files.rowCount() == 0
        assert win.table_chunks.rowCount() == 0
        assert win.selected_file_index == -1
        assert "trống" in win.lbl_selected_file.text().lower()

def test_delete_file_from_disk(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        f1 = tmp_path / "delete_me.txt"
        f1.write_text("Xóa tôi đi", encoding="utf-8")
        assert f1.exists()

        win = MainWindow()
        win.file_list = [f1]
        win._update_files_table()

        # Mock cảnh báo xác nhận Yes
        monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
        monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: None)

        win._delete_files_from_disk([f1])

        # Tệp trên đĩa phải bị xóa
        assert not f1.exists()
        # Tệp trong danh sách cũng phải bị loại bỏ
        assert len(win.file_list) == 0
        assert win.table_files.rowCount() == 0

def test_cannot_delete_while_processing(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        f1 = tmp_path / "file1.txt"
        f1.write_text("Text", encoding="utf-8")

        win = MainWindow()
        win.file_list = [f1]
        win._update_files_table()

        class DummyBridge:
            def isRunning(self):
                return True

        win.bridge_thread = DummyBridge()

        warn_called = False
        def mock_warning(*args, **kwargs):
            nonlocal warn_called
            warn_called = True
            return QMessageBox.StandardButton.Ok

        monkeypatch.setattr(QMessageBox, "warning", mock_warning)

        win.table_files.selectRow(0)
        win._delete_selected_files()

        assert warn_called is True
        assert len(win.file_list) == 1
