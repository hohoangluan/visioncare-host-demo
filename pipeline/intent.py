import logging
import re

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
# `chat` VÀO ĐÂY từ khi bỏ hai cờ `needs_location`/`needs_web`. Trước đó nó là
# nhãn phổ biến nhất mà LUÔN phải qua Gemini — đo trên 18 câu chat của tập eval:
# 0/18 câu xong được ở bước cục bộ, vì hai head tham số chỉ nhận 20% và 3.3%, mà
# cả hai phải cùng qua ngưỡng nên coverage thực tế nhân lại còn ~4%.
#
# Hai cờ đó giờ không còn ai sinh ra: vị trí do thread nền giữ nóng nên cứ nhét
# vào prompt, còn có tra Google hay không thì chính model quyết lúc sinh chữ
# (xem `handlers/chat.py` và `config.CHAT_ALWAYS_SEARCH`).
#
# Các nhãn còn lại (`nav_start` cần destination, `contact_call` cần
# contact_name, `music_play` cần song...) vẫn phải qua Gemini vì SetFit chỉ sinh
# ra nhãn, không trích được slot. Chi phí ~0.9s đó rơi đúng vào những nhãn sau
# đó còn phải chờ điện thoại 5-20s, nên không nghe ra.
_PARAM_FREE = frozenset({
    Intent.OCR, Intent.FIND, Intent.MONEY, Intent.SPACE, Intent.HAZARD,
    Intent.CHAT, Intent.NAV_STOP, Intent.MUSIC_STOP, Intent.UNKNOWN,
    # B5 (T05-intent-slots.md): "thôi bỏ đi"/"nói lại đi" không cần tham số nào.
    "cancel", "repeat",
})

# Hai nhãn này phụ thuộc trạng thái thiết bị, mà bộ phân loại cục bộ chỉ đọc
# chữ. "Tắt đi" ra `music_stop` hay `nav_stop` là do cái gì đang chạy quyết
# định, không do câu chữ.
_STATE_DEPENDENT = frozenset({Intent.NAV_STOP, Intent.MUSIC_STOP})

# `unknown` KHÔNG còn là nhãn được chọn.
#
# Trước đây nó là một lựa chọn thật: câu nghe ra chữ nhưng không ra nghĩa thì
# gán `unknown` và trả về một câu từ chối cứng. Bỏ vì nó bắt bộ phân loại quyết
# một việc mà chính người nghe cũng không chắc — mà quyết sai theo chiều này thì
# người dùng bị từ chối oan một câu hoàn toàn hợp lệ.
#
# Giờ những câu đó về `chat`, và chính Gemini nói "tôi chưa hiểu" khi nó không
# đoán ra ý (ràng buộc nằm trong `_SYSTEM_PROMPT` của `handlers/chat.py`).
# Gemini đọc được nguyên văn câu nói, bộ phân loại thì chỉ trả một cái nhãn —
# nên nó phán được việc này chính xác hơn, và trả lời được đúng câu vừa nói
# thay vì đọc một câu soạn sẵn.
#
# `Intent.UNKNOWN` vẫn còn trong `schemas.py` và vẫn dùng, nhưng chỉ còn hai
# nguồn sinh, cả hai đều là trạng thái LỖI chứ không phải kết quả phân loại:
# STT trả chuỗi rỗng, và lượt gọi Gemini phân loại hỏng.
_LABELS = (
    Intent.OCR, Intent.FIND, Intent.MONEY, Intent.SPACE, Intent.HAZARD, Intent.CHAT,
    Intent.NAV_START, Intent.NAV_STOP,
    Intent.CONTACT_CALL, Intent.EMERGENCY_CALL,
    Intent.RIDE_QUOTE, Intent.RIDE_CONFIRM,
    Intent.MUSIC_PLAY, Intent.MUSIC_STOP, Intent.MUSIC_VOLUME,
    # B5 — hai nhãn THOÁT, người khiếm thị cần cả hai. Không có hằng số tương
    # ứng trong `schemas.Intent` (file đó KHÔNG nằm trong "FILE BẠN ĐƯỢC SỬA"
    # của T05) — dùng thẳng chuỗi literal, khớp với giá trị mà
    # `_LOCAL_CANCEL_WORDS`/`_LOCAL_REPEAT_WORDS` bên dưới trả về.
    "cancel", "repeat",
)

