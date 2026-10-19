from tools.eval_intent import discordant, is_action_fp, summarize


def test_action_fp_wrong_param():
    # chứa nhau thì đúng; tên khác thì là hành động sai
    assert not is_action_fp("contact_call", "contact_call", {"contact_name": "mẹ"}, {"contact_name": "mẹ vợ"})
    assert is_action_fp("contact_call", "contact_call", {"contact_name": "Nam"}, {"contact_name": "Lan"})
    assert is_action_fp("chat", "music_play", {}, {})
    assert not is_action_fp("chat", "ocr", {}, None)  # không thuộc làn D


def test_gate_moves_fp_to_ask():
    rows = [
        {"id": "1", "gold": "chat", "pred": "music_play", "confidence": 0.3, "seconds": 0.1,
         "variant": "clean", "action_fp": True},
        {"id": "2", "gold": "music_play", "pred": "music_play", "confidence": 0.9, "seconds": 0.1,
         "variant": "clean", "action_fp": False},
    ]
    assert summarize(rows)["action_fp"] == 1
    s = summarize(rows, gate=0.5)
    assert s["action_fp"] == 0 and s["ask_rate"] == 0.5


def test_discordant_mcnemar():
    a = [{"id": str(i), "gold": "x", "pred": "x" if i < 10 else "y"} for i in range(12)]
    b = [{"id": str(i), "gold": "x", "pred": "y" if i < 10 else "x"} for i in range(12)]
    d = discordant(a, b)
    assert (d["a_only"], d["b_only"]) == (10, 2)
    assert abs(d["p_value"] - 0.0386) < 0.001
