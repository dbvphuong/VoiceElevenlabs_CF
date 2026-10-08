"""Kiểm tra địa chỉ IP thoát thực tế (Exit IP) qua ipify.org."""

from typing import Optional
from curl_cffi import requests
from loguru import logger
from config.constants import IPIFY_URL

def get_exit_ip(proxy_url: Optional[str] = None, timeout: float = 8.0) -> Optional[str]:
    """Kiểm tra IP public thực tế khi đi qua Proxy (hoặc IP gốc nếu proxy_url là None)."""
    proxies = None
    if proxy_url and proxy_url.lower() != "null":
        proxies = {
            "http": proxy_url,
            "https": proxy_url
        }

    try:
        response = requests.get(
            IPIFY_URL,
            proxies=proxies,
            timeout=timeout
        )
        if response.status_code == 200:
            ip = response.text.strip()
            return ip
    except Exception as e:
        logger.warning(f"Không kiểm tra được IP thoát qua {proxy_url or 'Direct'}: {e}")
        
    return None
