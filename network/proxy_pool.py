"""Quản lý danh sách Proxy, cơ chế Round-robin, Cooldown và phân phối cho nhiều luồng."""

import time
import asyncio
from typing import List, Optional, Dict, Any, Tuple
from urllib.parse import urlparse
from loguru import logger
from network.top_proxy_client import get_new_proxy_from_top_proxy
from network.proxy_checker import get_exit_ip

def parse_proxy_string(raw: Optional[str]) -> Optional[Dict[str, Any]]:
    """Phân tích chuỗi proxy (host:port, host:port:user:pass hoặc http://user:pass@host:port).
    Trả về dict chứa định dạng tương thích cho cả Playwright và curl_cffi.
    Trả về None nếu chuỗi rỗng, không hợp lệ, hoặc là API Key xoay proxy (không có port).
    """
    if not raw or raw.strip().lower() in ("null", "none", ""):
        return None

    candidate = raw.strip()
    # Nếu không chứa dấu hai chấm và không có @ thì chắc chắn không chứa port -> API Key
    if ":" not in candidate and "@" not in candidate:
        return None

    scheme = "http"
    if "://" in candidate:
        parts = candidate.split("://", 1)
        scheme = parts[0].lower()
        candidate = parts[1]

    user = ""
    password = ""
    host = ""
    port = ""

    # Dạng host:port:user:pass
    if "@" not in candidate and candidate.count(":") == 3:
        p_host, p_port, p_user, p_pass = candidate.split(":", 3)
        host, port, user, password = p_host, p_port, p_user, p_pass
    # Dạng host:port
    elif "@" not in candidate and candidate.count(":") == 1:
        p_host, p_port = candidate.split(":", 1)
        host, port = p_host, p_port
    else:
        # Dạng URI http://user:pass@host:port hoặc user:pass@host:port
        parsed = urlparse(f"{scheme}://{candidate}")
        host = parsed.hostname or ""
        if parsed.port:
            port = str(parsed.port)
        else:
            return None
        user = parsed.username or ""
        password = parsed.password or ""

    if not host or not port:
        return None

    try:
        port_num = int(port)
        if not (1 <= port_num <= 65535):
            return None
    except ValueError:
        return None

    curl_url = f"{scheme}://"
    if user:
        curl_url += f"{user}:{password}@" if password else f"{user}@"
    curl_url += f"{host}:{port_num}"

    playwright_dict: Dict[str, Any] = {
        "server": f"{scheme}://{host}:{port_num}"
    }
    if user:
        playwright_dict["username"] = user
        playwright_dict["password"] = password

    return {
        "raw": raw,
        "host": host,
        "port": port_num,
        "user": user,
        "password": password,
        "curl_url": curl_url,
        "playwright": playwright_dict,
    }

async def resolve_proxy_or_api_key(raw: Optional[str]) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """Phân giải chuỗi proxy cấu hình (có thể là IP:Port trực tiếp hoặc API Key xoay).
    Trả về: (proxy_str, proxy_dict_for_client)
    """
    if not raw or raw.strip().lower() in ("null", "none", ""):
        return None, None

    candidate = raw.strip()
    parsed = parse_proxy_string(candidate)
    if parsed is not None:
        return candidate, parsed

    # Trường hợp là API key (TopProxy)
    logger.info(f"Phát hiện API Key xoay, đang yêu cầu IP mới từ TopProxy...")
    new_ip = await get_new_proxy_from_top_proxy(candidate)
    if new_ip:
        parsed_new = parse_proxy_string(new_ip)
        return new_ip, parsed_new

    return None, None

class RotatingProxyKey:
    """Đại diện cho một thực thể proxy trong pool (Proxy trực tiếp hoặc API Key xoay)."""

    def __init__(self, key: str):
        self.key = key.strip()
        parsed = parse_proxy_string(self.key)
        self.is_direct_proxy = parsed is not None
        self.current_ip = self.key if self.is_direct_proxy else ""
        self.current_exit_ip: Optional[str] = None
        self.last_observed_exit_ip: Optional[str] = None
        self.is_being_used: bool = False
        self.next_available_time: float = 0.0

    @property
    def proxy_info(self) -> Optional[Dict[str, Any]]:
        return parse_proxy_string(self.current_ip) if self.current_ip else None

class ProxyPool:
    """Bộ điều phối Proxy đa luồng với cơ chế Round-robin và Cooldown."""

    def __init__(self, proxy_entries: List[str]):
        self.keys: List[RotatingProxyKey] = []
        self._lock = asyncio.Lock()
        self._next_index: int = 0

        seen = set()
        for entry in proxy_entries:
            e = entry.strip()
            if e and e.lower() != "null" and e not in seen:
                seen.add(e)
                self.keys.append(RotatingProxyKey(e))

        logger.info(f"Khởi tạo ProxyPool với {len(self.keys)} proxy / key xoay.")

    @property
    def count(self) -> int:
        return len(self.keys)

    async def get_available_key(self) -> Optional[RotatingProxyKey]:
        """Lấy một proxy key khả dụng theo cơ chế Round-robin."""
        async with self._lock:
            if not self.keys:
                return None

            now = time.time()
            total = len(self.keys)
            for offset in range(total):
                idx = (self._next_index + offset) % total
                candidate = self.keys[idx]
                if not candidate.is_being_used and candidate.next_available_time <= now:
                    candidate.is_being_used = True
                    self._next_index = (idx + 1) % total
                    return candidate

            return None

    async def release_key(self, key: RotatingProxyKey, cooldown_seconds: int = 0) -> None:
        """Trả proxy key về pool, có thể gắn thời gian chờ Cooldown."""
        async with self._lock:
            key.is_being_used = False
            if cooldown_seconds > 0:
                key.next_available_time = time.time() + cooldown_seconds
                logger.debug(f"Proxy key {key.key[:15]}... được gắn cooldown {cooldown_seconds}s.")

    async def ensure_active_ip(self, key: RotatingProxyKey, force_rotate: bool = False) -> bool:
        """Đảm bảo proxy key có IP hoạt động (tự gọi API TopProxy nếu là API key)."""
        if key.is_direct_proxy:
            parsed = parse_proxy_string(key.key)
            exit_ip = get_exit_ip(parsed["curl_url"], timeout=5.0) if parsed else None
            key.current_exit_ip = exit_ip
            return exit_ip is not None

        if force_rotate or not key.current_ip:
            new_ip = await get_new_proxy_from_top_proxy(key.key)
            if new_ip:
                key.current_ip = new_ip
                parsed_new = parse_proxy_string(new_ip)
                exit_ip = get_exit_ip(parsed_new["curl_url"], timeout=5.0) if parsed_new else None
                key.current_exit_ip = exit_ip
                key.last_observed_exit_ip = exit_ip
                if not exit_ip:
                    logger.warning(f"Proxy {new_ip} từ key {key.key[:10]}... không phản hồi mạng (Connection Reset).")
                    key.current_ip = ""
                    return False
                logger.info(f"Đã xoay IP TopProxy thành công: {new_ip} (Exit IP: {exit_ip})")
                return True
            else:
                return False

        # Nếu đã có IP nhưng chưa kiểm tra exit IP hoặc cần xác minh
        if key.current_ip and not key.current_exit_ip:
            parsed = parse_proxy_string(key.current_ip)
            exit_ip = get_exit_ip(parsed["curl_url"], timeout=5.0) if parsed else None
            key.current_exit_ip = exit_ip
            if not exit_ip:
                logger.warning(f"Proxy {key.current_ip} không phản hồi mạng, hủy IP này.")
                key.current_ip = ""
                return False

        return True
