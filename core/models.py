"""Định nghĩa các cấu trúc dữ liệu chính (Data Models) cho Pipeline."""

from dataclasses import dataclass, field
from typing import List, Optional
import json
from config.settings import VoiceTemplate

@dataclass
class ChunkTask:
    file_index: int
    file_path: str
    chunk_index: int
    text: str
    chunk_mp3_path: str
    voice_profile: VoiceTemplate = field(default_factory=VoiceTemplate)

@dataclass
class FileProgress:
    file_index: int
    total_chunks: int = 0
    completed_chunks: int = 0
    chunk_paths: List[str] = field(default_factory=list)
    output_path: str = ""

@dataclass
class TtsResult:
    success: bool
    retryable: bool
    message: str
    is_worker_stopping_error: bool = False
    rotate_proxy: bool = False

    @classmethod
    def from_error(cls, status_code: int, body: str) -> "TtsResult":
        """Phân loại mã lỗi trả về từ ElevenLabs tương đồng 100% với C# TtsResult.FromError."""
        code = ""
        status = ""
        try:
            data = json.loads(body)
            detail = data.get("detail", {})
            if isinstance(detail, dict):
                code = str(detail.get("code") or "")
                status = str(detail.get("status") or "")
        except Exception:
            pass

        # 1. Hết lượt demo trên IP hiện tại -> cần xoay Proxy ngay
        if code == "sign_in_required" or "sign_in_required" in body:
            return cls(
                success=False,
                retryable=True,
                message="Hết lượt demo trên IP này; sẽ xoay proxy và thử lại.",
                rotate_proxy=True
            )

        # 2. Yêu cầu gói trả phí (Voice Library hoặc tính năng nâng cao yêu cầu gói trả phí)
        if code == "paid_plan_required" or status_code == 402:
            return cls(
                success=False,
                retryable=False,
                message="Yêu cầu tài khoản trả phí ElevenLabs (Paid Plan Required). Giọng hoặc tính năng này không hỗ trợ gói Free.",
                is_worker_stopping_error=True
            )

        # 2b. Hết Quota của tài khoản
        if status == "quota_exceeded" or "quota_exceeded" in body:
            return cls(
                success=False,
                retryable=False,
                message="Hết quota tài khoản ElevenLabs.",
                is_worker_stopping_error=True
            )

        # 3. ElevenLabs phát hiện hoạt động bất thường (WAF/Anti-bot trên IP hiện tại)
        if status == "detected_unusual_activity" or "detected_unusual_activity" in body:
            return cls(
                success=False,
                retryable=True,
                message="ElevenLabs từ chối Free Tier do hoạt động bất thường (cần xoay proxy).",
                is_worker_stopping_error=False,
                rotate_proxy=True
            )

        # 4. Proxy yêu cầu xác thực
        if status_code == 407:
            return cls(
                success=False,
                retryable=False,
                message="Proxy yêu cầu xác thực: kiểm tra user/password hoặc whitelist IP.",
                is_worker_stopping_error=True
            )

        # 5. Các mã lỗi mạng tạm thời hoặc server quá tải
        is_retryable = status_code in (408, 429) or status_code >= 500
        return cls(
            success=False,
            retryable=is_retryable,
            message=f"HTTP {status_code}, code={code}, status={status}"
        )
