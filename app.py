import contextvars
import glob
import io
import logging
import os
import re
import hmac
import ipaddress
import threading
import time
import wave
from collections.abc import Callable, Iterable, Iterator
from itertools import chain

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import Response, StreamingResponse

import config
from handlers import chat
from models import vlm
from pipeline import adpcm, intent_local, phrases, router, stt, tts
from services.action_callbacks import action_callbacks
from services import capabilities
from services.frame_buffer import frames
from services.events_channel import events

logger = logging.getLogger("blind_assist")

# Uvicorn chỉ cấu hình logger của riêng nó; không có dòng này thì log INFO đo
# thời gian bên dưới bị root logger (mặc định WARNING) nuốt mất.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

app = FastAPI(title="Blind-Assist Audio Server")

# ─── T01: định danh thiết bị & lượt (CONTRACTS.md mục 2.1) ────────────────
#
# `device_id`/`turn_id` xuống tới handler/pipeline bằng ContextVar, KHÔNG
# thêm tham số vào chữ ký handler — có 15 handler, thêm tham số là 15 chỗ
# sửa và 15 chỗ quên (T01-protocol-ids.md mục 2.2). T03/T17/T18/T19 và các
# handler đọc qua `app.DEVICE_ID_CTX.get()` / `app.TURN_ID_CTX.get()`.
#
# Đặt Ở ĐÂY (module level) chỉ để KHAI BÁO ContextVar — bản thân ContextVar là
# một "khe" toàn cục vô hại khi rỗng. Giá trị THẬT chỉ được `.set()` bên trong
# scope của từng request (trong `process()`), không bao giờ set ở module
# level — set ở module level mới là thứ rò giữa các request.
DEVICE_ID_CTX: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "device_id_ctx", default=None
)
TURN_ID_CTX: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "turn_id_ctx", default=None
)


def _resolve_device_turn(request: Request) -> tuple[str, str | None]:
    """Đọc `X-Device-Id`/`X-Turn-Id` từ HEADER (không phải form field) — server
    phải đọc được các id này TRƯỚC khi body ảnh/audio upload xong.

    Thiếu `X-Device-Id`:
      - `config.REQUIRE_DEVICE_ID=1` -> từ chối rõ ràng (400).
      - `config.REQUIRE_DEVICE_ID=0` (**mặc định hiện tại**, giai đoạn
        chuyển): CHO PHÉP rơi về `config.VISIONCARE_DEVICE_ID` nhưng
        `logger.warning` MỖI LẦN — cấm im lặng, xem T01-protocol-ids.md mục
        2.2. `1` là đích cuối, chờ chốt mốc chuyển (CONTRACTS mục 7 câu #3).

    Thiếu `X-Turn-Id`: KHÔNG bị chặn (CONTRACTS mục 2.1 liệt kê BẮT BUỘC
    nhưng chưa có ai enforce phần này — xem `docs/tasks/contract-deltas/T01.md`),
    chỉ mất đi hai thứ dựa vào nó (idempotency ở đây, barge-in ở T04) —
    `logger.warning` để lộ ra ngoài, không âm thầm.
    """
    device_id = request.headers.get("x-device-id")
    turn_id = request.headers.get("x-turn-id")

    if not device_id:
        if config.REQUIRE_DEVICE_ID:
            raise HTTPException(
                status_code=400,
                detail="Thiếu header X-Device-Id bắt buộc (CONTRACTS.md mục 2.1)",
            )
        logger.warning(
            "Thiếu X-Device-Id, dùng tạm VISIONCARE_DEVICE_ID=%s "
            "(giai đoạn chuyển, REQUIRE_DEVICE_ID=0) — board cần lên firmware mới",
            config.VISIONCARE_DEVICE_ID,
        )
        device_id = config.VISIONCARE_DEVICE_ID

    if not turn_id:
        logger.warning(
            "Thiếu X-Turn-Id (device=%s) — KHÔNG bị chặn, nhưng lượt này mất "
            "idempotency (có thể gọi trùng pipeline nếu board tự thử lại) và "
            "sẽ mất luôn barge-in (T04) khi task đó chạy tới",
            device_id,
        )

    return device_id, turn_id


# ─── T01: chống gửi lặp theo X-Turn-Id (idempotency) ──────────────────────
#
# Hai `POST /process` cùng (device_id, turn_id) trong cửa sổ
# `config.PROCESS_IDEMPOTENCY_WINDOW_SECONDS` -> KHÔNG chạy lại pipeline (STT/
# Gemini/handler không bị gọi lần hai), chỉ phát lại đúng audio đã tổng hợp ở
# lượt đầu. Board có thể gửi trùng khi mất ACK giữa chừng rồi tự động thử lại
# — CẢ KHI lượt đầu còn đang chạy dở (chưa xong), không chỉ sau khi đã xong.
#
# Khoá theo CẢ device_id lẫn turn_id (không chỉ turn_id) — hai kính khác nhau
# lỡ trùng turn_id (bug firmware, hoặc test) không được ăn nhầm kết quả của
# nhau.
#
# Mỗi entry có `state`:
#   "pending" — một lượt đang CHẠY DỞ pipeline cho key này, chưa có body.
#               Mang theo `event` (threading.Event) để lượt trùng đợi.
#   "done"    — pipeline đã xong, có body sẵn để phát lại nguyên xi.
#
# Một entry "pending" bị bỏ hoang (crash giữa chừng, hoặc client rớt kết nối
# nên `_tee_and_cache` không bao giờ chạy hết vòng `for` — xem ghi chú ở đó)
# thì KHÔNG treo vĩnh viễn: quá `config.PROCESS_IDEMPOTENCY_WINDOW_SECONDS`
# kể từ lúc "reserved_at", nó bị coi là bỏ hoang và lượt sau chiếm lại được
# quyền chạy — dùng CHUNG một con số với TTL của entry "done" cho đơn giản
# (một config duy nhất, thay vì hai), xem `docs/tasks/contract-deltas/T01.md`.
_IDEMPOTENCY_LOCK = threading.Lock()
_IDEMPOTENCY_CACHE: dict[tuple[str, str], dict] = {}


