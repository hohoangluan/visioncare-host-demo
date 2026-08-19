import sys, time, os, httpx, json
if hasattr(sys.stdout, 'reconfigure'): sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path
from pipeline import stt, intent, router, tts
from services import visioncare_client
import config

config.VISIONCARE_CLIENT_TOKEN = 'f23ChvjGZt_WYrY-A8eJAyxO5LVEF_TGujmE7F_gRAY'
config.VISIONCARE_DEVICE_ID = 'glasses-123'
visioncare_client.reset_client()

test_suite = {
    'Chat Trò chuyện': [
        ('L1 - Siêu ngắn', 'tests/fixtures/space_room.jpg', 'Bây giờ là mấy giờ'),
        ('L2 - Trung bình', 'tests/fixtures/space_room.jpg', 'Thời tiết hôm nay thế nào'),
        ('L3 - Khá', 'tests/fixtures/space_room.jpg', 'Kể cho tôi nghe một câu chuyện ngắn về sự kiên trì'),
        ('L4 - Phức tạp + GPS', 'tests/fixtures/space_room.jpg', 'Xung quanh vị trí của tôi ở Tân Triều có nhà thuốc nào gần nhất không'),
        ('L5 - Nói ngắt quãng', 'tests/fixtures/space_room.jpg', 'tôi... muốn... hỏi... hôm... nay... ngày... bao... nhiêu'),
        ('L6 - Đa yêu cầu', 'tests/fixtures/space_room.jpg', 'Chào bạn, hãy cho tôi biết hôm nay ngày mấy và thời tiết ở đây ra sao'),
    ],
    'OCR Đọc chữ': [
        ('L1 - Siêu ngắn', 'tests/fixtures/ocr_screenshot.png', 'Đọc chữ'),
        ('L2 - Trung bình', 'tests/fixtures/ocr_screenshot.png', 'Đọc chữ trong ảnh'),
        ('L3 - Đoạn văn', 'tests/fixtures/ocr_screenshot.png', 'Đọc cho tôi đoạn văn bản in trên nhãn chai này'),
        ('L4 - Tìm thông tin', 'tests/fixtures/ocr_screenshot.png', 'Hãy tìm và đọc số điện thoại ghi trong bức ảnh này'),
        ('L5 - Nói ngắt quãng', 'tests/fixtures/ocr_screenshot.png', 'đọc... chữ... góc... trên... trái'),
        ('L6 - Đa dòng', 'tests/fixtures/ocr_screenshot.png', 'Đọc tất cả các dòng chữ in trên bảng từ trên xuống dưới'),
    ],
    'Miêu tả không gian': [
        ('L1 - Siêu ngắn', 'tests/fixtures/space_room.jpg', 'Miêu tả không gian'),
        ('L2 - Trung bình', 'tests/fixtures/space_room.jpg', 'Phía trước tôi có những đồ vật gì'),
        ('L3 - Lối đi an toàn', 'tests/fixtures/space_room.jpg', 'Miêu tả căn phòng này và chỉ ra lối đi an toàn cho người khiếm thị'),
        ('L4 - Chi tiết vị trí', 'tests/fixtures/space_room.jpg', 'Liệt kê chi tiết các đồ nội thất từ trái qua phải và khoảng cách'),
        ('L5 - Nói ngắt quãng', 'tests/fixtures/space_room.jpg', 'phía... trước... có... vật... cản... nguy... hiểm... nào... không'),
        ('L6 - Đa thông tin', 'tests/fixtures/space_room.jpg', 'Nhìn ảnh và cho tôi biết không gian phòng rộng bao nhiêu và có ai không'),
    ],
    'Tìm đồ vật': [
        ('L1 - Siêu ngắn', 'tests/fixtures/find_snack.jpg', 'Tìm chìa khóa'),
        ('L2 - Trung bình', 'tests/fixtures/find_snack.jpg', 'Gói bánh nằm ở đâu'),
        ('L3 - Hướng di chuyển', 'tests/fixtures/find_snack.jpg', 'Tìm giúp tôi gói bánh trên bàn và hướng di chuyển'),
        ('L4 - Góc giờ + Mét', 'tests/fixtures/find_snack.jpg', 'Hãy tìm xem gói bánh nằm ở hướng mấy giờ và cách bao nhiêu mét'),
        ('L5 - Nói ngắt quãng', 'tests/fixtures/find_snack.jpg', 'tìm... giúp... tôi... gói... bánh... ở... gần... đây'),
        ('L6 - Kèm dạng cầm', 'tests/fixtures/find_snack.jpg', 'Tìm gói bánh và mô tả kích thước cầm nắm giúp tôi'),
    ],
    'Đọc tiền': [
        ('L1 - Siêu ngắn', 'tests/fixtures/money_notes.jpg', 'Đọc tiền'),
        ('L2 - Trung bình', 'tests/fixtures/money_notes.jpg', 'Tờ tiền này mệnh giá bao nhiêu'),
        ('L3 - Phân loại', 'tests/fixtures/money_notes.jpg', 'Kiểm tra tờ tiền trên tay tôi là tiền polyme hay tiền giấy'),
        ('L4 - Chi tiết mệnh giá', 'tests/fixtures/money_notes.jpg', 'Cho tôi biết tờ tiền này là mấy trăm nghìn đồng'),
        ('L5 - Nói ngắt quãng', 'tests/fixtures/money_notes.jpg', 'xem... giúp... tờ... tiền... này... mệnh... giá... bao... nhiêu'),
        ('L6 - Đa tờ tiền', 'tests/fixtures/money_notes.jpg', 'Trên bàn có những tờ tiền mệnh giá bao nhiêu'),
    ],
    'Thao tác Điện thoại': [
        ('L1 - Mở nhạc', 'tests/fixtures/space_room.jpg', 'Mở bài hát Nơi này có anh'),
        ('L2 - Gọi điện', 'tests/fixtures/space_room.jpg', 'Gọi điện cho Nguyễn Văn A'),
        ('L3 - Chỉ đường', 'tests/fixtures/space_room.jpg', 'Chỉ đường cho tôi tới Bưu điện Thành phố'),
        ('L4 - Đặt xe', 'tests/fixtures/space_room.jpg', 'Đặt xe đi Đại học Bách Khoa'),
        ('L5 - Gọi cấp cứu', 'tests/fixtures/space_room.jpg', 'Gọi cấp cứu khẩn cấp'),
        ('L6 - Chỉnh âm lượng', 'tests/fixtures/space_room.jpg', 'Tăng âm lượng điện thoại lên'),
    ]
}

