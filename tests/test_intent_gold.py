"""Công cụ dựng tập gold ý định (tools/intent_gold) — không gọi mạng, không cần GPU.

`sol.ask_json` được thay bằng bản giả: test chỉ kiểm LUẬT của công cụ (chia tách
theo nhóm, đồng thuận nhãn), không kiểm chất lượng sol. Cố ý chỉ hai test này.
"""

from tools.intent_gold import build, sol

VARIANTS = ("clean", "stt_snr20", "stt_snr10", "stt_snr5")
DEVICE = {"music_playing": False, "navigating": False, "alerting": False,
          "ride_quote_pending": False}


def _row(group, variant, label):
    return {
        "id": f"{group}:{variant}", "group": group, "text": f"câu {group} {variant}",
        "source_text": f"câu {group}", "variant": variant, "device": dict(DEVICE),
        "label": label, "ocr_mode": "read", "needs_web": False, "params": {},
        "label_source": "agree", "origin": "eval",
    }


def _rows(labels_per_group):
    return [
        _row(f"g{i}", v, label)
        for i, label in enumerate(labels_per_group) for v in VARIANTS
    ]


def test_split_keeps_groups_together():
    rows = _rows(["chat", "ocr"] * 5)  # 10 group x 4 biến thể = 40 dòng
    assert len(rows) == 40
    dev, test = build.split_groups(rows)
    dev_groups = {r["group"] for r in dev}
    test_groups = {r["group"] for r in test}
    assert dev_groups and test_groups
    assert not dev_groups & test_groups
    assert len(dev) + len(test) == 40
    # mọi biến thể của một câu đi cùng một phía
    for g in test_groups:
        assert sum(r["group"] == g for r in test) == 4


def _item(old="nav_stop", sol_label="nav_stop", gemma="nav_stop"):
    return {
        "id": "q1", "text": "dừng lại", "device": {**DEVICE, "navigating": True},
        "old": old,
        "sol": {"label": sol_label, "ocr_mode": "read", "needs_web": False,
                "params": {}, "reason": "ngữ cảnh"},
        "gemma": None if gemma is None else {"label": gemma, "ocr_mode": "read",
                                               "needs_web": False},
    }


def test_consensus_rules(monkeypatch):
    calls = []

    def fake(system, user, schema, effort="high", timeout=120):
        calls.append(user)
        return reply

    monkeypatch.setattr(sol, "ask_json", fake)

    # cũ = sol = gemma -> agree, không tốn lượt phân xử
    reply = {}
    out = build.consensus(_item())
    assert out["status"] == "agree" and out["label"] == "nav_stop"
    assert calls == []

    # lệch, phân xử ra nhãn rõ -> sol_adjudicated
    reply = {"label": "music_stop", "ocr_mode": "read", "needs_web": False,
             "params": {}, "uncertain": False, "reason": "đang phát nhạc"}
    out = build.consensus(_item(old="nav_stop", sol_label="music_stop", gemma="nav_stop"))
    assert out["status"] == "sol_adjudicated" and out["label"] == "music_stop"
    assert len(calls) == 1
    # lượt phân xử thấy mọi nhãn ứng viên
    assert "nav_stop" in calls[0] and "music_stop" in calls[0]

    # phân xử trả uncertain -> review
    reply = {"label": "chat", "ocr_mode": "read", "needs_web": False, "params": {},
             "uncertain": True, "reason": "mơ hồ thật"}
    out = build.consensus(_item(old="nav_stop", sol_label="chat", gemma="alert_off"))
    assert out["status"] == "uncertain"

    # sol không trả lời được lượt phân xử -> cũng vào review, không đoán
    reply = None
    out = build.consensus(_item(old="nav_stop", sol_label="chat", gemma="alert_off"))
    assert out["status"] == "uncertain"
