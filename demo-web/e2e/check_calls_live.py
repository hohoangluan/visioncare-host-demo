# ruff: noqa
"""Kiểm gọi / nhắn / đọc tin trên stack THẬT (VH 18888 + AB 18001 + "em iu" = relative_sim cổng 18003).

Kính giả lập (WS /v2/session, giọng tổng hợp VieNeu -> ADPCM, đúng nhịp thời gian thực như client.html) dùng TOKEN RIÊNG của
kính (`~/.config/seevia/glasses-123.token`, quyền 600; không in). Dùng lại lớp của `tools/e2e_calls.py` (CallGlasses, Rel,
stream_phase dò tiếng "tách" hai chiều) nhưng KHÔNG dựng stack: gắn vào stack đang chạy.

Điều kiện (xem docs/2026-10-21-ux-khiem-thi/report-G.md): VH đã chạy với VISIONCARE_DEVICE_TOKENS; AB có care_link active "em iu";
relative_sim đang chạy (`~/.local/state/seevia/start_relative_sim.sh`).

    ~/.venvs/seevia/bin/python demo-web/e2e/check_calls_live.py --preflight      # chỉ kiểm điều kiện, không nói gì
    ~/.venvs/seevia/bin/python demo-web/e2e/check_calls_live.py                  # gọi + nhắn + đọc tin
    ~/.venvs/seevia/bin/python demo-web/e2e/check_calls_live.py --only call_em_iu message_em_iu

Ca: call_em_iu ("Gọi em iu": em iu đổ chuông, tự nghe, có khung âm thanh hai chiều, kính cúp, AB state=ended),
message_em_iu ("Nhắn em iu là con về muộn": em iu nhận đúng nội dung, tự trả lời, kính đọc tin trả lời),
read_messages ("Đọc tin nhắn": em iu nhắn lúc kính bận, kính đọc, AB ghi read_at).
KHÔNG có ca khẩn cấp (không gửi SOS thật). Mỗi lần chạy chiếm phiên kính `glasses-123` (đá kính thật nếu đang nối).
"""
import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO), str(REPO / "tools")]
import e2e_calls as EC  # noqa: E402
import e2e_full as base  # noqa: E402

STATE = Path.home() / ".local" / "state" / "seevia"
CONF = Path.home() / ".config" / "seevia"
PHRASES = ["Gọi em iu.", "Nhắn em iu là con về muộn.", "Đọc tin nhắn.", "Đúng.", "Kể cho tôi một câu chuyện cười ngắn."]
ROUND_TRIP_REPLY = "nhan duoc tin"  # auto-reply mặc định của start_relative_sim.sh, bỏ dấu


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class Live:
    def __init__(self, a):
        self.a = a
        acc = load_json(Path(a.accounts))
        self.owner_pub = acc["owner"].get("public_user_id", "")
        self.rel_phone = acc["relative"]["phone"]
        self.rel_name = acc["relative"]["display_name"]
        self.token = Path(a.token_file).read_text(encoding="utf-8").strip()
        self.rel = EC.Rel(a.rel_url, Path(a.rel_log))
        self.plog = base.PhoneLog(None, Path(a.vh_log))
        self.ab_hdr = None

    def ab_owner_headers(self):
        if self.ab_hdr is None:
            acc = load_json(Path(self.a.accounts))
            r = httpx.post(self.a.ab_url + "/api/v1/auth/login", timeout=15,
                           json={"phone_number": acc["owner"]["phone"], "password": acc["owner"]["password"]})
            r.raise_for_status()
            self.ab_hdr = {"Authorization": "Bearer " + r.json()["data"]["access_token"]}
        return self.ab_hdr


def preflight(L: Live) -> list[str]:
    """Danh sách vấn đề (rỗng = sẵn sàng)."""
    a, bad = L.a, []
    try:
        r = httpx.get(a.vh_url + "/health", timeout=5)
        if r.status_code != 200:
            bad.append(f"VH /health = {r.status_code}")
    except Exception as exc:  # noqa: BLE001
        bad.append(f"VH không nối được ({exc.__class__.__name__})")
    try:
        r = httpx.get(a.ab_url + "/health/live", timeout=5)
        if r.status_code != 200:
            bad.append(f"AB /health/live = {r.status_code}")
    except Exception as exc:  # noqa: BLE001
        bad.append(f"AB không nối được ({exc.__class__.__name__})")
    try:
        if httpx.get(a.rel_url + "/health", timeout=5).status_code != 200:
            bad.append("relative_sim không khoẻ")
    except Exception as exc:  # noqa: BLE001
        bad.append(f"relative_sim không nối được ({exc.__class__.__name__}): chạy ~/.local/state/seevia/start_relative_sim.sh")
    if bad:
        return bad
    try:
        links = httpx.get(a.ab_url + "/api/v1/care/links", headers=L.ab_owner_headers(), timeout=10).json()["data"]["links"]
        act = [x for x in links if x["role"] == "owner" and x["status"] == "active" and x["display_name"] == L.rel_name]
        if not act:
            bad.append(f"AB chưa có care_link active '{L.rel_name}' (chạy scripts/live_calls_setup.py invite)")
    except Exception as exc:  # noqa: BLE001
        bad.append(f"AB đăng nhập chủ kính/đọc care_links lỗi ({exc.__class__.__name__})")
    ws_err = asyncio.run(_ws_hello(L))
    if ws_err:
        bad.append(ws_err)
    return bad


