"""Dịch vụ tự động hóa Playwright để farm token hCaptcha invisible cho ElevenLabs."""

import time
import random
import asyncio
from pathlib import Path
from typing import Optional, Dict, Any, Callable
from playwright.async_api import async_playwright, Playwright, Browser, BrowserContext, Page, Route
from loguru import logger

from config.constants import ELEVENLABS_HOME_URL
from captcha.scripts import HCAPTCHA_TRIGGER_JS
from network.proxy_pool import parse_proxy_string, resolve_proxy_or_api_key
from captcha.profile_manager import profile_manager, cleanup_profile_locks


import subprocess
from captcha.chrome_launcher import (
    launch_chrome_native,
    wait_for_cdp_port,
    kill_process_tree,
    get_free_port,
)


class NavigationNetworkError(RuntimeError):
    """Không thể mở trang đích do kết nối mạng hoặc proxy."""


def is_navigation_network_error(error: Exception) -> bool:
    message = str(error).lower()
    return any(marker in message for marker in (
        "net::err_connection_closed",
        "net::err_connection_reset",
        "net::err_empty_response",
        "net::err_timed_out",
        "net::err_tunnel_connection_failed",
        "net::err_proxy_connection_failed",
        "page.goto: timeout",
        "chromewebdata",
        "interrupted by another navigation",
        "chrome-error",
    ))


