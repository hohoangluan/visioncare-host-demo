"""Nhịp các câu trấn an trong lúc chờ.

Hai loại câu, đừng lẫn: câu BÁO TIẾN ĐỘ (đã tìm được bài, đã mở ứng dụng, kết
quả cuối) luôn nói ngay khi có; câu TRẤN AN không mang thông tin mới, chỉ để
người dùng biết máy còn sống. Test ở đây chỉ nói về loại thứ hai.
"""

import time
from itertools import islice
from unittest.mock import patch

import pytest

import app
import config
from handlers import action_flow, waiting
from pipeline import tts


def _first_delays(count: int) -> list[float]:
    return list(islice(waiting.notice_delays(), count))


# --- Luật ưu tiên -----------------------------------------------------------
#
# Âm thanh có giá trị (kết quả model, trạng thái thật của action) luôn thắng câu
# trấn an. Trấn an chỉ được nói khi tới mốc mà vẫn chưa có gì.


def test_ready_content_is_never_held_back_by_the_notice_clock(monkeypatch):
    """Mốc trấn an không được giữ nội dung đã sẵn sàng."""
    monkeypatch.setattr(config, "SPEECH_FIRST_NOTICE_SECONDS", 30.0)
    started = time.monotonic()

    spoken = list(waiting.wait_for(lambda: "kết quả", notices=("chờ chút",)))

    assert spoken == []
    assert time.monotonic() - started < 0.5


def test_notice_is_dropped_entirely_when_content_beats_it(monkeypatch):
    """Tới mốc mà nội dung thật đã có thì bỏ hẳn câu trấn an, không nói bù."""
    monkeypatch.setattr(config, "SPEECH_FIRST_NOTICE_SECONDS", 0.05)
    monkeypatch.setattr(config, "SPEECH_NOTICE_GRACE_SECONDS", 1.0)

    def produce():
        time.sleep(0.3)  # quá mốc, nhưng còn trong nhịp nhường
        return "kết quả"

    assert list(waiting.wait_for(produce, notices=("chờ chút",))) == []


def test_wait_for_returns_the_produced_value():
    gen = waiting.wait_for(lambda: {"request_state": "succeeded"})
    try:
        next(gen)
    except StopIteration as stop:
        assert stop.value == {"request_state": "succeeded"}
    else:
        pytest.fail("không được nói gì khi kết quả có ngay")


def test_wait_for_propagates_failures_instead_of_swallowing_them():
    """Nuốt lỗi ở luồng nền thì người dùng nghe im lặng thay vì câu báo lỗi."""
    def boom():
        raise RuntimeError("hỏng")

    with pytest.raises(RuntimeError, match="hỏng"):
        list(waiting.wait_for(boom, notices=()))


def test_action_result_is_not_delayed_by_a_full_poll_interval(monkeypatch):
    """Trước đây luồng chính `sleep` một nhịp poll sau mỗi lần hỏi, nên kết quả
    vừa về vẫn nằm chờ tới hết nhịp đó. Giờ `sleep` nằm ở luồng nền."""
    monkeypatch.setattr(config, "SPEECH_FIRST_NOTICE_SECONDS", 30.0)
    monkeypatch.setattr(config, "VISIONCARE_RESULT_POLL_SECONDS", 0.05)
    done = {"request_state": "succeeded", "result": {}}

    started = time.monotonic()
    with patch("handlers.action_flow.call_service_api",
               return_value={"data": {"request_id": "r"}}), \
         patch("handlers.action_flow.get_request_status", return_value=done):
        list(action_flow.run_action("music_stop", "x", {}, ack="a", failure="f", progress=()))

    assert time.monotonic() - started < 0.5


def _silence_seconds(pcm: bytes) -> float:
    return pcm.count(b"\x00") / 2 / tts.OUTPUT_SAMPLE_RATE


def test_consecutive_sentences_get_a_pause_between_them(monkeypatch):
    """Nối thẳng đầu câu sau vào đuôi câu trước là một tràng tiếng liên tục.

    Người khiếm thị chỉ có kênh âm thanh để theo dõi: câu chào, câu trấn an và
    câu trả lời dính liền nhau thì không nghe ra ranh giới giữa chúng.
    """
    monkeypatch.setattr(config, "SPEECH_SENTENCE_PAUSE_SECONDS", 0.5)
    tts.clear_phrases()
    tts.register_phrase("Câu một.", b"\x01\x02" * 100)
    tts.register_phrase("Câu hai.", b"\x01\x02" * 100)

    out = b"".join(tts.synthesize_text_stream(["Câu một.\nCâu hai.\n"]))

    assert _silence_seconds(out) == pytest.approx(0.5, abs=0.01)


