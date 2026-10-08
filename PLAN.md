# Kế Hoạch Chuyển Đổi Dự Án DgtAutoElevenCs Sang Python (VoiceElevenlabs_CF)

Tài liệu này lưu trữ lộ trình phát triển, kiến trúc hệ thống và cấu trúc thư mục của dự án Python phục vụ việc tự động tạo giọng nói ElevenLabs qua cơ chế bypass hCaptcha và Anonymous TTS.

---

## 1. Kết quả Giai đoạn 1 (Spike PoC) - ĐÃ HOÀN THÀNH ✅

* **Môi trường:** Đã thiết lập Virtualenv `venv` (Python 3.13) và tệp `requirements.txt`.
* **Playwright Token Farmer (`test_poc.py`):**
  * Khởi chạy Chromium ở chế độ `headless` hoàn toàn.
  * Tối ưu hóa: Chặn request tải ảnh, font, media; xóa DOM React của ElevenLabs (`#__next`, `#root`).
  * Lấy token hCaptcha invisible thành công trong **~5.6 giây**, kích thước token ~2.360 ký tự, RAM tiêu thụ <150MB.
* **Xác thực API TTS:**
  * Thử nghiệm gửi token qua `curl_cffi` (giả lập Chrome 120).
  * Kiểm chứng cơ chế lỗi tương đồng 100% với bản C# gốc:
    * IP mạng trực tiếp: ElevenLabs phản hồi `HTTP 401 detected_unusual_activity`.
    * IP Proxy cố định: ElevenLabs phản hồi `HTTP 401 sign_in_required / quota_exceeded` (hết hạn ngạch demo trên landing page).
  * Kết luận: Khẳng định tính khả thi 100% của giải pháp và yêu cầu bắt buộc phải có cơ chế **Proxy Xoay (Rotating Proxy Pool)** để chạy tự động quy mô lớn.

---

## 2. Cấu Trúc Thư Mục Dự Án (Folder Structure)

```text
VoiceElevenlabs_CF/
│
├── config/                         # Quản lý cấu hình & hằng số hệ thống
│   ├── __init__.py
│   ├── settings.py                 # Pydantic Model: AppSettings, VoiceTemplate, ProxyConfig
│   └── constants.py                # Hằng số: URL ElevenLabs, SiteKey hCaptcha, Header mẫu
│
├── core/                           # Nhân xử lý văn bản, tệp và âm thanh
│   ├── __init__.py
│   ├── text_splitter.py            # Cắt đoạn thông minh theo dấu câu đa ngôn ngữ (<= 333 ký tự)
│   ├── audio_merger.py             # Ghép nối các part MP3 & chèn khoảng lặng bằng FFmpeg/pydub
│   ├── file_scanner.py             # Quét tệp .txt trong danh sách thư mục (hỗ trợ đệ quy)
│   └── models.py                   # Data classes: ChunkTask, FileProgress, TtsResult
│
├── network/                        # Tầng kết nối mạng, Proxy & API Client
│   ├── __init__.py
│   ├── proxy_pool.py               # Quản lý Pool Proxy (Round-robin, Cooldown 60s, Async Lock)
│   ├── top_proxy_client.py         # Kết nối API proxyxoay.shop lấy IP mới & thời gian chờ
│   ├── proxy_checker.py            # Kiểm tra Exit IP public qua ipify
│   └── tts_client.py               # Gọi ElevenLabs TTS (hỗ trợ Anonymous & API Key v4, Micro-jitter, NDJSON parser)
│
├── captcha/                        # Tầng giải hCaptcha & Farm Token
│   ├── __init__.py
│   ├── token_farmer.py             # Playwright Worker đóng gói thành Service cung cấp Token
│   └── scripts.py                  # Mã JavaScript inject kích hoạt widget hCaptcha invisible
│
├── pipeline/                       # Bộ điều phối hàng đợi & xử lý đa luồng
│   ├── __init__.py
│   ├── worker.py                   # Vòng lặp Worker xử lý từng chunk (lấy IP -> lấy Token -> gọi TTS -> retry)
│   └── orchestrator.py             # Quản lý tiến trình tổng: phân phối N workers, resume file, ghép audio
│
├── ui/                             # Giao diện người dùng (PyQt6)
│   ├── __init__.py
│   ├── main_window.py              # Cửa sổ chính: danh sách file, bảng chunks, thanh thông số giọng đọc
│   ├── settings_dialog.py          # Hộp thoại cấu hình: Proxy, API key, Thread count, Chunk size
│   ├── log_widget.py               # Widget hiển thị log màu thời gian thực
│   └── bridge.py                   # QThread / Signal-Slot adapter kết nối UI với Pipeline không đơ giao diện
│
├── utils/                          # Tiện ích chung
│   ├── __init__.py
│   └── logger.py                   # Cấu hình loguru: ghi Console, file logs.txt và bắn sự kiện về UI
│
├── tests/                          # Tệp kiểm thử đơn vị
│   └── __init__.py
│
├── test_poc.py                     # Script PoC đã kiểm chứng thành công ở Phase 1
├── requirements.txt                # Thư viện phụ thuộc
├── settings.json                   # Tệp cấu hình lưu trữ cục bộ
├── PLAN.md                         # Kế hoạch & Kiến trúc tổng thể (tệp này)
├── main.py                         # Entry point khởi chạy GUI
└── cli.py                          # Entry point chạy CLI (chạy không cần màn hình trên VPS)
```

