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
RESPONSE_FORMAT = get("RESPONSE_FORMAT", "auto")

# Số giây audio server gom sẵn trước khi gửi byte đầu về MCU.
#
# 🔴 ĐÃ BỎ (0.0) ngày 2026-08-24, theo quyết định của người dùng. Giữ lại biến
# để bật lại được bằng biến môi trường nếu board thật hụt tiếng.
#
# Ý định gốc vẫn đúng về nguyên tắc: server đi trước người nghe một quãng thì
# MCU cứ đọc socket là có dữ liệu. Nhưng 2.0s **mâu thuẫn trực tiếp với bảng
# ngân sách G1**: gom 2000 ms trước byte đầu nghĩa là mọi dòng ≤ 1200 ms của
# bảng đó KHÔNG THỂ đạt, kể cả khi xử lý mất 0 ms. Không thể cùng giữ cả hai.
#
# Ba thứ đã che giấu mâu thuẫn này cho tới khi T21 dựng bảng ngân sách:
#   - câu mở đầu dựng sẵn chỉ dài 0.94s, ngắn hơn mức đệm, nên nó bị GIỮ LẠI
#     và vòng lặp chặn chờ mảnh kế tiếp — tức chờ trọn STT + Gemini;
#   - đo được: trung vị tiếng đầu 3.68s, `emergency_call` 4.82s/ngân sách 300ms;
#   - không ai có bảng ngân sách để đối chiếu nên không ai thấy.
#
# Đường lui nếu board hụt tiếng: `AUDIO_PREROLL_SECONDS=0.5` (biến môi
# trường). Board còn hai lớp đệm riêng của nó — chọn mức 400ms/1500ms theo tỉ
# lệ nhả, và `BODY_GAP_MS = 30000` cho phép khoảng lặng dài giữa hai câu.
AUDIO_PREROLL_SECONDS = float(get("AUDIO_PREROLL_SECONDS", "0.0"))
# Chế độ phát âm thanh đệm ban đầu:
#   "warm_melodic" - âm thanh đệm warm_melodic.wav nén IMA ADPCM (MẶC ĐỊNH).
#   "chime"        - tiếng chuông Sound Effect êm tai ("Bính Boong" Earcon).
#   "voice"        - câu thoại tiếng Việt ("Đã tiếp nhận yêu cầu").
#
# 🔴 ĐỪNG ĐỔI SANG "voice". Đã thử và đã bị bác, 2026-08-24.
#
# Lý do bác là TRẢI NGHIỆM, không phải kỹ thuật, nên không có số đo nào phản
# bác lại được: **người dùng bấm nút liên tục cả ngày.** Nghe trọn câu "Đã
# tiếp nhận yêu cầu" ở đầu MỖI lượt là tra tấn — đúng thứ làm người ta bỏ
# thiết bị. Một tiếng ngắn không lời thì nghe cả trăm lần vẫn chịu được.
#
# Lập luận đã dùng để đổi, và vì sao nó KHÔNG thắng:
#   - "câu nói dài 1.68 s so với chuông 0.94 s nên lấp được nhiều khoảng chờ
#     hơn" — đúng về số, nhưng nó tối ưu ĐỒNG HỒ chứ không tối ưu người nghe.
#   - "G8 cấm earcon phía server" — G8 sinh ra để chặn việc THÊM một tiếng báo
#     trùng với `cueSent()` của board. Đoạn đệm này còn gánh việc thứ hai có
#     thật (lấp `AUDIO_PREROLL_SECONDS`), và người dùng đã chọn nó. Việc còn
#     lại của G8 là cân âm lượng giữa hai bên, không phải bỏ nó đi.
#
# Muốn đổi thì phải có người dùng THẬT nghe rồi nói là được — không phải một
# bảng số.
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
# model: đo trên cùng một key, `gemini-3.1-flash-lite`, `gemini-3.5-flash-lite`
# và `gemini-2.0-flash` đều trả 429 khi bật `google_search`. Tách ra để nhánh
# không tra cứu vẫn dùng model nhanh nhất.
#
# ĐÃ ĐỔI từ `gemini-2.5-flash-lite`. Bản lite qua được vòng grounding nhưng
# KHÔNG dùng nổi lịch sử hội thoại trong prompt. Đo trên đúng prompt production,
# lịch sử có sẵn "Thủ đô của Việt Nam là Hà Nội", hỏi tiếp "Thành phố đó có bao
# nhiêu người sinh sống":
#
#   gemini-2.5-flash-lite  4207ms  "Để tôi tra cứu thông tin này."          SAI
#   gemini-2.5-flash-lite  4207ms  "Tôi chưa xác định được vị trí của bạn"  SAI
#   gemini-2.5-flash       3533ms  "Hà Nội ... khoảng 8,5 triệu người"      ĐÚNG
#
# Hai lần chạy bản lite ra hai kiểu hỏng khác nhau, không lần nào trả lời câu
# được hỏi — câu đầu tệ nhất vì người dùng nghe "để tôi tra cứu" rồi im luôn.
# Và bản lite còn CHẬM HƠN, nên đây không phải đánh đổi tốc độ lấy chất lượng.
#
# Số lượt phải trả giá grounding cũng đã giảm: head `chat_web` bỏ vòng này cho
# ~39% lượt chat (xem `INTENT_LOCAL_WEB_MIN_CONF`).
GEMINI_SEARCH_MODEL = get("GEMINI_SEARCH_MODEL", "gemini-2.5-flash")

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