def test_no_pause_before_the_very_first_sentence(monkeypatch):
    """Chèn cả trước câu đầu thì mọi request đều chậm thêm đúng ngần ấy, mà
    chẳng ngăn cách được với câu nào."""
    monkeypatch.setattr(config, "SPEECH_SENTENCE_PAUSE_SECONDS", 0.5)
    tts.clear_phrases()
    tts.register_phrase("Câu một.", b"\x01\x02" * 100)

    out = b"".join(tts.synthesize_text_stream(["Câu một.\n"]))

    assert _silence_seconds(out) == 0.0


def test_pause_can_be_turned_off(monkeypatch):
    monkeypatch.setattr(config, "SPEECH_SENTENCE_PAUSE_SECONDS", 0.0)
    tts.clear_phrases()
    tts.register_phrase("Câu một.", b"\x01\x02" * 100)
    tts.register_phrase("Câu hai.", b"\x01\x02" * 100)

    out = b"".join(tts.synthesize_text_stream(["Câu một.\nCâu hai.\n"]))

    assert _silence_seconds(out) == 0.0


def test_opening_line_replaces_the_first_notice_entirely():
    """Câu chào "đã nhận yêu cầu, hệ thống đang xử lý" CHÍNH LÀ trấn an #1.

    Nghe thật thì câu chào rồi "vẫn đang xử lý" thành hai câu gần trùng ý liền
    nhau — như máy nói lại một câu chứ không phải báo tiến độ. Nên khi có câu
    mở đầu thì bỏ hẳn mốc đầu, đi thẳng vào nhịp thường.
    """
    delays = _first_delays(2)
    after_opening = next(waiting.notice_delays(2.72))

    assert delays[0] == config.SPEECH_FIRST_NOTICE_SECONDS  # không có câu mở đầu
    assert after_opening == pytest.approx(delays[1] + 2.72)  # có câu mở đầu


def test_notice_after_the_opening_still_counts_from_when_it_finishes():
    """Mốc đếm từ lúc câu mở đầu đọc XONG, không phải từ lúc bắt đầu đọc."""
    opening = tts.speaking_seconds(app._RECEIVED_MESSAGE)
    silence = next(waiting.notice_delays(opening)) - opening

    assert silence == pytest.approx(config.SPEECH_NOTICE_INTERVAL_SECONDS)


def test_no_notice_repeats_what_the_opening_line_already_said():
    """Câu chào đã nói "đang xử lý"; không câu trấn an nào được nói lại ý đó."""
    assert not any("đang xử lý" in notice.lower() for notice in waiting._DEFAULT_NOTICES)
    assert not any(
        "đang xử lý" in notice.lower() for notice in action_flow._DEFAULT_PROGRESS
    )


def test_speaking_seconds_is_exact_for_prerendered_lines():
    """Câu dựng sẵn thì đo thẳng từ PCM sắp phát, không ước lượng."""
    tts.clear_phrases()
    seconds = 3.0
    tts.register_phrase("câu thử", b"\x00" * int(seconds * tts.OUTPUT_SAMPLE_RATE * 2))
    assert tts.speaking_seconds("câu thử") == pytest.approx(seconds)


def test_speaking_seconds_falls_back_to_an_estimate_for_dynamic_lines():
    """Câu có tên bài / tên người chưa tồn tại lúc dựng sẵn, vẫn phải ước lượng
    được — nếu không thì mọi câu động đều bị coi như dài 0 giây."""
    tts.clear_phrases()
    short = tts.speaking_seconds("Đang gọi xe.")
    long = tts.speaking_seconds("Đang mở nhạc, tìm bài Nơi này có anh của Sơn Tùng.")
    assert 0.5 < short < 2.0
    assert long > short


