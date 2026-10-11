"""Quản lý danh sách Proxy, cơ chế Round-robin, Cooldown và phân phối cho nhiều luồng."""

import time
import asyncio
from typing import List, Optional, Dict, Any, Tuple
from urllib.parse import urlparse
from loguru import logger
from network.top_proxy_client import get_new_proxy_from_top_proxy, query_top_proxy
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
        # Circuit Breaker: phát hiện và tạm ngắt key bị chết kết nối liên tục
        self.consecutive_connection_failures: int = 0
        self.disabled_until: float = 0.0
        self.circuit_breaker_active: bool = False

    @property
    def proxy_info(self) -> Optional[Dict[str, Any]]:
        return parse_proxy_string(self.current_ip) if self.current_ip else None

class ProxyPool:
    """Bộ điều phối Proxy đa luồng với cơ chế Round-robin, Cooldown chuẩn và Circuit Breaker."""

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
        """Lấy một proxy key khả dụng theo cơ chế Round-robin (tự động bỏ qua key đang bị Circuit Breaker ngắt)."""
        async with self._lock:
            if not self.keys:
                return None

            now = time.time()
            total = len(self.keys)
            for offset in range(total):
                idx = (self._next_index + offset) % total
                candidate = self.keys[idx]

                # Kiểm tra nếu key đã hết hạn phạt Circuit Breaker
                if candidate.circuit_breaker_active:
                    if now < candidate.disabled_until:
                        continue  # Vẫn đang trong thời gian tạm ngắt
                    # Đã hết 15 phút tạm ngắt, cho thử lại một cơ hội
                    candidate.circuit_breaker_active = False
                    candidate.consecutive_connection_failures = 0
                    logger.info(f"[CIRCUIT BREAKER] Key {candidate.key[:10]}... đã hết thời gian phạt 15 phút, cho phép thử lại.")

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
                new_target = time.time() + cooldown_seconds
                key.next_available_time = max(key.next_available_time, new_target)
                logger.debug(f"Proxy key {key.key[:15]}... được gắn cooldown {cooldown_seconds}s.")

    async def ensure_active_ip(self, key: RotatingProxyKey, force_rotate: bool = False) -> bool:
        """Đảm bảo proxy key có IP hoạt động (tự gọi API TopProxy với Cooldown chính xác và Circuit Breaker)."""
        if key.is_direct_proxy:
            parsed = parse_proxy_string(key.key)
            exit_ip = get_exit_ip(parsed["curl_url"], timeout=8.0) if parsed else None
            key.current_exit_ip = exit_ip
            if exit_ip:
                key.consecutive_connection_failures = 0
                key.circuit_breaker_active = False
                return True
            else:
                key.consecutive_connection_failures += 1
                if key.consecutive_connection_failures >= 4:
                    key.disabled_until = time.time() + 900
                    key.next_available_time = key.disabled_until
                    key.circuit_breaker_active = True
                    logger.error(f"[CIRCUIT BREAKER] Proxy tĩnh {key.key} lỗi kết nối {key.consecutive_connection_failures} lần liên tiếp. TẠM KHÓA 15 PHÚT!")
                return False

        if force_rotate or not key.current_ip:
            proxy_str, wait_seconds, error_msg = await query_top_proxy(key.key)

            # Trường hợp 1: TopProxy đang trong thời gian chờ đổi IP (Status 101)
            if wait_seconds > 0:
                key.next_available_time = time.time() + wait_seconds
                logger.info(f"TopProxy key {key.key[:10]}... đang trong thời gian chờ ({wait_seconds}s). Đặt Cooldown chuẩn {wait_seconds}s.")
                return False

            # Trường hợp 2: Lấy được proxy mới từ TopProxy
            if proxy_str:
                key.current_ip = proxy_str
                parsed_new = parse_proxy_string(proxy_str)
                # Cho proxy 0.5s để server TopProxy sẵn sàng
                await asyncio.sleep(0.5)
                exit_ip = get_exit_ip(parsed_new["curl_url"], timeout=8.0) if parsed_new else None
                key.current_exit_ip = exit_ip
                key.last_observed_exit_ip = exit_ip

                if not exit_ip:
                    key.consecutive_connection_failures += 1
                    key.current_ip = ""
                    key.current_exit_ip = None
                    logger.warning(
                        f"Proxy {proxy_str} từ key {key.key[:10]}... không phản hồi mạng (lỗi liên tiếp: {key.consecutive_connection_failures})."
                    )

                    # Kích hoạt Circuit Breaker nếu chết cổng 4 lần liên tiếp (ví dụ lỗi port 10110 bị reset)
                    if key.consecutive_connection_failures >= 4:
                        key.disabled_until = time.time() + 900
                        key.next_available_time = key.disabled_until
                        key.circuit_breaker_active = True
                        logger.error(
                            f"[CIRCUIT BREAKER] Proxy key {key.key[:10]}... bị lỗi kết nối {key.consecutive_connection_failures} lần liên tiếp (nghi ngờ chết cổng máy chủ). "
                            f"TẠM KHÓA KEY NÀY TRONG 15 PHÚT ĐỂ TRÁNH NGHẼN LUỒNG!"
                        )
                    else:
                        key.next_available_time = time.time() + 25  # Chờ 25s trước khi thử lại

                    return False

                # Kết nối thành công -> Reset bộ đếm lỗi
                key.consecutive_connection_failures = 0
                key.circuit_breaker_active = False
                logger.info(f"Đã xoay IP TopProxy thành công: {proxy_str} (Exit IP: {exit_ip})")
                return True

            # Trường hợp 3: TopProxy báo lỗi khác
            logger.warning(f"TopProxy key {key.key[:10]}... không thể cấp IP: {error_msg}")
            key.next_available_time = time.time() + 20
            return False

        # Nếu đã có IP nhưng chưa kiểm tra exit IP hoặc cần xác minh
        if key.current_ip and not key.current_exit_ip:
            parsed = parse_proxy_string(key.current_ip)
            exit_ip = get_exit_ip(parsed["curl_url"], timeout=8.0) if parsed else None
            key.current_exit_ip = exit_ip
            if not exit_ip:
                logger.warning(f"Proxy {key.current_ip} không phản hồi mạng, hủy IP này.")
                key.current_ip = ""
                key.consecutive_connection_failures += 1
                return False
            key.consecutive_connection_failures = 0

        return True

