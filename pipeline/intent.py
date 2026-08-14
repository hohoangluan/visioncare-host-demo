import logging

import config
from models import vlm
from pipeline import intent_local
from schemas import Intent

logger = logging.getLogger("blind_assist")

# Nhãn KHÔNG cần trích tham số nào -> phân loại xong là xong, không phải hỏi
# Gemini nữa. Đây là chỗ bộ phân loại cục bộ tiết kiệm được cả giây: 5 nhãn ảnh
# nằm hết ở đây, mà handler của chúng vốn đã gọi Gemini kèm ảnh — lượt gọi phân
# loại trước đó là chờ trắng chỉ để lấy một cái nhãn.
#
# Các nhãn còn lại (`nav_start` cần destination, `contact_call` cần
# contact_name, `music_play` cần song, `chat` cần needs_location/needs_web...)
# vẫn phải qua Gemini vì SetFit chỉ sinh ra nhãn, không trích được slot.
_PARAM_FREE = frozenset({
    Intent.OCR, Intent.FIND, Intent.MONEY, Intent.SPACE, Intent.HAZARD,
    Intent.NAV_STOP, Intent.MUSIC_STOP, Intent.UNKNOWN,
})

# Hai nhãn này phụ thuộc trạng thái thiết bị, mà bộ phân loại cục bộ chỉ đọc
# chữ. "Tắt đi" ra `music_stop` hay `nav_stop` là do cái gì đang chạy quyết
# định, không do câu chữ.
_STATE_DEPENDENT = frozenset({Intent.NAV_STOP, Intent.MUSIC_STOP})

_LABELS = (
    Intent.OCR, Intent.FIND, Intent.MONEY, Intent.SPACE, Intent.HAZARD, Intent.CHAT,
    Intent.NAV_START, Intent.NAV_STOP,
    Intent.CONTACT_CALL, Intent.EMERGENCY_CALL,
    Intent.RIDE_QUOTE, Intent.RIDE_CONFIRM,
    Intent.MUSIC_PLAY, Intent.MUSIC_STOP, Intent.MUSIC_VOLUME,
    # `unknown` là nhãn model được phép CHỌN, không chỉ là giá trị dự phòng khi
    # gọi model hỏng. Không có nó thì mọi thứ STT nghe nhầm đều rơi vào `chat`,
    # và Gemini lịch sự trả lời một câu hỏi chưa từng ai hỏi.
    Intent.UNKNOWN,
)

_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": list(_LABELS)},
        "params": {
            "type": "object",
            "properties": {
                "destination": {"type": "string"},
                "contact_name": {"type": "string"},
                "song": {"type": "string"},
                "volume": {"type": "integer"},
                "direction": {"type": "string", "enum": ["up", "down"]},
                "confirm": {"type": "boolean"},
                "quote_id": {"type": "string"},
                "emergency_number": {"type": "string"},
                "needs_location": {"type": "boolean"},
                "needs_web": {"type": "boolean"},
            }
        }
    },
    "required": ["intent"],
}

