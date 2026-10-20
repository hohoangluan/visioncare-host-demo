# Phải đứng đầu, trước mọi thứ có thể kéo sherpa_onnx vào: xem `pipeline/stt.py`.
import onnxruntime  # noqa: F401, I001

import asyncio
import concurrent.futures
import contextlib
import glob
import io
import logging
import os
import re
import hmac
import ipaddress
import time
import wave
from collections.abc import Callable, Iterable, Iterator
from itertools import chain

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile, WebSocket
from fastapi.responses import JSONResponse, Response, StreamingResponse
from starlette.concurrency import run_in_threadpool

import config
from handlers import chat
from pipeline import adpcm, cues, device_ctx, final_router, guard, phrases, stt, tts
from pipeline import metrics
from pipeline import turn as turn_v2
from pipeline.image_buffer import image_buffer
from pipeline.reply import Reply
from services.action_callbacks import action_callbacks

logger = logging.getLogger("blind_assist")

# Uvicorn chỉ cấu hình logger của riêng nó; không có dòng này thì log INFO đo
# thời gian bên dưới bị root logger (mặc định WARNING) nuốt mất.
# Mỗi dòng mang [device turn] của lượt đang chạy (pipeline/metrics.py).
logging.basicConfig(level=logging.INFO, format=metrics.LOG_FORMAT)
# httpx ghi URL ĐẦY ĐỦ (cả query) ở INFO: SerpAPI truyền `api_key` trên query nên khoá lọt vào log.
for _noisy in ("httpx", "httpcore"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)
metrics.install_log_filter()

app = FastAPI(title="Blind-Assist Audio Server")
app.add_middleware(guard.ProcessBodyGuard)

PCM_FORMAT = f"pcm_s16le;rate={tts.OUTPUT_SAMPLE_RATE};channels=1"
_BYTES_PER_SAMPLE = 2


MP3_FORMAT = f"mp3;bitrate={tts.MP3_BITRATE_KBPS}kbps;rate={tts.OUTPUT_SAMPLE_RATE};channels=1"

# Chuỗi board đọc để tự cấu hình decoder ADPCM (`docs/HUONG_DAN_SERVER.md` §2B).
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
    *final_router.STATIC_SPEECH,
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


@app.exception_handler(guard.GuardError)
async def _guard_error(request: Request, exc: guard.GuardError) -> JSONResponse:
    return JSONResponse({"error": exc.error}, status_code=exc.status)


@app.on_event("startup")
def preload_models() -> None:
    """Load STT/TTS và chạy thử mỗi model 1 lần.

    Lần infer đầu tiên của mỗi model tốn thêm thời gian khởi tạo (warm-up
    kernel, dựng batch engine...) so với các lần sau. Trả trước chi phí đó ở
    đây để request thật đầu tiên của người dùng không phải gánh thêm warm-up
    này — bấm gửi post là có kết quả ngay.

    Không còn model cục bộ nào cho ảnh. Gemini cũng không còn trên đường chạy:
    `/process` đi chung pipeline v2 (Gemma) với `/v2/turn`, nên không warm client
    Gemini hay bộ phân loại ý định cục bộ nữa (Task 12).
    """
    guard.log_startup()
    stt._load_asr()
    stt.transcribe(_dummy_wav())

    # Vị trí điện thoại: lấy ở nền, không bao giờ trên đường request. Một vòng
    # `location/get` là poll xuống điện thoại tới 12s — đặt nó trong request là
    # bắt người dùng đứng chờ ngần ấy trước khi nghe được chữ nào.
    chat.start_location_refresher()
    tts._load_tts()
    # Tiêu thụ hết generator: warm-up phải đi đúng đường stream mà /process
    # dùng, vì phiên giải mã theo frame của infer_stream có warm-up riêng.
    for _ in tts.synthesize_stream("Khởi động"):
        pass

    # Dựng sẵn audio cho mọi câu cố định. Lần đầu tốn một hai phút; các lần sau
    # đọc lại từ đĩa nên gần như tức thì.
    phrases.warm(extra=STATIC_SPEECH)

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


