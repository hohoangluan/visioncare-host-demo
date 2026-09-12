"""Hợp đồng BOARD cho MỌI chức năng — một lượt HTTP thật, không mock router.

Vì sao có file này dù đã có `test_pipeline_e2e.py` và `test_audio_contract.py`
-----------------------------------------------------------------------------
Hai file kia mỗi file kiểm đúng một nửa, và cái board thật thấy là CHỖ NỐI của
hai nửa đó:

  * `test_pipeline_e2e.py` vào bằng `router.resolve_speech()` — dừng ở CHỮ.
    Nó không biết chữ đó có ra được thành byte audio hay không.
  * `test_audio_contract.py` kiểm byte audio — nhưng chỉ MỘT lượt, với
    `resolve_speech` bị mock thành `"xin chào"`. Nó không biết 19 chức năng
    kia có lượt nào trả về rỗng/nổ giữa chừng hay không.

Kính (theo phạm vi nhiệm vụ người dùng chốt 2026-08-26) chỉ làm ĐÚNG BA việc:

    1. gửi lên server một tấm ảnh + một đoạn audio (IMA ADPCM)
    2. nhận thân trả về, GIẢI NÉN ADPCM
    3. phát ra loa

Nó không phân tích, không quyết định, không có nhánh riêng cho từng chức năng.
⟹ Với board, **mọi chức năng phải trông y hệt nhau**: cùng một cấu trúc thân,
cùng bộ header, cùng cách giải nén. Một chức năng lệch khỏi khuôn đó là một
chức năng board phát ra tiếng rè — và không có log nào báo, vì board tin 4 byte
đầu của thân chứ không tin header HTTP (`measurements/G10.md` mục 1(c)).

Cách kiểm chứng audio có THẬT hay không
---------------------------------------
TTS bị thay bằng một hình sin 440 Hz. Nó đi trọn đường thật sau đó — chia
mảnh, mã hoá ADPCM, ghép header, stream — rồi test GIẢI NÉN thân trả về đúng
cách board giải nén và soi phổ. Ra đỉnh ở 440 Hz nghĩa là chuỗi
`PCM -> ADPCM -> HTTP -> giải nén` giữ nguyên tín hiệu. Chỉ đếm `len(body) > 0`
thì một lượt trả về toàn nhiễu vẫn xanh — mà nhiễu là đúng thứ đã xảy ra thật
khi thân bị gửi dạng stereo (SNR -11 dB).

Ranh giới mock: STT, bộ phân loại ý định, và các handler có ĐỤNG MẠNG (Gemini,
server app). Handler chỉ lật một cờ trong RAM thì chạy thật — chúng rẻ, và
chạy thật bắt được đúng loại bug `_HANDLERS` giữ hàm-thay-vì-module.
"""

from __future__ import annotations

import os
import struct
import uuid
from unittest.mock import patch

import numpy as np
import pytest
from fastapi.testclient import TestClient

import config
from app import app
from handlers import action_flow
from pipeline import adpcm
from schemas import Intent

client = TestClient(app)

# Chuỗi `Accept` board ESP32 thật gửi (`HUONG_DAN_SERVER.md` §1).
BOARD_ACCEPT = "audio/wav;codec=ima_adpcm, audio/mpeg, audio/wav"
# Firmware đời cũ chưa khai `codec=ima_adpcm` — vẫn phải chạy được.
LEGACY_ACCEPT = "audio/wav"

TONE_HZ = 440
TONE_SECONDS = 1.2
_TAIL_SECONDS = 0.4  # đủ dài để phân giải phổ, đủ ngắn để nằm sau earcon


def _tone_pcm(seconds: float = TONE_SECONDS) -> bytes:
    t = np.arange(int(seconds * adpcm.SAMPLE_RATE)) / adpcm.SAMPLE_RATE
    return (np.sin(2 * np.pi * TONE_HZ * t) * 12000).astype("<i2").tobytes()