# Bản dài trước đây: 5162 ký tự (~1474 token). Giữ lại ở đây để đối chiếu khi
# nghi bản ngắn làm sai nhãn nào — `tools/bench_intent_prompt.py` chạy được cả
# hai để so.
_PROMPT_TEMPLATE_LONG = (
    "Bạn là bộ phân loại ý định cho ứng dụng hỗ trợ người khiếm thị bằng giọng nói.\n"
    "Người dùng vừa nói một câu lệnh, hãy đọc kỹ và chọn ĐÚNG MỘT nhãn mô tả sát nhất ý định của họ "
    "trong 16 nhãn sau, đồng thời trích xuất các tham số liên quan (nếu có) vào trường 'params':\n\n"
    "- ocr: muốn đọc to chữ/văn bản in trong ảnh — sách, giấy tờ, nhãn sản phẩm, tin nhắn viết tay.\n"
    "- find: muốn tìm một đồ vật cụ thể hoặc hỏi hướng đi ngắn trong phòng.\n"
    "- money: muốn biết mệnh giá tờ tiền đang cầm trên tay.\n"
    "- space: muốn biết không gian phía trước/xung quanh có những gì (mô tả khung cảnh).\n"
    "- hazard: muốn biết phía trước có an toàn không, có vật cản gì cần tránh.\n"
    "- nav_start: muốn bắt đầu chỉ đường / điều hướng đi bộ ngoài trời đến địa điểm cụ thể. "
    "Ví dụ: \"chỉ đường cho tôi tới Bưu điện\", \"bắt đầu chỉ đường đến chợ Bến Thành\". "
    "(Trích xuất 'destination' là địa chỉ/tên điểm đến).\n"
    "- nav_stop: muốn dừng chỉ đường / dừng điều hướng. Ví dụ: \"dừng chỉ đường\", \"tắt chỉ đường\".\n"
    "- contact_call: muốn gọi điện thoại cho một người trong danh bạ. Ví dụ: \"gọi cho Nguyễn Văn A\", "
    "\"gọi điện cho mẹ\". (Trích xuất 'contact_name' là tên người cần gọi).\n"
    "- emergency_call: muốn gọi cấp cứu, gọi khẩn cấp hoặc gửi tin nhắn SOS khẩn cấp. "
    "Ví dụ: \"gọi cấp cứu\", \"gọi khẩn cấp\", \"cứu tôi với\", \"phát tín hiệu khẩn cấp\". "
    "(Có thể trích xuất 'emergency_number' nếu người dùng đọc số cụ thể).\n"
    "- ride_quote: muốn báo giá / đặt chuyến xe / đặt xe Grab đi tới đâu đó. "
    "Ví dụ: \"đặt xe đi Bách Khoa\", \"gọi xe tới sân bay\", \"báo giá chuyến đi về nhà\". "
    "(Trích xuất 'destination' là địa chỉ điểm đến).\n"
    "- ride_confirm: muốn xác nhận hoặc hủy chuyến xe đã báo giá. "
    "Ví dụ: \"xác nhận đặt xe\", \"đồng ý chuyến xe\", \"hủy chuyến xe\". "
    "(Trích xuất 'confirm' là true nếu đồng ý/xác nhận, false nếu hủy).\n"
    "- music_play: muốn phát / mở bài hát hay nghe nhạc. "
    "Ví dụ: \"mở bài hát Nơi này có anh\", \"phát nhạc Sơn Tùng\". "
    "(Trích xuất 'song' là tên bài hát/nghệ sĩ, 'volume' nếu có nói âm lượng). "
    "Một câu chỉ gồm tên ca sĩ (\"Sơn Tùng M-TP\") hoặc một câu như \"cứ phát\", "
    "\"bản nào cũng được\" cũng là music_play — đó là người dùng đang trả lời câu "
    "hỏi \"bạn muốn nghe của ca sĩ nào?\", và 'song' chính là nguyên câu họ vừa nói.\n"
    "- music_stop: muốn tắt nhạc, dừng phát nhạc. Ví dụ: \"tắt nhạc\", \"dừng nhạc\".\n"
    "- music_volume: muốn điều chỉnh âm lượng nghe nhạc (tăng, giảm, chỉnh mức âm lượng). "
    "Ví dụ: \"tăng âm lượng\", \"giảm âm lượng\", \"chỉnh âm lượng lên 70\". "
    "(Trích xuất 'direction' là \"up\" hoặc \"down\", hoặc 'volume' là mức 0..100).\n"
    "- chat: câu CÓ nghĩa nhưng không thuộc các nhóm trên — trò chuyện tự do, "
    "hỏi đáp thông thường, chào hỏi.\n"
    "- unknown: câu KHÔNG mang ý nghĩa nào đọc ra được. Thường là do nhận dạng "
    "giọng nói nghe nhầm thành một chuỗi từ rời rạc, micro chỉ thu được tiếng ồn, "
    "hoặc người dùng lỡ bấm gửi khi chưa nói. "
    "Ví dụ: \"ờ à ừm\", \"xe xe xe xe\", \"a bờ cờ dờ\", \"lô ca ta xi mà\".\n\n"
    "Ranh giới chat / unknown — đọc kỹ, đây là chỗ dễ sai nhất:\n"
    "- Câu ngắn, cụt, sai ngữ pháp hay nói trống không mà VẪN đoán ra ý thì "
    "KHÔNG phải unknown. \"mấy giờ rồi\", \"nóng quá\", \"ê\", \"buồn ngủ ghê\" "
    "đều là chat.\n"
    "- Chỉ chọn unknown khi bạn thật sự không nói được người dùng muốn gì. "
    "Người khiếm thị không đọc được màn hình để sửa, nên hỏi lại một câu rõ ràng "
    "vẫn hơn là đoán bừa rồi trả lời lạc đề.\n"
    "- Nhưng đừng lạm dụng: nghi ngờ mà vẫn mơ hồ đoán được ý thì chọn chat.\n\n"
    "RIÊNG nhãn 'chat', trả thêm hai cờ trong 'params' để hệ thống chỉ làm đúng "
    "phần việc cần thiết (mỗi thứ thừa đều làm người dùng chờ lâu hơn):\n"
    "- needs_location: true khi câu trả lời phụ thuộc người dùng đang ở đâu — "
    "\"trời hôm nay thế nào\", \"quán cà phê gần đây\", \"tôi đang ở đâu\", "
    "\"bao xa tới đó\". false khi ở đâu cũng trả lời như nhau.\n"
    "  Mọi cách nói mang nghĩa \"chỗ tôi đang đứng\" đều là true, không cần "
    "người dùng đọc ra địa chỉ: \"gần nhất\", \"gần đây\", \"quanh đây\", "
    "\"gần chỗ tôi\", \"ở đây\", \"chỗ này\", \"lân cận\", \"xung quanh\". "
    "Ví dụ \"nhà thuốc gần nhất ở đâu\", \"có quán ăn nào quanh đây không\", "
    "\"trạm xe buýt gần nhất\" — tất cả đều needs_location=true. "
    "Người khiếm thị hỏi \"gần nhất\" là đang hỏi gần CHỖ HỌ ĐỨNG; bỏ cờ này "
    "thì model không có mốc nào để tính gần xa và sẽ trả lời theo một thành phố "
    "nó tự chọn.\n"
    "- needs_web: true khi câu trả lời thay đổi theo ngày và phải tra mới biết — "
    "thời tiết, tin tức, tỉ số, giá cả, giờ mở cửa, sự kiện đang diễn ra. "
    "false với kiến thức chung, tính toán, định nghĩa, trò chuyện xã giao, "
    "hoặc câu hỏi về chính cuộc trò chuyện này.\n"
    "Hai cờ độc lập: có thể cả hai cùng true (\"trời hôm nay thế nào\"), "
    "cùng false (\"kể chuyện cười đi\"), hoặc chỉ một.\n\n"
    "Câu lệnh cần phân loại: \"{command_text}\"\n\n"
    "Trả về đúng định dạng JSON có trường 'intent' và 'params'."
)

