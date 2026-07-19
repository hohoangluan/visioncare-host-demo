from schemas import Intent
from pipeline import stt, intent as intent_mod, tts
from handlers import ocr, translate, find_object, read_money, describe_space

_HANDLERS = {
    Intent.OCR: ocr,
    Intent.TRANSLATE: translate,
    Intent.FIND: find_object,
    Intent.MONEY: read_money,
    Intent.SPACE: describe_space,
}


def process(image: bytes, audio: bytes) -> bytes:
    """Pipeline đầu-cuối: audio -> STT -> intent -> handler -> TTS."""
    command_text = stt.transcribe(audio)
    intent_name = intent_mod.detect(command_text)
    handler = _HANDLERS.get(intent_name, describe_space)
    result = handler.handle(image, command_text)
    return tts.synthesize(result.speech)
