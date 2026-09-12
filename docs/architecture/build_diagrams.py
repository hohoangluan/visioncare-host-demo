"""Sinh bộ sơ đồ kiến trúc SVG + index.html (chỉ dùng stdlib).

    python docs/architecture/build_diagrams.py
    python docs/architecture/render.py        # PNG + PDF + kiểm chữ đè nhau

Mỗi hình một cơ chế; chữ trên hình chỉ là nhãn, giải thích nằm ở caption.
Số đo lấy từ docs/tasks/measurements/E2E.md (27/08) và CLAUDE.md (RAM board).
"""
from pathlib import Path
from html import escape

OUT = Path(__file__).resolve().parent
FONT = 'Segoe UI, Arial, sans-serif'
C = dict(ink='#152840', muted='#5a6b80', line='#8a98aa', bg='#f6f8fc', white='#ffffff',
         glass='#0b7f8c', ai='#3859bb', app='#8753a6', android='#23805a', amber='#b7791f', red='#c0392b')
TINT = dict(glass='#e1f2f3', ai='#e7ecfa', app='#f1e8f7', android='#e3f2ea', amber='#fcf1de',
            red='#fbe7e4', muted='#eceff4', ink='#e9edf3', line='#eceff4')
DATE = '11/09/2026'


# ─────────────────────────────── icon ────────────────────────────────
# Mỗi icon vẽ trong hộp ~48×48 quanh (0,0); `c` = màu nét, `t` = màu nền.
def _icon(kind, c, t):
    f = f'fill="{c}" stroke="none"'
    I = {
        'glasses': f'<path d="M-30,-4 L-35,-13 M30,-4 L35,-13"/><rect x="-30" y="-9" width="25" height="19" rx="7" fill="{t}"/><rect x="5" y="-9" width="25" height="19" rx="7" fill="{t}"/><path d="M-5,-3 Q0,-8 5,-3"/><circle cx="0" cy="-14" r="3" {f}/>',
        'server': ''.join(f'<rect x="-22" y="{y}" width="44" height="14" rx="3" fill="{t}"/><circle cx="-13" cy="{y+7}" r="2.2" {f}/><path d="M-4,{y+7} H14"/>' for y in (-24, -7, 10)),
        'phone': f'<rect x="-15" y="-26" width="30" height="52" rx="6" fill="{t}"/><path d="M-5,-20 H5"/><circle cx="0" cy="19" r="2.5" {f}/>',
        'cloud': f'<path d="M-16,16 H18 A12,12 0 0 0 20,-8 A16,16 0 0 0 -10,-12 A14,14 0 0 0 -16,16 Z" fill="{t}"/>',
        'gemini': f'<path d="M-16,16 H18 A12,12 0 0 0 20,-8 A16,16 0 0 0 -10,-12 A14,14 0 0 0 -16,16 Z" fill="{t}"/><path d="M2,-5 Q3,3 11,4 Q3,5 2,13 Q1,5 -7,4 Q1,3 2,-5 Z" {f}/>',
        'sparkle': f'<path d="M0,-18 Q2,-2 18,0 Q2,2 0,18 Q-2,2 -18,0 Q-2,-2 0,-18 Z" {f}/>',
        'db': f'<path d="M-20,-15 V15 A20,7 0 0 0 20,15 V-15" fill="{t}"/><ellipse cx="0" cy="-15" rx="20" ry="7" fill="{t}"/><path d="M-20,0 A20,7 0 0 0 20,0"/>',
        'speaker': f'<path d="M-20,-8 H-9 L3,-19 V19 L-9,8 H-20 Z" fill="{t}"/><path d="M10,-9 A13,13 0 0 1 10,9 M16,-16 A22,22 0 0 1 16,16"/>',
        'mic': f'<rect x="-7" y="-22" width="14" height="26" rx="7" fill="{t}"/><path d="M-13,-3 A13,13 0 0 0 13,-3 M0,10 V19 M-8,19 H8"/>',
        'camera': f'<rect x="-22" y="-12" width="44" height="30" rx="5" fill="{t}"/><path d="M-9,-12 L-5,-19 H5 L9,-12"/><circle cx="0" cy="3" r="9"/>',
        'person': f'<circle cx="0" cy="-14" r="9" fill="{t}"/><path d="M-18,22 Q-18,0 0,0 Q18,0 18,22" fill="{t}"/>',
        'bell': f'<path d="M-14,10 Q-14,-18 0,-18 Q14,-18 14,10 L18,14 H-18 Z" fill="{t}"/><path d="M-4,18 A4,4 0 0 0 4,18"/>',
        'button': f'<circle r="19" fill="{t}"/><circle r="9" {f}/>',
        'wave': ''.join(f'<path d="M{x},{-h/2} V{h/2}"/>' for x, h in zip(range(-21, 24, 6), (8, 18, 30, 14, 26, 10, 20, 6))),
        'bubble': f'<rect x="-22" y="-17" width="44" height="29" rx="6" fill="{t}"/><path d="M-9,12 L-13,20 L0,12"/><path d="M-13,-7 H13 M-13,2 H6"/>',
        'tag': f'<path d="M-20,-14 H4 L20,0 L4,14 H-20 Z" fill="{t}"/><circle cx="-10" cy="0" r="3" {f}/>',
        'fork': f'<circle cx="-18" cy="0" r="4" {f}/><path d="M-18,0 H-4 M-4,0 L13,-14 M-4,0 H15 M-4,0 L13,14"/><circle cx="16" cy="-15" r="3.5" {f}/><circle cx="18" cy="0" r="3.5" {f}/><circle cx="16" cy="15" r="3.5" {f}/>',
        'wifi': f'<path d="M-21,-4 A30,30 0 0 1 21,-4 M-13,4 A18,18 0 0 1 13,4 M-5,11 A7,7 0 0 1 5,11"/><circle cx="0" cy="17" r="2.5" {f}/>',
        'ble': '<path d="M-9,-9 L8,7 L0,15 V-15 L8,-7 L-9,9"/>',
        'chip': f'<rect x="-15" y="-15" width="30" height="30" rx="3" fill="{t}"/><rect x="-6" y="-6" width="12" height="12" {f}/>' + ''.join(f'<path d="M{i},-15 V-21 M{i},15 V21 M-15,{i} H-21 M15,{i} H21"/>' for i in (-8, 0, 8)),
        'clock': f'<circle r="18" fill="{t}"/><path d="M0,-10 V0 L8,5"/>',
        'mail': f'<rect x="-20" y="-13" width="40" height="26" rx="3" fill="{t}"/><path d="M-20,-11 L0,3 L20,-11"/>',
        'download': f'<path d="M0,-18 V8 M-10,-2 L0,8 L10,-2 M-18,12 V18 H18 V12"/>',
        'shield': f'<path d="M0,-20 L17,-13 V0 Q17,14 0,20 Q-17,14 -17,0 V-13 Z" fill="{t}"/><path d="M-8,0 L-2,7 L9,-6"/>',
        'laptop': f'<rect x="-18" y="-15" width="36" height="24" rx="3" fill="{t}"/><path d="M-25,13 H25"/>',
        'music': f'<path d="M-6,12 V-14 L14,-18 V8"/><circle cx="-11" cy="12" r="5" {f}/><circle cx="9" cy="8" r="5" {f}/>',
        'call': f'<path d="M-14,-17 Q-19,-4 -8,8 Q4,20 17,16 L17,7 L8,3 L3,8 Q-6,3 -9,-3 L-4,-8 L-7,-17 Z" fill="{t}"/>',
        'pin': f'<path d="M0,20 Q-16,2 -16,-6 A16,16 0 0 1 16,-6 Q16,2 0,20 Z" fill="{t}"/><circle cx="0" cy="-6" r="5"/>',
        'car': f'<path d="M-21,6 V-2 L-14,-12 H14 L21,-2 V6 Z" fill="{t}"/><circle cx="-11" cy="8" r="4.5" {f}/><circle cx="11" cy="8" r="4.5" {f}/>',
        'repeat': '<path d="M-15,-3 A15,15 0 0 1 12,-9 M7,-16 L12,-9 L4,-5 M15,3 A15,15 0 0 1 -12,9 M-7,16 L-12,9 L-4,5"/>',
        'stop': f'<circle r="19" fill="{t}"/><rect x="-7" y="-7" width="14" height="14" rx="2" {f}/>',
        'alarm': f'<path d="M0,-19 L20,15 H-20 Z" fill="{t}"/><path d="M0,-6 V5"/><circle cx="0" cy="10" r="1.8" {f}/>',
        'list': f'<rect x="-18" y="-17" width="36" height="34" rx="4" fill="{t}"/><path d="M-10,-7 H10 M-10,1 H10 M-10,9 H1"/>',
        'check': f'<circle r="19" fill="{t}"/><path d="M-8,0 L-2,7 L9,-6"/>',
        'cross': f'<circle r="19" fill="{t}"/><path d="M-7,-7 L7,7 M7,-7 L-7,7"/>',
        'eye': f'<path d="M-22,0 Q0,-18 22,0 Q0,18 -22,0 Z" fill="{t}"/><circle r="6" {f}/>',
        'ota': f'<rect x="-15" y="-15" width="30" height="30" rx="3" fill="{t}"/>' + ''.join(f'<path d="M{i},-15 V-21 M{i},15 V21 M-15,{i} H-21 M15,{i} H21"/>' for i in (-8, 0, 8)) + '<path d="M0,-8 V6 M-6,0 L0,6 L6,0"/>',
    }
    return I[kind]