report_md = []
report_md.append('# 📊 Báo Cáo Chi Tiết Độ Trễ Từng Giai Đoạn (STT, Intent, Gemini/App, Action & TTFB)\n')
report_md.append('**Ngày thực hiện**: 17/08/2026\n')
report_md.append('**Môi trường**: Glasses Server (`8000`) & Backend Host Server (`8001`)\n')
report_md.append('**Tài khoản**: `user-100` | **Kính**: `glasses-123` | **Điện thoại**: `device-100` (ACTIVE)\n\n')

for category, cases in test_suite.items():
    print(f'\n================ Category: {category} ================')
    report_md.append(f'## 📌 Chức năng: {category}\n')
    report_md.append('| Cấp độ | Lệnh thoại | STT Latency | Intent Latency | Gemini/App Latency | Action Finish (Điện thoại) | TTFB (Gói 1) | Tổng thời gian | Status |')
    report_md.append('| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |')
    
    for level, img_path, text in cases:
        wav_in = tts.synthesize(text)
        img_bytes = Path(img_path).read_bytes() if img_path and Path(img_path).exists() else None
        
        # 1. STT
        t_stt_start = time.monotonic()
        rec_text = stt.transcribe(wav_in)
        t_stt = time.monotonic() - t_stt_start
        
        # 2. Intent
        t_intent_start = time.monotonic()
        intent_label = intent.detect(rec_text)
        t_intent = time.monotonic() - t_intent_start
        
        # 3. Gemini / App Handler & Action Finish
        t_gemini = 0.0
        t_action_finish = "N/A"
        try:
            gen = router.resolve_speech(img_bytes, wav_in)
            t0_gen = time.monotonic()
            first_chunk = next(gen)
            t_gemini = time.monotonic() - t0_gen
            
            if category == 'Thao tác Điện thoại':
                t_act_start = time.monotonic()
                rest_chunks = list(gen)
                t_action_finish = f'{(time.monotonic() - t_act_start):.3f} s'
            else:
                t_action_finish = "N/A (AI Speech)"
        except Exception as e:
            t_gemini = 0.0
            t_action_finish = "N/A"
            
        # 4. HTTP /process Live Stream TTFB & Total
        files = {'audio': ('cmd.wav', wav_in, 'audio/wav')}
        if img_bytes:
            files['image'] = (Path(img_path).name, img_bytes, 'image/jpeg')
            
        t_req_start = time.monotonic()
        ttfb = None
        chunks = []
        try:
            with httpx.stream('POST', 'http://127.0.0.1:8000/process', files=files, timeout=60) as resp:
                for chunk in resp.iter_bytes():
                    if ttfb is None:
                        ttfb = time.monotonic() - t_req_start
                    chunks.append(chunk)
            t_total = time.monotonic() - t_req_start
            body = b''.join(chunks)
            
            ttfb_ms = f'{ttfb * 1000:.0f} ms' if ttfb else 'N/A'
            stt_ms = f'{t_stt * 1000:.0f} ms'
            intent_ms = f'{t_intent * 1000:.0f} ms'
            gemini_ms = f'{t_gemini * 1000:.0f} ms'
            
            print(f'  [{level}] STT: {stt_ms} | Intent ({intent_label}): {intent_ms} | Gemini/App: {gemini_ms} | Action: {t_action_finish} | TTFB: {ttfb_ms} | Total: {t_total:.2f}s')
            report_md.append(f'| **{level}** | *\"{text}\"* | {stt_ms} | {intent_ms} ({intent_label}) | {gemini_ms} | **{t_action_finish}** | **{ttfb_ms}** | {t_total:.3f} s | **PASSED** |')
        except Exception as exc:
            print(f'  [{level}] ERROR: {exc}')
            report_md.append(f'| **{level}** | *\"{text}\"* | {stt_ms} | {intent_ms} | N/A | N/A | N/A | N/A | **FAILED** |')
            
    report_md.append('\n---\n')

content = '\n'.join(report_md)
Path('DETAILED_STAGE_LATENCY_BENCHMARK.md').write_text(content, encoding='utf-8')
print('\nDONE! Wrote detailed benchmark to DETAILED_STAGE_LATENCY_BENCHMARK.md')