async def _ws_hello(L: Live) -> str | None:
    import websockets

    try:
        ws = await websockets.connect(L.a.vh_url.replace("http", "ws", 1) + "/v2/session", max_size=None)
        await ws.send(json.dumps({"t": "hello", "device": L.a.glasses_id, "token": L.token, "fw": "e2e", "accept": "ima_adpcm"}))
        first = json.loads(await asyncio.wait_for(ws.recv(), 15))
        await ws.close()
        if first.get("t") != "hello_ok":
            return f"VH từ chối hello: {first}"
    except Exception as exc:  # noqa: BLE001
        return f"VH từ chối token riêng ({exc!r}): đã restart VH với VISIONCARE_DEVICE_TOKENS chưa?"
    return None


# ───────────────────────────── ca ─────────────────────────────

async def sc_call_em_iu(c: EC.Ctx, L: Live):
    g, rel, phone = c.g, c.rel, L.rel_phone
    rel.behave({phone: EC.answer(1.0)})
    m0, base_idx = rel.mark(), len(g.events)
    t = await EC.utter(c, "Gọi em iu.")
    r = EC.R("call_em_iu", False)
    ring = await rel.wait(m0, 25, "push", user=phone, type="call_incoming")
    if ring is None:
        r["notes"] = f"em iu không nhận chuông (say: {g.says(base_idx)})"
        return r
    r["ring_ms"] = EC.ms(ring["wall"] - t.release_wall)
    ans = await rel.wait(m0, 10, "answer_http", user=phone)
    act = await g.wait_state("active", 10, base_idx)
    if ans is None or act is None:
        r["notes"] = f"không nghe máy/không active (say: {g.says(base_idx)})"
        return r
    call_id = ans["call_id"]
    r["answer_to_active_ms"] = EC.ms(act["wall"] - ans["t_send"])
    sm, problems = await EC.stream_phase(c, base_idx, phone, call_id, "glasses")
    r.update(sm)
    if sm.get("ended_reason") not in ("glasses_hangup", None):
        problems.append(f"ended reason={sm.get('ended_reason')}")
    await asyncio.sleep(0.5)
    await EC.check_ab_state(c, phone, call_id, "ended", problems)
    r["pass"], r["notes"] = not problems, "; ".join(problems) or "gọi em iu -> chuông -> tự nghe -> tiếng hai chiều -> kính cúp -> AB ended"
    return r


async def sc_message_em_iu(c: EC.Ctx, L: Live):
    g, rel, phone = c.g, c.rel, L.rel_phone
    rel.behave({phone: {"incoming": "ignore"}})
    m0, base_idx = rel.mark(), len(g.events)
    t = await EC.utter(c, "Nhắn em iu là con về muộn.")
    r = EC.R("message_em_iu", False, first_audio_ms=t.ms("first_audio"))
    msg = await rel.wait(m0, 25, "push", user=phone, type="message_in")
    if msg is None:
        r["notes"] = f"em iu không nhận tin (say: {g.says(base_idx)})"
        return r
    r["message_ms"] = EC.ms(msg["wall"] - t.release_wall)
    text = msg.get("text") or ""
    problems = [] if "muon" in EC.strip_accents(text) else [f"tin tới em iu thiếu 'muộn': {text!r}"]
    # em iu tự trả lời -> kính phải đọc
    say = await g.wait_say(ROUND_TRIP_REPLY, 30, base_idx)
    if say is None:
        problems.append(f"kính không đọc tin trả lời của em iu (say: {g.says(base_idx)})")
    else:
        r["reply_read_ms"] = EC.ms(say["wall"] - msg["wall"])
    r["pass"] = not problems
    r["notes"] = "; ".join(problems) or f"tin tới em iu: {text!r}; trả lời đã được kính đọc: {say['f'].get('text', '')!r}"
    return r