class SVG:
    def __init__(self, w, h, number, title, subtitle):
        self.w, self.h = w, h
        markers = ''.join(
            f'<marker id="m-{k}" markerWidth="10" markerHeight="10" refX="8.5" refY="4.5" orient="auto-start-reverse" markerUnits="userSpaceOnUse"><path d="M0,0 L9,4.5 L0,9 Z" fill="{C[k]}"/></marker>'
            for k in ('line', 'glass', 'ai', 'app', 'android', 'amber', 'red', 'muted'))
        self.p = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" aria-label="{escape(title)}: {escape(subtitle)}">'
                  f'<defs>{markers}</defs><rect width="100%" height="100%" fill="{C["bg"]}"/>']
        self.text(40, 38, 'YOUR EYES / VISIONCARE  ·  KIẾN TRÚC', 12.5, 'ai', 700)
        self.text(40, 78, f'{number}  {title}', 28, 'ink', 700)
        self.text(40, 106, subtitle, 15.5, 'muted')

    # ── nguyên tố ──
    def text(self, x, y, s, size=14, color='ink', weight=400, anchor='start', halo=None, italic=False):
        extra = f' stroke="{halo}" stroke-width="5" paint-order="stroke" stroke-linejoin="round"' if halo else ''
        st = ' font-style="italic"' if italic else ''
        self.p.append(f'<text x="{x}" y="{y}" font-family="{FONT}" font-size="{size}" fill="{C.get(color, color)}" font-weight="{weight}" text-anchor="{anchor}"{st}{extra}>{escape(s)}</text>')

    def rect(self, x, y, w, h, fill='white', stroke='#dbe2ec', rx=14, dash=False, sw=1.5):
        fill = C.get(fill, TINT.get(fill, fill)) if fill != 'white' else '#ffffff'
        d = ' stroke-dasharray="7 5"' if dash else ''
        self.p.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" stroke="{C.get(stroke, stroke)}" stroke-width="{sw}"{d}/>')

    def icon(self, kind, cx, cy, color='ai', scale=1.0, disc=True, disc_r=34):
        c = C[color]
        if disc:
            self.p.append(f'<circle cx="{cx}" cy="{cy}" r="{disc_r*scale}" fill="{TINT[color]}"/>')
        self.p.append(f'<g transform="translate({cx} {cy}) scale({scale})" fill="none" stroke="{c}" stroke-width="{3/max(scale,0.6):.2f}" stroke-linecap="round" stroke-linejoin="round">{_icon(kind, c, "#ffffff")}</g>')

    def badge(self, cx, cy, s, color='ai', r=13):
        self.p.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{C[color]}"/>')
        self.text(cx, cy + 4.5, str(s), 13, '#ffffff', 700, 'middle')

    def pill(self, cx, cy, s, color='ai', size=13, filled=False, weight=600):
        w = len(s) * size * 0.56 + 24
        self.p.append(f'<rect x="{cx-w/2:.1f}" y="{cy-size*0.95:.1f}" width="{w:.1f}" height="{size*1.9:.1f}" rx="{size*0.95:.1f}" fill="{C[color] if filled else TINT[color]}" stroke="{C[color]}" stroke-width="1"/>')
        self.text(cx, cy + size * 0.36, s, size, '#ffffff' if filled else color, weight, 'middle')

    def arrow(self, pts, color='line', label=None, at=None, dash=False, both=False, sw=2.4, halo='bg', size=13, lcolor=None, anchor='middle', curve=False):
        if curve and len(pts) == 3:
            (x0, y0), (qx, qy), (x1, y1) = pts
            d = f'M{x0},{y0} Q{qx},{qy} {x1},{y1}'
        else:
            d = 'M' + ' L'.join(f'{x},{y}' for x, y in pts)
        dd = ' stroke-dasharray="8 6"' if dash else ''
        ms = f' marker-start="url(#m-{color})"' if both else ''
        self.p.append(f'<path d="{d}" fill="none" stroke="{C[color]}" stroke-width="{sw}" stroke-linejoin="round" marker-end="url(#m-{color})"{ms}{dd}/>')
        if label:
            labels = label if isinstance(label, list) else [label]
            x, y = at if at else ((pts[0][0] + pts[-1][0]) / 2, (pts[0][1] + pts[-1][1]) / 2 - 9)
            for i, t in enumerate(labels):
                self.text(x, y + i * (size + 5), t, size if i == 0 else size - 1, lcolor or (color if color != 'line' else 'muted'),
                          600 if i == 0 else 400, anchor, halo=C.get(halo, halo))

    def card(self, cx, top, w, h, icon, title, sub=(), color='ai', tag=None, fill='white'):
        """Thẻ dọc: icon trên, tên, 1-2 dòng phụ, tag repo dưới đáy."""
        self.rect(cx - w / 2, top, w, h, fill)
        self.p.append(f'<rect x="{cx-w/2+18}" y="{top}" width="{w-36}" height="4" rx="2" fill="{C[color]}"/>')
        self.icon(icon, cx, top + 48, color)
        self.text(cx, top + 106, title, 17, color, 700, 'middle')
        for i, s in enumerate(sub):
            self.text(cx, top + 128 + i * 19, s, 13, 'muted', 400, 'middle')
        if tag:
            self.text(cx, top + h - 12, tag, 11.5, 'line', 600, 'middle')

    def mini(self, x, y, w, h, icon, title, sub=None, color='ai', fill='white', stroke='#dbe2ec'):
        """Thẻ ngang gọn: icon trái, chữ phải."""
        self.rect(x, y, w, h, fill, stroke, rx=12)
        self.icon(icon, x + 36, y + h / 2, color, 0.72)
        if sub:
            self.text(x + 68, y + h / 2 - 3, title, 14.5, color, 700)
            self.text(x + 68, y + h / 2 + 16, sub, 12.5, 'muted')
        else:
            self.text(x + 68, y + h / 2 + 5, title, 14.5, color, 700)

    def bracket(self, x0, x1, y, label, color):
        self.p.append(f'<path d="M{x0},{y-8} V{y} H{x1} V{y-8}" fill="none" stroke="{C[color]}" stroke-width="2.4"/>')
        self.text((x0 + x1) / 2, y + 19, label, 13, color, 600, 'middle')

    def footer(self, s):
        self.text(40, self.h - 22, s + f'   ·   {DATE}', 12, 'muted')

    def save(self, name):
        data = ''.join(self.p) + '</svg>'
        (OUT / name).write_text(data, encoding='utf-8')
        return data