def _idempotent_sweep_locked(now: float) -> None:
    """PHẢI gọi trong `_IDEMPOTENCY_LOCK`. Dọn entry "done" đã hết hạn VÀ entry
    "pending" bị bỏ hoang quá lâu — chạy ở MỌI điểm ghi (không chỉ lúc tra một
    key cụ thể) để cache không phình vô hạn dù `turn_id` luôn là uuid mới,
    không bao giờ được tra lại lần hai để tự dọn theo đường cũ.
    """
    expired = [
        key for key, entry in _IDEMPOTENCY_CACHE.items()
        if (entry["state"] == "done" and entry["expires_at"] < now)
        or (
            entry["state"] == "pending"
            and now - entry["reserved_at"] >= config.PROCESS_IDEMPOTENCY_WINDOW_SECONDS
        )
    ]
    for key in expired:
        del _IDEMPOTENCY_CACHE[key]


def _idempotent_enforce_cap_locked() -> None:
    """Chặn trên số entry — FIFO, đơn giản hơn là bo tổng dung lượng byte cho
    chính xác. Chỉ chạm tới khi sweep ở trên không đủ (vd. rất nhiều thiết bị
    cùng lúc) — bình thường sweep đã giữ cache nhỏ."""
    while len(_IDEMPOTENCY_CACHE) > config.PROCESS_IDEMPOTENCY_MAX_ENTRIES:
        oldest_key = next(iter(_IDEMPOTENCY_CACHE))
        _IDEMPOTENCY_CACHE.pop(oldest_key, None)


def _idempotent_begin(device_id: str, turn_id: str | None):
    """Xin quyền chạy pipeline cho `(device_id, turn_id)`, hoặc lấy kết quả có sẵn.

    Trả về một cặp `(kind, payload)`:
      ("hit", entry)   — đã có kết quả XONG ("done") — dùng lại, không chạy
                         pipeline.
      ("wait", event)  — CÙNG key đang có lượt khác chạy DỞ ("pending") —
                         đợi `event` (có giới hạn) rồi gọi lại hàm này.
      ("own", None)    — không ai đang giữ key này (hoặc lượt cũ đã bỏ hoang
                         quá lâu, vừa bị sweep) — người gọi CHIẾM quyền chạy,
                         và PHẢI gọi `_idempotent_finish()` khi xong (dù
                         thành công hay đã đổi thành câu báo lỗi).
    """
    if not turn_id:
        return "own", None
    key = (device_id, turn_id)
    now = time.monotonic()
    with _IDEMPOTENCY_LOCK:
        _idempotent_sweep_locked(now)
        entry = _IDEMPOTENCY_CACHE.get(key)
        if entry is not None:
            if entry["state"] == "done":
                return "hit", entry
            return "wait", entry["event"]
        _IDEMPOTENCY_CACHE[key] = {
            "state": "pending",
            "reserved_at": now,
            "event": threading.Event(),
        }
        return "own", None


def _idempotent_finish(
    device_id: str,
    turn_id: str | None,
    response_format: str,
    media_type: str,
    headers: dict[str, str],
    body: bytes,
) -> None:
    """Đóng lượt đã CHIẾM quyền ở `_idempotent_begin` (kind == "own"): ghi kết
    quả "done" rồi đánh thức mọi lượt đang đợi ở nhánh "wait".

    Thân quá lớn (`config.PROCESS_IDEMPOTENCY_MAX_BODY_BYTES`) thì KHÔNG cache
    — đơn giản hơn là bo tổng dung lượng cache cho chính xác; lượt trùng
    turn_id hiếm hoi cỡ này (nếu có) sẽ tự chạy lại pipeline, chấp nhận được.
    """
    if not turn_id:
        return
    key = (device_id, turn_id)
    now = time.monotonic()
    event: threading.Event | None = None
    with _IDEMPOTENCY_LOCK:
        entry = _IDEMPOTENCY_CACHE.get(key)
        event = entry.get("event") if entry is not None else None
        _idempotent_sweep_locked(now)
        if len(body) > config.PROCESS_IDEMPOTENCY_MAX_BODY_BYTES:
            _IDEMPOTENCY_CACHE.pop(key, None)
        else:
            _IDEMPOTENCY_CACHE[key] = {
                "state": "done",
                "expires_at": now + config.PROCESS_IDEMPOTENCY_WINDOW_SECONDS,
                "response_format": response_format,
                "media_type": media_type,
                "headers": dict(headers),
                "body": body,
            }
            _idempotent_enforce_cap_locked()
    if event is not None:
        event.set()


