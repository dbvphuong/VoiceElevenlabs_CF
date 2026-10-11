"""Client tương tác với dịch vụ proxy xoay proxyxoay.shop (TopProxy)."""

import re
import time
import asyncio
from typing import Tuple, Optional
from urllib.parse import quote
from curl_cffi import requests
from loguru import logger
from config.constants import TOP_PROXY_API_URL

def parse_top_proxy_response(json_data: dict) -> Tuple[Optional[str], int, str]:
    """Phân tích phản hồi từ API proxyxoay.shop.
    Trả về: (proxy_str, wait_seconds, error_message)
    """
    status = json_data.get("status", 0)
    message = str(json_data.get("message", ""))

    # Status 100: Thành công lấy được proxy mới
    if status == 100:
        proxy_http = str(json_data.get("proxyhttp", "")).strip()
        if proxy_http.endswith("::"):
            proxy_http = proxy_http[:-2]
        if proxy_http:
            return proxy_http, 0, ""
        return None, 0, "TopProxy trả về status 100 nhưng trường proxyhttp rỗng."

    # Status 101: Đang trong thời gian chờ đổi IP
    if status == 101:
        match = re.search(r"\bCon\s+(\d+)s\b", message, re.IGNORECASE)
        if match:
            seconds = int(match.group(1))
            return None, max(1, min(seconds, 3600)), ""
        return None, 10, "Đang chờ đổi IP nhưng không đọc được số giây."

    return None, 0, f"TopProxy status {status}: {message}"

async def query_top_proxy(api_key: str) -> Tuple[Optional[str], int, str]:
    """Gửi một yêu cầu kiểm tra/đổi IP từ TopProxy một lần duy nhất.
    Trả về: (proxy_str, wait_seconds, error_message)
    """
    if not api_key:
        return None, 0, "API key rỗng"

    url = TOP_PROXY_API_URL.format(key=quote(api_key))
    try:
        response = requests.get(url, timeout=12)
        if response.status_code != 200:
            err = f"TopProxy HTTP {response.status_code}: {response.text[:120]}"
            logger.error(err)
            return None, 0, err

        data = response.json()
        return parse_top_proxy_response(data)
    except Exception as e:
        err = f"Lỗi kết nối API TopProxy: {e}"
        logger.error(err)
        return None, 0, err

async def get_new_proxy_from_top_proxy(
    api_key: str,
    max_wait_rounds: int = 1,
    allow_wait: bool = False
) -> Optional[str]:
    """Lấy địa chỉ HTTP proxy mới từ API key của proxyxoay.shop.
    Nếu allow_wait=False: trả về None ngay nếu gặp cooldown để chuyển sang key khác.
    Nếu allow_wait=True: chờ theo nhịp 0.5s để phản hồi ngay khi dừng.
    """
    if not api_key:
        return None

    for _ in range(max_wait_rounds):
        logger.info(f"Đang yêu cầu IP mới từ TopProxy...")
        proxy, wait_seconds, error = await query_top_proxy(api_key)

        if proxy:
            logger.success(f"Đã nhận proxy từ TopProxy: {proxy}")
            return proxy

        if wait_seconds > 0:
            if not allow_wait:
                logger.info(f"TopProxy yêu cầu chờ {wait_seconds}s, tự động chuyển sang key khác...")
                return None

            logger.info(f"TopProxy yêu cầu chờ {wait_seconds}s trước khi đổi IP mới...")
            for _ in range(int(wait_seconds * 2)):
                await asyncio.sleep(0.5)
        else:
            if error:
                logger.error(f"Lỗi từ TopProxy: {error}")
            return None

    return None

