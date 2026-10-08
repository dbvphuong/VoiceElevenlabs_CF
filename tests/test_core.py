"""Kiểm thử đơn vị cho toàn bộ các module Core & Network xây dựng trong Giai đoạn 2."""

import pytest
import tempfile
from pathlib import Path
import json

from config.settings import AppSettings, VoiceTemplate
from core.models import ChunkTask, FileProgress, TtsResult
from core.text_splitter import split_text_by_sentences
from core.file_scanner import collect_txt_files
from core.audio_merger import merge_mp3_files, run_ffmpeg
from network.proxy_pool import parse_proxy_string, ProxyPool, RotatingProxyKey

def test_settings_load_and_save():
    with tempfile.TemporaryDirectory() as tmp_dir:
        settings_file = Path(tmp_dir) / "test_settings.json"
        
        # 1. Tạo và lưu settings
        settings = AppSettings(
            voice_id="test_voice_123",
            speed=1.1,
            thread_count=3,
            chunk_size=400,
            static_proxies="1.2.3.4:8080:user:pass"
        )
        settings.save(settings_file)
        assert settings_file.exists()

        # 2. Tải lại và kiểm tra
        loaded = AppSettings.load(settings_file)
        assert loaded.voice_id == "test_voice_123"
        assert loaded.speed == 1.1
        assert loaded.thread_count == 3
        assert loaded.chunk_size == 400
        assert loaded.static_proxies == "1.2.3.4:8080:user:pass"

def test_text_splitter():
    text = (
        "Đây là câu thứ nhất. Đây là câu thứ hai rất dài và có nhiều thông tin chi tiết cần phải cắt nhỏ ra "
        "để không vượt quá giới hạn ký tự tối đa của một đoạn âm thanh ElevenLabs! "
        "Câu thứ ba có dấu chấm hỏi? Và một câu ngắn nữa."
    )
    chunks = split_text_by_sentences(text, max_length=60)
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk) <= 60
        assert len(chunk.strip()) > 0
    # Đảm bảo toàn bộ nội dung được giữ lại
    reconstructed = " ".join(chunks)
    assert "Đây là câu thứ nhất" in reconstructed
    assert "câu ngắn nữa" in reconstructed

def test_tts_result_from_error():
    # 1. sign_in_required
    res1 = TtsResult.from_error(401, json.dumps({
        "detail": {"code": "sign_in_required", "status": "quota_exceeded"}
    }))
    assert res1.retryable is True
    assert res1.rotate_proxy is True

    # 2. detected_unusual_activity
    res2 = TtsResult.from_error(401, json.dumps({
        "detail": {"status": "detected_unusual_activity"}
    }))
    assert res2.is_worker_stopping_error is True
    assert res2.rotate_proxy is True

    # 3. Server 500
    res3 = TtsResult.from_error(500, "Internal Server Error")
    assert res3.retryable is True

    # 4. paid_plan_required (Model v4 or paid plan required)
    res4 = TtsResult.from_error(402, json.dumps({
        "detail": {"code": "paid_plan_required", "status": "payment_required"}
    }))
    assert res4.is_worker_stopping_error is True
    assert "Paid Plan Required" in res4.message


def test_file_scanner():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        sub_dir = tmp_path / "sub"
        sub_dir.mkdir()

        (tmp_path / "file1.txt").write_text("Hello 1", encoding="utf-8")
        (tmp_path / "file2.txt").write_text("Hello 2", encoding="utf-8")
        (tmp_path / "ignore.pdf").write_text("Ignored", encoding="utf-8")
        (sub_dir / "file3.txt").write_text("Hello 3", encoding="utf-8")

        # Quét không đệ quy
        flat_results = collect_txt_files(folders=[tmp_path], include_subfolders=False)
        assert len(flat_results) == 2

        # Quét có đệ quy
        recur_results = collect_txt_files(folders=[tmp_path], include_subfolders=True)
        assert len(recur_results) == 3

def test_proxy_parser():
    p1 = parse_proxy_string("127.0.0.1:8080:myuser:mypass")
    assert p1 is not None
    assert p1["host"] == "127.0.0.1"
    assert p1["port"] == 8080
    assert p1["user"] == "myuser"
    assert p1["password"] == "mypass"
    assert p1["curl_url"] == "http://myuser:mypass@127.0.0.1:8080"
    assert p1["playwright"]["server"] == "http://127.0.0.1:8080"
    assert p1["playwright"]["username"] == "myuser"

    p2 = parse_proxy_string("null")
    assert p2 is None

@pytest.mark.asyncio
async def test_proxy_pool_round_robin():
    pool = ProxyPool([
        "1.1.1.1:80:u1:p1",
        "2.2.2.2:80:u2:p2",
        "3.3.3.3:80:u3:p3"
    ])
    assert pool.count == 3

    k1 = await pool.get_available_key()
    assert k1 is not None and "1.1.1.1" in k1.key

    k2 = await pool.get_available_key()
    assert k2 is not None and "2.2.2.2" in k2.key

    # Release k1 với cooldown
    await pool.release_key(k1, cooldown_seconds=60)
    assert k1.is_being_used is False

def test_audio_merger_with_ffmpeg():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        part1 = tmp_path / "part_1.mp3"
        part2 = tmp_path / "part_2.mp3"
        out_mp3 = tmp_path / "merged_final.mp3"

        # Dùng ffmpeg tạo 2 đoạn audio mẫu chuẩn MP3 (0.5s mỗi đoạn)
        run_ffmpeg(
            "-f", "lavfi", "-i", "sine=frequency=440:duration=0.5",
            "-c:a", "libmp3lame", "-q:a", "2", str(part1)
        )
        run_ffmpeg(
            "-f", "lavfi", "-i", "sine=frequency=880:duration=0.5",
            "-c:a", "libmp3lame", "-q:a", "2", str(part2)
        )

        assert part1.exists() and part1.stat().st_size > 0
        assert part2.exists() and part2.stat().st_size > 0

        # Thử nghiệm hàm merge_mp3_files kèm 0.2s silence
        success = merge_mp3_files([part1, part2], out_mp3, silence_seconds=0.2)
        assert success is True
        assert out_mp3.exists()
        assert out_mp3.stat().st_size > part1.stat().st_size