def _bind_context(iterator: Iterator[bytes]) -> Iterator[bytes]:
    """Đóng băng Context HIỆN TẠI (mang device_id/turn_id đã `.set()`) rồi chạy
    mọi lần kéo tiếp theo của `iterator` trong đúng Context đó.

    `StreamingResponse` được Starlette tiêu thụ SAU KHI `process()` đã
    return — có thể ở thread/task khác, nơi ContextVar đã bị `.reset()` hoặc
    rỗng. Không có lớp này thì handler ở downstream (T03/T17) đọc
    `device_id`/`turn_id` ra `None` ngay khi phần audio sinh sau mảnh đầu tiên
    chạy, dù mảnh đầu vẫn thấy đúng giá trị (nó được kéo TRONG lúc còn ở
    `process()`).

    `contextvars.copy_context()` chạy NGAY ở đây — tức trong lời gọi hàm này,
    còn trong scope request — không phải lúc thân generator `_gen()` bắt đầu
    chạy (đó là lúc `next()` đầu tiên được gọi, có thể đã ra khỏi request).
    """
    ctx = contextvars.copy_context()
    it = iter(iterator)

    def _gen() -> Iterator[bytes]:
        while True:
            try:
                chunk = ctx.run(next, it)
            except StopIteration:
                return
            yield chunk

    return _gen()


def _tee_and_cache(
    iterator: Iterator[bytes],
    device_id: str,
    turn_id: str | None,
    response_format: str,
    media_type: str,
    headers: dict[str, str],
) -> Iterator[bytes]:
    """Vừa phát từng mảnh cho client, vừa gom lại để lưu vào cache idempotency
    SAU KHI phát xong — không trì hoãn mảnh đầu để chờ gom trọn trước.

    CHỈ gọi hàm này khi người gọi đã CHIẾM quyền ở `_idempotent_begin` (kind
    == "own") — xem `process()`. Nếu client rớt kết nối giữa chừng,
    `GeneratorExit` ném vào ngay tại `yield chunk` bên dưới, thoát khỏi vòng
    `for` TRƯỚC khi chạy tới `_idempotent_finish` — CỐ Ý: thân đã thu chỉ là
    một phần, cache một phần là SAI, nên bỏ nguyên chứ không cache thiếu.
    Entry "pending" sẽ tự hết hạn theo `_idempotent_sweep_locked` như mọi lượt
    bỏ hoang khác, không cần dọn riêng ở đây.
    """
    chunks: list[bytes] = []
    for chunk in iterator:
        chunks.append(chunk)
        yield chunk
    _idempotent_finish(
        device_id, turn_id, response_format, media_type, headers, b"".join(chunks)
    )


PCM_FORMAT = f"pcm_s16le;rate={tts.OUTPUT_SAMPLE_RATE};channels=1"
_BYTES_PER_SAMPLE = 2


MP3_FORMAT = f"mp3;bitrate={tts.MP3_BITRATE_KBPS}kbps;rate={tts.OUTPUT_SAMPLE_RATE};channels=1"

# Chuỗi board đọc để tự cấu hình decoder ADPCM (`HUONG_DAN_SERVER.md` §2B).
ADPCM_FORMAT = (
    f"ima_adpcm;rate={adpcm.SAMPLE_RATE};channels=1;block={adpcm.BLOCK_ALIGN}"
)

# Định dạng board nuốt được, xếp theo thứ tự board khuyến nghị. Dùng khi
# `RESPONSE_FORMAT=auto` để chọn theo `Accept` của chính client gửi tới.
_ADPCM_FORMATS = ("adpcm_wav", "adpcm_stream")


def _negotiate(accept: str) -> str:
    """Chọn định dạng trả về theo `Accept` của client.

    Board gửi `Accept: audio/wav;codec=ima_adpcm, audio/mpeg, audio/wav` — tức
    nó tự khai đọc được ADPCM. Firmware cũ hơn không khai `codec=ima_adpcm`, và
    trả ADPCM cho nó là ra nhiễu. Đọc `Accept` thay vì cấu hình cứng ở server
    thì hai đời firmware chạy được cùng lúc trên cùng một endpoint.
    """
    accept = accept.lower()
    if "ima_adpcm" in accept:
        return "adpcm_wav"
    if "audio/mpeg" in accept:
        return "mp3_stream"
    if "audio/wav" in accept:
        return "wav"
    # Không khai gì: theo hợp đồng hiện tại board đọc được ADPCM.
    return "adpcm_wav"


def _stream_headers(response_format: str) -> dict[str, str]:
    """Đủ thông tin để MCU tự cấu hình I2S/decoder và tính buffer, không hardcode gì.

    Tách thành từng header số riêng thay vì bắt firmware parse chuỗi ghép: trên
    MCU, `atoi` một header là xong, còn tách chuỗi là thêm một chỗ để sai.
    """
    # Số giây audio đã nằm sẵn trong mảnh đầu. MCU phát ngay khi nhận được
    # mảnh đó; đây là quãng an toàn nó có trước khi cần mảnh tiếp theo.
    preroll = str(config.AUDIO_PREROLL_SECONDS)

    if response_format in _ADPCM_FORMATS:
        return {
            "X-Audio-Format": ADPCM_FORMAT,  # đúng chuỗi board mô tả trong hợp đồng
            "X-Audio-Encoding": "ima_adpcm",
            "X-Audio-Sample-Rate": str(adpcm.SAMPLE_RATE),
            "X-Audio-Bits": "4",
            "X-Audio-Channels": "1",
            # Làm tròn xuống cho khớp `nAvgBytesPerSec` trong header WAV, để
            # board đọc header hay đọc chỗ này cũng ra một con số.
            "X-Audio-Byte-Rate": str(adpcm.AVG_BYTES_PER_SEC),
            "X-Audio-Block-Align": str(adpcm.BLOCK_ALIGN),
            "X-Audio-Samples-Per-Block": str(adpcm.SAMPLES_PER_BLOCK),
            "X-Audio-Preroll-Seconds": preroll,
        }

    if response_format == "mp3_stream":
        return {
            "X-Audio-Format": MP3_FORMAT,  # dạng gộp, cho người debug bằng curl
            "X-Audio-Encoding": "mp3",
            "X-Audio-Sample-Rate": str(tts.OUTPUT_SAMPLE_RATE),
            "X-Audio-Channels": "1",
            # CBR nên cố định suốt stream. Nhân trực tiếp ra kích thước buffer
            # theo giây, khỏi tự tính. Không có X-Audio-Bits: không áp dụng
            # cho dữ liệu đã nén.
            "X-Audio-Byte-Rate": str(tts.MP3_BYTE_RATE),
            "X-Audio-Preroll-Seconds": preroll,
        }

    return {
        "X-Audio-Format": PCM_FORMAT,  # dạng gộp, cho người debug bằng curl
        "X-Audio-Encoding": "pcm_s16le",
        "X-Audio-Sample-Rate": str(tts.OUTPUT_SAMPLE_RATE),
        "X-Audio-Bits": str(_BYTES_PER_SAMPLE * 8),
        "X-Audio-Channels": "1",
        # Nhân trực tiếp ra kích thước buffer theo giây, khỏi tự tính.
        "X-Audio-Byte-Rate": str(tts.OUTPUT_SAMPLE_RATE * _BYTES_PER_SAMPLE),
        "X-Audio-Preroll-Seconds": preroll,
    }

