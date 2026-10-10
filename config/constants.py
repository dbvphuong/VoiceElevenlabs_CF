"""Hằng số cấu hình hệ thống."""

# hCaptcha SiteKey dùng trên trang elevenlabs.io
HCAPTCHA_SITEKEY = "8e58fe8c-1a48-4f94-88ae-8e90b586a192"

# Các Endpoint của ElevenLabs
ELEVENLABS_HOME_URL = "https://elevenlabs.io/"
ELEVENLABS_ANONYMOUS_TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream/with-timestamps/anonymous"
ELEVENLABS_OFFICIAL_TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream?output_format=mp3_44100_128"
FERNDOCS_PROXY_BASE = "https://proxy.ferndocs.com/"

# Dịch vụ kiểm tra IP & Proxy ngoài
TOP_PROXY_API_URL = "https://proxyxoay.shop/api/get.php?key={key}&nhamang=Random&tinhthanh=0"
IPIFY_URL = "https://api.ipify.org"

# Danh sách Model ID hỗ trợ (đồng bộ với C# ElevenLabsAPITest.ModelIds)
MODEL_IDS = [
    "eleven_multilingual_v2",
    "eleven_flash_v2",
    "eleven_flash_v2_5",
    "eleven_turbo_v2",
    "eleven_turbo_v2_5",
    "eleven_v3",
    "eleven_v4",
    "eleven_v4_turbo",
]

# Mã ngôn ngữ (Model v2 trở lên)
LANGUAGE_CODES = [None, "en", "vi", "ja", "zh"]

# Danh sách User-Agent và Client Hints giả lập trình duyệt thực tế (Windows Chrome)
BROWSER_PROFILES = [
    {
        "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
        "sec_ch_ua": '"Google Chrome";v="135", "Chromium";v="135", "Not-A.Brand";v="8"',
        "platform": '"Windows"',
    },
    {
        "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
        "sec_ch_ua": '"Google Chrome";v="134", "Chromium";v="134", "Not-A.Brand";v="8"',
        "platform": '"Windows"',
    },
    {
        "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
        "sec_ch_ua": '"Google Chrome";v="133", "Chromium";v="133", "Not-A.Brand";v="8"',
        "platform": '"Windows"',
    },
]

# Giới hạn kích thước cắt văn bản mặc định
DEFAULT_CHUNK_SIZE = 333
MAX_RETRY_ROUNDS = 5