# Trần thời gian cho MỘT lượt gọi Gemini. SDK `google-genai` mặc định KHÔNG có
# trần nào (`HttpOptions.timeout=None`), nghĩa là một lần treo phía Google là
# treo luôn cả lượt của người dùng.
#
# Đây không phải lo xa. Benchmark 23/08 (`DETAILED_STAGE_LATENCY_BENCHMARK.md`)
# bắt được một lượt phân loại `ocr` tốn 37977ms, trong khi phân bố của chính
# bước đó trên 36 lượt là p50 32ms / p90 1684ms. Người dùng ngồi im 38 giây cho
# một bước lẽ ra tốn dưới 2 giây.
#
# Hai trần TÁCH RIÊNG vì hai bước có hình dạng khác hẳn nhau:
#
#   phân loại (`generate_json`, không stream)  p50   32ms  p90 1684ms
#   sinh chữ  (`generate_stream`, mảnh đầu)    p50 1667ms  p90 3126ms  max 5930ms
#
# Bước phân loại không sinh ra chữ nào để đọc lên — nó là chờ trắng thuần tuý,
# nên siết chặt hết mức CÒN ĐƯỢC PHÉP. Bước sinh chữ thì câu dài stream nhiều
# giây là bình thường, siết bằng phân loại sẽ cắt nhầm câu đang chạy đúng, nên
# để rộng 30s (~5 lần lượt chậm nhất đo được).
#
# 🔴 10s là SÀN CỨNG CỦA API, không phải lựa chọn theo số đo. Chọn 8s theo p90
# rồi thử thật thì Gemini từ chối cả lượt gọi:
#     400 INVALID_ARGUMENT
#     "Manually set deadline 8s is too short. Minimum allowed deadline is 10s."
# Tức đặt dưới 10s không làm nhanh thêm mà làm HỎNG mọi lượt. Đừng "tối ưu"
# con số này xuống nữa.
#
# Hết giờ ném `VLMError`, và đó là loại lỗi các nhánh dự phòng ĐÃ bắt sẵn:
# `pipeline/intent.py::_ask_gemini` đổi thành `classify_failed`, còn
# `handlers/chat.py::_stream_with_search_fallback` trả lời lại không kèm tra
# cứu. Không có nhánh xử lý lỗi nào mới phải viết.
GEMINI_INTENT_TIMEOUT_SECONDS = float(get("GEMINI_INTENT_TIMEOUT_SECONDS", "10"))
GEMINI_TIMEOUT_SECONDS = float(get("GEMINI_TIMEOUT_SECONDS", "30"))

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

# Ngưỡng RIÊNG cho head `chat_web`, và nó cố tình khác `INTENT_LOCAL_PARAM_MIN_CONF`
# ở trên vì bài toán bất đối xứng, không phải vì head này yếu hơn.
#
# Head kia gác một THAM SỐ handler sẽ dùng: đọc sai `direction` là tăng âm lượng
# khi người ta bảo giảm. Head này chỉ gác việc CÓ BẬT GROUNDING HAY KHÔNG, và
# hai chiều sai lệch nhau hẳn:
#   - đoán nhầm "cần tra"  -> chậm đúng bằng hôm nay, câu trả lời không đổi.
#   - đoán nhầm "khỏi tra" -> hỏi thời tiết mà nghe "chưa tra cứu được".
# Nên chỉ chiều "khỏi tra" mới cần chắc, và không chắc thì giữ nguyên hành vi cũ
# (có tra) chứ không chặn nhãn.
#
# Số đo (5-fold CV trên 177 câu `data/intent/params_chat_web.jsonl`, cột giữa là
# phần trăm lượt chat được bỏ grounding, cột phải là số lượt bỏ NHẦM):
#   0.60   53.1%   4 sai
#   0.65   48.6%   1 sai
#   0.70   39.0%   0 sai      <- chọn
#   0.80   15.8%   0 sai
# 0.70 là điểm cuối cùng còn sạch lỗi. Nới lên 0.65 đổi 9.6% tốc độ lấy lượt trả
# lời sai đầu tiên — không đáng, vì lượt sai đó rơi đúng vào thời tiết/giá cả,
# thứ người dùng hỏi để hành động theo.
#
# CẢNH BÁO khi chỉnh: 177 câu là bộ nhỏ, "0 sai" không phải bảo chứng. Đo lại
# bằng `tools/train_param_heads.py` sau mỗi lần bổ sung dữ liệu.
INTENT_LOCAL_WEB_MIN_CONF = float(get("INTENT_LOCAL_WEB_MIN_CONF", "0.70"))
TTS_VOICE = get("TTS_VOICE", "Ngọc Linh")
TTS_STYLE = get("TTS_STYLE", "tu_nhien")

# VisionCare Host API configuration (app server running on localhost:8001)
VISIONCARE_HOST_URL = get("VISIONCARE_HOST_URL", "http://127.0.0.1:8001")
VISIONCARE_CLIENT_TOKEN = get("VISIONCARE_CLIENT_TOKEN", "f23ChvjGZt_WYrY-A8eJAyxO5LVEF_TGujmE7F_gRAY")
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
VISIONCARE_CALLBACK_TOKEN = get("VISIONCARE_CALLBACK_TOKEN", "visioncare-secret-token")

CHAT_LOCATION_REFRESH_SECONDS = float(get("CHAT_LOCATION_REFRESH_SECONDS", "240.0"))
CHAT_LOCATION_MAX_FIX_AGE_SECONDS = float(get("CHAT_LOCATION_MAX_FIX_AGE_SECONDS", "600.0"))
CHAT_LOCATION_TTL_SECONDS = float(get("CHAT_LOCATION_TTL_SECONDS", "600.0"))
CHAT_ALWAYS_SEARCH = get("CHAT_ALWAYS_SEARCH", "1") != "0"




