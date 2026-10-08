import asyncio
import base64
import json
import time
from pathlib import Path
from playwright.async_api import async_playwright, Route
from curl_cffi import requests
from loguru import logger

VOICE_ID = "21m00Tcm4TlvDq8ikWAM"  # Rachel (hoặc voice bất kỳ)
SAMPLE_TEXT = "Xin chào, đây là bản thử nghiệm thành công trên Python."
OUTPUT_FILE = Path("test_poc_output.mp3")

# Proxy (dạng host:port:user:pass)
PROXY_RAW = ""

def parse_proxy(raw: str):
    if not raw or raw == "null":
        return None
    parts = raw.split(":")
    if len(parts) == 4:
        host, port, user, password = parts
        return {
            "server": f"http://{host}:{port}",
            "username": user,
            "password": password,
            "curl_url": f"http://{user}:{password}@{host}:{port}"
        }
    return None

HCAPTCHA_TRIGGER_JS = """
() => {
    return new Promise((resolve, reject) => {
        try {
            // Xóa React root để tối ưu RAM
            const root = document.getElementById('__next') || document.getElementById('root');
            if (root) root.remove();
            document.querySelectorAll('video, audio, iframe').forEach(el => el.remove());
        } catch(e) {}

        function doCaptcha() {
            const sitekey = '8e58fe8c-1a48-4f94-88ae-8e90b586a192';
            const div = document.createElement('div');
            div.style.display = 'none';
            document.body.appendChild(div);

            try {
                const widgetId = window.hcaptcha.render(div, {
                    sitekey: sitekey,
                    size: 'invisible',
                    callback: function(token) {
                        try { div.remove(); } catch(e) {}
                        resolve(token);
                    },
                    'error-callback': function(err) {
                        try { div.remove(); } catch(e) {}
                        reject('hCaptcha error: ' + JSON.stringify(err));
                    },
                    'close-callback': function() {
                        try { div.remove(); } catch(e) {}
                        reject('hCaptcha closed');
                    }
                });

                window.hcaptcha.reset(widgetId);
                window.hcaptcha.execute(widgetId);
            } catch (err) {
                try { div.remove(); } catch(e) {}
                reject('Execute exception: ' + String(err));
            }
        }

        if (!window.hcaptcha) {
            const script = document.createElement('script');
            script.src = 'https://js.hcaptcha.com/1/api.js';
            document.head.appendChild(script);

            let checkCount = 0;
            const timer = setInterval(() => {
                if (window.hcaptcha) {
                    clearInterval(timer);
                    doCaptcha();
                }
                if (checkCount++ > 60) {
                    clearInterval(timer);
                    reject('Timeout loading hCaptcha api.js');
                }
            }, 250);
        } else {
            doCaptcha();
        }
    });
}
"""

async def farm_hcaptcha_token(proxy_info=None, timeout_seconds: int = 35) -> str:
    logger.info("Khởi chạy Playwright Chromium (Headless mode)...")
    start_time = time.time()
    
    async with async_playwright() as p:
        browser_args = [
            "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
            "--enforce-webrtc-ip-permission-check",
            "--disable-blink-features=AutomationControlled",
        ]
        
        launch_kwargs = {
            "headless": True,
            "args": browser_args
        }
        if proxy_info:
            launch_kwargs["proxy"] = {
                "server": proxy_info["server"],
                "username": proxy_info["username"],
                "password": proxy_info["password"],
            }
            logger.info(f"Playwright sử dụng Proxy: {proxy_info['server']}")
            
        browser = await p.chromium.launch(**launch_kwargs)
        
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
            locale="en-US",
            viewport={"width": 800, "height": 600}
        )
        
        page = await context.new_page()
        
        # Handler chặn tài nguyên dạng async chuẩn
        async def handle_route(route: Route):
            if route.request.resource_type in ["image", "media", "font"]:
                await route.abort()
            else:
                await route.continue_()
                
        await page.route("**/*", handle_route)
        
        logger.info("Đang truy cập elevenlabs.io...")
        await page.goto("https://elevenlabs.io/", wait_until="commit", timeout=30000)
        # Đợi trang bắt đầu có DOM
        await page.wait_for_load_state("domcontentloaded", timeout=20000)
        
        logger.info("Đang inject script và lấy hCaptcha invisible token...")
        token = await asyncio.wait_for(
            page.evaluate(HCAPTCHA_TRIGGER_JS),
            timeout=timeout_seconds
        )
        
        elapsed = time.time() - start_time
        logger.success(f"Lấy token hCaptcha thành công trong {elapsed:.2f}s! (Độ dài: {len(token)})")
        await browser.close()
        return token