_ERROR_MESSAGE = "Có lỗi xảy ra, vui lòng thử lại"

# Chỉ audio là bắt buộc: đó là câu lệnh, không có nó thì không biết người dùng
# muốn gì. Ảnh thì tuỳ câu hỏi — "gọi cho mẹ" hay "kể chuyện cười" không cần ảnh
# nào, nên đòi đủ cả hai ở đây là chặn oan. Câu hỏi thật sự cần ảnh mà thiếu ảnh
# thì `pipeline/image_quality.py` nói, vì chỉ ở đó mới biết intent là gì.
_MISSING_AUDIO_MESSAGE = "Không nhận được âm thanh, vui lòng nói lại."

# Câu đầu tiên, phát ngay khi gói tin vào tới server — trước cả STT.
#
# Người khiếm thị bấm gửi xong không có gì để nhìn: im lặng 2-3 giây đầu là
# không phân biệt được với "gửi hụt, phải bấm lại". Câu này chỉ nói đúng một
# điều có thật ở thời điểm đó: yêu cầu đã tới nơi và đang được xử lý.
#
# Chỉ nói được ngay vì audio của nó đã dựng sẵn (`pipeline/phrases.py`). Tổng
# hợp lúc chạy thì chính nó lại là quãng chờ mới, đúng thứ nó sinh ra để xoá.
_RECEIVED_MESSAGE = "Đã tiếp nhận yêu cầu"

STATIC_SPEECH: tuple[str, ...] = (
    _RECEIVED_MESSAGE,
    _ERROR_MESSAGE,
    _MISSING_AUDIO_MESSAGE,
)


def _next_debug_index() -> int:
    """Số thứ tự kế tiếp, dựa trên request*.wav đã có trong STORAGE_DIR."""
    os.makedirs(config.STORAGE_DIR, exist_ok=True)
    indices = [
        int(m.group(1))
        for f in glob.glob(os.path.join(config.STORAGE_DIR, "request*.wav"))
        if (m := re.match(r"request(\d+)\.wav$", os.path.basename(f)))
    ]
    return max(indices, default=0) + 1


def _save_debug_audio(name: str, audio_bytes: bytes) -> None:
    path = os.path.join(config.STORAGE_DIR, name)
    with open(path, "wb") as f:
        f.write(audio_bytes)


def _pcm_to_wav(pcm_bytes: bytes) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(tts.OUTPUT_SAMPLE_RATE)
        w.writeframes(pcm_bytes)
    return buf.getvalue()


def _image_extension(image_bytes: bytes) -> str:
    if image_bytes[:2] == b"\xff\xd8":
        return "jpg"
    if image_bytes[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    return "jpg"


def _save_debug_image(idx: int, image_bytes: bytes) -> None:
    ext = _image_extension(image_bytes)
    path = os.path.join(config.STORAGE_DIR, f"request{idx}.{ext}")
    with open(path, "wb") as f:
        f.write(image_bytes)


def _dummy_wav() -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * 1600)  # 0.1s im lặng
    return buf.getvalue()


