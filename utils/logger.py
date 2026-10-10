"""Cấu hình quản lý nhật ký hệ thống (Loguru Logger) và bắt lỗi toàn cục."""

import sys
import traceback
from pathlib import Path
from loguru import logger

# Đường dẫn thư mục logs luôn trỏ đến thư mục logs của dự án hoặc cạnh file exe khi đóng gói
ROOT_DIR = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
LOGS_DIR = ROOT_DIR / "logs"

def clean_old_logs(days: int = 5):
    """Tự động dọn dẹp các tệp nhật ký cũ hơn `days` ngày khi khởi động ứng dụng."""
    try:
        if not LOGS_DIR.exists():
            return
        import time
        cutoff_time = time.time() - (days * 86400)
        for log_path in LOGS_DIR.glob("*.log"):
            if log_path.name == "crash.log":
                continue
            try:
                if log_path.stat().st_mtime < cutoff_time:
                    log_path.unlink()
                    logger.info(f"Đã dọn dẹp file log cũ (> {days} ngày): {log_path.name}")
            except Exception:
                pass
    except Exception as e:
        logger.debug(f"Không thể quét dọn log cũ: {e}")

def setup_application_logger(verbose: bool = False):
    """Khởi tạo cấu hình ghi log tự động ra thư mục logs/ và Console."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    clean_old_logs(days=5)

    # Xóa các handler mặc định của loguru để tránh ghi lặp
    logger.remove()

    # 1. Ghi ra Console (Terminal / CMD nếu có)
    if sys.stderr is not None:
        console_format = (
            "<green>{time:HH:mm:ss}</green> | "
            "<level>{level: <7}</level> | "
            "<cyan>{message}</cyan>"
        )
        logger.add(
            sys.stderr,
            format=console_format,
            level="DEBUG" if verbose else "INFO",
            colorize=True
        )

    # 2. Ghi ra tệp nhật ký hàng ngày (Tất cả mức độ từ DEBUG/INFO)
    app_log_path = LOGS_DIR / "app_{time:YYYY-MM-DD}.log"
    logger.add(
        str(app_log_path),
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <7} | {name}:{function}:{line} - {message}",
        level="DEBUG",
        rotation="10 MB",
        retention="5 days",
        encoding="utf-8",
        enqueue=True,  # Thread-safe
        backtrace=True,
        diagnose=True,
    )

    # 3. Ghi riêng các lỗi cảnh báo & sự cố nghiêm trọng
    error_log_path = LOGS_DIR / "error_{time:YYYY-MM-DD}.log"
    logger.add(
        str(error_log_path),
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <7} | {name}:{function}:{line} - {message}",
        level="WARNING",
        rotation="10 MB",
        retention="5 days",
        encoding="utf-8",
        enqueue=True,
        backtrace=True,
        diagnose=True,
    )

    # 4. Thiết lập bắt lỗi ngoại lệ chưa xử lý toàn cục (Global Exception Hook)
    def global_exception_handler(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return

        crash_msg = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        logger.critical(f"NGOẠI LỆ CHƯA XỬ LÝ (UNHANDLED CRASH):\n{crash_msg}")

        # Ghi riêng vào file crash.log khẩn cấp
        crash_log_file = LOGS_DIR / "crash.log"
        try:
            with open(crash_log_file, "a", encoding="utf-8") as f:
                f.write(f"\n{'='*60}\nCRASH REPORT: {exc_value}\n{'='*60}\n{crash_msg}\n")
        except Exception:
            pass

    sys.excepthook = global_exception_handler
    logger.debug(f"Hệ thống Logger đã kích hoạt. Thư mục lưu trữ: {LOGS_DIR.resolve()}")
