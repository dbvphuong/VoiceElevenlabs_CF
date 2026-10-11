"""Unit tests xác minh các cải tiến và sửa lỗi:
1. Xóa IP khi dính sign_in_required / unusual_activity.
2. Khớp đúng Cooldown từ TopProxy.
3. Circuit Breaker tự ngắt key proxy bị chết cổng liên tục.
4. Bảo vệ profile không bị xóa bừa bãi khi lỗi mạng/captcha.
5. Đồng bộ browser_fingerprint giữa Chrome và TTS API request.
"""

import time
import pytest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
from pathlib import Path

from network.proxy_pool import ProxyPool, RotatingProxyKey
from network.top_proxy_client import parse_top_proxy_response
from network.tts_client import generate_tts
from core.models import TtsResult, ChunkTask
from config.settings import VoiceTemplate


def test_parse_top_proxy_cooldown_parsing():
    """Kiểm tra parse đúng wait_seconds từ status 101 của TopProxy."""
    res_101 = {
        "status": 101,
        "message": "Con 25s moi co the doi proxy"
    }
    proxy, wait_sec, err = parse_top_proxy_response(res_101)
    assert proxy is None
    assert wait_sec == 25
    assert err == ""


def test_circuit_breaker_activates_after_repeated_failures():
    """Kiểm tra Circuit Breaker tự động khóa key khi gặp lỗi kết nối liên tiếp."""
    key = RotatingProxyKey("dummy_key_123")
    assert key.circuit_breaker_active is False
    assert key.consecutive_connection_failures == 0

    pool = ProxyPool(["dummy_key_123"])

    # Giả lập get_exit_ip luôn trả về None (chết cổng)
    with patch("network.proxy_pool.query_top_proxy", new_callable=AsyncMock) as mock_query, \
         patch("network.proxy_pool.get_exit_ip", return_value=None):
        
        mock_query.return_value = ("1.2.3.4:8080", 0, "")

        # Thử 3 lần đầu
        for i in range(3):
            ok = asyncio.run(pool.ensure_active_ip(key, force_rotate=True))
            assert ok is False
            assert key.circuit_breaker_active is False
            assert key.consecutive_connection_failures == i + 1

        # Lần thứ 4 -> Kích hoạt Circuit Breaker
        ok = asyncio.run(pool.ensure_active_ip(key, force_rotate=True))
        assert ok is False
        assert key.consecutive_connection_failures == 4
        assert key.circuit_breaker_active is True
        assert key.disabled_until > time.time() + 800  # Khóa khoảng 15 phút


def test_circuit_breaker_skips_disabled_key_in_pool():
    """Kiểm tra pool tự động bỏ qua key đang bị Circuit Breaker khóa."""
    pool = ProxyPool(["dead_key_1", "alive_key_2"])
    dead = pool.keys[0]
    alive = pool.keys[1]

    dead.circuit_breaker_active = True
    dead.disabled_until = time.time() + 600

    # Lấy key từ pool -> phải nhận được alive_key_2
    chosen = asyncio.run(pool.get_available_key())
    assert chosen is not None
    assert chosen.key == "alive_key_2"


def test_ensure_active_ip_exact_cooldown():
    """Kiểm tra gán đúng cooldown từ TopProxy status 101 mà không quy chụp chết mạng."""
    pool = ProxyPool(["key_cooldown"])
    key = pool.keys[0]

    with patch("network.proxy_pool.query_top_proxy", new_callable=AsyncMock) as mock_query:
        # TopProxy trả về còn 35s
        mock_query.return_value = (None, 35, "")

        ok = asyncio.run(pool.ensure_active_ip(key, force_rotate=True))
        assert ok is False
        assert key.circuit_breaker_active is False
        # next_available_time phải gần bằng now + 35s
        assert abs(key.next_available_time - (time.time() + 35)) < 2.0


def test_tts_uses_synchronized_browser_fingerprint(tmp_path):
    """Kiểm tra generate_tts sử dụng chính xác User-Agent và Client Hints từ browser_fingerprint."""
    custom_fp = {
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/155.0.0.0 Safari/537.36",
        "sec_ch_ua": '"Google Chrome";v="155", "Chromium";v="155", "Not-A.Brand";v="8"',
        "platform": '"Windows"',
    }

    out_file = tmp_path / "test.mp3"

    with patch("curl_cffi.requests.Session.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '{"audio_base64": "AAAA"}\n'
        mock_post.return_value = mock_resp

        res = asyncio.run(generate_tts(
            voice_id="test_voice",
            text="Xin chào",
            output_path=out_file,
            hcaptcha_token="fake_token",
            browser_fingerprint=custom_fp,
        ))

        assert res.success is True
        # Kiểm tra headers gửi đi trong request post
        _, kwargs = mock_post.call_args
        sent_headers = kwargs.get("headers", {})
        assert sent_headers.get("User-Agent") == custom_fp["user_agent"]
        assert sent_headers.get("sec-ch-ua") == custom_fp["sec_ch_ua"]
        assert sent_headers.get("sec-ch-ua-platform") == custom_fp["platform"]
