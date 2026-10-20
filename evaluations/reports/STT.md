# C6 — STT Zipformer-vi 30M (VIVOS test)

Nguồn: `results/stt_vivos/20261020-2045_full.json` (chạy 2026-10-20T20:45:29, VH `ece963b`, host gpu156).

## Dữ liệu và cách chấm

- Tập: VIVOS test (Luong & Vu, 2016; AILAB VNU-HCM), 760/760 câu, 19 người nói, tổng 44.8 phút audio.
- Đường chạy: `pipeline.stt.transcribe(wav_bytes)` của VH (cả giải WAV + `_normalize` như production). **CPU (sherpa-onnx OfflineRecognizer, như production)**, 2 luồng, giải mã `modified_beam_search` (beam 4 đường, hotword lệnh bật điểm 2.0; hotword tên người thân: không đặt).
- Chuẩn hoá chấm: `tools.bench_stt_compare.normalize` của VH (NFC, chữ thường, bỏ dấu câu). WER/CER gộp toàn tập (tổng lỗi / tổng từ), CI 95 % bootstrap 1.000 lần theo câu. Thư viện `jiwer`.
- Tải CPU máy lúc đầu 11.0 / cuối 11.0 (máy dùng chung — trễ có thể nhiễu).

## Kết quả

| Chỉ số | Giá trị [CI 95 %] |
|---|---|
| **WER** | **4.58 % [3.99; 5.18]** |
| CER | 2.18 % [1.83; 2.53] |
| WER người nói **tệ nhất** (VIVOSDEV10, 40 câu) | 17.6 % [12.3; 23.6] |
| WER người nói tốt nhất (VIVOSDEV15, 40 câu) | 1.7 % [0.6; 3.0] |
| Số câu hypothesis rỗng | 0 |
| (tham chiếu) WER giải mã `greedy_search`, cùng tập | 4.60 % [4.01; 5.19] |

Người nói theo WER giảm dần (mỗi người ~40 câu → CI rộng, đừng đọc chênh vài điểm):

| Người nói | Số câu | WER [CI] |
|---|---|---|
| VIVOSDEV10 | 40 | 17.6 % [12.3; 23.6] |
| VIVOSDEV04 | 40 | 10.3 % [6.1; 14.8] |
| VIVOSDEV02 | 40 | 9.3 % [5.6; 13.6] |
| VIVOSDEV09 | 40 | 6.3 % [3.7; 9.4] |
| VIVOSDEV01 | 40 | 5.6 % [2.7; 8.6] |
| VIVOSDEV18 | 40 | 5.3 % [3.2; 7.5] |
| VIVOSDEV07 | 40 | 5.0 % [2.6; 7.5] |
| VIVOSDEV08 | 40 | 3.7 % [1.4; 5.9] |
| VIVOSDEV14 | 40 | 3.4 % [1.8; 5.3] |
| VIVOSDEV11 | 40 | 3.2 % [1.2; 5.9] |
| VIVOSDEV05 | 40 | 3.1 % [1.1; 5.9] |
| VIVOSDEV17 | 40 | 3.0 % [1.5; 4.8] |
| VIVOSDEV03 | 40 | 2.9 % [1.2; 5.6] |
| VIVOSDEV13 | 40 | 2.8 % [0.8; 5.6] |
| VIVOSDEV06 | 40 | 2.7 % [0.9; 4.8] |
| VIVOSDEV19 | 40 | 2.3 % [1.0; 3.8] |
| VIVOSDEV16 | 40 | 2.2 % [1.0; 3.6] |
| VIVOSDEV12 | 40 | 1.8 % [0.3; 3.7] |
| VIVOSDEV15 | 40 | 1.7 % [0.6; 3.0] |

## Độ trễ

Mỗi câu (`transcribe`, CPU, n=760): **p50 128.78 ms / p90 176.7 ms / p99 234.02 ms** (mean 132.18, max 277.5).
RTF: median 0.037, p90 0.041, gộp (tổng thời gian / tổng audio) 0.037.
Lưu ý: câu VIVOS dài hơn câu lệnh kính (VIVOS trung bình 3.5 s/câu; config.py đo lệnh ~1-2 s) nên trễ tuyệt đối cao hơn trễ thật; dùng RTF để so.

## Baseline công bố (chép từ bài gốc, đã mở PDF arXiv 2406.02555)

Le, Nguyen & Nguyen (VinAI), *PhoWhisper: Automatic Speech Recognition for Vietnamese*, ICLR 2024 Tiny Papers — **Table 2 (trang 2), WER %**, cột VIVOS:

| Mô hình | #tham số | WER VIVOS |
|---|---|---|
| wav2vec2-base-vietnamese-250h | 95M | 10.83 |
| wav2vec2-base-vi-vlsp2020 | 95M | 9.90 |
| wav2vec2-large-vi-vlsp2020 | 317M | 8.61 |
| PhoWhisper-tiny | 39M | 10.41 |
| PhoWhisper-base | 74M | 8.46 |
| PhoWhisper-small | 244M | 6.33 |
| PhoWhisper-medium | 769M | 4.97 |
| PhoWhisper-large | 1.55B | 4.67 |

Vietnamese Open ASR Leaderboard: **chưa đối chiếu** (chưa mở được bảng gốc có Zipformer trong đợt này).

## Giới hạn / không so trực tiếp được

- **Bài PhoWhisper nhét VIVOS train (13,94 h) vào dữ liệu huấn luyện**; Zipformer-vi 30M của VH lấy từ `hynt/Zipformer-30M-RNNT-6000h` (Hugging Face, theo `models/stt/README.md`; tên nêu 6000 h huấn luyện) — **chưa kiểm** tập huấn luyện đó có chứa VIVOS hay không, nên không biết số có bị thổi phồng không.
- Bài báo không nêu quy tắc chuẩn hoá WER chi tiết (hoa/thường, dấu câu); ta chuẩn hoá thường + bỏ dấu câu, VIVOS vốn không dấu câu. Chênh nhỏ có thể do cách chuẩn hoá.
- Zipformer 30M là mô hình nhỏ chạy CPU 2 luồng cho **câu lệnh ngắn**; so với PhoWhisper-large 1,55B là so khác hạng cân. Mục đích là đặt SeeVia cạnh mốc công bố, không phải để thắng.
- Production giải mã beam + hotword **lệnh kính** (MẸ, GỌI CHO…) có thể làm WER đọc văn xuôi VIVOS lệch nhẹ so với greedy; dòng "tham chiếu greedy" (nếu có) cho biết lệch bao nhiêu.
- WER theo người nói: mỗi người ~40 câu nên CI rộng; "người tệ nhất" là cực trị của 19 giá trị nhiễu (winner's curse) — dùng để chỉ hướng, không kết luận.