def _require_callback_auth(request: Request) -> None:
    """Callback của backend: chỉ từ `CALLBACK_ALLOWED_NETWORKS` và mang `VISIONCARE_CALLBACK_TOKEN`."""
    host = request.client.host if request.client else ""
    try:
        caller = ipaddress.ip_address(host)
        is_allowed = any(
            caller in ipaddress.ip_network(net, strict=False)
            for net in config.CALLBACK_ALLOWED_NETWORKS
        )
    except ValueError:
        is_allowed = False
    if not is_allowed:
        raise HTTPException(status_code=403, detail="Callback source not allowed")

    expected = config.VISIONCARE_CALLBACK_TOKEN
    supplied = request.headers.get("authorization", "")
    if not expected:
        raise HTTPException(status_code=503, detail="Callback token is not configured")
    if not hmac.compare_digest(supplied, f"Bearer {expected}"):
        raise HTTPException(status_code=401, detail="Invalid callback token")


@app.post("/internal/action-results")
async def receive_action_result(request: Request) -> dict:
    """Accept an idempotent backend callback from `CALLBACK_ALLOWED_NETWORKS` only."""
    _require_callback_auth(request)
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


@app.post("/internal/calls")
async def receive_call_event(request: Request) -> JSONResponse:
    """Callback cuộc gọi của AB (`call_answered|call_rejected|call_ended|call_missed|call_incoming|
    emergency_exhausted`). Cùng xác thực với `/internal/action-results`; dedupe theo `Idempotency-Key`;
    luôn trả nhanh (AB thử lại 1/2/5/10 s với mọi mã không phải 2xx)."""
    from live import call_bridge

    _require_callback_auth(request)
    try:
        body = await request.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="Body must be a JSON object")
    status, out = await call_bridge.handle_event(body, request.headers.get("idempotency-key", ""))
    return JSONResponse(out, status_code=status)


@app.post("/internal/messages")
async def receive_message_event(request: Request) -> JSONResponse:
    """Callback tin nhắn của AB (`message_received`, `Idempotency-Key: message-<id>`). Cùng xác thực với
    `/internal/calls`; luôn trả 2xx nhanh (AB bỏ tin sau 8 lần thử; tin chưa đọc VH lấy bù bằng `messages/unread`)."""
    from live import messages

    _require_callback_auth(request)
    try:
        body = await request.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="Body must be a JSON object")
    status, out = await messages.handle_event(body, request.headers.get("idempotency-key", ""))
    return JSONResponse(out, status_code=status)


