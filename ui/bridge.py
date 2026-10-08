"""Cầu nối bất đồng bộ giữa Giao diện PyQt6 và Pipeline Orchestrator & Profile Warmer."""

import time
import asyncio
from pathlib import Path
from typing import List, Optional
from PyQt6.QtCore import QThread, pyqtSignal
from loguru import logger

from config.settings import AppSettings
from pipeline.orchestrator import Orchestrator
from captcha.profile_warmer import profile_warmer

class PipelineBridgeThread(QThread):
    """Luồng phụ thực thi Orchestrator để không gây gián đoạn (freeze) giao diện chính."""

    # Tín hiệu gửi về UI
    chunk_status_signal = pyqtSignal(int, int, str, str)  # file_idx, chunk_idx, status, note
    file_progress_signal = pyqtSignal(int, int, int, str)  # file_idx, completed, total, status_text
    overall_progress_signal = pyqtSignal(int, int)         # completed_all, total_all
    finished_signal = pyqtSignal(bool)                     # success

    def __init__(
        self,
        settings: AppSettings,
        input_files: List[Path],
        parent=None,
        warm_and_voice: bool = False,
        show_browser: bool = False,
    ):
        super().__init__(parent)
        self.settings = settings
        self.input_files = input_files
        self.warm_and_voice = warm_and_voice
        self.show_browser = show_browser
        self.orchestrator: Orchestrator | None = None
        self._is_stopped = False

    def run(self):
        """Khởi chạy asyncio loop trên thread riêng."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop

        self.orchestrator = Orchestrator(
            settings=self.settings,
            on_chunk_status=lambda f, c, s, n: self.chunk_status_signal.emit(f, c, s, n),
            on_file_progress=lambda f, comp, tot, txt: self.file_progress_signal.emit(f, comp, tot, txt),
            on_overall_progress=lambda comp, tot: self.overall_progress_signal.emit(comp, tot),
            warm_and_voice=self.warm_and_voice,
            show_browser=self.show_browser,
        )

        try:
            success = loop.run_until_complete(self.orchestrator.run(self.input_files))
            self.finished_signal.emit(success)
        except asyncio.CancelledError:
            logger.info("Luồng Pipeline TTS đã được dừng lại ngay lập tức.")
            self.finished_signal.emit(False)
        except Exception as e:
            logger.exception(f"Lỗi không xác định trong luồng Pipeline: {e}")
            self.finished_signal.emit(False)
        finally:
            loop.close()

    def stop(self):
        """Dừng tiến trình Orchestrator ngay lập tức."""
        self._is_stopped = True
        if self.orchestrator:
            self.orchestrator.stop()
        if hasattr(self, '_loop') and self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._cancel_all_tasks)

    def _cancel_all_tasks(self):
        for task in asyncio.all_tasks(self._loop):
            task.cancel()

class ProfileWarmerThread(QThread):
    """Luồng phụ thực thi quy trình nuôi Profile Chrome."""

    status_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(bool, str)  # success, message_or_path

    def __init__(
        self,
        thread_count: int = 1,
        proxy_raw: Optional[str] = None,
        proxy_list: Optional[list] = None,
        show_window: bool = False,
        loop_continuous: bool = False,
        parent=None
    ):
        super().__init__(parent)
        self.thread_count = max(1, thread_count)
        self.proxy_raw = proxy_raw
        self.proxy_list = proxy_list or ([proxy_raw] if proxy_raw else [])
        self.show_window = show_window
        self.loop_continuous = loop_continuous
        self._is_stopped = False

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        try:
            # Xác định số lượng luồng nuôi song song
            if self.proxy_list and len(self.proxy_list) > 0:
                worker_count = min(self.thread_count, len(self.proxy_list))
            else:
                worker_count = self.thread_count

            logger.info(f"[ProfileWarmerThread] Bắt đầu nuôi với {worker_count} luồng song song.")
            self.status_signal.emit(f"Khởi chạy {worker_count} luồng nuôi profile song song...")

            async def run_worker(w_id: int):
                # Mỗi worker được ưu tiên proxy theo chỉ số w_id
                worker_proxy_list = []
                if self.proxy_list:
                    offset = w_id % len(self.proxy_list)
                    worker_proxy_list = self.proxy_list[offset:] + self.proxy_list[:offset]

                # Tọa độ cửa sổ khi hiển thị
                cols = 2
                row = w_id // cols
                col = w_id % cols
                w_pos = (50 + col * 550, 50 + row * 380)

                while not self._is_stopped:
                    try:
                        res_path = await profile_warmer.warm_profile(
                            proxy_raw=self.proxy_raw,
                            proxy_list=worker_proxy_list,
                            show_window=self.show_window,
                            window_pos=w_pos,
                            worker_id=w_id + 1,
                            on_progress=lambda msg: self.status_signal.emit(msg)
                        )
                        self.finished_signal.emit(True, str(res_path))
                    except asyncio.CancelledError:
                        break
                    except Exception as ex:
                        self.status_signal.emit(f"[Luồng {w_id + 1}] Gặp sự cố: {ex}")

                    if not self.loop_continuous or self._is_stopped:
                        break

                    self.status_signal.emit(f"[Luồng {w_id + 1}] Chuẩn bị lượt nuôi tiếp theo...")

                    for _ in range(5):
                        if self._is_stopped:
                            break
                        await asyncio.sleep(1)

            async def main_async():
                tasks = [run_worker(i) for i in range(worker_count)]
                await asyncio.gather(*tasks)

            try:
                loop.run_until_complete(main_async())
            except asyncio.CancelledError:
                logger.info("Luồng Nuôi Profile đã được dừng lại ngay lập tức.")
        finally:
            loop.close()

    def stop(self):
        """Dừng tiến trình nuôi profile ngay lập tức."""
        self._is_stopped = True
        if hasattr(self, '_loop') and self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._cancel_all_tasks)

    def _cancel_all_tasks(self):
        for task in asyncio.all_tasks(self._loop):
            task.cancel()