# Bản đang dùng. Rút từ ~1474 xuống ~430 token bằng ba cách, KHÔNG cắt luật nào:
#
# 1. Bỏ mô tả kiểu dữ liệu của tham số. `_SCHEMA` đã liệt kê đủ tên trường, kiểu
#    và enum rồi, và Gemini nhận schema đó ở mọi lượt gọi — viết lại trong prompt
#    là trả tiền hai lần cho cùng một thông tin.
# 2. Bỏ ví dụ ở những nhãn mà tên nhãn đã tự nói ra nghĩa (`nav_stop`,
#    `music_stop`). Giữ ví dụ ở đúng ba chỗ từng đo được là hay sai:
#    ranh giới chat/unknown, ca "trả lời câu hỏi ca sĩ" của music_play, và
#    những cách nói mang nghĩa "chỗ tôi đang đứng".
# 3. Đổi văn xuôi giải thích thành gạch đầu dòng mệnh lệnh.
#
# CẢNH BÁO: mỗi luật còn lại đều đến từ một lần hỏng đo được ngoài đời (xem
# lịch sử git của file này). Rút thêm nữa thì đo lại bằng
# `tools/bench_intent_prompt.py` trước, đừng cắt theo cảm giác.
_PROMPT_TEMPLATE = (
    "Phân loại ý định câu lệnh thoại của người khiếm thị dùng kính hỗ trợ.\n"
    "Chọn ĐÚNG MỘT nhãn, trích tham số vào 'params'.\n\n"
    "ocr: đọc chữ in/viết trong ảnh (sách, giấy tờ, nhãn, biển hiệu).\n"
    "find: tìm một đồ vật cụ thể trong phòng.\n"
    "money: mệnh giá tờ tiền đang cầm.\n"
    "space: phía trước/xung quanh CÓ GÌ (tả khung cảnh).\n"
    "hazard: phía trước CÓ AN TOÀN không, vật cản cần tránh.\n"
    "nav_start: bắt đầu chỉ đường đi bộ tới một nơi (destination).\n"
    "nav_stop: dừng chỉ đường.\n"
    "contact_call: gọi điện cho người trong danh bạ (contact_name).\n"
    "emergency_call: gọi cấp cứu/khẩn cấp/SOS (emergency_number nếu có đọc số).\n"
    "ride_quote: đặt xe/gọi Grab đi đâu đó (destination).\n"
    "ride_confirm: xác nhận hoặc huỷ chuyến vừa báo giá (confirm).\n"
    "music_play: phát nhạc/mở bài hát (song, volume nếu có).\n"
    "  Câu chỉ có tên ca sĩ, hoặc \"cứ phát\"/\"bài nào cũng được\", cũng là\n"
    "  music_play — đó là trả lời câu hỏi \"muốn nghe của ca sĩ nào?\", và\n"
    "  song chính là nguyên câu vừa nói.\n"
    "music_stop: tắt nhạc.\n"
    "music_volume: chỉnh âm lượng (direction up/down, hoặc volume 0..100).\n"
    "chat: câu CÓ nghĩa nhưng không thuộc nhóm trên — hỏi đáp, chào hỏi, than thở.\n"
    "unknown: câu KHÔNG đọc ra nghĩa nào. Thường do nghe nhầm thành chuỗi từ rời\n"
    "  rạc, hoặc mic chỉ thu được tiếng ồn. Ví dụ \"ờ à ừm\", \"xe xe xe xe\".\n\n"
    "Ranh giới chat/unknown — chỗ dễ sai nhất:\n"
    "- Câu ngắn, cụt, sai ngữ pháp mà VẪN đoán ra ý thì là chat, không phải\n"
    "  unknown: \"mấy giờ rồi\", \"nóng quá\", \"ê\", \"buồn ngủ ghê\".\n"
    "- Chỉ chọn unknown khi thật sự không nói được người dùng muốn gì. Người\n"
    "  khiếm thị không đọc màn hình để sửa, hỏi lại còn hơn đoán bừa rồi lạc đề.\n"
    "- Nhưng mơ hồ mà vẫn đoán được ý thì chọn chat.\n\n"
    "RIÊNG nhãn chat, trả thêm hai cờ độc lập trong 'params':\n"
    "- needs_location: true khi câu trả lời phụ thuộc người dùng đang ở đâu.\n"
    "  Mọi cách nói nghĩa \"chỗ tôi đang đứng\" đều tính, không cần đọc địa chỉ:\n"
    "  \"gần nhất\", \"gần đây\", \"quanh đây\", \"ở đây\", \"lân cận\". Thiếu cờ\n"
    "  này thì model không có mốc nào để tính gần xa và tự chọn một thành phố.\n"
    "- needs_web: true khi câu trả lời đổi theo ngày và phải tra mới biết —\n"
    "  thời tiết, tin tức, tỉ số, giá cả, giờ mở cửa. false với kiến thức chung,\n"
    "  tính toán, xã giao, hoặc hỏi về chính cuộc trò chuyện này.\n\n"
    "Câu lệnh: \"{command_text}\"\n\n"
    "Trả JSON có 'intent' và 'params'."
)


