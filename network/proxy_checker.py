"""Kiểm tra địa chỉ IP thoát thực tế (Exit IP) qua ipify.org."""

from typing import Optional
from curl_cffi import requests
from loguru import logger
from config.constants import IPIFY_URL

import time

CHECK_IP_URLS = [
    IPIFY_URL,
    "https://icanhazip.com",
    "https://api.my-ip.io/ip",
]

def get_exit_ip(proxy_url: Optional[str] = None, timeout: float = 8.0) -> Optional[str]:
    """Kiểm tra IP public thực tế khi đi qua Proxy (hỗ trợ nhiều endpoint dự phòng và retry)."""
    proxies = None
    if proxy_url and proxy_url.lower() != "null":
        proxies = {
            "http": proxy_url,
            "https": proxy_url
        }

    last_error = None
    for idx, check_url in enumerate(CHECK_IP_URLS):
        try:
            if idx > 0:
                time.sleep(1.2)  # Đợi 1.2s để proxy kịp mở socket routing nếu vừa đổi IP
            response = requests.get(
                check_url,
                proxies=proxies,
                timeout=timeout
            )
            if response.status_code == 200:
                ip = response.text.strip()
                if ip and len(ip) <= 45 and ("." in ip or ":" in ip):
                    return ip
        except Exception as e:
            last_error = e

    logger.warning(f"Không kiểm tra được IP thoát qua {proxy_url or 'Direct'}: {last_error}")
    return None
