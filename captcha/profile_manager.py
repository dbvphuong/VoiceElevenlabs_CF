"""Quản lý các thư mục Profile (profiles_nuoi và profiles_dung)."""

import os
import shutil
import time
import random
from pathlib import Path
from typing import List, Optional, Set
from loguru import logger
import psutil

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROFILE_BASE_DIR = PROJECT_ROOT / "Profile"
PROFILES_NUOI_DIR = PROFILE_BASE_DIR / "profiles_nuoi"
PROFILES_DUNG_DIR = PROFILE_BASE_DIR / "profiles_dung"

def kill_chrome_processes_for_profile(profile_path: Path) -> int:
    """Đóng cưỡng bức bất kỳ tiến trình Chrome nào đang chiếm giữ thư mục profile này."""
    if not profile_path:
        return 0
    try:
        resolved_path_str = str(Path(profile_path).resolve()).lower()
        killed = 0
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                p_name = (proc.info.get('name') or '').lower()
                if 'chrome' in p_name:
                    cmd = ' '.join(proc.info.get('cmdline') or []).lower()
                    if resolved_path_str in cmd:
                        proc.kill()
                        killed += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return killed
    except Exception as ex:
        logger.debug(f"Không thể kiểm tra psutil: {ex}")
        return 0

def cleanup_profile_locks(profile_path: Path) -> None:
    """Xóa các tệp khóa tạm thời của Chromium (SingletonLock, lockfile, v.v.) và tắt tiến trình kẹt."""
    if not profile_path:
        return
    kill_chrome_processes_for_profile(profile_path)
    p = Path(profile_path)
    if not p.exists():
        return
    lock_files = [
        p / "SingletonLock",
        p / "SingletonCookie",
        p / "SingletonSocket",
        p / "lockfile",
        p / "Default" / "lockfile",
    ]
    for lf in lock_files:
        try:
            if lf.exists():
                lf.unlink(missing_ok=True)
        except Exception:
            pass

