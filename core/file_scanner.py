"""Quét và thu thập các tệp văn bản .txt từ danh sách thư mục và tệp đơn lẻ."""

from pathlib import Path
from typing import List, Iterable, Optional, Callable
from loguru import logger

def collect_txt_files(
    folders: Iterable[str | Path],
    individual_files: Optional[Iterable[str | Path]] = None,
    include_subfolders: bool = False,
    on_error: Optional[Callable[[str, Exception], None]] = None
) -> List[Path]:
    """Quét toàn bộ tệp .txt từ danh sách thư mục và danh sách tệp được chọn,
    tự động chuẩn hóa đường dẫn và loại bỏ các tệp trùng lặp.
    """
    seen = set()
    results: List[Path] = []

    # 1. Quét từ các thư mục
    for folder in folders:
        folder_path = Path(folder)
        if not folder_path.is_dir():
            continue

        try:
            pattern = "**/*.txt" if include_subfolders else "*.txt"
            for file_path in sorted(folder_path.glob(pattern), key=lambda p: str(p).lower()):
                if file_path.is_file():
                    resolved = file_path.resolve()
                    if str(resolved).lower() not in seen:
                        seen.add(str(resolved).lower())
                        results.append(resolved)
        except Exception as e:
            logger.warning(f"Lỗi khi duyệt thư mục {folder_path}: {e}")
            if on_error:
                on_error(str(folder_path), e)

    # 2. Bổ sung các tệp đơn lẻ
    if individual_files:
        for file in individual_files:
            file_path = Path(file)
            if file_path.is_file() and file_path.suffix.lower() == ".txt":
                resolved = file_path.resolve()
                if str(resolved).lower() not in seen:
                    seen.add(str(resolved).lower())
                    results.append(resolved)

    return results
