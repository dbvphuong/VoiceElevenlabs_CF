# 11labs CF Automation Tool (Python)

Ứng dụng desktop và dòng lệnh tự động chuyển văn bản thành giọng nói (Text-to-Speech) qua ElevenLabs sử dụng kỹ thuật vượt hCaptcha tàng hình (Invisible hCaptcha) và kết nối luồng âm thanh ẩn danh (Anonymous Stream), chuyển đổi và tối ưu hóa từ phiên bản WinForms C# (`DgtCloneCs`).

---

## 1. Điểm Nổi Bật

* **Tiết kiệm tài nguyên:** Thay thế WebView2 nặng nề của C# bằng Playwright Chromium Headless tối ưu (chặn hình ảnh, font, media; tự động dọn DOM), giảm 70% RAM.
* **Lách Cloudflare WAF & TLS Fingerprint:** Sử dụng `curl_cffi` giả lập trọn vẹn vân tay Chrome 120 (TLS/JA3/HTTP2) cùng kỹ thuật Micro-jitter.
* **Cơ chế Proxy xoay & Phục hồi lỗi:** Hỗ trợ cả Proxy tĩnh và API Proxy xoay (`proxyxoay.shop`), tự động nhận diện và xoay IP khi hết hạn ngạch demo trên landing page (`sign_in_required`).
* **Cơ chế Resume thông minh:** Tự động phát hiện các đoạn MP3 đã tạo từ phiên trước để tái sử dụng, không sinh lại gây tốn tài nguyên.
* **Ghép nối âm thanh chất lượng cao:** Tích hợp `FFmpeg` demuxer `concat` và bộ lọc `anullsrc` tạo khoảng lặng chính xác giữa các đoạn.
* **Độc lập 2 chế độ:** Có thể chạy giao diện đồ họa hiện đại (**PyQt6 GUI**) hoặc chạy nền trên máy chủ không màn hình (**CLI Runner**).

---

## 2. Cách Sử Dụng Nhanh với `run.bat` (Duy nhất 1 tệp khởi chạy)

### Cách 1: Mở Giao diện đồ họa (GUI Desktop)
* Chỉ cần **nhấp đúp chuột vào tệp [`run.bat`](file:///e:/GG/VoiceElevenlabs_CF/run.bat)** trong thư mục dự án. Giao diện Desktop sẽ mở lên ngay lập tức.

### Cách 2: Chạy dòng lệnh tiện lợi (Kéo & Thả)
* **Kéo và thả** bất kỳ tệp `.txt` hoặc thư mục truyện nào trực tiếp vào tệp **[`run.bat`](file:///e:/GG/VoiceElevenlabs_CF/run.bat)**, hệ thống sẽ tự động kích hoạt chế độ CLI xử lý ngay lập tức.

### Cách 3: Chạy qua Terminal / CMD
* Chạy trực tiếp qua `run.bat` kèm cờ tùy chọn hoặc gọi qua môi trường ảo:
  ```cmd
  :: Xem trợ giúp
  run.bat --help

  :: Xử lý 1 tệp văn bản cụ thể
  run.bat -i "C:\path\to\story.txt" -v "21m00Tcm4TlvDq8ikWAM"

  :: Quét và xử lý toàn bộ thư mục (kèm thư mục con)
  run.bat -f "C:\path\to\folder" -r --threads 2 --silence 0.3
  ```

---

## 3. Cấu Trúc Thư Mục Dự Án

```text
VoiceElevenlabs_CF/
├── config/             # Cấu hình hệ thống (settings.py, constants.py)
├── core/               # Xử lý văn bản (text_splitter), audio (audio_merger), file (file_scanner)
├── network/            # Quản lý proxy_pool, top_proxy_client, proxy_checker, tts_client
├── captcha/            # Dịch vụ Playwright farm token (token_farmer, scripts)
├── pipeline/           # Bộ điều phối hàng đợi (worker.py, orchestrator.py)
├── ui/                 # Giao diện người dùng PyQt6 (main_window, settings_dialog, bridge)
├── utils/              # Tiện ích logging xoay vòng tự động (logger.py)
├── logs/               # Thư mục lưu trữ nhật ký hoạt động (app_*.log, error_*.log, crash.log)
├── tests/              # Bộ kiểm thử tự động (pytest)
│
├── run.bat             # Tệp khởi động DUY NHẤT (Tự nhận diện GUI / Kéo thả / CLI)
├── settings.json       # Tệp lưu trữ cài đặt cấu hình cục bộ
├── requirements.txt    # Danh sách thư viện phụ thuộc
├── PLAN.md             # Kế hoạch chi tiết 5 giai đoạn
├── main.py             # Entry point khởi chạy GUI
└── cli.py              # Entry point khởi chạy CLI
```

---

## 4. Chạy Kiểm Thử Đơn Vị (Unit Tests)

Dự án đi kèm 9 bài test tự động bao phủ toàn bộ các module lõi:
```powershell
.\venv\Scripts\pytest.exe -v
```
Kết quả kiểm thử: **9/9 tests PASSED (100%)**.