def _stream_audio(
    speech_pieces: Iterable[str],
    idx: int,
    started: float,
    processing: float | Callable[[], float],
    encode: Callable[[Iterator[bytes]], Iterator[bytes]] | None = None,
    byte_rate: float | None = None,
    prelude: bytes = b"",
    debug_name: str | None = None,
    debug_wrap: Callable[[bytes], bytes] | None = None,
    preroll_seconds: float | None = None,
) -> Iterator[bytes]:
    """Đọc các mảnh text thành từng mảnh audio, vừa gửi vừa gom lại để ghi debug.

    `started` là mốc lúc request vào, `processing` là số giây STT/Gemini đã
    tiêu trước khi tới đây — cả hai chỉ dùng để ghi log đo thời gian.
    `processing` có thể là hàm không đối số: `/process` chỉ biết con số này sau
    khi lượt v2 chạy xong (lúc đó câu mở đầu đã đang phát), nên log lấy lúc ghi.

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
    if preroll_seconds is None:
        preroll_seconds = config.AUDIO_PREROLL_SECONDS
    preroll_bytes = int(preroll_seconds * rate)
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
        processing() if callable(processing) else processing,
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


class _ProcessArm:
    """Cầu nối làn D cho `/process`: lệnh chờ chỉ đếm ngược từ lúc byte audio đầu tiên rời server.

    Byte đầu của `/process` là câu mở đầu ("Đã tiếp nhận yêu cầu") đi trước câu đọc lại, và server còn gom
    `AUDIO_PREROLL_SECONDS` trước khi gửi, nên cộng thêm `extra` (câu mở đầu + đệm cũ) vào cửa sổ huỷ.
    `Reply.on_audio_start` của lượt chỉ biết sau khi lượt v2 xong (`set`), còn byte đầu có thể đi trước
    hoặc sau đó (`first_chunk`): bên nào tới sau thì kích hoạt.
    """

    def __init__(self) -> None:
        self._arm: Callable[[float], None] | None = None
        self._sent = False
        self._done = False
        self.extra = tts.speaking_seconds(_RECEIVED_MESSAGE) + config.AUDIO_PREROLL_SECONDS

    def set(self, arm: Callable[[float], None] | None) -> None:
        self._arm = arm
        self._maybe()

    def first_chunk(self) -> None:
        self._sent = True
        self._maybe()

    def _maybe(self) -> None:
        if self._sent and self._arm is not None and not self._done:
            self._done = True
            self._arm(self.extra)


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


_process_seq: tuple[str, int] | None = None


def _next_process_index() -> int:
    """Số thứ tự request `/process`: quét STORAGE_DIR một lần (mỗi thư mục), sau đó chỉ đếm tiếp.

    Quét `request*.wav` mỗi request thì tốn tỉ lệ thuận số file debug đã tích tụ,
    mà hàm này chạy trên event loop.
    """
    global _process_seq
    if _process_seq is None or _process_seq[0] != config.STORAGE_DIR:
        _process_seq = (config.STORAGE_DIR, _next_debug_index())
    else:
        _process_seq = (_process_seq[0], _process_seq[1] + 1)
    return _process_seq[1]


async def _once(data: bytes):
    """Body một mảnh: `/process` đã có trọn audio nên đưa cho `turn.run` như luồng 1 mảnh."""
    yield data


def _save_debug_inputs(idx: int, audio_bytes: bytes, content_type: str | None, image_bytes: bytes) -> None:
    try:
        _save_debug_audio(f"request{idx}.wav", adpcm.ensure_wav(audio_bytes, content_type))
        if image_bytes:
            _save_debug_image(idx, image_bytes)
    except Exception:  # noqa: BLE001 - file debug hỏng không được kéo lượt hỏng
        logger.exception("process() request%d: ghi file debug lỗi", idx)


@app.post("/process", dependencies=[Depends(guard.turn_guard)])
async def process(
    request: Request,
    image: UploadFile | None = File(None),
    audio: UploadFile | None = File(None),
):
    """Firmware cũ (multipart `audio` + `image` tuỳ chọn) chạy chung pipeline v2.

    Hợp đồng HTTP giữ nguyên: câu mở đầu, luôn trả audio (lỗi cũng thành câu
    nói), định dạng theo `Accept`/`RESPONSE_FORMAT`, token theo Task 9. Bên trong:
    ảnh vào Image Buffer với turn id `process-<n>`, audio là body một mảnh của
    `turn.run(single_shot=True)` (làn B đọc thẳng ảnh, làn C chỉ gửi lệnh điện
    thoại — không có WS để mở live).

    Câu mở đầu phát NGAY trong lúc lượt v2 chạy ở task riêng: generator tiếng nói
    (chạy ở thread TTS) nói câu chào rồi mới chờ kết quả lượt. Chờ ở thread chứ
    không ở event loop, và không thêm await nào trên đường nóng.
    """
    device = _device_id(request)
    device_ctx.current.set(device)
    started = time.monotonic()
    idx = _next_process_index()
    response_format = config.RESPONSE_FORMAT
    if response_format == "auto":
        response_format = _negotiate(request.headers.get("accept", ""))
    plan = _plan_for(response_format, idx)
    turn_done: list[float] = []
    arm = _ProcessArm()

    try:
        if audio is None:
            speech: Iterable[str] = [_MISSING_AUDIO_MESSAGE]
        else:
            from handlers.action_flow import device_state
            from live.session import sessions
            from pipeline import pending_action

            # Ảnh không bắt buộc: lượt chỉ than phiền khi intent thật sự cần ảnh.
            image_bytes = await image.read() if image is not None else b""
            audio_bytes = await audio.read()
            turn_id = f"process-{idx}"
            if image_bytes:
                image_buffer.put(device, turn_id, image_bytes)

            loop = asyncio.get_running_loop()
            turn_gen = pending_action.begin_turn(device)
            state = {**device_state(), "alerting": sessions.active(device) is not None}
            task = loop.create_task(turn_v2.run(
                device, turn_id, audio.content_type, _once(audio_bytes), state,
                gen=turn_gen, transport="process", single_shot=True,
            ))
            done: concurrent.futures.Future = concurrent.futures.Future()

            def relay(t: asyncio.Task) -> None:
                if t.cancelled():
                    done.cancel()
                elif t.exception() is not None:
                    done.set_exception(t.exception())
                else:
                    done.set_result(t.result())

            task.add_done_callback(relay)

            def speech_gen() -> Iterator[str]:
                try:
                    # Xuống dòng ở cuối là dấu "câu trọn vẹn, đọc ngay" cho
                    # `tts._sentences()`; audio của câu này dựng sẵn nên ra tiếng
                    # trước khi STT/Clef/Gemma xong.
                    yield _RECEIVED_MESSAGE + "\n"
                    _save_debug_inputs(idx, audio_bytes, audio.content_type, image_bytes)
                    result = done.result()
                    turn_done.append(time.monotonic())
                    reply = result.reply
                    arm.set(reply.on_audio_start)
                    # Kính cũ không có clip cue trong flash: cue đổi thành câu nói.
                    for cue in reply.cues:
                        text = cues.fallback_text(cue)
                        if text:
                            yield text + "\n"
                    if reply.speech:
                        yield from reply.speech
                finally:
                    if not task.done():  # kính ngắt giữa chừng: huỷ lượt đang chạy
                        loop.call_soon_threadsafe(task.cancel)

            speech = speech_gen()
        reply = Reply(speech=speech)
    except Exception:  # noqa: BLE001 - MCU must receive audio, never a JSON error.
        logger.exception("process() request%d thất bại", idx)
        reply = Reply(speech=[_ERROR_MESSAGE])

    # Kéo tới mảnh audio đầu ở đây: lỗi trước byte đầu vẫn đổi được thành câu báo lỗi.
    _, body = await _reply_audio(
        reply, False, response_format, started, legacy_idx=idx,
        processing=lambda: (turn_done[0] if turn_done else time.monotonic()) - started,
    )
    if body is None:
        return Response(content=b"", media_type=plan.media_type)

    if response_format == "wav":
        # Gom trọn rồi mới gửi: mất thời gian chờ, đổi lại MCU nhận một file
        # hoàn chỉnh có Content-Length, không phụ thuộc việc đường truyền có
        # giữ đều 32 KB/s hay không.
        payload = await run_in_threadpool(lambda: b"".join(body))
        arm.first_chunk()  # cả file đi một lần ngay sau đây
        return Response(content=_pcm_to_wav(payload), media_type="audio/wav")

    # Kính ngắt giữa chừng -> huỷ lệnh chờ (như /v2/turn); đồng hồ làn D chạy từ byte đầu đã gửi.
    return StreamingResponse(
        _stream_until_disconnect(body, reply, device, arm.first_chunk),
        media_type=plan.media_type,
        headers=_stream_headers(response_format),
    )


# ── Voice server v2 (docs/superpowers/specs/2026-10-19-voice-server-architecture-design.md) ──
#
# Ba đường cùng host (§5): `/v2/image` (ảnh lúc bấm nút), `/v2/turn` (audio
# chunked trong lúc nói), `/v2/live` (WebSocket realtime cho làn B/C). Cả ba là
# async: `/v2/turn` phải đọc body THEO MẢNH trong lúc người dùng còn nói, và
# chạy song song partial STT, Clef, prewarm trên cùng event loop. Việc nặng CPU
# (STT, detector, TTS) đi thread riêng nên không chặn loop.

_v2_counter = 0


def _device_id(request: Request) -> str:
    """Id kính ĐÃ xác thực (token riêng -> kính chủ token; token chung -> `X-Device-Id` do client khai)
    và đặt `per_device` vào ContextVar để C5–C7 biết có được gọi điện/nhắn tin hay không."""
    auth = guard.request_auth(request)
    device_ctx.current.set(auth.device_id)  # per_device luôn đi cùng đúng kính của nó, không để lệch cặp
    device_ctx.per_device.set(auth.per_device)
    return auth.device_id


@app.on_event("startup")
async def warm_v2() -> None:
    """Bắt tay TLS tới Clef/Gemma, chọn đường Gemma nhanh nhất, nạp detector."""
    if not config.V2_WARM:
        return
    from live import hazard, text_align
    from models import clef, llm

    started = time.monotonic()
    from pipeline import intent_classifier

    async def warm_gemma() -> None:
        await llm.warm()
        # Prefix danh sách nhãn vào KV cache: lượt phân loại đầu khỏi prefill lại.
        await llm.prewarm(intent_classifier.prefix_messages())

    results = await asyncio.gather(
        clef.warm(), warm_gemma(),
        asyncio.to_thread(text_align.detector), asyncio.to_thread(hazard.detector),
        return_exceptions=True,
    )
    for name, result in zip(("clef", "gemma", "text-det", "hazard"), results):
        if isinstance(result, BaseException):
            logger.warning("warm %s lỗi: %r", name, result)
    logger.info("warm v2 xong %.2fs", time.monotonic() - started)


@app.post("/v2/image", status_code=204, dependencies=[Depends(guard.image_guard)])
async def image_lane(request: Request) -> Response:
    """Làn ảnh (§5.1): JPEG lúc bấm nút -> Image Buffer trong RAM, trả 204 ngay."""
    # Đọc theo stream và dừng ngay khi vượt trần: `await request.body()` sẽ gom
    # cả body khổng lồ vào RAM trước khi ta kịp từ chối.
    cap = config.DEVICE_MAX_IMAGE_BYTES
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > cap:
        return JSONResponse({"error": "image too large"}, status_code=413)
    parts, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > cap:
            return JSONResponse({"error": "image too large"}, status_code=413)
        parts.append(chunk)
    data = b"".join(parts)
    if data:
        image_buffer.put(_device_id(request), request.headers.get("x-turn-id", ""), data)
    return Response(status_code=204)


def _has_speech(speech) -> bool:
    return speech is not None and not (isinstance(speech, (list, tuple)) and not speech)


async def _reply_audio(
    reply: Reply, cue_ok: bool, response_format: str, released: float,
    legacy_idx: int | None = None, processing: Callable[[], float] | None = None,
) -> tuple[dict[str, str], Iterator[bytes] | None]:
    """Phần dùng chung của `/v2/turn` (HTTP) và `WS /v2/session`: Reply -> (header cue/live, audio).

    Trả `(headers, None)` khi chỉ có cue. Mảnh audio đầu đã được kéo sẵn ở đây
    nên lỗi trước byte đầu vẫn đổi được thành câu báo lỗi.

    `legacy_idx` (chỉ `/process`, firmware cũ): dùng số thứ tự file debug của request,
    đệm `AUDIO_PREROLL_SECONDS` (khớp header `X-Audio-Preroll-Seconds` đã khai) và
    ghi `response<idx>.*` như trước; `processing` là giờ-xử-lý cho dòng log.
    """
    global _v2_counter
    headers: dict[str, str] = {}
    lead: list[str] = []
    if cue_ok:
        if reply.cues:
            headers["X-Cue"] = ",".join(reply.cues)
    else:
        # Kính chưa có clip trong flash: cue đổi thành câu nói (đã dựng sẵn).
        lead = [t + "\n" for t in map(cues.fallback_text, reply.cues) if t]
    if reply.live:
        headers["X-Live"] = reply.live
        headers["X-Live-Token"] = reply.live_token or ""

    if not lead and not _has_speech(reply.speech):
        return headers, None

    if legacy_idx is None:
        _v2_counter += 1
        idx = _v2_counter
    else:
        idx = legacy_idx
    plan = _plan_for(response_format, idx)
    pieces = chain(lead, reply.speech if _has_speech(reply.speech) else [])
    preroll = config.V2_AUDIO_PREROLL_SECONDS if legacy_idx is None else config.AUDIO_PREROLL_SECONDS
    debug = {} if legacy_idx is None else {"debug_name": plan.debug_name, "debug_wrap": plan.debug_wrap}

    def stream(text: Iterable[str]) -> Iterator[bytes]:
        return _stream_audio(
            text, idx, released, processing or (time.monotonic() - released),
            encode=plan.encode, byte_rate=plan.byte_rate, prelude=plan.prelude,
            preroll_seconds=preroll, **debug,
        )

    audio_stream = stream(pieces)
    try:
        first = await run_in_threadpool(next, audio_stream, b"")
        body: Iterator[bytes] = _first_then(first, audio_stream)
    except Exception:  # noqa: BLE001
        logger.exception("v2 turn: lỗi trước byte audio đầu")
        body = stream([_ERROR_MESSAGE])
    return headers, body


def _first_then(first: bytes, rest: Iterator[bytes]) -> Iterator[bytes]:
    """`chain([first], rest)` nhưng có `.close()` đóng luôn `rest` (kính ngắt giữa câu)."""
    try:
        yield first
        yield from rest
    finally:
        rest.close()


async def _stream_until_disconnect(
    body: Iterator[bytes], reply: Reply, device: str | None,
    on_first_chunk: Callable[[], None] | None = None,
):
    """Audio trả lời cho `StreamingResponse`, dọn sạch khi kính ngắt giữa chừng.

    Starlette huỷ task gửi khi client rớt nhưng KHÔNG đóng iterator đồng bộ: Gemma và
    TTS cứ chạy nốt, còn lệnh làn D đang chờ đọc xong vẫn nổ. Ở đây `finally` làm 3 việc:
    đóng generator audio (trong thread đọc), huỷ bước Gemma đang bay (`abort`), và huỷ
    lệnh chờ của kính. Phát hết bình thường thì KHÔNG huỷ lệnh chờ — nó đang đếm ngược
    đúng bằng thời gian đọc lại lệnh.

    `on_first_chunk`: gọi ngay khi khối audio đầu tiên được giao cho StreamingResponse — đây là lúc làn D
    bắt đầu đếm cửa sổ huỷ (`Reply.on_audio_start`), không phải lúc `route()` xong.
    """
    from live.device_session import _iter_in_thread
    from pipeline import pending_action

    completed = False
    first = True
    try:
        async with contextlib.aclosing(_iter_in_thread(body, getattr(reply.speech, "abort", None))) as chunks:
            async for chunk in chunks:
                yield chunk
                if first:
                    first = False
                    if on_first_chunk is not None:
                        on_first_chunk()
        completed = True
    finally:
        if not completed and device is not None:
            if pending_action.cancel(device, "kính ngắt"):
                logger.info("v2 turn: kính ngắt giữa lượt, huỷ lệnh chờ của %s", device)


async def _v2_response(
    reply: Reply, cue_ok: bool, response_format: str, released: float, device: str | None = None,
) -> Response:
    headers, body = await _reply_audio(reply, cue_ok, response_format, released)
    if body is None:
        return Response(content=b"", headers=headers)

    if response_format == "wav":
        payload = await run_in_threadpool(lambda: b"".join(body))
        if reply.on_audio_start is not None:
            reply.on_audio_start(0.0)  # cả file đi một lần ngay sau đây
        return Response(content=_pcm_to_wav(payload), media_type="audio/wav", headers=headers)

    audio_headers = _stream_headers(response_format)
    audio_headers["X-Audio-Preroll-Seconds"] = str(config.V2_AUDIO_PREROLL_SECONDS)
    media_type = _plan_for(response_format, _v2_counter).media_type
    on_first = (lambda: reply.on_audio_start(0.0)) if reply.on_audio_start is not None else None
    return StreamingResponse(
        _stream_until_disconnect(body, reply, device, on_first),
        media_type=media_type, headers={**audio_headers, **headers},
    )


@app.post("/v2/turn", dependencies=[Depends(guard.turn_guard)])
async def turn_lane(request: Request) -> Response:
    """Làn âm thanh (§5.2): ADPCM chunked trong lúc nói -> cue/live/audio. Luôn 200."""
    from handlers.action_flow import device_state
    from live.session import sessions
    from pipeline import pending_action

    device = _device_id(request)
    device_ctx.current.set(device)
    turn_id = request.headers.get("x-turn-id", "")
    cue_ok = cues.supported(request.headers.get("x-cue-version"))
    response_format = config.RESPONSE_FORMAT
    if response_format == "auto":
        response_format = _negotiate(request.headers.get("accept", ""))

    # Lệnh làn D đang chờ đọc xong của lượt trước phải bị huỷ trước mọi xử lý.
    turn_gen = pending_action.begin_turn(device)
    state = {**device_state(), "alerting": sessions.active(device) is not None}
    try:
        result = await turn_v2.run(
            device, turn_id, request.headers.get("content-type"), request.stream(), state, gen=turn_gen,
        )
        reply, released = result.reply, result.released_at
    except Exception:  # noqa: BLE001 - kính luôn phải nghe được gì đó
        logger.exception("v2 turn %s thất bại", turn_id)
        pending_action.cancel(device, "lượt lỗi/kính ngắt")  # lượt hỏng thì không có lời đọc lại nào để chờ
        reply, released = Reply(cues=["system_busy"]), time.monotonic()
    return await _v2_response(reply, cue_ok, response_format, released, device)


if config.V2_DEBUG_STATS:
    @app.get("/v2/debug/stats")
    async def debug_stats(request: Request, reset: int = 0) -> dict:
        """Bộ đếm Gemma cho bench tải (Task 16). Chỉ có khi V2_DEBUG_STATS=1; vẫn cần token kính."""
        from models.llm import client as llm

        guard.check_token(request.headers)
        out = llm.stats()
        if reset:
            llm.reset_stats()
        return out


@app.websocket("/v2/live")
async def live_lane(ws: WebSocket, token: str = "") -> None:
    """Làn realtime B/C (§5.3). Token một lần, lấy từ `X-Live-Token`."""
    from lanes import nav_live, ocr_live
    from live.session import sessions

    # Token kính trước, rồi mới tới token phiên một lần: sai/thiếu đều đóng 4401
    # và không đụng tới `sessions` (không đốt token phiên của người khác).
    auth = guard.authenticate(ws.headers, ws.headers.get("x-device-id") or None)
    if auth is None:
        await ws.close(code=4401)
        return
    session = sessions.claim(token)
    # Token riêng chỉ mở được phiên live của chính kính đó.
    if session is None or (auth.per_device and session.device != auth.device_id):
        await ws.close(code=4401)
        return
    await ws.accept()
    runner = ocr_live.run if session.mode == "ocr" else nav_live.run
    await runner(ws, session)
    try:
        await ws.close()
    except RuntimeError:
        pass


@app.websocket("/v2/call")
async def call_media_lane(ws: WebSocket, token: str = "") -> None:
    """Âm thanh cuộc gọi phía app (§5.3): PCM16LE 16 kHz mono khung 20 ms; text hangup/mute.
    `token` = media_token do VH sinh, DÙNG MỘT LẦN. Accept trước rồi đóng 4401 (đóng trước accept thành 403)."""
    from live.call_bridge import calls

    await ws.accept()
    call = calls.claim_token(token)
    if call is None:
        await ws.close(code=4401)
        return
    await call.attach_app(ws)


@app.websocket("/v2/session")
async def device_session_lane(ws: WebSocket) -> None:
    """Một WebSocket mỗi kính (§5.4): lượt, audio trả lời, OCR/nav live cùng một socket.

    Chấp nhận kết nối TRƯỚC rồi mới kiểm `hello` và đóng 4401: đóng trước accept
    sẽ thành HTTP 403 trên server thật, firmware không đọc được mã lỗi.
    """
    from live.device_session import serve

    await ws.accept()
    await serve(ws, _reply_audio)
