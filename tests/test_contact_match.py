"""T08/D7 — so khớp tên danh bạ thuần hàm, không I/O và không gọi model."""

from handlers.contact_match import format_candidates, norm, phon, rank


def _contact(name: str, tail: str = "456", contact_id: str | None = None) -> dict:
    return {
        "name": name,
        "phone_tail": tail,
        "contact_id": contact_id or f"id-{name}",
    }


def test_norm_ignores_vietnamese_tone_marks():
    assert norm("  Nguyễn, NGUYỆT-Anh! ") == "nguyen nguyet anh"


def test_rank_tone_error_reaches_confirm_threshold():
    decision = rank("Nguyet Anh", [_contact("Nguyệt Anh")])
    assert decision.kind == "confirm"
    assert decision.candidates[0].score >= 88


def test_rank_extra_family_name_reaches_confirm_threshold():
    decision = rank("Nguyệt Anh", [_contact("Nguyễn Nguyệt Anh")])
    assert decision.kind == "confirm"
    assert decision.candidates[0].score >= 88


def test_rank_reversed_tokens_reaches_confirm_threshold():
    decision = rank("Anh Nguyệt", [_contact("Nguyệt Anh")])
    assert decision.kind == "confirm"
    assert decision.candidates[0].score >= 88


def test_phon_rescues_common_asr_consonant_pairs():
    pairs = [
        ("Nan", "Lan"),
        ("Chung", "Trung"),
        ("Xơn", "Sơn"),
        ("Dung", "Giung"),
    ]
    for heard, stored in pairs:
        assert phon(heard) == phon(stored)
        assert rank(heard, [_contact(stored)]).candidates[0].score >= 88


def test_rank_rejects_unrelated_name_below_70_without_confirmation():
    decision = rank("Ngọc Ánh", [_contact("Nguyệt Anh")])
    assert decision.kind == "no_match"
    assert decision.best_score < 70


def test_rank_caps_spoken_candidates_at_three():
    contacts = [_contact(f"Nguyệt Anh {suffix}") for suffix in "ABCDEF"]
    decision = rank("Nguyệt Anh", contacts)
    assert decision.kind == "select"
    assert len(decision.candidates) == 3


def test_duplicate_names_only_expose_three_or_four_digit_tails():
    contacts = [
        {"name": "Mẹ", "phone_number": "+84 901 234 567", "contact_id": "a"},
        {"name": "Mẹ", "phone_number": "***789", "contact_id": "b"},
    ]
    labels = format_candidates(rank("mẹ", contacts).candidates)
    joined = " ".join(labels)
    assert "Mẹ, số đuôi 4567" in joined
    assert "Mẹ, số đuôi 789" in joined
    assert "901 234 567" not in joined


def test_exact_spelling_wins_a_phonetic_tie():
    decision = rank("Sơn", [_contact("Xơn"), _contact("Sơn")])
    assert decision.candidates[0].name == "Sơn"
    assert decision.candidates[0].score > decision.candidates[1].score


def test_empty_and_one_character_queries_are_no_match():
    contacts = [_contact("An")]
    assert rank("", contacts).kind == "no_match"
    assert rank("a", contacts).kind == "no_match"

