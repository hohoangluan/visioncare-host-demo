import sys, time, os, httpx, json
if hasattr(sys.stdout, 'reconfigure'): sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path
from pipeline import stt, intent, router, tts
from services import visioncare_client
import config

config.VISIONCARE_CLIENT_TOKEN = 'f23ChvjGZt_WYrY-A8eJAyxO5LVEF_TGujmE7F_gRAY'
config.VISIONCARE_DEVICE_ID = 'glasses-123'
visioncare_client.reset_client()

# Kính thật KHÔNG gọi vào localhost — nó đi qua Cloudflare tunnel, nên báo cáo
# có cả hai cột TTFB để thấy con số người dùng thật gặp.
#
# 🔴 HAI CỘT ĐÓ KHÔNG ĐƯỢC TRỪ CHO NHAU. Chúng tới từ hai lượt /process khác
# nhau, mỗi lượt cõng một lượt gọi Gemini riêng, mà Gemini dao động 56ms-5930ms
# trên chính bộ đo này — nhiễu lớn gấp hơn 30 lần phần mạng cần đo. Trừ hai cột
# ra "+652ms tới +8083ms" và kết luận Cloudflare tốn 2 giây là SAI; đo sạch
# bằng /frame cho ra 171ms (keep-alive) / 448ms (kết nối mới) cho cùng 272KB.
# Phần mạng đo riêng ở `_tunnel_overhead()`.
LOCAL_URL = os.environ.get('BENCH_LOCAL_URL', 'http://127.0.0.1:8000/process')
TUNNEL_URL = os.environ.get('BENCH_TUNNEL_URL', 'https://api.visioncare-host.uk/process')
# Bỏ qua đo tunnel bằng BENCH_TUNNEL_URL='' (máy không có mạng ra ngoài).
MEASURE_TUNNEL = bool(TUNNEL_URL)


def _files(wav_in, img_path, img_bytes):
    """Dựng lại dict files cho MỖI request: httpx đọc cạn bytes sau lần gửi đầu."""
    files = {'audio': ('cmd.wav', wav_in, 'audio/wav')}
    if img_bytes:
        files['image'] = (Path(img_path).name, img_bytes, 'image/jpeg')
    return files


def _tunnel_overhead(payload_bytes=272 * 1024, reps=5):
    """Phần Cloudflare cộng thêm, đo SẠCH — không có Gemini xen vào giữa.

    Dùng `/frame` chứ không phải `/process`: nó trả 204 ngay khi nhận xong thân
    request, nên hiệu giữa local và tunnel đúng bằng phần mạng. Đo trên
    `/process` thì mỗi lượt còn cõng thêm một lượt gọi Gemini dao động
    56ms-5930ms, lớn gấp hơn 30 lần thứ đang cần đo.

    Trả về cả cột "kết nối mới" lẫn "keep-alive", vì chênh lệch giữa hai cột đó
    CHÍNH LÀ phần firmware tiết kiệm được khi giữ kết nối — con số đó không
    nhìn ra được nếu chỉ đo một kiểu.
    """
    import os
    import statistics

    body = b'\xff\xd8\xff\xe0' + os.urandom(max(0, payload_bytes - 4))
    headers = {
        'X-Device-Id': 'bench',
        'X-Turn-Id': '11111111-1111-1111-1111-111111111111',
        'Content-Type': 'image/jpeg',
    }
    out = {}
    for name, url in (('local', LOCAL_URL), ('tunnel', TUNNEL_URL)):
        if not url:
            continue
        url = url.replace('/process', '/frame')
        cold, warm = [], []
        for _ in range(reps):
            with httpx.Client() as c:
                t0 = time.monotonic()
                try:
                    c.post(url, content=body, headers=headers, timeout=60)
                    cold.append(time.monotonic() - t0)
                except Exception:
                    pass
            time.sleep(0.5)
        with httpx.Client() as c:
            try:
                c.post(url, content=body, headers=headers, timeout=60)  # mở kết nối trước
            except Exception:
                pass
            for _ in range(reps):
                t0 = time.monotonic()
                try:
                    c.post(url, content=body, headers=headers, timeout=60)
                    warm.append(time.monotonic() - t0)
                except Exception:
                    pass
                time.sleep(0.5)
        out[name] = (
            statistics.median(cold) if cold else None,
            statistics.median(warm) if warm else None,
        )
    return out


def _measure(client, url, wav_in, img_path, img_bytes):
    """(ttfb_giây, tổng_giây) của một lượt /process, hoặc (None, None) khi hỏng.

    Nhận `client` sẵn có chứ không tự tạo: dùng lại kết nối là đúng thứ kính
    thật làm (keep-alive), và nếu đo mỗi lượt một TLS handshake mới thì cột
    tunnel sẽ đắt hơn thực tế vài trăm ms.
    """
    t0 = time.monotonic()
    ttfb = None
    try:
        with client.stream('POST', url, files=_files(wav_in, img_path, img_bytes), timeout=60) as resp:
            for chunk in resp.iter_bytes():
                if ttfb is None:
                    ttfb = time.monotonic() - t0
        return ttfb, time.monotonic() - t0
    except Exception:
        return None, None

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
report_md.append(f'**Ngày thực hiện**: {time.strftime("%d/%m/%Y %H:%M")}\n')
report_md.append('**Môi trường**: Glasses Server (`8000`) & Backend Host Server (`8001`)\n')
report_md.append(f'**Đường ngoài**: `{TUNNEL_URL or "không đo"}` (Cloudflare tunnel, keep-alive)\n')
report_md.append('**Tài khoản**: `user-100` | **Kính**: `glasses-123` | **Điện thoại**: `device-100` (ACTIVE)\n\n')

