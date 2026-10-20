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
# Không đặt HF_HUB_OFFLINE ở đây: lần chạy đầu vieneu phải tải model/voices từ
# huggingface.co. Khi models/.cache/huggingface đã đủ file, đặt HF_HUB_OFFLINE=1 trong
# môi trường (hoặc .env) để vieneu khỏi gọi HEAD lên mạng mỗi lần nạp (chậm lúc khởi
# động và hỏng nếu mạng chập chờn). Đặt trước khi import vieneu, nên để ở .env/shell.

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

# Giải mã STT: beam search + hotword lệnh (contextual biasing của sherpa-onnx), cùng model Zipformer.
# Đo 2026-10-20 trên bàn đo câu lệnh (tools/bench_stt_cmd.py + bench_stt_report.py: 408 câu gold dev/test +
# lệnh bổ sung x 3 giọng TTS x {sạch, SNR10+ADPCM}; 2.400 clip) so với greedy cũ, mỗi lần đổi một biến:
#   cấu hình           đúng-lệnh dev-s/dev-n/test-s/test-n   intent                     WER VietMed  p90 lượt cuối
#   greedy             80,5/78,2/84,2/81,1                   87,6/83,9/87,4/87,2        14,73        ~88 ms
#   beam4 (không hw)   80,5/78,5/83,8/82,5                   87,6/83,9/87,4/87,6        14,36        ~110 ms (hoà, p=0,42)
#   hotword 2.0, 4 đường   82,1/79,7/86,3/86,3               88,0/84,8/88,0/88,2        14,36        112 ms (+24)
#   + tên người thân   84,1/82,1/88,0/88,0                   88,0/84,8/88,0/88,2        14,36        113 ms (+25)  <- chọn
# Câu bất đồng (cộng 4 ô): từ khoá lệnh +64/-4, intent +33/-16 (p=0,021), WER VietMed 17 clip tốt/7 tệ.
# Hotword điểm 1,0 yếu, 3,0 thêm 2 câu chat bị chèn lệnh, 5,0 phá WER (+1,3 điểm) và chèn 13 câu chat.
# Model khác đều thua: ChunkFormer-large (WER VietMed 17,98), Zipformer-vi 70M (16,2), Omnilingual 300M và
# Moonshine-vi (trễ ~1000 và ~400 ms). Chi tiết: .superpowers/sdd/2026-10-19-glasses-calls-messages/stt-opt-report.md
# `greedy_search` để quay lại cách cũ (hotword chỉ có tác dụng với modified_beam_search).
STT_DECODING = get("STT_DECODING", "modified_beam_search")
STT_BEAM_PATHS = int(get("STT_BEAM_PATHS", "4"))
STT_HOTWORDS_SCORE = float(get("STT_HOTWORDS_SCORE", "2.0"))
# Bật danh sách từ lệnh cố định (pipeline.stt.COMMAND_HOTWORDS), hoặc tệp riêng mỗi dòng một cụm CHỮ HOA.
STT_HOTWORDS = get("STT_HOTWORDS", "1") != "0"
STT_HOTWORDS_FILE = get("STT_HOTWORDS_FILE", "")
# Hotword theo người dùng (tên người thân từ care_links, `stt.set_user_hotwords`): tên đúng 90-92% -> 97-98%.
STT_USER_HOTWORDS = get("STT_USER_HOTWORDS", "1") != "0"

TTS_VOICE = get("TTS_VOICE", "Ngọc Linh")
TTS_STYLE = get("TTS_STYLE", "tu_nhien")

