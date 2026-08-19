"""Kiểm phần dựng sẵn audio cho câu nói cố định.

Điểm dễ hỏng nhất không phải việc dựng, mà là việc TRA: khoá dựng ra phải khớp
đúng chuỗi mà `tts._sentences()` sinh ra lúc chạy. Lệch một dấu cách hay lệch
chỗ cắt câu thì cache vẫn "chạy đúng" — chỉ là không bao giờ trúng, và triệu
chứng đúng bằng thứ nó sinh ra để chữa. Nên phần lớn test ở đây kiểm sự khớp đó.
"""

import numpy as np
import pytest

import config
from handlers import action_flow, music, phone, result_speech, waiting
from pipeline import phrases, tts


@pytest.fixture(autouse=True)
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PHRASE_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(config, "TTS_PRERENDER", True)


@pytest.fixture
def fake_tts(monkeypatch):
    """TTS giả, đếm số câu thật sự phải tổng hợp."""
    synthesized = []

    def fake_stream(text):
        synthesized.append(text)
        # Đủ dài để qua ngưỡng "file cache hỏng" — PCM vài byte bị coi là cụt.
        yield np.zeros(tts.OUTPUT_SAMPLE_RATE, dtype="<i2").tobytes()

    monkeypatch.setattr(tts, "synthesize_stream", fake_stream)
    return synthesized


def test_warm_registers_every_static_phrase(fake_tts):
    count = phrases.warm()
    assert count == len(phrases.collect())
    assert count > 30, "gom hụt câu cố định"


def test_warm_serves_from_memory_without_calling_model(fake_tts):
    phrases.warm()
    fake_tts.clear()

    chunks = list(tts.synthesize_text_stream([f"{music._STOP_ACK}\n"]))

    assert fake_tts == [], "câu đã dựng sẵn mà vẫn gọi model"
    assert b"".join(chunks) == tts.prerendered(music._STOP_ACK)


def test_second_warm_reads_from_disk_instead_of_synthesizing(fake_tts):
    phrases.warm()
    first_pass = len(fake_tts)
    fake_tts.clear()

    tts.clear_phrases()
    phrases.warm()

    assert first_pass > 0
    assert fake_tts == [], "khởi động lần hai vẫn tổng hợp lại từ đầu"
    assert tts.phrase_count() == first_pass


def test_cache_key_includes_voice(fake_tts, monkeypatch):
    """Đổi giọng phải dựng lại, không được dùng file của giọng cũ.

    Không tính giọng vào khoá thì server phát hai giọng khác nhau xen kẽ trong
    cùng một câu trả lời: câu cố định giọng cũ, câu động giọng mới.
    """
    phrases.warm()
    fake_tts.clear()

    monkeypatch.setattr(config, "TTS_VOICE", "Giọng khác")
    tts.clear_phrases()
    phrases.warm()

    assert len(fake_tts) > 0


def test_warm_prunes_phrases_no_longer_in_code(fake_tts, tmp_path):
    stale = tmp_path / "0123456789abcdef.pcm"
    stale.write_bytes(b"\x00\x00")

    phrases.warm()

    assert not stale.exists(), "sửa một chữ là bỏ lại một file, cache phình mãi"


def test_disabling_prerender_leaves_cache_empty(fake_tts, monkeypatch):
    monkeypatch.setattr(config, "TTS_PRERENDER", False)
    assert phrases.warm() == 0
    assert tts.phrase_count() == 0


def test_truncated_cache_file_is_rebuilt_not_trusted(monkeypatch):
    """File cache ngắn bất thường là hỏng, phải dựng lại chứ không nạp nguyên xi.

    Đã gặp thật: bộ test ghi đè PCM 2 byte vào thư mục cache thật. Vì "khác
    rỗng" nên lần chạy server sau nạp lại đúng 2 byte đó — server im lặng ở
    đúng những câu đáng lẽ phát ngay, không lỗi, không log, không ai biết.
    """
    def full_length(text):
        yield np.zeros(16000, dtype="<i2").tobytes()  # 1 giây audio

    monkeypatch.setattr(tts, "synthesize_stream", full_length)
    phrases.warm()

    # Cắt cụt mọi file trên đĩa, rồi khởi động lại.
    for path in __import__("pathlib").Path(config.PHRASE_CACHE_DIR).glob("*.pcm"):
        path.write_bytes(b"\x00\x00")

    rebuilt = []

    def counting(text):
        rebuilt.append(text)
        yield np.zeros(16000, dtype="<i2").tobytes()

    monkeypatch.setattr(tts, "synthesize_stream", counting)
    tts.clear_phrases()
    phrases.warm()

    assert len(rebuilt) == tts.phrase_count(), "file cụt vẫn được tin"
    assert len(tts.prerendered(music._STOP_ACK)) == 32000


def test_broken_phrase_does_not_stop_the_rest(monkeypatch):
    """Một câu dựng hỏng thì bỏ qua câu đó, không được chặn cả server."""
    def flaky(text):
        if text == music._STOP_ACK:
            raise RuntimeError("model hỏng")
        yield np.zeros(tts.OUTPUT_SAMPLE_RATE, dtype="<i2").tobytes()

    monkeypatch.setattr(tts, "synthesize_stream", flaky)
    phrases.warm()

    assert tts.prerendered(music._STOP_ACK) is None
    assert tts.prerendered(music._VOLUME_ACK) is not None


# --- Khớp khoá với chuỗi thật lúc chạy ---------------------------------------


def _spoken_sentences(pieces) -> list[str]:
    return list(tts._sentences(pieces))


@pytest.mark.parametrize(
    "piece",
    [
        f"{action_flow._utterance(music._STOP_ACK)}",
        f"{action_flow._utterance(phone._EMERGENCY_ACK)}",
        f"{action_flow._utterance(action_flow._DEFAULT_PROGRESS[0])}",
        f"{result_speech._NAV_OPENED_WITH_TAP}\n",
        f"{result_speech._RIDE_APP_OPENED}\n",
    ],
)
def test_runtime_sentence_matches_a_prerendered_key(piece, fake_tts):
    """Chuỗi lúc chạy phải tra trúng cache, không chỉ "gần giống"."""
    phrases.warm()

    for sentence in _spoken_sentences([piece]):
        assert tts.prerendered(sentence) is not None, f"trượt cache: {sentence!r}"


def test_music_ack_tail_is_prerendered_even_though_head_is_dynamic(fake_tts):
    """Câu ack có tên bài: nửa đầu tổng hợp thật, nửa sau phải lấy sẵn."""
    phrases.warm()
    ack = action_flow._utterance(f"Đang mở nhạc, tìm bài Nơi này có anh. {music._TAP_TO_OPEN}")

    sentences = _spoken_sentences([ack])

    assert tts.prerendered(sentences[0]) is None  # có tên bài -> phải tổng hợp
    assert tts.prerendered(sentences[-1]) is not None  # câu nhắc bấm -> lấy sẵn


def test_phrase_key_ignores_whitespace_differences():
    assert tts.phrase_key("  Đang gọi xe.  ") == tts.phrase_key("Đang gọi xe.")
    assert tts.phrase_key("Đang gọi\nxe.") == tts.phrase_key("Đang gọi xe.")
