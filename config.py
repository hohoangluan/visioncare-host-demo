import os

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "models", ".env"))


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
RESPONSE_FORMAT = get("RESPONSE_FORMAT", "mp3_stream")

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

# VisionCare Host API configuration
VISIONCARE_HOST_URL = get("VISIONCARE_HOST_URL", "https://app.visioncare-host.uk")
VISIONCARE_CLIENT_TOKEN = get("VISIONCARE_CLIENT_TOKEN", "demo-client-token")
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

