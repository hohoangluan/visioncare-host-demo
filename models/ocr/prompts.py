_NORMAL = """Dịch đoạn văn bản sau sang tiếng Việt tự nhiên, ngắn gọn, dễ \
nghe qua tai nghe. Chỉ trả về bản dịch, không giải thích thêm:

{text}"""

_SPECIALIZED = """Dịch đoạn văn bản sau sang tiếng Việt, nhưng GIỮ NGUYÊN \
(không dịch) các thuật ngữ chuyên ngành, tên riêng, mã số, đơn vị đo. Chỉ \
dịch phần văn bản thông thường xung quanh. Chỉ trả về bản dịch, không giải \
thích thêm:

{text}"""


def build(text: str, mode: str) -> str:
    from . import Mode

    template = _SPECIALIZED if mode == Mode.SPECIALIZED else _NORMAL
    return template.format(text=text)