def test_result_arriving_just_after_the_deadline_skips_the_notice(monkeypatch):
    """Audio phát tuần tự nên câu trấn an đã đẩy ra là không rút lại được: kết
    quả về ngay sau đó phải xếp hàng chờ đọc xong câu đã hết tác dụng."""
    monkeypatch.setattr(config, "SPEECH_FIRST_NOTICE_SECONDS", 0.05)
    monkeypatch.setattr(config, "SPEECH_NOTICE_GRACE_SECONDS", 1.0)

    def slow_stream():
        time.sleep(0.25)  # về sau mốc trấn an, nhưng còn trong nhịp nhường
        yield "câu trả lời"

    assert list(waiting.with_progress_notice(slow_stream())) == ["câu trả lời"]


def test_notice_still_spoken_when_the_wait_is_genuinely_long(monkeypatch):
    """Nhịp nhường không được biến thành 'im luôn': chờ thật thì vẫn phải nói."""
    monkeypatch.setattr(config, "SPEECH_FIRST_NOTICE_SECONDS", 0.05)
    monkeypatch.setattr(config, "SPEECH_NOTICE_GRACE_SECONDS", 0.05)

    def slow_stream():
        time.sleep(0.6)
        yield "câu trả lời"

    spoken = list(waiting.with_progress_notice(slow_stream()))
    assert spoken[-1] == "câu trả lời"
    assert len(spoken) > 1


def test_first_notice_waits_longer_than_the_gap_between_later_ones():
    """Phần lớn request xong trước câu trấn an đầu tiên, và nên như vậy.

    Nói sớm quá thì mọi request đều phải nghe một câu thừa trước câu trả lời
    thật.
    """
    delays = _first_delays(3)
    assert delays[0] == config.SPEECH_FIRST_NOTICE_SECONDS
    assert delays[0] < delays[1]


def test_notices_spread_out_instead_of_repeating_at_a_fixed_beat():
    """Nhịp đều nghe thành một tràng liên tục.

    Giãn cách tính từ lúc ĐẨY câu ra, mà mỗi câu đọc lên mất 2-3 giây — nhịp đều
    4 giây cũ chỉ để lại ~1 giây im lặng giữa hai câu. Nghe thử đúng là dồn dập.
    Chờ càng lâu thì càng ít cần nhắc lại, nên giãn dần.
    """
    delays = _first_delays(6)
    later = delays[1:]
    assert later == sorted(later)
    assert later[-1] > later[0]


def test_notice_interval_stops_growing_at_the_cap():
    """Giãn mãi thì thành bỏ rơi người dùng — phải có trần."""
    delays = _first_delays(30)
    assert max(delays) <= config.SPEECH_NOTICE_MAX_INTERVAL_SECONDS


def test_notices_stay_under_the_cap_for_the_longest_action():
    """`music_play` chờ tới 40 giây; không quãng nào được im quá trần."""
    budget = config.VISIONCARE_MUSIC_RESULT_TIMEOUT_SECONDS
    elapsed = 0.0
    gaps = []
    for delay in waiting.notice_delays():
        if elapsed + delay > budget:
            gaps.append(budget - elapsed)
            break
        elapsed += delay
        gaps.append(delay)

    assert max(gaps) <= config.SPEECH_NOTICE_MAX_INTERVAL_SECONDS
    assert 3 <= len(gaps) <= 6, f"{len(gaps)} câu trấn an trong {budget}s"


def test_progress_lines_are_marked_as_complete_utterances():
    """Thiếu dấu này thì câu trấn an nằm chờ mảnh text sau mới được đọc.

    Đúng thứ nó sinh ra để khỏi phải chờ.
    """
    assert action_flow._utterance("Đang gọi xe.").endswith("\n")
    assert action_flow._utterance("Đang gọi xe.\n") == "Đang gọi xe.\n"


def test_notices_do_not_repeat_the_opening_greeting():
    """Người dùng vừa nghe câu chào vài giây trước.

    Nghe lại gần y hệt thì tưởng máy phát lại chứ không phải đang chạy tiếp.
    """
    import app

    opening = app._RECEIVED_MESSAGE.lower().rstrip(".")
    for notice in waiting._DEFAULT_NOTICES + action_flow._DEFAULT_PROGRESS:
        assert notice.lower().rstrip(".") != opening


@pytest.mark.parametrize(
    "notices",
    [waiting._DEFAULT_NOTICES, action_flow._DEFAULT_PROGRESS, action_flow.STATIC_SPEECH],
)
def test_notice_lists_have_no_duplicates(notices):
    """Quay vòng một danh sách trùng lặp là nghe cùng một câu hai lần liền."""
    assert len(set(notices)) == len(notices)