def legend(s, x, y, items):
    for i, (color, dash, label) in enumerate(items):
        yy = y + i * 24
        s.p.append(f'<path d="M{x},{yy} H{x+38}" stroke="{C[color]}" stroke-width="3"' + (' stroke-dasharray="8 6"' if dash else '') + f' marker-end="url(#m-{color})"/>')
        s.text(x + 50, yy + 4.5, label, 13, 'ink')


# ─────────────────────────── 01 · tổng quan ───────────────────────────
def d01():
    s = SVG(1660, 890, '01', 'Toàn cảnh: ai nói chuyện với ai',
            'Bốn khối chạy chính. Kính chỉ nói chuyện với server kính; server kính nhờ server app khi cần tới điện thoại.')
    legend(s, 1250, 40, [('ai', False, 'hỏi – đáp (một lượt giữ nút)'), ('app', False, 'hành động trên điện thoại'), ('amber', True, 'nền / quản lý')])
    T = 330
    s.card(105, T, 150, 190, 'person', 'Người dùng', ['khiếm thị'], 'glass')
    s.card(385, T, 220, 190, 'glasses', 'Kính', ['ESP32-S3 · camera', 'mic · loa · nút'], 'glass', 'your-eyes-esp32-firmware')
    s.card(830, T, 230, 190, 'server', 'Server kính', ['STT → ý định → TTS', 'FastAPI · cổng 8000'], 'ai', 'Sever_test')
    s.card(1195, T, 220, 190, 'server', 'Server app', ['tài khoản · operation', 'FastAPI · cổng 8001'], 'app', 'app_demo_backend')
    s.card(1545, T, 190, 190, 'phone', 'Android', ['thực thi lệnh', 'Kotlin · Compose'], 'android', 'app_demo_backend')
    s.mini(715, 150, 230, 84, 'gemini', 'Gemini', 'hiểu ảnh · trò chuyện', 'ai')
    s.mini(1325, 150, 170, 84, 'bell', 'Firebase', 'FCM push', 'app')
    B = 600
    s.card(830, B, 230, 150, 'chip', 'Model cục bộ (CPU)', ['Zipformer STT · SetFit', 'VieNeu-TTS · YOLO'], 'ai')
    s.card(1195, B, 220, 150, 'db', 'PostgreSQL', ['users · devices', 'operations'], 'app')
    s.card(1545, B, 190, 150, 'music', 'Ứng dụng máy', ['Spotify · Maps', 'gọi điện · GPS'], 'android')
    # người ↔ kính
    s.arrow([(182, 392), (272, 392)], 'ai', 'nói', at=(227, 382))
    s.arrow([(272, 442), (182, 442)], 'ai', 'nghe', at=(227, 432))
    # kính ↔ server kính
    s.pill(605, 506, 'HTTPS · Cloudflare tunnel', 'muted', 12, weight=500)
    s.arrow([(497, 372), (713, 372)], 'ai', 'ảnh + câu nói', at=(605, 362))
    s.arrow([(713, 420), (497, 420)], 'ai', 'tiếng trả lời (stream)', at=(605, 410))
    s.arrow([(497, 468), (713, 468)], 'amber', 'poll /downlink · OTA', at=(605, 458), dash=True)
    # server kính ↔ Gemini
    s.arrow([(800, 236), (800, 328)], 'ai', both=True)
    s.text(812, 288, 'ảnh + câu hỏi ⇅ chữ (stream)', 13, 'ai', 600, 'start', halo=C['bg'])
    # server kính ↔ server app
    s.arrow([(947, 385), (1083, 385)], 'app', 'lệnh JSON', at=(1015, 375))
    s.arrow([(1083, 440), (947, 440)], 'app', 'kết quả', at=(1015, 430))
    # server app → FCM → Android → report
    s.arrow([(1255, 328), (1255, 192), (1323, 192)], 'app')
    s.arrow([(1497, 192), (1575, 192), (1575, 328)], 'app', 'push lệnh', at=(1563, 280), anchor='end')
    s.arrow([(1448, 456), (1307, 456)], 'app', 'report (REST)', at=(1377, 446))
    # xuống hàng dưới
    s.arrow([(830, 522), (830, 598)], 'line', 'chạy local', at=(842, 565), both=True, anchor='start')
    s.arrow([(1195, 522), (1195, 598)], 'app', 'operation', at=(1207, 565), both=True, anchor='start')
    s.arrow([(1545, 522), (1545, 598)], 'android', 'Intent / SDK', at=(1557, 565), anchor='start')
    # BLE — đường thẳng từ điện thoại sang kính, không qua server
    s.arrow([(1470, 522), (1470, 570), (1370, 570), (1370, 810), (385, 810), (385, 523)], 'amber', dash=True)
    s.text(880, 800, 'BLE: điện thoại cấp Wi-Fi thẳng cho kính khi kính chưa có mạng', 13, 'amber', 600, 'middle', halo=C['bg'])
    # hai con số
    s.rect(30, 608, 320, 64, 'white')
    s.text(50, 648, '0.25 s', 26, 'ai', 700)
    s.text(148, 634, 'tiếng đầu tiên (trung vị)', 13, 'ink', 600)
    s.text(148, 654, 'sau khi gửi xong câu nói', 12.5, 'muted')
    s.rect(30, 684, 320, 64, 'white')
    s.text(50, 724, '16/16', 26, 'ai', 700)
    s.text(148, 710, 'chức năng có tiếng < 1 s', 13, 'ink', 600)
    s.text(148, 730, 'bench qua tunnel · 27/08', 12.5, 'muted')
    s.footer('Web UI mock (app/ · Expo) là bản trình diễn giao diện, không nằm trong luồng lệnh thật')
    return s.save('01-tong-quan.svg')


