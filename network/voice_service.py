"""Dịch vụ tra cứu và quản lý giọng đọc ElevenLabs (Voice Lookup & Search Service)."""

import json
from pathlib import Path
from typing import Optional, List, Dict, Any
from curl_cffi import requests
from loguru import logger

# Danh sách một số giọng mẫu tiêu chuẩn & phổ biến trên ElevenLabs
DEFAULT_PREMADE_VOICES: List[Dict[str, Any]] = [
    {
        "voice_id": "21m00Tcm4TlvDq8ikWAM",
        "name": "Rachel - Calm, Gentle",
        "category": "premade",
        "labels": {"gender": "female", "accent": "american", "age": "young", "use_case": "narration", "descriptive": "calm"}
    },
    {
        "voice_id": "j9jfwdrw7BRfcR43Qohk",
        "name": "Frederick Surrey - vũ trụ",
        "category": "professional",
        "labels": {"gender": "male", "accent": "british", "age": "middle_aged", "use_case": "narrative_story", "descriptive": "calm"}
    },
    {
        "voice_id": "pNInz6obpgDQGcFmaJgB",
        "name": "Adam - Dominant, Firm",
        "category": "premade",
        "labels": {"gender": "male", "accent": "american", "age": "middle_aged", "use_case": "social_media"}
    },
    {
        "voice_id": "bfGb7JTLUnZebZRiFYyq",
        "name": "Adam - Distinct, Deep and Engaging",
        "category": "professional",
        "labels": {"gender": "male", "accent": "american", "age": "middle_aged", "use_case": "narrative_story", "descriptive": "deep"}
    },
    {
        "voice_id": "EXAVITQu4vr4xnSDxMaL",
        "name": "Sarah - Mature, Reassuring, Confident",
        "category": "premade",
        "labels": {"gender": "female", "accent": "american", "age": "young", "use_case": "entertainment_tv", "descriptive": "professional"}
    },
    {
        "voice_id": "JBFqnCBsd6RMkjVDRZzb",
        "name": "George - Warm, Captivating Storyteller",
        "category": "premade",
        "labels": {"gender": "male", "accent": "british", "age": "middle_aged", "use_case": "narrative_story", "descriptive": "mature"}
    },
    {
        "voice_id": "CwhRBWXzGAHq8TQ4Fs17",
        "name": "Roger - Laid-Back, Casual, Resonant",
        "category": "premade",
        "labels": {"gender": "male", "accent": "american", "age": "middle_aged", "use_case": "conversational", "descriptive": "classy"}
    },
    {
        "voice_id": "FGY2WhTYpPnrIDTdsKH5",
        "name": "Laura - Enthusiast, Quirky Attitude",
        "category": "premade",
        "labels": {"gender": "female", "accent": "american", "age": "young", "use_case": "social_media", "descriptive": "sassy"}
    },
    {
        "voice_id": "IKne3meq5aSn9XLyUdCD",
        "name": "Charlie - Deep, Confident, Energetic",
        "category": "premade",
        "labels": {"gender": "male", "accent": "australian", "age": "young", "use_case": "conversational", "descriptive": "hyped"}
    },
    {
        "voice_id": "N2lVS1w4EtoT3dr4eOWO",
        "name": "Callum - Husky Trickster",
        "category": "premade",
        "labels": {"gender": "male", "accent": "american", "age": "middle_aged", "use_case": "characters_animation"}
    },
    {
        "voice_id": "SAz9YHcvj6GT2YYXdXww",
        "name": "River - Relaxed, Neutral, Informative",
        "category": "premade",
        "labels": {"gender": "neutral", "accent": "american", "age": "middle_aged", "use_case": "conversational", "descriptive": "calm"}
    },
    {
        "voice_id": "SOYHLrjzK2X1ezoPC6cr",
        "name": "Harry - Fierce Warrior",
        "category": "premade",
        "labels": {"gender": "male", "accent": "american", "age": "young", "use_case": "characters_animation", "descriptive": "rough"}
    },
    {
        "voice_id": "TX3LPaxmHKxFdv7VOQHJ",
        "name": "Liam - Energetic, Social Media Creator",
        "category": "premade",
        "labels": {"gender": "male", "accent": "american", "age": "young", "use_case": "social_media", "descriptive": "confident"}
    },
    {
        "voice_id": "Xb7hH8MSUJpSbSDYk0k2",
        "name": "Alice - Clear, Engaging Educator",
        "category": "premade",
        "labels": {"gender": "female", "accent": "british", "age": "middle_aged", "use_case": "informative_educational", "descriptive": "professional"}
    },
    {
        "voice_id": "XrExE9yKIg1WjnnlVkGX",
        "name": "Matilda - Knowledgable, Professional",
        "category": "premade",
        "labels": {"gender": "female", "accent": "american", "age": "middle_aged", "use_case": "informative_educational", "descriptive": "upbeat"}
    },
    {
        "voice_id": "bIHbv24MWmeRgasZH58o",
        "name": "Will - Relaxed Optimist",
        "category": "premade",
        "labels": {"gender": "male", "accent": "american", "age": "young", "use_case": "conversational", "descriptive": "chill"}
    },
    {
        "voice_id": "cgSgspJ2msm6clMCkdW9",
        "name": "Jessica - Playful, Bright, Warm",
        "category": "premade",
        "labels": {"gender": "female", "accent": "american", "age": "young", "use_case": "conversational", "descriptive": "cute"}
    },
    {
        "voice_id": "cjVigY5qzO86Huf0OWal",
        "name": "Eric - Smooth, Trustworthy",
        "category": "premade",
        "labels": {"gender": "male", "accent": "american", "age": "middle_aged", "use_case": "conversational", "descriptive": "classy"}
    },
    {
        "voice_id": "hpp4J3VqNfWAUOO0d1Us",
        "name": "Bella - Professional, Bright, Warm",
        "category": "premade",
        "labels": {"gender": "female", "accent": "american", "age": "middle_aged", "use_case": "informative_educational", "descriptive": "professional"}
    },
    {
        "voice_id": "iP95p4xoKVk53GoZ742B",
        "name": "Chris - Charming, Down-to-Earth",
        "category": "premade",
        "labels": {"gender": "male", "accent": "american", "age": "middle_aged", "use_case": "conversational", "descriptive": "casual"}
    },
    {
        "voice_id": "nPczCjzI2devNBz1zQrb",
        "name": "Brian - Deep, Resonant and Comforting",
        "category": "premade",
        "labels": {"gender": "male", "accent": "american", "age": "middle_aged", "use_case": "social_media", "descriptive": "classy"}
    },
    {
        "voice_id": "onwK4e9ZLuTAKqWW03F9",
        "name": "Daniel - Steady Broadcaster",
        "category": "premade",
        "labels": {"gender": "male", "accent": "british", "age": "middle_aged", "use_case": "informative_educational", "descriptive": "formal"}
    },
    {
        "voice_id": "pFZP5JQG7iQjIQuC4Bku",
        "name": "Lily - Velvety Actress",
        "category": "premade",
        "labels": {"gender": "female", "accent": "british", "age": "middle_aged", "use_case": "informative_educational", "descriptive": "confident"}
    },
    {
        "voice_id": "pqHfZKP75CvOlQylNhV4",
        "name": "Bill - Wise, Mature, Balanced",
        "category": "premade",
        "labels": {"gender": "male", "accent": "american", "age": "old", "use_case": "advertisement", "descriptive": "crisp"}
    },
    {
        "voice_id": "W1hAcdh0RNsPYUA7fkJh",
        "name": "El Faraon - Deep, Powerful and Peaceful",
        "category": "professional",
        "labels": {"gender": "male", "accent": "colombian", "age": "middle_aged", "use_case": "narrative_story"}
    },
    {
        "voice_id": "UQoLnPXvf18gaKpLzfb8",
        "name": "Sawyer - Calm, Measured and Serious",
        "category": "professional",
        "labels": {"gender": "male", "accent": "american", "age": "middle_aged", "use_case": "informative_educational"}
    },
    {
        "voice_id": "dPah2VEoifKnZT37774q",
        "name": "Knox Dark - Serious, Deep, and Steady",
        "category": "professional",
        "labels": {"gender": "male", "accent": "american", "age": "middle_aged", "use_case": "narrative_story"}
    }
]

