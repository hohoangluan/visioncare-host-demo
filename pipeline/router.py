from schemas import Intent
from pipeline import stt, intent as intent_mod, tts
from handlers import ocr, find_object, read_money, describe_space

_HANDLERS = {
    Intent.OCR: ocr,
    Intent.FIND: find_object,
    Intent.MONEY: read_money,
    Intent.SPACE: describe_space,
}

_UNKNOWN_INTENT_MESSAGE = "Xin lỗi, tôi không hiểu yêu cầu, xin thử lại."


def process(image: bytes, audio: bytes) -> bytes:
    """Pipeline đầu-cuối: audio -> STT -> intent -> handler -> TTS."""
    command_text = stt.transcribe(audio)
    intent_name = intent_mod.detect(command_text)

    if intent_name == Intent.UNKNOWN:
        # Không khớp intent nào: hỏi lại luôn, khỏi chạy OCR/gọi Gemini đoán bừa.
        return tts.synthesize(_UNKNOWN_INTENT_MESSAGE)

    handler = _HANDLERS[intent_name]
    result = handler.handle(image, command_text)
    return tts.synthesize(result.speech)