# ─────────────────────────── 02 · một lượt ───────────────────────────
def d02():
    s = SVG(1660, 990, '02', 'Một lượt giữ nút, từ đầu tới cuối',
            'Ví dụ: “mô tả xung quanh giúp tôi”. Ảnh đi trước và chờ sẵn; câu nói tới sau; tiếng mở đầu phát trước khi Gemini xong.')
    lanes = [(150, 170, 'glass', 'glasses', 'Kính'), (340, 190, 'ai', 'server', 'Server kính'), (550, 140, 'muted', 'gemini', 'Cloud')]
    for y, h, col, ic, name in lanes:
        s.rect(30, y, 1600, h, TINT[col], TINT[col], rx=16)
        ccol = 'ai' if col == 'muted' else col
        s.icon(ic, 92, y + h / 2 - 12, ccol, 0.8)
        s.text(92, y + h / 2 + 34, name, 14, ccol, 700, 'middle')

    def step(n, x, y, ic, title, sub, col):
        s.p.append(f'<circle cx="{x}" cy="{y}" r="33" fill="#ffffff" stroke="{C[col]}" stroke-width="2"/>')
        s.icon(ic, x, y, col, 0.78, disc=False)
        s.badge(x + 27, y - 27, n, col, 12)
        s.text(x, y + 56, title, 14.5, 'ink', 700, 'middle')
        if sub:
            s.text(x, y + 75, sub, 12.5, 'muted', 400, 'middle')

    K, S, G = 215, 415, 605
    step(1, 270, K, 'button', 'Giữ nút', 'bắt đầu một lượt', 'glass')
    step(2, 440, K, 'camera', 'Chụp ảnh', 'XGA 1024×768', 'glass')
    step(3, 620, K, 'mic', 'Thu tiếng', 'IMA ADPCM', 'glass')
    step(4, 440, S, 'list', 'Đệm ảnh', 'theo device + turn', 'ai')
    step(5, 740, S, 'wave', 'STT', 'Zipformer · CPU', 'ai')
    step(6, 900, S, 'tag', 'Ý định', 'SetFit → Gemini', 'ai')
    step(7, 1060, S, 'fork', 'Router', '6 bước → handler', 'ai')
    step(8, 1230, G, 'gemini', 'Gemini', 'ảnh + câu hỏi', 'ai')
    step(9, 1390, S, 'speaker', 'TTS', 'VieNeu · theo câu', 'ai')
    step(10, 1540, K, 'speaker', 'Phát loa', 'đệm → I2S', 'glass')
    s.p.append(f'<circle cx="1060" cy="{K}" r="22" fill="#ffffff" stroke="{C["glass"]}" stroke-width="2" stroke-dasharray="4 3"/>')
    s.icon('speaker', 1060, K, 'glass', 0.5, disc=False)
    s.text(1060, K - 34, 'tiếng mở đầu', 12.5, 'glass', 700, 'middle')

    s.arrow([(305, K), (405, K)], 'glass')
    s.arrow([(475, K), (585, K)], 'glass')
    s.arrow([(440, K + 84), (440, S - 35)], 'glass', ['POST /frame', 'socket riêng'], at=(452, 347), anchor='start', halo=TINT['ai'])
    s.arrow([(620, K + 84), (620, S), (705, S)], 'glass', ['POST /process', 'chunked'], at=(632, 347), anchor='start', halo=TINT['ai'])
    s.arrow([(775, S), (865, S)], 'ai')
    s.arrow([(935, S), (1025, S)], 'ai')
    s.arrow([(1060, S - 34), (1060, K + 24)], 'glass', dash=True)
    s.text(1072, 300, '≈ 0.3 s', 13, 'glass', 700, halo=TINT['ai'])
    s.arrow([(1095, S), (1160, S), (1160, G), (1195, G)], 'ai', 'hỏi', at=(1172, 520), anchor='start', halo=TINT['ai'])
    s.arrow([(440, S + 96), (440, G), (1195, G)], 'ai', 'ảnh lấy từ đệm, không gửi lại', at=(800, G - 10), dash=True, halo=TINT['muted'])
    s.arrow([(1265, G), (1320, G), (1320, S), (1355, S)], 'ai', 'chữ (stream)', at=(1308, 520), anchor='end', halo=TINT['ai'])
    s.arrow([(1425, S), (1500, S), (1500, K + 30)], 'ai', ['audio stream', 'câu đầu phát ngay'], at=(1488, 350), anchor='end', halo=TINT['ai'])

    # ── dòng thời gian thật (hàng `space`, E2E.md bảng 1) ──
    y0 = 760
    s.text(40, 728, 'Người dùng nghe gì, khi nào — hàng “space” trong E2E.md, đo qua tunnel 27/08 (mốc 0 = gửi xong câu nói)', 14, 'ink', 700)
    X0, PX = 200, 430  # 430 px / giây
    X = lambda sec: X0 + sec * PX
    s.p.append(f'<path d="M{X0},{y0+66} H{X(3.2)}" stroke="{C["line"]}" stroke-width="1.5"/>')
    for t in range(4):
        s.p.append(f'<path d="M{X(t)},{y0+61} V{y0+71}" stroke="{C["line"]}" stroke-width="1.5"/>')
        s.text(X(t), y0 + 88, f'{t} s', 12, 'muted', 400, 'middle')
    s.text(40, y0 + 44, 'nghe thấy', 13, 'glass', 700)
    s.rect(X(0.308), y0 + 26, X(2.969) - X(0.308), 28, 'glass', 'glass', rx=6)
    s.text((X(0.308) + X(2.969)) / 2, y0 + 45, 'đang phát (tiếng mở đầu → câu trả lời)', 13, '#ffffff', 600, 'middle')
    s.p.append(f'<path d="M{X(0.308)},{y0+10} V{y0+58}" stroke="{C["glass"]}" stroke-width="2.5"/>')
    s.text(X(0.308), y0 + 4, 'tiếng đầu 0.31 s', 12.5, 'glass', 700, 'middle')
    s.p.append(f'<path d="M{X(2.969)},{y0+10} V{y0+58}" stroke="{C["glass"]}" stroke-width="2.5"/>')
    s.text(X(2.969), y0 + 4, 'byte cuối 2.97 s', 12.5, 'glass', 700, 'middle')
    yb = y0 + 108
    s.text(40, yb + 14, 'độ dài chặng', 13, 'ai', 700)
    for i, (name, ms) in enumerate([('STT', 52), ('ý định', 19), ('handler (Gemini)', 1124)]):
        yy = yb + i * 26
        s.rect(X0, yy, max(X(ms / 1000) - X0, 3), 18, 'ai', 'ai', rx=4)
        s.text(max(X(ms / 1000), X0 + 3) + 10, yy + 14, f'{name} · {ms} ms', 12.5, 'ai', 600)
    s.text(1030, yb + 14, 'Chặng đo bằng turn_trace, cùng thang với trục trên.', 12.5, 'muted')
    s.text(1030, yb + 34, 'Tiếng đầu tới trước khi Gemini xong: người dùng không', 12.5, 'muted')
    s.text(1030, yb + 54, 'ngồi trong im lặng chờ phần chậm nhất.', 12.5, 'muted')
    s.footer('Trung vị 16 chức năng: tiếng đầu 0.25 s, chậm nhất 0.88 s (contact_call). Nguồn: docs/tasks/measurements/E2E.md')
    return s.save('02-mot-luot.svg')


