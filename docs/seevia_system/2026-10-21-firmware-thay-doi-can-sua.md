# Firmware: những gì server đã đổi trong ngày 2026-10-21 và việc cần sửa

Nguồn sự thật đầy đủ vẫn là `docs/FIRMWARE_ENDPOINTS.md` (nhánh `chot-ai-2026-10-21` của `visioncare-host-demo`, worktree `vh-chot`).
File này chỉ liệt kê **phần khác so với đầu ngày** (mốc `00ad021`), cái gì bắt buộc sửa ở kính, cái gì tuỳ chọn, cái gì KHÔNG phải sửa.
Mọi khung, mã, con số bên dưới đã có trong `FIRMWARE_ENDPOINTS.md`; số mục trong ngoặc là mục của file đó.

## 0. Tóm tắt một dòng

| Việc | Bắt buộc? |
|---|---|
| A. Đọc tiền: phiên `live:"ocr"` mới, `cues` rỗng, kính phải vào chế độ gửi VGA ngay sau `reply_end` | **Có** (nếu chưa xử lý `live:"ocr"` mà không có cue) |
| B. Token riêng từng kính trong NVS | **Có**, nếu muốn gọi/nhắn/khẩn cấp |
| C. Khẩn cấp: nhận `call_state ringing_out` ngay sau `hello_ok` khi nối lại | **Có** |
| D. Tin nhắn chưa đọc có thể tới ngay sau kết nối | Kiểm tra, thường đã xử lý |
| E. Các câu báo vào/ra chế độ mới | Không (đi qua audio `0x02` sẵn có) |
| F. Cảnh báo vật cản, VQA `ask`, OCR cảnh báo chữ số | **Không đổi** giao thức |
| G. Lỗi đã biết phía kính: rớt chữ đầu khi nói sớm | Nên xử lý, xem mục 7 |

## 1. A — Đọc tiền v2 (mục 6 của FIRMWARE_ENDPOINTS)

Bản đầu ngày: đọc tiền chạy "y như chat", không live. Bản mới có HAI nhánh tuỳ độ chắc của server:

```
-- chắc (~49 % lượt): y như chat, không live --
kính   turn_start ; 0x01 <JPEG UXGA buffer> ; 0x03 <ADPCM>... ; turn_end
server reply{live:null, cues:[]} ; 0x02... ("50 nghìn đồng.") ; reply_end

-- không chắc (~50 %): một câu hướng dẫn, rồi đọc lại đúng MỘT lần --
server reply{live:"ocr", cues:[]} ; 0x02... (một trong ba câu hướng dẫn) ; reply_end ; {"t":"cam","size":"vga","fps":5,"quality":12}
kính   0x04 <VGA>...
server 0x02... ("50 nghìn đồng." | "Tôi vẫn chưa đọc chắc được tờ này.") ; {"t":"end"}
```

Ba câu hướng dẫn (lời nói, không phải cue): "Lùi ra xa một chút, để cả tờ tiền nằm giữa." / "Giữ yên tay." / "Đưa tờ tiền lại gần hơn một chút."

Firmware cần đảm bảo:
1. `reply` có `live:"ocr"` mà `cues` là **mảng rỗng** vẫn được coi là vào phiên live OCR (trước giờ luôn kèm cue `ocr_start`). Nếu code hiện tại chỉ vào chế độ live khi có cue thì sửa thành dựa vào `live`.
2. Sau `reply_end` của lượt đó, nhận `cam` và bắt đầu gửi `0x04` VGA 5 fps. Server **bỏ 1,0 s khung đầu** (`MONEY_RETRY_SETTLE_S`), lấy khung đầu đủ nét sau đó, hết **3,0 s** (`MONEY_RETRY_TIMEOUT_S`) thì dùng khung nét nhất. Không có `capture uxga` và không có cue căn khung trong nhánh này.
3. Nhận `{"t":"end"}` thì dừng stream, về IDLE. Đây là lần đọc lại duy nhất; không lặp.
4. Lượt mới (`turn_start`), đóng socket: huỷ phiên như OCR live hiện có.
5. Đang chỉ đường (nav live): phiên đọc tiền tạm thay nav, xong server tự dựng lại nav (kính nhận lại `cam` qvga 8 fps như lúc bật cảnh báo). Firmware phải chấp nhận `cam` mới đổi chế độ giữa chừng, không giả định nav chỉ bật một lần.

Chưa có thay đổi nào cần ở phần cứng camera: vẫn dùng `cam`/`capture` hiện có.

## 2. B — Token riêng cho từng kính (mục 2, 16)