---

## 3. Lộ Trình 5 Giai Đoạn (Development Roadmap)

### ✅ Giai đoạn 1: Spike PoC (Đã hoàn thành)
- [x] Tạo virtualenv `venv` và tệp `requirements.txt`.
- [x] Cài đặt Chromium cho Playwright.
- [x] Viết `test_poc.py` kiểm chứng lấy invisible hCaptcha token thành công.
- [x] Kiểm chứng luồng gửi API TTS anonymous và đối chiếu lỗi với mã nguồn C#.

---

### ✅ Giai đoạn 2: Xây Dựng Core & Network Modules (Đã hoàn thành)
- [x] **`config/settings.py` & `config/constants.py`**:
  - Định nghĩa `AppSettings` bằng Pydantic (tương thích 100% với file `settings.json` của C#).
  - Tự động load / save tệp JSON.
- [x] **`core/text_splitter.py`**:
  - Chuyển đổi hàm `AudioProcessor.SplitTextBySentences` từ C# sang Python.
  - Giữ đúng 3 tầng ưu tiên ngắt dấu câu (Chấm/hỏi/than $\rightarrow$ Phẩy/chấm phẩy $\rightarrow$ Trợ từ Á Đông).
- [x] **`core/audio_merger.py`**:
  - Gọi `ffmpeg.exe` ghép các tệp `part_*.mp3` bằng demuxer `concat` và bộ sinh khoảng lặng `anullsrc`.
- [x] **`core/file_scanner.py`**:
  - Quét đệ quy các tệp `.txt` từ danh sách thư mục, lọc bỏ tệp trùng lặp.
- [x] **`network/proxy_pool.py` & `network/top_proxy_client.py`**:
  - Triển khai cơ chế xoay vòng Round-robin, Cooldown 60s khi gặp lỗi.
  - Tích hợp API `proxyxoay.shop` lấy proxy mới và parse thời gian chờ IP.
  - Tích hợp hàm kiểm tra Exit IP qua `ipify.org`.
- [x] **`network/tts_client.py`**:
  - Đóng gói request TTS với `curl_cffi` (impersonate Chrome 120, Micro-jitter 200-1500ms, NDJSON parser).
  - Phân loại lỗi `TtsResult` (`sign_in_required`, `detected_unusual_activity`, HTTP 429, 500...).
- [x] **`captcha/token_farmer.py` & `captcha/scripts.py`**:
  - Đóng gói Service Playwright Chromium cung cấp Token hCaptcha invisible.
- [x] **`tests/test_core.py`**:
  - 7/7 bài kiểm thử đơn vị tự động đã vượt qua (100% pass).

---

### ✅ Giai đoạn 3: Bộ Điều Phối Pipeline & CLI Runner (Đã hoàn thành)
- [x] **`captcha/token_farmer.py`**:
  - Đóng gói Playwright thành Service/Worker tái sử dụng trình duyệt, dọn RAM bằng `about:blank`.
  - Cơ chế tự phục hồi: Khởi tạo lại browser context nếu bị lỗi 2 lần liên tiếp.
- [x] **`pipeline/worker.py` & `pipeline/orchestrator.py`**:
  - Quản lý hàng đợi `asyncio.Queue` cho các `ChunkTask`.
  - Phân phối N worker chạy đồng thời theo Round-robin.
  - Cơ chế Resume: Tự động bỏ qua các `part_*.mp3` đã hoàn thành từ phiên trước.
  - Vòng lặp retry đa tầng (tối đa 5 rounds lớn).
  - Tự động gọi ghép audio khi 1 file hoàn thành tất cả các chunk và dọn dẹp các part tạm.
- [x] **`cli.py`**:
  - Giao diện dòng lệnh hoàn chỉnh với đầy đủ tham số `-i`, `-f`, `-r`, `-t`, `-v`, `--speed`, `--silence`, `--proxy`, `--api-key`.
  - Hỗ trợ in tiếng Việt Unicode mượt mà trên console Windows.
- [x] **`tests/test_pipeline.py`**:
  - Kiểm thử tự động cơ chế Resume và tự động ghép file MP3 khi đủ chunk (9/9 tests pass).

---

### ✅ Giai đoạn 4: Giao Diện Người Dùng (PyQt6 UI) (Đã hoàn thành)
- [x] **`ui/main_window.py`**:
  - Giao diện hai cột hiện đại: bảng danh sách tệp .txt và bảng chi tiết từng chunk của tệp được chọn.
  - Bảng tham số giọng đọc: Speed, Stability, Similarity, Style, Model, Voice ID.
  - Tiến độ tổng thể (QProgressBar), nhãn thống kê, nút Bắt đầu / Dừng lại.
- [x] **`ui/settings_dialog.py`**:
  - Hộp thoại cấu hình Proxy tĩnh, Proxy xoay, ElevenLabs API Key, Số luồng, Kích thước đoạn, Khoảng lặng.
- [x] **`ui/log_widget.py`**:
  - Khung nhật ký hoạt động thời gian thực phân màu theo cấp độ (INFO, SUCCESS, WARNING, ERROR), tự động cuộn.
- [x] **`ui/bridge.py`**:
  - Luồng `QThread` chạy song song với giao diện, truyền tín hiệu `pyqtSignal` cập nhật bảng biểu và thanh tiến độ mượt mà, không gây đơ lag giao diện (Unfreeze UI).
- [x] **`main.py`**:
  - Điểm khởi chạy ứng dụng Desktop với bộ giao diện QSS phẳng, hiện đại và thanh lịch.

---

### ✅ Giai đoạn 5: Kiểm Thử Toàn Diện & Tệp Khởi Chạy Nhanh (.BAT) (Đã hoàn thành)
- [x] **`run.bat`**: Tệp khởi chạy DUY NHẤT cực kỳ thông minh: Nhấp đúp chuột để mở giao diện đồ họa Desktop PyQt6; Kéo thả file/thư mục để chạy CLI tự động; Gõ lệnh kèm cờ trong Terminal.
- [x] **`logs/`**: Thư mục lưu trữ nhật ký xoay vòng theo ngày và tự động bắt lỗi ngoại lệ (`crash.log`).
- [x] **`README.md`**: Tài liệu hướng dẫn sử dụng chi tiết cho cả 2 chế độ GUI và CLI.
- [x] **Kiểm thử tự động**: 9/9 bài test đơn vị và tích hợp đều vượt qua 100%. Toàn bộ luồng dọn dẹp bộ nhớ và resume file hoạt động ổn định.
