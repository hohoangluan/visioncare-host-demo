"""Trang chấm tay 50 mẫu C4 (VizWiz) — có ảnh. python -m bench.handcheck_page [build|serve] [--port 18765]

build: đọc results/vqa_vizwiz/handcheck_50.csv + ảnh datas/vizwiz/val → results/vqa_vizwiz/handcheck_50.html (tự chứa, ảnh base64).
serve: build rồi phục vụ trang ở http://127.0.0.1:PORT/?t=<token> (VS Code tự chuyển tiếp cổng). Mỗi lần chấm, trang tự POST
       /save → ghi results/vqa_vizwiz/handcheck_50_human.csv + điền lại 3 cột human_* trong handcheck_50.csv.
Mở file .html trực tiếp (không serve) vẫn chấm được: nút "Tải CSV" tải file về, chép lại vào results/vqa_vizwiz/.

Chấm MÙ: trang không hiện llm_refused / llm_matches / llm_vqa_acc / answerable_gt. Tiêu chí giống hệt BRIEF của Codex
(results/vqa_vizwiz/codex_judge/BRIEF.md) để so được Người – Gemma – Codex.
"""

import argparse
import base64
import csv
import http.server
import io
import json
import os
import secrets

from PIL import Image, ImageOps

EVAL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(EVAL_DIR, "results", "vqa_vizwiz")
SRC_CSV = os.path.join(OUT_DIR, "handcheck_50.csv")
HUMAN_CSV = os.path.join(OUT_DIR, "handcheck_50_human.csv")
HTML = os.path.join(OUT_DIR, "handcheck_50.html")
IMG_DIR = os.path.join(EVAL_DIR, "datas", "vizwiz", "val")
TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "handcheck_page.html")
HUMAN_COLS = ["image", "human_refused", "human_matches", "human_n_match", "human_hallucination",
              "human_image_answerable", "human_note"]
MAX_SIDE, JPEG_Q = 1024, 82


def is_unans(a: str) -> bool:
    a = a.strip().lower()
    return a == "unanswerable" or a.startswith("quality issues")


def read_csv(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def thumb(path: str) -> str:
    im = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    im.thumbnail((MAX_SIDE, MAX_SIDE))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=JPEG_Q)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def build() -> None:
    prev = {r["image"]: r for r in read_csv(HUMAN_CSV)}
    items = []
    for r in read_csv(SRC_CSV):
        answers = []
        for part in r["gt_answers_en"].split(" | "):
            i, a = part.split(":", 1)
            answers.append({"i": int(i), "a": a, "unans": is_unans(a)})
        h = prev.get(r["image"], {})
        items.append({"image": r["image"], "q_vi": r["question_vi"], "q_en": r["question_en"], "answer": r["answer_vi"],
                      "answers": answers, "img": thumb(os.path.join(IMG_DIR, r["image"])),
                      "saved": {k: h.get(k, "") for k in HUMAN_COLS[1:]}})
    html = open(TEMPLATE, encoding="utf-8").read().replace("/*__DATA__*/[]", json.dumps(items, ensure_ascii=False))
    with open(HTML, "w", encoding="utf-8") as f:
        f.write(html)
        f.flush(); os.fsync(f.fileno())
    print("ghi", HTML, f"{os.path.getsize(HTML) / 1e6:.1f} MB,", len(items), "mẫu,", len(prev), "mẫu đã chấm trước")


def save(rows: list[dict]) -> int:
    known = {r["image"] for r in read_csv(SRC_CSV)}
    clean = []
    for r in rows:
        if r.get("image") not in known:
            continue
        clean.append({k: str(r.get(k, "")).replace("\n", " ")[:500] for k in HUMAN_COLS})
    tmp = HUMAN_CSV + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=HUMAN_COLS)
        w.writeheader(); w.writerows(clean)
        f.flush(); os.fsync(f.fileno())
    os.replace(tmp, HUMAN_CSV)
    # Điền 3 cột người chấm trong handcheck_50.csv (định dạng METRICS/VQA.md: refused 0/1, n_match, note)
    by = {r["image"]: r for r in clean}
    src = read_csv(SRC_CSV)
    for r in src:
        h = by.get(r["image"])
        if h:
            r["human_refused"], r["human_n_match"], r["human_note"] = h["human_refused"], h["human_n_match"], h["human_note"]
    with open(SRC_CSV + ".tmp", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(src[0].keys()))
        w.writeheader(); w.writerows(src)
        f.flush(); os.fsync(f.fileno())
    os.replace(SRC_CSV + ".tmp", SRC_CSV)
    return len(clean)


def serve(port: int) -> None:
    token = secrets.token_urlsafe(12)

    class H(http.server.BaseHTTPRequestHandler):
        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path.split("?")[0] != "/":
                return self._send(404, b"not found", "text/plain")
            self._send(200, open(HTML, "rb").read(), "text/html; charset=utf-8")

        def do_POST(self):
            if self.path != "/save" or self.headers.get("X-Token") != token:
                return self._send(403, b"forbidden", "text/plain")
            n = int(self.headers.get("Content-Length", 0))
            if n > 2_000_000:
                return self._send(413, b"too large", "text/plain")
            try:
                k = save(json.loads(self.rfile.read(n))["rows"])
            except (ValueError, KeyError, TypeError) as e:
                return self._send(400, str(e).encode(), "text/plain")
            self._send(200, json.dumps({"saved": k}).encode(), "application/json")

        def log_message(self, *a):
            pass

    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), H)
    print(f"mở: http://127.0.0.1:{port}/?t={token}  (Ctrl+C để dừng; kết quả ghi {HUMAN_CSV})", flush=True)
    httpd.serve_forever()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", default="serve", choices=["build", "serve"])
    ap.add_argument("--port", type=int, default=18765)
    a = ap.parse_args()
    build()
    if a.cmd == "serve":
        serve(a.port)


if __name__ == "__main__":
    main()
