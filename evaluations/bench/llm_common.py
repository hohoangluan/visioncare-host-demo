"""Phần dùng chung của gói L (LLM nhìn ảnh): gọi tuần tự + đo TTFT, cache theo id mẫu, chuẩn hoá chữ, phát hiện từ chối.

Gọi `common.setup(gpu=False)` TRƯỚC khi import module này (cần VH trong sys.path).
"""

import asyncio
import hashlib
import io
import json
import os
import re
import sys
import time
import unicodedata
from collections import Counter

import numpy as np

from bench import common

# ---------------------------------------------------------------- văn bản


def nfc_lower(s: str) -> str:
    return unicodedata.normalize("NFC", s or "").lower()


def strip_punct(s: str) -> str:
    """NFC, chữ thường, dấu câu/ký hiệu -> khoảng trắng, gộp khoảng trắng. GIỮ dấu tiếng Việt."""
    s = nfc_lower(s)
    s = "".join(" " if unicodedata.category(c)[0] in "PS" else c for c in s)
    return " ".join(s.split())


def words(s: str) -> list[str]:
    return strip_punct(s).split()


_NUM_RE = re.compile(r"\d+(?:[.,]\d{3})*")


def digit_tokens(s: str) -> list[str]:
    """Chuỗi chữ số: nhóm phân nghìn (`.`/`,` + đúng 3 chữ số) được gộp rồi bỏ dấu; dấu khác tách chuỗi."""
    return [re.sub(r"[.,]", "", m) for m in _NUM_RE.findall(s or "")]


def lev(a: str, b: str) -> int:
    from rapidfuzz.distance import Levenshtein
    return Levenshtein.distance(a, b)


_REFUSE_RE = re.compile(
    r"không\s+(?:thấy|nhìn\s+thấy|đọc|rõ|nhận\s+ra|xác\s+định|tìm\s+thấy|có\s+thông\s+tin|có\s+chữ|biết)|"
    r"chụp\s+lại|không\s+chắc|khó\s+đọc|quá\s+mờ|không\s+đủ\s+(?:rõ|thông\s+tin)|không\s+có\s+chữ|"
    r"không\s+có\s+thông\s+tin|không\s+trả\s+lời|không\s+thể")


def is_refusal(text: str, maxlen: int = 160) -> bool:
    """Câu từ chối/'không đọc chắc': sentinel KHONG_CO_CHU, câu `_NO_TEXT` của VH, hoặc câu NGẮN có mẫu từ chối."""
    t = nfc_lower(text).strip()
    if not t:
        return True
    if "khong_co_chu" in t:
        return True
    return len(t) <= maxlen and bool(_REFUSE_RE.search(t))


def to_jpeg(data: bytes, quality: int = 95) -> bytes:
    """Kính gửi JPEG: ảnh đã là JPEG thì giữ nguyên, còn lại mã hoá lại."""
    from PIL import Image
    img = Image.open(io.BytesIO(data))
    if img.format == "JPEG":
        return data
    out = io.BytesIO()
    img.convert("RGB").save(out, format="JPEG", quality=quality)
    return out.getvalue()


# ---------------------------------------------------------------- thống kê


def ci_entry(values, stat=np.mean, n: int = 1000) -> dict:
    v, lo, hi = common.bootstrap_ci(values, stat=stat, n=n)
    return {"value": v, "ci": [lo, hi], "n": int(len(values))}


def ratio_stat(a):
    """a: (mẫu × 2) = [tử, mẫu] -> tổng tử / tổng mẫu."""
    d = a[:, 1].sum()
    return float(a[:, 0].sum() / d) if d else float("nan")


# ---------------------------------------------------------------- cache + gọi tuần tự


def cfg_hash(parts: dict) -> str:
    """Băm mọi thứ ảnh hưởng đầu ra (prompt, model, cỡ ảnh...) — đổi thì cache cũ không dùng lại."""
    import config
    base = {"model": config.LLM_MODEL, "ocr_side": config.LLM_OCR_IMAGE_MAX_SIDE,
            "llm_side": config.LLM_IMAGE_MAX_SIDE, "first_words": config.FIRST_SENTENCE_MAX_WORDS}
    blob = json.dumps({**base, **parts}, sort_keys=True, ensure_ascii=False)
    return hashlib.md5(blob.encode()).hexdigest()[:12]


class Cache:
    """results/<task>/<name>.jsonl — mỗi dòng {key, cfg, ...}; chỉ nhận dòng cùng cfg. Ghi nối + fsync (NFS)."""

    def __init__(self, task: str, cfg: str, name: str = "cache.jsonl"):
        self.dir = os.path.join(common.RESULTS, task)
        os.makedirs(self.dir, exist_ok=True)
        # BENCH_CACHE_TAG: lượt xác nhận cần gọi MỚI toàn bộ (khoá cache không băm đường code) -> file cache riêng, cache cũ giữ nguyên.
        tag = os.environ.get("BENCH_CACHE_TAG")
        self.path = os.path.join(self.dir, f"{tag}_{name}" if tag else name)
        self.cfg = cfg
        self.data: dict[str, dict] = {}
        if os.path.exists(self.path):
            with open(self.path, encoding="utf-8") as f:
                for line in f:
                    try:
                        e = json.loads(line)
                    except ValueError:
                        continue  # dòng cuối bị cắt
                    if e.get("cfg") == cfg:
                        self.data[e["key"]] = e

    def get(self, key: str) -> dict | None:
        return self.data.get(key)

    def put(self, key: str, entry: dict) -> None:
        entry = {**entry, "key": key, "cfg": self.cfg}
        self.data[key] = entry
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())


