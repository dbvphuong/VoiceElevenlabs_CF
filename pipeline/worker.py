"""Worker xử lý từng đoạn văn bản (ChunkTask) trong quy trình TTS."""

import time
import asyncio
from pathlib import Path
from typing import Optional, Callable
from loguru import logger

from config.settings import AppSettings
from core.models import ChunkTask, TtsResult
from network.proxy_pool import ProxyPool, RotatingProxyKey
from network.tts_client import generate_tts, is_v4_model
from captcha.token_farmer import TokenFarmer

class WorkerState:
    """Trạng thái nội bộ của một Worker."""

    def __init__(self, worker_id: int, farmer: Optional[TokenFarmer] = None):
        self.worker_id = worker_id
        self.farmer = farmer
        self.current_proxy_key: Optional[RotatingProxyKey] = None
        self.consecutive_token_failures: int = 0
        self.restarts_without_token: int = 0

class PipelineWorker:
    """Điều phối logic của một luồng xử lý ChunkTask độc lập."""

    def __init__(
        self,
        worker_id: int,
        settings: AppSettings,
        proxy_pool: Optional[ProxyPool] = None,
        on_chunk_status: Optional[Callable[[int, int, str, str], None]] = None,
        on_chunk_completed: Optional[Callable[[ChunkTask], None]] = None,
        on_file_need_merge: Optional[Callable[[int], None]] = None,
        warm_and_voice: bool = False,
        show_browser: bool = False,
    ):
        self.worker_id = worker_id
        self.settings = settings
        self.proxy_pool = proxy_pool
        self.on_chunk_status = on_chunk_status
        self.on_chunk_completed = on_chunk_completed
        self.on_file_need_merge = on_file_need_merge
        self.warm_and_voice = warm_and_voice
        self.show_browser = show_browser

        self.farmer: Optional[TokenFarmer] = None
        self.current_proxy_str: Optional[str] = None
        self.state = WorkerState(worker_id)

    async def _ensure_farmer(self, proxy_str: Optional[str], force_restart: bool = False) -> TokenFarmer:
        """Đảm bảo TokenFarmer đang chạy và sử dụng đúng cổng proxy được chỉ định."""
        if (
            not force_restart
            and self.farmer is not None
            and self.current_proxy_str == proxy_str
        ):
            return self.farmer

        if self.farmer is not None:
            await self.farmer.close()

        self.current_proxy_str = proxy_str
        self.farmer = TokenFarmer(
            proxy_raw=proxy_str,
            headless=False,
            off_screen=not self.show_browser,
            is_new_nuoi=self.warm_and_voice
        )
        await self.farmer.start()
        return self.farmer

    def _update_status(self, task: ChunkTask, status: str, note: str = "") -> None:
        if self.on_chunk_status:
            self.on_chunk_status(task.file_index, task.chunk_index, status, note)

    async def process_chunk(
        self,
        task: ChunkTask,
        max_attempts: int,
        retry_round: int,
        cancel_event: asyncio.Event,
    ) -> bool:
        """Thực thi xử lý một ChunkTask.
        Trả về True nếu đoạn hoàn thành (hoặc bị bỏ qua sang vòng sau),
        Trả về False nếu gặp lỗi chặn nghiêm trọng khiến worker phải dừng lại.
        """
        file_name = Path(task.file_path).name
        chunk_num = task.chunk_index + 1
        self._update_status(task, "Đang xử lý", f"[Bước 1/5] Chuẩn bị proxy...")
        
        attempts = 0
        blocking_attempts = 0
        max_blocking_attempts = 10 if retry_round == 0 else 1
        last_failure = ""

        while not cancel_event.is_set():
            attempts += 1
            if attempts > max_attempts:
                msg = (
                    f"Đã thử {max_attempts} lần trong vòng này. "
                    f"Lỗi cuối: {last_failure}" if last_failure else ""
                )
                self._update_status(task, "Lỗi", msg)
                logger.warning(f"[Worker {self.worker_id}] Chunk {chunk_num} ({file_name}): {msg}")
                return True

            tot_steps = 6 if self.warm_and_voice else 5
            logger.info(f"--- [Worker {self.worker_id}] Bắt đầu xử lý Chunk {chunk_num} ({file_name}) ---")

            # ============================================================
            # [BƯỚC 1: ĐỔI IP MỚI]
            # ============================================================
            logger.info(f"[Worker {self.worker_id}] [Bước 1/{tot_steps}: Đổi IP mới]")
            self._update_status(task, "Đang xử lý", f"[Bước 1/{tot_steps}] Đổi IP mới...")

            proxy_key: Optional[RotatingProxyKey] = None
            cooldown_seconds = 0
            proxy_url_for_curl: Optional[str] = None
            raw_proxy_for_farmer: Optional[str] = None

            try:
                if self.proxy_pool and self.proxy_pool.count > 0:
                    proxy_key = await self.proxy_pool.get_available_key()
                    while proxy_key is None and not cancel_event.is_set():
                        await asyncio.sleep(1)
                        proxy_key = await self.proxy_pool.get_available_key()

                    if cancel_event.is_set():
                        return False

                    if proxy_key:
                        is_active = await self.proxy_pool.ensure_active_ip(proxy_key)
                        if not is_active:
                            logger.warning(f"[Worker {self.worker_id}] Proxy {proxy_key.key[:10]}... không phản hồi mạng, tự động đổi sang proxy khác trong pool...")
                            await self.proxy_pool.release_key(proxy_key, cooldown_seconds=60)
                            continue

                        p_info = proxy_key.proxy_info
                        if p_info:
                            proxy_url_for_curl = p_info["curl_url"]
                            raw_proxy_for_farmer = proxy_key.current_ip
                            logger.info(f"[Worker {self.worker_id}] [Bước 1/{tot_steps}: Đổi IP mới] [DONE] IP: {proxy_key.current_ip} (Exit IP: {proxy_key.current_exit_ip or 'N/A'})")
                        else:
                            logger.info(f"[Worker {self.worker_id}] [Bước 1/{tot_steps}: Đổi IP mới] [DONE] IP: {proxy_key.current_ip}")

                elif self.settings.static_proxies and self.settings.static_proxies.strip():
                    raw_proxy_for_farmer = self.settings.static_proxies.splitlines()[0].strip()
                    logger.info(f"[Worker {self.worker_id}] [Bước 1/{tot_steps}: Đổi IP mới] [DONE] Sử dụng Proxy tĩnh: {raw_proxy_for_farmer}")
                else:
                    logger.info(f"[Worker {self.worker_id}] [Bước 1/{tot_steps}: Đổi IP mới] [DONE] Kết nối mạng trực tiếp")

                logger.info("       ↓")

                # ============================================================
                # [BƯỚC 2: MỞ CHROME + GÁN IP ĐÓ VÀO]
                # ============================================================
                hcaptcha_token = ""
                need_captcha = not (is_v4_model(task.voice_profile.model_index) and self.settings.eleven_labs_api_key)

                farmer: Optional[TokenFarmer] = None
                if need_captcha:
                    logger.info(f"[Worker {self.worker_id}] [Bước 2/{tot_steps}: Mở Chrome + Gán IP đó vào] Khởi động Chrome...")
                    self._update_status(task, "Đang xử lý", f"[Bước 2/{tot_steps}] Mở Chrome & gán IP...")

                    try:
                        farmer = await self._ensure_farmer(raw_proxy_for_farmer)
                        logger.info(f"[Worker {self.worker_id}] [Bước 2/{tot_steps}: Mở Chrome + Gán IP đó vào] [DONE] Đã nạp Profile: {farmer.profile_name}")
                    except Exception as ex:
                        last_failure = f"Lỗi khởi động Chrome: {ex}"
                        logger.warning(f"[Worker {self.worker_id}] {last_failure}")
                        await asyncio.sleep(2)
                        continue

                    logger.info("       ↓")

                    # ============================================================
                    # [BƯỚC 3/6 (NẾU NUÔI KHÉP KÍN): NUÔI PROFILE TRÊN CHÍNH IP NÀY]
                    # ============================================================
                    if self.warm_and_voice and not farmer.is_session_warmed:
                        logger.info(f"[Worker {self.worker_id}] [Bước 3/{tot_steps}: Nuôi Profile trên IP] Bắt đầu lướt web tăng Trust hCaptcha trên cùng IP...")
                        self._update_status(task, "Đang xử lý", f"[Bước 3/{tot_steps}] Nuôi Profile trên IP này...")

                        warm_ok = await farmer.warm_session(
                            on_progress=lambda m: self._update_status(task, "Đang xử lý", f"[Nuôi IP] {m}"),
                            cancel_event=cancel_event
                        )
                        if cancel_event.is_set():
                            return False

                        if warm_ok:
                            logger.info(f"[Worker {self.worker_id}] [Bước 3/{tot_steps}: Nuôi Profile trên IP] [DONE] Nuôi thành công, chuyển tiếp ngay sang ElevenLabs trên cùng IP.")
                        else:
                            logger.warning(f"[Worker {self.worker_id}] [Bước 3/{tot_steps}: Nuôi Profile trên IP] Gặp gián đoạn khi nuôi, vẫn tiếp tục chuyển sang ElevenLabs...")

                        logger.info("       ↓")

                    # ============================================================
                    # [BƯỚC GIẢI HCAPTCHA]
                    # ============================================================
                    cap_step = 4 if self.warm_and_voice else 3
                    logger.info(f"[Worker {self.worker_id}] [Bước {cap_step}/{tot_steps}: Mở web mục tiêu → Giải hCaptcha] Điều hướng elevenlabs.io và giải captcha...")
                    self._update_status(task, "Đang xử lý", f"[Bước {cap_step}/{tot_steps}] Giải hCaptcha ElevenLabs...")

                    start_captcha_time = time.time()
                    try:
                        hcaptcha_token = await farmer.get_token(timeout_seconds=35)
                        captcha_elapsed = time.time() - start_captcha_time
                        logger.info(f"[Worker {self.worker_id}] [Bước {cap_step}/{tot_steps}] [DONE] Nhận hCaptcha Token thành công ({captcha_elapsed:.1f}s)")
                        self.state.consecutive_token_failures = 0
                    except Exception as ex:
                        last_failure = f"Không lấy được token Captcha: {ex}"
                        logger.warning(f"[Worker {self.worker_id}] {last_failure}")
                        self.state.consecutive_token_failures += 1
                        if self.state.consecutive_token_failures >= 2:
                            prof_name = farmer.profile_name
                            logger.warning(
                                f"[Worker {self.worker_id}] [CẢNH BÁO] Profile '{prof_name}' bị lỗi Captcha {self.state.consecutive_token_failures} lần liên tiếp. "
                                f"Tiến hành xóa profile này..."
                            )
                            self._update_status(task, "Đang xử lý", f"Xóa profile lỗi {prof_name}, đổi profile...")
                            await farmer.discard_profile()
                            self.farmer = None
                            self.state.consecutive_token_failures = 0
                            try:
                                farmer = await self._ensure_farmer(raw_proxy_for_farmer, force_restart=True)
                            except Exception:
                                pass
                        await asyncio.sleep(2)
                        continue

                    logger.info("       ↓")

                # Lưu thông tin profile vừa dùng để xử lý xóa nếu bị chặn
                used_profile_path = farmer.profile_path if farmer else None
                used_profile_name = farmer.profile_name if farmer else "N/A"

                # ============================================================
                # [BƯỚC GỬI REQUEST TTS & NHẬN MP3]
                # ============================================================
                tts_step = 5 if self.warm_and_voice else 4
                logger.info(f"[Worker {self.worker_id}] [Bước {tts_step}/{tot_steps}: Gửi request TTS & Nhận MP3] Đang gọi API tạo âm thanh ElevenLabs...")
                self._update_status(task, "Đang xử lý", f"[Bước {tts_step}/{tot_steps}] Đang tải file MP3...")

                result: TtsResult = await generate_tts(
                    voice_id=task.voice_profile.voice_id,
                    text=task.text,
                    output_path=task.chunk_mp3_path,
                    hcaptcha_token=hcaptcha_token,
                    proxy_url=proxy_url_for_curl,
                    voice_profile=task.voice_profile,
                    api_key=self.settings.eleven_labs_api_key,
                )

                # ============================================================
                # [BƯỚC ĐÓNG CHROME HOÀN TOÀN]
                # ============================================================
                close_step = 6 if self.warm_and_voice else 5
                if need_captcha and self.farmer:
                    logger.info(f"[Worker {self.worker_id}] [Bước {close_step}/{tot_steps}: Đóng Chrome hoàn toàn] Đang giải phóng phiên...")
                    try:
                        if self.warm_and_voice and result.success:
                            saved_dung = await self.farmer.finish_and_save()
                            if saved_dung:
                                logger.info(f"[Worker {self.worker_id}] [DONE] Profile khép kín đã lưu vào profiles_dung: {saved_dung.name}")
                            self.farmer = None
                        else:
                            await self.farmer.close()
                            self.farmer = None
                    except Exception:
                        pass
                    logger.info(f"[Worker {self.worker_id}] [Bước {close_step}/{tot_steps}] [DONE] Đã đóng Chrome.")
                    logger.info("       ↓")

                # Kiểm tra kết quả tải MP3
                out_path = Path(task.chunk_mp3_path)
                if result.success and out_path.exists() and out_path.stat().st_size > 0:
                    size_kb = out_path.stat().st_size / 1024
                    logger.success(f"[Worker {self.worker_id}] [Bước {tts_step}/{tot_steps}: Gửi request TTS & Nhận MP3] [DONE] Đã nhận file MP3: {out_path.name} ({size_kb:.1f} KB)")
                    self._update_status(task, "Hoàn thành", f"Đoạn {chunk_num} hoàn tất.")
                    logger.info(f"[Worker {self.worker_id}] (Lặp lại Bước 1 cho đoạn / Profile tiếp theo)")
                    if self.on_chunk_completed:
                        res = self.on_chunk_completed(task)
                        if asyncio.iscoroutine(res):
                            await res
                    return True

                # Xử lý khi TTS thất bại
                self._update_status(task, "Lỗi", result.message)
                last_failure = result.message
                logger.warning(f"[Worker {self.worker_id}] Thất bại tại chunk {chunk_num}: {result.message}")

                # Kiểm tra nếu bị chặn do phát hiện bất thường (WAF/Anti-bot) hoặc lỗi Captcha
                is_bot_or_captcha_blocked = (
                    "detected_unusual_activity" in result.message
                    or "hoạt động bất thường" in result.message
                    or "hcaptcha" in result.message.lower()
                )
                if is_bot_or_captcha_blocked and used_profile_path:
                    logger.warning(
                        f"[Worker {self.worker_id}] [CẢNH BÁO] Profile '{used_profile_name}' bị chặn bởi ElevenLabs ({result.message}). "
                        f"Tiến hành XÓA BỎ profile này khỏi thư mục profiles_dung..."
                    )
                    self._update_status(task, "Đang xử lý", f"Xóa profile bị chặn {used_profile_name}...")
                    from captcha.profile_manager import profile_manager
                    profile_manager.delete_profile(used_profile_path)

                if not result.retryable:
                    if result.is_worker_stopping_error and self.settings.continue_worker_on_blocking_errors:
                        if proxy_key and result.rotate_proxy:
                            cooldown_seconds = 60 if proxy_key.is_direct_proxy else 0
                            if not proxy_key.is_direct_proxy:
                                proxy_key.current_ip = ""

                        blocking_attempts += 1
                        if blocking_attempts < max_blocking_attempts:
                            logger.info(f"[Worker {self.worker_id}] Gặp lỗi chặn ({blocking_attempts}/{max_blocking_attempts}); thử lại...")
                            attempts = 0
                            await asyncio.sleep(2)
                            continue

                        logger.warning(f"[Worker {self.worker_id}] Đã hết {max_blocking_attempts} lần lỗi chặn; chuyển sang vòng sau.")
                        return True

                    logger.error(f"[Worker {self.worker_id}] Dừng worker do lỗi chặn: {result.message}")
                    return False

                # Lỗi Retryable thông thường
                if proxy_key:
                    cooldown_seconds = 60 if proxy_key.is_direct_proxy else 0
                    if not proxy_key.is_direct_proxy:
                        proxy_key.current_ip = ""
                else:
                    await asyncio.sleep(3)

            finally:
                if proxy_key and self.proxy_pool:
                    await self.proxy_pool.release_key(proxy_key, cooldown_seconds)

        return False

    async def close(self) -> None:
        """Giải phóng tài nguyên của Worker."""
        if self.farmer:
            await self.farmer.close()
            self.farmer = None
