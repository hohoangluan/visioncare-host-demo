# Kiến trúc OCR cho SeeVia

Đọc chữ cho người khiếm thị qua kính ESP32-S3 + OV2640. Ba yêu cầu, theo thứ tự
khi phải đánh đổi: **đúng** (nhất là số) → **nhanh** (tới tiếng đầu tiên) →
**ít làm phiền** (người dùng không bị chỉ huy liên tục).

Chi tiết giao thức, cấu hình và firmware: `docs/superpowers/specs/2026-10-19-ocr-stream-guidance-design.md`.

---

## 1. Người dùng thật cần gì

Những điều nghiên cứu đã chỉ ra, và hệ quả cho thiết kế:

| Bằng chứng | Hệ quả |
|---|---|
| Đưa camera trúng chữ là khó khăn cốt lõi của mọi hệ thống camera cho người mù ([SKI, ASSETS 2014](https://www.ski.org/wp-content/uploads/2025/01/appliance_displays_-_assets_2014-1.pdf)) | Phải có hướng dẫn căn khung — nhưng chỉ khi thật cần |
| Hướng dẫn bằng lời **chen vào giọng đọc**; tín hiệu lặp lâu thì người dùng lờ đi ([Stearns et al., TACCESS 2016](https://ruofeidu.com/papers/Stearns_EvaluatingHapticAndAuditoryDirectionalGuidanceToAssistBlindPeopleInReadingPrintedTextUsingFinger-MountedCameras_TACCESS2016.pdf)) | Hướng dẫn chủ yếu bằng **tiếng bíp**, lời nói chỉ khi cần; không bao giờ chồng lên lúc đang đọc |
| Âm liên tục có cao độ chỉ hướng dùng được cho dò dòng chữ (cùng nghiên cứu) | Dùng nhịp/cao độ bíp để báo "đang tiến gần đúng" |
| Hướng dẫn khung hình dễ khó nghe, gây xao nhãng; nhận diện bằng máy hay sai khi thiếu sáng ([CSUN 2023](https://Ski.org/sites/default/files/publications/csun2023-interactivetrainingforblindnavigation_cameraready_v2.full__0.pdf)) | Có trần thời gian, hết giờ thì **đọc thử** chứ không bắt căn mãi |
| Chế độ "Short Text" của Seeing AI — đọc ngay bất kỳ chữ nào trong khung, giao diện tối giản — là cách người mù hay dùng để tìm chữ ([Neat et al. 2019](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC6824725/)) | Cần một chế độ **đọc nhanh không hướng dẫn** bên cạnh chế độ đọc kỹ |
| Đọc màn hình thiết bị (máy giặt, điều hoà, lò vi sóng) là nhu cầu riêng, khó ([SKI, ASSETS 2014](https://www.ski.org/wp-content/uploads/2025/01/appliance_displays_-_assets_2014-1.pdf)) | Thêm tác vụ màn hình LED/LCD; PP-OCRv6 có hỗ trợ chữ số LED 7 đoạn |

Những thứ người khiếm thị ở Việt Nam hay cần đọc. Danh sách này là giả định của
người thiết kế, cần xác nhận lại qua phỏng vấn ở P0:

- hạn sử dụng (NSX/HSD) trên bao bì,
- tên thuốc, liều dùng,
- tên sản phẩm,
- tiền,
- hoá đơn, giấy báo điện nước,
- giấy tờ, thư từ,
- biển hiệu, số phòng, nút thang máy,
- màn hình thiết bị gia dụng.

Từ đó ra **6 yêu cầu thiết kế**:

1. **Mặc định là nhanh.** Câu "đọc chữ" phải ra tiếng trong vài giây, không bắt căn khung trước.
2. **Đọc thứ quan trọng nhất trước.** Tên sản phẩm trước thành phần, tổng tiền trước từng món, HSD trước mọi thứ khác.
3. **Không bao giờ bịa số.** Thà nói "không đọc chắc" còn hơn đọc sai liều thuốc hay mệnh giá.
4. **Nói thật về giới hạn.** Chữ quá nhỏ so với camera thì nói thẳng, không lặp "lại gần" vô hạn.
5. **Rảnh tay, ngắt được.** Một tay cầm đồ, tay kia cầm gậy, nên mọi thao tác đều bằng giọng nói, và nói chen vào là dừng được ngay.
6. **Riêng tư.** Giấy tờ tuỳ thân, đơn thuốc, hoá đơn không lưu lại.

---

## 2. Ba chế độ

| Chế độ | Kích hoạt | Làm gì | Tiếng đầu tiên |
|---|---|---|---|
| **Đọc nhanh** (mặc định) | "đọc chữ", "cái này ghi gì" | Chụp 1 ảnh full-res ngay, đọc chữ **to nhất trước**, chỉ đọc dòng tin được | ≤ 2s |
| **Đọc kỹ** | "đọc kỹ", "đọc hết", hoặc tự gợi ý khi đọc nhanh thấy nhiều chữ nhỏ | Stream 640 + hướng dẫn căn khung + tự chụp burst | bíp đầu ≤ 0,3s; nội dung ≤ 2s sau khi chụp |
| **Hỏi về chữ** | "hạn sử dụng khi nào", "tổng bao nhiêu tiền", "thuốc này uống sao" | Như đọc nhanh, rồi trả lời đúng câu hỏi thay vì đọc toàn bộ | ≤ 3s |

Đọc nhanh tự chuyển sang đọc kỹ chỉ bằng **một câu gợi ý ở cuối**, không hỏi
lại: *"Còn nhiều chữ nhỏ, nói 'đọc kỹ' để tôi hướng dẫn."*

---

## 3. Sơ đồ

```
                         ┌───────────── /process (đã có) ─────────────┐
 Kính: mic + 1 ảnh UXGA ─▶│ STT → intent=ocr → chọn chế độ từ câu lệnh │
                         └───────┬───────────────────────┬────────────┘
                     đọc nhanh / hỏi                  đọc kỹ
                                 │                       │
                                 │            WebSocket /ws/ocr/{id}
                                 │            stream VGA ↔ mã hướng dẫn
                                 │            frame_metrics → guidance
                                 │            → lệnh chụp burst 3×UXGA
                                 ▼                       ▼
                    ┌────────────────── reader (GPU local) ──────────────────┐
                    │ chọn frame nét nhất → xoay → PP-OCRv6 det+rec          │
                    │ → dòng {text, box, conf, line_px} → thứ tự đọc          │
                    └───────────────┬────────────────────────────────────────┘
                                    ▼
                    ┌──────────── answer (2 đường song song) ────────────────┐
                    │ ĐƯỜNG NHANH: luật tiếng Việt (regex HSD/NSX, tiền, mg, │
                    │   số phòng) + dòng to nhất → câu đầu tiên ngay          │
                    │ ĐƯỜNG KỸ: Gemma 4 26B-A4B (ảnh + dòng OCR + câu hỏi)    │
                    │   → JSON → verify số → formatter → câu tiếp theo        │
                    └───────────────┬────────────────────────────────────────┘
                                    ▼
                         TTS hiện có (stream) → kính
```

---

## 4. Nhanh: ngân sách độ trễ

Mục tiêu đo từ lúc người dùng **nói xong** tới **tiếng đầu tiên có nội dung**.
Câu chào ("đã nhận") hiện có không tính.

| Chặng | Đọc nhanh | Cách giữ trong ngân sách |
|---|---|---|
| STT + intent | ~0,1s | đã có: Zipformer local + SetFit local |
| Decode + xoay + det/rec PP-OCRv6 | ≤ 0,6s | GPU, model nạp sẵn lúc khởi động (warm như `vlm.warm()`) |
| Câu đầu từ đường nhanh | ~0s | luật thuần Python, không gọi model |
| TTS câu đầu | ~0,5–1s | stream sẵn có; câu cố định đã dựng sẵn trong `phrases.py` |
| **Tổng tới tiếng đầu** | **≤ 2s** | |
| Gemma (chạy song song, không chặn câu đầu) | 1–3s | câu từ Gemma nối vào sau câu đầu |

Bốn quyết định làm nên tốc độ:

1. **Không có model lớn trên đường tới câu đầu.** Câu đầu luôn đến từ OCR + luật.
   Gemma chỉ bổ sung phía sau.
2. **Đọc nguyên văn không gọi Gemma.**
3. **Vòng hướng dẫn chỉ chạy det tiny trên 640px** (vài ms/frame). Âm thanh hướng
   dẫn nằm sẵn trong flash kính, không qua TTS.
4. **Kiểm soát luồng bằng credit.** Server không bao giờ xử lý frame cũ, nên độ
   trễ không tích tụ.

---

## 5. Chính xác: 5 lớp

| Lớp | Chống lỗi gì | Cơ chế |
|---|---|---|
| 1. Đủ pixel | mất dấu, sai chữ nhỏ | ngưỡng `line_px` trên ảnh full-res; đọc kỹ chỉ chụp khi đạt |
| 2. Ảnh tốt nhất | mờ do rung đầu | burst 3 tấm, chọn theo độ nét **trong vùng chữ** |
| 3. Chỉ đọc dòng tin được | đọc rác | `conf` của rec; dòng thấp bị bỏ, kèm câu "còn vài chữ không đọc được" |
| 4. Sửa dấu có ràng buộc | OCR đúng chữ cái, sai dấu | Gemma chỉ được **đổi dấu**: sau khi bỏ dấu, chuỗi sửa phải trùng chuỗi gốc từng ký tự, không trùng thì giữ bản OCR |
| 5. Chặn số bịa | sai tiền, liều, ngày | mọi số trong câu trả lời phải có trong text OCR (đã chuẩn hoá `.`/`đ`/`O→0`/`l→1`); không có thì nói "không đọc chắc" |

Lớp 4 và 5 kiểm tra được bằng code, nên không phụ thuộc việc model có nghe
lời prompt hay không.

**Đường nhanh dùng luật tiếng Việt.** Luật nhận diện chính xác, nên câu đầu
đúng ngay cả khi Gemma chậm hoặc lỗi:

| Mẫu | Ví dụ | Câu đọc |
|---|---|---|
| HSD/NSX + ngày | `HSD: 12/05/2027`, `EXP 05.2027` | "Hạn sử dụng 12 tháng 5 năm 2027, còn 7 tháng." |
| Tiền | `125.000đ`, `TỔNG CỘNG 1.250.000` | "Tổng cộng một triệu hai trăm năm mươi nghìn đồng." |
| Hàm lượng | `500mg`, `5ml` | "500 mi-li-gam." |
| Mệnh giá tiền | đã có `read_money` | giữ nguyên |

Với hoá đơn, số đứng sau từ khoá "Tổng cộng", "Thành tiền" được ưu tiên hơn số
lớn nhất. Đây là lỗi kinh điển: số lớn nhất thường là tiền khách đưa.

---

## 6. Ít làm phiền: tương tác

**Hướng dẫn căn khung (chỉ ở chế độ đọc kỹ)**

- Lớp âm thanh chính là **bíp**:
  - bíp đầu tiên báo "đã thấy chữ",
  - nhịp bíp nhanh dần khi chữ to dần tới ngưỡng,
  - tiếng chụp khi đạt.
  Người dùng không cần hiểu câu nào để làm đúng.
- **Lời nói chỉ khi bíp không đủ:** cắt mép ("nhìn sang trái"), chói, tối,
  "chữ quá nhỏ so với camera". Mỗi lần một câu, cách nhau ≥ 1,5s, vấn đề phải
  lặp lại 3 frame mới được nói.
- **Không bảo xoay giấy.** Xoay và nghiêng nhẹ do server tự sửa.
- **Trần 30 giây.** Hết giờ thì đọc thử ảnh tốt nhất đang có. Không có phiên
  nào kết thúc mà không đọc gì.

**Khi đọc**

- **Đọc to nhất trước.** Sắp các dòng theo chiều cao chữ trước, rồi mới theo vị
  trí. Đó thường là tên sản phẩm, tiêu đề, tên biển.
- **Văn bản dài: tóm tắt trước** 1–2 câu, kèm "Nói 'đọc hết' để nghe toàn bộ."
- **Lệnh giọng nói:** "đọc lại", "đọc tiếp", "đọc hết", "dừng", "chữ đầu tiên
  là gì". Kết quả OCR gần nhất được giữ 5 phút để hỏi tiếp mà không phải chụp
  lại.
- **Ngắt lời:** nút bấm hoặc lệnh mới huỷ luồng TTS đang phát (cần firmware hỗ trợ).
- **Nói rõ mức chắc chắn**, không dùng phần trăm: "Hạn sử dụng 12/05/2027" so
  với "Hạn sử dụng có vẻ là tháng 5 năm 2027, chữ hơi mờ."

---

## 7. Thành phần

| Thành phần | Chọn | Ghi chú |
|---|---|---|
| Phát hiện chữ khi preview | PP-OCRv6 tiny | GPU local, 640×480 |
| Det + rec ảnh full-res | PP-OCRv6 medium (đọc kỹ) / small (đọc nhanh) | small hay medium cho đọc nhanh: chọn theo số đo độ trễ |
| Xoay / nắn / hướng dòng | bộ đi kèm PaddleOCR 3.x | |
| Rec dự phòng | VietOCR trên crop dòng | chỉ nếu PP-OCRv6 thua trên bộ test tiếng Việt |
| Hiểu tài liệu, sửa dấu | Gemma 4 26B-A4B | endpoint có sẵn (LAN, UIT dự phòng) — `docs/LLM_PROVIDER.md` |
| So sánh | Gemini hiện tại | giữ làm baseline tới khi đo xong |
| STT, intent, TTS | giữ nguyên | |

Module mới (`pipeline/ocr_session.py`, `frame_metrics.py`, `guidance.py`,
`models/ocr/engine.py`, `reader.py`, `tasks/`, `rules_vi.py`, `verify.py`,
`models/llm/client.py`) được mô tả trong spec.

---

## 8. Giới hạn phải nói thẳng

- **Lens OV2640 120° là nút thắt.** Theo ước lượng hình học, chữ 10pt cần cầm
  cách kính khoảng 10cm, và ở đó lens có thể mất nét. Thiết kế này chạy tốt với
  chữ to (biển hiệu, tên sản phẩm, HSD in đậm, tiền, màn hình LED), và chỉ
  "đọc thử" với chữ nhỏ.
- **Phần mềm không vượt được giới hạn quang học.** Đổi sang OV5640 có lấy nét
  tự động, góc khoảng 70°, là cải thiện lớn nhất có thể làm. Kiến trúc không
  phải sửa, chỉ đổi số hiệu chuẩn.
- **Mọi con số trong tài liệu này** (≤ 2s, 28px, 1,5s…) **là mục tiêu, chưa đo.**

---

## 9. Đo thế nào là thành công

| Chỉ số | Mục tiêu | Đo ở đâu |
|---|---|---|
| Tới tiếng đầu tiên (đọc nhanh) | p50 ≤ 2s, p90 ≤ 3s | log `/process` |
| Số bịa lọt qua | **0** | bộ test `data/ocr_eval/` |
| Đúng HSD / tổng tiền / liều | ≥ baseline Gemini, đếm theo từng câu bất đồng | bộ test |
| CER có dấu và bỏ dấu | thấp hơn baseline | bộ test |
| Đọc kỹ: thời gian tới lúc chụp | p50 ≤ 10s | log phiên |
| Đọc kỹ: số câu hướng dẫn mỗi phiên | ≤ 4 | log phiên |
| Người dùng hoàn thành tác vụ (đọc được HSD hộp sữa, tổng hoá đơn, tên thuốc) | ≥ 80% không cần trợ giúp | thử với người khiếm thị thật |

Thứ tự triển khai:

1. **P0:** hiệu chuẩn lens, bộ test, phỏng vấn 3–5 người dùng về thứ họ cần đọc.
2. **P1:** đọc nhanh + hỏi về chữ. Chạy được ngay với firmware hiện tại, không cần stream.
3. **P2:** đọc kỹ với simulator webcam.
4. **P3:** firmware stream.

P1 mang lại phần lớn giá trị mà không cần đụng tới kính.