# VisionCare Host API configuration (app server running on localhost:8001)
VISIONCARE_HOST_URL = get("VISIONCARE_HOST_URL", "http://127.0.0.1:8001")
VISIONCARE_CLIENT_TOKEN = get("VISIONCARE_CLIENT_TOKEN", "")
VISIONCARE_DEVICE_ID = get("VISIONCARE_DEVICE_ID", "glasses-123")
# `user_id` (public_user_id) chủ kính, gửi AB ở các lệnh gọi/nhắn/khẩn cấp (AB kiểm kính có gắn user này không).
# Các lệnh làn D cũ chỉ gửi device_id nên VH chưa từng biết user; demo ghép glasses-123 -> user-100. Rỗng = chưa cấu hình.
VISIONCARE_USER_ID = get("VISIONCARE_USER_ID", "")

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
# Bảo vệ endpoint kính (Task 9): trần kích thước + rate limit qua tunnel công khai.
# Token kính nằm ở VISIONCARE_DEVICE_CLIENT_TOKEN (rỗng = mọi endpoint kính trả 503).
VISIONCARE_DEVICE_CLIENT_TOKEN = get("VISIONCARE_DEVICE_CLIENT_TOKEN", "")
# Token theo từng kính (Plan 2 / C0): đường dẫn file JSON `{"<device_id>": "<sha256 hex của token>"}`
# (git-ignored; sinh bằng `tools/device_token.py add <device_id>`). Rỗng = không có token riêng.
# Đường dẫn tương đối tính từ gốc dự án.
VISIONCARE_DEVICE_TOKENS = get("VISIONCARE_DEVICE_TOKENS", "")
# 1 (mặc định) = token dùng chung cũ vẫn được chấp nhận để không gãy kính/demo đang chạy; phiên đó
# `per_device=False` nên KHÔNG được gọi điện/nhắn tin/khẩn cấp. 0 = chỉ token riêng.
VISIONCARE_ALLOW_SHARED_DEVICE_TOKEN = get("VISIONCARE_ALLOW_SHARED_DEVICE_TOKEN", "1") == "1"
DEVICE_MAX_IMAGE_BYTES = int(get("DEVICE_MAX_IMAGE_BYTES", "2000000"))
DEVICE_MAX_AUDIO_S = float(get("DEVICE_MAX_AUDIO_S", "30"))
# Trần cả body /process (multipart ảnh+audio): ảnh + audio PCM16 16 kHz mono tối đa
# DEVICE_MAX_AUDIO_S + 64 KB dư cho biên multipart/header WAV. Kiểm TRƯỚC khi parse.
DEVICE_MAX_PROCESS_BYTES = int(get(
    "DEVICE_MAX_PROCESS_BYTES",
    str(DEVICE_MAX_IMAGE_BYTES + int(DEVICE_MAX_AUDIO_S * 32000) + 65536)))
# Trần MỘT khung WS của kính (ảnh lượt + tiêu đề). Khớp `uvicorn --ws-max-size 2100000` (mặc định 16 MB là
# bộ nhớ chưa xác thực mỗi socket); `device_session` cũng tự bỏ khung vượt trần này.
WS_MAX_FRAME_BYTES = DEVICE_MAX_IMAGE_BYTES + 65536
LIVE_MAX_FRAME_BYTES = int(get("LIVE_MAX_FRAME_BYTES", "300000"))
DEVICE_TURNS_PER_MIN = float(get("DEVICE_TURNS_PER_MIN", "30"))
DEVICE_IMAGES_PER_MIN = float(get("DEVICE_IMAGES_PER_MIN", "40"))
LIVE_MAX_FPS = float(get("LIVE_MAX_FPS", "15"))
CLEF_MODEL = get("CLEF_MODEL", "clef-flash")
CLEF_MODEL_ID = get("CLEF_MODEL_ID", "@cf/cloudflare/clef-flash")
CLEF_TIMEOUT_S = float(get("CLEF_TIMEOUT_S", "1"))
# Dưới ngưỡng này nhãn Clef coi như không chắc -> dùng luật từ khoá nếu khớp.
CLEF_MIN_CONFIDENCE = float(get("CLEF_MIN_CONFIDENCE", "0.15"))

