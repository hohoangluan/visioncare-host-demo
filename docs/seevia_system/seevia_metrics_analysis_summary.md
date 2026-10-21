# Tóm tắt phân tích kết quả metric SeeVia (run 18/10/2026)

Nguồn: `results.csv` (22.838 dòng dữ liệu) và `METRICS_VA_THU_NGHIEM_GIA_LAP.md`.
Mục tiêu dự án: latency < 1 s; accuracy, precision, recall không được quá thấp.

## 1. Kết luận chính

Chưa có kết luận nào về latency < 1 s hay về accuracy, precision, recall của hệ thống.
Gần như toàn bộ kết quả đo phần hạ tầng (codec, streaming, quality gate, backend).
STT, intent, Gemini và TTS đều được giả lập.

## 2. Đã đo và chưa đo

| Nhóm | Trạng thái | Ý nghĩa |
|---|---|---|
| Codec ADPCM/PCM | Đo thật (tone tổng hợp) | Chỉ đúng cho fixture |
| Quality gate ảnh | Đo thật, 930/930 đúng kỳ vọng | Chỉ ảnh tổng hợp |
| HTTP stream (1.620 request) | Socket và codec thật, AI giả | Không suy ra latency AI |
| Backend + PostgreSQL | Thật, delivery/report giả | Không gồm FCM, Android |
| WER/CER, intent P/R/F1, vision accuracy, Gemini TTFT, TTS thật, T_first_useful nghe thật, underrun phần cứng, T_action | `not_measured` (10 mục) | Thiếu model, API key, dataset, thiết bị |

Mock dùng trong phép HTTP: STT 20 ms, intent 10 ms, handler 30 ms, TTS 4×5 ms, ack 0,5 s, nghỉ 0,45 s, câu trả lời 1 s.

## 3. Phát hiện chính

### 3.1 Latency
- `simulated_useful_playback_s` p50 nằm trong 0,955–1,31 s. Giá trị này bị ack + nghỉ của fixture (0,95 s) chi phối.
- Nội dung hữu ích sẵn sàng sau 0,09–0,36 s nên compute giả bị ack che hoàn toàn.
- Với model thật: `T_first_useful ≈ max(ack + nghỉ, thời điểm câu đầu sẵn sàng)`. Cần đo STT, intent, Gemini TTFT, TTS câu đầu có kịp trong khoảng 0,95 s hay không.
- Preroll 2 s chỉ thêm khoảng 0,1 s (ADPCM WAV: 0,966 → 1,098 s; PCM stream: 0,955 → 1,056 s), vì preroll tính theo nội dung audio, không phải đồng hồ.

### 3.2 Streaming và codec
- ADPCM giảm payload khoảng 3,9 lần (15.872 so với 62.400 byte).
- Với đầu vào PCM WAV, `eof_s` p50 từ concurrency 1 lên 5: PCM stream 0,105 → 0,111 s; ADPCM WAV 0,122 → 0,261 s. Với đầu vào ADPCM: 0,149 → 0,407 s (2,7 lần). Mã hoá ADPCM chịu tranh chấp CPU.
- Encode ADPCM tuyến tính, khoảng 10 ms mỗi giây audio (RTF ≈ 0,01).
- Decode ADPCM có chi phí cố định khoảng 19 ms mỗi lần gọi, cần profile.
- Waveform correlation 0,9996–0,9999 (ADPCM), 1,000 (PCM), chỉ trên tone.
- Với ADPCM WAV, `first_body_byte_s` (~5 ms) chỉ là header 60 byte. Nên báo `first_decodable_audio_s` (16–360 ms).

### 3.3 Quality gate ảnh
- 5,5–7,7 ms ở 640×480; 37–51 ms ở 1600×1200 (tỉ lệ theo số pixel, đo ở độ phân giải gốc).
- Ảnh tối, sáng, phẳng bị từ chối đúng thông báo; ảnh hỏng được pass-through.
- False accept/reject trên ảnh thật chưa biết.

### 3.4 Backend (concurrency 1 / 2 / 5)
| Chỉ số | c = 1 | c = 2 | c = 5 |
|---|---:|---:|---:|
| Accept p50 / p95 (ms) | 27,0 / 28,8 | 32,4 / 37,6 | 63,2 / 69,9 |
| Vòng accept → delivery giả → report → status p50 / p95 (ms) | 139,5 / 151,1 | 203,5 / 210,6 | 407,8 / 413,7 |

- Tăng gần tuyến tính theo concurrency, các bước gần như tuần tự. Nghi ngờ do NullPool trong engine test (giả thuyết chưa kiểm chứng).
- `delivery_batch_s` chỉ có n = 30, 15, 6; với n = 6 thì p95/p99 không có ý nghĩa.
- Phần chiếm thời gian lớn nhất (FCM, Android, callback thực) chưa đo.

## 4. Lỗi và test thất bại

| Mục | Kết quả | Ghi chú |
|---|---|---|
| Router bypass | 4/4 probe fail | "Tăng âm lượng", "đọc chữ" bị biến thành `music_stop`/`nav_stop` khi đang phát nhạc/dẫn đường. Lỗi logic thật, ảnh hưởng recall |
| ADPCM vs FFmpeg bit-exact | 1 fail | Chênh 2–4 LSB trên biên độ ~6000 (<0,1%); không tích luỹ qua block 505 mẫu. Khả năng cao khác cách làm tròn (giả thuyết). Cần đối chiếu decoder trên kính |
| FFmpeg → source | 1 fail | FFmpeg 4.2.7 không hỗ trợ `-block_size 256`; lỗi môi trường |
| OpenAPI artifacts | 1 fail | `parents[3]` trỏ ra `SeeVia_system/contracts`; hai artifact còn khác output sinh lại |
| Voice suite | 374 pass, 2 fail, 15 skip | 15 skip do thiếu `GEMINI_API_KEY` |
| Backend suite | 370 pass, 1 fail | Gồm 84 integration test pass trên PostgreSQL thật |

## 5. Lưu ý khi đọc số

- Mock xác định nên độ phân tán rất nhỏ; không dùng p95/p99 này làm kỳ vọng production.
- `passed` ở phép HTTP chỉ nghĩa là HTTP 200 và waveform đúng fixture.
- `underrun = 0` và `stall = 0` là kết quả của mô hình playback với TTS giả rất nhanh, không phải bằng chứng phần cứng.
- n = 30 mỗi cấu hình: p99 gần như là giá trị lớn nhất.

## 6. Việc nên làm tiếp (theo ưu tiên)

1. Đo latency thật: STT thật + Gemini key; đo STT, intent, Gemini TTFT, TTS câu đầu. Báo riêng intent xử lý local (stop, volume, gọi điện) và intent qua Gemini (ocr, space, chat).
2. Quét ngưỡng intent trên `eval.jsonl`: so 0,50/0,15 với 0,80/0,50; ghi coverage, selective accuracy, per-class precision/recall, tỉ lệ fallback Gemini.
3. Sửa router bypass và đo chi phí chạy STT trước khi quyết định stop.
4. Xác nhận decoder ADPCM trên kính; nâng FFmpeg lên bản hỗ trợ `-block_size`.
5. Chạy lại backend với connection pool; đo FCM/Android trên điện thoại thật để có T_action.
