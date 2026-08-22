"""T15 -- OCR: chat luong doc chu (docs/tasks/T15-ocr-quality.md).

H2 (retry xoay 180 khi gap sentinel) va H7 (OCR chuyen biet ngoai Gemini)
CHUA duoc cai: so do that o docs/tasks/measurements/H4.md cho thay ca 3
model (ke ca `-lite`) da tu doc dung anh xoay 180 do qua chinh prompt hien
co (2/2, 2/2, 1/1 sau khi loai loi ha tang 503 tam thoi) -- khong co bang so
nao chung minh can them mot luot goi Gemini thu hai. Vi vay o day KHONG co
test cho H2/H7 -- xem "khong can, xem H4" trong docs/tasks/reports/T15.md.

`models/ocr/__init__.py` va `handlers/ocr.py` KHONG nam trong bang "FILE BAN
DUOC SUA" cua agent T15 (xem AGENT_RULES muc B3) -- nen cac test o day kiem
tung khoi xay dung (config, tham so `model` cua vlm client, ham
`guidance_for_attempt`, bo dem `no_text_count`) O MUC CO LAP, khong kiem
duong day production end-to-end qua `ocr.read_stream()` (dieu do can sua hai
file ngoai pham vi).
"""
import logging
from pathlib import Path

import pytest

import config
from handlers import action_flow
from models.ocr import prompts
from models.vlm import client
from pipeline import image_quality, phrases

PROJ = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _clean_pending_state():
    action_flow.reset_state()
    yield
    action_flow.reset_state()


class _FakePart:
    def __init__(self, text):
        self.text = text


class _FakeModels:
    def __init__(self, texts=None):
        self._texts = texts or ["ok"]
        self.calls = []

    def generate_content_stream(self, **kwargs):
        self.calls.append(kwargs)
        return iter([_FakePart(t) for t in self._texts])


class _FakeClient:
    def __init__(self, models):
        self.models = models


def _fake(monkeypatch, texts=None):
    models = _FakeModels(texts)
    monkeypatch.setattr(client, "_get_client", lambda: _FakeClient(models))
    return models


# ─── H1 -- GEMINI_OCR_MODEL tach rieng ─────────────────────────────────────


def test_ocr_model_is_separate():
    """GEMINI_OCR_MODEL phai la mot bien config rieng, khac GEMINI_MODEL."""
    assert hasattr(config, "GEMINI_OCR_MODEL")
    assert config.GEMINI_OCR_MODEL != config.GEMINI_MODEL
    assert "lite" not in config.GEMINI_OCR_MODEL.lower(), (
        "H1 (25.1): OCR la tac vu doi hoi cao nhat nhom Gemini VLM, khong "
        "dung ban -lite"
    )


@pytest.mark.parametrize(
    "handler_path",
    [
        "handlers/describe_space.py",
        "handlers/describe_hazard.py",
        "handlers/find_object.py",
        "handlers/read_money.py",
    ],
)
def test_other_handlers_do_not_reference_ocr_model(handler_path):
    """space/hazard/find/money KHONG duoc doi model vi task nay -- doc thang
    source thay vi import (bon file nay ngoai bang "FILE BAN DUOC SUA", T15
    khong duoc sua chung, chi duoc kiem chung khong bi anh huong)."""
    with open(PROJ / handler_path, encoding="utf-8") as f:
        source = f.read()
    assert "GEMINI_OCR_MODEL" not in source
    assert "model=" not in source, (
        f"{handler_path} khong duoc truyen model= xuong vlm.generate_stream -- "
        "se vo tinh doi model cua handler nay theo T15"
    )


def test_vlm_accepts_model_param(monkeypatch):
    """generate_stream(model=...) phai duoc dung boi Gemini API."""
    models = _fake(monkeypatch, ["ok"])
    list(client.generate_stream("prompt", model="gemini-3.5-flash"))
    assert models.calls[0]["model"] == "gemini-3.5-flash"


def test_vlm_model_param_defaults_to_config_gemini_model(monkeypatch):
    """Khong truyen model= -> van dung config.GEMINI_MODEL nhu truoc T15,
    de space/hazard/find/money khong doi hanh vi mot dong nao."""
    monkeypatch.setattr(config, "GEMINI_MODEL", "gemini-9-fake")
    models = _fake(monkeypatch, ["ok"])
    list(client.generate_stream("prompt"))
    assert models.calls[0]["model"] == "gemini-9-fake"


def test_vlm_model_param_does_not_override_search_model(monkeypatch):
    """search=True van uu tien GEMINI_SEARCH_MODEL khi khong truyen model=."""
    monkeypatch.setattr(config, "GEMINI_SEARCH_MODEL", "gemini-search-fake")
    models = _fake(monkeypatch, ["ok"])
    list(client.generate_stream("prompt", search=True))
    assert models.calls[0]["model"] == "gemini-search-fake"