# ─── Vùng cấu hình theo task (docs/tasks/) ────────────────────────────────
# Mỗi task chỉ thay marker của chính nó. Marker là mỏ neo Edit duy nhất, để
# nhiều agent chạy song song không cùng tranh dòng cuối file.

# === T01 ===
# `X-Device-Id` / `X-Turn-Id` trên `POST /process` (CONTRACTS.md mục 2.1).
#
# Giai đoạn chuyển: nhiều board ngoài hiện trường có thể chưa lên firmware mới
# (chưa gửi `X-Device-Id`). Mặc định CHO PHÉP rơi về `VISIONCARE_DEVICE_ID`
# nhưng `logger.warning` mỗi lần — không được im lặng, vì im lặng biến lỗi cấu
# hình firmware thành trộn session giữa hai người dùng thật.
#
# Bật `REQUIRE_DEVICE_ID=1` để chặn hẳn (400) khi thiếu header — làm vậy khi
# mọi board ngoài hiện trường đã lên firmware mới. 🔴 Chưa chốt: giai đoạn
# chuyển này kéo dài bao lâu — xem CONTRACTS.md mục 7 câu hỏi #12 và
# docs/tasks/reports/T01.md.
REQUIRE_DEVICE_ID = get("REQUIRE_DEVICE_ID", "0") == "1"

# T17/F3 — provisional until firmware RTT/capture-age measurements are recorded.
# 800 ms from the old spec is impossible when capture happens at button-down and
# speech commonly lasts 2–4 seconds, so keep a conservative 6-second freshness
# window while waiting at most 800 ms for the rare frame-after-process race.
FRAME_MAX_AGE_MS = float(get("FRAME_MAX_AGE_MS", "6000"))
FRAME_WAIT_MS = float(get("FRAME_WAIT_MS", "800"))

# F5 (SPEC mục 19): bao lâu server chờ ảnh TẦNG CAO sau khi đã xin.
#
# Vòng này gồm: sự kiện SSE xuống board (~vài chục ms) + board chụp loạt 3
# khung HD (~250 ms) + bắt tay TLS cho socket /frame (623–650 ms đo được trên
# `Thanh_Cuong_FI`, 2026-08-25) + đẩy ~21 KB lên.
#
# 2500 ms để cả bốn chặng đó vừa, kể cả khi mạng chậm hơn lúc đo. Quá hạn thì
# KHÔNG hỏng lượt — router rơi về khung tầng thấp đang có. `ocr` là intent
# người dùng chấp nhận chờ lâu hơn (T15/H1 cố ý làm nó chậm để đọc đúng), nên
# 2.5 s là đánh đổi đúng chiều ở đây và SAI ở mọi intent khác — đó chính là lý
# do F5 chỉ xin tầng cao cho `ocr`.
FRAME_HIGH_TIER_WAIT_MS = float(get("FRAME_HIGH_TIER_WAIT_MS", "2500"))

# T18/F6 — SSE heartbeat keeps Cloudflare/NAT mappings active. The 15-second
# default is provisional until a 10-minute tunnel run is measured on hardware.
EVENT_HEARTBEAT_SECONDS = float(get("EVENT_HEARTBEAT_SECONDS", "15"))
EVENT_QUEUE_SIZE = int(get("EVENT_QUEUE_SIZE", "8"))
INCOMING_CALL_WINDOW_SECONDS = float(get("INCOMING_CALL_WINDOW_SECONDS", "15"))

# Cửa sổ chống gửi lặp theo `X-Turn-Id`: hai `POST /process` cùng
# (device_id, turn_id) trong cửa sổ này -> KHÔNG chạy lại pipeline (không gọi
# STT/Gemini/handler lần hai), chỉ phát lại đúng audio đã tổng hợp lần đầu.
#
# 60s là ĐỀ XUẤT TẠM, chưa chốt (CONTRACTS.md mục 7 câu hỏi #12): dài quá thì
# người dùng lặp lại đúng câu bị nuốt mất; ngắn quá thì board retry sau khi
# mất gói vẫn gọi trùng ra ngoài (Gemini/VisionCare host).
#
# CÙNG một con số này còn dùng làm hạn "bỏ hoang" cho một lượt đang CHẠY DỞ
# (chưa kịp ghi kết quả) — quá ngần ấy giây kể từ lúc giữ quyền mà vẫn chưa
# xong (crash, treo) thì coi là bỏ hoang, lượt trùng turn_id sau được chiếm
# lại quyền chạy. Một config duy nhất cho cả hai nghĩa, đơn giản hơn hai biến
# riêng — xem docs/tasks/contract-deltas/T01.md.
PROCESS_IDEMPOTENCY_WINDOW_SECONDS = float(get("PROCESS_IDEMPOTENCY_WINDOW_SECONDS", "60"))

# Chặn trên: cache idempotency không được phình vô hạn. Sweep (dọn entry hết
# hạn) chạy ở mọi lần ghi nên bình thường cache luôn nhỏ; cái cap FIFO này chỉ
# là lưới an toàn khi có rất nhiều thiết bị/lượt cùng lúc.
PROCESS_IDEMPOTENCY_MAX_ENTRIES = int(get("PROCESS_IDEMPOTENCY_MAX_ENTRIES", "64"))