async def timed_stream(factory, retries: int = 2) -> dict:
    """Chạy một async-generator (spoken/answer) tới hết. Trả {text, ttft_ms, total_ms, attempts} hoặc {error,...}.
    TTFT = mảnh đầu tiên ra khỏi generator (lúc TTS có thể bắt đầu). Lỗi mạng: thử lại `retries` lần."""
    err = None
    for attempt in range(retries + 1):
        t0 = time.perf_counter()
        ttft, parts = None, []
        try:
            async for piece in factory():
                if ttft is None:
                    ttft = (time.perf_counter() - t0) * 1000
                parts.append(piece)
            return {"text": "".join(parts).strip(), "ttft_ms": ttft,
                    "total_ms": (time.perf_counter() - t0) * 1000, "attempts": attempt + 1}
        except Exception as exc:  # noqa: BLE001 — LLMError/httpx/timeout: ghi lại, thử tiếp
            err = repr(exc)[:300]
            await asyncio.sleep(1.0 + attempt)
    return {"text": "", "ttft_ms": None, "total_ms": None, "attempts": retries + 1, "error": err}


async def run_items(items, key_fn, factory_fn, cache: Cache, tag: str = "") -> dict[str, dict]:
    """Tuần tự từng mẫu: có trong cache thì dùng (kèm độ trễ đã đo), không thì gọi LLM rồi cache (trừ khi lỗi)."""
    out: dict[str, dict] = {}
    for i, it in enumerate(items):
        key = key_fn(it)
        hit = cache.get(key)
        if hit is not None:
            out[key] = {**hit, "cached": True}
        else:
            r = await timed_stream(lambda it=it: factory_fn(it))
            if "error" not in r:
                cache.put(key, r)
            out[key] = {**r, "key": key, "cached": False}
        r = out[key]
        print(f"[{tag}] {i + 1}/{len(items)} {key} {'cache' if r['cached'] else 'goi'} "
              f"ttft={r.get('ttft_ms') and round(r['ttft_ms'])}ms err={r.get('error')}", file=sys.stderr, flush=True)
    return out


# ---------------------------------------------------------------- prompt "hỏi về chữ"

_ASK_Q = {"q": ""}


def ask_prompt(question: str) -> str:
    """Prompt 'hỏi về chữ' của bàn đo. VH CHƯA có đường production riêng (xem llm_NOTES.md): dựng từ `prompts._COMMON`
    + câu hỏi, chạy qua đúng `read_image` (resize 1600/q90, max_tokens 1024, temperature 0, xử lý sentinel)."""
    from models.ocr import prompts
    return prompts._COMMON + (
        f'Người dùng hỏi về chữ trong ảnh: "{question}"\n'
        "Chỉ trả lời đúng câu hỏi đó, bằng một câu tiếng Việt ngắn, dễ nghe. Giữ ĐÚNG mọi con số, ngày tháng, "
        "tên riêng như trong ảnh, không làm tròn, không đoán. Nếu thông tin cần tìm không có hoặc không đọc chắc "
        'thì nói thẳng: "Không đọc chắc, vui lòng chụp lại."'
    )


def ASK_TEMPLATE_FOR_HASH() -> str:
    return ask_prompt("<Q>")


def install_ask_hook() -> None:
    """Cho `ocr_live.read_image(jpeg, "ask", dev)` dùng `ask_prompt(câu hỏi hiện tại)`; mọi mode khác giữ nguyên."""
    from lanes import ocr_live
    if getattr(ocr_live, "_bench_hooked", False):
        return
    orig = ocr_live._prompt

    def _prompt(mode: str) -> str:
        return ask_prompt(_ASK_Q["q"]) if mode == "ask" else orig(mode)

    ocr_live._prompt = _prompt
    ocr_live._bench_hooked = True


def set_ocr_tiles(n: int, cfg_parts: dict) -> None:
    """Bật OCR_TILES của VH (nhánh ocr-tien, 2026-10-21) cho cả tiến trình bench; ghi vào cfg để cache tách riêng.
    n = 0 thì ép tắt (VH có cờ) — cfg giữ nguyên như trước để dùng lại cache baseline."""
    import config
    if hasattr(config, "OCR_TILES"):
        config.OCR_TILES = n
    elif n:
        raise SystemExit("VH này không có OCR_TILES — đặt SEEVIA_VH_DIR tới worktree vh-ocr")
    if n:
        from lanes import ocr_live
        cfg_parts.update(ocr_tiles=n, tiles_note=ocr_live._TILES_NOTE)


def ask_spoken(jpeg: bytes, question: str):
    """async-generator production: `spoken(jpeg, "ask", ...)` với câu hỏi `question`."""
    from lanes import ocr_live
    install_ask_hook()
    _ASK_Q["q"] = question  # gọi tuần tự nên biến toàn cục an toàn
    return ocr_live.spoken(jpeg, "ask", "bench")


def new_loop_run(coro):
    """asyncio.run + đóng client LLM cuối lượt."""
    async def wrapper():
        from models import llm
        try:
            return await coro
        finally:
            await llm.close()
    return asyncio.run(wrapper())