# B5 — bắt "cancel"/"repeat" TẤT ĐỊNH, không mạng ngoài, không LLM (ngân sách
# < 300ms, T21/G1). Chạy trước cả SetFit lẫn Gemini trong `detect_with_params`.
#
# ⚠️ Xem docs/tasks/reports/T05.md mục "Lệch với task file": `pipeline/router.py`
# (T04) đã có MỘT bộ regex cancel/repeat riêng ở bước 3/5, chạy TRƯỚC khi một
# câu tới được `detect_with_params` (bước 6). Hai regex dưới đây vì vậy chủ yếu
# là lưới dự phòng cho lượt gọi `detect_with_params` trực tiếp (không qua
# router) hoặc câu lọt qua bộ regex kia — không phải đường chính người dùng đi
# qua trong `/process` thật. Giữ ở đây vì `pipeline/intent.py` phải tự đứng
# được một mình (test đơn vị, lời gọi trực tiếp), và vì đây đúng là phạm vi
# B5 giao cho T05 (`_LABELS`/`_PARAM_FREE` ở FILE NÀY).
_LOCAL_CANCEL_WORDS = re.compile(
    r"\bhủy\b|\bhuỷ\b|bỏ đi|thôi khỏi|không cần nữa|\bthôi\b", re.I
)
_LOCAL_REPEAT_WORDS = re.compile(
    r"nói lại|nhắc lại|lặp lại|nghe không rõ|gì cơ|sao cơ", re.I
)

