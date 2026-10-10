"""Client gọi API sinh âm thanh của ElevenLabs (hỗ trợ Anonymous TTS & Official API)."""

import os
import random
import base64
import json
import asyncio
from pathlib import Path
from typing import Optional, Dict, Any
from curl_cffi import requests
from loguru import logger

from config.constants import (
    MODEL_IDS,
    LANGUAGE_CODES,
    BROWSER_PROFILES,
    ELEVENLABS_ANONYMOUS_TTS_URL,
    ELEVENLABS_OFFICIAL_TTS_URL,
    FERNDOCS_PROXY_BASE,
)
from config.settings import VoiceTemplate
from core.models import TtsResult

def is_v4_model(model_index: int) -> bool:
    if 0 <= model_index < len(MODEL_IDS):
        return MODEL_IDS[model_index] in ("eleven_v4", "eleven_v4_turbo")
    return False

def build_voice_settings_payload(voice_profile: VoiceTemplate) -> dict:
    """Tạo payload voice_settings tương tự C# ElevenLabsAPITest.BuildVoiceSettings."""
    settings = {
        "stability": max(0.0, min(100.0, float(voice_profile.stability))) / 100.0,
        "similarity_boost": max(0.0, min(100.0, float(voice_profile.similarity))) / 100.0,
    }
    if not is_v4_model(voice_profile.model_index):
        settings["speed"] = max(0.7, min(1.2, float(voice_profile.speed)))
        settings["style"] = max(0.0, min(100.0, float(voice_profile.style))) / 100.0
        settings["use_speaker_boost"] = bool(voice_profile.speaker_boost)
    return settings

async def generate_tts(
    voice_id: str,
    text: str,
    output_path: str | Path,
    hcaptcha_token: str = "",
    proxy_url: Optional[str] = None,
    voice_profile: Optional[VoiceTemplate] = None,
    api_key: Optional[str] = None,
    use_ferndocs: bool = False,
    timeout: float = 35.0,
) -> TtsResult:
    """Gửi yêu cầu sinh âm thanh tới ElevenLabs và lưu thành tệp MP3."""
    out_file = Path(output_path).resolve()
    out_file.parent.mkdir(parents=True, exist_ok=True)
    temp_partial = out_file.with_suffix(".mp3.partial")

    profile = voice_profile or VoiceTemplate(voice_id=voice_id)
    model_idx = max(0, min(len(MODEL_IDS) - 1, profile.model_index))
    model_id = MODEL_IDS[model_idx]
    lang_idx = profile.lang_index

    # 1. Micro-jitter né Burst Detection của WAF
    jitter = random.uniform(0.2, 1.2)
    await asyncio.sleep(jitter)

    # 2. Xây dựng Payload
    payload: Dict[str, Any] = {
        "text": text,
        "model_id": model_id,
        "voice_settings": build_voice_settings_payload(profile),
    }

    if model_id != "eleven_multilingual_v2" and not is_v4_model(model_idx) and 0 < lang_idx < len(LANGUAGE_CODES):
        lang_code = LANGUAGE_CODES[lang_idx]
        if lang_code:
            payload["language_code"] = lang_code

    if hcaptcha_token:
        payload["hcaptcha_token"] = hcaptcha_token

    # 3. Chuẩn bị Proxy & Session curl_cffi
    session = requests.Session(impersonate="chrome120")
    if proxy_url and proxy_url.lower() != "null":
        session.proxies = {
            "http": proxy_url,
            "https": proxy_url,
        }

    # Chọn ngẫu nhiên browser profile cho Headers
    ua_prof = random.choice(BROWSER_PROFILES)

    # 4. Nhánh A: Chạy qua Official API Key nếu không có hCaptcha token nhưng có API Key
    if not hcaptcha_token and api_key and api_key.strip():
        target_url = ELEVENLABS_OFFICIAL_TTS_URL.format(voice_id=voice_id)
        headers = {
            "xi-api-key": api_key.strip(),
            "Content-Type": "application/json",
            "User-Agent": ua_prof["ua"],
        }
        try:
            logger.debug(f"Gọi Official TTS API cho {out_file.name}...")
            resp = session.post(target_url, headers=headers, json=payload, timeout=timeout)
            if resp.status_code == 200 and resp.content:
                temp_partial.write_bytes(resp.content)
                temp_partial.replace(out_file)
                return TtsResult(success=True, retryable=False, message="Đã lưu MP3 qua Official API.")
            return TtsResult.from_error(resp.status_code, resp.text)
        except Exception as e:
            return TtsResult(success=False, retryable=True, message=f"Lỗi kết nối Official API: {e}")

    # Nếu không có cả hCaptcha token lẫn API Key
    if not hcaptcha_token and not (api_key and api_key.strip()):
        return TtsResult(
            success=False,
            retryable=False,
            message="Không tìm thấy hCaptcha token hoặc API Key để tạo âm thanh.",
            is_worker_stopping_error=True
        )

    # 5. Nhánh B: Chạy qua Anonymous TTS Endpoint kèm hCaptcha Token
    target_url = ELEVENLABS_ANONYMOUS_TTS_URL.format(voice_id=voice_id)
    url_to_call = f"{FERNDOCS_PROXY_BASE}{target_url}" if use_ferndocs else target_url

    headers = {
        "User-Agent": ua_prof["ua"],
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9,vi;q=0.8",
        "Origin": "https://elevenlabs.io",
        "Referer": "https://elevenlabs.io/",
        "Content-Type": "application/json",
        "sec-ch-ua": ua_prof["sec_ch_ua"],
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": ua_prof["platform"],
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "cross-site" if use_ferndocs else "same-site",
    }
    if use_ferndocs:
        headers["x-fern-proxy-request-headers"] = "Content-Type"

    try:
        logger.debug(f"Gửi Anonymous TTS request ({out_file.name}) tới: {url_to_call}")
        response = session.post(
            url_to_call,
            headers=headers,
            json=payload,
            timeout=timeout
        )

        if response.status_code != 200:
            error_body = response.text
            logger.warning(f"TTS {out_file.name} thất bại HTTP {response.status_code}: {error_body[:200]}")
            return TtsResult.from_error(response.status_code, error_body)

        # 6. Parse phản hồi NDJSON
        audio_chunks = []
        for line in response.text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                b64 = data.get("audio_base64")
                if b64:
                    audio_chunks.append(base64.b64decode(b64))
            except Exception:
                pass

        if not audio_chunks:
            return TtsResult(
                success=False,
                retryable=False,
                message="Server trả về 200 nhưng không tìm thấy trường audio_base64 hợp lệ."
            )

        full_audio = b"".join(audio_chunks)
        temp_partial.write_bytes(full_audio)
        temp_partial.replace(out_file)
        logger.debug(f"Đã lưu thành công đoạn âm thanh {out_file.name} ({len(full_audio):,} bytes)")
        return TtsResult(success=True, retryable=False, message="Đã lưu MP3 thành công.")

    except Exception as e:
        logger.error(f"Lỗi ngoại lệ khi gọi TTS cho {out_file.name}: {e}")
        return TtsResult(success=False, retryable=True, message=str(e))
    finally:
        if temp_partial.exists():
            try:
                temp_partial.unlink()
            except Exception:
                pass
