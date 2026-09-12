import contextvars
import glob
import io
import logging
import os
import re
import hmac
import ipaddress
import queue
import threading
import time
import wave
from collections.abc import Callable, Iterable, Iterator
from itertools import chain

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response, StreamingResponse

import config
from handlers import chat
from models import vlm
from pipeline import adpcm, intent_local, phrases, router, stt, tts
from services.action_callbacks import action_callbacks
from services import capabilities
from services.device_registry import devices
from services.firmware import firmware
from services.frame_buffer import frames
from services.events_channel import events
from services import turn_trace
# T24/W5: `/frame` hỏi worker xem thiết bị này còn được chấm không.
from services import hazard_worker
from services.hazard_risk import risk_engine
from services.incoming_calls import (
    announcement_for,
    incoming_call_audio,
    incoming_calls,
    sanitize_caller,
)

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
INCOMING_CALL_AUDIO_PATH = "/incoming-call/audio"


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
        headers = {
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
        # 🔴 `X-Audio-Format` CHỈ đi kèm thân THÔ. Với board, header này có
        # đúng một nghĩa: `parseAudioFormat()` (`src/audio/audio_format.cpp`)
        # đặt `fmt.raw = true` chỉ vì THẤY nó — nó không đọc thân, nên không
        # thể biết thân có container hay không.
        #
        # `adpcm_wav` gói thân trong RIFF, nên kèm header này là khai sai. Board
        # tự chữa bằng cách ngửi 4 byte đầu, và kêu lên (đo trên board thật
        # 2026-08-26):
        #
        #     CANH BAO: header x-audio-format bao du lieu THO, nhung than bat
        #     dau bang 'RIFF'.  Theo than — doc nhu file WAV. Server nen bo
        #     header do, hoac tra du lieu tho that su.
        #
        # Bỏ nó KHÔNG đổi một byte board phát ra: nhánh chọn đường phát trong
        # `audio_service.cpp` xét `isRiff` TRƯỚC `fmt.raw`, nên thân RIFF vốn
        # đã luôn đi đường `readWavHeader()`. Đổi lại, thân WAV còn khai được
        # tổng độ dài — thứ nhánh "thô" không có.
        #
        # Các header SỐ ở trên vẫn giữ cho cả hai: chúng không khai gì về đóng
        # gói, và người debug bằng curl đọc chúng.
        if response_format != "adpcm_wav":
            headers["X-Audio-Format"] = ADPCM_FORMAT
        return headers

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

    # T24/W4: nạp model nhận diện vật cản, nếu máy này có.
    #
    # Nạp ở đây chứ không nạp lười lúc người dùng bật chế độ: nạp ONNX mất
    # ~0.5s, và lúc người dùng nói "bật cảnh báo vật cản" là lúc họ sắp bước
    # đi — không phải lúc bắt họ đợi.
    #
    # Không có model thì `load_default()` trả None và `hazard_watch` từ chối
    # bật, nói thẳng ra. Server vẫn chạy bình thường: đây là một tính năng
    # thiếu, không phải một lỗi khởi động.
    # Độ sâu là tín hiệu CHÍNH, YOLO là phụ (đặt tên cho vật). Thiếu độ sâu
    # thì lui về YOLO một mình — nhưng lúc đó hệ MÙ với cột/tường/bậc thềm,
    # và `depth_detector.load_default()` ghi cảnh báo đúng câu đó vào log.
    from services.depth_detector import load_default as _load_obstacle_detector
    from services.hazard_detector import load_default as _load_yolo
    from services.hazard_risk import risk_engine

    risk_engine.set_detector(_load_obstacle_detector(_load_yolo()))
    # T25: sổ ghép đôi có xuống đĩa từ 2026-08-25 — đọc lại NGAY ở đây.
    #
    # 🔴 Không có dòng này thì mọi lần khởi động lại server, mọi chiếc kính lại
    # `paired_to: null`, và `emergency_call` trả `404 GLASSES_DEVICE_NOT_LINKED`
    # cho tới khi có người ghép lại bằng tay — mà không ai được báo.
    restored = devices.load_pairings()
    if restored:
        logger.info("Đọc lại %d cặp ghép đôi từ đĩa", restored)

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


def _require_internal_callback(request: Request) -> None:
    """Apply the same loopback + bearer policy to spontaneous device events."""
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


@app.post("/internal/device-events")
async def receive_device_event(request: Request) -> dict:
    """Accept spontaneous phone events without an action ``request_id``."""
    _require_internal_callback(request)
    envelope = await request.json()
    if not isinstance(envelope, dict):
        raise HTTPException(status_code=422, detail="Event body must be an object")
    device_id = str(envelope.get("device_id") or "").strip()
    event_type = envelope.get("type")
    if not device_id:
        raise HTTPException(status_code=422, detail="Missing device_id")

    from handlers import action_flow

    if event_type == "call_incoming":
        raw_caller = envelope.get("caller")
        if not isinstance(raw_caller, dict):
            raise HTTPException(status_code=422, detail="caller must be an object")
        try:
            caller = sanitize_caller(raw_caller)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        # Interrupt first. TTS preparation/event delivery happens afterwards so
        # it cannot delay the <=200 ms cut target. bump_generation never clears
        # Session.pending.
        started = time.monotonic()
        action_flow.bump_generation(device_id)
        interruption_ms = (time.monotonic() - started) * 1000
        incoming_calls.open(device_id, caller)
        queued = events.publish(
            device_id,
            {
                "type": "call_incoming",
                "caller": caller,
                # Kính nhận một sự kiện nhỏ ở lượt poll kế tiếp (≤2 s), rồi tự
                # kéo audio với X-Device-Id và khai báo Accept như thường lệ.
                "audio_url": INCOMING_CALL_AUDIO_PATH,
            },
        )
        return {
            "status": "ok",
            "data": {
                "type": event_type,
                # `queued` LUÔN ≥ 1 — hộp thư không đánh rơi. Muốn biết kính
                # có thật sự nghe được không thì đọc `downlink_open`, đừng
                # suy từ `queued`. Đây chính là chỗ kênh SSE cũ nói dối:
                # `subscribers: 1` mà sự kiện vẫn rơi vào hộp thư chết.
                "queued": queued,
                "downlink_open": events.downlink_open(device_id),
                "announcement": announcement_for(caller),
                "interruption_ms": round(interruption_ms, 3),
            },
        }

    if event_type == "call_ended":
        incoming_calls.close(device_id)
        queued = events.call_ended(device_id)
        return {
            "status": "ok",
            "data": {
                "type": event_type,
                "queued": queued,
                "downlink_open": events.downlink_open(device_id),
            },
        }
    raise HTTPException(status_code=422, detail="Unsupported device event type")


class _StallAwareStream:
    """Đọc một luồng byte, nhưng biết được lúc nào nguồn **đang đứng im**.

    🔴 Vì sao phải có (T21, đo được 2026-08-24):

    `_stream_audio()` gom `AUDIO_PREROLL_SECONDS` giây audio rồi mới gửi byte
    đầu. Câu mở đầu ("Đã tiếp nhận yêu cầu" / `warm_melodic`) đã **dựng sẵn**,
    ra khỏi TTS gần như tức thì — nhưng nó chỉ dài ~0.94 s, ngắn hơn mức đệm
    2.0 s. Nên vòng lặp giữ nó lại rồi **chặn ở `next(stream)` chờ mảnh kế
    tiếp** — mà mảnh kế tiếp chỉ có sau khi STT + Gemini + TTS chạy xong.

    Đo được: trung vị tiếng đầu **3.68 s**, `emergency_call` **4.82 s** so với
    ngân sách 300 ms. Người dùng đứng im nghe không thấy gì trong gần 4 giây,
    trong khi audio để phát cho họ **đã nằm sẵn trong RAM từ mili giây thứ 100**.

    Chờ thêm ở đây còn vô ích về mặt kỹ thuật: mức đệm sinh ra để phòng nguồn
    chậm hơn tốc độ phát, nhưng khi nguồn **dừng hẳn** thì chờ không gom thêm
    được byte nào — nó chỉ đổi im lặng lấy im lặng.

    Lớp này chạy một thread đọc nguồn và đẩy vào hàng đợi, nhờ vậy
    `_stream_audio()` đọc được **có hạn giờ**: hết hạn mà nguồn chưa nhả gì
    thêm thì nhả luôn chỗ đang giữ.

    Lỗi được chuyển nguyên vẹn sang bên đọc, đúng thứ tự với các mảnh trước nó
    — nhánh phục hồi "nối câu báo lỗi vào cuối" của `_stream_audio()` phụ
    thuộc vào điều đó.

    🔴 **KHÔNG đọc trước một mảnh nào.** Thread chỉ gọi `next(source)` sau khi
    bên đọc xin, đúng một lần mỗi lần xin. Bản đầu tiên của lớp này dùng hàng
    đợi 64 chỗ và thread tự do rút cạn nguồn — nó làm đỏ ngay hai test đã có
    sẵn từ trước (`test_stream_pcm_yields_each_chunk_before_synthesizing_the_next`
    và `test_preroll_does_not_wait_for_the_whole_answer`), và hai test đó đúng:
    tổng hợp trước phần chưa ai cần là đốt CPU cho audio mà người dùng có thể
    ngắt lời trước khi nghe tới, và là quay về đúng cái "gửi trọn gói" mà cả
    kiến trúc stream này sinh ra để tránh.
    """

    def __init__(self, source: Iterator[bytes]) -> None:
        self._queue: queue.Queue = queue.Queue()
        self._want = threading.Semaphore(0)
        self._pending = False
        self._stop = threading.Event()
        # 🔴 Chạy bơm TRONG bản sao Context của luồng request.
        #
        # Bơm này là thứ ĐẦU TIÊN advance generator của `synthesize_text_stream`,
        # nên toàn bộ pipeline (STT → intent → handler) thật ra chạy dưới nó.
        # Không chép context thì `DEVICE_ID_CTX`/`TURN_ID_CTX` (T01) và trace
        # G9 (T21) đều rỗng ở mọi chặng.
        #
        # Đã dính đúng lỗi này HAI lần trong cùng một phiên: sửa ở
        # `pipeline/tts.py` xong thì chỗ mất context chỉ dịch sang đây, vì lớp
        # này chen thêm một thread nữa vào giữa. Triệu chứng giống hệt nhau —
        # `ttfb_ms` đúng còn `stt_ms`/`intent_ms`/`handler_ms` bằng 0 — nên rất
        # dễ tưởng lần sửa trước không ăn.
        context = contextvars.copy_context()
        self._thread = threading.Thread(
            target=context.run, args=(self._pump, source), name="preroll-pump", daemon=True
        )
        self._thread.start()

    def _pump(self, source: Iterator[bytes]) -> None:
        while True:
            # Chờ bên đọc xin. Không xin thì KHÔNG chạm vào nguồn — đó là chỗ
            # giữ tính lười của cả đường stream.
            self._want.acquire()
            if self._stop.is_set():
                return
            try:
                self._queue.put(("chunk", next(source)))
            except StopIteration:
                self._queue.put(("done", None))
                return
            except BaseException as exc:  # noqa: BLE001 - chuyển nguyên vẹn sang consumer
                self._queue.put(("error", exc))
                return

    def get(self, timeout: float | None) -> tuple[str, object]:
        """`("chunk", bytes)` · `("error", exc)` · `("done", …)` · `("stall", None)`.

        `timeout=None` = chờ mãi (dùng sau khi đã gửi byte đầu — lúc đó không
        còn gì để vội, và trả về sớm chỉ tạo ra một vòng lặp bận).

        Trả `("stall", …)` **không** huỷ lời xin đang treo: thread vẫn đang
        chờ nguồn nhả mảnh đó. Lần gọi sau nhặt đúng mảnh ấy, không xin thêm —
        nếu không thì mỗi lần hết giờ lại kéo thêm một mảnh chưa ai cần.
        """
        if not self._pending:
            self._want.release()
            self._pending = True
        try:
            item = self._queue.get(timeout=timeout)
        except queue.Empty:
            return ("stall", None)
        self._pending = False
        return item

    def close(self) -> None:
        self._stop.set()
        self._want.release()   # gỡ thread khỏi acquire() để nó thoát


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

    # 🔴 Mức đệm có HẠN GIỜ, không chờ vô hạn — xem `_StallAwareStream`.
    # Không có hạn này thì câu mở đầu đã dựng sẵn nằm chờ trọn STT + Gemini,
    # và đó chính là 3.68 s trung vị đo được ở `measurements/G1.md`.
    pump = _StallAwareStream(stream)

    while True:
        try:
            # Còn đang gom đệm thì đọc CÓ HẠN GIỜ; đã gửi byte đầu rồi thì
            # chờ thoải mái (không còn gì để vội, và trả về sớm chỉ tạo ra
            # một vòng lặp bận đốt CPU của mọi request khác).
            kind, payload = pump.get(
                config.AUDIO_PREROLL_MAX_WAIT_SECONDS if first_chunk_at is None else None
            )
            if kind == "stall":
                if holding:
                    # Nguồn đứng im mà tay đang có audio: nhả ra. Giữ thêm chỉ
                    # đổi im lặng lấy im lặng — nguồn dừng thì không gom thêm
                    # được byte nào nữa.
                    chunk = b"".join(holding)
                    holding = []
                    held = 0
                    first_chunk_at = time.monotonic() - started
                    yield chunk
                continue
            if kind == "done":
                break
            if kind == "error":
                raise payload  # type: ignore[misc]
            chunk = payload  # type: ignore[assignment]
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
            # Bơm cũ đã hỏng — thay bằng bơm mới trên luồng câu báo lỗi. Dùng
            # lại bơm cũ thì nó vẫn đang đọc cái nguồn vừa ném lỗi.
            pump.close()
            pump = _StallAwareStream(stream)
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

    pump.close()

    payload = b"".join(collected)
    # ttfb là con số người dùng cảm nhận được (lúc bắt đầu nghe thấy tiếng);
    # tổng chỉ nói khi nào câu nói kết thúc. audio dài hơn (tổng - ttfb) nghĩa
    # là MCU phát kịp, không bị hụt tiếng giữa chừng. `rate` là byte-rate của
    # đúng định dạng đã gửi (PCM, ADPCM hay MP3 — cả ba đều CBR) nên phép chia
    # này luôn ra giây audio thật, không riêng gì PCM.
    total_seconds = time.monotonic() - started
    audio_seconds = len(payload) / rate
    logger.info(
        "request%d | xử lý=%.2fs ttfb=%.2fs tổng=%.2fs audio=%.2fs",
        idx,
        processing,
        first_chunk_at if first_chunk_at is not None else 0.0,
        total_seconds,
        audio_seconds,
    )

    # G9 + G11/T21. `ttfb` là dòng thứ nhất của bảng ngân sách; `release_rate`
    # là dòng thứ hai và nó đo một thứ KHÁC HẲN: (giây tiếng)/(giây đồng hồ)
    # từ mảnh đầu tới mảnh cuối. TTFB đạt mà tỉ lệ này dưới 1.30× thì board
    # đợi nhận xong cả câu mới phát — người dùng vẫn không nghe thấy gì sớm.
    # Hai dòng phải cùng xanh, nên phải cùng có mặt trong một trace.
    if first_chunk_at is not None:
        turn_trace.stage("ttfb", first_chunk_at)
        streaming_seconds = total_seconds - first_chunk_at
        if streaming_seconds > 0:
            turn_trace.annotate(
                release_rate=round(audio_seconds / streaming_seconds, 2),
                audio_seconds=round(audio_seconds, 2),
            )
    turn_trace.finish()

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


def _render_incoming_call_pcm(announcement: str) -> bytes:
    """Render one complete sentence so the caller-name prosody stays intact."""
    return b"".join(tts.synthesize_text_stream([announcement]))


def _incoming_call_audio_stream(caller: dict[str, object], plan: _Plan) -> Iterator[bytes]:
    """Encode cached mono/16 kHz PCM according to the normal board plan.

    For ADPCM WAV the 60-byte prelude is deliberately yielded before touching
    the dynamic TTS cache.  The board can configure its decoder while a first-
    time caller announcement is still being synthesized.
    """
    if plan.prelude:
        yield plan.prelude

    pcm = incoming_call_audio.get_or_create(caller, _render_incoming_call_pcm)
    if pcm is None:
        return
    encoded: Iterator[bytes] = iter([pcm])
    if plan.encode is not None:
        encoded = plan.encode(encoded)
    yield from encoded


@app.get(INCOMING_CALL_AUDIO_PATH)
def get_incoming_call_audio(request: Request):
    """Return the current device's caller announcement using /process audio.

    Contract for firmware: after a ``call_incoming`` SSE event, GET the event's
    ``audio_url`` with the same ``X-Device-Id`` and ``Accept`` headers used by
    the normal audio path.  A missing/expired call is 404; ``ring_only`` is 204.
    """
    device_id = request.headers.get("x-device-id", "").strip()
    if not device_id:
        raise HTTPException(status_code=400, detail="Missing X-Device-Id")
    call = incoming_calls.current(device_id)
    if call is None:
        raise HTTPException(status_code=404, detail="No active incoming call")
    if announcement_for(call.caller) is None:
        return Response(status_code=204, headers={"Cache-Control": "no-store"})

    response_format = config.RESPONSE_FORMAT
    if response_format == "auto":
        response_format = _negotiate(request.headers.get("accept", ""))
    plan = _plan_for(response_format, 0)

    # Debug/curl mode keeps the same complete PCM WAV behavior as /process.
    if response_format == "wav":
        pcm = incoming_call_audio.get_or_create(call.caller, _render_incoming_call_pcm)
        if pcm is None:  # guarded above; protects against a future policy race
            return Response(status_code=204, headers={"Cache-Control": "no-store"})
        return Response(
            content=_pcm_to_wav(pcm),
            media_type="audio/wav",
            headers={"Cache-Control": "no-store"},
        )

    headers = _stream_headers(response_format)
    # This URL is intentionally stable; intermediaries must never replay a
    # previous caller's bytes for a later call on the same device.
    headers["Cache-Control"] = "no-store"
    return StreamingResponse(
        _incoming_call_audio_stream(call.caller, plan),
        media_type=plan.media_type,
        headers=headers,
    )


_ORPHAN_HAZARD_STOPS: dict[str, float] = {}
_ORPHAN_HAZARD_LOCK = threading.Lock()


def _stop_orphan_hazard_stream(device_id: str) -> None:
    """Bảo board thôi canh khi server không còn chấm cho nó — xem `/frame`."""
    now = time.monotonic()
    with _ORPHAN_HAZARD_LOCK:
        last = _ORPHAN_HAZARD_STOPS.get(device_id, 0.0)
        if now - last < config.HAZARD_ORPHAN_STOP_COOLDOWN_S:
            return
        _ORPHAN_HAZARD_STOPS[device_id] = now

    logger.warning(
        "frame() device=%s đẩy khung hazard nhưng server không canh thiết bị "
        "này (mất cờ sau restart?) — gửi hazard_watch stop xuống board",
        device_id,
    )
    events.hazard_watch(device_id, "stop")


@app.post("/frame", status_code=204)
async def receive_frame(request: Request) -> Response:
    """Receive one JPEG on the independent fire-and-forget frame channel.

    T24/W2 mở rộng kênh này thay vì làm giao thức mới. ``X-Stream-Kind``:

    ``turn``    mặc định, hành vi cũ nguyên vẹn — cần ``X-Turn-Id``, vào ring
                1-3 khung của lượt hỏi-đáp (T17).
    ``hazard``  luồng canh vật cản — **không** cần ``X-Turn-Id`` (nó không
                thuộc lượt nào), vào ô riêng giữ đúng một khung mới nhất.

    Vì sao mở rộng chứ không tách endpoint: board mở **một** kết nối keep-alive
    và gọi lại đúng API đã xanh, không phải bắt tay TLS lại mỗi khung và không
    phải viết một đường mạng mới trên firmware. Cùng lý do đã khiến F2 bị huỷ.
    """
    device_id = request.headers.get("x-device-id", "").strip()
    turn_id = request.headers.get("x-turn-id", "").strip()
    stream_kind = (request.headers.get("x-stream-kind") or "turn").strip().lower()
    if not device_id:
        raise HTTPException(status_code=400, detail="Missing X-Device-Id")
    if stream_kind not in {"turn", "hazard"}:
        raise HTTPException(status_code=400, detail="X-Stream-Kind must be turn|hazard")
    # Chỉ luồng `turn` mới bắt buộc `X-Turn-Id` — giữ nguyên hợp đồng cũ.
    if stream_kind == "turn" and not turn_id:
        raise HTTPException(status_code=400, detail="Missing X-Turn-Id")

    frame_bytes = await request.body()
    if not frame_bytes:
        raise HTTPException(status_code=400, detail="Empty frame body")

    if stream_kind == "hazard":
        # 🔴 Board đang chụp mà server KHÔNG chấm: bảo nó dừng.
        #
        # Cờ `hazard_watching` nằm trong RAM (`action_flow`), nên restart server
        # giữa lúc đang canh là mất cờ — trong khi board không biết gì và vẫn
        # đẩy khung. Nó còn tiếp tục kêu tít ở MỨC CUỐI nhận được, vì
        # `hazard_level` chỉ gửi khi đổi mức. Người dùng nghe cảnh báo về một
        # cái cột đã đi qua từ trước lúc restart, và pin thì vẫn cạn.
        #
        # Đây là chỗ DUY NHẤT server biết được board còn đang canh, nên chỗ
        # sửa phải ở đây. Nhịp lại bằng `HAZARD_ORPHAN_STOP_COOLDOWN_S`: hàng
        # đợi SSE 8 chỗ sẽ đầy trong vài giây nếu lệnh dừng đi theo nhịp khung.
        if device_id not in hazard_worker.worker.watching():
            _stop_orphan_hazard_stream(device_id)
            return Response(status_code=204)

        frames.put_hazard(
            device_id,
            frame_bytes,
            capture_ts=request.headers.get("x-capture-ts"),
        )

        # T24/W5: chấm NGAY và trả mức trong chính response này.
        #
        # Board chờ response rồi mới chụp khung kế, nên mỗi thiết bị chỉ có
        # đúng MỘT request đang bay — không có ca dồn hàng mà một vòng lặp nền
        # phải cố công tránh. Đổi lại board giữ được MỘT phiên TLS keep-alive
        # (mức không cần đi đường SSE nữa), và bắt tay 616–911 ms biến mất
        # khỏi vòng canh. Xem `services/hazard_worker.py` phần đầu file.
        scored = hazard_worker.worker.score_frame(device_id, frame_bytes)
        if scored is None:
            # Chấm hỏng. 204 = "đã nhận, không có mức nào cho anh" — board giữ
            # nguyên mức cuối thay vì tự cho là an toàn.
            return Response(status_code=204)

        level, changed = scored
        # KHÔNG log mỗi khung: luồng này chạy vài khung mỗi giây và sẽ chôn
        # vùi mọi dòng log khác trong vài phút. `score_frame()` đã log lúc ĐỔI.
        return JSONResponse(
            {"level": level, "changed": changed},
            headers={"Cache-Control": "no-store"},
        )

    # 🔴 `X-Frame-Tier` đã BỎ 2026-08-26 cùng toàn bộ F5. Board gửi đúng một
    # loại ảnh (XGA 1024×768) cho mọi lượt. Header cũ, nếu một board chưa nạp
    # lại vẫn gửi, được BỎ QUA chứ không trả 400: firmware và server nâng cấp
    # lệch nhau là chuyện thường, và từ chối khung ảnh của một board cũ nghĩa
    # là người dùng nghe "không nhận được ảnh từ kính" cho tới khi họ nạp lại.
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


# ─── T25: OTA kéo qua internet + sổ thiết bị ──────────────────────────────
#
# Kính KHÔNG cùng mạng với server. Đường phát hành duy nhất chạy được là kính
# tự hỏi rồi tự kéo, qua đúng tên miền/cổng nó vẫn dùng. Xem
# `services/firmware.py` và `src/net/ota_manager.h` bên repo firmware.


def _device_from_headers(request: Request) -> str:
    """`X-Device-Id` bắt buộc, và ghi nhận luôn bản firmware kính đang chạy.

    KHÔNG rơi về `config.VISIONCARE_DEVICE_ID` như `/process` — RUNBOOK mục 7
    cấm đúng chuyện đó, và ở đây còn tệ hơn: rơi nhầm nghĩa là đẩy firmware
    hoặc Wi-Fi của kính này xuống kính khác.
    """
    device_id = request.headers.get("x-device-id", "").strip()
    if not device_id:
        raise HTTPException(status_code=400, detail="Missing X-Device-Id")
    devices.seen(
        device_id,
        fw_version=request.headers.get("x-fw-version"),
        wifi_ssid=request.headers.get("x-wifi-ssid"),
    )
    return device_id


@app.get("/firmware/manifest")
def firmware_manifest(request: Request) -> dict:
    """Kính hỏi: có bản mới cho tôi không?

    Trả `{"update": false, ...}` là câu trả lời BÌNH THƯỜNG, không phải lỗi —
    đó là câu trả lời của gần như mọi lần hỏi.
    """
    device_id = _device_from_headers(request)
    current = (request.headers.get("x-fw-version") or "").strip()
    manifest = firmware.manifest_for(current or None)
    logger.info(
        "firmware_manifest() device=%s dang_chay=%s -> %s",
        device_id,
        current or "(không khai báo)",
        manifest.get("version") if manifest.get("update") else manifest.get("reason"),
    )
    return manifest


@app.get("/firmware/bin")
def firmware_binary(request: Request, version: str = ""):
    """Trả ảnh firmware nhị phân cho kính ghi thẳng vào slot OTA.

    `version` là BẮT BUỘC dù manifest vừa nói bản nào: không có nó thì một
    kính đang tải dở sẽ nhận nửa bản cũ nửa bản mới khi bản phát hành đổi
    giữa chừng — và ảnh ghép đó vẫn ghi "thành công", chỉ chết lúc khởi động.
    """
    _device_from_headers(request)
    build = firmware.get(version) if version else firmware.latest()
    if build is None:
        raise HTTPException(status_code=404, detail="No such firmware version")
    return Response(
        content=build.path.read_bytes(),
        media_type="application/octet-stream",
        headers={
            "Content-Length": str(build.size),
            # Kính đối chiếu digest TRƯỚC `Update.end()`. Gửi kèm ở header nữa
            # để `curl -D -` kiểm được mà không phải mở manifest.
            "X-Firmware-Sha256": build.sha256,
            "X-Firmware-Version": build.version,
            "Cache-Control": "no-store",
        },
    )


@app.post("/internal/firmware/push")
async def push_firmware_update(request: Request) -> dict:
    """Bảo một (hoặc mọi) kính đi lấy bản mới ngay, không đợi vòng hỏi 6 giờ.

    Thân: `{"device_id": "glasses-01"}` — thiếu `device_id` thì đẩy cho MỌI
    kính đang chạy bản khác bản phát hành.
    """
    _require_internal_callback(request)
    envelope = await request.json() if await request.body() else {}
    if not isinstance(envelope, dict):
        raise HTTPException(status_code=422, detail="Body must be an object")

    build = firmware.latest()
    if build is None:
        raise HTTPException(status_code=409, detail="No firmware released")

    target = str(envelope.get("device_id") or "").strip()
    if target:
        candidates = [target]
    else:
        candidates = [
            item["device_id"]
            for item in devices.snapshot()
            if item["fw_version"] != build.version
        ]

    # Xếp hàng KỂ CẢ khi kính đang không poll. Khác `wifi_config` bên dưới:
    # nạp firmware là việc luôn đúng để làm bất cứ khi nào kính quay lại, và
    # `GET /firmware/manifest` là nguồn sự thật nên một sự kiện cũ không đẩy
    # được board sang bản sai. `downlink_open` đi kèm để bên gọi biết ngay bây
    # giờ nó có tới hay không.
    pushed: dict[str, int] = {}
    for device_id in candidates:
        events.firmware_update(device_id, build.version)
        pushed[device_id] = events.downlink_open(device_id)
        devices.mark_update_pushed(device_id, build.version)
    return {"status": "ok", "data": {"version": build.version, "pushed": pushed}}


@app.post("/internal/device/wifi")
async def push_wifi_config(request: Request) -> dict:
    """App đổi Wi-Fi cho kính từ xa, qua kênh xuống `GET /downlink`.

    Đường này chỉ chạy khi kính CÒN mạng cũ. Kính đã mất mạng thì hai lối còn
    lại là BLE (`src/net/ble_provision.h`) và SoftAP `VisionCare-Setup`
    (`src/net/wifi_provision.h`).
    """
    _require_internal_callback(request)
    envelope = await request.json()
    if not isinstance(envelope, dict):
        raise HTTPException(status_code=422, detail="Body must be an object")

    device_id = str(envelope.get("device_id") or "").strip()
    ssid = str(envelope.get("ssid") or "").strip()
    if not device_id or not ssid:
        raise HTTPException(status_code=422, detail="device_id and ssid are required")

    # 🔴 Kiểm TRƯỚC khi xếp hàng, và KHÔNG xếp hàng nếu kính đang mất tích.
    #
    # Khác hẳn `firmware_update` ở trên. Một `wifi_config` nằm chờ trong hộp
    # thư sẽ nổ vào mặt người dùng lúc kính quay lại — có thể là hàng giờ sau,
    # trên đúng mạng đang chạy tốt — và đá nó sang mạng họ đã thôi không muốn
    # nữa. Đổi Wi-Fi là việc phải xảy ra BÂY GIỜ hoặc không xảy ra.
    if not events.downlink_open(device_id):
        age = events.last_poll_age_seconds(device_id)
        logger.info(
            "push_wifi_config() device=%s: kính không giữ kênh xuống (lần poll cuối: %s)",
            device_id,
            "chưa bao giờ" if age is None else f"{age:.0f}s trước",
        )
        raise HTTPException(
            status_code=409,
            detail=(
                "Glasses are not polling /downlink; use BLE provisioning or the "
                "VisionCare-Setup hotspot"
            ),
        )

    # 🔴 KHÔNG log `password`. Xem ghi chú ở `EventHub.wifi_config()`.
    queued = events.wifi_config(device_id, ssid, str(envelope.get("password") or ""))
    logger.info("push_wifi_config() device=%s ssid=%s queued=%d", device_id, ssid, queued)
    return {"status": "ok", "data": {"queued": queued, "downlink_open": True}}


def _require_app_token(request: Request) -> None:
    """Cửa cho **app điện thoại**, khác cửa `/internal/*` của server app.

    `_require_internal_callback()` đòi loopback vì phía gọi nó là server app
    8001 chạy cùng máy. App điện thoại thì không — nó ở ngoài internet, đi vào
    qua Cloudflare tunnel. Bắt loopback ở đây nghĩa là tính năng không tồn tại.

    🔴 Đánh đổi đã biết, ghi ra để phiên sau không tưởng là sơ suất: cửa này
    chỉ có MỘT lớp là bearer token dùng chung. Token lộ = ai đó đổi được Wi-Fi
    và ép nạp firmware cho kính của người khác. Ba thứ bù lại, và cả ba đều
    phải còn nguyên:
      1. chặng vào đã là TLS (Cloudflare tunnel), token không đi bản rõ;
      2. mọi lệnh đều khoá theo `X-Device-Id` — không có lệnh "cho tất cả";
      3. firmware kính nạp về vẫn phải khớp `sha256` của server.
    Muốn chặt hơn thì đổi sang token theo từng thiết bị — xem
    `docs/tasks/T25-ota-provisioning.md` mục 7 câu 1.
    """
    expected = config.DEVICE_CONTROL_TOKEN
    if not expected:
        raise HTTPException(status_code=503, detail="Device control token is not configured")
    supplied = request.headers.get("authorization", "")
    if not hmac.compare_digest(supplied, f"Bearer {expected}"):
        raise HTTPException(status_code=401, detail="Invalid device control token")


@app.get("/internal/traces")
def list_traces(request: Request, limit: int = 200) -> dict:
    """G9/T21: 200 lượt gần nhất, để `tools/measure_budget.py` dựng bảng G1.

    Loopback-only: trace mang `device_id` và nội dung intent của từng lượt —
    đủ để dựng lại người dùng vừa làm gì, cả ngày.

    Không có endpoint tương ứng cho app: đây là dữ liệu chẩn đoán của người
    vận hành, không phải của người đeo kính.
    """
    _require_internal_callback(request)
    return {
        "status": "ok",
        "data": {"traces": [trace.as_dict() for trace in turn_trace.traces.recent(limit)]},
    }


@app.get("/internal/hazard")
def hazard_status(request: Request) -> dict:
    """T24/W5: vòng canh có THẬT SỰ chạy không, trả lời bằng số.

    🔴 Vì sao cần một endpoint riêng cho việc này: luồng canh **cố ý không log
    mỗi khung** (vài khung mỗi giây sẽ chôn vùi mọi dòng log khác trong vài
    phút), và `hazard_level` chỉ ghi log khi ĐỔI mức. Nên "board đang đẩy khung
    đều đặn, cảnh vẫn SAFE" và "board không đẩy khung nào" nhìn từ log là **y
    hệt nhau** — cả hai đều im lặng.

    Đó chính xác là cách T24 hỏng mà không ai biết: `fps=0.00 (0 khung)` trên
    board, và server thì không có gì để nói.

    Loopback-only như `/internal/traces`: đây là dữ liệu vận hành.
    """
    _require_internal_callback(request)
    worker = hazard_worker.worker
    watching = sorted(worker.watching())
    return {
        "status": "ok",
        "data": {
            "watching": watching,
            "scored": worker.scored,
            "errors": worker.errors,
            "levels": {
                device_id: risk_engine.current_level(device_id)
                for device_id in watching
            },
            "frames_waiting": {
                device_id: frames.latest_hazard(
                    device_id, max_age_ms=config.HAZARD_FRAME_MAX_AGE_MS
                ) is not None
                for device_id in watching
            },
            # 🔴 Hai số này phân biệt ba ca nhìn giống hệt nhau từ ngoài:
            #   downlink_open=false          -> kính không poll: mất mạng, hoặc
            #                                   đang bận cả phút — lỗi đường xuống
            #   open=true, queued>0 mãi      -> kính poll nhưng không rút được?
            #                                   không xảy ra được, nghi server
            #   open=true, queued=0, im lặng -> board nhận rồi mà không làm —
            #                                   lỗi ở phía firmware
            # Thiếu chúng thì mọi lần gỡ lỗi đều bắt đầu bằng một cuộc đoán.
            "downlink_open": {
                device_id: events.downlink_open(device_id)
                for device_id in watching
            },
            "downlink_last_poll_seconds": {
                device_id: (
                    None if (age := events.last_poll_age_seconds(device_id)) is None
                    else round(age, 1)
                )
                for device_id in watching
            },
            "downlink_queued": {
                device_id: events.queued_count(device_id)
                for device_id in watching
            },
        },
    }


@app.get("/devices")
def list_devices() -> dict:
    """Danh sách kính đã từng gọi tới — app dùng để hiện trạng thái ghép đôi.

    Mỗi bản ghi có `wifi_ssid`: người dùng phải THẤY kính đang đăng ký mạng
    nào thì mới biết phải cấp mạng nào cho nó. Không có dòng đó thì họ chỉ
    thấy "kính không nối được" và chỉ còn cách đoán.
    """
    return {"status": "ok", "data": {"devices": devices.snapshot()}}


@app.get("/device/status")
def device_status(request: Request) -> dict:
    """Trạng thái MỘT kính, kèm câu trả lời "có bản firmware mới không".

    Gộp hai thứ app cần vào một lần gọi: màn hình "Kính của tôi" hiện đủ số
    máy, mạng đang dùng, bản đang chạy, và nút cập nhật — một vòng mạng.
    """
    _require_app_token(request)
    device_id = request.query_params.get("device_id", "").strip()
    if not device_id:
        raise HTTPException(status_code=400, detail="Missing device_id")

    record = devices.get(device_id)
    build = firmware.latest()
    return {
        "status": "ok",
        "data": {
            "device_id": device_id,
            "serial": record.serial if record else device_id.removeprefix("glasses-"),
            # `known: false` = kính này chưa gọi tới server lần nào. KHÁC hẳn
            # `online: false` (đã từng gọi, giờ im) — app phải nói hai câu khác
            # nhau, vì cách xử lý của người dùng khác nhau: một bên là "kiểm
            # lại số máy", một bên là "kiểm lại mạng của kính".
            "known": record is not None,
            "online": devices.is_online(device_id),
            "wifi_ssid": record.wifi_ssid if record else None,
            "fw_version": record.fw_version if record else None,
            "paired_to": record.paired_to if record else None,
            "seconds_since_seen": (
                round(time.monotonic() - record.last_seen, 1) if record else None
            ),
            "latest_version": build.version if build else None,
            "update_available": bool(
                build is not None and record is not None and record.fw_version != build.version
            ),
            # Kính có đang poll `GET /downlink` không — quyết định đổi Wi-Fi
            # từ xa có chạy được không. Không poll thì app phải chỉ người dùng
            # sang BLE hoặc hotspot VisionCare-Setup.
            "downlink_open": events.downlink_open(device_id),
            "downlink_last_poll_seconds": (
                None if (age := events.last_poll_age_seconds(device_id)) is None
                else round(age, 1)
            ),
        },
    }


@app.post("/device/wifi")
async def app_set_wifi(request: Request) -> dict:
    """App đổi Wi-Fi cho kính từ xa. Cùng đường với `/internal/device/wifi`."""
    _require_app_token(request)
    envelope = await request.json()
    if not isinstance(envelope, dict):
        raise HTTPException(status_code=422, detail="Body must be an object")
    device_id = str(envelope.get("device_id") or "").strip()
    ssid = str(envelope.get("ssid") or "").strip()
    if not device_id or not ssid:
        raise HTTPException(status_code=422, detail="device_id and ssid are required")

    # Kiểm TRƯỚC khi xếp hàng — cùng lý do như `/internal/device/wifi`: một
    # `wifi_config` nằm chờ sẽ đá kính ra khỏi mạng đang chạy tốt, hàng giờ
    # sau, lúc không ai mong đợi.
    if not events.downlink_open(device_id):
        raise HTTPException(
            status_code=409,
            detail=(
                "Glasses are not polling /downlink; use BLE provisioning or the "
                "VisionCare-Setup hotspot"
            ),
        )

    # 🔴 KHÔNG log `password`.
    queued = events.wifi_config(device_id, ssid, str(envelope.get("password") or ""))
    logger.info("app_set_wifi() device=%s ssid=%s queued=%d", device_id, ssid, queued)
    return {"status": "ok", "data": {"queued": queued, "downlink_open": True}}


@app.post("/device/firmware-update")
async def app_request_firmware_update(request: Request) -> dict:
    """App bấm "cập nhật ngay" — không đợi vòng hỏi 6 giờ của kính."""
    _require_app_token(request)
    envelope = await request.json() if await request.body() else {}
    device_id = str((envelope or {}).get("device_id") or "").strip()
    if not device_id:
        raise HTTPException(status_code=422, detail="device_id is required")

    build = firmware.latest()
    if build is None:
        raise HTTPException(status_code=409, detail="No firmware released")

    # Xếp hàng dù kính có đang poll hay không: nạp firmware là việc luôn đúng
    # để làm khi kính quay lại, và `GET /firmware/manifest` mới là nguồn sự
    # thật nên một sự kiện cũ không đẩy được board sang bản sai.
    #
    # KHÔNG còn 409 ở đây (kênh SSE cũ trả 409 khi `subscribers == 0`): với
    # hộp thư poll thì sự kiện không mất, chỉ tới muộn. Trả 200 kèm
    # `downlink_open` để app tự nói "sẽ cập nhật khi kính online" thay vì báo
    # đỏ một việc thật ra đã nhận.
    events.firmware_update(device_id, build.version)
    devices.mark_update_pushed(device_id, build.version)
    return {
        "status": "ok",
        "data": {
            "version": build.version,
            "downlink_open": events.downlink_open(device_id),
        },
    }


@app.post("/internal/device/pair")
async def pair_device(request: Request) -> dict:
    """Ghép một kính (theo số máy hoặc `device_id`) với một điện thoại."""
    _require_internal_callback(request)
    envelope = await request.json()
    if not isinstance(envelope, dict):
        raise HTTPException(status_code=422, detail="Body must be an object")

    phone = str(envelope.get("phone") or "").strip()
    device_id = str(envelope.get("device_id") or "").strip()
    serial = str(envelope.get("serial") or "").strip()
    if not phone or not (device_id or serial):
        raise HTTPException(
            status_code=422, detail="phone and one of device_id/serial are required"
        )

    if not device_id:
        # Người dùng gõ số in trên vỏ kính ("01"). Kính chưa từng gọi tới thì
        # chưa có bản ghi nào để tra — dựng `device_id` theo đúng quy ước của
        # firmware để ghép trước vẫn chạy được.
        record = devices.resolve_by_serial(serial)
        device_id = record.device_id if record else f"glasses-{serial}"

    record = devices.pair(device_id, phone)
    return {
        "status": "ok",
        "data": {"device_id": record.device_id, "serial": record.serial, "paired_to": phone},
    }


@app.get("/downlink")
def poll_downlink(request: Request) -> JSONResponse:
    """Rút cạn hộp thư của một kính. Thay `GET /events` (SSE) từ 2026-08-26.

    Board gọi mỗi ~2 giây và CHỈ KHI RẢNH — không đang `/process`, không đang
    phát tiếng, không đang OTA. Đó là toàn bộ lý do thiết kế này tồn tại: nó
    bảo đảm board không bao giờ giữ hai phiên TLS cùng lúc, mà mỗi phiên TLS
    ngốn 45 056 B RAM liền trên tổng số ~114 KB nó có. Kênh SSE cũ giữ kết nối
    thường trực nên vi phạm điều đó liên tục, và hệ quả đo được là
    `firmware_update` trả `pushed: 0` còn `wifi_config` rơi vào hộp thư chết.

    Trả HẾT sự kiện đang chờ trong một lượt, không trả từng cái: bốn sự kiện
    xếp hàng mà trả nhỏ giọt thì mất 8 giây mới đi hết, và trong đó có thể có
    `call_incoming`.

    KHÔNG cache: `Cache-Control: no-store` là bắt buộc — kênh này đi qua
    Cloudflare tunnel, và một lượt poll được cache lại nghĩa là board đọc mãi
    một hộp thư cũ.
    """
    device_id = request.headers.get("x-device-id", "").strip()
    if not device_id:
        raise HTTPException(status_code=400, detail="Missing X-Device-Id")
    devices.seen(
        device_id,
        fw_version=request.headers.get("x-fw-version"),
        wifi_ssid=request.headers.get("x-wifi-ssid"),
    )
    pending = events.drain(device_id)
    if pending:
        # Chỉ log khi CÓ gì để trả. Board poll mỗi 2 giây, tức 43 200 lượt mỗi
        # ngày — log mỗi lượt sẽ chôn vùi mọi dòng khác.
        logger.info(
            "downlink: trả %d sự kiện cho %s (%s)",
            len(pending),
            device_id,
            ", ".join(str(e.get("type")) for e in pending),
        )
    return JSONResponse(
        {
            "status": "ok",
            "data": {
                "events": pending,
                # Board giữ hằng của riêng nó; số này để nó đối chiếu và để
                # chẩn đoán từ xa biết server mong nhịp nào.
                "poll_after_ms": config.DOWNLINK_POLL_HINT_MS,
            },
        },
        headers={"Cache-Control": "no-store"},
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
    # Nút khẩn cấp (bấm 3 lần trên gọng kính). Đi chung `/process` chứ KHÔNG
    # có endpoint riêng, và đó là lựa chọn có chủ đích: `/process` đã có sẵn
    # idempotency theo `X-Turn-Id`, trace G9, và đường trả audio stream mà
    # board đã biết đọc. Một endpoint mới phải dựng lại cả bốn thứ đó — bốn
    # chỗ nữa để sai, trên đúng con đường không được phép sai.
    #
    # Idempotency đặc biệt quan trọng ở đây: nút bấm dồn dập rất dễ sinh hai
    # request cho cùng một sự kiện, và hai cuộc gọi cấp cứu là một sự cố thật.
    panic = request.headers.get("x-trigger", "").strip().lower() == "emergency"
    # T25: mỗi lượt bấm nút cũng là một lần điểm danh — server biết kính nào
    # đang chạy bản firmware nào và đang ở mạng nào mà KHÔNG tốn thêm một
    # vòng hỏi nào. Đặt sau `_resolve_device_turn()` để dùng đúng `device_id`
    # đã qua chính sách thiếu-header của T01.
    devices.seen(
        device_id,
        fw_version=request.headers.get("x-fw-version"),
        wifi_ssid=request.headers.get("x-wifi-ssid"),
    )
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
        # G9/T21: mở trace cho lượt này. Mọi chặng bên dưới (STT, intent,
        # handler trong `pipeline/router.py`; TTFB ở `_stream_audio`) ghi vào
        # đây, và `finish()` in đúng MỘT dòng khoá bằng `turn_id`.
        #
        # Mở SAU cửa idempotency: một lượt gửi lặp trả lại audio đã có sẵn thì
        # không chạy chặng nào cả, và ghi nó vào bảng p50 sẽ kéo mọi con số
        # xuống một cách vô nghĩa.
        turn_trace.begin(device_id, turn_id)
        idx = _next_debug_index()
        response_format = config.RESPONSE_FORMAT
        if response_format == "auto":
            response_format = _negotiate(request.headers.get("accept", ""))
        plan = _plan_for(response_format, idx)
        encode, byte_rate = plan.encode, plan.byte_rate

        try:
            if panic:
                # Bấm nút 3 lần. Đặt TRƯỚC nhánh `audio is None` vì lượt panic
                # CỐ Ý không mang audio — rơi xuống dưới thì người đang cần cấp
                # cứu nghe được đúng câu "không nhận được tiếng nói".
                #
                # Ảnh vẫn đọc nếu board kịp gửi: `emergency_call` không dùng
                # ảnh, nhưng phía tiếp nhận cuộc gọi có thể dùng, và bỏ đi thì
                # không lấy lại được.
                image_bytes = image.file.read() if image is not None else None
                pieces: Iterable[str] = chain(
                    [_RECEIVED_MESSAGE + "\n"],
                    router.resolve_panic(image_bytes),
                )
            elif audio is None:
                pieces = [_MISSING_AUDIO_MESSAGE]
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