- Có hai loại token. **Token dùng chung**: `device` do kính tự khai, chỉ đủ cho lượt lệnh và live. **Token riêng**: ràng buộc với `device_id`, **bắt buộc** cho gọi điện, nhắn tin, khẩn cấp (thiếu thì server từ chối với câu "Kính cần token riêng").
- Cấp: `python tools/device_token.py add <device_id>` (in đúng một lần; server chỉ giữ sha256). Nạp vào NVS của kính đó.
- Gửi: trường `token` trong `hello`, hoặc `Authorization: Bearer <token>` / `X-Device-Token`. Thiếu hoặc sai: HTTP 401, WS đóng 4401. Server chưa cấu hình: 503 / 4401.
- Với kính demo hiện tại (`glasses-123`) chưa có token riêng, nên gọi/nhắn đang bị chặn; cần cấp một token và nạp vào kính để demo gọi/nhắn.

## 3. C — Khẩn cấp và nối lại phiên (mục 16.2)

Thay đổi hành vi server:
- Socket rớt khi chuỗi khẩn cấp đang `ringing_out`: server **không cúp**, vẫn gọi người thân kế tiếp. Các cuộc gọi thường vẫn bị cúp như cũ.
- Kính mở lại phiên thì ngay sau `hello_ok` nhận `call_state` `ringing_out` (kèm `call` id) dù chưa bấm gì. Firmware phải vào thẳng trạng thái gọi đi từ khung này, **không giả định IDLE** sau `hello_ok`.
- Bấm nút lúc đó = `call_hangup`, dừng cả chuỗi. Chỉ lý do `glasses_hangup` và `timeout` mới dừng chuỗi.
- Chuỗi đã `active` mà rớt socket thì cúp như cuộc thường.
- Câu cấp cứu chỉ gọi **người thân**, không bao giờ quay số từ câu nói (đã bỏ trích số 115/114/113). Firmware không được tự quay 115.

## 4. D — Tin nhắn tới ngay sau kết nối (mục 16.3)

Với token riêng, vừa vào phiên server tự lấy tin chưa đọc từ app server và xếp hàng như tin vừa tới. Kính có thể nhận `reply result-*` ngay sau `hello_ok` dù chưa bấm nút. Phần "reply result-*" đã có từ trước (mục 4.1); chỉ cần chắc rằng nhận nó khi IDLE ngay sau kết nối là hợp lệ và phát âm bình thường.

## 5. E — Câu báo vào/ra chế độ (mới, không cần đổi firmware)

Các chế độ live chỉ có hai: cảnh báo vật cản (`nav`) và đọc chữ (`ocr`, gồm đọc tiền lần 2).

| Sự kiện | Cách phát | Ghi chú |
|---|---|---|
| Bật cảnh báo / tắt cảnh báo | Cue `nav_alert_on` "Đã bật cảnh báo." / `nav_alert_off` "Đã tắt cảnh báo." | Đã có trong flash, không đổi |
| Vào đọc chữ | Cue `ocr_start` "Đưa sách ra trước mặt." | Không đổi |
| Cảnh báo bị đọc chữ tạm chiếm | Lời nói qua `0x02`: "Tạm tắt cảnh báo." | **Mới** |
| Cảnh báo dựng lại sau đọc chữ / sau cúp máy | "Bật lại cảnh báo." | **Mới** |
| Thoát đọc chữ | "Thoát đọc chữ." | **Mới** |
| Thoát đọc tiền lần 2 | "Thoát đọc tiền." | **Mới** |

Tất cả câu **mới** là lời nói thường qua `reply`/audio `0x02`, **không phải cue**, nên firmware không cần đổi gì. Chúng ngắn có chủ đích (2–4 từ) vì người dùng chê nói nhiều.
Nếu bên firmware muốn đưa chúng thành cue trong flash cho nhanh hơn: thêm clip vào bảng `pipeline/cues.py`, sinh lại bằng `tools/make_cue_clips.py`, **tăng `CUE_VERSION` (hiện 2)** và nạp clip. Việc này ngoài phạm vi hiện tại; làm hay không do bên firmware quyết.