# Bối cảnh thiết bị chèn vào trước câu lệnh.
#
# "Tắt đi", "dừng lại", "thôi đủ rồi" KHÔNG tự nó cho biết tắt cái gì. Đo trên
# bộ câu huấn luyện, `nav_stop` <-> `music_stop` là cặp lẫn nhau nhiều nhất, và
# thêm dữ liệu không chữa được: chính người nghe cũng chịu nếu không biết cái gì
# đang chạy. Thứ gỡ được nút này là trạng thái lúc chạy, không phải model to hơn.
_CONTEXT_TEMPLATE = (
    "Bối cảnh thiết bị NGAY LÚC NÀY:\n"
    "- Nhạc: {music}\n"
    "- Chỉ đường: {nav}\n"
    "- Chuyến xe đã báo giá, đang chờ xác nhận: {ride}\n\n"
    "Dùng bối cảnh này khi câu lệnh không tự nói ra tắt/dừng cái gì "
    "(\"tắt đi\", \"dừng lại\", \"thôi\", \"đủ rồi\", \"không cần nữa\"):\n"
    "- Chỉ nhạc đang phát -> music_stop.\n"
    "- Chỉ chỉ đường đang chạy -> nav_stop.\n"
    "- Cả hai cùng chạy -> chọn cái vừa bật gần đây nhất: {recent}.\n"
    "- Không cái nào chạy -> đừng đoán bừa hai nhãn đó; nếu câu không còn manh "
    "mối nào khác thì chọn unknown.\n"
    "Câu lệnh có nói rõ ra ("
    "\"tắt nhạc\", \"dừng chỉ đường\") thì cứ theo câu lệnh, bỏ qua bối cảnh.\n\n"
)