def call_tts_anonymous(hcaptcha_token: str, text: str, voice_id: str, output_path: Path, proxy_info=None, use_ferndocs=False) -> bool:
    target_url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream/with-timestamps/anonymous"
    url_to_call = f"https://proxy.ferndocs.com/{target_url}" if use_ferndocs else target_url
    
    logger.info(f"Đang gửi request TTS tới: {url_to_call} (use_ferndocs={use_ferndocs})")
    
    payload = {
        "text": text,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {
            "similarity_boost": 0.5,
            "stability": 0.5
        },
        "hcaptcha_token": hcaptcha_token
    }
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9,vi;q=0.8",
        "Origin": "https://elevenlabs.io",
        "Referer": "https://elevenlabs.io/",
        "Content-Type": "application/json",
        "sec-ch-ua": '"Not_A Brand";v="8", "Chromium";v="135", "Google Chrome";v="135"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-site" if not use_ferndocs else "cross-site"
    }
    if use_ferndocs:
        headers["x-fern-proxy-request-headers"] = "Content-Type"
    
    session = requests.Session(impersonate="chrome120")
    if proxy_info:
        logger.info(f"curl_cffi sử dụng Proxy: {proxy_info['curl_url']}")
        session.proxies = {
            "http": proxy_info["curl_url"],
            "https": proxy_info["curl_url"]
        }
        
    response = session.post(
        url_to_call,
        headers=headers,
        json=payload,
        timeout=35
    )
    
    logger.info(f"Mã phản hồi HTTP: {response.status_code}")
    
    if response.status_code != 200:
        logger.error(f"Lỗi từ server ({response.status_code}): {response.text[:500]}")
        return False
        
    audio_chunks = []
    lines = response.text.splitlines()
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
            b64_str = data.get("audio_base64")
            if b64_str:
                audio_chunks.append(base64.b64decode(b64_str))
        except Exception:
            pass
            
    if not audio_chunks:
        logger.error("Không tìm thấy trường 'audio_base64' trong phản hồi.")
        return False
        
    full_audio = b"".join(audio_chunks)
    output_path.write_bytes(full_audio)
    logger.success(f"ĐÃ LƯU FILE MP3 THÀNH CÔNG: {output_path} ({len(full_audio):,} bytes)")
    return True

async def main():
    logger.info("=== BẮT ĐẦU CHẠY THỬ NGHIỆM SPIKE POC (PHASE 1) ===")
    
    proxy_info = parse_proxy(PROXY_RAW)
    logger.info(f"Proxy cấu hình: {proxy_info['server'] if proxy_info else 'Trực tiếp (Không proxy)'}")
    
    try:
        # Bước 1: Lấy Token hCaptcha qua Playwright
        token = await farm_hcaptcha_token(proxy_info=proxy_info)
        
        # Bước 2A: Thử gọi TRỰC TIẾP ElevenLabs bằng curl_cffi (Chrome 120 impersonate)
        logger.info("--- Thử nghiệm 2A: Gọi trực tiếp ElevenLabs qua curl_cffi ---")
        success = call_tts_anonymous(
            hcaptcha_token=token,
            text=SAMPLE_TEXT,
            voice_id=VOICE_ID,
            output_path=OUTPUT_FILE,
            proxy_info=proxy_info,
            use_ferndocs=False
        )
        
        # Nếu chưa được, thử 2B qua FernDocs
        if not success:
            logger.info("--- Thử nghiệm 2B: Thử qua FernDocs proxy ---")
            success = call_tts_anonymous(
                hcaptcha_token=token,
                text=SAMPLE_TEXT,
                voice_id=VOICE_ID,
                output_path=OUTPUT_FILE,
                proxy_info=proxy_info,
                use_ferndocs=True
            )
            
        if success and OUTPUT_FILE.exists() and OUTPUT_FILE.stat().st_size > 0:
            logger.success("=== THỬ NGHIỆM GIAI ĐOẠN 1 THÀNH CÔNG 100%! ===")
            logger.info(f"File audio được lưu tại: {OUTPUT_FILE.resolve()}")
        else:
            logger.warning("Thử nghiệm chưa tạo được audio thành công.")
            
    except Exception as e:
        logger.exception(f"Lỗi: {e}")

if __name__ == "__main__":
    asyncio.run(main())