# ─────────────────────────── 03 · router ───────────────────────────
def d03():
    s = SVG(1660, 1020, '03', 'Router 6 bước: câu nói rơi qua từng cổng',
            'Cổng nào khớp trước thì thắng. Chỉ bước 6 mới tốn tới mô hình; năm bước trên là luật cục bộ.')
    gx, gw, gh = 470, 330, 92
    s.pill(gx + 110, 150, 'câu nói sau STT', 'ai', 14, filled=True)
    s.pill(gx + gw - 50, 150, '3 nhịp nút SOS', 'red', 13, filled=True)
    s.arrow([(gx + gw - 50, 170), (gx + gw - 50, 198)], 'red')
    s.text(gx + gw - 30, 190, 'X-Trigger: emergency · bỏ qua STT', 12.5, 'red', 600)
    gates = [
        ('KHẨN CẤP', 'regex cục bộ · tuyệt đối', 'red', '“cứu tôi với”', 'alarm', 'Gọi cấp cứu ngay', 'không qua bước xác minh nào'),
        ('PENDING TẤT ĐỊNH', 'đang có câu hỏi chờ trả lời', 'ai', '“ừ” · “không” · “số hai”', 'check', 'Trả lời câu hỏi đang chờ', '“Gọi cho Mẹ nhé?” → “ừ”'),
        ('DỪNG / LỆNH TOÀN CỤC', 'regex cục bộ · 0 ms', 'amber', '“dừng lại”', 'stop', 'Dừng nhạc, chỉ đường, canh vật cản', 'không gọi Gemini'),
        ('PENDING ĐIỀN SLOT', 'qua slot validator', 'ai', '“Mẹ” (sau “gọi cho ai?”)', 'list', 'Điền chỗ trống vào lệnh đang dở', 'lệnh chạy tiếp, không hỏi lại'),
        ('HUỶ / NHẮC LẠI', 'regex cục bộ · 0 ms', 'muted', '“thôi” · “nói lại đi”', 'repeat', 'Huỷ hoặc phát lại câu trước', 'không mạng ngoài'),
        ('Ý ĐỊNH MỚI', 'SetFit ONNX ~8 ms → Gemini nếu chưa chắc', 'android', '“đọc chữ trước mặt”', 'fork', 'Chọn handler mới', 'ocr · find · money · chat · nhạc · gọi…'),
    ]
    for i, (name, sub, col, example, ic, out, outsub) in enumerate(gates):
        y = 200 + i * 128
        c = 'ai' if col == 'muted' else col
        s.rect(gx, y, gw, gh, 'white', C[c], rx=12, sw=2)
        s.badge(gx + 30, y + gh / 2, i + 1, c, 15)
        s.text(gx + 58, y + 40, name, 16, c, 700)
        s.text(gx + 58, y + 62, sub, 12.5, 'muted')
        # ví dụ bên trái
        bw = len(example) * 7.2 + 30
        s.rect(gx - 60 - bw, y + 26, bw, 40, 'white', '#cfd8e5', rx=20)
        s.text(gx - 60 - bw / 2, y + 51, example, 13.5, 'ink', 600, 'middle', italic=True)
        s.arrow([(gx - 58, y + gh / 2), (gx - 4, y + gh / 2)], 'line', dash=True, sw=1.6)
        # khớp → kết quả
        s.arrow([(gx + gw + 2, y + gh / 2), (gx + gw + 90, y + gh / 2)], c, 'khớp', at=(gx + gw + 46, y + gh / 2 - 9))
        s.mini(gx + gw + 94, y + 6, 390, 80, ic, out, outsub, c)
        # không khớp → xuống
        if i < 5:
            s.arrow([(gx + gw / 2, y + gh + 2), (gx + gw / 2, y + 126)], 'line', 'không', at=(gx + gw / 2 + 12, y + gh + 24), anchor='start', size=12)
    s.arrow([(gx + 110, 170), (gx + 110, 198)], 'ai')
    # ngoặc: bước 3 kẹp giữa hai pha pending
    bx = gx + gw + 500
    y2, y3, y4 = 200 + 128 + gh / 2, 200 + 256 + gh / 2, 200 + 384 + gh / 2
    s.p.append(f'<path d="M{bx},{y2} H{bx+22} V{y4} H{bx}" fill="none" stroke="{C["ai"]}" stroke-width="2.4"/>')
    s.p.append(f'<path d="M{bx+22},{y3} H{bx+40}" stroke="{C["amber"]}" stroke-width="2.4"/>')
    s.text(bx + 50, y3 - 58, 'Lệnh dừng kẹp GIỮA', 14, 'ai', 700)
    s.text(bx + 50, y3 - 38, 'hai pha pending:', 14, 'ai', 700)
    s.text(bx + 50, y3 - 10, '“ừ / không / số hai” trả lời', 13, 'ink')
    s.text(bx + 50, y3 + 9, 'câu hỏi trước khi xét dừng;', 13, 'ink')
    s.text(bx + 50, y3 + 34, 'đang chờ tên bài mà nói', 13, 'ink')
    s.text(bx + 50, y3 + 53, '“dừng lại” → là lệnh dừng,', 13, 'ink')
    s.text(bx + 50, y3 + 72, 'không bị điền làm tên bài.', 13, 'ink')
    s.footer('Nguồn: pipeline/router.py — khối ghi chú đầu file và resolve_speech()')
    return s.save('03-router.svg')


