"""Kiểm thử tự động cho module Pipeline (Worker & Orchestrator)."""

import pytest
import tempfile
import asyncio
from pathlib import Path

from config.settings import AppSettings
from core.models import ChunkTask, FileProgress
from core.audio_merger import run_ffmpeg
from pipeline.orchestrator import Orchestrator

def create_sample_mp3(file_path: Path, duration: float = 0.4):
    """Tạo file MP3 giả lập hợp lệ bằng ffmpeg để test logic ghép nối."""
    run_ffmpeg(
        "-f", "lavfi",
        "-i", f"sine=frequency=440:duration={duration}",
        "-c:a", "libmp3lame",
        "-q:a", "2",
        str(file_path)
    )

@pytest.mark.asyncio
async def test_orchestrator_resume_and_merge():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        text_file = tmp_path / "truyen_ngan.txt"
        text_content = (
            "Đoạn văn thứ nhất để kiểm tra chức năng resume. "
            "\n"
            "Đoạn văn thứ hai để kiểm tra chức năng tự động ghép nối sau khi hoàn tất."
        )
        text_file.write_text(text_content, encoding="utf-8")

        settings = AppSettings(
            chunk_size=100,
            silence_enabled=True,
            silence_value=0.1
        )

        orchestrator = Orchestrator(settings=settings)
        out_mp3 = orchestrator.get_output_path(text_file)
        assert out_mp3.name == "truyen_ngan.mp3"

        chunk_dir = text_file.parent / text_file.stem
        chunk_dir.mkdir(parents=True, exist_ok=True)
        part0 = chunk_dir / "part_0.mp3"
        part1 = chunk_dir / "part_1.mp3"

        # Tạo trước 2 part mẫu để mô phỏng trường hợp tất cả chunk đã tạo xong
        create_sample_mp3(part0, duration=0.3)
        create_sample_mp3(part1, duration=0.3)

        # Chạy orchestrator với file này
        success = await orchestrator.run([text_file])

        assert success is True
        # Đảm bảo file MP3 cuối cùng đã được ghép
        assert out_mp3.exists()
        assert out_mp3.stat().st_size > 0
        # Đảm bảo các part tạm đã được dọn dẹp sạch sẽ
        assert not part0.exists()
        assert not part1.exists()

@pytest.mark.asyncio
async def test_orchestrator_skip_existing_output():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        text_file = tmp_path / "test_done.txt"
        text_file.write_text("Nội dung đã được tạo từ trước.", encoding="utf-8")

        # Tạo sẵn file output
        out_mp3 = tmp_path / "test_done.mp3"
        create_sample_mp3(out_mp3, duration=0.5)

        settings = AppSettings()
        orchestrator = Orchestrator(settings=settings)

        # File đã có output thì orchestrator phải bỏ qua không cần tạo lại
        success = await orchestrator.run([text_file])
        assert success is True
        assert orchestrator.total_chunks_all == 0

@pytest.mark.asyncio
async def test_orchestrator_warm_and_voice_flags():
    settings = AppSettings()
    orchestrator = Orchestrator(settings=settings, warm_and_voice=True, show_browser=True)
    assert orchestrator.warm_and_voice is True
    assert orchestrator.show_browser is True

def test_token_farmer_is_new_nuoi_init():
    from captcha.token_farmer import TokenFarmer
    from captcha.profile_manager import profile_manager
    farmer = TokenFarmer(is_new_nuoi=True)
    assert farmer.is_new_nuoi is True
    assert farmer.profile_path is not None
    assert "profiles_nuoi" in str(farmer.profile_path)
    profile_manager.delete_profile(farmer.profile_path)

def test_on_chunk_completed_realtime_progress():
    overall_calls = []
    file_calls = []
    settings = AppSettings()
    orchestrator = Orchestrator(
        settings=settings,
        on_overall_progress=lambda comp, tot: overall_calls.append((comp, tot)),
        on_file_progress=lambda f_idx, comp, tot, txt: file_calls.append((f_idx, comp, tot, txt)),
    )
    orchestrator.total_chunks_all = 10
    orchestrator.total_completed_chunks = 2
    orchestrator.file_progresses[0] = FileProgress(
        file_index=0,
        total_chunks=5,
        completed_chunks=1,
        chunk_paths=[],
        output_path="test.mp3"
    )

    from core.models import ChunkTask, VoiceTemplate
    task = ChunkTask(
        file_index=0,
        file_path="test.txt",
        chunk_index=1,
        text="Sample",
        chunk_mp3_path="part_1.mp3",
        voice_profile=VoiceTemplate(voice_id="xyz")
    )
    orchestrator._on_chunk_completed(task)

    assert orchestrator.total_completed_chunks == 3
    assert len(overall_calls) == 1
    assert overall_calls[-1] == (3, 10)

    assert orchestrator.file_progresses[0].completed_chunks == 2
    assert len(file_calls) == 1
    assert file_calls[-1] == (0, 2, 5, "Đang chạy: 2/5")

def test_orchestrator_output_file_suffix():
    settings = AppSettings(output_file_suffix="_voice")
    orchestrator = Orchestrator(settings=settings)
    out_path = orchestrator.get_output_path(Path("sample/test.txt"))
    assert out_path.name == "test_voice.mp3"

    settings2 = AppSettings(output_file_suffix="_voice.mp3")
    orchestrator2 = Orchestrator(settings=settings2)
    out_path2 = orchestrator2.get_output_path(Path("sample/test.txt"))
    assert out_path2.name == "test_voice.mp3"

    settings_default = AppSettings()
    orchestrator_default = Orchestrator(settings=settings_default)
    out_path3 = orchestrator_default.get_output_path(Path("sample/test.txt"))
    assert out_path3.name == "test.mp3"