_RECENT_LABELS = {"music_playing": "nhạc (music_stop)", "navigating": "chỉ đường (nav_stop)"}


def _context_block(state: dict | None) -> str:
    if not state:
        return ""
    recent = _RECENT_LABELS.get(state.get("most_recent") or "", "không có cái nào")
    return _CONTEXT_TEMPLATE.format(
        music="ĐANG PHÁT" if state.get("music_playing") else "không phát",
        nav="ĐANG CHẠY" if state.get("navigating") else "không chạy",
        ride="có" if state.get("ride_quote_pending") else "không",
        recent=recent,
    )


# Từ khoá cho biết câu lệnh đã NÓI RÕ tắt/dừng cái gì.
#
# Cần vì độ tự tin của bộ phân loại cục bộ KHÔNG phân biệt được rõ với mơ hồ.
# Đo thật: "tắt đi" ra `nav_stop` với conf 0.848 và biên 0.829 — tự tin ngang
# "dừng chỉ đường" (0.870/0.860), dù câu trước hoàn toàn mơ hồ. Dữ liệu huấn
# luyện đã lỡ gán bừa "tắt đi" về một bên nên model học theo. Hai ngưỡng không
# cứu được chuyện này; chỉ có mặt chữ mới cứu được.
_MUSIC_WORDS = ("nhạc", "bài hát", "bài nhạc", "ca sĩ")
_NAV_WORDS = ("chỉ đường", "điều hướng", "dẫn đường", "bản đồ", "lộ trình", "chỉ lối")


def _named_stop_target(text: str) -> str | None:
    """Câu lệnh có tự nói ra tắt/dừng cái gì không. `None` = nói trống không."""
    lowered = (text or "").lower()
    if any(word in lowered for word in _NAV_WORDS):
        return Intent.NAV_STOP
    if any(word in lowered for word in _MUSIC_WORDS):
        return Intent.MUSIC_STOP
    return None


def _apply_state(label: str, state: dict | None, text: str = "") -> str | None:
    """Gỡ mơ hồ tắt/dừng bằng trạng thái thiết bị. `None` = chịu, hỏi Gemini.

    Thứ tự quan trọng: CÂU CHỮ trước, trạng thái sau. Người dùng nói "tắt nhạc"
    trong lúc đang chỉ đường thì phải ra `music_stop` — họ nói gì làm nấy. Xếp
    ngược lại thì bối cảnh lấn câu lệnh, và đó chính là bug đo được ở lần chạy
    E2E đầu tiên: "tắt nhạc" + đang chỉ đường ra `nav_stop`.

    Áp đúng bộ luật đang dùng trong prompt Gemini (xem `_CONTEXT_TEMPLATE`) để
    hai đường đi cho cùng một kết quả.
    """
    if label not in _STATE_DEPENDENT:
        return label

    named = _named_stop_target(text)
    if named is not None:
        return named

    state = state or {}
    music, nav = state.get("music_playing"), state.get("navigating")
    if music and not nav:
        return Intent.MUSIC_STOP
    if nav and not music:
        return Intent.NAV_STOP
    if music and nav:
        recent = state.get("most_recent")
        return Intent.MUSIC_STOP if recent == "music_playing" else Intent.NAV_STOP
    # Không cái nào chạy. Người dùng vẫn có thể vừa nói rõ "tắt nhạc" — nhãn cục
    # bộ đúng, chỉ là chưa có gì để tắt, và handler tự nói câu đó. Nhưng cũng có
    # thể họ chỉ nói "tắt đi" trống không, lúc đó đoán là sai. Không phân biệt
    # được bằng nhãn, nên trả `None` để Gemini đọc lại nguyên câu.
    return None