# ─────────────────────────── 04 · hành động ───────────────────────────
def d04():
    s = SVG(1660, 960, '04', 'Hành động trên điện thoại: một request_id đi trọn vòng',
            'Ví dụ: “mở nhạc”. Lệnh đi xuống bằng FCM, kết quả đi về bằng REST — không đi ngược qua FCM.')
    T = 330
    s.card(120, T, 170, 170, 'glasses', 'Kính', ['nói · nghe'], 'glass')
    s.card(480, T, 230, 170, 'server', 'Server kính', ['router → action_flow', 'chờ kết quả'], 'ai')
    s.card(900, T, 230, 170, 'server', 'Server app', ['định tuyến kính → máy', 'ba worker nền'], 'app')
    s.card(1480, T, 220, 170, 'phone', 'Android', ['FCM → Dispatcher', '→ ActionRegistry'], 'android')
    s.mini(1105, 158, 180, 84, 'bell', 'Firebase', 'FCM data message', 'app')
    # đi xuống (tím)
    s.arrow([(207, 380), (363, 380)], 'ai', '“mở nhạc”', at=(285, 370))
    s.arrow([(597, 380), (783, 380)], 'app', ['① POST /service/…', 'device_id · request_id'], at=(690, 350))
    s.arrow([(960, 328), (960, 200), (1103, 200)], 'app', '② delivery worker', at=(972, 280), anchor='start')
    s.arrow([(1287, 200), (1480, 200), (1480, 328)], 'app', '③ push lệnh', at=(1383, 190))
    # đi về (xanh lá)
    s.arrow([(1368, 450), (1017, 450)], 'android', ['⑤ POST /device/report', 'succeeded / failed + result'], at=(1192, 474))
    s.arrow([(783, 450), (597, 450)], 'android', ['⑥ callback', 'dự phòng: poll'], at=(690, 474))
    s.arrow([(363, 450), (207, 450)], 'ai', '⑦ nói kết quả', at=(285, 474))
    # android thực thi
    s.arrow([(1480, 502), (1480, 560)], 'android', '④ thực thi', at=(1492, 536), anchor='start')
    for i, (ic, lb) in enumerate([('music', 'nhạc'), ('call', 'gọi điện'), ('pin', 'chỉ đường'), ('car', 'đặt xe*')]):
        x = 1385 + i * 64
        s.icon(ic, x, 605, 'android', 0.62)
        s.text(x, 648, lb, 12, 'android', 600, 'middle')
    s.text(1480, 672, 'Android API · Spotify · Maps · Grab', 12, 'muted', 400, 'middle')
    # postgres
    s.arrow([(900, 502), (900, 568)], 'app', both=True)
    s.mini(790, 570, 220, 84, 'db', 'PostgreSQL', 'processing → succeeded', 'app')
    # hết giờ
    s.arrow([(480, 502), (480, 568)], 'amber', 'không có kết quả?', at=(492, 540), anchor='start', dash=True)
    s.rect(330, 570, 300, 96, TINT['amber'], 'amber', rx=12)
    s.icon('clock', 372, 618, 'amber', 0.7)
    s.text(408, 606, 'Hết cửa sổ chờ', 14.5, 'amber', 700)
    s.text(408, 628, 'nói “Điện thoại chưa báo lại.”', 13, 'ink', 600)
    s.text(408, 648, 'không hứa gì thêm', 12.5, 'muted')
    # ba ID
    s.text(40, 730, 'Ba ID, ba phạm vi — đừng lẫn:', 14, 'ink', 700)
    s.bracket(120, 480, 775, 'X-Turn-Id · một lượt kính ↔ server kính', 'glass')
    s.bracket(480, 1480, 830, 'request_id · một operation: service → FCM → Android → report → callback', 'app')
    s.bracket(120, 900, 885, 'device_id · chiếc kính; server app ánh xạ ra người dùng và điện thoại', 'ai')
    s.footer('* Đặt xe: luồng demo mở Grab, giá/chuyến thật chưa tích hợp. Kính chưa ghép đôi ⇒ server app trả 404 GLASSES_DEVICE_NOT_LINKED ngay bước ①')
    return s.save('04-hanh-dong.svg')


# ─────────────────────────── 05 · kênh xuống + RAM ───────────────────────────
def d05():
    s = SVG(1660, 860, '05', 'Kênh xuống: kính hỏi, server không đẩy',
            'Server không mở được kết nối vào kính sau NAT, nên kính tự hỏi khi rảnh. Bản demo1 tắt kênh này vì thiếu RAM liền.')
    s.rect(30, 140, 880, 670, 'white')
    s.text(56, 178, 'CƠ CHẾ', 13, 'ai', 700)
    srcs = [('phone', 'Android', 'có cuộc gọi đến', 'android'), ('wifi', 'App', 'đổi Wi-Fi cho kính', 'android'), ('laptop', 'Dev', 'publish_firmware.py', 'muted')]
    for i, (ic, t, sub, col) in enumerate(srcs):
        y = 220 + i * 140
        s.mini(56, y, 230, 84, ic, t, sub, 'ai' if col == 'muted' else col)
    # hộp thư trên server kính
    s.rect(340, 210, 230, 380, TINT['ai'], '#c9d4f1', rx=16)
    s.icon('server', 455, 262, 'ai', 0.8)
    s.text(455, 316, 'Server kính', 16, 'ai', 700, 'middle')
    s.text(455, 336, 'hộp thư theo device_id', 12.5, 'muted', 400, 'middle')
    for i, ev in enumerate(['call_incoming', 'wifi_config', 'firmware_update']):
        y = 364 + i * 66
        s.rect(358, y, 194, 52, 'white', '#c9d4f1', rx=8)
        s.icon('mail', 386, y + 26, 'amber', 0.55, disc=False)
        s.text(410, y + 31, ev, 13.5, 'ink', 600)
    s.arrow([(288, 262), (338, 380)], 'android')
    s.arrow([(288, 402), (338, 446)], 'android')
    s.arrow([(288, 542), (338, 512)], 'line')
    s.text(58, 324, 'qua server app → /internal/device-events', 12, 'muted')
    # kính poll
    s.card(800, 250, 180, 170, 'glasses', 'Kính', ['chỉ khi rảnh:', 'không /process, OTA'], 'glass')
    s.arrow([(708, 300), (572, 300)], 'amber', ['GET /downlink', '≈ 2 s một lần'], at=(640, 270), halo='#ffffff')
    s.arrow([(572, 380), (708, 380)], 'amber', ['events[]', 'lấy hết một lượt'], at=(640, 404), halo='#ffffff')
    s.icon('clock', 640, 228, 'amber', 0.6)
    # kính làm gì với event
    outs = [('speaker', 'báo “có cuộc gọi…”'), ('wifi', 'ghi NVS → nối mạng mới'), ('download', 'kéo manifest → OTA')]
    for i, (ic, t) in enumerate(outs):
        y = 470 + i * 62
        s.icon(ic, 690, y + 20, 'glass', 0.55)
        s.text(718, y + 25, t, 13, 'ink', 600)
    s.arrow([(800, 422), (800, 462)], 'glass')
    s.text(56, 780, 'Cache-Control: no-store — kênh đi qua Cloudflare, một lượt poll bị cache nghĩa là kính đọc mãi hộp thư cũ.', 12.5, 'muted')

    # ── panel phải: RAM ──
    s.rect(940, 140, 690, 670, 'white')
    s.text(966, 178, 'VÌ SAO demo1 TẮT NÓ — khối RAM liền lớn nhất trên ESP32 (đo trên board)', 13, 'red', 700)
    X0, W = 966, 540
    X = lambda b: X0 + b / 114676 * W
    rows = [('khởi động', 114676, 'glass'), ('sau MỘT phiên TLS', 69620, 'glass'), ('sau khi cấp phát audio', 34804, 'red')]
    for i, (lb, b, col) in enumerate(rows):
        y = 222 + i * 78
        s.text(X0, y, lb, 13.5, 'ink', 600)
        s.rect(X0, y + 10, X(b) - X0, 30, col, col, rx=6)
        s.text(X(b) - 10, y + 31, f'{b:,} B'.replace(',', ' '), 13, '#ffffff', 700, 'end')
    tx = X(45056)
    s.p.append(f'<path d="M{tx},{206} V{450}" stroke="{C["red"]}" stroke-width="2" stroke-dasharray="6 5"/>')
    s.text(tx, 470, 'một phiên TLS cần 45 056 B', 13, 'red', 700, 'middle')
    s.text(tx, 490, 'phiên thứ hai (poll) không cấp phát nổi', 12.5, 'red', 400, 'middle')
    # hệ quả
    y = 530
    s.text(966, y, 'Bản demo1: ENABLE_DOWNLINK 0', 15, 'ink', 700)
    items = [('cross', 'red', 'kính không báo cuộc gọi đến'),
             ('cross', 'red', 'đổi Wi-Fi từ app qua server → 409'),
             ('check', 'android', 'đổi Wi-Fi qua BLE / SoftAP / LAN vẫn chạy'),
             ('check', 'android', 'OTA vẫn chạy: POST /ota/pull + hỏi mỗi 6 giờ')]
    for i, (ic, col, t) in enumerate(items):
        yy = y + 36 + i * 42
        s.icon(ic, 982, yy - 5, col, 0.5)
        s.text(1006, yy, t, 13.5, 'ink')
    s.text(966, 780, 'Đường ra chưa quyết: đẩy mbedtls sang PSRAM (6.16 MB liền) — phải rời Arduino IDE.', 12.5, 'muted')
    s.footer('Nguồn: CLAUDE.md mục “nút thắt RAM”, app.py poll_downlink(), services/events_channel.py')
    return s.save('05-kenh-xuong.svg')