# SerpAPI cho làn A. Trống key (hoặc tra hỏng) thì Gemma nói thẳng là chưa tra được.
SERPAPI_API_KEY = get("SERPAPI_API_KEY", "")
# Trần cứng: quá hạn là bỏ, không để làn A kẹt cả lượt.
SEARCH_TIMEOUT_S = float(get("SEARCH_TIMEOUT_S", "2.5"))
# Phát "Để tôi tra cứu." ngay trong lúc chờ SerpAPI (chưa đo trên bench_live: chưa có khoá).
SEARCH_FILLER = get("SEARCH_FILLER", "1") != "0"

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

# VAD Silero (pipeline/vad.py, Task 2b): cắt im lặng, chốt sớm khi hết câu, no_speech
# ngay khi cả lượt không có tiếng. Tắt: VAD_ENABLED=0.
VAD_ENABLED = get("VAD_ENABLED", "1") != "0"
VAD_MODEL_PATH = get("VAD_MODEL_PATH", "./models/vad/silero_vad.onnx")
VAD_END_SILENCE_S = float(get("VAD_END_SILENCE_S", "0.35"))
VAD_THRESHOLD = float(get("VAD_THRESHOLD", "0.5"))
VAD_PAD_S = float(get("VAD_PAD_S", "0.2"))  # đệm hai đầu đoạn tiếng, tránh cắt phụ âm
VAD_EARLY_FINAL = get("VAD_EARLY_FINAL", "1") != "0"

# Đệm audio trước byte đầu cho /v2/turn. Đo 2026-10-19 (TTS GPU, RTF 0,76),
# `tools/bench_live.py` cột `starve`, 15 lượt với đệm 0: loa đói tối đa 177 ms
# (localhost). Mỗi 0,1 s đệm là ~0,08 s chờ thêm trước tiếng đầu; người dùng
# chọn 0,2 s (ưu tiên tốc độ). Đo lại cột `starve` trên đường WiFi/Cloudflare thật.
V2_AUDIO_PREROLL_SECONDS = float(get("V2_AUDIO_PREROLL_SECONDS", "0.2"))
# Biên thêm sau khi đọc lại lệnh làn D xong, trước khi thi hành (pending_action).
ACTION_READBACK_MARGIN_S = float(get("ACTION_READBACK_MARGIN_S", "0.15"))
# Từ lúc router trả lời tới lúc tiếng đọc lại thật sự ra loa (TTS câu đầu); cộng vào
# đồng hồ chờ để cửa sổ huỷ không bị TTS ăn mất.
ACTION_TTS_LEAD_S = float(get("ACTION_TTS_LEAD_S", "0.4"))
# Làn D chỉ chạy khi Gemma gán nhãn với độ tin cậy >= ngưỡng này; dưới ngưỡng thì
# hỏi lại. Đo 2026-10-19 (Task 4): 0,999 là ngưỡng nhỏ nhất cho action_fp = 0 trên gold_dev
# (ask_rate 9,1%) và gold_test (FP 0, ask 5%); 0,85 còn FP 1. Lưu ý: dev chỉ có MỘT
# FP (câu STT méo, conf 0,9987) quyết định ngưỡng — khớp một điểm, không phải biên chắc.
# Quét lại 2026-10-19 (Task 4d, dev, 5 lượt, định dạng nhãn): ở 0,998 còn FP 1 trong 2/5 lượt,
# ở 0,99-0,995 cũng 2/5 (ask_rate 2-7%); chỉ 0,999 cho FP 0 cả 5 lượt (ask 7-11%) -> giữ 0,999.
ACTION_MIN_CONFIDENCE = float(get("ACTION_MIN_CONFIDENCE", "0.999"))
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
# Mức thấp nhất được gửi cho kính. 2 = bỏ mức 1 (vật xa/ngoài lối đi) cho đỡ ồn; 1 = gửi cả mức 1.
HAZARD_MIN_LEVEL = int(get("HAZARD_MIN_LEVEL", "2"))
# Bật GET /v2/debug/stats (số request Gemma đang bay/đỉnh/tổng) cho tools/bench_load.py. Mặc định tắt:
# endpoint không tồn tại (404) khi cờ này không phải "1".
V2_DEBUG_STATS = get("V2_DEBUG_STATS", "") == "1"
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
# Định dạng đầu ra của Gemma: "choice" (nhãn ngắn, Task 4c) hoặc "json" (ba trường, bản cũ).
INTENT_FORMAT = get("INTENT_FORMAT", "choice")
# Ai quyết `ocr_mode` / `needs_web` khi INTENT_FORMAT=choice (Task 4d): "rules" = luật từ khoá
# trong `intent_early` (0 ms), "gemma" = lượt nhãn phụ (+~45 ms cho chat/ocr; quay về bản cũ).
# Đo 2026-10-19 gold_dev, xen kẽ x2: chat p50 120 -> 60 ms, ocr 125 -> 61 ms, p90 chung 128 -> 81;
# needs_web đúng 19/29 -> 28/29 (luật khớp dev, test 13 -> 14/19), ocr_mode 8/9 -> 9/9.
INTENT_AUX = get("INTENT_AUX", "rules")
INTENT_LLM_TIMEOUT_S = float(get("INTENT_LLM_TIMEOUT_S", "0.8"))
# Trần chờ intent cuối (cả lượt dự phòng); quá trần thì luật từ khoá / làn chat.
INTENT_DECIDE_TIMEOUT_S = float(get("INTENT_DECIDE_TIMEOUT_S", "1.5"))