def _build_prompt(command_text: str, state: dict | None = None) -> str:
    return _context_block(state) + _PROMPT_TEMPLATE.format(command_text=command_text)


def detect_with_params(text: str, state: dict | None = None) -> tuple[str, dict]:
    """Phân loại ý định và trích xuất tham số từ câu lệnh giọng nói.

    `state`: cái gì đang chạy trên điện thoại (xem `action_flow.device_state()`).
    Bỏ trống thì bước phân loại chạy như cũ — chỉ mất khả năng gỡ mơ hồ cho
    những câu tắt/dừng nói trống không.

    Trả về (intent_name, params_dict).
    """
    if not text.strip():
        return Intent.UNKNOWN, {}

    if state is None:
        # Nhập sau, không phải lúc import: `handlers` phụ thuộc ngược lại vào
        # `pipeline` (qua tts/phrases), nhập ở đầu file là vòng tròn.
        from handlers.action_flow import device_state

        state = device_state()

    local = intent_local.classify(text)
    if local is not None:
        resolved = _apply_state(local.label, state, text)
        if resolved is not None and resolved in _PARAM_FREE:
            logger.info(
                "phân loại cục bộ: %s (conf=%.2f biên=%.2f)",
                resolved, local.confidence, local.margin,
            )
            return resolved, {}

        # Nhãn cần tham số, nhưng có nhãn mà tham số của nó là bài PHÂN LOẠI
        # chứ không phải trích chuỗi (`chat` hai cờ, `music_volume` hướng,
        # `ride_confirm` đồng ý/huỷ). Head cục bộ đọc được, và gần như miễn phí
        # vì dùng lại chính embedding vừa tính.
        if resolved is not None:
            params = intent_local.read_params(resolved, local)
            if params is not None:
                logger.info(
                    "phân loại cục bộ: %s %s (conf=%.2f biên=%.2f)",
                    resolved, params, local.confidence, local.margin,
                )
                return resolved, params
        # Đủ chắc về nhãn nhưng nhãn đó cần tham số (hoặc trạng thái không gỡ
        # được mơ hồ) -> vẫn phải hỏi Gemini. Không dùng nhãn cục bộ làm gợi ý
        # trong prompt: gợi ý sai thì Gemini bị neo theo, mà mỗi lần nó tự phân
        # loại lại là một cơ hội sửa cho bước cục bộ.

    # `classify_failed` phân biệt "phân loại xong, kết luận là vô nghĩa" với
    # "chưa phân loại được vì hệ thống hỏng". Cùng ra nhãn `unknown` nhưng lỗi
    # của ai thì khác nhau — nói "tôi chưa hiểu bạn muốn gì" khi thật ra Gemini
    # vừa timeout là đổ lỗi cho người dùng về một việc họ không làm sai.
    try:
        reply = vlm.generate_json(
            _build_prompt(text, state), schema=_SCHEMA, model=config.GEMINI_INTENT_MODEL
        )
    except vlm.VLMError:
        return Intent.UNKNOWN, {"classify_failed": True}

    if not isinstance(reply, dict):
        return Intent.UNKNOWN, {"classify_failed": True}

    intent_val = reply.get("intent")
    if intent_val not in _LABELS:
        return Intent.UNKNOWN, {"classify_failed": True}

    params = reply.get("params")
    if not isinstance(params, dict):
        params = {}

    return intent_val, params


def detect(text: str) -> str:
    """Trả về nhãn intent tương thích ngược."""
    intent_val, _ = detect_with_params(text)
    return intent_val