# ─────────────────────────── 06 · Wi-Fi + OTA ───────────────────────────
def d06():
    s = SVG(1660, 800, '06', 'Đưa Wi-Fi và firmware mới vào kính',
            'Trái: ba đường cấp mạng. Phải: kính tự kéo firmware, server chỉ công bố — không ai đẩy binary vào kính.')
    s.rect(30, 140, 760, 610, 'white')
    s.text(56, 178, 'BA ĐƯỜNG CẤP WI-FI', 13, 'ai', 700)
    s.card(140, 330, 150, 150, 'phone', 'Điện thoại', ['app Android'], 'android')
    s.card(660, 330, 170, 150, 'glasses', 'Kính', ['VisionCare-01'], 'glass')
    s.arrow([(215, 360), (400, 230), (575, 360)], 'android', curve=True)
    s.icon('ble', 396, 295, 'android', 0.55)
    s.text(396, 238, '① BLE · Nordic UART', 13.5, 'android', 700, 'middle', halo='#ffffff')
    s.text(396, 257, 'khi kính chưa có mạng', 12.5, 'muted', 400, 'middle', halo='#ffffff')
    s.arrow([(217, 405), (573, 405)], 'android', '② SoftAP / LAN · POST /wifi/config', at=(395, 395), halo='#ffffff')
    s.mini(300, 560, 200, 76, 'server', 'Server kính', 'wifi_config', 'ai')
    s.arrow([(160, 482), (160, 598), (298, 598)], 'amber', '③ qua server', at=(172, 540), anchor='start', dash=True, halo='#ffffff')
    s.arrow([(502, 598), (660, 598), (660, 482)], 'amber', '/downlink', at=(672, 540), anchor='start', dash=True, halo='#ffffff')
    s.pill(400, 676, 'demo1: đường ③ trả 409 (kênh xuống tắt)', 'red', 12.5)
    s.text(56, 730, 'Kính nhận xong → ghi NVS → khởi động lại → vào mạng mới.', 13, 'ink', 600)

    s.rect(820, 140, 810, 610, 'white')
    s.text(846, 178, 'OTA — KÍNH KÉO VỀ', 13, 'ai', 700)
    top = [('laptop', 'publish_firmware.py', 'bin + version', 'muted'),
           ('server', 'Server kính', 'manifest: version + sha256', 'ai'),
           ('glasses', 'Kính hỏi', 'lúc khởi động · mỗi 6 giờ', 'glass')]
    bot = [('download', 'Tải /firmware/bin', None, 'glass'),
           ('shield', 'Kiểm SHA-256', None, 'glass'),
           ('ota', 'Ghi phân vùng OTA', None, 'glass'),
           ('repeat', 'Khởi động lại', None, 'glass')]
    xs = [900, 1150, 1420]
    for (ic, t, sub, col), x in zip(top, xs):
        c = 'ai' if col == 'muted' else col
        s.icon(ic, x, 260, c, 0.95)
        s.text(x, 320, t, 14.5, 'ink', 700, 'middle')
        s.text(x, 340, sub, 12.5, 'muted', 400, 'middle')
    s.arrow([(938, 260), (1110, 260)], 'line', 'phát hành', at=(1024, 250), halo='#ffffff')
    s.arrow([(1382, 260), (1190, 260)], 'glass', 'GET manifest', at=(1286, 250))
    s.pill(1420, 380, 'hoặc POST /ota/pull (LAN)', 'glass', 12)
    s.arrow([(1420, 400), (1420, 470), (1535, 470), (1535, 520)], 'glass', 'version khác', at=(1478, 460))
    bx = [1535, 1330, 1125, 920]
    for (ic, t, _, col), x in zip(bot, bx):
        s.icon(ic, x, 560, col, 0.95)
        s.text(x, 620, t, 14, 'ink', 700, 'middle')
    for a, b in zip(bx, bx[1:]):
        s.arrow([(a - 38, 560), (b + 40, 560)], 'glass')
    s.text(846, 672, 'So version bằng != chứ không phải > — cố ý, để rollback được bằng cách phát hành bản cũ.', 12.5, 'muted')
    s.text(846, 694, 'Chặn OTA khi vừa bấm nút trong 60 s. Bảng phân vùng phải là min_spiffs — chỉ ghi được qua USB.', 12.5, 'muted')
    s.footer('Nguồn: services/firmware.py, tools/publish_firmware.py, tools/ble_provision.py, CLAUDE.md')
    return s.save('06-wifi-ota.svg')