# ── Gọi điện qua kính (docs/superpowers/specs/2026-10-19-glasses-calls-messages-design.md, §5.3) ──
# Chuông tối đa (AB cũng dùng số này để đánh `missed`); hạn token media = chuông + CALL_TOKEN_GRACE_S.
CALL_RING_TIMEOUT_S = float(get("CALL_RING_TIMEOUT_S", "30"))
CALL_TOKEN_GRACE_S = float(get("CALL_TOKEN_GRACE_S", "10"))
# Sau `active`, app phải mở `WS /v2/call` trong ngần này giây, không thì cúp (`media_timeout`).
CALL_MEDIA_WAIT_S = float(get("CALL_MEDIA_WAIT_S", "15"))
# Đệm chống giật đầu app -> kính. 0 = không đệm, phát ngay khi khung tới (thấp nhất, dễ giật hơn).
CALL_JITTER_MS = int(get("CALL_JITTER_MS", "60"))
CALL_JITTER_MAX_LATE_MS = int(get("CALL_JITTER_MAX_LATE_MS", "200"))
# Dự phòng khi kính không khử vọng: đầu app đang nói (RMS > -40 dBFS trong 100 ms gần nhất) thì mic kính giảm 20 dB.
CALL_HALF_DUPLEX = get("CALL_HALF_DUPLEX", "0") == "1"
CALL_HALF_DUPLEX_THRESHOLD_DBFS = float(get("CALL_HALF_DUPLEX_THRESHOLD_DBFS", "-40"))
CALL_HALF_DUPLEX_HOLD_MS = int(get("CALL_HALF_DUPLEX_HOLD_MS", "100"))
CALL_HALF_DUPLEX_DUCK_DB = float(get("CALL_HALF_DUPLEX_DUCK_DB", "20"))
# Trần khung WS của app (PCM16 20 ms = 640 B; chừa dư cho cụm).
CALL_MAX_FRAME_BYTES = int(get("CALL_MAX_FRAME_BYTES", "16384"))
# Số token media gửi AB khi bắt đầu chuỗi khẩn cấp (mỗi lượt gọi trong chuỗi dùng một token; AB cho 1..90).
# 3 vòng x tối đa 10 người thân = 30. Hết token trước khi hết vòng thì AB kết thúc chuỗi sớm.
EMERGENCY_MEDIA_TOKENS = int(get("EMERGENCY_MEDIA_TOKENS", "30"))
