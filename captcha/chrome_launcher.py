"""Mô-đun khởi chạy và quản lý tiến trình Google Chrome native qua Chrome DevTools Protocol (CDP)."""

import os
import time
import socket
import shutil
import asyncio
import subprocess
from pathlib import Path
from typing import Optional, List, Tuple
from loguru import logger

def find_chrome_executable() -> str:
    """Tự động tìm kiếm đường dẫn thực thi Google Chrome trên máy tính."""
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe"),
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p
    which_chrome = shutil.which("chrome") or shutil.which("google-chrome") or shutil.which("chromium")
    if which_chrome:
        return which_chrome
    return r"C:\Program Files\Google\Chrome\Application\chrome.exe"

def get_free_port() -> int:
    """Lấy một cổng TCP tự do trên localhost do OS cấp phát."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]

async def wait_for_cdp_port(port: int, timeout: float = 12.0) -> bool:
    """Chờ tiến trình Chrome mở cổng Remote Debugging sẵn sàng nhận kết nối CDP."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            reader, writer = await asyncio.open_connection('127.0.0.1', port)
            writer.close()
            await writer.wait_closed()
            return True
        except (OSError, ConnectionRefusedError):
            await asyncio.sleep(0.15)
    return False

def launch_chrome_native(
    profile_dir: Path,
    port: int,
    proxy_server: Optional[str] = None,
    show_window: bool = False,
    window_pos: Optional[Tuple[int, int]] = None,
    extra_args: Optional[List[str]] = None,
) -> subprocess.Popen:
    """Khởi chạy tiến trình Google Chrome độc lập với profile riêng và cổng debug CDP."""
    chrome_exe = find_chrome_executable()
    if not os.path.isfile(chrome_exe):
        raise FileNotFoundError(f"Không tìm thấy Google Chrome tại: {chrome_exe}")

    profile_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        chrome_exe,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={str(profile_dir.resolve())}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-blink-features=AutomationControlled",
        "--disable-infobars",
        "--disable-background-networking",
        "--disable-background-timer-throttling",
        "--disable-backgrounding-occluded-windows",
        "--disable-breakpad",
        "--disable-component-update",
        "--disable-domain-reliability",
        "--disable-sync",
        "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
        "--enforce-webrtc-ip-permission-check",
    ]

    if proxy_server:
        cmd.append(f"--proxy-server={proxy_server}")

    if show_window:
        if window_pos:
            cmd.append(f"--window-position={window_pos[0]},{window_pos[1]}")
        else:
            cmd.append("--window-position=100,100")
        cmd.append("--window-size=1200,800")
    else:
        # Chạy ẩn / dịch ra ngoài khung nhìn
        cmd.append("--window-position=3000,3000")
        cmd.append("--window-size=1200,800")

    if extra_args:
        cmd.extend(extra_args)

    cmd.append("about:blank")

    logger.debug(f"Khởi chạy Chrome Native (Port: {port}, Profile: {profile_dir.name})...")
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return proc

def kill_process_tree(proc: Optional[subprocess.Popen]) -> None:
    """Đóng an toàn và dọn dẹp toàn bộ cây tiến trình của Chrome."""
    if proc is None:
        return
    try:
        proc.terminate()
        try:
            proc.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            if os.name == 'nt':
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False
                )
            else:
                proc.kill()
    except Exception as e:
        logger.debug(f"Dọn dẹp tiến trình Chrome {proc.pid}: {e}")
