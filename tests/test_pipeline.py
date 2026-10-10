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


@pytest.mark.asyncio
async def test_orchestrator_retry_round_preserves_all_uncompleted_chunks(monkeypatch):
    """Đảm bảo Orchestrator ở các vòng retry không bao giờ bị mất task khi có chunk lỗi."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        text_file = tmp_path / "long_text.txt"
        text_file.write_text("Đoạn một. Đoạn hai. Đoạn ba. Đoạn bốn.", encoding="utf-8")

        settings = AppSettings(chunk_size=10, thread_count=1)
        orchestrator = Orchestrator(settings=settings)

        call_count = {}
        from pipeline.worker import PipelineWorker

        async def mock_process_chunk(self, task, max_attempts=1, retry_round=0, cancel_event=None):
            idx = task.chunk_index
            call_count[idx] = call_count.get(idx, 0) + 1
            if retry_round == 0:
                if idx in (0, 2):
                    # Giả lập thất bại: không tạo mp3
                    return True
                else:
                    create_sample_mp3(Path(task.chunk_mp3_path), duration=0.2)
                    if self.on_chunk_completed:
                        res = self.on_chunk_completed(task)
                        if asyncio.iscoroutine(res):
                            await res
                    return True
            else:
                # Ở retry round: tạo thành công
                create_sample_mp3(Path(task.chunk_mp3_path), duration=0.2)
                if self.on_chunk_completed:
                    res = self.on_chunk_completed(task)
                    if asyncio.iscoroutine(res):
                        await res
                return True

        monkeypatch.setattr(PipelineWorker, "process_chunk", mock_process_chunk)

        success = await orchestrator.run([text_file])
        assert success is True
        # Cả 4 chunk đều phải hoàn thành và các chunk lỗi được retry đầy đủ
        assert call_count[0] >= 2
        assert call_count[2] >= 2
        assert call_count[1] >= 1
        assert call_count[3] >= 1
        out_mp3 = orchestrator.get_output_path(text_file)
        assert out_mp3.exists()
        assert out_mp3.stat().st_size > 0


def test_orchestrator_sets_cancel_event_when_all_chunks_completed():
    """Kiểm tra orchestrator tự động kích hoạt cancel_event ngay khi toàn bộ chunk hoàn tất."""
    orchestrator = Orchestrator(settings=AppSettings())
    orchestrator.total_chunks_all = 3
    orchestrator.total_completed_chunks = 2
    orchestrator.file_progresses[0] = FileProgress(
        file_index=0,
        total_chunks=3,
        completed_chunks=2,
        chunk_paths=[],
        output_path="test.mp3"
    )
    from core.models import ChunkTask, VoiceTemplate
    task = ChunkTask(
        file_index=0,
        file_path="test.txt",
        chunk_index=2,
        text="Last chunk",
        chunk_mp3_path="part_2.mp3",
        voice_profile=VoiceTemplate(voice_id="xyz")
    )
    assert not orchestrator.cancel_event.is_set()
    orchestrator._on_chunk_completed(task)
    assert orchestrator.total_completed_chunks == 3
    assert orchestrator.cancel_event.is_set()


@pytest.mark.asyncio
async def test_worker_skips_when_chunk_exists_or_cancelled(tmp_path):
    """Kiểm tra PipelineWorker bỏ qua ngay nếu file chunk đã có sẵn hoặc cancel_event đã bật."""
    import threading
    from pipeline.worker import PipelineWorker
    from core.models import ChunkTask, VoiceTemplate

    chunk_file = tmp_path / "done_chunk.mp3"
    create_sample_mp3(chunk_file, duration=0.2)

    task = ChunkTask(
        file_index=0,
        file_path="sample.txt",
        chunk_index=0,
        text="Already done",
        chunk_mp3_path=str(chunk_file),
        voice_profile=VoiceTemplate(voice_id="xyz")
    )

    worker = PipelineWorker(worker_id=1, settings=AppSettings(), warm_and_voice=True)
    cancel_event = threading.Event()

    # Case 1: File chunk đã tồn tại trên đĩa -> trả về True ngay lập tức không khởi chạy nuôi/tạo
    result = await worker.process_chunk(task, cancel_event=cancel_event)
    assert result is True

    # Case 2: cancel_event đã set -> trả về False ngay lập tức
    not_done_file = tmp_path / "not_done.mp3"
    task2 = ChunkTask(
        file_index=0,
        file_path="sample.txt",
        chunk_index=1,
        text="Not done",
        chunk_mp3_path=str(not_done_file),
        voice_profile=VoiceTemplate(voice_id="xyz")
    )
    cancel_event.set()
    result2 = await worker.process_chunk(task2, cancel_event=cancel_event)
    assert result2 is False


@pytest.mark.asyncio
async def test_orchestrator_chunk_naming_stt_mp3(tmp_path, monkeypatch):
    """Kiểm tra tên file chunk được tạo dưới dạng STT.mp3 bắt đầu từ 1.mp3 (1.mp3, 2.mp3, ...)."""
    text_file = tmp_path / "sample_story.txt"
    text_file.write_text("Câu một dài thật là dài. Câu hai cũng dài không kém. Câu ba kết thúc ở đây.", encoding="utf-8")

    settings = AppSettings(chunk_size=30)
    orchestrator = Orchestrator(settings=settings)

    from pipeline.worker import PipelineWorker

    async def mock_process(self, task, max_attempts=1, retry_round=0, cancel_event=None):
        create_sample_mp3(Path(task.chunk_mp3_path), duration=0.1)
        if self.on_chunk_completed:
            res = self.on_chunk_completed(task)
            if asyncio.iscoroutine(res):
                await res
        return True

    monkeypatch.setattr(PipelineWorker, "process_chunk", mock_process)

    success = await orchestrator.run([text_file])
    assert success is True

    fp = orchestrator.file_progresses[0]
    assert len(fp.chunk_paths) >= 2
    for idx, cp in enumerate(fp.chunk_paths):
        expected_name = f"{idx + 1}.mp3"
        assert Path(cp).name == expected_name



