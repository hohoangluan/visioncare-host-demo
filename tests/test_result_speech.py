from handlers import result_speech


def test_command_expired_is_spoken_not_generic():
    data = {"request_state": "failed", "error": {"code": "COMMAND_EXPIRED", "message": "x", "details": {}}}
    assert result_speech.speak_result("music_play", data) == (
        "Điện thoại nhận lệnh quá muộn nên chưa làm. Bạn nói lại giúp tôi nhé."
    )
