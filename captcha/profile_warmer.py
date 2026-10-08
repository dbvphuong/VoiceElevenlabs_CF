"""Mô-đun nuôi và tăng điểm tín nhiệm (Warm up Trust Score) cho Profile Chrome."""

import time
import random
import asyncio
from pathlib import Path
from typing import Optional, Callable
from playwright.async_api import async_playwright
from loguru import logger

from network.proxy_pool import resolve_proxy_or_api_key
from network.proxy_checker import get_exit_ip
from captcha.profile_manager import profile_manager, cleanup_profile_locks

class ProfileWarmer:
    """Điều phối quy trình nuôi Profile qua 3 bước: YouTube -> VnExpress -> hCaptcha Demo."""

    async def warm_profile(
        self,
        proxy_raw: Optional[str] = None,
        proxy_list: Optional[list] = None,
        show_window: bool = False,
        window_pos: Optional[tuple] = None,
        worker_id: int = 1,
        on_progress: Optional[Callable[[str], None]] = None,
    ) -> Path:
        """Thực hiện chu trình nuôi 1 Profile mới và chuyển vào profiles_dung.
        Chỉ ghi log khi lỗi hoặc khi hoàn thành để tránh làm nhiễu nhật ký.
        """

        tag = f"[Luồng {worker_id}] " if worker_id > 0 else ""

        def update_status(status_text: str):
            """Chỉ cập nhật trạng thái hiển thị ngắn gọn trên thanh giao diện, không spam log."""
            if on_progress:
                on_progress(f"{tag}{status_text}")
            logger.debug(f"{tag}{status_text}")

        update_status("Đang chuẩn bị proxy...")

        # ============================================================
        # 1. ĐỔI IP & KIỂM TRA PROXY
        # ============================================================
        proxy_info = None
        candidates = list(proxy_list) if proxy_list else ([proxy_raw] if proxy_raw else [])
        valid_candidates = [c.strip() for c in candidates if c and c.strip().lower() not in ("null", "none", "")]

        if valid_candidates:
            for candidate in valid_candidates:
                res_ip, p_info = await resolve_proxy_or_api_key(candidate)
                if not res_ip or not p_info:
                    continue

                exit_ip = get_exit_ip(p_info["curl_url"], timeout=6.0)
                if exit_ip:
                    proxy_info = p_info
                    break

            if not proxy_info:
                err_msg = "Không có Proxy nào trong danh sách phản hồi Internet."
                logger.error(f"{tag}Lỗi nuôi profile: {err_msg}")
                raise RuntimeError(err_msg)

        # ============================================================
        # 2. KHỞI TẠO SESSION PROFILE
        # ============================================================
        session_dir = profile_manager.create_new_nuoi_session(prefix=f"nuoi_w{worker_id}")
        cleanup_profile_locks(session_dir)

        is_warmed_successfully = False
        try:
            update_status("Đang mở trình duyệt...")

            browser_args = [
                "--disable-blink-features=AutomationControlled",
                "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
                "--enforce-webrtc-ip-permission-check",
                "--window-size=1200,800",
            ]

            if not show_window:
                browser_args.append("--window-position=3000,3000")
            else:
                if window_pos:
                    browser_args.append(f"--window-position={window_pos[0]},{window_pos[1]}")
                else:
                    browser_args.append("--window-position=100,100")

            launch_kwargs = {
                "user_data_dir": str(session_dir),
                "headless": False,  # Bắt buộc False để bảo toàn trust score hCaptcha
                "args": browser_args,
                "viewport": {"width": 1200, "height": 800},
                "locale": "vi-VN",
            }

            if proxy_info:
                launch_kwargs["proxy"] = proxy_info["playwright"]

            async with async_playwright() as pw:
                try:
                    context = await pw.chromium.launch_persistent_context(
                        channel="chrome",
                        **launch_kwargs
                    )
                except Exception:
                    context = await pw.chromium.launch_persistent_context(
                        **launch_kwargs
                    )

                page = context.pages[0] if context.pages else await context.new_page()

                async def safe_goto(url: str, timeout_ms: int = 35000, retries: int = 2) -> bool:
                    for attempt in range(retries):
                        try:
                            await page.goto(url, wait_until="commit", timeout=timeout_ms)
                            return True
                        except Exception:
                            if attempt < retries - 1:
                                await asyncio.sleep(2)
                            else:
                                return False
                    return False

                try:
                    # ============================================================
                    # 3.1: YOUTUBE (~15 giây)
                    # ============================================================
                    update_status("Đang nạp Cookie YouTube...")
                    ok_yt = await safe_goto("https://www.youtube.com", timeout_ms=35000)
                    if ok_yt:
                        await asyncio.sleep(random.uniform(4.0, 5.0))
                        try:
                            search_input = page.locator("input#search, input[name='search_query']").first
                            if await search_input.count() > 0:
                                await search_input.click()
                                await page.keyboard.type("tin tức hôm nay", delay=random.randint(60, 110))
                                await page.keyboard.press("Enter")
                                await asyncio.sleep(random.uniform(2.0, 3.0))
                        except Exception:
                            pass

                        await page.mouse.wheel(0, random.randint(460, 540))
                        await asyncio.sleep(random.uniform(1.8, 2.5))

                    # ============================================================
                    # 3.2: VNEXPRESS (~25 giây)
                    # ============================================================
                    update_status("Đang nạp Cache VnExpress...")
                    ok_vn = await safe_goto("https://vnexpress.net", timeout_ms=35000)
                    if ok_vn:
                        await asyncio.sleep(random.uniform(3.0, 4.0))
                        await page.mouse.wheel(0, random.randint(600, 750))
                        await asyncio.sleep(random.uniform(1.2, 2.0))
                        await page.mouse.wheel(0, random.randint(650, 800))
                        await asyncio.sleep(random.uniform(1.5, 2.2))

                        try:
                            articles = page.locator("article.item-news a.title-news, h3.title-news a, .item-news h3 a")
                            cnt = await articles.count()
                            if cnt > 0:
                                pick_idx = random.randint(0, min(cnt - 1, 8))
                                target_link = articles.nth(pick_idx)
                                await target_link.click(timeout=8000)
                                await asyncio.sleep(random.uniform(5.0, 7.0))
                                await page.mouse.wheel(0, random.randint(350, 450))
                                await asyncio.sleep(random.uniform(1.5, 2.0))
                        except Exception:
                            pass

                    # ============================================================
                    # 3.3: HCAPTCHA DEMO (~10 giây)
                    # ============================================================
                    update_status("Đang nạp Script hCaptcha Demo...")
                    ok_hc = await safe_goto("https://accounts.hcaptcha.com/demo", timeout_ms=35000)
                    if ok_hc:
                        await asyncio.sleep(random.uniform(4.0, 5.0))
                        for _ in range(random.randint(6, 9)):
                            tx = random.randint(200, 800)
                            ty = random.randint(150, 550)
                            await page.mouse.move(tx, ty, steps=random.randint(5, 10))
                            await asyncio.sleep(random.uniform(0.15, 0.35))

                        await asyncio.sleep(random.uniform(2.0, 2.5))

                finally:
                    update_status("Đang đóng trình duyệt...")
                    await context.close()

            # Giải phóng hoàn toàn các tiến trình Chrome con và khóa tệp
            cleanup_profile_locks(session_dir)
            await asyncio.sleep(1.0)

            # Di chuyển sang profiles_dung (MOVE, không sao chép)
            target_dung_dir = profile_manager.transfer_to_dung(session_dir)
            is_warmed_successfully = True

            # Ghi duy nhất 1 dòng thành công rõ ràng
            logger.success(f"{tag}Nuôi Profile thành công: {target_dung_dir.name} -> Đã chuyển vào profiles_dung")
            update_status(f"Hoàn thành: {target_dung_dir.name}")

            return target_dung_dir

        except Exception as ex:
            logger.error(f"{tag}Lỗi nuôi profile ({session_dir.name}): {ex}")
            raise

        finally:
            if not is_warmed_successfully and session_dir.exists():
                cleanup_profile_locks(session_dir)
                profile_manager.delete_profile(session_dir)

profile_warmer = ProfileWarmer()