# Thân audio lớn hơn ngần này (byte) thì KHÔNG cache — đơn giản hơn bo tổng
# dung lượng cache cho chính xác. ~4 MB rộng rãi hơn hẳn một câu trả lời PCM
# trần 60s (~1.92 MB ở 32 000 B/s), thứ đã là câu dài bất thường.
PROCESS_IDEMPOTENCY_MAX_BODY_BYTES = int(get("PROCESS_IDEMPOTENCY_MAX_BODY_BYTES", str(4_000_000)))
# === T03 ===
# Phiên & pending theo device_id (docs/tasks/T03-session-pending.md,
# CONTRACTS.md mục 4).
#
# TTL theo `kind` — ĐÃ CHỐT ở CONTRACTS.md mục 4.1, KHÔNG tự đổi ở đây:
# confirm 25s (để lâu nguy hiểm — quên ngữ cảnh rồi "ừ" cho việc khác) ·
# select 45s (kể cả bảng giá xe: giá có surge, quá hạn phải gọi lại, cấm đọc
# lại giá cũ) · fill 120s (quyết định #1, spec mục 17.3).
PENDING_TTL_CONFIRM_SECONDS = float(get("PENDING_TTL_CONFIRM_SECONDS", "25"))
PENDING_TTL_SELECT_SECONDS = float(get("PENDING_TTL_SELECT_SECONDS", "45"))
PENDING_TTL_FILL_SECONDS = float(get("PENDING_TTL_FILL_SECONDS", "120"))

# Ước lượng TẠM tốc độ đọc của TTS đang dùng (ký tự/giây), dùng để suy ra lúc
# TTS đọc xong một câu hỏi khi đường phát audio không có hook gọi ngược về
# `handlers/action_flow.py` (mục 21.3 — `asked_at` phải tính từ lúc TTS phát
# xong, không phải lúc server tạo pending). CHƯA ĐO trên giọng TTS đang dùng —
# đây là phỏng đoán hợp lý, không phải số đo (AGENT_RULES mục A9).
PENDING_ASKED_AT_ESTIMATE_CHARS_PER_SECOND = float(
    get("PENDING_ASKED_AT_ESTIMATE_CHARS_PER_SECOND", "14")
)

# Dọn session của thiết bị không hoạt động quá ngần này (giây). Đề xuất "24
# giờ" ở T03-session-pending.md mục 6 câu 2 — không phải câu hỏi 🔴 chặn ở
# CONTRACTS.md mục 7 (chỉ câu #9, cache vị trí, mới thật sự chặn task này) —
# áp dụng luôn để dict session không phình vô hạn qua nhiều ngày chạy.
SESSION_IDLE_GC_SECONDS = float(get("SESSION_IDLE_GC_SECONDS", str(24 * 3600)))
# === T07 ===
# P9 (docs/tasks/T07-location.md mục 2.1, CONTRACTS.md mục 7 câu hỏi #3):
# tầng giữa "vị trí cũ nhưng còn dùng được, có nói rõ là cũ" trong
# `handlers/chat.py:_location_text()` chỉ có chỗ chạy khi
# CHAT_LOCATION_TTL_SECONDS < CHAT_LOCATION_MAX_FIX_AGE_SECONDS. Định nghĩa
# gốc ở trên (dòng ~236-238) đặt CẢ HAI bằng 600s — cửa sổ [TTL, MAX_FIX_AGE)
# rỗng, tầng giữa KHÔNG BAO GIỜ chạy được trong production dù logic đúng
# (bắt được ở vòng review, không phải tự đo).
#
# Ghi đè TTL xuống 180s (3 phút) ở đây, GIỮ NGUYÊN MAX_FIX_AGE ở 600s: mở
# ra cửa sổ 180s-600s (3-10 phút) nơi vị trí bị coi là "hơi cũ, vẫn dùng
# được, nói rõ với người dùng" trước khi rơi hẳn về "chưa xác định được vị
# trí". 180s là số ĐỀ XUẤT trong khoảng task file gợi ý (120-300s), CHƯA ĐO
# trên hành vi đi bộ thật (AGENT_RULES mục A9) — không phải kết quả từ bảng
# số nào, chỉ là một mặc định hợp lý để P9 có tác dụng thay vì rỗng.
#
# Ghi đè một hằng đã định nghĩa ở dòng ~238 thay vì sửa thẳng dòng đó là
# CHỦ Ý: bảng "file được sửa" của T07 chỉ cho phép chạm đúng dòng marker
# `# === T07 ===` này (AGENT_RULES mục B4) — Python đọc module từ trên
# xuống nên gán lại cùng tên biến ở đây ghi đè giá trị ở dòng ~238 khi
# module được import; đọc cùng biến môi trường `CHAT_LOCATION_TTL_SECONDS`
# nên set biến môi trường vẫn thắng ở CẢ HAI chỗ như trước.
CHAT_LOCATION_TTL_SECONDS = float(get("CHAT_LOCATION_TTL_SECONDS", "180.0"))
# === T15 ===
# Model riêng cho OCR (`ocr`/H1, docs/tasks/T15-ocr-quality.md mục 25.1).
#
# `ocr` là tác vụ đòi hỏi cao nhất trong nhóm dùng Gemini VLM (`ocr`, `space`,
# `hazard`, `find`, `money`, `chat`): `space`/`hazard` chỉ cần nhận ra khối
# lớn, sai vài chi tiết vẫn có ích; OCR sai MỘT ký tự là đọc sai. Không đổi
# thẳng `GEMINI_MODEL` được vì `space`/`hazard` là intent đi bộ, cần nhanh —
# nâng chung sẽ kéo cả hai chậm theo. Cùng lý do đã tách `GEMINI_INTENT_MODEL`
# và `GEMINI_SEARCH_MODEL` ở trên: mỗi bước có ràng buộc riêng thì có biến
# riêng, handler khác không đổi một dòng.
#
# Số đo H4 (docs/tasks/measurements/H4.md, 3 model x 3 biến thể, 27 lượt gọi
# Gemini thật, có ca hỏng thật `request323.jpg` cháy sáng): `-lite` (mặc định
# hiện tại của GEMINI_MODEL) và hai model to hơn được so trực tiếp trên cùng
# bộ ảnh — xem file đó cho bảng số và khuyến nghị.
#
# 🔴 CHƯA NỐI DÂY: `models/ocr/__init__.py` phải truyền
# `model=config.GEMINI_OCR_MODEL` xuống `vlm.generate_stream()` để biến này
# có tác dụng thật trong production — file đó nằm ngoài bảng "FILE BẠN ĐƯỢC
# SỬA" của agent T15 (xem docs/tasks/reports/T15.md mục "Lệch với task
# file"). `models/vlm/client.py` (T15/H1) đã nhận tham số `model=...` và bench
# H4 đã gọi thật qua tham số đó — chỉ còn thiếu một dòng gọi ở call site.
GEMINI_OCR_MODEL = get("GEMINI_OCR_MODEL", "gemini-3.5-flash")
# === T25 ===
# OTA qua internet + cấu hình mạng từ app + số máy kính
# (docs/tasks/T25-ota-provisioning.md).

