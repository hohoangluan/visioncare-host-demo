from handlers import read_money
from models import vlm

IMG = b"fake image"


def test_read_money_streams_vlm_response(monkeypatch):
    captured = {}

    def fake_generate_stream(prompt, image=None):
        captured["prompt"] = prompt
        captured["image"] = image
        yield "50 nghìn đồng."

    monkeypatch.setattr(vlm, "generate_stream", fake_generate_stream)

    speech = "".join(read_money.handle(IMG, "đọc tiền"))

    assert speech == "50 nghìn đồng."
    assert captured["image"] == IMG
    assert "trọng tâm" in captured["prompt"].lower()


def test_read_money_prompt_forbids_filler_words(monkeypatch):
    captured = {}

    def fake_generate_stream(prompt, image=None):
        captured["prompt"] = prompt
        yield "100 nghìn đồng."

    monkeypatch.setattr(vlm, "generate_stream", fake_generate_stream)

    list(read_money.handle(IMG, "đọc mệnh giá"))

    prompt = captured["prompt"].lower()
    assert "đây là" in prompt or "dẫn dắt" in prompt

