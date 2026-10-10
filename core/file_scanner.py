"""Quét và thu thập các tệp văn bản .txt từ danh sách thư mục và tệp đơn lẻ."""

from pathlib import Path
from typing import List, Iterable, Optional, Callable
from loguru import logger

def collect_txt_files(
    folders: Iterable[str | Path],
    individual_files: Optional[Iterable[str | Path]] = None,
    include_subfolders: bool = False,
    excluded_files: Optional[Iterable[str | Path]] = None,
    on_error: Optional[Callable[[str, Exception], None]] = None
) -> List[Path]:
    """Quét toàn bộ tệp .txt từ danh sách thư mục và danh sách tệp được chọn,
    tự động chuẩn hóa đường dẫn, loại bỏ các tệp trong excluded_files và các tệp trùng lặp.
    """
    seen = set()
    excluded = set()
    if excluded_files:
        for ex in excluded_files:
            try:
                excluded.add(str(Path(ex).resolve()).lower())
            except Exception:
                pass

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
                    res_str = str(resolved).lower()
                    if res_str in excluded:
                        continue
                    if res_str not in seen:
                        seen.add(res_str)
                        results.append(resolved)
        except Exception as e:
            logger.warning(f"Lỗi khi duyệt thư mục {folder_path}: {e}")
            if on_error:
                on_error(str(folder_path), e)

    # 2. Bổ sung các tệp đơn lẻ (nếu người dùng chủ động nạp thêm)
    if individual_files:
        for file in individual_files:
            file_path = Path(file)
            if file_path.is_file() and file_path.suffix.lower() == ".txt":
                resolved = file_path.resolve()
                res_str = str(resolved).lower()
                if res_str not in seen:
                    seen.add(res_str)
                    results.append(resolved)

    return results