# Thư mục chứa firmware phát hành. Bên trong: các file `<version>.bin` và
# MỘT file `latest.json` = {"version": "...", "file": "<version>.bin"}.
#
# 🔴 Không có `latest.json` thì server KHÔNG phát hành gì cả — file `.bin`
# lạc vào thư mục này không tự trở thành bản phát hành. Fail-closed là chủ ý:
# đẩy nhầm bản dựng dở xuống kính của người khiếm thị là hỏng thiết bị mà họ
# không nhìn thấy dòng log nào để biết vì sao. Xem `services/firmware.py`.
FIRMWARE_DIR = get("FIRMWARE_DIR", os.path.join(os.path.dirname(__file__), "firmware"))

# Bao lâu coi một kính là "đang online" kể từ request cuối. Dùng cho
# `GET /devices` (app hiện trạng thái ghép đôi) và cho quyết định đẩy sự kiện
# `firmware_update` — đẩy vào một kính đã tắt là mất sự kiện, board sẽ tự bắt
# lại ở vòng hỏi định kỳ (OTA_POLL_MS phía firmware).
DEVICE_ONLINE_WINDOW_SECONDS = float(get("DEVICE_ONLINE_WINDOW_SECONDS", "120"))

# Token cho các endpoint `/device/*` mà **app điện thoại** gọi (T25).
#
# Khác `VISIONCARE_CALLBACK_TOKEN` ở chỗ: cửa `/internal/*` còn đòi thêm địa
# chỉ loopback, vì phía gọi là server app 8001 chạy cùng máy. App điện thoại
# đi từ internet vào qua Cloudflare tunnel nên không loopback được — bắt
# loopback ở đó nghĩa là tính năng không tồn tại.
#
# Mặc định dùng lại `VISIONCARE_CALLBACK_TOKEN` để bản chạy thử không phải
# cấu hình thêm gì. 🔴 Đặt riêng `DEVICE_CONTROL_TOKEN` trước khi phát hành:
# token này đi tới điện thoại người dùng, còn token kia chỉ ở giữa hai server.
DEVICE_CONTROL_TOKEN = get("DEVICE_CONTROL_TOKEN", "") or VISIONCARE_CALLBACK_TOKEN
# === T21 ===
# G11 (docs/tasks/T21-latency-budget.md mục 2): dòng THỨ HAI của bảng ngân
# sách, đo một thứ khác hẳn TTFB.
#
#     tỉ lệ = (giây tiếng)/(giây đồng hồ), đo từ mảnh ĐẦU tới mảnh CUỐI
#
# TTFB đạt mà tỉ lệ này dưới ngưỡng thì `audio_player.cpp` của board rơi vào
# nhánh "nguồn chậm hơn tốc độ phát → đợi nhận xong hết rồi mới phát" — người
# dùng vẫn đứng im cho tới khi cả câu sinh xong. Hai dòng phải cùng xanh.
#
# 1.30 là ngưỡng board dùng, chép sang đây để server tự chấm điểm mình được
# mà không phải cắm dây đọc log board. CHƯA ĐO trên bản TLS=1 (T21/F10).
AUDIO_MIN_RELEASE_RATE = float(get("AUDIO_MIN_RELEASE_RATE", "1.30"))