# ─────────────────────────── 07 · module ───────────────────────────
def d07():
    s = SVG(1660, 880, '07', 'Module trong từng repo',
            'Mỗi cột một khối chạy; mỗi ô một trách nhiệm chính. File nguồn cụ thể nằm trong README mục “Nguồn”.')
    cols = [('glasses', 'Firmware', 'your-eyes-esp32-firmware', 'glass', [
                ('button', 'Nút & cảm biến', 'giữ để nói · 3 nhịp SOS'),
                ('mic', 'Audio hai chiều', 'ADPCM lên · stream về → I2S'),
                ('wifi', 'Kết nối', 'HTTPS · X-Device-Id · X-Turn-Id'),
                ('ota', 'Quản lý', 'BLE · NVS · OTA · /diag/log')]),
            ('server', 'Server kính', 'Sever_test', 'ai', [
                ('wave', 'Nghe & hiểu', 'STT · SetFit → Gemini · router'),
                ('eye', 'Nghiệp vụ ảnh', 'đọc chữ · tiền · tìm đồ · cảnh'),
                ('speaker', 'Giọng nói', 'VieNeu-TTS · stream về kính'),
                ('mail', 'Điều phối thiết bị', 'đệm ảnh · /downlink · firmware')]),
            ('server', 'Server app', 'apps/backend', 'app', [
                ('person', 'Danh tính', 'tài khoản · ghép kính ↔ máy'),
                ('list', 'Operation', 'nhận lệnh · chống lặp · trạng thái'),
                ('bell', 'Worker', 'delivery · timeout · callback'),
                ('db', 'Lưu trữ', 'PostgreSQL · Alembic')]),
            ('phone', 'Android', 'apps/android', 'android', [
                ('phone', 'Giao diện', 'Compose · ghép kính · Wi-Fi'),
                ('fork', 'Thực thi lệnh', 'FCM → Dispatcher → Registry'),
                ('music', 'Tích hợp máy', 'GPS · danh bạ · Spotify · Maps'),
                ('repeat', 'Độ bền', 'SQLite · gửi lại report')])]
    for ci, (ic, name, repo, col, mods) in enumerate(cols):
        x = 30 + ci * 402
        s.rect(x, 140, 385, 690, TINT[col], TINT[col], rx=18)
        s.icon(ic, x + 52, 196, col, 0.9)
        s.text(x + 96, 192, name, 20, col, 700)
        s.text(x + 96, 214, repo, 12.5, 'muted')
        for mi, (mic, t, sub) in enumerate(mods):
            y = 260 + mi * 140
            s.rect(x + 16, y, 353, 120, 'white', 'white', rx=14)
            s.icon(mic, x + 66, y + 60, col, 0.85)
            s.text(x + 112, y + 54, t, 16, 'ink', 700)
            s.text(x + 112, y + 76, sub, 13, 'muted')
    s.footer('Server app và Android nằm chung monorepo app_demo_backend')
    return s.save('07-module.svg')


# ─────────────────────────── index.html ───────────────────────────
FIGS = [
    ('01-tong-quan', 'Toàn cảnh', 'Bốn khối chạy chính và ba loại luồng. Màu mũi tên = loại luồng.'),
    ('02-mot-luot', 'Một lượt', 'Từ lúc giữ nút tới lúc loa phát, kèm dòng thời gian đo thật.'),
    ('03-router', 'Router 6 bước', 'Vì sao “ừ” và “dừng lại” được hiểu đúng giữa cuộc hội thoại.'),
    ('04-hanh-dong', 'Hành động', 'Lệnh xuống qua FCM, kết quả về qua REST; ba ID và phạm vi của chúng.'),
    ('05-kenh-xuong', 'Kênh xuống', 'Kính poll hộp thư; và vì sao bản demo1 phải tắt nó.'),
    ('06-wifi-ota', 'Wi-Fi & OTA', 'Ba đường cấp mạng; OTA do kính kéo về.'),
    ('07-module', 'Module', 'Trách nhiệm của từng repo, đọc theo hàng.'),
]


def html(svgs):
    nav = ''.join(f'<a href="#{f}">{i:02} · {t}</a>' for i, (f, t, _) in enumerate(FIGS, 1))
    secs = ''.join(
        f'<section id="{f}"><figure>{svg}<figcaption><b>{i:02} · {t}.</b> {d} '
        f'<a href="{f}.svg" download>SVG</a> · <a href="{f}.png">PNG</a></figcaption></figure></section>'
        for i, ((f, t, d), svg) in enumerate(zip(FIGS, svgs), 1))
    page = f'''<title>Your Eyes — Kiến trúc</title>
<style>
:root{{--bg:#edf1f7;--card:#fff;--ink:#152840;--muted:#5a6b80;--line:#dbe2ec;--acc:#3859bb}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{--bg:#0f1826;--card:#172234;--ink:#e6ecf5;--muted:#9fb0c5;--line:#2a3a52;--acc:#8fa8ff}}}}
:root[data-theme="dark"]{{--bg:#0f1826;--card:#172234;--ink:#e6ecf5;--muted:#9fb0c5;--line:#2a3a52;--acc:#8fa8ff}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font-family:"Segoe UI",Arial,sans-serif;line-height:1.55;padding-inline:16px}}
header{{max-width:1500px;margin:auto;padding-block:36px 18px}}header small{{color:var(--acc);font-weight:700;letter-spacing:2px;font-size:12px}}
h1{{font-size:clamp(26px,4vw,38px);line-height:1.15;margin:8px 0}}header p{{color:var(--muted);max-width:900px;margin:0}}
nav{{position:sticky;top:0;z-index:5;background:var(--bg);display:flex;gap:8px;flex-wrap:wrap;max-width:1500px;margin:auto;padding-block:10px}}
nav a{{border:1px solid var(--line);background:var(--card);color:var(--ink);padding:6px 12px;border-radius:999px;font-size:13.5px;text-decoration:none}}nav a:hover{{border-color:var(--acc)}}
main{{max-width:1500px;margin:auto;padding-block:8px 40px}}section{{margin-block:18px}}
figure{{margin:0;background:var(--card);border:1px solid var(--line);border-radius:14px;overflow:hidden}}
figure svg{{display:block;width:100%;height:auto;cursor:zoom-in}}figure.big{{overflow-x:auto}}figure.big svg{{width:1660px;max-width:none;cursor:zoom-out}}
figcaption{{padding:12px 18px;color:var(--muted);font-size:14.5px;border-top:1px solid var(--line)}}figcaption b{{color:var(--ink)}}figcaption a{{color:var(--acc)}}
footer{{max-width:1500px;margin:auto;color:var(--muted);font-size:13px;padding-block:0 30px}}footer a{{color:var(--acc)}}
@media print{{@page{{size:A3 landscape;margin:10mm}}body{{background:#fff;padding:0}}header,nav,footer,figcaption{{display:none}}section{{break-after:page;margin:0}}figure{{border:none}}figure svg{{max-height:270mm}}}}
</style>
<header><small>YOUR EYES / VISIONCARE · KIẾN TRÚC</small><h1>Kính cảm nhận · Server hiểu · Điện thoại hành động</h1>
<p>Bảy hình, mỗi hình một cơ chế. Bấm vào hình để xem cỡ thật. Chi tiết, bảng trạng thái và file nguồn nằm trong <a href="README.md">README</a>.</p></header>
<nav>{nav}</nav><main>{secs}</main>
<footer>Sinh bởi <code>build_diagrams.py</code> · {DATE}. Hình là kiến trúc mục tiêu dựa trên mã hiện có; mức độ đã chạy trên phần cứng xem README mục “Đã có gì”.</footer>
<script>document.querySelectorAll('figure').forEach(f=>f.querySelector('svg').addEventListener('click',()=>f.classList.toggle('big')));</script>'''
    (OUT / 'index.html').write_text(page, encoding='utf-8')


if __name__ == '__main__':
    svgs = [d01(), d02(), d03(), d04(), d05(), d06(), d07()]
    html(svgs)
    print(f'Generated {len(svgs)} SVG + index.html')
