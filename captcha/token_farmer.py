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

class TokenFarmer:
    """Quản lý một phiên trình duyệt Chrome (thừa hưởng Profile đã nuôi) để farm token hCaptcha."""

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
        """Khởi động trình duyệt với Profile đã nuôi và cấu hình Off-screen anti-detect."""
        if self._context:
            return

        # Phân giải proxy nếu là API key
        if not self._proxy_info and self.proxy_raw:
            resolved_ip, p_info = await resolve_proxy_or_api_key(self.proxy_raw)
            if p_info:
                self._proxy_info = p_info
                self.proxy_raw = resolved_ip

        self._pw = await async_playwright().start()

        browser_args = [
            "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
            "--enforce-webrtc-ip-permission-check",
            "--disable-blink-features=AutomationControlled",
        ]

        # Chạy giao diện thật nhưng dịch ra ngoài màn hình nếu off_screen=True
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

        # 1. Nếu có Profile đã nuôi trong profiles_dung -> launch_persistent_context
        target_profile = self.profile_path or profile_manager.get_next_warmed_profile()

        if target_profile and target_profile.exists():
            self.profile_path = target_profile
            cleanup_profile_locks(target_profile)
            logger.info(f"TokenFarmer nạp Profile đã nuôi: {target_profile.name}")
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

        # 2. Nếu chưa có profile nào -> fallback khởi chạy browser thông thường
        else:
            logger.debug("Chưa có Profile đã nuôi sẵn, khởi chạy Chrome thông thường.")
            try:
                self._browser = await self._pw.chromium.launch(channel="chrome", **launch_kwargs)
            except Exception:
                self._browser = await self._pw.chromium.launch(**launch_kwargs)

            b_ver = self._browser.version
            ua = f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{b_ver} Safari/537.36"
            self._context = await self._browser.new_context(
                user_agent=ua,
                locale="vi-VN",
                viewport={"width": 1200, "height": 800}
            )
            self._page = await self._context.new_page()

        # Chặn video, audio, font nặng nhưng KHÔNG chặn hcaptcha/cloudflare để tránh challenge-error
        async def block_heavy_resources(route: Route):
            req_url = route.request.url.lower()
            if "hcaptcha" in req_url or "cloudflare" in req_url:
                await route.continue_()
                return

            if route.request.resource_type in ["media", "font"]:
                await route.abort()
            elif route.request.resource_type == "image" and "hcaptcha" not in req_url:
                await route.abort()
            else:
                await route.continue_()

        await self._page.route("**/*", block_heavy_resources)
        logger.debug("TokenFarmer đã sẵn sàng.")

    async def warm_session(
        self,
        on_progress: Optional[Callable[[str], None]] = None,
        cancel_event: Optional[asyncio.Event] = None
    ) -> bool:
        """Nuôi nhẹ Profile trực tiếp trên phiên trình duyệt và IP hiện tại (YouTube -> VnExpress -> hCaptcha Demo)."""
        async with self._lock:
            await self.start()
            if not self._page:
                return False

            def report(msg: str):
                if on_progress:
                    on_progress(msg)
                logger.info(f"[{self.profile_name}] {msg}")

            async def safe_goto(url: str, timeout_ms: int = 30000) -> bool:
                try:
                    await self._page.goto(url, wait_until="commit", timeout=timeout_ms)
                    return True
                except Exception as e:
                    logger.debug(f"safe_goto {url} thất bại: {e}")
                    return False

            try:
                # 1. YouTube (~8-10 giây)
                report("Đang nạp Cookie YouTube...")
                ok_yt = await safe_goto("https://www.youtube.com")
                if ok_yt and not (cancel_event and cancel_event.is_set()):
                    await asyncio.sleep(random.uniform(2.5, 3.5))
                    try:
                        search_input = self._page.locator("input#search, input[name='search_query']").first
                        if await search_input.count() > 0:
                            await search_input.click()
                            sample_queries = ["tin tức hôm nay", "nhạc lofi thư giãn", "tin việt nam mới nhất", "thời tiết hôm nay"]
                            q = random.choice(sample_queries)
                            await self._page.keyboard.type(q, delay=random.randint(40, 80))
                            await self._page.keyboard.press("Enter")
                            await asyncio.sleep(random.uniform(2.0, 3.0))
                    except Exception:
                        pass
                    try:
                        await self._page.mouse.wheel(0, random.randint(400, 600))
                        await asyncio.sleep(random.uniform(1.2, 1.8))
                    except Exception:
                        pass

                if cancel_event and cancel_event.is_set():
                    return False

                # 2. VnExpress (~10-12 giây)
                report("Đang nạp Cache VnExpress...")
                ok_vn = await safe_goto("https://vnexpress.net")
                if ok_vn and not (cancel_event and cancel_event.is_set()):
                    await asyncio.sleep(random.uniform(2.5, 3.5))
                    try:
                        await self._page.mouse.wheel(0, random.randint(500, 700))
                        await asyncio.sleep(random.uniform(1.2, 1.8))
                        articles = self._page.locator("article.item-news a.title-news, h3.title-news a, .item-news h3 a")
                        cnt = await articles.count()
                        if cnt > 0:
                            pick_idx = random.randint(0, min(cnt - 1, 5))
                            await articles.nth(pick_idx).click(timeout=6000)
                            await asyncio.sleep(random.uniform(3.0, 4.0))
                            await self._page.mouse.wheel(0, random.randint(300, 500))
                            await asyncio.sleep(random.uniform(1.0, 1.5))
                    except Exception:
                        pass

                if cancel_event and cancel_event.is_set():
                    return False

                # 3. hCaptcha Demo (~6-8 giây)
                report("Đang nạp Script hCaptcha Demo...")
                ok_hc = await safe_goto("https://accounts.hcaptcha.com/demo")
                if ok_hc and not (cancel_event and cancel_event.is_set()):
                    await asyncio.sleep(random.uniform(2.5, 3.5))
                    for _ in range(random.randint(5, 8)):
                        tx = random.randint(150, 750)
                        ty = random.randint(120, 500)
                        await self._page.mouse.move(tx, ty, steps=random.randint(4, 8))
                        await asyncio.sleep(random.uniform(0.1, 0.25))
                    await asyncio.sleep(random.uniform(1.5, 2.0))

                self.is_session_warmed = True
                report("Nuôi Profile trên IP này hoàn tất!")
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
                    await self._page.goto(ELEVENLABS_HOME_URL, wait_until="commit", timeout=25000)
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
        """Đóng toàn bộ phiên trình duyệt và giải phóng tài nguyên."""
        current_prof = self.profile_path
        try:
            if self._context:
                await self._context.close()
            if self._browser:
                await self._browser.close()
            if self._pw:
                await self._pw.stop()
        except Exception:
            pass
        finally:
            if current_prof:
                cleanup_profile_locks(current_prof)
                if self.is_new_nuoi and current_prof.exists() and "profiles_nuoi" in str(current_prof):
                    # Nếu là session nuôi tạm chưa được lưu sang profiles_dung thì dọn dẹp
                    profile_manager.delete_profile(current_prof)
                else:
                    profile_manager.release_profile(current_prof)
                self.profile_path = None
            self._context = None
            self._browser = None
            self._page = None
            self._pw = None

    async def discard_profile(self) -> None:
        """Đóng toàn bộ phiên trình duyệt và xóa vĩnh viễn profile này do bị lỗi captcha hoặc bị chặn."""
        target_path = self.profile_path
        self.profile_path = None
        await self.close()
        if target_path and target_path.exists():
            await asyncio.sleep(0.5)
            profile_manager.delete_profile(target_path)