# 🔴 G8 — PHÁT HIỆN CỦA T21, CHƯA CHỐT CÁCH XỬ LÝ.
#
# `AUDIO_PREROLL_MODE` mặc định "warm_melodic" nghĩa là server phát một đoạn
# nhạc đệm ở đầu MỌI câu trả lời. Nhưng firmware đã kêu `cueSent()` NGAY khi
# nhả nút (`src/audio/audio_cues.cpp`, chạy trên core 1 song song lúc core 0
# chờ server) — tức người dùng nghe:
#
#     bíp (0 ms, board)  →  ~1 s im  →  nhạc đệm (server)  →  câu trả lời
#
# T21/G8 ghi rõ "KHÔNG làm earcon phía server" vì đúng lý do đó: bíp hai lần.
# RUNBOOK mục 7 cũng liệt kê "Earcon phía server" vào bảng việc KHÔNG được làm.
#
# KHÔNG tự đổi mặc định ở đây: đó là thay đổi người dùng NGHE THẤY, và đoạn
# đệm này còn phục vụ một việc thứ hai có thật (lấp `AUDIO_PREROLL_SECONDS` để
# board không hụt tiếng). Việc còn lại theo T21/G8 là "bảo đảm câu trả lời
# không đè lên `cueSent()`" và "cân âm lượng giữa hai bên" — cả hai đều phải
# NGHE trên board thật mới chốt được. Xem docs/tasks/reports/T21.md.
# === T24 ===
# Cảnh báo vật cản thời gian thực (`hazard_watch`,
# docs/tasks/T24-hazard-watch.md). Chạy SONG SONG với `hazard` theo lượt của
# T16, không thay thế nó.
#
# 🔴 MỌI số dưới đây là ĐIỂM KHỞI ĐẦU suy ra từ ngưỡng gốc của OD_module
# (0.70/0.55, cooldown 2500 ms, chia hai tầng), CHƯA ĐO trên dữ liệu đi bộ
# thật — AGENT_RULES mục A9. Chốt được chúng là câu hỏi #3 của T24 mục 7.

# Hành lang đi bộ, tính theo bề ngang khung hình. Vật ngoài khoảng này thì
# người dùng đi qua bên cạnh nó chứ không đâm vào — không lọc thì mọi cái cây
# ven đường đều kêu và người dùng tắt chế độ này trong ngày đầu.
HAZARD_CORRIDOR_LEFT = float(get("HAZARD_CORRIDOR_LEFT", "0.20"))
HAZARD_CORRIDOR_RIGHT = float(get("HAZARD_CORRIDOR_RIGHT", "0.80"))

# Camera đơn không đo được khoảng cách. Hai đại lượng thay thế, trọng số theo
# OD_module gốc: box TO nghĩa là gần, mép dưới THẤP nghĩa là gần chân người.
HAZARD_AREA_WEIGHT = float(get("HAZARD_AREA_WEIGHT", "0.60"))
HAZARD_BOTTOM_WEIGHT = float(get("HAZARD_BOTTOM_WEIGHT", "0.40"))
# Diện tích (chuẩn hoá) coi là "chiếm trọn tầm nhìn".
HAZARD_AREA_FULL = float(get("HAZARD_AREA_FULL", "0.35"))

# Ba chiều gộp thành một điểm. `approach` nhẹ nhất vì nó cần nhiều khung hình
# mới đáng tin, mà những khung đầu tiên sau khi bật chế độ thì chưa có.
HAZARD_CORRIDOR_WEIGHT = float(get("HAZARD_CORRIDOR_WEIGHT", "0.40"))
HAZARD_PROXIMITY_WEIGHT = float(get("HAZARD_PROXIMITY_WEIGHT", "0.45"))
HAZARD_APPROACH_WEIGHT = float(get("HAZARD_APPROACH_WEIGHT", "0.15"))

HAZARD_MIN_CONFIDENCE = float(get("HAZARD_MIN_CONFIDENCE", "0.25"))

# Ngưỡng vào từng mức. Ba tầng (khác OD_module: hai tầng) để khớp tông tăng
# dần của W6 — SAFE im lặng, LOW tít chậm, MEDIUM nhanh hơn, HIGH dồn dập.
HAZARD_ENTER_LOW = float(get("HAZARD_ENTER_LOW", "0.40"))
HAZARD_ENTER_MEDIUM = float(get("HAZARD_ENTER_MEDIUM", "0.55"))
HAZARD_ENTER_HIGH = float(get("HAZARD_ENTER_HIGH", "0.70"))

# Hysteresis BẤT ĐỐI XỨNG: lên mức phát ngay (chậm một nhịp là vấp), xuống
# mức phải giữ đủ lâu — một khung hình trượt detector không được phép tắt
# tiếng cảnh báo giữa lúc người dùng đang bước tới đúng cái cột đó.
HAZARD_COOLDOWN_MS = float(get("HAZARD_COOLDOWN_MS", "2500"))

# ── Vòng canh phía SERVER (T24/W5, `services/hazard_worker.py`) ────────────
#
# Board chụp và đẩy khung mỗi `HAZARD_WATCH_PERIOD_MS = 500` (hằng số bên
# firmware, `src/camera/hazard_watch.cpp`). Server chấm điểm theo nhịp riêng
# vì hai bên KHÔNG cùng đồng hồ và không nên cùng nhịp: chấm nhanh hơn board
# đẩy chỉ tổ chấm lại đúng một khung cũ.
#
# 🔴 500 ms là nhịp KHỞI ĐẦU, chưa đo trên khung thật của OV2640. Suy luận độ
# sâu đo được p50 **107 ms lúc máy rảnh** nhưng **236 ms khi server đang chạy
# song song** (measurements/T24.md mục 6) — biên còn ~264 ms, hẹp. Nếu vòng
# canh ăn quá nhịp thì `tick()` bỏ qua chứ không dồn hàng, và đếm vào
# `skipped` để log nói ra thay vì âm thầm tụt fps.
HAZARD_WATCH_TICK_MS = float(get("HAZARD_WATCH_TICK_MS", "500"))

# Khung cũ hơn mức này thì KHÔNG chấm. Chấm một khung 3 giây trước rồi kêu
# HIGH nghĩa là báo về một cái cột người dùng đã đi qua rồi.
#
# 1200 ms = hai chu kỳ đẩy của board cộng biên mạng. Mất khung lác đác thì
# vẫn chấm được khung kế; mất hẳn đường truyền thì im chứ không bịa.
HAZARD_FRAME_MAX_AGE_MS = float(get("HAZARD_FRAME_MAX_AGE_MS", "1200"))