**Thứ tự khung (đã cài, commit `6e591a5`, đã gộp vào `vh-chot`):**
- Đọc chữ/đọc tiền tự kết thúc: audio nội dung → audio "Thoát đọc chữ." / "Thoát đọc tiền." → khung `{"t":"end"}`. Firmware chỉ về IDLE khi nhận `end`, nên câu thoát luôn nằm trước `end`.
- Hết trần mà không có ảnh nào: chỉ nói "Thoát đọc chữ.", **không gửi `end`** (giữ đúng giao thức cũ). Firmware cần tự có timeout thoát chế độ live khi không nhận `end`, như trước đây.
- Không nói câu thoát khi người dùng huỷ bằng lượt mới, khi kính ngắt kết nối, hoặc khi phiên bị thay.
- Cảnh báo bị đọc chữ chiếm: nói "Tạm tắt cảnh báo." **trước** câu đọc chữ. Dựng lại sau đó: nói "Bật lại cảnh báo." và kính nhận lại `cam` qvga 8 fps. Lượt mới huỷ OCR vẫn dựng lại cảnh báo và vẫn nói "Bật lại cảnh báo." (chỉ câu thoát đọc chữ là im).
- Người dùng nói "tắt cảnh báo" lúc cảnh báo đang bị tạm dừng: sau khi đọc chữ xong **không** tự bật lại, và không có câu "Bật lại cảnh báo.".

## 6. F — Không đổi giao thức

- **Cảnh báo vật cản** (`hazard`): khung `{"t":"hazard","level","dir","kind"}` và `cam` qvga 8 fps/quality 15 giữ nguyên. Có thêm logic mới `HAZARD_LOGIC=predict` (dự đoán quỹ đạo), **mặc định vẫn `area`** (logic cũ) nên hành vi không đổi. Nếu sau này cài model mới (`ft_11s_last`), giá trị `kind` có thể mang tên lớp mới ngoài COCO (vd `pole`, `warning_column`); firmware chỉ nên dùng `level` và `dir` để phát cue, đừng ánh xạ `kind` cứng.
- **Hỏi về ảnh** (intent mới `ask`): chỉ ở server; kính vẫn gửi `turn_start` + `0x01` JPEG + audio như lượt hỏi/tả cảnh.
- **OCR cảnh báo chữ số chưa chắc**: thêm một câu vào cuối lời đọc ("Có con số tôi đọc chưa chắc, bạn đưa lại gần để tôi đọc lại."), cùng audio `0x02`.
- **Cue clips**: `cue_version` vẫn **2**; số clip trong tài liệu ghi 31 (sửa so với 32 cũ). Không có clip mới.
- **Trang giám sát** (`WS /v2/observe`, mục 15): chỉ cho công cụ demo, kính thật không dùng và không cần xử lý. `hello.debug` vẫn như cũ.

## 7. G — Lỗi đã biết phía kính/thu âm cần xem

1. **Rớt chữ đầu câu khi nói ngay sau bấm nút** (đo ~0,6–1,0 s sau bấm: "Tắt cảnh báo" nghe thành "Cảnh báo"). Đã loại trừ VAD của server làm cắt đầu; còn khả năng nằm ở thời điểm kính bắt đầu gửi `0x03` sau khi bấm (khởi động mic, pre-roll). Đề nghị: kính giữ **pre-roll 200–300 ms** audio trước lúc bấm hoặc gửi `0x03` từ ngay lúc `turn_start`, rồi đo lại bằng `demo-web/e2e/stt_ab.py`. Chưa chứng minh đây là nguyên nhân; cần thử trên kính thật.
2. **Chạy full tour chạm kính thật**: client giả lập `client.html` dùng mã `glasses-123`, sẽ thay phiên kính thật nếu đang nối (đóng `4000`). Khi test chung, báo trước để tránh đá nhau.
3. **Âm thanh thật chưa kiểm**: các bài e2e chạy headless, chỉ kiểm khung `0x02` và độ trễ; chưa nghe loa. Cần nghe thật khi nạp bản firmware mới.

## 8. Cách kiểm sau khi sửa

- Đọc tiền: dùng ảnh tờ tiền bị lệch mép để ép nhánh "không chắc" và xem kính vào stream VGA, rồi thoát khi nhận `end`. Server có nhật ký ở `storage/server.log`.
- Khẩn cấp nối lại: bấm "cấp cứu", rút mạng kính khi `ringing_out`, nối lại và xem có vào lại trạng thái gọi đi không.
- Bộ test phía server chạy ở `vh-chot` (`pytest -q`, ghi nhận 707 pass, 2 skip).
- Kính giả lập: `demo-web/client.html` (qua `demo-web/serve.py`), tham chiếu chuỗi khung.

## 9. Việc chưa chốt phía server liên quan kính

- Gọi/nhắn chỉ chạy được khi kính có token riêng, tài khoản chủ kính và người thân (ví dụ "em iu") đã gắn trên app server. Chưa chạy lại full tour pha G/H sau khi mở khoá.
- Đặt xe, dẫn đường, phát nhạc đã chạy một phần; lỗi nằm ở app/điện thoại hoặc STT, không phải giao thức kính.
