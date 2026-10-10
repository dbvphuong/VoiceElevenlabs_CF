"""Bộ điều phối toàn bộ quy trình từ tệp văn bản sang tệp âm thanh hoàn chỉnh."""

import os
import shutil
import asyncio
from pathlib import Path
from typing import List, Dict, Optional, Callable
from loguru import logger

from config.constants import MAX_RETRY_ROUNDS
from config.settings import AppSettings, VoiceTemplate
from core.models import ChunkTask, FileProgress
from core.text_splitter import split_text_by_sentences
from core.audio_merger import merge_mp3_files
from core.file_scanner import collect_txt_files
from network.proxy_pool import ProxyPool
from pipeline.worker import PipelineWorker

class Orchestrator:
    """Quản lý hàng đợi công việc, phân bổ Worker, xử lý đa tầng Retry và ghép MP3."""

    def __init__(
        self,
        settings: AppSettings,
        on_chunk_status: Optional[Callable[[int, int, str, str], None]] = None,
        on_file_progress: Optional[Callable[[int, int, int, str], None]] = None,
        on_overall_progress: Optional[Callable[[int, int], None]] = None,
        warm_and_voice: bool = False,
        show_browser: bool = False,
    ):
        self.settings = settings
        self.on_chunk_status = on_chunk_status
        self.on_file_progress = on_file_progress
        self.on_overall_progress = on_overall_progress
        self.warm_and_voice = warm_and_voice
        self.show_browser = show_browser

        self.proxy_pool: Optional[ProxyPool] = None
        self._init_proxy_pool()

        self.file_progresses: Dict[int, FileProgress] = {}
        self.pending_files: List[Path] = []
        self.cancel_event = asyncio.Event()

        self.total_chunks_all: int = 0
        self.total_completed_chunks: int = 0
        self.reused_chunks: int = 0
        self._merge_lock = asyncio.Lock()
        self._pending_merge_tasks: List[asyncio.Task] = []

    def _init_proxy_pool(self) -> None:
        """Khởi tạo ProxyPool từ cấu hình RotatingProxies hoặc StaticProxies."""
        entries: List[str] = []
        if self.settings.rotating_proxies and self.settings.rotating_proxies.strip():
            entries.extend([line.strip() for line in self.settings.rotating_proxies.splitlines() if line.strip()])
        elif self.settings.static_proxies and self.settings.static_proxies.strip():
            entries.extend([line.strip() for line in self.settings.static_proxies.splitlines() if line.strip()])

        if entries:
            self.proxy_pool = ProxyPool(entries)
        else:
            self.proxy_pool = None

    def get_output_path(self, input_file: Path) -> Path:
        """Xác định đường dẫn tệp MP3 hoàn chỉnh đầu ra."""
        suffix = self.settings.output_file_suffix or ""
        if suffix.lower().endswith(".mp3"):
            suffix = suffix[:-4]
        out_name = f"{input_file.stem}{suffix}.mp3"
        return input_file.parent / out_name

    def get_voice_profile_for_file(self, file_path: Path) -> VoiceTemplate:
        """Xác định VoiceTemplate cho file:
        1. Ưu tiên cao nhất: FileVoiceProfiles (mẫu giọng gán riêng cho file tại thời điểm thêm).
        2. Ưu tiên kế: FolderVoiceProfiles (mẫu giọng gán riêng cho thư mục).
        3. Ưu tiên kế: Selected Voice Template.
        4. Sử dụng cấu hình chung của settings.
        """
        file_resolved = str(file_path.resolve()).lower()

        # 1. Kiểm tra FileVoiceProfiles
        for fvp in self.settings.file_voice_profiles:
            if fvp.file_path:
                try:
                    if str(Path(fvp.file_path).resolve()).lower() == file_resolved:
                        if fvp.voice.name:
                            for vt in self.settings.voice_templates:
                                if vt.name.lower() == fvp.voice.name.lower():
                                    return vt
                        return fvp.voice
                except Exception:
                    if fvp.file_path.lower() == file_resolved:
                        if fvp.voice.name:
                            for vt in self.settings.voice_templates:
                                if vt.name.lower() == fvp.voice.name.lower():
                                    return vt
                        return fvp.voice

        # 2. Kiểm tra FolderVoiceProfiles
        file_dir = str(file_path.parent.resolve()).lower()
        for fvp in self.settings.folder_voice_profiles:
            if fvp.folder_path:
                try:
                    p_folder = str(Path(fvp.folder_path).resolve()).lower()
                    if file_dir == p_folder or file_dir.startswith(p_folder + "\\") or file_dir.startswith(p_folder + "/"):
                        if fvp.voice.name:
                            for vt in self.settings.voice_templates:
                                if vt.name.lower() == fvp.voice.name.lower():
                                    return vt
                        return fvp.voice
                except Exception:
                    pass

        # 3. Kiểm tra Selected Voice Template
        if self.settings.selected_voice_template_name:
            for vt in self.settings.voice_templates:
                if vt.name.lower() == self.settings.selected_voice_template_name.lower():
                    return vt.model_copy()

        # 4. Sử dụng cấu hình chung của settings
        return VoiceTemplate(
            name="Mặc định",
            voice_id=self.settings.voice_id,
            model_index=self.settings.model_index,
            lang_index=self.settings.lang_index,
            speed=self.settings.speed,
            style=self.settings.style,
            stability=self.settings.stability,
            similarity=self.settings.similarity,
            speaker_boost=self.settings.speaker_boost
        )

    def stop(self) -> None:
        """Gửi tín hiệu dừng toàn bộ tiến trình."""
        logger.warning("Đã gửi tín hiệu dừng tiến trình Orchestrator.")
        self.cancel_event.set()

    def _on_chunk_completed(self, task: ChunkTask) -> None:
        """Callback khi một đoạn MP3 được hoàn thành."""
        self.total_completed_chunks += 1
        if self.on_overall_progress:
            self.on_overall_progress(self.total_completed_chunks, self.total_chunks_all)

        fp = self.file_progresses.get(task.file_index)
        if not fp:
            return

        fp.completed_chunks += 1
        status_msg = f"Đang chạy: {fp.completed_chunks}/{fp.total_chunks}"
        if self.on_file_progress:
            self.on_file_progress(task.file_index, fp.completed_chunks, fp.total_chunks, status_msg)

        # Nếu đã hoàn thành đủ mọi chunk của file này -> Ghép MP3
        if fp.completed_chunks == fp.total_chunks:
            coro = self._merge_file(task.file_index)
            try:
                t = asyncio.create_task(coro)
                self._pending_merge_tasks.append(t)
            except RuntimeError:
                coro.close()

        # Nếu toàn bộ các đoạn trong danh sách đã hoàn thành -> Dừng ngay lập tức các worker đang nuôi / chờ
        if self.total_completed_chunks >= self.total_chunks_all and self.total_chunks_all > 0:
            logger.success(f"Toàn bộ {self.total_completed_chunks}/{self.total_chunks_all} đoạn đã hoàn tất! Phát tín hiệu dừng ngay các worker khác.")
            self.cancel_event.set()

    async def _merge_file(self, file_index: int) -> None:
        """Ghép nối các part của một file thành tệp MP3 cuối cùng."""
        async with self._merge_lock:
            fp = self.file_progresses.get(file_index)
            if not fp or not fp.chunk_paths:
                return

            if self.on_file_progress:
                self.on_file_progress(file_index, fp.completed_chunks, fp.total_chunks, "Đang ghép file MP3...")

            valid_parts = [p for p in fp.chunk_paths if Path(p).exists() and Path(p).stat().st_size > 0]
            if not valid_parts:
                logger.warning(f"Không tìm thấy part nào hợp lệ để ghép cho {fp.output_path}")
                return

            logger.info(f"Bắt đầu ghép {len(valid_parts)} đoạn -> {fp.output_path}")
            try:
                silence_val = self.settings.silence_value if self.settings.silence_enabled else 0.0
                success = merge_mp3_files(valid_parts, fp.output_path, silence_seconds=silence_val)
                if success:
                    # Dọn dẹp các tệp part_*.mp3 tạm
                    for p in valid_parts:
                        p_path = Path(p)
                        if p_path.exists():
                            p_path.unlink()

                    # Xóa thư mục tạm nếu rỗng
                    chunk_dir = Path(valid_parts[0]).parent if valid_parts else None
                    if chunk_dir and chunk_dir.exists() and not any(chunk_dir.iterdir()):
                        shutil.rmtree(chunk_dir, ignore_errors=True)

                    if self.on_file_progress:
                        self.on_file_progress(file_index, fp.total_chunks, fp.total_chunks, "Xong")
                    logger.success(f"Hoàn tất ghép file MP3: {fp.output_path}")

            except Exception as e:
                logger.error(f"Lỗi khi ghép file {fp.output_path}: {e}")
                if self.on_file_progress:
                    self.on_file_progress(file_index, fp.completed_chunks, fp.total_chunks, "Lỗi ghép file")

    async def run(self, input_paths: List[Path]) -> bool:
        """Chạy toàn bộ quy trình cho danh sách các tệp văn bản."""
        self.cancel_event.clear()
        self.pending_files = input_paths
        self.file_progresses.clear()
        self.total_chunks_all = 0
        self.total_completed_chunks = 0
        self.reused_chunks = 0

        initial_tasks: List[ChunkTask] = []

        # 1. Phân tích nội dung và cắt chunk từng file
        for f_idx, file_path in enumerate(self.pending_files):
            out_mp3 = self.get_output_path(file_path)

            # Nếu file output đã tồn tại và có dữ liệu -> Bỏ qua
            if out_mp3.exists() and out_mp3.stat().st_size > 0:
                if self.on_file_progress:
                    self.on_file_progress(f_idx, 0, 0, "Bỏ qua (đã có output)")
                continue

            content = file_path.read_text(encoding="utf-8-sig", errors="replace")
            chunks = split_text_by_sentences(content, max_length=self.settings.chunk_size)
            if not chunks:
                if self.on_file_progress:
                    self.on_file_progress(f_idx, 0, 0, "Xong (Tệp rỗng)")
                continue

            chunk_dir = file_path.parent / file_path.stem
            chunk_dir.mkdir(parents=True, exist_ok=True)

            fp = FileProgress(
                file_index=f_idx,
                total_chunks=len(chunks),
                completed_chunks=0,
                chunk_paths=[],
                output_path=str(out_mp3)
            )
            self.file_progresses[f_idx] = fp
            self.total_chunks_all += len(chunks)

            # Xác định VoiceProfile cho tệp (ưu tiên Folder profile, Template được chọn, hoặc thông số chung)
            voice_prof = self.get_voice_profile_for_file(file_path)

            for c_idx, c_text in enumerate(chunks):
                stt = c_idx + 1
                c_path = chunk_dir / f"{stt}.mp3"

                # Tương thích ngược: tự động đổi tên file part_ cũ nếu có
                if not c_path.exists():
                    old_candidates = [
                        chunk_dir / f"part_{c_idx}.mp3",
                        chunk_dir / f"part_{stt}.mp3",
                        chunk_dir / f"Part_{c_idx}.mp3",
                        chunk_dir / f"Part_{stt}.mp3",
                    ]
                    for old_p in old_candidates:
                        if old_p.exists() and old_p.stat().st_size > 0:
                            try:
                                old_p.rename(c_path)
                                break
                            except Exception:
                                pass

                fp.chunk_paths.append(str(c_path))

                # Kiểm tra cơ chế Resume: Đoạn MP3 đã có sẵn từ phiên trước
                if c_path.exists() and c_path.stat().st_size > 0:
                    fp.completed_chunks += 1
                    self.total_completed_chunks += 1
                    self.reused_chunks += 1
                    if self.on_chunk_status:
                        self.on_chunk_status(f_idx, c_idx, "Hoàn thành", "Đoạn MP3 đã có sẵn.")
                else:
                    if self.on_chunk_status:
                        self.on_chunk_status(f_idx, c_idx, "Đang chờ", "")
                    initial_tasks.append(ChunkTask(
                        file_index=f_idx,
                        file_path=str(file_path),
                        chunk_index=c_idx,
                        text=c_text,
                        chunk_mp3_path=str(c_path),
                        voice_profile=voice_prof
                    ))

            if fp.completed_chunks == fp.total_chunks:
                t = asyncio.create_task(self._merge_file(f_idx))
                self._pending_merge_tasks.append(t)
            else:
                if self.on_file_progress:
                    self.on_file_progress(f_idx, fp.completed_chunks, fp.total_chunks, f"Đang chạy: {fp.completed_chunks}/{fp.total_chunks}")

        if self.on_overall_progress:
            self.on_overall_progress(self.total_completed_chunks, self.total_chunks_all)

        logger.info(
            f"Tổng cộng: {self.total_chunks_all} đoạn "
            f"(có sẵn {self.reused_chunks}, cần xử lý mới {len(initial_tasks)})."
        )

        if not initial_tasks:
            # Đảm bảo các file đã có sẵn tất cả chunk được ghép hoàn tất
            if self._pending_merge_tasks:
                await asyncio.gather(*self._pending_merge_tasks, return_exceptions=True)
                self._pending_merge_tasks.clear()
            logger.info("Không có đoạn âm thanh nào cần tạo mới.")
            return True

        # 2. Xác định số lượng Worker
        requested_workers = max(1, self.settings.thread_count)
        if self.proxy_pool and self.proxy_pool.count > 0:
            worker_count = min(requested_workers, self.proxy_pool.count)
        else:
            worker_count = 1  # Nếu không có proxy xoay, chỉ chạy 1 luồng tránh xung đột IP

        logger.info(f"Khởi chạy {worker_count} worker đồng thời...")

        # 3. Vòng lặp Retry đa tầng (MaxRetryRounds = 5)
        current_tasks = initial_tasks

        for round_idx in range(MAX_RETRY_ROUNDS + 1):
            if self.cancel_event.is_set() or not current_tasks:
                break

            if round_idx > 0:
                logger.info(f"=== Vòng xử lý lại {round_idx}/{MAX_RETRY_ROUNDS}: {len(current_tasks)} đoạn chưa xong ===")

            task_queue: asyncio.Queue[ChunkTask] = asyncio.Queue()
            for t in current_tasks:
                await task_queue.put(t)

            failed_this_round: List[ChunkTask] = []
            max_attempts_per_chunk = 3 if round_idx == 0 else 2

            # Tạo danh sách Worker
            workers = [
                PipelineWorker(
                    worker_id=w_id,
                    settings=self.settings,
                    proxy_pool=self.proxy_pool,
                    on_chunk_status=self.on_chunk_status,
                    on_chunk_completed=self._on_chunk_completed,
                    warm_and_voice=self.warm_and_voice,
                    show_browser=self.show_browser,
                )
                for w_id in range(worker_count)
            ]

            async def worker_loop(w: PipelineWorker):
                while not self.cancel_event.is_set():
                    # Nếu toàn bộ các đoạn trong dự án đã hoàn thành, thoát ngay
                    if self.total_completed_chunks >= self.total_chunks_all and self.total_chunks_all > 0:
                        break

                    try:
                        task = task_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break

                    # Nếu file này đã hoàn thành hoặc đoạn này đã có sẵn MP3, bỏ qua
                    fp = self.file_progresses.get(task.file_index)
                    if fp and fp.completed_chunks >= fp.total_chunks:
                        continue

                    chunk_p = Path(task.chunk_mp3_path)
                    if chunk_p.exists() and chunk_p.stat().st_size > 0:
                        continue

                    try:
                        await w.process_chunk(
                            task,
                            max_attempts=max_attempts_per_chunk,
                            retry_round=round_idx,
                            cancel_event=self.cancel_event
                        )
                    except Exception as e:
                        logger.error(f"[Worker {w.worker_id}] Lỗi ngoại lệ khi xử lý chunk {task.chunk_index + 1}: {e}")

                    if self.cancel_event.is_set():
                        break

            # Chạy tất cả worker đồng thời
            worker_tasks = [asyncio.create_task(worker_loop(w)) for w in workers]
            await asyncio.gather(*worker_tasks, return_exceptions=True)

            # Đóng tài nguyên của các worker
            for w in workers:
                try:
                    await w.close()
                except Exception:
                    pass

            if self.cancel_event.is_set():
                break

            # Kiểm tra trạng thái thực tế trên đĩa: giữ lại tất cả các task CHƯA có file MP3 hợp lệ
            current_tasks = [
                t for t in initial_tasks
                if not (Path(t.chunk_mp3_path).exists() and Path(t.chunk_mp3_path).stat().st_size > 0)
            ]

            if not current_tasks:
                logger.success("Tất cả các đoạn âm thanh đã được tạo thành công!")
                break

            if round_idx < MAX_RETRY_ROUNDS:
                logger.info(f"Nghỉ 3 giây trước vòng xử lý lại tiếp theo...")
                await asyncio.sleep(3)

        # Đợi toàn bộ các tiến trình ghép MP3 hoàn tất
        if self._pending_merge_tasks:
            await asyncio.gather(*self._pending_merge_tasks, return_exceptions=True)
            self._pending_merge_tasks.clear()

        # Kiểm tra quét lần cuối: Ghép nối tất cả các file đã có đủ mọi part trên đĩa mà chưa được ghép
        for f_idx, fp in self.file_progresses.items():
            out_file = Path(fp.output_path)
            if not out_file.exists() or out_file.stat().st_size == 0:
                all_parts_exist = (
                    len(fp.chunk_paths) > 0
                    and all(Path(p).exists() and Path(p).stat().st_size > 0 for p in fp.chunk_paths)
                )
                if all_parts_exist:
                    logger.info(f"Phát hiện file {fp.output_path} đã có đủ {len(fp.chunk_paths)} part trên đĩa -> Tiến hành ghép MP3...")
                    t = asyncio.create_task(self._merge_file(f_idx))
                    self._pending_merge_tasks.append(t)

        if self._pending_merge_tasks:
            await asyncio.gather(*self._pending_merge_tasks, return_exceptions=True)
            self._pending_merge_tasks.clear()

        is_completed = (self.total_completed_chunks == self.total_chunks_all)
        logger.info(f"Kết thúc lượt chạy: Hoàn thành {self.total_completed_chunks}/{self.total_chunks_all} đoạn.")
        return is_completed