@app.on_event("startup")
def preload_models() -> None:
    """Load STT/TTS và chạy thử mỗi model 1 lần.

    Lần infer đầu tiên của mỗi model tốn thêm thời gian khởi tạo (warm-up
    kernel, dựng batch engine...) so với các lần sau. Trả trước chi phí đó ở
    đây để request thật đầu tiên của người dùng không phải gánh thêm warm-up
    này — bấm gửi post là có kết quả ngay.

    Không còn model cục bộ nào cho ảnh: cả 4 handler đều đọc ảnh qua Gemini.
    """
    stt._load_asr()
    stt.transcribe(_dummy_wav())
    intent_local.warm()

    # Dựng sẵn client Gemini + bắt tay TLS. Đo trong tiến trình sạch:
    #   lượt 1 (client lạnh)  3.58s
    #   lượt 2-5 (ấm)         0.50 - 0.62s
    #   sau 30s idle          0.68s     <- kết nối sống, không cần keepalive
    # Tức request THẬT đầu tiên của người dùng vốn phải gánh thêm ~3 giây chỉ để
    # dựng client và bắt tay. Trả trước ở đây, giống cách STT/TTS đã làm.
    vlm.warm()

    # Vị trí điện thoại: lấy ở nền, không bao giờ trên đường request. Một vòng
    # `location/get` là poll xuống điện thoại tới 12s — đặt nó trong request là
    # bắt người dùng đứng chờ ngần ấy trước khi nghe được chữ nào.
    chat.start_location_refresher()
    capabilities.start_pairing_refresh()
    tts._load_tts()
    # Tiêu thụ hết generator: warm-up phải đi đúng đường stream mà /process
    # dùng, vì phiên giải mã theo frame của infer_stream có warm-up riêng.
    for _ in tts.synthesize_stream("Khởi động"):
        pass

    # Dựng sẵn audio cho mọi câu cố định. Lần đầu tốn một hai phút; các lần sau
    # đọc lại từ đĩa nên gần như tức thì.
    phrases.warm(extra=(*STATIC_SPEECH, *capabilities.STATIC_SPEECH))

    lead_in = tts.prerendered(_RECEIVED_MESSAGE)
    if lead_in is None:
        logger.warning("Chưa dựng sẵn được câu chào đầu, nó sẽ phải tổng hợp lúc chạy")
    else:
        # Câu chào đầu cũng là thứ lấp đầy khoản đệm preroll. Ngắn hơn đệm thì
        # server vẫn phải chờ STT sinh thêm audio mới gửi được byte đầu, và cái
        # lợi "nghe ngay" mất sạch — nên nói rõ ra ở log thay vì để im.
        seconds = len(lead_in) / (tts.OUTPUT_SAMPLE_RATE * _BYTES_PER_SAMPLE)
        logger.info(
            "Câu chào đầu dài %.2fs (đệm preroll %.2fs)%s",
            seconds, config.AUDIO_PREROLL_SECONDS,
            "" if seconds >= config.AUDIO_PREROLL_SECONDS else " - NGẮN HƠN ĐỆM",
        )


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/internal/action-results")
async def receive_action_result(request: Request) -> dict:
    """Accept an idempotent backend callback on loopback only."""
    host = request.client.host if request.client else ""
    try:
        is_loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        is_loopback = False
    if not is_loopback:
        raise HTTPException(status_code=403, detail="Loopback callback only")

    expected = config.VISIONCARE_CALLBACK_TOKEN
    supplied = request.headers.get("authorization", "")
    if not expected:
        raise HTTPException(status_code=503, detail="Callback token is not configured")
    if not hmac.compare_digest(supplied, f"Bearer {expected}"):
        raise HTTPException(status_code=401, detail="Invalid callback token")

    envelope = await request.json()
    data = envelope.get("data") if isinstance(envelope, dict) else None
    if not isinstance(data, dict) or not data.get("request_id"):
        raise HTTPException(status_code=422, detail="Missing callback data/request_id")
    request_id = str(data["request_id"])
    idempotency_key = request.headers.get("idempotency-key", "")
    if idempotency_key != request_id:
        raise HTTPException(status_code=400, detail="Idempotency-Key must equal request_id")

    matched = action_callbacks.resolve(request_id, data)
    return {"status": "ok", "data": {"request_id": request_id, "matched": matched}}


