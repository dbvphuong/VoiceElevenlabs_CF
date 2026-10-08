"""Kiểm thử đơn vị cho VoiceService và Quản lý Voice Template / Folder Profiles."""

import pytest
import tempfile
from pathlib import Path

from config.settings import AppSettings, VoiceTemplate, FolderVoiceProfile, FileVoiceProfile
from network.voice_service import VoiceService, DEFAULT_PREMADE_VOICES
from pipeline.orchestrator import Orchestrator

def test_voice_service_cache_and_premade():
    with tempfile.TemporaryDirectory() as tmp_dir:
        cache_file = Path(tmp_dir) / "test_voices_cache.json"
        svc = VoiceService(cache_path=cache_file)

        # 1. Kiểm tra các giọng premade có sẵn
        rachel = svc.get_cached_voice("21m00Tcm4TlvDq8ikWAM")
        assert rachel is not None
        assert "Rachel" in rachel["name"]
        assert rachel["category"] == "premade"

        frederick = svc.get_cached_voice("j9jfwdrw7BRfcR43Qohk")
        assert frederick is not None
        assert "Frederick" in frederick["name"]

        # 2. Kiểm tra giọng không tồn tại
        unknown = svc.get_cached_voice("invalid_voice_id_xyz")
        assert unknown is None

def test_voice_template_persistence():
    with tempfile.TemporaryDirectory() as tmp_dir:
        settings_file = Path(tmp_dir) / "settings_tmpl.json"

        settings = AppSettings()
        settings.voice_templates.append(
            VoiceTemplate(
                name="Mẫu Kể Chuyện",
                voice_id="j9jfwdrw7BRfcR43Qohk",
                speed=0.95,
                style=35,
                stability=50,
                similarity=40
            )
        )
        settings.selected_voice_template_name = "Mẫu Kể Chuyện"
        settings.save(settings_file)

        # Tải lại
        loaded = AppSettings.load(settings_file)
        assert len(loaded.voice_templates) == 1
        assert loaded.voice_templates[0].name == "Mẫu Kể Chuyện"
        assert loaded.voice_templates[0].voice_id == "j9jfwdrw7BRfcR43Qohk"
        assert loaded.voice_templates[0].speed == 0.95
        assert loaded.selected_voice_template_name == "Mẫu Kể Chuyện"

def test_orchestrator_voice_profile_resolution():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        folder_a = tmp_path / "folder_a"
        folder_b = tmp_path / "folder_b"
        folder_a.mkdir()
        folder_b.mkdir()

        file_a = folder_a / "chap1.txt"
        file_b = folder_b / "chap2.txt"
        file_root = tmp_path / "root.txt"
        file_a.write_text("Hello A", encoding="utf-8")
        file_b.write_text("Hello B", encoding="utf-8")
        file_root.write_text("Hello Root", encoding="utf-8")

        # Cấu hình:
        # - Folder A có profile riêng (Adam)
        # - Template chung được chọn là (Rachel)
        # - Global settings là (Default / Voice X)
        settings = AppSettings(
            voice_id="global_voice_id",
            speed=1.0,
            voice_templates=[
                VoiceTemplate(name="Rachel Template", voice_id="rachel_id", speed=0.85),
                VoiceTemplate(name="Adam Template", voice_id="adam_id", speed=0.95),
            ],
            selected_voice_template_name="Rachel Template",
            folder_voice_profiles=[
                FolderVoiceProfile(
                    folder_path=str(folder_a),
                    voice=VoiceTemplate(name="Adam Template", voice_id="adam_id", speed=0.95)
                )
            ]
        )

        orchestrator = Orchestrator(settings=settings)

        # 1. file_a nằm trong folder_a -> phải nhận Adam (ưu tiên 1: Folder profile)
        prof_a = orchestrator.get_voice_profile_for_file(file_a)
        assert prof_a.voice_id == "adam_id"
        assert prof_a.speed == 0.95

        # 2. file_b không có folder profile -> nhận Rachel Template (ưu tiên 2: Selected template)
        prof_b = orchestrator.get_voice_profile_for_file(file_b)
        assert prof_b.voice_id == "rachel_id"
        assert prof_b.speed == 0.85

        # 3. Khi bỏ selected_voice_template_name -> nhận global settings (ưu tiên 3)
        settings.selected_voice_template_name = ""
        prof_root = orchestrator.get_voice_profile_for_file(file_root)
        assert prof_root.voice_id == "global_voice_id"
        assert prof_root.speed == 1.0

def test_orchestrator_file_voice_profile_priority():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        file1 = tmp_path / "1.Ba Lan.txt"
        file2 = tmp_path / "27.Anh.txt"
        file1.write_text("Text 1", encoding="utf-8")
        file2.write_text("Text 2", encoding="utf-8")

        # Cấu hình:
        # file1 gán giọng Rachel (lúc thêm file 1)
        # file2 gán giọng Vũ Trụ (lúc thêm file 2)
        settings = AppSettings(
            selected_voice_template_name="Default Template",
            file_voice_profiles=[
                FileVoiceProfile(
                    file_path=str(file1),
                    voice=VoiceTemplate(name="Rachel (Nữ)", voice_id="rachel_id", speed=0.9)
                ),
                FileVoiceProfile(
                    file_path=str(file2),
                    voice=VoiceTemplate(name="Vũ trụ lượng tử", voice_id="vu_tru_id", speed=0.95)
                ),
            ]
        )

        orchestrator = Orchestrator(settings=settings)

        prof1 = orchestrator.get_voice_profile_for_file(file1)
        assert prof1.name == "Rachel (Nữ)"
        assert prof1.voice_id == "rachel_id"
        assert prof1.speed == 0.9

        prof2 = orchestrator.get_voice_profile_for_file(file2)
        assert prof2.name == "Vũ trụ lượng tử"
        assert prof2.voice_id == "vu_tru_id"
        assert prof2.speed == 0.95