# Bao nhiêu lần chấm hỏng LIÊN TIẾP thì tắt chế độ cho thiết bị đó.
#
# 🔴 Fail-closed lần hai. `handlers/hazard_watch.py` đã chặn ca "không có
# model" lúc BẬT, nhưng detector còn hỏng được giữa chừng (hết RAM, ONNX ném
# lỗi trên một khung méo). Cứ chạy tiếp và nuốt lỗi nghĩa là người dùng vẫn
# nghe "đang canh" trong khi không ai chấm gì — đúng cái nguy hiểm nhất.
# Tắt hẳn và đẩy `hazard_watch stop` xuống board để nó thôi đốt pin chụp.
HAZARD_WATCH_MAX_FAILURES = int(get("HAZARD_WATCH_MAX_FAILURES", "5"))

# 🔴 HẠN GIỜ cho mức đệm ở trên — T21, đo được 2026-08-24.
#
# `AUDIO_PREROLL_SECONDS` gom 2.0 giây audio trước khi gửi byte đầu. Câu mở
# đầu ("Đã tiếp nhận yêu cầu" / warm_melodic) đã DỰNG SẴN và ra khỏi TTS gần
# như tức thì — nhưng nó chỉ dài ~0.94 s, ngắn hơn mức đệm. Nên vòng gom giữ
# nó lại rồi CHẶN chờ mảnh kế tiếp, mà mảnh kế tiếp chỉ có sau khi STT +
# Gemini + TTS chạy xong.
#
# Đo được trước khi sửa (`measurements/G1.md`): trung vị tiếng đầu 3.68 s,
# `emergency_call` 4.82 s so với ngân sách 300 ms. Người dùng đứng im gần 4
# giây trong khi audio để phát cho họ ĐÃ nằm sẵn trong RAM từ mili giây 100.
#
# Chờ thêm còn vô ích về kỹ thuật: mức đệm sinh ra để phòng nguồn CHẬM hơn
# tốc độ phát, nhưng khi nguồn DỪNG HẲN thì chờ không gom thêm được byte nào.
# Nó chỉ đổi im lặng lấy im lặng.
#
# 0.35 s: đủ để gom trọn một mảnh PCM bình thường (khoảng nghỉ giữa hai mảnh
# đo được là 0.81 s ở trường hợp tệ nhất, và mảnh đầu luôn là câu dựng sẵn nên
# nó tới trong vài chục ms), nhưng không đủ để nuốt mất cả một lượt gọi Gemini.
AUDIO_PREROLL_MAX_WAIT_SECONDS = float(get("AUDIO_PREROLL_MAX_WAIT_SECONDS", "0.35"))

# Model nhận diện vật cản cho `hazard_watch` (T24/W4).
#
# 🔴 Fail-closed: không có file này thì `hazard_watch` **từ chối bật** và nói
# thẳng ra với người dùng. Một chế độ cảnh báo vật cản im lặng còn nguy hiểm
# hơn không có nó — người dùng tin là đang được canh và đi nhanh hơn.
#
# Tải/export bằng: python tools/fetch_hazard_model.py
HAZARD_MODEL_PATH = get(
    "HAZARD_MODEL_PATH",
    os.path.join(os.path.dirname(__file__), "models", "od", "yolo11n.onnx"),
)

# NMS IoU lúc gộp box trùng. 0.45 là giá trị gốc của OD_module và cũng là mặc
# định của YOLO — chưa có lý do đo được để đổi.
HAZARD_NMS_IOU = float(get("HAZARD_NMS_IOU", "0.45"))

# Model ước lượng độ sâu — tín hiệu CHÍNH của `hazard_watch` (T24/W4).
#
# 🔴 Vì sao cần khi đã có YOLO: YOLO11n biết đúng 80 lớp COCO và KHÔNG có lớp
# "vật thể chung". Cột điện, tường, bậc thềm, cành cây thấp, cửa kính, hàng
# rào — không cái nào nằm trong 80 lớp đó, nên không có box, nên hệ báo SAFE
# cho một cây cột chắn ngay trước mặt. Đó là mù đúng thứ người khiếm thị hay
# va vào nhất.
#
# Độ sâu trả về khoảng cách theo TỪNG PIXEL nên không cần danh sách lớp, bắt
# được cả vật vô danh. Tải bằng: python tools/fetch_depth_model.py
DEPTH_MODEL_PATH = get(
    "DEPTH_MODEL_PATH",
    os.path.join(os.path.dirname(__file__), "models", "od", "depth_anything_v2_small.onnx"),
)

# 🔴 `DEPTH_NEAR_THRESHOLD` ĐÃ BỊ XOÁ, không phải đổi tên.
#
# Nó là ngưỡng TUYỆT ĐỐI trên bản đồ disparity đã chuẩn hoá theo từng khung —
# và vì chuẩn hoá theo khung luôn đẩy thứ gần nhất về 1.0, mà thứ gần nhất
# trong mọi khung chụp lúc đi bộ là MẶT ĐẤT DƯỚI CHÂN, nó chấm điểm mặt đất.
# Đo trên 25 ảnh thật: bắt được 8/8, **báo oan 11/11** — kêu HIGH cho một con
# đường quê trống trơn. Chi tiết: docs/tasks/measurements/T24.md.
#
# Ai định thêm lại một ngưỡng tuyệt đối ở đây, đọc bảng đó trước.