def _stream_audio(
    speech_pieces: Iterable[str],
    idx: int,
    started: float,
    processing: float,
    encode: Callable[[Iterator[bytes]], Iterator[bytes]] | None = None,
    byte_rate: float | None = None,
    prelude: bytes = b"",
    debug_name: str | None = None,
    debug_wrap: Callable[[bytes], bytes] | None = None,
) -> Iterator[bytes]:
    """Đọc các mảnh text thành từng mảnh audio, vừa gửi vừa gom lại để ghi debug.

    `started` là mốc lúc request vào, `processing` là số giây STT/Gemini đã
    tiêu trước khi tới đây — cả hai chỉ dùng để ghi log đo thời gian.

    `encode` (vd. `tts.encode_adpcm`) bọc thêm quanh PCM để nén trước khi gửi;
    bỏ trống thì gửi PCM trần như cũ. `byte_rate` phải khớp định dạng đã chọn
    để đệm preroll tính đúng số byte cần gom trước khi gửi mảnh đầu.

    `prelude` (header WAV 60 byte của ADPCM) được nhả NGAY, trước cả khi gom
    preroll: board đọc header ngay trên luồng để cấu hình decoder, giữ nó lại
    chờ gom đủ đệm là bắt board chờ trắng đúng quãng đó. Nó không phải audio nên
    cũng không tính vào đệm.
    """
    collected: list[bytes] = []
    first_chunk_at = None
    stream = tts.synthesize_text_stream(speech_pieces)
    if encode is not None:
        stream = encode(stream)

    if prelude:
        yield prelude

    rate = byte_rate if byte_rate is not None else tts.OUTPUT_SAMPLE_RATE * _BYTES_PER_SAMPLE

    # Gom sẵn `AUDIO_PREROLL_SECONDS` giây audio rồi mới gửi byte đầu. Nhờ vậy
    # server luôn đi trước người nghe một quãng và MCU cứ đọc socket là có dữ
    # liệu — không cần ring buffer lớn phía thiết bị.
    preroll_bytes = int(config.AUDIO_PREROLL_SECONDS * rate)
    holding: list[bytes] = []
    held = 0

    recovered = False

    while True:
        try:
            chunk = next(stream)
        except StopIteration:
            break
        except Exception:  # noqa: BLE001
            if first_chunk_at is None and not prelude:
                # Chưa gửi byte nào -> để lỗi nổi lên cho endpoint đổi thành
                # câu báo lỗi. Nuốt ở đây thì MCU nhận HTTP 200 rỗng và người
                # khiếm thị không nghe gì, cũng không biết vì sao.
                #
                # Có `prelude` thì header WAV đã rời server rồi: không rút lại
                # được nữa, nên phải tự phục hồi ngay dưới đây thay vì ném lên.
                raise

            logger.exception("stream response%d đứt giữa chừng", idx)
            if recovered:
                break  # câu báo lỗi cũng hỏng nốt, không thử vòng nữa
            # Byte đầu đã rời server nên không đổi header được nữa, nhưng vẫn
            # nối thêm câu báo lỗi vào cuối. Dừng ngang ở đây thì người dùng
            # nghe cụt giữa câu rồi im — không có cách nào biết là hỏng hay hết.
            recovered = True
            stream = tts.synthesize_text_stream([_ERROR_MESSAGE])
            if encode is not None:
                stream = encode(stream)
            continue

        collected.append(chunk)

        if first_chunk_at is None:
            holding.append(chunk)
            held += len(chunk)
            if held < preroll_bytes:
                continue  # chưa đủ đệm, chưa gửi gì
            chunk = b"".join(holding)
            holding = []

        if first_chunk_at is None:
            first_chunk_at = time.monotonic() - started
        yield chunk

    # Câu trả lời ngắn hơn mức đệm (ví dụ câu báo lỗi) vẫn phải phát ra.
    if holding:
        if first_chunk_at is None:
            first_chunk_at = time.monotonic() - started
        yield b"".join(holding)

    payload = b"".join(collected)
    # ttfb là con số người dùng cảm nhận được (lúc bắt đầu nghe thấy tiếng);
    # tổng chỉ nói khi nào câu nói kết thúc. audio dài hơn (tổng - ttfb) nghĩa
    # là MCU phát kịp, không bị hụt tiếng giữa chừng. `rate` là byte-rate của
    # đúng định dạng đã gửi (PCM, ADPCM hay MP3 — cả ba đều CBR) nên phép chia
    # này luôn ra giây audio thật, không riêng gì PCM.
    logger.info(
        "request%d | xử lý=%.2fs ttfb=%.2fs tổng=%.2fs audio=%.2fs",
        idx,
        processing,
        first_chunk_at if first_chunk_at is not None else 0.0,
        time.monotonic() - started,
        len(payload) / rate,
    )

    # Ghi ra file MỞ ĐƯỢC BẰNG PLAYER, không phải nguyên xi thứ đã gửi: luồng
    # gửi đi cố tình không mang header (PCM trần) hoặc mang header độ dài giả
    # (`0xFFFFFFFF` cho ADPCM đang stream). `debug_wrap` bọc lại header thật.
    if payload and debug_name is not None:
        _save_debug_audio(
            debug_name, debug_wrap(payload) if debug_wrap is not None else payload
        )


class _Plan:
    """Mọi thứ khác nhau giữa các định dạng trả về, gom vào một chỗ.

    Trước đây chỉ có hai nhánh (PCM/MP3) nên một cặp `if/else` là đủ. Với ADPCM,
    mỗi định dạng còn khác nhau ở header đi trước, ở media type và ở cách bọc
    file debug — rải ba thứ đó ra ba chỗ trong endpoint là ba chỗ để quên.
    """

    __slots__ = ("encode", "byte_rate", "media_type", "prelude", "debug_name", "debug_wrap")

    def __init__(self, encode, byte_rate, media_type, prelude, debug_name, debug_wrap):
        self.encode = encode
        self.byte_rate = byte_rate
        self.media_type = media_type
        self.prelude = prelude
        self.debug_name = debug_name
        self.debug_wrap = debug_wrap


def _plan_for(response_format: str, idx: int) -> _Plan:
    if response_format == "adpcm_wav":
        # Định dạng board xếp hạng ưu tiên số 1: WAV IMA ADPCM. Header 60 byte
        # đi trước với cỡ khối `data` = 0xFFFFFFFF ("chưa biết, đang stream").
        return _Plan(
            tts.encode_adpcm, adpcm.BYTE_RATE, "audio/wav",
            adpcm.wav_header(None), f"response{idx}.wav",
            lambda payload: adpcm.wav_header(len(payload)) + payload,
        )

    if response_format == "adpcm_stream":
        # Chỉ các khối 256 byte, không header RIFF. Tiết kiệm 60 byte mỗi lượt
        # và bỏ hẳn chuyện phải khai một độ dài chưa biết; board lấy tham số
        # decoder từ `X-Audio-Format`.
        return _Plan(
            tts.encode_adpcm, adpcm.BYTE_RATE, "application/octet-stream",
            b"", f"response{idx}.wav",
            lambda payload: adpcm.wav_header(len(payload)) + payload,
        )

    if response_format == "mp3_stream":
        # Nén MP3 CBR 32kbps trước khi gửi: 1/8 dung lượng so với PCM trần,
        # đỡ tải WiFi/MCU. `wav` vẫn cần PCM trần (đóng gói WAV, không nén).
        return _Plan(
            tts.encode_mp3, float(tts.MP3_BYTE_RATE), "audio/mpeg",
            b"", f"response{idx}.mp3", None,
        )

    return _Plan(
        None, float(tts.OUTPUT_SAMPLE_RATE * _BYTES_PER_SAMPLE),
        "application/octet-stream", b"", f"response{idx}.wav", _pcm_to_wav,
    )