CACHE_FILE = Path(__file__).resolve().parent.parent / "config" / "voices_cache.json"

class VoiceService:
    """Quản lý tra cứu, tìm kiếm và đồng bộ danh sách giọng ElevenLabs."""

    def __init__(self, cache_path: Optional[Path] = None):
        self.cache_path = cache_path or CACHE_FILE
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._load_cache()

    def _load_cache(self) -> None:
        # 1. Nạp danh sách mặc định
        for v in DEFAULT_PREMADE_VOICES:
            self._cache[v["voice_id"]] = v

        # 2. Nạp thêm từ tệp cache nếu có
        if self.cache_path.exists():
            try:
                data = json.loads(self.cache_path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    for v in data:
                        if "voice_id" in v:
                            self._cache[v["voice_id"]] = v
            except Exception as e:
                logger.warning(f"Lỗi đọc voices_cache.json: {e}")

    def _save_cache(self) -> None:
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            voice_list = list(self._cache.values())
            self.cache_path.write_text(
                json.dumps(voice_list, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
        except Exception as e:
            logger.warning(f"Lỗi ghi voices_cache.json: {e}")

    def get_cached_voice(self, voice_id: str) -> Optional[Dict[str, Any]]:
        """Lấy thông tin giọng từ cache cục bộ."""
        return self._cache.get(voice_id.strip())

    def fetch_voice_by_id(
        self,
        voice_id: str,
        api_key: Optional[str] = None,
        proxy_url: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Tra cứu thông tin chi tiết một Voice ID qua API ElevenLabs hoặc Cache."""
        vid = voice_id.strip()
        if not vid:
            return None

        # 1. Nếu có API key, ưu tiên truy vấn trực tiếp ElevenLabs để lấy tên chuẩn & cấu hình mới nhất
        if api_key and api_key.strip():
            url = f"https://api.elevenlabs.io/v1/voices/{vid}"
            headers = {"xi-api-key": api_key.strip()}
            proxies = None
            if proxy_url and proxy_url.lower() != "null":
                proxies = {"http": proxy_url, "https": proxy_url}

            try:
                session = requests.Session(impersonate="chrome120")
                if proxies:
                    session.proxies = proxies
                resp = session.get(url, headers=headers, timeout=8)
                if resp.status_code == 200:
                    data = resp.json()
                    item = {
                        "voice_id": vid,
                        "name": data.get("name", vid),
                        "category": data.get("category", "custom"),
                        "labels": data.get("labels", {}),
                        "description": data.get("description", ""),
                        "settings": data.get("settings", {}),
                        "preview_url": data.get("preview_url", "")
                    }
                    self._cache[vid] = item
                    self._save_cache()
                    return item
                else:
                    logger.debug(f"API ElevenLabs trả mã {resp.status_code} cho voice {vid}")
            except Exception as e:
                logger.debug(f"Không thể gọi API ElevenLabs cho voice {vid}: {e}")

        # 2. Fallback: Trả về từ Cache / Mặc định nếu có
        return self.get_cached_voice(vid)

    def search_shared_voices(
        self,
        query: str,
        api_key: Optional[str] = None,
        page_size: int = 30
    ) -> List[Dict[str, Any]]:
        """Tìm kiếm giọng trong thư viện cộng đồng ElevenLabs (Shared Voices Library)."""
        q = query.strip()
        if not q or not api_key:
            return []

        url = f"https://api.elevenlabs.io/v1/shared-voices?page_size={page_size}&search={requests.utils.quote(q)}"
        headers = {"xi-api-key": api_key.strip()}
        try:
            session = requests.Session(impersonate="chrome120")
            resp = session.get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                results = []
                for v in data.get("voices", []):
                    vid = v.get("voice_id")
                    if vid:
                        item = {
                            "voice_id": vid,
                            "name": v.get("name", vid),
                            "category": "shared_community",
                            "labels": {
                                "accent": v.get("accent", ""),
                                "gender": v.get("gender", ""),
                                "age": v.get("age", ""),
                                "descriptive": v.get("descriptive", "")
                            },
                            "description": v.get("description", ""),
                            "settings": {},
                            "preview_url": v.get("preview_url", "")
                        }
                        results.append(item)
                        # Lưu vào cache để dùng lại
                        self._cache[vid] = item
                if results:
                    self._save_cache()
                return results
        except Exception as e:
            logger.warning(f"Lỗi tìm kiếm shared voices trên ElevenLabs: {e}")
        return []

    def fetch_all_voices(
        self,
        api_key: Optional[str] = None,
        proxy_url: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Lấy toàn bộ danh sách giọng có sẵn (từ tài khoản qua API key hoặc từ Cache)."""
        if api_key and api_key.strip():
            url = "https://api.elevenlabs.io/v1/voices"
            headers = {"xi-api-key": api_key.strip()}
            proxies = None
            if proxy_url and proxy_url.lower() != "null":
                proxies = {"http": proxy_url, "https": proxy_url}

            try:
                session = requests.Session(impersonate="chrome120")
                if proxies:
                    session.proxies = proxies
                resp = session.get(url, headers=headers, timeout=10)
                if resp.status_code == 200:
                    voices_data = resp.json().get("voices", [])
                    for v in voices_data:
                        vid = v.get("voice_id")
                        if vid:
                            self._cache[vid] = {
                                "voice_id": vid,
                                "name": v.get("name", vid),
                                "category": v.get("category", "custom"),
                                "labels": v.get("labels", {}),
                                "description": v.get("description", ""),
                                "settings": v.get("settings", {}),
                                "preview_url": v.get("preview_url", "")
                            }
                    self._save_cache()
            except Exception as e:
                logger.warning(f"Lỗi lấy danh sách giọng từ ElevenLabs: {e}")

        return list(self._cache.values())

# Đối tượng singleton dùng chung trong toàn ứng dụng
voice_service = VoiceService()
