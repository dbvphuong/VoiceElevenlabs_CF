"""Kiểm thử đơn vị cho mô-đun Chrome Native CDP Launcher."""

import os
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from captcha.chrome_launcher import (
    find_chrome_executable,
    get_free_port,
    wait_for_cdp_port,
    launch_chrome_native,
    kill_process_tree,
)


def test_find_chrome_executable():
    exe = find_chrome_executable()
    assert isinstance(exe, str)
    assert len(exe) > 0
    assert exe.lower().endswith("chrome.exe") or "chrome" in exe.lower()


def test_get_free_port():
    port1 = get_free_port()
    port2 = get_free_port()
    assert isinstance(port1, int)
    assert 1024 <= port1 <= 65535
    assert isinstance(port2, int)
    assert 1024 <= port2 <= 65535


@pytest.mark.asyncio
async def test_wait_for_cdp_port_timeout():
    # Cổng 9999 chưa được mở, timeout nhanh 0.1s phải trả về False
    port = get_free_port()
    ready = await wait_for_cdp_port(port, timeout=0.1)
    assert ready is False


def test_kill_process_tree_none_safe():
    # Truyền None không được ném Exception
    kill_process_tree(None)


def test_launch_chrome_native_args(tmp_path):
    mock_proc = MagicMock()
    with patch("captcha.chrome_launcher.subprocess.Popen", return_value=mock_proc) as mock_popen:
        profile_dir = tmp_path / "test_prof"
        port = 12345
        proc = launch_chrome_native(
            profile_dir=profile_dir,
            port=port,
            proxy_server="http://1.2.3.4:8080",
            show_window=True,
            window_pos=(200, 300),
        )

        assert proc == mock_proc
        mock_popen.assert_called_once()
        args = mock_popen.call_args[0][0]

        # Kiểm tra các tham số bắt buộc
        assert any(f"--remote-debugging-port={port}" in a for a in args)
        assert any(f"--user-data-dir={str(profile_dir.resolve())}" in a for a in args)
        assert any("--proxy-server=http://1.2.3.4:8080" in a for a in args)
        assert any("--window-position=200,300" in a for a in args)
        assert any("--disable-blink-features=AutomationControlled" in a for a in args)