_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": list(_LABELS)},
        "params": {
            "type": "object",
            "properties": {
                "destination": {"type": "string"},
                # A1 (T05-intent-slots.md): bản THÔ nguyên văn STT, giữ song
                # song với `destination` (đã sửa lỗi nghe nhầm) để log được tỉ
                # lệ sửa đúng/sai — xem `_STT_CORRECTION_BLOCK`.
                "destination_raw": {"type": "string"},
                "contact_name": {"type": "string"},
                # "song" GIỮ NGUYÊN làm alias trong lúc chuyển: `handlers/music.py`
                # và hợp đồng host (`endpoint.md:131`) vẫn dùng chuỗi
                # "Tên - Ca sĩ" nguyên khối này. KHÔNG xoá.
                "song": {"type": "string"},
                "song_title": {"type": "string"},
                "artist": {"type": "string"},
                # true = người dùng đọc rõ tên bài hát cụ thể; false = câu trả
                # lời chung chung ("cứ phát", "bài nào cũng được") hoặc chỉ có
                # tên ca sĩ.
                "song_is_specific": {"type": "boolean"},
                "volume": {"type": "integer"},
                "direction": {"type": "string", "enum": ["up", "down"]},
                "confirm": {"type": "boolean"},
                "quote_id": {"type": "string"},
                "emergency_number": {"type": "string"},
                "needs_location": {"type": "boolean"},
                "needs_web": {"type": "boolean"},
                # A1 — đầu vào của readback (T06/D3): "low" thì T06 đọc lại
                # slot cho người dùng xác nhận trước khi dùng.
                "slot_confidence": {"type": "string", "enum": ["high", "low"]},
                # A1 — hướng người dùng đang hỏi (find/hazard/space): "cái ví
                # của tôi ở BÊN TRÁI đâu rồi".
                "focus": {"type": "string", "enum": ["left", "right", "front", "behind"]},
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
    "find: tìm một ĐỒ VẬT cụ thể trong tầm tay, thường là đồ của người dùng.\n"
    "money: mệnh giá tờ tiền đang cầm.\n"
    "space: phía trước/xung quanh CÓ GÌ (tả khung cảnh).\n"
    "hazard: phía trước CÓ AN TOÀN không, vật cản cần tránh.\n"
    "nav_start: bắt đầu chỉ đường đi bộ tới một nơi (destination).\n"
    "nav_stop: dừng chỉ đường.\n"
    "contact_call: gọi điện cho người trong danh bạ (contact_name).\n"
    "emergency_call: gọi cấp cứu/khẩn cấp/SOS (emergency_number nếu có đọc số).\n"
    "ride_quote: đặt xe/gọi Grab đi đâu đó (destination).\n"
    "ride_confirm: xác nhận hoặc huỷ chuyến vừa báo giá (confirm).\n"
    "music_play: phát nhạc/mở bài hát. Điền CẢ HAI kiểu tham số nếu nghe ra:\n"
    "  - song (alias cũ, GIỮ để tương thích ngược): chuỗi \"Tên bài - Ca sĩ\",\n"
    "    hoặc chỉ một trong hai nếu câu không nói đủ.\n"
    "  - song_title/artist (mới, TÁCH RIÊNG): song_title là tên bài, artist là\n"
    "    tên ca sĩ, kể cả khi câu chỉ nói một trong hai.\n"
    "  song_is_specific = true khi người dùng đọc rõ TÊN BÀI cụ thể; false khi\n"
    "  câu chỉ có tên ca sĩ, hoặc \"cứ phát\"/\"bài nào cũng được\" — đó là trả\n"
    "  lời câu hỏi \"muốn nghe của ca sĩ nào?\", lúc này ĐỪNG điền song_title,\n"
    "  và song vẫn là nguyên câu vừa nói.\n"
    "music_stop: tắt nhạc.\n"
    "music_volume: chỉnh âm lượng (direction up/down, hoặc volume 0..100).\n"
    "cancel: muốn HUỶ hẳn việc đang hỏi/đang chờ trả lời — khác music_stop/\n"
    "  nav_stop (hai nhãn đó là tắt nhạc/dừng chỉ đường đang CHẠY, không phải\n"
    "  huỷ một câu hỏi). \"thôi bỏ đi\", \"không cần nữa\", \"huỷ đi\".\n"
    "repeat: muốn nghe LẠI câu vừa rồi vì không nghe rõ/không hiểu. \"gì cơ\",\n"
    "  \"nói lại đi\", \"sao cơ\".\n"
    "chat: MỌI thứ còn lại — hỏi đáp, chào hỏi, than thở, hỏi giờ, hỏi thời\n"
    "  tiết, hỏi mình đang ở đâu, nhờ kể chuyện. Kể cả câu nghe cụt, sai ngữ\n"
    "  pháp, hay không đọc ra nghĩa gì: cứ chọn chat, đừng cố loại bỏ.\n"
    "  Đây là nhãn mặc định, nhưng CHỈ khi câu không khớp nhãn nào ở trên —\n"
    "  khớp rồi thì lấy nhãn đó, đừng rơi về chat cho chắc.\n\n"
    "Mẫu \"X ở đâu\" thuộc nhãn nào là do X quyết định, không do mặt chữ:\n"
    "- X là ĐỒ VẬT trong tầm tay -> find. \"gói bánh của tôi ở đâu\", \"cái\n"
    "  điều khiển đâu rồi\", \"ly nước để đâu\".\n"
    "- X là ĐỊA ĐIỂM, cơ sở, dịch vụ ngoài đời -> chat. \"nhà thuốc gần nhất ở\n"
    "  đâu\", \"quanh đây có quán ăn không\", \"trạm xe buýt chỗ nào\".\n"
    "- Người dùng nhờ DẪN ĐI tới đó -> nav_start, không phải hai nhãn trên.\n\n"
    "Câu lệnh: \"{command_text}\"\n\n"
    "Trả JSON có 'intent' và 'params'."
)


# A2 (T05-intent-slots.md mục 2): STT là Zipformer-vi 30M int8 (`pipeline/
# stt.py`), sai tên riêng liên tục. Không có khối này, prompt trích slot chỉ
# trích SPAN nguyên văn — tức là chép lại đúng lỗi nghe nhầm rồi đem đi query
# (chỉ đường sai chỗ, tìm bài hát sai tên).
#
# Ba mệnh lệnh dưới đây đều BẮT BUỘC, thiếu một là hỏng một kiểu khác nhau:
# 1. SỬA — không sửa thì chép lại lỗi.
# 2. THÚ NHẬN khi không sửa được (đặt slot_confidence=low) — thiếu vế này thì
#    T06/D3 (readback theo slot_confidence) không có tín hiệu để hỏi lại.
# 3. CẤM BỊA — thiếu vế này thì model "sửa" bằng cách tự nghĩ ra số nhà/tên
#    đường/tên album chưa từng nghe thấy, còn hại hơn chép lại nguyên lỗi.
_STT_CORRECTION_BLOCK = (
    "Câu lệnh trên do máy nhận dạng giọng nói tiếng Việt (model nhỏ) ghi lại. "
    "TÊN RIÊNG (địa danh, tên người, tên bài hát) bị nghe sai rất nhiều.\n"
    "- SỬA: khi trích slot, sửa về dạng đúng mà bạn tin người dùng định nói, "
    "đừng chép lại lỗi nghe nhầm. Ví dụ: \"Bát Khoa\" -> \"Bách Khoa\".\n"
    "- THÚ NHẬN: không sửa được (không đủ tự tin) thì GIỮ NGUYÊN văn bản gốc "
    "và đặt slot_confidence = \"low\". Sửa được, tự tin thì slot_confidence = "
    "\"high\".\n"
    "- CẤM BỊA: KHÔNG bịa thêm số nhà, tên đường, tên album mà câu lệnh không "
    "hề nhắc tới. Không đoán ra được một TÊN RIÊNG là gì (nghe như một chuỗi "
    "âm tiết vô nghĩa) thì GIỮ NGUYÊN đúng nguyên văn đã nghe — ĐỪNG thay "
    "bằng một tên nghe có vẻ hợp lý (kể cả tên nước ngoài, tên công ty, tên "
    "địa điểm nổi tiếng) mà bạn không chắc chắn.\n\n"
)


# B3 (T05-intent-slots.md mục 2): có pending (`kind == "fill"`) đang mở thì câu
# vừa nói RẤT có thể là câu trả lời trần trụi ("Sơn Tùng", "đúng rồi", "mẹ") —
# không tự nó mang nghĩa gì nếu đọc rời khỏi ngữ cảnh câu hỏi vừa hỏi. Khối này
# cho Gemini biết ngữ cảnh đó, và bắt buộc phải có vế thứ ba ("việc hoàn toàn
# khác thì bỏ qua pending") — thiếu vế đó thì MỌI câu trong 120s sau một câu
# hỏi đều bị kéo về đúng slot đang chờ, kể cả "gọi cho mẹ" giữa lúc đang hỏi
# tên bài hát.
_PENDING_PROMPT_TEMPLATE = (
    "Hệ thống VỪA HỎI người dùng: \"{question}\"\n"
    "Câu vừa nói RẤT có thể là câu trả lời cho câu hỏi này, kể cả khi nó cụt "
    "hoặc chỉ có một từ.\n"
    "- Nếu ĐÚNG là câu trả lời cho câu hỏi trên -> intent = \"{intent}\", trích "
    "giá trị vừa nói vào slot \"{slot}\".\n"
    "- Nếu là câu HUỶ (\"thôi\", \"bỏ đi\", \"không cần nữa\", \"huỷ\") -> "
    "intent = \"cancel\".\n"
    "- Nếu là việc HOÀN TOÀN KHÁC, không liên quan câu hỏi trên -> BỎ QUA câu "
    "hỏi này, phân loại bình thường theo danh sách nhãn bên dưới như một câu "
    "nói mới, đừng cố ép về slot \"{slot}\".\n\n"
)


def _pending_block(pending) -> str:
    return _PENDING_PROMPT_TEMPLATE.format(
        question=pending.question, intent=pending.intent, slot=pending.slot,
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


def _location_block() -> str:
    """A3 (T05-intent-slots.md mục 2): vị trí hiện tại cho bước PHÂN LOẠI ý
    định — `nav_start`/`ride_quote` là hai nhãn cần vị trí nhất
    ("Bách Khoa" là Hà Nội hay TP.HCM?) nhưng trước T05 không được cấp gì.

    Dùng LẠI `handlers.chat._location_text()`/`_location_available()`
    (T07) — không viết lại logic cache/TTL/backoff ở đây.

    ⚠️ KHÁC hẳn `handlers/chat.py` (C1): ở đó vị trí rỗng vẫn PHẢI chèn khối
    cấm bịa, vì `chat` là bước SINH CÂU TRẢ LỜI tự do và im lặng bỏ qua sẽ khiến
    model tự bịa một thành phố. Ở đây là bước PHÂN LOẠI NHÃN — không có vị trí
    thật thì KHÔNG chèn dòng nào cả (đừng tốn token nói "chưa rõ vị trí" cho
    một nhãn không cần tới vị trí, ví dụ `ocr`/`money`), im lặng bỏ qua là đúng.
    """
    from handlers import chat as chat_mod  # lazy: tránh vòng import lúc nạp module

    if not chat_mod._location_available():
        return ""
    return f"Vị trí hiện tại của người dùng: {chat_mod._location_text()}\n\n"


def _context_block(state: dict | None) -> str:
    location = _location_block()
    if not state:
        return location
    recent = _RECENT_LABELS.get(state.get("most_recent") or "", "không có cái nào")
    return location + _CONTEXT_TEMPLATE.format(
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


def _build_prompt(command_text: str, state: dict | None = None, pending=None) -> str:
    """Ráp prompt trích slot đầy đủ: khối pending (B3, nếu có) + bối cảnh thiết
    bị/vị trí (A3) + khối sửa lỗi STT (A2) + phần khai báo nhãn/tham số.

    `pending`: object có `.question`/`.intent`/`.slot` (khớp
    `handlers.action_flow.Pending`) — `None` khi không có pending nào, hoặc
    khi pending không phải loại `fill` (xem `detect_with_params`).
    """
    pending_block = _pending_block(pending) if pending is not None else ""
    return (
        pending_block
        + _context_block(state)
        + _STT_CORRECTION_BLOCK
        + _PROMPT_TEMPLATE.format(command_text=command_text)
    )


def _ask_gemini(prompt: str) -> tuple[str, dict]:
    """Gọi Gemini phân loại + validate reply. DÙNG CHUNG cho đường thường
    (SetFit không đủ chắc) VÀ đường có pending (B3) — một nguồn xử lý lỗi duy
    nhất, tránh hai chỗ hai cách xử lý `VLMError`/reply hỏng.

    `classify_failed` phân biệt "phân loại xong, kết luận là vô nghĩa" với
    "chưa phân loại được vì hệ thống hỏng". Cùng ra nhãn `unknown` nhưng lỗi
    của ai thì khác nhau — nói "tôi chưa hiểu bạn muốn gì" khi thật ra Gemini
    vừa timeout là đổ lỗi cho người dùng về một việc họ không làm sai.
    """
    try:
        reply = vlm.generate_json(prompt, schema=_SCHEMA, model=config.GEMINI_INTENT_MODEL)
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


def detect_with_params(
    text: str, state: dict | None = None, pending=None
) -> tuple[str, dict]:
    """Phân loại ý định và trích xuất tham số từ câu lệnh giọng nói.

    `state`: cái gì đang chạy trên điện thoại (xem `action_flow.device_state()`).
    Bỏ trống thì bước phân loại chạy như cũ — chỉ mất khả năng gỡ mơ hồ cho
    những câu tắt/dừng nói trống không.

    `pending` (B3): pending đang mở, nếu có (khớp `handlers.action_flow.Pending`
    — chỉ cần có `.slot`/`.intent`/`.known`/`.question`/`.kind`). CHỈ có tác
    dụng khi `pending.kind == "fill"` — hai loại pending TẤT ĐỊNH (`confirm`/
    `select`) không đi qua đây (T04/`pipeline/router.py` xử lý riêng bằng
    regex, ngân sách < 400ms, không phải việc của hàm này).

    ⚠️ Xem docs/tasks/reports/T05.md mục "Lệch với task file": tính tới lúc
    T05 hoàn thành, `pipeline/router.py::_try_fill_pending_slot` (T04, đã
    commit) CHƯA gọi `detect_with_params(..., pending=...)` — nó tự gọi thẳng
    `intent_local.classify()` khi có pending đang mở, khác hẳn B3. Tham số
    `pending` ở đây có mặt và được test đầy đủ ở tầng đơn vị, nhưng chưa được
    router nối vào cho tới khi có một task sau sửa `pipeline/router.py` (nằm
    ngoài "FILE BẠN ĐƯỢC SỬA" của T05).

    Trả về (intent_name, params_dict).
    """
    if not text.strip():
        return Intent.UNKNOWN, {}

    # B5 — cancel/repeat: tất định, không mạng ngoài, không SetFit, không
    # Gemini (ngân sách < 300ms, T21/G1). Chạy TRƯỚC cả pending lẫn SetFit:
    # một câu huỷ rõ ràng thì huỷ ngay, không cần biết đang có pending hay
    # không, và không tốn một lượt classify cục bộ vô ích.
    if _LOCAL_CANCEL_WORDS.search(text):
        logger.info("nhãn cục bộ (regex, không SetFit/Gemini): cancel")
        return "cancel", {}
    if _LOCAL_REPEAT_WORDS.search(text):
        logger.info("nhãn cục bộ (regex, không SetFit/Gemini): repeat")
        return "repeat", {}

    if state is None:
        # Nhập sau, không phải lúc import: `handlers` phụ thuộc ngược lại vào
        # `pipeline` (qua tts/phrases), nhập ở đầu file là vòng tròn.
        from handlers.action_flow import device_state

        state = device_state()

    if pending is not None and getattr(pending, "kind", "fill") == "fill":
        # B3 — có pending MỞ SLOT đang chờ: SetFit cục bộ KHÔNG ĐƯỢC GỌI. Nó
        # chưa từng được huấn luyện cho câu trả lời trần trụi ("Sơn Tùng",
        # "đúng rồi", "mẹ") — ép nó quyết một câu như vậy chính là nguồn bug
        # (T05-intent-slots.md mục 1, chỗ hỏng #1/#2). Đi thẳng Gemini kèm
        # khối hỏi-gì (`_pending_block`) để nó có ngữ cảnh mà một mình câu chữ
        # không có.
        logger.info(
            "pending mở slot=%s (%s) -> bỏ qua SetFit, hỏi Gemini kèm ngữ cảnh",
            pending.slot, pending.intent,
        )
        return _ask_gemini(_build_prompt(text, state, pending))

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

    return _ask_gemini(_build_prompt(text, state))


def detect(text: str) -> str:
    """Trả về nhãn intent tương thích ngược."""
    intent_val, _ = detect_with_params(text)
    return intent_val