class TokenFarmer:
    """Quản lý một phiên trình duyệt Chrome Native (CDP) để farm token hCaptcha."""

    def __init__(
        self,
        proxy_raw: Optional[str] = None,
        headless: bool = False,
        off_screen: bool = True,
        profile_path: Optional[Path] = None,
        is_new_nuoi: bool = False,
    ):
        self.proxy_raw = proxy_raw
        self.headless = headless
        self.off_screen = off_screen
        self.is_new_nuoi = is_new_nuoi
        if is_new_nuoi:
            self.profile_path = profile_manager.create_new_nuoi_session(prefix="seq_nuoi")
        else:
            self.profile_path = profile_path or profile_manager.get_next_warmed_profile()
        self._proxy_info = parse_proxy_string(proxy_raw)
        self.is_session_warmed: bool = False

        self._proc: Optional[subprocess.Popen] = None
        self._cdp_port: Optional[int] = None
        self._pw: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._lock = asyncio.Lock()

    @property
    def profile_name(self) -> str:
        """Tên profile đang được nạp."""
        return self.profile_path.name if self.profile_path else "Chrome Mặc định"

    async def start(self) -> None:
        """Khởi động trình duyệt Google Chrome với Profile persistent sạch qua Playwright."""
        if (
            self._context
            and self._page
            and not self._page.is_closed()
        ):
            return

        if self._context or self._browser or self._page or self._pw:
            await self.close()

        # Phân giải proxy nếu là API key
        if not self._proxy_info and self.proxy_raw:
            resolved_ip, p_info = await resolve_proxy_or_api_key(self.proxy_raw)
            if p_info:
                self._proxy_info = p_info
                self.proxy_raw = resolved_ip

        target_profile = self.profile_path or profile_manager.get_next_warmed_profile()
        if not target_profile or not target_profile.exists():
            target_profile = profile_manager.create_new_nuoi_session(prefix="farmer_session")
            self.is_new_nuoi = True

        self.profile_path = target_profile
        cleanup_profile_locks(target_profile)
        logger.info(f"TokenFarmer nạp Profile Chrome: {target_profile.name}")

        self._pw = await async_playwright().start()

        browser_args = [
            "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
            "--enforce-webrtc-ip-permission-check",
            "--disable-blink-features=AutomationControlled",
        ]

        if self.off_screen and not self.headless:
            browser_args.extend([
                "--window-position=3000,3000",
                "--window-size=1200,800"
            ])

        launch_kwargs: Dict[str, Any] = {
            "headless": self.headless,
            "args": browser_args,
            "viewport": {"width": 1200, "height": 800},
            "locale": "vi-VN",
        }

        if self._proxy_info:
            launch_kwargs["proxy"] = self._proxy_info["playwright"]
            logger.debug(f"TokenFarmer gắn Proxy: {self._proxy_info['playwright']['server']}")

        try:
            self._context = await self._pw.chromium.launch_persistent_context(
                user_data_dir=str(target_profile),
                channel="chrome",
                **launch_kwargs
            )
        except Exception as ex1:
            if "existing browser session" in str(ex1).lower():
                logger.warning(f"Profile {target_profile.name} bị khóa bởi phiên trước, dọn dẹp và thử lại...")
                cleanup_profile_locks(target_profile)
                await asyncio.sleep(1.0)
            try:
                self._context = await self._pw.chromium.launch_persistent_context(
                    user_data_dir=str(target_profile),
                    channel="chrome",
                    **launch_kwargs
                )
            except Exception:
                self._context = await self._pw.chromium.launch_persistent_context(
                    user_data_dir=str(target_profile),
                    **launch_kwargs
                )

        self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()

        # Cho phép đầy đủ script và tài nguyên ElevenLabs / Cloudflare / hCaptcha
        async def block_heavy_resources(route: Route):
            req_url = route.request.url.lower()
            if "hcaptcha" in req_url or "cloudflare" in req_url or "elevenlabs" in req_url:
                await route.continue_()
                return

            if route.request.resource_type in ["media", "font"]:
                await route.abort()
            else:
                await route.continue_()

        await self._page.route("**/*", block_heavy_resources)
        logger.debug(f"TokenFarmer đã sẵn sàng với Profile {target_profile.name}.")

    async def warm_session(
        self,
        on_progress: Optional[Callable[[str], None]] = None,
        cancel_event: Optional[asyncio.Event] = None
    ) -> bool:
        if cancel_event and cancel_event.is_set():
            return False

        async with self._lock:
            if cancel_event and cancel_event.is_set():
                return False
            await self.start()
            if not self._page or (cancel_event and cancel_event.is_set()):
                return False

            def report(msg: str):
                if on_progress:
                    on_progress(msg)
                logger.info(f"[{self.profile_name}] {msg}")

            async def safe_goto(url: str, timeout_ms: int = 30000) -> bool:
                if cancel_event and cancel_event.is_set():
                    return False
                try:
                    await self._page.goto(url, wait_until="commit", timeout=timeout_ms)
                    return True
                except Exception as e:
                    logger.debug(f"safe_goto {url} thất bại: {e}")
                    return False

            try:
                # Nuôi siêu tốc: Nạp endpoint hCaptcha Demo và rê chuột 2s để tạo session trust
                report("Đang nạp Script hCaptcha Demo & rê chuột 2s...")
                ok_hc = await safe_goto("https://accounts.hcaptcha.com/demo", timeout_ms=15000)
                if ok_hc and not (cancel_event and cancel_event.is_set()):
                    for _ in range(random.randint(4, 6)):
                        if cancel_event and cancel_event.is_set():
                            return False
                        tx = random.randint(150, 750)
                        ty = random.randint(120, 500)
                        await self._page.mouse.move(tx, ty, steps=random.randint(4, 8))
                        await asyncio.sleep(random.uniform(0.2, 0.35))
                    await asyncio.sleep(0.5)

                self.is_session_warmed = True
                report("Nuôi siêu tốc trên IP hoàn tất!")
                return True

            except Exception as e:
                logger.warning(f"Lỗi trong quá trình warm_session ({self.profile_name}): {e}")
                return False

    async def get_token(self, timeout_seconds: float = 35.0) -> str:
        """Kích hoạt và lấy một token hCaptcha mới từ ElevenLabs."""
        async with self._lock:
            await self.start()
            if not self._page:
                raise RuntimeError("Page chưa được khởi tạo.")

            start_time = time.time()
            try:
                # 1. Điều hướng tới elevenlabs.io nếu chưa mở
                if "elevenlabs.io" not in self._page.url:
                    for attempt in range(2):
                        try:
                            await self._page.goto(ELEVENLABS_HOME_URL, wait_until="commit", timeout=25000)
                            break
                        except Exception as goto_err:
                            if not is_navigation_network_error(goto_err):
                                raise
                            if attempt == 1:
                                raise NavigationNetworkError(
                                    f"Không mở được elevenlabs.io qua kết nối hiện tại sau 2 lần: {goto_err}"
                                ) from goto_err
                            logger.warning(f"Kết nối tới elevenlabs.io bị ngắt; thử lại sau 1.5s: {goto_err}")
                            await asyncio.sleep(1.5)
                    await self._page.wait_for_load_state("domcontentloaded", timeout=15000)
                    # Mô phỏng chuột nhẹ để kích hoạt hành vi tự nhiên
                    try:
                        await self._page.mouse.move(250, 300)
                        await asyncio.sleep(0.4)
                    except Exception:
                        pass

                # 2. Inject script và nhận Promise token
                token = await asyncio.wait_for(
                    self._page.evaluate(HCAPTCHA_TRIGGER_JS),
                    timeout=timeout_seconds
                )

                elapsed = time.time() - start_time
                logger.debug(f"Đã lấy token hCaptcha thành công trong {elapsed:.2f}s (Độ dài: {len(token)}).")

                # 3. Đưa trang về about:blank để dọn dẹp RAM
                try:
                    await self._page.goto("about:blank", timeout=5000)
                except Exception:
                    pass

                return token

            except Exception as e:
                logger.warning(f"Lỗi khi lấy token hCaptcha ({type(e).__name__}): {e}")
                try:
                    await self._page.goto("about:blank", timeout=5000)
                except Exception:
                    pass
                if is_navigation_network_error(e) and not isinstance(e, NavigationNetworkError):
                    raise NavigationNetworkError(str(e)) from e
                raise

    async def finish_and_save(self) -> Optional[Path]:
        """Đóng phiên và chuyển profile đã nuôi thành công vào kho profiles_dung."""
        current_prof = self.profile_path
        await self.close()
        if current_prof and current_prof.exists() and "profiles_nuoi" in str(current_prof):
            try:
                dung_path = profile_manager.transfer_to_dung(current_prof)
                return dung_path
            except Exception as ex:
                logger.warning(f"Không thể chuyển profile sang profiles_dung: {ex}")
        return None

    async def close(self) -> None:
        """Đóng toàn bộ phiên trình duyệt Chrome và giải phóng tài nguyên."""
        current_prof = self.profile_path
        try:
            if self._page and not self._page.is_closed():
                await self._page.close()
        except Exception:
            pass
        try:
            if self._context:
                await self._context.close()
        except Exception:
            pass
        try:
            if self._browser and self._browser.is_connected():
                await self._browser.close()
        except Exception:
            pass
        try:
            if self._pw:
                await self._pw.stop()
        except Exception:
            pass
        finally:
            if self._proc:
                kill_process_tree(self._proc)
                self._proc = None
            self._cdp_port = None
            self._context = None
            self._browser = None
            self._page = None
            self._pw = None

            if current_prof:
                cleanup_profile_locks(current_prof)
                if self.is_new_nuoi and current_prof.exists() and "profiles_nuoi" in str(current_prof):
                    # Nếu là session nuôi tạm chưa được lưu sang profiles_dung thì dọn dẹp
                    profile_manager.delete_profile(current_prof)
                else:
                    profile_manager.release_profile(current_prof)
                self.profile_path = None

    async def discard_profile(self) -> None:
        """Đóng toàn bộ phiên trình duyệt và xóa vĩnh viễn profile này do bị lỗi captcha hoặc bị chặn."""
        target_path = self.profile_path
        self.profile_path = None
        await self.close()
        if target_path and target_path.exists():
            await asyncio.sleep(0.5)
            profile_manager.delete_profile(target_path)

