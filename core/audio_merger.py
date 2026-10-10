import sys
import os
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import List, Optional
from loguru import logger

def get_ffmpeg_path() -> str:
    """Tìm kiếm đường dẫn thực thi ffmpeg trên máy."""
    # 0. Nếu chạy từ gói PyInstaller onefile (_MEIPASS)
    if hasattr(sys, "_MEIPASS"):
        meipass_ffmpeg = Path(sys._MEIPASS) / "ffmpeg.exe"
        if meipass_ffmpeg.exists():
            return str(meipass_ffmpeg.resolve())

    # 1. Tìm cạnh file exe thực thi (khi chạy dưới dạng portable exe)
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).parent
        exe_ffmpeg = exe_dir / "ffmpeg.exe"
        if exe_ffmpeg.exists():
            return str(exe_ffmpeg.resolve())

    # 2. Tìm trong thư mục làm việc hiện tại
    bundled = Path("ffmpeg.exe")
    if bundled.exists():
        return str(bundled.resolve())
    
    # 3. Tìm theo PATH của hệ điều hành
    which_path = shutil.which("ffmpeg")
    if which_path:
        return which_path

    # 4. Fallback đường dẫn cài đặt thường thấy trên máy của user
    known_path = Path(r"E:\SETUP\ffmpeg-2026-03-18-git-106616f13d-full_build\bin\ffmpeg.exe")
    if known_path.exists():
        return str(known_path)

    return "ffmpeg"

def run_ffmpeg(*args: str) -> None:
    """Thực thi lệnh ffmpeg bằng subprocess."""
    ffmpeg_bin = get_ffmpeg_path()
    cmd = [
        ffmpeg_bin,
        "-nostdin",
        "-hide_banner",
        "-v", "error",
        "-xerror",
        "-y",
        *args
    ]
    logger.debug(f"Chạy lệnh FFmpeg: {' '.join(cmd)}")
    extra_kwargs = {}
    if os.name == "nt":
        # Ẩn hoàn toàn cửa sổ dòng lệnh (CMD đen) khi gọi FFmpeg trên Windows
        extra_kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 1)
        startupinfo.wShowWindow = getattr(subprocess, "SW_HIDE", 0)
        extra_kwargs["startupinfo"] = startupinfo

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        **extra_kwargs
    )
    if result.returncode != 0:
        error_msg = result.stderr.strip() or "Lỗi không xác định từ FFmpeg"
        raise RuntimeError(f"FFmpeg thất bại (mã {result.returncode}): {error_msg}")

def merge_mp3_files(input_files: List[str | Path], output_file: str | Path, silence_seconds: float = 0.0) -> bool:
    """Ghép nối danh sách các tệp MP3 thành một tệp hoàn chỉnh, hỗ trợ chèn khoảng lặng."""
    if not input_files:
        raise ValueError("Danh sách tệp âm thanh đầu vào rỗng.")

    resolved_inputs = [Path(f).resolve() for f in input_files]
    for f in resolved_inputs:
        if not f.exists() or f.stat().st_size == 0:
            raise FileNotFoundError(f"Tệp âm thanh đầu vào không tồn tại hoặc rỗng: {f}")

    output_path = Path(output_file).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Tạo thư mục làm việc tạm thời
    work_dir = output_path.parent / f".merge_{uuid.uuid4().hex}"
    work_dir.mkdir(parents=True, exist_ok=True)

    silence_mp3 = work_dir / "silence.mp3"
    manifest_txt = work_dir / "inputs.txt"
    merged_mp3 = work_dir / "merged.mp3"

    try:
        # 1. Tạo tệp khoảng lặng nếu được cấu hình
        if silence_seconds > 0 and len(resolved_inputs) > 1:
            run_ffmpeg(
                "-f", "lavfi",
                "-i", "anullsrc=r=44100:cl=mono",
                "-t", f"{silence_seconds:.3f}",
                "-c:a", "libmp3lame",
                "-q:a", "2",
                str(silence_mp3)
            )

        # 2. Tạo manifest cho concat demuxer
        manifest_lines: List[str] = []
        for i, in_file in enumerate(resolved_inputs):
            # Escape dấu nháy đơn theo chuẩn ffmpeg concat
            escaped_path = str(in_file).replace("\\", "/").replace("'", "'\\''")
            manifest_lines.append(f"file '{escaped_path}'")
            if i < len(resolved_inputs) - 1 and silence_seconds > 0:
                silence_escaped = str(silence_mp3).replace("\\", "/").replace("'", "'\\''")
                manifest_lines.append(f"file '{silence_escaped}'")

        manifest_txt.write_text("\n".join(manifest_lines), encoding="utf-8")

        # 3. Chạy FFmpeg concat demuxer và re-encode libmp3lame
        run_ffmpeg(
            "-f", "concat",
            "-safe", "0",
            "-i", str(manifest_txt),
            "-vn",
            "-c:a", "libmp3lame",
            "-q:a", "2",
            str(merged_mp3)
        )

        if not merged_mp3.exists() or merged_mp3.stat().st_size == 0:
            raise RuntimeError("Ghép âm thanh trả về tệp rỗng.")

        # 4. Di chuyển kết quả về output_file
        shutil.move(str(merged_mp3), str(output_path))
        logger.info(f"Đã ghép thành công {len(resolved_inputs)} đoạn -> {output_path} ({output_path.stat().st_size:,} bytes)")
        return True

    finally:
        # Dọn dẹp thư mục tạm
        if work_dir.exists():
            shutil.rmtree(work_dir, ignore_errors=True)