# Mức một pixel phải VƯỢT trung vị của chính dòng chứa nó mới được coi là vật
# cản. Tương đối theo dòng nên nó không trôi theo độ sáng, theo cảnh, hay theo
# việc mặt đất gần hay xa.
#
# 0.16 đo trên 25 ảnh: đường trống ra diện tích vượt 0.000, cột điện sát ra
# 0.124. Hạ xuống 0.10 thì bắt được y hệt (5/8) mà báo oan tăng từ 2 lên 3 —
# xem bảng quét ở docs/tasks/measurements/T24.md.
DEPTH_EXCESS_MARGIN = float(get("DEPTH_EXCESS_MARGIN", "0.16"))

# Mức vượt được coi là "sát mặt" (độ tin cậy = 1.0). CHƯA ĐO trên khung thật.
DEPTH_EXCESS_FULL = float(get("DEPTH_EXCESS_FULL", "0.45"))

# Bề rộng hành lang giữa (phần chiều rộng khung được xét). Vật nằm ngoài dải
# này ở BÊN CẠNH người dùng chứ không chắn bước chân.
#
# 🔴 Đây là ràng buộc chặn phần lớn báo oan. Hành lang hẹp, lối đi có lan can
# kính, vỉa hè sát tường — tất cả đều có mặt phẳng RẤT gần ở hai mép khung.
# Bỏ ràng buộc này thì chúng kêu hết.
DEPTH_CORRIDOR_WIDTH = float(get("DEPTH_CORRIDOR_WIDTH", "0.34"))

# Điểm xa nhất còn nhìn thấy được trong hành lang giữa. Cao hơn mức này nghĩa
# là KHÔNG nhìn được ra xa — có gì đó choán ngang tầm nhìn (tường, bậc thềm,
# cánh cửa). Đây là tín hiệu DUY NHẤT bắt được loại vật cản choán hết chiều
# ngang, vì loại đó tự trở thành trung vị của dòng nên `DEPTH_EXCESS_MARGIN`
# triệt tiêu mất.
#
# 0.16 đo được là tốt nhất trên bộ 25 ảnh. Cao nhất trong nhóm đường thoáng
# là 0.152 nên biên chỉ còn 0.008 — MỎNG, và đó là điều phải biết trước khi
# tin vào tín hiệu này. Vẫn CHƯA ĐỦ để bắt bậc thềm: xem mục "còn yếu" ở
# services/depth_detector.py.
DEPTH_BLOCKED_VIEW = float(get("DEPTH_BLOCKED_VIEW", "0.16"))

# Mức "chắn kín" (độ tin cậy = 1.0). CHƯA ĐO trên khung thật.
DEPTH_BLOCKED_FULL = float(get("DEPTH_BLOCKED_FULL", "0.45"))

# Một vùng phải chiếm ít nhất ngần này diện tích KHUNG mới được coi là vật cản.
#
# 🔴 0.015 → 0.002. Không phải nới lỏng tuỳ tiện: từ khi chỉ xét hành lang
# giữa (`DEPTH_CORRIDOR_WIDTH = 0.34`), một cây trụ chắn ngay trước mặt chỉ
# chiếm ~0.009 diện tích KHUNG dù nó choán 3.5% hành lang. Ngưỡng cũ 0.015
# vứt đúng những vật cản mà tín hiệu này sinh ra để bắt — đo được: hai ảnh
# trụ chắn tụt từ "bắt được" xuống SAFE.
#
# 🔴 0.002 của khung 308×308 là 190 pixel. Trên 25 ảnh này nó KHÔNG thêm báo
# oan nào, nhưng đó là ảnh chụp sạch. Khung thật từ OV2640 có nhiễu hạt hơn
# hẳn — con số này phải đo lại trên khung của board.
DEPTH_MIN_REGION_AREA = float(get("DEPTH_MIN_REGION_AREA", "0.002"))

# Cỡ ảnh đưa vào model. 518 là cỡ Depth Anything V2 được huấn luyện, nhưng
# model chạy được ở cỡ khác vì nó toàn convolution/attention theo patch.
#
# Đo trên máy này (CPU, i5-12500H, bản fp32 99 MB, đã ấm — lượt ĐẦU của mỗi
# phiên tốn ~2.6 s, đừng lấy số đó):
#
#     input 518 →  441 ms
#     input 392 →  361 ms
#     input 308 →  223 ms   ← chọn
#     input 252 →  145 ms
#
# Chọn 308: `HAZARD_WATCH_PERIOD_MS = 500` nên cả vòng (giải nén JPEG + độ sâu
# + YOLO đặt tên) phải lọt trong 500 ms. 223 + ~200 (YOLO) = ~420 ms — vừa,
# nhưng KHÔNG còn nhiều biên. Nếu board đẩy khung nhanh hơn dự kiến thì hạ
# xuống 252, hoặc bỏ tầng YOLO (mất tên gọi, giữ nguyên cảnh báo).
#
# 🔴 CHƯA ĐO trên khung thật của board (1280×720 từ camera OV2640, không phải
# ảnh fixture). Và chưa đo pin.
DEPTH_INPUT_SIZE = int(get("DEPTH_INPUT_SIZE", "308"))


# T24/W5: nhịp tối thiểu giữa hai lệnh "thôi canh đi" gửi xuống một board đang
# đẩy khung hazard mà server không chấm (mất cờ sau restart).
#
# Khung tới 2 lần/giây; hàng đợi SSE mỗi thiết bị có 8 chỗ. Gửi lệnh dừng theo
# đúng nhịp khung sẽ làm đầy hàng trong 4 giây và đẩy văng `call_incoming`.
HAZARD_ORPHAN_STOP_COOLDOWN_S = float(get("HAZARD_ORPHAN_STOP_COOLDOWN_S", "5.0"))