async def sc_read_messages(c: EC.Ctx, L: Live):
    g, rel, phone = c.g, c.rel, L.rel_phone
    rel.behave({phone: {"incoming": "ignore", "auto_reply": None}})  # tắt tự trả lời để khỏi nhiễu
    base_idx = len(g.events)
    body = "Anh ăn cơm chưa, em để phần nhé."
    t = await g.say("Kể cho tôi một câu chuyện cười ngắn.", wait_end=False)  # kính bận
    sent = rel.ctl("/ctl/message", {"user": phone, "owner_user_id": L.owner_pub, "text": body})
    r = EC.R("read_messages", False)
    if t.error or sent.get("http") != 200:
        r["notes"] = f"lượt chat lỗi {t.error} / gửi tin {sent.get('http')}"
        return r
    await g.wait_for(lambda e: e["k"] == "json" and e["f"].get("t") == "reply_end" and e["f"].get("turn") == t.tid, 40, base_idx)
    # kính rảnh: nếu tự đọc thì xong, nếu chưa thì nói "Đọc tin nhắn."
    say = await g.wait_say("em iu nhắn", 12, base_idx)
    how = "tự đọc sau reply_end"
    if say is None:
        await EC.utter(c, "Đọc tin nhắn.")
        say = await g.wait_say("em iu nhắn", 25, base_idx)
        how = "đọc theo lệnh 'Đọc tin nhắn'"
    if say is None:
        r["notes"] = f"kính không đọc tin của em iu (say: {g.says(base_idx)})"
        return r
    problems = []
    said = say["f"].get("text", "")
    if "an com" not in EC.strip_accents(said):
        problems.append(f"nội dung đọc lạ: {said!r}")
    item, end = None, time.time() + 12
    while time.time() < end:
        h = rel.ctl("/ctl/history", {"user": phone, "owner_user_id": L.owner_pub})
        item = next((m for m in h.get("messages", []) if "ăn cơm" in m["text"]), None)
        if item and item.get("read_at"):
            break
        await asyncio.sleep(0.4)
    if not (item and item.get("read_at")):
        problems.append("AB không ghi read_at")
    r["pass"], r["notes"] = not problems, "; ".join(problems) or f"{how}: {said!r}; AB read_at có"
    return r


SCENARIOS = {"call_em_iu": sc_call_em_iu, "message_em_iu": sc_message_em_iu, "read_messages": sc_read_messages}


async def run(L: Live, only):
    a = L.a
    audio_fn = base.make_audio_fn(Path(a.cache))
    for text in PHRASES:
        audio_fn(text)  # tổng hợp trước (cache); lần sau không cần GPU/TTS
    results = []
    for name in only or list(SCENARIOS):
        g = EC.CallGlasses(a.vh_url, L.token, audio_fn, a.glasses_id)
        await g.connect()
        await g.ws.send(json.dumps({"t": "cancel"}))
        await asyncio.sleep(0.8)
        c = EC.Ctx(g, L.rel, L.plog, a, L.owner_pub, None)
        L.rel.behave({L.rel_phone: {"auto_reply": a.auto_reply}} if name != "read_messages" else {})
        t0 = time.time()
        try:
            r = await asyncio.wait_for(SCENARIOS[name](c, L), 150)
        except Exception as exc:  # noqa: BLE001
            r = EC.R(name, False, f"ngoại lệ: {exc!r}")
        r["secs"] = round(time.time() - t0, 1)
        results.append(r)
        print(f"[{'PASS' if r['pass'] else 'FAIL'}] {r['name']}: {r['notes']}  ({r['secs']} s)", flush=True)
        g.stop_mic()
        try:
            await g.close()
        except Exception:  # noqa: BLE001
            pass
        await asyncio.sleep(2.0)
    L.rel.behave({L.rel_phone: {"auto_reply": a.auto_reply}})
    return results


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--only", nargs="*", choices=list(SCENARIOS))
    ap.add_argument("--preflight", action="store_true", help="chỉ kiểm điều kiện (không nói, không cần GPU)")
    ap.add_argument("--vh-url", default="http://127.0.0.1:18888")
    ap.add_argument("--ab-url", default="http://127.0.0.1:18001")
    ap.add_argument("--rel-url", default="http://127.0.0.1:18003")
    ap.add_argument("--rel-log", default=str(STATE / "relative_sim.jsonl"))
    ap.add_argument("--vh-log", default=str(STATE / "vh.log"))
    ap.add_argument("--accounts", default=str(CONF / "live_accounts.json"))
    ap.add_argument("--token-file", default=str(CONF / "glasses-123.token"))
    ap.add_argument("--glasses-id", default="glasses-123")
    ap.add_argument("--auto-reply", default="Em nhận được tin rồi, anh về cẩn thận nhé.",
                    help="câu em iu tự trả lời (đặt lại sau mỗi ca); phải chứa 'nhận được tin' cho ca message_em_iu")
    ap.add_argument("--cache", default=str(REPO / "tools" / "board_audio" / "e2e"))
    ap.add_argument("--json-out")
    ap.add_argument("--gpu", default=None, help="CUDA_VISIBLE_DEVICES cho TTS khi cần tổng hợp clip mới")
    args = ap.parse_args()
    if args.gpu is not None:
        os.environ["CUDA_VISIBLE_DEVICES"] = args.gpu
    L = Live(args)
    bad = preflight(L)
    if bad:
        print("CHƯA SẴN SÀNG:\n - " + "\n - ".join(bad))
        sys.exit(2)
    print("preflight OK: VH, AB, relative_sim, care_link em iu, token riêng được VH nhận")
    if args.preflight:
        return
    results = asyncio.run(run(L, args.only))
    print("\n" + EC.table(results))
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    sys.exit(0 if all(r["pass"] for r in results) else 1)


if __name__ == "__main__":
    main()