@app.post("/frame", status_code=204)
async def receive_frame(request: Request) -> Response:
    """Receive one JPEG on the independent fire-and-forget frame channel."""
    device_id = request.headers.get("x-device-id", "").strip()
    turn_id = request.headers.get("x-turn-id", "").strip()
    if not device_id:
        raise HTTPException(status_code=400, detail="Missing X-Device-Id")
    if not turn_id:
        raise HTTPException(status_code=400, detail="Missing X-Turn-Id")
    frame_bytes = await request.body()
    if not frame_bytes:
        raise HTTPException(status_code=400, detail="Empty frame body")
    frames.put(
        device_id,
        turn_id,
        frame_bytes,
        capture_ts=request.headers.get("x-capture-ts"),
    )
    logger.info(
        "frame() nhận device=%s turn=%s bytes=%d capture_ts=%s",
        device_id,
        turn_id,
        len(frame_bytes),
        request.headers.get("x-capture-ts"),
    )
    return Response(status_code=204)


@app.get("/events")
def stream_events(request: Request) -> StreamingResponse:
    """Keep one bounded, per-device SSE downlink open for the glasses."""
    device_id = request.headers.get("x-device-id", "").strip()
    if not device_id:
        raise HTTPException(status_code=400, detail="Missing X-Device-Id")
    return StreamingResponse(
        events.subscribe(device_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/process")
def process(
    request: Request,
    image: UploadFile | None = File(None),
    audio: UploadFile | None = File(None),
):
    """Xử lý một lệnh ảnh+audio, trả lời bằng audio stream phát dần được.

    Toàn bộ STT/OCR/Gemini chạy xong trước khi byte audio đầu tiên rời server,
    nên lỗi ở các bước đó vẫn đổi được thành câu báo lỗi bình thường. Chỉ bước
    TTS được stream — đó cũng là bước tốn giây, và là lý do người dùng phải
    đứng chờ trước khi nghe được gì.

    Sync def (không async): FastAPI chạy nó trong threadpool riêng thay vì
    trên event loop chính, nên STT/OCR/gọi Gemini/TTS của một request không
    chặn các request khác đang xử lý song song.

    T01: `device_id`/`turn_id` đọc từ header `X-Device-Id`/`X-Turn-Id`
    (CONTRACTS.md mục 2.1), xuống tới pipeline/handler qua `DEVICE_ID_CTX`/
    `TURN_ID_CTX` — KHÔNG qua tham số. Trùng `X-Turn-Id` trong cửa sổ
    idempotency thì trả lại đúng audio đã tổng hợp lần trước, không chạy lại
    pipeline.
    """
    device_id, turn_id = _resolve_device_turn(request)
    device_token = DEVICE_ID_CTX.set(device_id)
    turn_token = TURN_ID_CTX.set(turn_id)
    logger.info(
        "process() nhận X-Device-Id=%s X-Turn-Id=%s X-Capture-Ts=%s",
        device_id, turn_id, request.headers.get("x-capture-ts"),
    )
    try:
        # T01: xin quyền chạy pipeline cho (device_id, turn_id) — KHÔNG chỉ
        # tra "đã xong chưa", vì lượt trùng có thể tới trong lúc lượt đầu
        # CÒN ĐANG CHẠY DỞ (đúng ca "mất ACK giữa chừng, board tự thử lại"
        # nêu ở comment của `_IDEMPOTENCY_CACHE`) — đó là lúc `entry` mới
        # "pending", chưa có body nào để mà trả cả.
        kind, payload = _idempotent_begin(device_id, turn_id)
        if kind == "wait":
            # Lượt khác CÙNG (device_id, turn_id) đang chạy dở — đợi nó xong
            # rồi DÙNG LẠI kết quả, không tự chạy pipeline lần hai. Giới hạn
            # đợi bằng đúng cửa sổ idempotency: quá đó thì coi lượt kia là bỏ
            # hoang (crash/treo) và tự nhận quyền chạy — chấp nhận đợi tối đa
            # ngần ấy giây (đơn giản hơn tính phần thời gian còn lại của lượt
            # kia), xem docs/tasks/contract-deltas/T01.md.
            payload.wait(timeout=config.PROCESS_IDEMPOTENCY_WINDOW_SECONDS)
            kind, payload = _idempotent_begin(device_id, turn_id)

        if kind == "hit":
            cached = payload
            logger.info(
                "process() device=%s turn=%s trùng trong cửa sổ idempotency "
                "%.0fs — trả lại kết quả cũ, KHÔNG chạy lại pipeline",
                device_id, turn_id, config.PROCESS_IDEMPOTENCY_WINDOW_SECONDS,
            )
            if cached["response_format"] == "wav":
                return Response(
                    content=cached["body"], media_type=cached["media_type"]
                )
            return StreamingResponse(
                iter([cached["body"]]),
                media_type=cached["media_type"],
                headers=cached["headers"],
            )

        # kind == "own": chiếm được quyền chạy bình thường.
        # kind == "wait" (VẪN, sau khi đã đợi hết hạn): cực hiếm — một lượt
        # THỨ BA chen vào giữa, hoặc lượt đầu treo đúng lúc hết hạn đợi. Không
        # đợi thêm nữa (tránh treo người dùng), tự chạy pipeline luôn — NHƯNG
        # không tự nhận là chủ, để không ghi đè cache của người đang thật sự
        # giữ quyền.
        own_reservation = kind == "own"
        if not own_reservation:
            logger.warning(
                "process() device=%s turn=%s: đợi hết %.0fs mà lượt giữ "
                "quyền vẫn chưa xong — tự chạy pipeline, KHÔNG ghi cache "
                "(hiếm, xem docs/tasks/contract-deltas/T01.md)",
                device_id, turn_id, config.PROCESS_IDEMPOTENCY_WINDOW_SECONDS,
            )

        started = time.monotonic()
        idx = _next_debug_index()
        response_format = config.RESPONSE_FORMAT
        if response_format == "auto":
            response_format = _negotiate(request.headers.get("accept", ""))
        plan = _plan_for(response_format, idx)
        encode, byte_rate = plan.encode, plan.byte_rate

        try:
            if audio is None:
                pieces: Iterable[str] = [_MISSING_AUDIO_MESSAGE]
            else:
                # Ảnh không bắt buộc: `resolve_speech` nhận `None` và chỉ than
                # phiền khi intent thật sự cần ảnh.
                image_bytes = image.file.read() if image is not None else None
                # Board gửi ADPCM thô để đẩy được ngay trong lúc còn đang thu;
                # `ensure_wav` dựng lại header. File WAV thật vẫn đi qua nguyên vẹn.
                audio_bytes = adpcm.ensure_wav(
                    audio.file.read(), audio.content_type,
                )
                _save_debug_audio(f"request{idx}.wav", audio_bytes)
                if image_bytes:
                    _save_debug_image(idx, image_bytes)

                # Câu chào đi TRƯỚC, và `chain` giữ nó lười: `resolve_speech`
                # (kéo theo STT) chỉ chạy khi TTS đã lấy xong câu chào, nên
                # người dùng nghe thấy tiếng trong lúc STT còn đang chạy.
                # Xuống dòng ở cuối là dấu "câu trọn vẹn, đọc ngay" cho
                # `tts._sentences()`; thiếu nó thì câu chào nằm chờ mảnh text
                # sau, tức là chờ đúng STT mà nó sinh ra để khỏi phải chờ.
                # Câu chào này CŨNG là câu trấn an đầu tiên, nên câu kế tiếp phải
                # đếm từ lúc nó đọc xong. Đo chính xác vì audio của nó đã dựng sẵn.
                pieces = chain(
                    [_RECEIVED_MESSAGE + "\n"],
                    router.resolve_speech(
                        image_bytes, audio_bytes,
                        opening_seconds=tts.speaking_seconds(_RECEIVED_MESSAGE),
                    ),
                )

            # Kéo tới MẢNH ĐẦU TIÊN ở đây, còn trong try. Mọi thứ trên đường
            # tới đó — gọi Gemini, mất mạng giữa luồng text, TTS/encode lỗi —
            # vẫn đổi được thành câu báo lỗi nghe được. Sau mảnh này thì header
            # 200 đã gửi, không rút lại được nữa.
            #
            # Định dạng có `prelude` (ADPCM WAV) thì mảnh đầu chính là 60 byte
            # header và nó ra ngay lập tức — đúng yêu cầu của board, đổi lại lỗi
            # phía sau do `_stream_audio` tự nối câu báo lỗi vào luồng.
            audio_stream = _stream_audio(
                pieces, idx, started, time.monotonic() - started,
                encode=encode, byte_rate=byte_rate, prelude=plan.prelude,
                debug_name=plan.debug_name, debug_wrap=plan.debug_wrap,
            )
            body: Iterator[bytes] = chain([next(audio_stream)], audio_stream)
        except Exception:  # noqa: BLE001 - MCU must receive audio, never a JSON error.
            logger.exception("process() request%d thất bại", idx)
            body = _stream_audio(
                [_ERROR_MESSAGE], idx, started, time.monotonic() - started,
                encode=encode, byte_rate=byte_rate, prelude=plan.prelude,
                debug_name=plan.debug_name, debug_wrap=plan.debug_wrap,
            )

        if response_format == "wav":
            # Gom trọn rồi mới gửi: mất thời gian chờ, đổi lại MCU nhận một
            # file hoàn chỉnh có Content-Length, không phụ thuộc việc đường
            # truyền có giữ đều 32 KB/s hay không. Đã gom trọn sẵn nên lưu
            # thẳng vào cache idempotency, không cần tee — CHỈ khi mình thật
            # sự giữ quyền (`own_reservation`), xem nhánh "wait" ở trên.
            content = _pcm_to_wav(b"".join(body))
            if own_reservation:
                _idempotent_finish(
                    device_id, turn_id, "wav", "audio/wav", {}, content
                )
            return Response(content=content, media_type="audio/wav")

        stream_headers = _stream_headers(response_format)
        # `_bind_context`: giữ device_id/turn_id đúng cho phần audio sinh ra
        # SAU KHI process() đã return (Starlette kéo tiếp generator ở
        # thread/task khác). `_tee_and_cache`: gom lại đúng những gì đã gửi
        # để lượt gọi lặp `X-Turn-Id` kế tiếp có gì mà trả, không phải tính
        # toán lại — CHỈ gọi khi mình giữ quyền, xem nhánh "wait" ở trên;
        # không thì chỉ cần `_bind_context` (context vẫn phải đúng cho pipeline
        # chạy hộ), không ghi vào cache chung của người khác.
        bound_body = _bind_context(body)
        cached_body = (
            _tee_and_cache(
                bound_body, device_id, turn_id,
                response_format, plan.media_type, stream_headers,
            )
            if own_reservation
            else bound_body
        )
        return StreamingResponse(
            cached_body,
            media_type=plan.media_type,
            headers=stream_headers,
        )
    finally:
        DEVICE_ID_CTX.reset(device_token)
        TURN_ID_CTX.reset(turn_token)
