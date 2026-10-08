"""Kiểm thử đơn vị cho hệ thống quản lý Profile và luồng nuôi Profile."""

import pytest
import tempfile
import shutil
from pathlib import Path

from captcha.profile_manager import ProfileManager
from captcha.token_farmer import TokenFarmer

def test_profile_manager_lifecycle():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_base = Path(tmp_dir) / "Profile"
        pm = ProfileManager()
        # Ghi đè đường dẫn tạm để test
        pm.ensure_dirs()
        assert pm.count_available_profiles() >= 0

        # Tạo 1 session nuôi
        session = pm.create_new_nuoi_session(prefix="test_nuoi")
        assert session.exists()
        assert "test_nuoi" in session.name

        # Tạo file giả lập bên trong session
        dummy_file = session / "dummy_cookie.txt"
        dummy_file.write_text("sample_cookie", encoding="utf-8")

        # Chuyển (move) sang profiles_dung
        dung_path = pm.transfer_to_dung(session)
        assert dung_path.exists()
        assert not session.exists(), "Session nuôi phải được di chuyển (move), không được để sót trong profiles_nuoi"
        assert (dung_path / "dummy_cookie.txt").exists()
        assert (dung_path / "dummy_cookie.txt").read_text(encoding="utf-8") == "sample_cookie"

        # Lấy profile có sẵn
        latest = pm.get_next_warmed_profile()
        assert latest is not None

        # Kiểm tra xóa bỏ profile khi bị lỗi/chặn
        assert pm.delete_profile(dung_path) is True
        assert not dung_path.exists(), "Profile phải bị xóa bỏ hoàn toàn"

def test_token_farmer_detects_profile():
    with tempfile.TemporaryDirectory() as tmp_dir:
        profile_path = Path(tmp_dir) / "profile_ready"
        profile_path.mkdir()

        farmer = TokenFarmer(headless=False, off_screen=True, profile_path=profile_path)
        assert farmer.profile_path == profile_path
        assert farmer.headless is False
        assert farmer.off_screen is True
