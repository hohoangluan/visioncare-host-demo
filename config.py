import os

from dotenv import load_dotenv

# `.env` ở gốc dự án là chỗ chính (mẫu: .env.example); `models/.env` giữ lại cho
# cấu hình cũ. load_dotenv không ghi đè biến đã có, nên file nạp trước thắng.
_ROOT = os.path.dirname(__file__)
load_dotenv(os.path.join(_ROOT, ".env"))
load_dotenv(os.path.join(_ROOT, "models", ".env"))


def get(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


# Model download caches (HuggingFace/torch/PaddleX) mặc định nằm ở
# %USERPROFILE% (ổ C). Trỏ về đây (trong project, ổ D) để không ăn ổ C.
_CACHE_ROOT = get("MODEL_CACHE_DIR", os.path.join(os.path.dirname(__file__), "models", ".cache"))
os.environ.setdefault("HF_HOME", os.path.join(_CACHE_ROOT, "huggingface"))
os.environ.setdefault("TORCH_HOME", os.path.join(_CACHE_ROOT, "torch"))

STORAGE_DIR = get("STORAGE_DIR", "./storage")

# Cách trả audio về client:
#   "mp3_stream" - nén MP3 CBR 32kbps rồi stream từng mảnh (mặc định). 1/8
#                  dung lượng PCM trần — đỡ tải WiFi/MCU, MCU cần decoder MP3.
#   "pcm_stream" - stream PCM trần theo từng mảnh, phát dần được, không cần
#                  decoder ở MCU (đẩy thẳng I2S).
#   "wav"        - tổng hợp xong cả câu rồi gửi một file WAV hoàn chỉnh.
#
# "wav" bắt người dùng chờ tổng hợp xong cả bài mới nghe được tiếng đầu — với
# câu trả lời 35s audio là chờ thêm ~14s đứng im. Quá lâu, nên mặc định là
# stream, và chống ngắt quãng bằng `AUDIO_PREROLL_SECONDS` bên dưới.
RESPONSE_FORMAT = get("RESPONSE_FORMAT", "auto")

# Số giây audio server gom sẵn trước khi gửi byte đầu về MCU.
#
# Mục đích: server luôn đi trước người nghe một quãng, nên mỗi lần MCU đọc
# socket là có sẵn dữ liệu — MCU không cần ring buffer lớn, chỉ cần đọc và đẩy
# thẳng I2S. Đệm nằm ở RAM server (rẻ) thay vì RAM ESP32 (~320 KB, đắt).
#
# Chọn 2.0s: khoảng nghỉ tệ nhất giữa 2 mảnh PCM đo được là 0.81s, phần dư dành
# cho jitter WiFi. Tốn thêm rất ít thời gian chờ vì TTS sinh nhanh gấp ~2.5 lần
# tốc độ phát — gom 2s audio chỉ mất ~0.8s.
AUDIO_PREROLL_SECONDS = float(get("AUDIO_PREROLL_SECONDS", "2.0"))
# Chế độ phát âm thanh đệm ban đầu:
#   "warm_melodic" - âm thanh đệm warm_melodic.wav nén IMA ADPCM (mặc định).
#   "chime"        - tiếng chuông Sound Effect êm tai ("Bính Boong" Earcon).
#   "voice"        - câu thoại tiếng Việt ("Đã tiếp nhận yêu cầu").
AUDIO_PREROLL_MODE = get("AUDIO_PREROLL_MODE", "warm_melodic")
# Nhịp các câu trấn an ("hệ thống đang xử lý, bạn chờ một chút") trong lúc chờ.
#
# Phân biệt hai loại câu, đừng gộp: câu BÁO TIẾN ĐỘ (đã tìm được bài X, đã mở
# ứng dụng, kết quả cuối) luôn nói ngay khi có, không chịu nhịp này; nhịp dưới
# đây chỉ điều khiển câu TRẤN AN — thứ không mang thông tin mới, chỉ để người
# dùng biết máy còn sống.
#
# Giãn cách tính từ lúc ĐẨY câu ra, mà mỗi câu đọc lên mất 2-3 giây, nên giãn
# cách 4s cũ chỉ để lại ~1s im lặng giữa hai câu: nghe thành một tràng liên tục,
# nói nhiều hơn cả nội dung thật. Nghe thử thấy đúng là dồn dập.
#
# Nên: lần đầu chờ lâu hơn (phần lớn request xong trước mốc này, không nói câu
# nào), và giãn dần ra sau mỗi câu — chờ càng lâu thì càng ít cần nhắc lại.
# Với `music_play` chờ 40s: 4 câu (mốc 4s, 13s, 26s, 40s) thay vì 10 câu.
SPEECH_FIRST_NOTICE_SECONDS = float(get("SPEECH_FIRST_NOTICE_SECONDS", "4.0"))
SPEECH_NOTICE_INTERVAL_SECONDS = float(get("SPEECH_NOTICE_INTERVAL_SECONDS", "9.0"))
SPEECH_NOTICE_BACKOFF = float(get("SPEECH_NOTICE_BACKOFF", "1.4"))
SPEECH_NOTICE_MAX_INTERVAL_SECONDS = float(get("SPEECH_NOTICE_MAX_INTERVAL_SECONDS", "18.0"))

# Nhịp nhường cuối cùng trước khi cam kết nói một câu trấn an.
#
# Audio phát tuần tự, nên câu đã đẩy vào luồng là không rút lại được: kết quả
# thật về ngay sau đó vẫn phải xếp hàng chờ đọc xong câu trấn an. Một câu trấn
# an dài khoảng 2,5 giây, nên nói hụt ngay trước lúc có kết quả là bắt người
# dùng chờ thêm chừng ấy để nghe một câu đã hết tác dụng.
#
# 0,5 giây: đủ để cứu những lần kết quả về sát mốc, và đó cũng là toàn bộ giá
# phải trả khi thật sự còn phải chờ lâu.
SPEECH_NOTICE_GRACE_SECONDS = float(get("SPEECH_NOTICE_GRACE_SECONDS", "0.5"))

# Chỗ thở chèn giữa hai câu liền nhau trong cùng một luồng audio.
#
# TTS chỉ tổng hợp trong phạm vi từng câu, nên nối thẳng lại là một tràng tiếng
# liên tục. Người khiếm thị chỉ có kênh âm thanh để theo dõi: câu chào, câu trấn
# an, câu kết quả và đoạn model viết dính liền nhau thì không nghe ra ranh giới,
# và một đoạn trả lời dài thành khó bám.
#
# 0,45 giây: đủ nghe rõ là đã sang câu khác, còn dưới quãng nghỉ tự nhiên giữa
# hai câu của người nói (~0,6s) nên không thành lê thê. Câu trả lời 5 câu dài
# thêm 1,8 giây — trả giá bằng chừng đó để nghe kịp.
SPEECH_SENTENCE_PAUSE_SECONDS = float(get("SPEECH_SENTENCE_PAUSE_SECONDS", "0.45"))

# Dựng sẵn audio cho các câu cố định lúc khởi động (xem `pipeline/phrases.py`).
# Đặt "0" để tắt khi chỉ cần server lên nhanh và không quan tâm độ trễ.
TTS_PRERENDER = get("TTS_PRERENDER", "1") != "0"
PHRASE_CACHE_DIR = get("PHRASE_CACHE_DIR", os.path.join(_CACHE_ROOT, "tts_phrases"))

GEMINI_API_KEY = get("GEMINI_API_KEY", "")
GEMINI_MODEL = get("GEMINI_MODEL", "gemini-2.5-flash")
# Model riêng cho lượt có tra Google. Hạn mức grounding tính riêng theo từng
# model: đo trên cùng một key, `gemini-3.1-flash-lite` và `gemini-2.0-flash`
# trả 429 khi bật `google_search`, trong khi `gemini-2.5-flash-lite` trả lời
# đúng ngày thật. Tách ra để nhánh không tra cứu vẫn dùng model nhanh nhất.
GEMINI_SEARCH_MODEL = get("GEMINI_SEARCH_MODEL", "gemini-2.5-flash-lite")

# Model riêng cho bước phân loại ý định.
#
# Bước này nằm NỐI TIẾP giữa STT và handler: người dùng chờ hết nó trước khi
# công việc thật bắt đầu, mà nó chỉ sinh ra một cái nhãn, không sinh chữ nào để
# đọc lên. Nên chọn theo độ trễ, không theo độ thông minh.
#
# Đo trên 8 câu lệnh thật, cùng prompt, cùng schema:
#   gemini-2.5-flash        trung bình 2.63s, chậm nhất 6.85s
#   gemini-2.5-flash-lite   trung bình 1.53s, chậm nhất 1.71s
#   gemini-3.1-flash-lite   trung bình 1.50s, chậm nhất 1.77s
#
# Cả ba phân loại đúng như nhau (14/14 trên bộ câu lệnh mở rộng).
#
# LƯU Ý khi đọc bảng trên: `models/.env` đang đặt `GEMINI_MODEL` =
# `gemini-3.1-flash-lite`, nên trước khi có biến này thì bước phân loại VỐN ĐÃ
# chạy trên model đó rồi — tách ra đây không nhanh thêm được giây nào. Giá trị
# của biến này là tách rời: đổi `GEMINI_MODEL` sang model to hơn cho handler sẽ
# không kéo bước phân loại chậm theo, mà đó là bước người dùng chờ trắng vì nó
# không sinh ra chữ nào để đọc lên.
GEMINI_INTENT_MODEL = get("GEMINI_INTENT_MODEL", "gemini-3.1-flash-lite")
# Số token Gemini được phép dùng để "nghĩ" trước khi trả lời. Đặt -1 để không
# đụng tới, dùng mặc định của model; 0 để tắt hẳn.
#
# CẢNH BÁO khi chỉnh: đo trên gemini-3.1-flash-lite (ảnh không gian, prompt
# describe_space), 3 lần xen kẽ mỗi bên, tắt thinking KHÔNG nhanh hơn:
#   thinking=0     median 9.03s (8.53 - 12.32)
#   thinking=1024  median 9.45s (6.53 - 9.81)
# Hai dải chồng nhau. Thời gian chờ ở bước này do mạng và tải phía Google
# quyết định (cùng lệnh gọi đó dao động 2.7s tới 12.3s trong một buổi), không
# do thinking. Đừng kết luận từ một lần đo đơn lẻ — nhiễu lớn hơn hiệu ứng.
GEMINI_THINKING_BUDGET = int(get("GEMINI_THINKING_BUDGET", "-1"))
# Số lượt hỏi-đáp gần nhất được nhắc lại cho Gemini ở intent `chat`, để câu
# tiếp theo ("còn cái kia thì sao?") vẫn hiểu được bối cảnh. Giữ nhỏ: mỗi lượt
# thêm vào prompt là thêm token phải gửi lại ở MỌI lượt sau.
CHAT_HISTORY_TURNS = int(get("CHAT_HISTORY_TURNS", "6"))
# Quá ngần này giây không nói gì thì coi như cuộc trò chuyện mới, xoá lịch sử.
CHAT_HISTORY_TTL_SECONDS = float(get("CHAT_HISTORY_TTL_SECONDS", "600"))
# Ngưỡng lọc ảnh đầu vào (xem pipeline/image_quality.py để biết cách đo và vì
# sao chỉ bắt outlier cực đoan). Chỉnh qua env nếu có thêm dữ liệu thật để
# calibrate lại — ngưỡng gốc dựa trên 62 ảnh camera hiện tại, chưa nhiều.
IMAGE_MIN_SHARPNESS = float(get("IMAGE_MIN_SHARPNESS", "5"))
IMAGE_MIN_BRIGHTNESS = float(get("IMAGE_MIN_BRIGHTNESS", "30"))
IMAGE_MAX_BRIGHTNESS = float(get("IMAGE_MAX_BRIGHTNESS", "235"))
# Thư mục chứa Zipformer-vi 30M RNN-T int8 cho sherpa-onnx (encoder/decoder/
# joiner/tokens.txt). Tải từ release `asr-models` của k2-fsa/sherpa-onnx:
# sherpa-onnx-zipformer-vi-30M-int8-2026-02-09.tar.bz2
STT_MODEL_DIR = get("STT_MODEL_DIR", "./models/stt")
# Số luồng CPU cho STT.
#
# Đo trên 8 câu lệnh thật (~1.1-2.0s audio mỗi câu, 5 lần/câu):
#   threads=1   median 44.9ms   chậm nhất 52.4ms
#   threads=2   median 33.5ms   chậm nhất 40.3ms
#   threads=4   median 33.5ms   chậm nhất 41.6ms
#   threads=8   median 57.1ms   chậm nhất 99.8ms
#
# Chọn 2: hết phần lợi của việc thêm luồng (4 không nhanh hơn), mà vẫn để lõi
# trống cho TTS và các lệnh gọi Gemini chạy song song trong cùng một request.
# Thêm nữa còn phản tác dụng — 8 luồng chậm hơn cả 1 luồng vì tranh nhau lõi.
STT_NUM_THREADS = int(get("STT_NUM_THREADS", "2"))

# ── Phân loại ý định chạy cục bộ (SetFit + ONNX int8) ────────────────────
#
# Đứng TRƯỚC Gemini chứ không thay Gemini: câu nào đủ chắc thì xong trong ~8ms,
# câu nào không chắc thì vẫn rơi xuống Gemini. Dựng model bằng
# `tools/train_intent_setfit.py`; chưa có model thì mọi câu đi đường Gemini.
INTENT_LOCAL_ENABLED = get("INTENT_LOCAL_ENABLED", "1") != "0"
INTENT_LOCAL_DIR = get("INTENT_LOCAL_DIR", "./models/intent_encoder")
INTENT_LOCAL_NUM_THREADS = int(get("INTENT_LOCAL_NUM_THREADS", "2"))

# Hai ngưỡng, đo trên tập eval 236 câu (bảng đầy đủ trong README):
#   conf>=0.50 biên>=0.15  nhận 98.3%  đúng 94.8%  (12 câu sai mà vẫn nhận)
#   conf>=0.70 biên>=0.35  nhận 95.8%  đúng 96.0%  ( 9 câu)
#   conf>=0.80 biên>=0.50  nhận 93.2%  đúng 96.4%  ( 8 câu)
#   conf>=0.90 biên>=0.70  nhận 14.0%  đúng 100%   ( 0 câu)
#
# Chọn 0.80/0.50: điểm cuối cùng trước cái vực giữa 0.80 và 0.90 (93.2% rơi
# thẳng xuống 14.0%), nên siết thêm một nấc là mất gần hết phần lợi về tốc độ.
#
# Cần CẢ HAI, không phải một. Xác suất cao vẫn có thể là "hai nhãn cùng cao" —
# đúng tình huống `nav_stop` tranh với `music_stop`. Biên hẹp nghĩa là model
# đang lưỡng lự, và đó là lúc phải hỏi Gemini chứ không phải lấy cái nhỉnh hơn.
INTENT_LOCAL_MIN_CONF = float(get("INTENT_LOCAL_MIN_CONF", "0.50"))
INTENT_LOCAL_MIN_MARGIN = float(get("INTENT_LOCAL_MIN_MARGIN", "0.15"))

# Ngưỡng riêng cho các head THAM SỐ (chat needs_location/needs_web,
# music_volume direction, ride_confirm confirm). Chúng là bài nhị phân nên xác
# suất trải khác hẳn head 16 nhãn — dùng chung ngưỡng là sai loại bài.
#
# Không chắc thì rơi xuống Gemini y như hôm nay, nên đặt chặt không gây hại gì
# ngoài việc mất phần lợi tốc độ. Đặt lỏng mới nguy: đọc sai `needs_web` là
# Gemini trả lời thời tiết bằng thứ nó tự bịa.
INTENT_LOCAL_PARAM_MIN_CONF = float(get("INTENT_LOCAL_PARAM_MIN_CONF", "0.75"))
TTS_VOICE = get("TTS_VOICE", "Ngọc Linh")
TTS_STYLE = get("TTS_STYLE", "tu_nhien")

# VisionCare Host API configuration (app server running on localhost:8001)
VISIONCARE_HOST_URL = get("VISIONCARE_HOST_URL", "http://127.0.0.1:8001")
VISIONCARE_CLIENT_TOKEN = get("VISIONCARE_CLIENT_TOKEN", "")
VISIONCARE_DEVICE_ID = get("VISIONCARE_DEVICE_ID", "glasses-123")

# Số giây chờ kết quả thật của một action sau khi host trả `202 Accepted`.
#
# `202` chỉ nghĩa là host đã nhận lệnh, chưa nói điện thoại làm được hay không.
# Không chờ thì người khiếm thị chỉ nghe "đã gửi yêu cầu" rồi im — không biết
# cuộc gọi có đổ chuông không, nhạc có phát không.
#
# Chọn 25s: dài hơn thời gian điện thoại cần để mở app đích và người dùng bấm
# vào thông báo, nhưng vẫn ngắn hơn deadline phía host (`contact_call` 60s,
# `music_play` 45s) nên câu trả lời không bị treo tới lúc host tự `timed_out`.
VISIONCARE_RESULT_TIMEOUT_SECONDS = float(get("VISIONCARE_RESULT_TIMEOUT_SECONDS", "25"))
# Nhịp hỏi host xem action xong chưa.
#
# Đây là độ trễ giữa lúc điện thoại thật sự xong và lúc người dùng nghe được
# kết quả — nội dung có giá trị nhất trong cả lượt, nên không để nó nằm chờ một
# cái đồng hồ. Đo thật trên 6 mốc hoàn thành khác nhau:
#
#   poll=1.00s  trễ trung bình 0.66s, tối đa 0.95s   (25 lần gọi trong 25s)
#   poll=0.50s  trễ trung bình 0.33s, tối đa 0.46s   (50 lần)
#   poll=0.25s  trễ trung bình 0.21s, tối đa 0.21s   (100 lần)
#
# Chọn 0.50: nửa độ trễ so với 1.0 mà chỉ thêm 25 lần gọi tới host chạy cùng
# máy. Xuống 0.25 chỉ mua thêm 0.12s nữa mà gấp đôi số lần gọi.
VISIONCARE_RESULT_POLL_SECONDS = float(get("VISIONCARE_RESULT_POLL_SECONDS", "0.5"))

# `music_play` chờ lâu hơn: điện thoại tự cho ứng dụng nhạc tới 35s để thật sự
# ra tiếng trước khi kết luận. Chờ ít hơn ngần ấy thì server kính luôn nói
# "điện thoại chưa phản hồi" và nuốt mất lý do thật máy đã báo về. Vẫn dưới
# deadline 45s của host cho action này.
VISIONCARE_MUSIC_RESULT_TIMEOUT_SECONDS = float(
    get("VISIONCARE_MUSIC_RESULT_TIMEOUT_SECONDS", "40")
)
VISIONCARE_FAST_ACTION_SECONDS = float(get("VISIONCARE_FAST_ACTION_SECONDS", "2.0"))
VISIONCARE_CALLBACK_TOKEN = get("VISIONCARE_CALLBACK_TOKEN", "")
# Mạng được phép gọi `/internal/action-results`. Mặc định chỉ loopback (chạy cả
# hai server trên cùng máy). Chạy Docker thì backend nằm ở container khác nên
# phải liệt kê dải mạng của Docker (xem docker-compose.yml); vẫn cần bearer token.
CALLBACK_ALLOWED_NETWORKS = tuple(
    n.strip() for n in get("CALLBACK_ALLOWED_NETWORKS", "127.0.0.0/8,::1/128").split(",") if n.strip()
)

CHAT_LOCATION_REFRESH_SECONDS = float(get("CHAT_LOCATION_REFRESH_SECONDS", "240.0"))
CHAT_LOCATION_MAX_FIX_AGE_SECONDS = float(get("CHAT_LOCATION_MAX_FIX_AGE_SECONDS", "600.0"))
CHAT_LOCATION_TTL_SECONDS = float(get("CHAT_LOCATION_TTL_SECONDS", "600.0"))
CHAT_ALWAYS_SEARCH = get("CHAT_ALWAYS_SEARCH", "1") != "0"



# ── Voice server v2 (docs/superpowers/specs/2026-10-19-voice-server-architecture-design.md) ──

# Gemma 4 26B-A4B qua API tương thích OpenAI (UIT). Đường LAN 192.168.20.150:8899
# đã bỏ: 2026-10-19 nó nhận TCP rồi trả "Empty reply" ở mọi đường dẫn. Vẫn nhận
# danh sách nhiều URL (cách nhau dấu phẩy): khởi động đo cả hai, dùng đường nhanh
# nhất, lỗi giữa chừng thì chuyển đường kế tiếp.
LLM_BASE_URLS = tuple(
    u.strip().rstrip("/") for u in get(
        "LLM_BASE_URLS", get("AGENT_BASE_URL", "https://llm.uit.edu.vn/gemma/v1"),
    ).split(",") if u.strip()
)
LLM_API_KEY = get("LLM_API_KEY", get("AGENT_API_KEY", ""))
LLM_MODEL = get("LLM_MODEL", get("AGENT_MODEL", "gemma-4-26b"))
# llm.uit.edu.vn cần thêm cross-sign Sectigo E46 (docs/LLM_PROVIDER.md).
LLM_CA_BUNDLE = get("LLM_CA_BUNDLE", os.path.join(_ROOT, "certs", "uit-ca-bundle.pem"))
# Bắt tay TCP tới một host chết phải hỏng NHANH để kịp chuyển đường dự phòng.
LLM_CONNECT_TIMEOUT_S = float(get("LLM_CONNECT_TIMEOUT_S", "0.5"))
LLM_TIMEOUT_S = float(get("LLM_TIMEOUT_S", "30"))
LLM_MAX_TOKENS = int(get("LLM_MAX_TOKENS", "400"))
# Cạnh dài ảnh gửi cho Gemma. Ảnh UXGA 1600px gửi nguyên là nhiều token ảnh hơn
# và upload lâu hơn mà Gemma vẫn thu về độ phân giải nội bộ của nó.
LLM_IMAGE_MAX_SIDE = int(get("LLM_IMAGE_MAX_SIDE", "896"))
# OCR cần giữ chi tiết chữ nhỏ nên ảnh chụp high-res gửi lớn hơn.
LLM_OCR_IMAGE_MAX_SIDE = int(get("LLM_OCR_IMAGE_MAX_SIDE", "1600"))

# Clef (Cloudflare Workers AI) — phân loại intent cuối và trên partial.
CLOUDFLARE_API_TOKEN = get("CLOUDFLARE_API_TOKEN", "")
CLOUDFLARE_ACCOUNT_ID = get("CLOUDFLARE_ACCOUNT_ID", "")
CLEF_MODEL = get("CLEF_MODEL", "clef-flash")
CLEF_MODEL_ID = get("CLEF_MODEL_ID", "@cf/cloudflare/clef-flash")
CLEF_TIMEOUT_S = float(get("CLEF_TIMEOUT_S", "1"))
# Dưới ngưỡng này nhãn Clef coi như không chắc -> dùng luật từ khoá nếu khớp.
CLEF_MIN_CONFIDENCE = float(get("CLEF_MIN_CONFIDENCE", "0.15"))

# Google Programmable Search cho làn A. Trống key thì Gemma trả lời thẳng.
GOOGLE_SEARCH_API_KEY = get("GOOGLE_SEARCH_API_KEY", "")
GOOGLE_SEARCH_CX = get("GOOGLE_SEARCH_CX", "")
SEARCH_TIMEOUT_S = float(get("SEARCH_TIMEOUT_S", "3"))

# Image Buffer (§6): ảnh chỉ nằm trong RAM, hạn 30 s.
IMAGE_BUFFER_TTL_S = float(get("IMAGE_BUFFER_TTL_S", "30"))
# Âm thanh tới trước ảnh (kính không mở được 2 kết nối): chờ ảnh tối đa ngần này
# trước khi coi như không có ảnh.
IMAGE_WAIT_S = float(get("IMAGE_WAIT_S", "1.5"))

# Pseudo-streaming STT (§7.1): giải lại cả buffer mỗi ngần này giây.
STT_PARTIAL_INTERVAL_S = float(get("STT_PARTIAL_INTERVAL_S", "0.3"))
# Early intent (§7.2): Clef trên partial khi đủ từ và đã đứng yên ngần này giây.
EARLY_CLASSIFY_MIN_WORDS = int(get("EARLY_CLASSIFY_MIN_WORDS", "3"))
EARLY_CLASSIFY_STABLE_S = float(get("EARLY_CLASSIFY_STABLE_S", "0.3"))
EARLY_CLASSIFY_MAX_CALLS = int(get("EARLY_CLASSIFY_MAX_CALLS", "2"))
# Sau bản ghi cuối, chạy SONG SONG với Clef cuối những việc không có tác dụng
# phụ (Gemma sinh câu trả lời làn A, Gemma trích tham số làn D) theo nhãn đoán
# sớm. Clef xác nhận thì dùng luôn, khác nhãn thì huỷ. Không phát tiếng, không
# gửi lệnh điện thoại nào trước khi có nhãn cuối (§1 nguyên tắc 3).
SPECULATIVE_FINAL = get("SPECULATIVE_FINAL", "1") != "0"

# Đệm audio trước byte đầu cho /v2/turn. Đo 2026-10-19 (TTS GPU, RTF 0,76),
# `tools/bench_live.py` cột `starve`, 15 lượt với đệm 0: loa đói tối đa 177 ms
# (localhost). Mỗi 0,1 s đệm là ~0,08 s chờ thêm trước tiếng đầu; người dùng
# chọn 0,2 s (ưu tiên tốc độ). Đo lại cột `starve` trên đường WiFi/Cloudflare thật.
V2_AUDIO_PREROLL_SECONDS = float(get("V2_AUDIO_PREROLL_SECONDS", "0.2"))
# Biên thêm sau khi đọc lại lệnh làn D xong, trước khi thi hành (pending_action).
ACTION_READBACK_MARGIN_S = float(get("ACTION_READBACK_MARGIN_S", "0.15"))
# Câu TTS đầu của làn A cắt ở ngần này từ để tiếng ra sớm (§9).
FIRST_SENTENCE_MAX_WORDS = int(get("FIRST_SENTENCE_MAX_WORDS", "8"))

# WebSocket realtime (§5.3).
LIVE_TOKEN_TTL_S = float(get("LIVE_TOKEN_TTL_S", "10"))
OCR_ALIGN_TIMEOUT_S = float(get("OCR_ALIGN_TIMEOUT_S", "20"))
OCR_CUE_MIN_GAP_S = float(get("OCR_CUE_MIN_GAP_S", "1.5"))
OCR_LOOK_AROUND_GAP_S = float(get("OCR_LOOK_AROUND_GAP_S", "3"))
OCR_GOOD_FRAMES = int(get("OCR_GOOD_FRAMES", "3"))
# Chiều cao dòng tối thiểu tính trên ảnh UXGA (spec OCR: ~28 px/dòng).
OCR_MIN_LINE_PX = float(get("OCR_MIN_LINE_PX", "28"))
OCR_CAPTURE_WIDTH = int(get("OCR_CAPTURE_WIDTH", "1600"))
# Ảnh buffer UXGA đã đạt chuẩn căn khung thì đọc luôn, khỏi mở WebSocket.
OCR_ACCEPT_BUFFER = get("OCR_ACCEPT_BUFFER", "1") != "0"
LAST_TEXT_TTL_S = float(get("LAST_TEXT_TTL_S", "300"))
# "auto" = PP-OCR det (ONNX, `TEXT_DET_MODEL_PATH`) nếu có file, không thì bộ dò hình thái OpenCV.
TEXT_DETECTOR = get("TEXT_DETECTOR", "auto")

# Hazard (§11). File ONNX YOLO; trống/thiếu file thì làn C không có detector.
HAZARD_MODEL_PATH = get("HAZARD_MODEL_PATH", os.path.join(_ROOT, "models", "hazard", "yolo11n.onnx"))
HAZARD_IMGSZ = int(get("HAZARD_IMGSZ", "320"))
HAZARD_MIN_SCORE = float(get("HAZARD_MIN_SCORE", "0.35"))
HAZARD_NUM_THREADS = int(get("HAZARD_NUM_THREADS", "4"))
HAZARD_REPEAT_S = float(get("HAZARD_REPEAT_S", "2"))
HAZARD_LEVEL1_GAP_S = float(get("HAZARD_LEVEL1_GAP_S", "5"))
# Tắt bước warm mạng/detector lúc khởi động (test đặt 0).
V2_WARM = get("V2_WARM", "1") != "0"
# Model ONNX của server (hazard, text detector): "auto" = CUDA nếu có, "cpu", "cuda".
ONNX_DEVICE = get("ONNX_DEVICE", "auto")
ONNX_GPU_ID = int(get("ONNX_GPU_ID", "0"))
TEXT_DET_MODEL_PATH = get(
    "TEXT_DET_MODEL_PATH", os.path.join(_ROOT, "models", "text_det", "ch_PP-OCRv4_det_infer.onnx")
)
# TTS: "auto" = CUDA (PyTorch) nếu có GPU, không thì ONNX/CPU. Số đo trong pipeline/tts.py.
TTS_DEVICE = get("TTS_DEVICE", "auto")
# Spec §7.2: bỏ lượt Clef trên partial nếu còn lượt đang chạy. 0 = vẫn gọi (thử nghiệm độ trễ).
EARLY_CLASSIFY_SKIP_INFLIGHT = get("EARLY_CLASSIFY_SKIP_INFLIGHT", "1") != "0"
# Bộ phân loại intent (`pipeline/intent_classifier.py`): "auto" = Gemma rồi Clef
# dự phòng, "gemma", "clef". Số đo so sánh nằm trong module đó.
INTENT_BACKEND = get("INTENT_BACKEND", "auto")
INTENT_LLM_TIMEOUT_S = float(get("INTENT_LLM_TIMEOUT_S", "0.8"))
# Trần chờ intent cuối (cả lượt dự phòng); quá trần thì luật từ khoá / làn chat.
INTENT_DECIDE_TIMEOUT_S = float(get("INTENT_DECIDE_TIMEOUT_S", "1.5"))
