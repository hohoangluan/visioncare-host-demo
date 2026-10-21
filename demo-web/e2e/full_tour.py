"""Chạy toàn tuyến SeeVia: client.html (kính giả lập) -> VH -> AB -> điện thoại; người dùng xem ở index.html."""
import asyncio, os, sys, json, time

REPO = "/workingspace_aiclub/WorkingSpace/Personal/vannk/SeeVia_system/visioncare-host-demo"
SEEVIA = os.path.dirname(REPO)
sys.path.insert(0, os.path.join(REPO, "demo-web", "e2e"))
import browser_e2e as B

SCR = os.path.join(REPO, 'storage', 'e2e-demo-web', 'tour-2026-10-21')
CMD = lambda h: f"cmd/{h}_v0_clean.wav"
CLIPS = {
    "space": (CMD("874fa909"), "Phía trước mặt tôi đang có những gì"),
    "hazard": (CMD("7c5ed748"), "Quét xem có vật cản gì không"),
    "chat": (CMD("ede5dd89"), "Vịnh hạ long thuộc tỉnh nào vậy kính"),
    "alert_on": (CMD("5348806a"), "Bật cảnh báo vật cản"),
    "alert_off": (CMD("da525622"), "Tắt cảnh báo"),
    "ocr": (CMD("5653b567"), "Đọc tiêu đề báo"),
    "money": (CMD("3e86c8bf"), "Tờ tiền đang cầm là bao nhiêu"),
    "find": (CMD("6279348a"), "Chai nước suối để ở đâu"),
    "music_play": (CMD("02f28662"), "Phát nhạc bolero"),
    "music_up": (CMD("88916421"), "Bật to lên"),
    "music_down": (CMD("c9df1714"), "Vặn nhỏ lại xem"),
    "music_stop": (CMD("faeac088"), "Ngừng nhạc lại"),
    "nav_start": (CMD("5de54613"), "Đưa tôi đến bệnh viện"),
    "nav_stop": (CMD("cd65a871"), "Dừng dẫn đường"),
    "ride_quote": (CMD("48737d98"), "Gọi xe đi sở thú"),
    "ride_confirm": (CMD("dc2b9141"), "Nhận cuốc này"),
    "call": (CMD("836fc553"), "Gọi cho mẹ"),
    "msg": (CMD("3c784899"), "Nhắn cho mẹ là con sắp về"),
    "msg_read": (CMD("e0c34c3f"), "Có ai gửi lời nhắn cho tôi không"),
    "emergency": (CMD("376d4f07"), "Tôi cần cấp cứu"),
    "yes": (os.path.join(SCR, "assets", "yes.wav"), "Đúng"),
}
B.CLIPS.update(CLIPS)  # đường tuyệt đối thì os.path.join bỏ BENCH

OUT = os.path.join(B.STORAGE, "tour-" + time.strftime("%H%M%S"))
os.makedirs(OUT, exist_ok=True)
LOG = []


def say_log(msg):
    print(msg, flush=True)
    LOG.append(msg)


def mjpeg(name, imgs, secs):
    out = os.path.join(B.STORAGE, "assets", f"tour_{name}.mjpeg")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    return B.ffmpeg_mjpeg(imgs, secs, out)


VND = f"{SEEVIA}/evaluations/datas/vnd_kaggle/050000/050000_100.png"
BOTTLE = f"{SEEVIA}/evaluations/datas/vizwiz/val/VizWiz_val_00000686.jpg"
CAMS = {
    "street": lambda: B.cam_file("nav"),
    "trucks": lambda: B.cam_file("trucks"),
    "sign": lambda: B.cam_file("sign"),
    "money": lambda: mjpeg("money", [VND], 4),
    "bottle": lambda: mjpeg("bottle", [BOTTLE], 4),
}


async def last_bubbles(s, n=3):
    return await s.view.evaluate("n=>[...document.querySelectorAll('#history .bubble')].slice(-n).map(b=>b.innerText.replace(/\\s+/g,' ').trim())", n)


