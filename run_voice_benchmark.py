import sys, time, os, httpx
if hasattr(sys.stdout, 'reconfigure'): sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path
from pipeline import tts

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

results_md = []
results_md.append('# 🎙 Báo Cáo Benchmark Latency 6 Cấp Độ Thoại (Voice Test Cases)\n')
results_md.append('**Ngày thực hiện**: 17/08/2026\n')
results_md.append('**Môi trường Server**: `http://127.0.0.1:8000` (FastAPI + Gemini VLM + VieNeu TTS)\n\n')

total_passed = 0
total_failed = 0

for category, cases in test_suite.items():
    print(f'=== Running Category: {category} ===')
    results_md.append(f'## 📌 Chức năng: {category}\n')
    results_md.append('| Cấp độ | Câu lệnh giọng nói | TTFB (Âm thanh đầu) | Tổng thời gian | Độ dài Audio | Kích thước Audio | Status |')
    results_md.append('| :--- | :--- | :---: | :---: | :---: | :---: | :---: |')
    
    for level, img_path, text in cases:
        t0 = time.monotonic()
        wav_in = tts.synthesize(text)
        files = {'audio': ('cmd.wav', wav_in, 'audio/wav')}
        if img_path and Path(img_path).exists():
            files['image'] = (Path(img_path).name, Path(img_path).read_bytes(), 'image/jpeg')
            
        ttfb = None
        chunks = []
        try:
            with httpx.stream('POST', 'http://127.0.0.1:8000/process', files=files, timeout=60) as resp:
                for chunk in resp.iter_bytes():
                    if ttfb is None:
                        ttfb = time.monotonic() - t0
                    chunks.append(chunk)
            t_total = time.monotonic() - t0
            body = b''.join(chunks)
            audio_dur = len(body) / 2 / 16000
            ttfb_ms = f'{ttfb*1000:.0f} ms' if ttfb else 'N/A'
            
            print(f'  [{level}] TTFB: {ttfb_ms} | Total: {t_total:.2f}s | Audio: {audio_dur:.2f}s')
            results_md.append(f'| **{level}** | *\"{text}\"* | **{ttfb_ms}** | {t_total:.3f} s | {audio_dur:.2f} s | {len(body):,} B | **PASSED** |')
            total_passed += 1
        except Exception as exc:
            print(f'  [{level}] ERROR: {exc}')
            results_md.append(f'| **{level}** | *\"{text}\"* | **N/A** | ERROR | N/A | N/A | **FAILED** |')
            total_failed += 1
    results_md.append('\n---\n')

print(f'\nDONE! Passed: {total_passed}, Failed: {total_failed}')
content = '\n'.join(results_md)
Path('VOICE_LATENCY_BENCHMARK.md').write_text(content, encoding='utf-8')