local_client = httpx.Client()
tunnel_client = httpx.Client()

print('Đo phần Cloudflare cộng thêm (/frame, 272KB, không có Gemini)...')
_ov = _tunnel_overhead()


def _ovms(v):
    return f'{v * 1000:.0f} ms' if v else 'N/A'


report_md.append('## 📌 Phần Cloudflare cộng thêm (đo riêng, 272KB qua `/frame`)\n')
report_md.append('Đo trên `/frame` vì nó trả 204 ngay, không có Gemini xen vào — khác với cột TTFB ở các bảng dưới, vốn còn cõng độ trễ Gemini dao động 56ms–5930ms và KHÔNG được đem trừ cho nhau.\n')
report_md.append('| Đường | Kết nối mới mỗi lượt | Keep-alive | Keep-alive tiết kiệm |')
report_md.append('| :--- | :---: | :---: | :---: |')
for _name, _label in (('local', 'localhost'), ('tunnel', 'Cloudflare tunnel')):
    if _name not in _ov:
        continue
    _c, _w = _ov[_name]
    _save = _ovms(_c - _w) if (_c and _w) else 'N/A'
    report_md.append(f'| {_label} | {_ovms(_c)} | {_ovms(_w)} | {_save} |')
    print(f'  {_label:18s} moi={_ovms(_c)}  keep-alive={_ovms(_w)}  tiet kiem={_save}')
report_md.append('\n---\n')

for category, cases in test_suite.items():
    print(f'\n================ Category: {category} ================')
    report_md.append(f'## 📌 Chức năng: {category}\n')
    report_md.append('| Cấp độ | Lệnh thoại | STT Latency | Intent Latency | Gemini/App Latency | Action Finish | TTFB local | TTFB qua Cloudflare | Tổng thời gian | Status |')
    report_md.append('| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |')

    for level, img_path, text in cases:
        time.sleep(2.5) # Avoid hitting free tier rate limits
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
            t_action_finish = f"Error: {e}"
            
        # 4. HTTP /process qua localhost, rồi qua Cloudflare tunnel
        stt_ms = f'{t_stt * 1000:.0f} ms'
        intent_ms = f'{t_intent * 1000:.0f} ms'
        gemini_ms = f'{t_gemini * 1000:.0f} ms'

        ttfb, t_total = _measure(local_client, LOCAL_URL, wav_in, img_path, img_bytes)
        cf_ttfb, cf_total = (None, None)
        if MEASURE_TUNNEL:
            time.sleep(2.5)
            cf_ttfb, cf_total = _measure(tunnel_client, TUNNEL_URL, wav_in, img_path, img_bytes)

        def _ms(v):
            return f'{v * 1000:.0f} ms' if v else 'N/A'

        # 🔴 KHÔNG trừ hai cột TTFB cho nhau để ra "phần Cloudflare".
        #
        # Bản đầu của script này có cột đó và nó SAI: hai con số tới từ HAI lượt
        # /process khác nhau, mỗi lượt mang một độ trễ Gemini riêng. Gemini dao
        # động 56ms - 5930ms trên chính bộ đo này, tức nhiễu lớn gấp hơn 30 lần
        # thứ cần đo. Cột đó đọc ra "+652ms tới +8083ms" và người đọc kết luận
        # nhầm là Cloudflare tốn hơn 2 giây.
        #
        # Phần Cloudflare được đo RIÊNG bằng `_tunnel_overhead()`: cùng payload,
        # endpoint /frame (trả 204 ngay, không có Gemini ở giữa), nên hiệu số
        # còn lại đúng là phần mạng.
        status = 'PASSED' if ttfb else 'FAILED'

        print(f'  [{level}] STT: {stt_ms} | Intent ({intent_label}): {intent_ms} | '
              f'Gemini/App: {gemini_ms} | Action: {t_action_finish} | '
              f'TTFB local: {_ms(ttfb)} | TTFB tunnel: {_ms(cf_ttfb)} | '
              f'Total: {t_total:.2f}s' if t_total else f'  [{level}] FAILED')
        report_md.append(
            f'| **{level}** | *"{text}"* | {stt_ms} | {intent_ms} ({intent_label}) | '
            f'{gemini_ms} | **{t_action_finish}** | **{_ms(ttfb)}** | **{_ms(cf_ttfb)}** | '
            f'{t_total:.3f} s | **{status}** |'
            if t_total else
            f'| **{level}** | *"{text}"* | {stt_ms} | {intent_ms} | N/A | N/A | N/A | N/A | N/A | **FAILED** |'
        )
            
    report_md.append('\n---\n')

content = '\n'.join(report_md)
Path('DETAILED_STAGE_LATENCY_BENCHMARK.md').write_text(content, encoding='utf-8')
print('\nDONE! Wrote detailed benchmark to DETAILED_STAGE_LATENCY_BENCHMARK.md')
