"""Client `cx/gpt-6.1-sol` qua 9router — CHỈ cho công cụ offline trong `tools/`.

Không bao giờ import từ code runtime của server: khoá 9router không được có mặt
trên đường phục vụ. Khoá đọc thẳng từ `SeeVia_system/.env` (tên biến bắt đầu
bằng chữ số nên `os.environ`/dotenv của `config.py` không dùng được) và không
bao giờ được in ra log.

Đo 2026-10-19: `response_format` kiểu json_schema chạy tốt với sol qua 9router
(~3,5 s/lượt, effort low). sol trả một tool call/response và không kèm text khi
dùng `tools`, nên ở đây KHÔNG dùng tools — chỉ `response_format`.

Nhưng `response_format` qua 9router chỉ được tôn trọng LÚC CÓ LÚC KHÔNG (đo
2026-10-19: với schema lồng nhau, sol từng trả mảng trần thay vì object, bỏ trường
bắt buộc, thêm trường lạ). Vì vậy `ask_json` luôn chép schema vào system prompt,
parse khối `{...}` đầu tiên và tự kiểm theo schema; sai thì thử lại.
"""

import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

# VH/tools/intent_gold/sol.py -> parents[3] = SeeVia_system
ENV_PATH = Path(__file__).resolve().parents[3] / ".env"
_RETRIES = 4
_BACKOFF_S = 4.0

_lock = threading.Lock()
STATS = {"calls": 0, "failures": 0}


class SolError(RuntimeError):
    """Hết lượt thử mà sol/9router vẫn không trả được JSON hợp lệ."""


def _env() -> dict[str, str]:
    out: dict[str, str] = {}
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        out[key.strip()] = value.strip().strip("\"'")
    return out


def _config() -> tuple[str, str, str]:
    env = _env()
    try:
        return (env["9ROUTER_API_URL"].rstrip("/"), env["9ROUTER_API_KEY"],
                env["9ROUTER_MODEL"])
    except KeyError as exc:
        raise SolError(f"thiếu {exc.args[0]} trong {ENV_PATH}") from None


def _post(body: dict, timeout: float) -> str:
    """Một lượt chat/completions -> chuỗi nội dung của choice đầu."""
    url, key, model = _config()
    resp = httpx.post(
        f"{url}/chat/completions", json={**body, "model": model},
        headers={"Authorization": f"Bearer {key}"}, timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"] or ""


def _first_json_object(text: str):
    """Khối `{...}` đầu tiên cân ngoặc trong `text` (phòng khi sol kèm lời dẫn)."""
    start = text.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            elif ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        break
        start = text.find("{", start + 1)
    raise ValueError("không có khối JSON")


_TYPES = {"string": str, "boolean": bool, "object": dict, "array": list,
          "integer": int, "number": (int, float), "null": type(None)}


def validate(value, schema: dict, path: str = "$") -> None:
    """Kiểm tra tối thiểu theo schema (type/enum/required/properties/items).

    Không kéo thêm gói `jsonschema` vào venv dùng chung; schema của công cụ này
    chỉ dùng chừng đó từ khoá.
    """
    kinds = schema.get("type")
    if kinds:
        kinds = [kinds] if isinstance(kinds, str) else kinds
        ok = any(
            isinstance(value, _TYPES[k]) and not (k in ("integer", "number")
                                                  and isinstance(value, bool))
            for k in kinds
        )
        if not ok:
            raise ValueError(f"{path}: sai kiểu {type(value).__name__}, cần {kinds}")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{path}: {value!r} ngoài enum")
    if isinstance(value, dict):
        for name in schema.get("required", []):
            if name not in value:
                raise ValueError(f"{path}: thiếu {name}")
        for name, sub in schema.get("properties", {}).items():
            if name in value:
                validate(value[name], sub, f"{path}.{name}")
    if isinstance(value, list) and "items" in schema:
        for i, item in enumerate(value):
            validate(item, schema["items"], f"{path}[{i}]")


def ask_json(system: str, user: str, schema: dict, effort: str = "high",
             timeout: float = 120) -> dict:
    """Hỏi sol, trả dict đã parse và đã kiểm theo `schema`. Thử 4 lần, nghỉ 4 s."""
    system += ("\n\nTrả về DUY NHẤT một đối tượng JSON hợp lệ theo JSON Schema sau, không "
               "kèm chữ nào khác, không bọc trong mảng:\n" + json.dumps(schema, ensure_ascii=False))
    body = {
        "reasoning_effort": effort,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "out", "strict": True, "schema": schema},
        },
    }
    last: Exception | None = None
    for attempt in range(_RETRIES):
        with _lock:
            STATS["calls"] += 1
        try:
            text = _post(body, timeout)
            try:
                obj = json.loads(text)
            except json.JSONDecodeError:
                obj = _first_json_object(text)
            validate(obj, schema)
            return obj
        except Exception as exc:  # noqa: BLE001 - mạng, 5xx, JSON hỏng đều thử lại
            last = exc
            with _lock:
                STATS["failures"] += 1
            if attempt < _RETRIES - 1:
                time.sleep(_BACKOFF_S)
    # Không đưa nguyên `last` vào thông báo: lỗi httpx có thể chứa URL/header.
    raise SolError(f"sol lỗi sau {_RETRIES} lần: {type(last).__name__}")


def ask_many(jobs: list[tuple[str, str, dict]], effort: str,
             concurrency: int = 6) -> list[dict | None]:
    """Chạy nhiều lượt song song (≤ 6, hạn mức sol); lượt hỏng trả `None`."""
    concurrency = max(1, min(concurrency, 6))

    def one(job):
        system, user, schema = job
        try:
            return ask_json(system, user, schema, effort=effort)
        except SolError:
            return None

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        return list(pool.map(one, jobs))