TONE_PCM = _tone_pcm()


def _board_upload_audio(seconds: float = 0.6) -> bytes:
    """Đúng thứ board gửi LÊN: WAV IMA ADPCM, không phải PCM."""
    pcm = _tone_pcm(seconds)
    blocks = adpcm.encode_blocks(pcm)
    return adpcm.wav_header(len(blocks), sample_count=len(pcm) // 2) + blocks


def _fixture_image() -> bytes:
    path = os.path.join(os.path.dirname(__file__), "fixtures", "space_room.jpg")
    with open(path, "rb") as f:
        return f.read()


IMAGE = _fixture_image()


# ══════════════════════════════════════════════════════════════════════════
# Bảng chức năng — MỘT dòng cho mỗi thứ người dùng bấm nút rồi nói ra được
# ══════════════════════════════════════════════════════════════════════════
#
# `patch_target = None` nghĩa là handler chạy THẬT: nó không đụng mạng, chỉ
# lật cờ trong RAM. Hai intent `hazard_watch_*` buộc phải như vậy — `_HANDLERS`
# giữ THAM CHIẾU HÀM (`hazard_watch.start`) chứ không giữ module, nên mock
# thuộc tính module không chạm tới được cái dict đó.

CASES = [
    # id             câu người dùng nói             intent                     handler đụng mạng
    ("space",        "Mô tả xung quanh tôi.",       Intent.SPACE,              "handlers.describe_space.handle"),
    ("ocr",          "Đọc giúp tôi tài liệu này.",  Intent.OCR,                "handlers.ocr.handle"),
    ("find",         "Giúp tôi tìm gói bánh.",      Intent.FIND,               "handlers.find_object.handle"),
    ("money",        "Tờ tiền này là bao nhiêu?",   Intent.MONEY,              "handlers.read_money.handle"),
    ("hazard",       "Phía trước có gì nguy hiểm?", Intent.HAZARD,             "handlers.describe_hazard.handle"),
    ("chat",         "Kể một câu chuyện cười.",     Intent.CHAT,               "handlers.chat.handle"),
    ("nav_start",    "Chỉ đường đến chợ Bến Thành.", Intent.NAV_START,         "handlers.nav_start.handle"),
    ("nav_stop",     "Dừng chỉ đường lại.",         Intent.NAV_STOP,           "handlers.nav_stop.handle"),
    ("contact_call", "Gọi cho Nguyễn Văn A.",       Intent.CONTACT_CALL,       "handlers.contact_call.handle"),
    ("emergency",    "Gọi cấp cứu khẩn cấp.",       Intent.EMERGENCY_CALL,     "handlers.emergency_call.handle"),
    ("ride_quote",   "Đặt xe đi Bách Khoa.",        Intent.RIDE_QUOTE,         "handlers.ride_quote.handle"),
    ("ride_confirm", "Xác nhận đặt xe.",            Intent.RIDE_CONFIRM,       "handlers.ride_confirm.handle"),
    ("music_play",   "Mở bài Nơi này có anh.",      Intent.MUSIC_PLAY,         "handlers.music_play.handle"),
    ("music_stop",   "Dừng phát nhạc.",             Intent.MUSIC_STOP,         "handlers.music_stop.handle"),
    ("music_volume", "Tăng âm lượng.",              Intent.MUSIC_VOLUME,       "handlers.music_volume.handle"),
    ("watch_start",  "Bật cảnh báo vật cản.",       Intent.HAZARD_WATCH_START, None),
    ("watch_stop",   "Tắt cảnh báo vật cản.",       Intent.HAZARD_WATCH_STOP,  None),
    ("call_answer",  "Nghe máy.",                   Intent.CALL_ANSWER,        None),
    ("call_reject",  "Từ chối cuộc gọi.",           Intent.CALL_REJECT,        None),
    # Không phải chức năng: STT ra chữ vô nghĩa. Board VẪN phải nghe được một
    # câu hỏi lại — im lặng là ca tệ nhất với người khiếm thị, họ không phân
    # biệt được "server chưa trả lời" với "kính hỏng".
    ("unknown",      "Bờ rào xanh lét quả nhiên.",  Intent.UNKNOWN,            None),
]

IDS = [c[0] for c in CASES]
REPLY = "Đây là câu trả lời cho lượt này."


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(config, "AUDIO_PREROLL_SECONDS", 0.0)
    action_flow.reset_state()
    yield
    action_flow.reset_state()


def _turn(case, accept: str = BOARD_ACCEPT, image: bytes | None = IMAGE,
          turn_id: str | None = None):
    """Một lượt bấm nút, đi ĐÚNG đường HTTP mà board đi.

    Trả về `(response, spoken)` — `spoken` là chuỗi chữ đã đi vào TTS, để kiểm
    "có nói gì không" tách khỏi "byte audio có đúng không".
    """
    _id, text, intent, target = case
    spoken: list[str] = []

    def fake_tts(chunks):
        spoken.append("".join(chunks))
        yield TONE_PCM

    ctx = [
        patch("pipeline.stt.transcribe", return_value=text),
        patch("pipeline.intent.detect_with_params", return_value=(intent, {})),
        patch("pipeline.tts.synthesize_text_stream", fake_tts),
    ]
    if target is not None:
        ctx.append(patch(target, return_value=iter([REPLY])))

    files = {"audio": ("record.wav", _board_upload_audio(), "audio/wav")}
    if image is not None:
        files["image"] = ("capture.jpg", image, "image/jpeg")

    headers = {
        "Accept": accept,
        "X-Device-Id": "glasses-01",
        "X-Turn-Id": turn_id or uuid.uuid4().hex,
        "X-Fw-Version": "2026.08.26-demo1",
        "X-Wifi-Ssid": "Thanh_Cuong_FI",
    }

    for c in ctx:
        c.__enter__()
    try:
        response = client.post("/process", files=files, headers=headers)
    finally:
        for c in reversed(ctx):
            c.__exit__(None, None, None)
    return response, "".join(spoken)


def _decode(body: bytes) -> np.ndarray:
    """Giải nén ĐÚNG cách board giải nén: bỏ 60 byte header, decode khối."""
    return adpcm.decode_blocks(body[adpcm.WAV_HEADER_BYTES:])


def _peak_hz(samples: np.ndarray) -> float:
    windowed = samples.astype(np.float64) * np.hanning(samples.size)
    spectrum = np.abs(np.fft.rfft(windowed))
    return float(np.fft.rfftfreq(samples.size, 1 / adpcm.SAMPLE_RATE)[spectrum.argmax()])


# ══════════════════════════════════════════════════════════════════════════
# 1. Mỗi chức năng phải nói ra được một câu
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_every_function_answers_200(case):
    response, _ = _turn(case)
    assert response.status_code == 200, response.text


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_every_function_speaks_something(case):
    """Im lặng là ca tệ nhất: người khiếm thị không phân biệt được "server chưa
    trả lời" với "kính hỏng". Kể cả `unknown` cũng phải ra một câu hỏi lại."""
    _, spoken = _turn(case)
    assert spoken.strip(), "không có chữ nào đi vào TTS"


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_every_function_speaks_prose_not_data(case):
    """Handler trả nhầm dict/JSON thì board đọc vành vạch dấu ngoặc ra loa."""
    _, spoken = _turn(case)
    for junk in ("{", "}", "[", "<", "None", "Traceback"):
        assert junk not in spoken, f"{junk!r} lọt vào câu nói: {spoken!r}"


# ══════════════════════════════════════════════════════════════════════════
# 2. Mỗi chức năng phải trả về ADPCM board giải nén ra TIẾNG THẬT
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_every_function_returns_adpcm_headers(case):
    """Board tự cấu hình I2S từ mấy header này — sai một cái là đổi sample rate
    giữa lượt, nghe ra giọng nhanh/chậm."""
    response, _ = _turn(case)
    h = response.headers
    assert h["x-audio-encoding"] == "ima_adpcm"
    assert h["x-audio-channels"] == "1"
    assert h["x-audio-sample-rate"] == str(adpcm.SAMPLE_RATE)
    assert h["x-audio-bits"] == "4"


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_every_function_body_starts_with_the_60_byte_header(case):
    """Board đọc header NGAY trên luồng để dựng decoder, trước cả byte audio
    đầu tiên. Thân không mở bằng đúng 60 byte đó là board dựng decoder sai."""
    body = _turn(case)[0].content
    assert body[:4] == b"RIFF" and body[8:12] == b"WAVE"
    fmt_tag, n_ch = struct.unpack_from("<HH", body, 20)
    sample_rate = struct.unpack_from("<I", body, 24)[0]
    block_align = struct.unpack_from("<H", body, 32)[0]
    assert fmt_tag == adpcm.FORMAT_TAG
    assert n_ch == 1
    assert sample_rate == adpcm.SAMPLE_RATE
    assert block_align == adpcm.BLOCK_ALIGN
    assert body[adpcm.WAV_HEADER_BYTES - 8:adpcm.WAV_HEADER_BYTES - 4] == b"data"


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_every_function_body_decodes_to_the_signal_that_was_synthesized(case):
    """Kiểm chuỗi `PCM -> ADPCM -> HTTP -> giải nén` giữ nguyên tín hiệu."""
    body = _turn(case)[0].content
    payload = body[adpcm.WAV_HEADER_BYTES:]
    assert len(payload) % adpcm.BLOCK_ALIGN == 0, "khối ADPCM bị cắt dở"

    decoded = _decode(body)
    assert decoded.size == len(payload) // adpcm.BLOCK_ALIGN * adpcm.SAMPLES_PER_BLOCK
    # Có earcon `warm_melodic` chạy trước, nên soi phần ĐUÔI — chỗ chỉ còn
    # tiếng nói (ở đây là hình sin thay cho TTS).
    tail = decoded[-int(_TAIL_SECONDS * adpcm.SAMPLE_RATE):]
    assert abs(_peak_hz(tail) - TONE_HZ) < 15, "giải nén ra không phải tín hiệu đã gửi"


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_every_function_returns_at_least_the_whole_utterance(case):
    """Thân ngắn hơn câu đã tổng hợp = board bị cắt lời giữa chừng."""
    decoded = _decode(_turn(case)[0].content)
    assert decoded.size >= TONE_SECONDS * adpcm.SAMPLE_RATE * 0.95


# ══════════════════════════════════════════════════════════════════════════
# 3. Bất biến của riêng đường board — không chức năng nào được lệch
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_x_audio_format_never_lies_about_the_body(case):
    """`X-Audio-Format` có ĐÚNG MỘT nghĩa với board: "thân là dữ liệu THÔ".

    `parseAudioFormat()` (`src/audio/audio_format.cpp`) đặt `fmt.raw = true`
    chỉ vì THẤY header này — nó không đọc thân. Nhánh `adpcm_wav` gói thân
    trong RIFF, nên gửi kèm header đó là khai sai và board kêu lên. Bất biến
    hai chiều: có header ⟺ thân KHÔNG có container.

    Các header SỐ thì phải còn ở cả hai nhánh — chúng không khai gì về đóng
    gói, và người debug bằng curl đọc chúng.
    """
    response, _ = _turn(case)
    h = response.headers
    body_is_container = response.content[:4] == b"RIFF"
    assert body_is_container == ("x-audio-format" not in h), (
        f"x-audio-format={h.get('x-audio-format')!r} nhưng thân bắt đầu bằng "
        f"{response.content[:4]!r}"
    )
    assert h["x-audio-block-align"] == str(adpcm.BLOCK_ALIGN)
    assert h["x-audio-samples-per-block"] == str(adpcm.SAMPLES_PER_BLOCK)


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_retry_with_the_same_turn_id_replays_identical_bytes(case):
    """Board thử lại khi mất ACK giữa chừng (`X-Turn-Id` không đổi). Chạy lại
    pipeline lần hai nghĩa là gọi điện HAI lần cho một lần bấm nút."""
    turn_id = uuid.uuid4().hex
    first = _turn(case, turn_id=turn_id)[0]
    second = _turn(case, turn_id=turn_id)[0]
    assert second.status_code == 200
    assert second.content == first.content


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_legacy_firmware_without_adpcm_accept_still_gets_playable_audio(case):
    """Firmware đời cũ không khai `codec=ima_adpcm`. Trả ADPCM cho nó là ra
    nhiễu, nên server phải lui về WAV PCM — hai đời board chung một endpoint."""
    response, _ = _turn(case, accept=LEGACY_ACCEPT)
    assert response.status_code == 200
    assert response.headers.get("x-audio-encoding") != "ima_adpcm"
    assert response.content[:4] == b"RIFF"


# ══════════════════════════════════════════════════════════════════════════
# 4. Kính KHÔNG quyết định gì — mọi nhánh nằm ở server
# ══════════════════════════════════════════════════════════════════════════


def test_board_sends_one_shape_of_request_for_every_function():
    """Phạm vi nhiệm vụ của kính (chốt 2026-08-26): nó chỉ gửi (ảnh, audio) và
    phát audio trả về. Không có chức năng nào đòi kính gửi thêm trường riêng.

    Test này khoá đúng điều đó: cùng MỘT gói multipart, đổi mỗi câu nói, mọi
    chức năng đều chạy. Ngày nào có handler đòi board gửi thêm gì, test đỏ ở
    đây trước khi board đỏ ngoài đời.
    """
    for case in CASES:
        response, spoken = _turn(case)
        assert response.status_code == 200, f"{case[0]}: {response.text}"
        assert spoken.strip(), f"{case[0]}: im lặng"


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_no_function_makes_the_board_wait_for_a_second_round_trip(case):
    """F5 (xin ảnh tầng cao) đã xoá 2026-08-26 và kênh xuống đã tắt ở `demo1`.
    Không lượt nào được trả về một lệnh bắt board chụp lại rồi gửi lần hai —
    lượt bấm nút phải kết thúc bằng audio, chỉ audio."""
    response, _ = _turn(case)
    assert response.headers["content-type"].startswith("audio/")


def test_image_missing_is_answered_in_speech_not_in_an_error_code():
    """Kính không đọc mã lỗi HTTP thành lời. Ảnh hỏng/thiếu vẫn phải là 200 +
    một câu người dùng nghe hiểu được."""
    space = CASES[0]
    response, spoken = _turn(space, image=None)
    assert response.status_code == 200
    assert spoken.strip()
    assert _decode(response.content).size > 0


# ══════════════════════════════════════════════════════════════════════════
# 5. Chiều LÊN cũng là ADPCM — và server phải giải nén ra đúng tiếng đó
# ══════════════════════════════════════════════════════════════════════════
#
# Bốn test trên kia mock `stt.transcribe`, nên chúng không hề chạm vào chiều
# LÊN: kính có gửi lên nhiễu trắng thì chúng vẫn xanh. Ở đây `stt.transcribe`
# vẫn bị mock (model thật chậm và không xác định) NHƯNG mock ghi lại đúng
# những byte nó nhận được, rồi test giải nén chúng và soi phổ.
#
# Đây là nửa còn thiếu của vòng tròn:  kính nén -> server giải nén -> server
# nén -> kính giải nén.  Cả bốn mũi tên phải giữ được hình sin 440 Hz.


def _turn_capturing_uplink(audio_body: bytes, content_type: str):
    """Chạy một lượt và trả về đúng khối byte mà `stt.transcribe` nhận được."""
    seen: list[bytes] = []

    def spy_transcribe(audio, *a, **kw):
        seen.append(audio)
        return "Mô tả xung quanh tôi."

    def fake_tts(chunks):
        for _ in chunks:
            pass
        yield TONE_PCM

    with patch("pipeline.stt.transcribe", side_effect=spy_transcribe), patch(
        "pipeline.intent.detect_with_params", return_value=(Intent.SPACE, {})
    ), patch("pipeline.tts.synthesize_text_stream", fake_tts), patch(
        "handlers.describe_space.handle", return_value=iter([REPLY])
    ):
        response = client.post(
            "/process",
            files={
                "image": ("capture.jpg", IMAGE, "image/jpeg"),
                "audio": ("record.wav", audio_body, content_type),
            },
            headers={"Accept": BOARD_ACCEPT, "X-Device-Id": "glasses-01",
                     "X-Turn-Id": uuid.uuid4().hex},
        )
    assert seen, "STT không hề được gọi"
    return response, seen[0]


def test_uplink_adpcm_wav_reaches_stt_as_the_same_signal():
    """Kính gửi LÊN dạng nén (WAV IMA ADPCM). Server phải giải nén ra đúng
    tiếng đó trước khi đưa vào STT — sai ở đây thì STT nghe nhiễu và mọi
    chức năng rơi vào nhánh `unknown` mà không có lỗi nào bật lên."""
    uplink = _board_upload_audio(seconds=1.0)
    assert struct.unpack_from("<H", uplink, 20)[0] == adpcm.FORMAT_TAG

    response, heard = _turn_capturing_uplink(uplink, "audio/wav")
    assert response.status_code == 200

    samples, rate, channels = adpcm.decode_wav(heard)
    assert rate == adpcm.SAMPLE_RATE and channels == 1
    assert abs(_peak_hz(samples[-int(_TAIL_SECONDS * rate):]) - TONE_HZ) < 15


def test_uplink_raw_adpcm_blocks_without_header_are_rebuilt():
    """Kính đẩy khối ADPCM THÔ ngay trong lúc còn đang thu — nó chưa biết tổng
    độ dài nên không viết nổi header WAV. `ensure_wav` dựng lại header đó.

    Đây là đường thật của firmware (`app.py` chỗ gọi `ensure_wav`), không phải
    ca giả định: bỏ nhánh này thì kính vẫn gửi được, chỉ là STT nghe ra rác.
    """
    raw_blocks = adpcm.encode_blocks(_tone_pcm(1.0))
    assert raw_blocks[:4] != b"RIFF"

    response, heard = _turn_capturing_uplink(raw_blocks, "application/octet-stream")
    assert response.status_code == 200
    assert heard[:4] == b"RIFF", "server không dựng lại header cho khối thô"

    samples, rate, _ = adpcm.decode_wav(heard)
    assert abs(_peak_hz(samples[-int(_TAIL_SECONDS * rate):]) - TONE_HZ) < 15


def test_the_whole_round_trip_stays_adpcm_both_ways():
    """Một lượt, hai chiều, cùng một codec — đúng phạm vi nhiệm vụ của kính:
    nén khi gửi, giải nén khi nhận, không làm gì khác."""
    uplink = _board_upload_audio(seconds=1.0)
    response, heard = _turn_capturing_uplink(uplink, "audio/wav")

    # lên: ADPCM
    assert struct.unpack_from("<H", heard, 20)[0] == adpcm.FORMAT_TAG
    # xuống: ADPCM
    assert response.headers["x-audio-encoding"] == "ima_adpcm"
    assert struct.unpack_from("<H", response.content, 20)[0] == adpcm.FORMAT_TAG
    # và cái kính phát ra vẫn là tín hiệu server tổng hợp
    down = _decode(response.content)
    assert abs(_peak_hz(down[-int(_TAIL_SECONDS * adpcm.SAMPLE_RATE):]) - TONE_HZ) < 15