# ─── H3 -- ba cau huong dan tang dan theo pending.attempt ──────────────────


def test_guidance_escalates():
    """attempt 1/2/3 -> BA cau KHAC nhau."""
    g1 = prompts.guidance_for_attempt(1)
    g2 = prompts.guidance_for_attempt(2)
    g3 = prompts.guidance_for_attempt(3)
    assert len({g1, g2, g3}) == 3, "ca 3 cau phai khac nhau, khong lap lai"


def test_guidance_clamps_beyond_third_attempt():
    """attempt >= 3 khong duoc quay lai cau 1 -- giu nguyen cau cuoi."""
    assert prompts.guidance_for_attempt(3) == prompts.guidance_for_attempt(4)
    assert prompts.guidance_for_attempt(4) == prompts.guidance_for_attempt(99)


def test_guidance_is_stateless_no_private_counter():
    """Goi hai lan cung attempt phai ra CUNG mot cau -- ham khong tu tang bo
    dem rieng, chi doc tham so dau vao (H3: 'khong dung bo dem rieng')."""
    first = prompts.guidance_for_attempt(2)
    second = prompts.guidance_for_attempt(2)
    assert first == second


def test_attempt_counter_from_pending():
    """Dung thang `pending.attempt` (T03/21.2, handlers/action_flow.Pending),
    KHONG dung bo dem rieng cua rieng OCR."""
    action_flow.set_pending(
        "ocr_retry", "ocr", {}, "Khong thay ro chu.", kind="fill",
    )
    pending = action_flow.get_pending()
    assert pending.attempt == 0

    first_guidance = prompts.guidance_for_attempt(pending.attempt + 1)

    action_flow.record_pending_attempt()
    pending = action_flow.get_pending()
    assert pending.attempt == 1
    second_guidance = prompts.guidance_for_attempt(pending.attempt + 1)

    action_flow.record_pending_attempt()
    pending = action_flow.get_pending()
    assert pending.attempt == 2
    third_guidance = prompts.guidance_for_attempt(pending.attempt + 1)

    assert len({first_guidance, second_guidance, third_guidance}) == 3


def test_guidance_all_prebuilt():
    """Ca ba cau huong dan phai nam trong tap `phrases.collect()` (T06/G5) --
    khong thi se bi tong hop TTS song, dung ngay luc nguoi dung dang sot
    ruot vi vua chup hong."""
    collected = phrases.collect()
    from pipeline import tts

    for sentence in prompts.GUIDANCE_BY_ATTEMPT:
        for piece in tts._sentences([sentence]):
            key = tts.phrase_key(piece)
            assert key in collected, f"thieu cau du am san: {sentence!r}"


def test_ocr_prompts_module_has_static_speech():
    """`STATIC_SPEECH` la quy uoc chung cua moi module co cau co dinh (xem
    `pipeline/phrases.py:_speech_modules()`) -- phai dung dung ten thuoc
    tinh, khong thi collect() lang le bo qua."""
    assert hasattr(prompts, "STATIC_SPEECH")
    assert set(prompts.STATIC_SPEECH) == set(prompts.GUIDANCE_BY_ATTEMPT)


# ─── H5 -- dem KHONG_CO_CHU, kem sharpness/brightness da do san ────────────


@pytest.fixture(autouse=True)
def _reset_no_text_counter():
    image_quality.reset_no_text_count()
    yield
    image_quality.reset_no_text_count()


def test_no_text_count_starts_at_zero():
    assert image_quality.no_text_count() == 0


def test_no_text_logged_with_metrics(caplog):
    """KHONG_CO_CHU -> log co sharpness + brightness -- LAY TU GATE, khong do
    lai (ham chi nhan float, khong nhan bytes anh -- xem chu ky ham)."""
    with caplog.at_level(logging.INFO, logger="blind_assist"):
        image_quality.record_no_text(sharpness=12.34, brightness=56.7)

    assert any(
        "12.34" in rec.message and "56.7" in rec.message for rec in caplog.records
    ), "log thieu sharpness/brightness da do san o gate"


def test_no_text_count_increments():
    """Ba lan ghi nhan -> dem = 3, dung so tich luy de so sanh truoc/sau."""
    image_quality.record_no_text(1.0, 2.0)
    image_quality.record_no_text(3.0, 4.0)
    n = image_quality.record_no_text(5.0, 6.0)
    assert n == 3
    assert image_quality.no_text_count() == 3


def test_no_text_count_handles_missing_metrics():
    """Anh khong decode duoc thi measure() tra None -- ham nay van phai nhan
    duoc None ma khong crash, chi khong co so de log."""
    n = image_quality.record_no_text(None, None)
    assert n == 1
