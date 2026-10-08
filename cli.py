"""Giao diện dòng lệnh (CLI Runner) cho công cụ tự động tạo giọng nói ElevenLabs."""

import sys
import argparse
import asyncio
import signal
from pathlib import Path
from typing import List

# Đảm bảo in tiếng Việt có dấu không bị lỗi Unicode trên Windows console
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from loguru import logger

from config.settings import AppSettings
from core.file_scanner import collect_txt_files
from pipeline.orchestrator import Orchestrator
from utils.logger import setup_application_logger

def parse_args():
    parser = argparse.ArgumentParser(
        description="Tool tự động tạo voice ElevenLabs bằng hCaptcha (Không dùng API tính phí)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    
    parser.add_argument("-f", "--folder", type=str, help="Đường dẫn thư mục chứa các tệp .txt")
    parser.add_argument("-i", "--file", type=str, help="Đường dẫn đến 1 tệp .txt cụ thể")
    parser.add_argument("-r", "--recursive", action="store_true", help="Quét đệ quy các thư mục con")
    parser.add_argument("-t", "--threads", type=int, help="Số luồng worker xử lý đồng thời")
    parser.add_argument("-v", "--voice-id", type=str, help="Voice ID (ví dụ: 21m00Tcm4TlvDq8ikWAM - Rachel)")
    parser.add_argument("--template", type=str, help="Tên mẫu giọng (Voice Template) muốn áp dụng")
    parser.add_argument("--speed", type=float, help="Tốc độ đọc (0.7 đến 1.2)")
    parser.add_argument("--silence", type=float, help="Khoảng lặng giữa các đoạn (giây)")
    parser.add_argument("--chunk-size", type=int, help="Độ dài tối đa của một đoạn cắt (ký tự)")
    parser.add_argument("--proxy", type=str, help="Proxy đơn lẻ (host:port:user:pass) hoặc API key xoay")
    parser.add_argument("--api-key", type=str, help="ElevenLabs API Key (Tùy chọn)")
    parser.add_argument("--verbose", action="store_true", help="Hiển thị log chi tiết (DEBUG mode)")
    
    return parser.parse_args()

async def main_async():
    args = parse_args()
    setup_application_logger(verbose=args.verbose)
    
    print("\n" + "=" * 60)
    print("   11labs CF Automation Tool - Python Engine v1.0   ")
    print("=" * 60 + "\n")

    # 1. Tải cấu hình từ settings.json
    settings = AppSettings.load()

    # 2. Ghi đè cấu hình từ tham số dòng lệnh CLI (nếu có)
    if args.template:
        matched = next((t for t in settings.voice_templates if t.name.lower() == args.template.lower()), None)
        if matched:
            settings.selected_voice_template_name = matched.name
            settings.voice_id = matched.voice_id
            settings.speed = matched.speed
            settings.model_index = matched.model_index
            settings.lang_index = matched.lang_index
            settings.style = matched.style
            settings.stability = matched.stability
            settings.similarity = matched.similarity
            settings.speaker_boost = matched.speaker_boost
            logger.info(f"Đã áp dụng mẫu giọng '{matched.name}' (Voice ID: {matched.voice_id})")
        else:
            logger.warning(f"Không tìm thấy mẫu giọng '{args.template}' trong settings.json.")

    if args.threads:
        settings.thread_count = args.threads
    if args.voice_id:
        settings.voice_id = args.voice_id
    if args.speed:
        settings.speed = args.speed
    if args.silence is not None:
        settings.silence_enabled = (args.silence > 0)
        settings.silence_value = args.silence
    if args.chunk_size:
        settings.chunk_size = args.chunk_size
    if args.api_key:
        settings.eleven_labs_api_key = args.api_key
    if args.proxy:
        settings.rotating_proxies = args.proxy

    # 3. Thu thập danh sách tệp .txt
    target_files: List[Path] = []
    if args.file:
        f_path = Path(args.file).resolve()
        if f_path.is_file():
            target_files.append(f_path)
        else:
            logger.error(f"Tệp không tồn tại: {f_path}")
            return
    elif args.folder:
        target_files = collect_txt_files(
            folders=[args.folder],
            include_subfolders=args.recursive
        )
    elif settings.folders or settings.folder:
        folders_to_scan = settings.folders if settings.folders else [settings.folder]
        target_files = collect_txt_files(
            folders=folders_to_scan,
            include_subfolders=settings.scan_subfolders
        )
    else:
        logger.error("Vui lòng chỉ định tệp đầu vào bằng -i <file.txt> hoặc thư mục bằng -f <folder>.")
        return

    if not target_files:
        logger.warning("Không tìm thấy tệp .txt nào hợp lệ để xử lý.")
        return

    logger.info(f"Đã tìm thấy {len(target_files)} tệp .txt để đưa vào hàng đợi.")

    # 4. Khởi tạo Orchestrator
    def on_chunk(file_idx: int, chunk_idx: int, status: str, note: str):
        if status == "Hoàn thành":
            logger.success(f"[File #{file_idx + 1} | Chunk #{chunk_idx + 1}] {status} - {note}")
        elif status == "Lỗi":
            logger.error(f"[File #{file_idx + 1} | Chunk #{chunk_idx + 1}] {status} - {note}")

    def on_file(file_idx: int, completed: int, total: int, status_text: str):
        logger.info(f"[Tiến độ File #{file_idx + 1}] {status_text}")

    def on_overall(completed_all: int, total_all: int):
        pct = (completed_all / total_all * 100) if total_all > 0 else 0
        logger.info(f"[Tổng thể] {completed_all}/{total_all} chunks ({pct:.1f}%)")

    orchestrator = Orchestrator(
        settings=settings,
        on_chunk_status=on_chunk,
        on_file_progress=on_file,
        on_overall_progress=on_overall
    )

    # 5. Xử lý ngắt tín hiệu Ctrl + C
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: orchestrator.stop())
        except NotImplementedError:
            # Windows không hỗ trợ add_signal_handler đầy đủ
            pass

    # 6. Khởi chạy Pipeline
    try:
        success = await orchestrator.run(target_files)
        if success:
            logger.success("=== TẤT CẢ CÁC TỆP ĐÃ ĐƯỢC XỬ LÝ VÀ GHÉP XONG THÀNH CÔNG! ===")
        else:
            logger.warning("Tiến trình kết thúc nhưng vẫn còn đoạn chưa hoàn tất.")
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.warning("Tiến trình đã bị người dùng hủy bỏ (Ctrl + C).")
        orchestrator.stop()

def main():
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        print("\nĐã dừng chương trình.")

if __name__ == "__main__":
    main()