class ProfileManager:
    """Quản lý vòng đời lưu trữ của các Profile Chrome."""

    def __init__(self):
        self._current_index = 0
        self._in_use_profiles: Set[str] = set()
        self.ensure_dirs()
        self.clean_nuoi_directory()

    def ensure_dirs(self) -> None:
        """Đảm bảo các thư mục gốc luôn tồn tại."""
        PROFILES_NUOI_DIR.mkdir(parents=True, exist_ok=True)
        PROFILES_DUNG_DIR.mkdir(parents=True, exist_ok=True)

    def get_available_profiles(self) -> List[Path]:
        """Lấy danh sách các profile đã nuôi xong sẵn sàng sử dụng trong profiles_dung."""
        self.ensure_dirs()
        profiles = []
        for p in PROFILES_DUNG_DIR.iterdir():
            if p.is_dir() and (p / "Default").exists():
                profiles.append(p)
            elif p.is_dir():
                profiles.append(p)
        # Sắp xếp theo thời gian sửa đổi gần nhất
        profiles.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        return profiles

    def count_available_profiles(self) -> int:
        """Đếm số lượng profile có sẵn."""
        return len(self.get_available_profiles())

    def acquire_profile(self, exclude: Optional[Set[str]] = None) -> Optional[Path]:
        """Lấy 1 profile độc quyền (không bị trùng với worker khác đang dùng)."""
        profiles = self.get_available_profiles()
        valid = []
        for p in profiles:
            p_name = p.name
            if p_name in self._in_use_profiles:
                continue
            if exclude and (str(p) in exclude or p_name in exclude):
                continue
            valid.append(p)

        if not valid:
            # Nếu tất cả đều đang in_use hoặc exclude, fallback xoay vòng nhưng giải phóng lock
            if not profiles:
                return None
            idx = self._current_index % len(profiles)
            self._current_index += 1
            chosen = profiles[idx]
        else:
            chosen = valid[0]

        self._in_use_profiles.add(chosen.name)
        cleanup_profile_locks(chosen)
        return chosen

    def release_profile(self, profile_path: Optional[Path]) -> None:
        """Giải phóng profile sau khi sử dụng xong để worker khác có thể dùng."""
        if not profile_path:
            return
        p_name = profile_path.name
        self._in_use_profiles.discard(p_name)
        cleanup_profile_locks(profile_path)

    def get_next_warmed_profile(self, exclude: Optional[Set[str]] = None) -> Optional[Path]:
        """Lấy 1 profile đã nuôi sẵn để dùng (độc quyền theo luồng)."""
        return self.acquire_profile(exclude=exclude)

    def create_new_nuoi_session(self, prefix: str = "profile") -> Path:
        """Tạo một thư mục session mới trong profiles_nuoi."""
        self.ensure_dirs()
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        rand_id = random.randint(1000, 9999)
        unique_name = f"{prefix}_{timestamp}_{os.getpid()}_{rand_id}"
        session_path = PROFILES_NUOI_DIR / unique_name
        session_path.mkdir(parents=True, exist_ok=True)
        return session_path

    def transfer_to_dung(self, nuoi_path: Path) -> Path:
        """Di chuyển (MOVE) profile đã nuôi thành công từ profiles_nuoi sang profiles_dung.
        Đảm bảo dọn sạch tiến trình Chrome và khóa tệp trước khi di chuyển.
        """
        self.ensure_dirs()
        cleanup_profile_locks(nuoi_path)

        target_name = nuoi_path.name
        target_path = PROFILES_DUNG_DIR / target_name

        if target_path.exists():
            cleanup_profile_locks(target_path)
            shutil.rmtree(target_path, ignore_errors=True)

        try:
            shutil.move(str(nuoi_path), str(target_path))
        except Exception as ex:
            logger.debug(f"shutil.move gặp lỗi {ex}, sử dụng copytree + xóa thư mục nguồn...")
            shutil.copytree(nuoi_path, target_path, dirs_exist_ok=True)
            shutil.rmtree(nuoi_path, ignore_errors=True)

        # Đảm bảo thư mục nguồn đã bị xóa hoàn toàn khỏi profiles_nuoi
        if nuoi_path.exists():
            try:
                shutil.rmtree(nuoi_path, ignore_errors=True)
            except Exception:
                pass

        cleanup_profile_locks(target_path)
        return target_path

    def delete_profile(self, profile_path: Path) -> bool:
        """Xóa bỏ vĩnh viễn một profile bị lỗi/chặn/trust thấp khỏi hệ thống (cả thư mục)."""
        if not profile_path:
            return False
        try:
            p = Path(profile_path)
            self._in_use_profiles.discard(p.name)
            cleanup_profile_locks(p)
            if p.exists() and p.is_dir():
                prof_name = p.name
                shutil.rmtree(p, ignore_errors=True)
                if p.exists():
                    time.sleep(0.5)
                    shutil.rmtree(p, ignore_errors=True)
                logger.warning(f"Đã xóa hoàn toàn profile không đạt yêu cầu: {prof_name}")
                return True
        except Exception as ex:
            logger.warning(f"Lỗi khi xóa profile {profile_path}: {ex}")
        return False

    def clean_nuoi_directory(self) -> int:
        """Dọn dẹp các thư mục tồn đọng trong profiles_nuoi:
        - Xóa các bản sao đã tồn tại trong profiles_dung.
        - Xóa các thư mục hỏng / rỗng / dở dang (< 5MB hoặc thiếu thư mục Default).
        - Di chuyển các profile hoàn chỉnh hợp lệ sang profiles_dung.
        """
        self.ensure_dirs()
        cleaned_count = 0
        dung_names = {p.name for p in PROFILES_DUNG_DIR.iterdir() if p.is_dir()}

        for p in list(PROFILES_NUOI_DIR.iterdir()):
            if not p.is_dir():
                continue

            cleanup_profile_locks(p)

            # 1. Trùng lặp với profiles_dung -> Xóa bên nuôi
            if p.name in dung_names:
                shutil.rmtree(p, ignore_errors=True)
                cleaned_count += 1
                continue

            # 2. Kiểm tra tính hợp lệ
            has_default = (p / "Default").exists()
            try:
                size_mb = sum(f.stat().st_size for f in p.rglob('*') if f.is_file()) / (1024 * 1024)
            except Exception:
                size_mb = 0

            # Nếu thư mục rỗng hoặc dở dang (< 5MB hoặc không có Default) -> Xóa rác
            if not has_default or size_mb < 5.0:
                shutil.rmtree(p, ignore_errors=True)
                cleaned_count += 1
            else:
                # Profile đầy đủ đã nuôi xong nhưng chưa kịp move -> Chuyển sang profiles_dung
                logger.info(f"Tìm thấy profile nuôi hoàn tất còn sót {p.name} ({size_mb:.1f}MB) -> Di chuyển sang profiles_dung.")
                self.transfer_to_dung(p)
                cleaned_count += 1

        return cleaned_count

profile_manager = ProfileManager()