async def turn(s, name, clip, wait=6, tail=2.5, shot=True):
    say_log(f"\n▶ [{name}] nói: “{B.CLIPS[clip][1]}”")
    await s.say(clip, tail=tail)
    done = await s.reply_done(60)
    await asyncio.sleep(wait)  # chờ kết quả từ điện thoại / câu live
    heard = await s.heard()
    bub = await last_bubbles(s)
    say_log(f"   server nghe → ý định: {heard}")
    for b in bub:
        say_log(f"   · {b[:220]}")
    say_log(f"   chế độ: {await s.modes()}  | reply_done={done}")
    if shot:
        await B.Report(OUT).shot(s.view, name)


async def phase(title, cam, clips, body):
    say_log(f"\n========== {title} ==========")
    r = B.Report(OUT)
    base = "https://localhost:18443"
    async with B.Session(base, r, CAMS[cam](), clips=clips) as s:
        await s.start_devices()
        await asyncio.sleep(2)
        try:
            await body(s)
        except Exception as e:  # noqa: BLE001
            say_log(f"   !! lỗi pha: {e!r}")
        if s.errors:
            say_log(f"   !! lỗi JS: {s.errors}")
    await asyncio.sleep(3)


async def p_scene(s):
    await turn(s, "01_space", "space")
    await turn(s, "02_hazard", "hazard")
    await turn(s, "03_chat", "chat")


async def p_nav(s):
    await turn(s, "04_alert_on", "alert_on", wait=25)
    await turn(s, "05_alert_off", "alert_off", wait=3)


async def p_ocr_direct(s):
    await turn(s, "06_ocr_direct", "ocr", wait=8)


async def p_ocr_live(s):
    await turn(s, "07_ocr_live", "ocr", wait=20)


async def p_money(s):
    await turn(s, "08_money", "money", wait=6)


async def p_find(s):
    await turn(s, "09_find", "find", wait=6)


async def p_phone(s):
    await turn(s, "10_music_play", "music_play", wait=20)
    await turn(s, "11_music_up", "music_up", wait=10)
    await turn(s, "12_music_down", "music_down", wait=10)
    await turn(s, "13_music_stop", "music_stop", wait=10)
    await turn(s, "14_nav_start", "nav_start", wait=18)
    await turn(s, "15_nav_confirm_yes", "yes", wait=18)  # nếu server hỏi lại "phải không?"
    await turn(s, "16_nav_stop", "nav_stop", wait=12)
    await turn(s, "17_ride_quote", "ride_quote", wait=22)
    await turn(s, "18_ride_confirm", "ride_confirm", wait=22)
    await turn(s, "19_call_mom", "call", wait=15)
    await turn(s, "20_msg_send", "msg", wait=15)
    await turn(s, "21_msg_yes", "yes", wait=15)
    await turn(s, "22_msg_read", "msg_read", wait=12)


async def p_emergency(s):
    await turn(s, "23_emergency", "emergency", wait=40)


async def main():
    only = sys.argv[1:]
    plan = [
        ("A. Cảnh / vật cản / hỏi đáp", "trucks", ["space", "hazard", "chat"], p_scene),
        ("B. Cảnh báo vật cản trực tiếp", "street", ["alert_on", "alert_off"], p_nav),
        ("C. Đọc chữ (ảnh rõ)", "sign", ["ocr"], p_ocr_direct),
        ("D. Đọc chữ trực tiếp (ảnh không chữ)", "trucks", ["ocr"], p_ocr_live),
        ("E. Đọc tiền", "money", ["money"], p_money),
        ("F. Tìm đồ vật", "bottle", ["find"], p_find),
        ("G. Điện thoại: nhạc / dẫn đường / đặt xe / gọi / nhắn", "trucks",
         ["music_play", "music_up", "music_down", "music_stop", "nav_start", "yes", "nav_stop", "ride_quote",
          "ride_confirm", "call", "msg", "msg_read"], p_phone),
        ("H. Khẩn cấp (gọi người thân)", "trucks", ["emergency"], p_emergency),
    ]
    for title, cam, clips, body in plan:
        if only and title[0] not in only:
            continue
        await phase(title, cam, clips, body)
    open(os.path.join(OUT, "tour.log"), "w").write("\n".join(LOG))
    say_log(f"\nẢnh + log: {OUT}")


asyncio.run(main())
