"""So khớp tên danh bạ cho T08/D7.

Module này cố ý thuần hàm: không đọc danh bạ, không gọi mạng và không giữ cache.
P1 sẽ chỉ cần đưa danh sách contact vào :func:`rank` khi app hỗ trợ
``contact_list``.
"""

from collections import Counter
from dataclasses import dataclass
import re
import unicodedata
from collections.abc import Iterable, Mapping

from rapidfuzz import fuzz


CONFIRM_SCORE = 88.0
SELECT_SCORE = 70.0
CONFIRM_MARGIN = 8.0
MAX_SPOKEN_CANDIDATES = 3


def norm(value: str) -> str:
    """Tầng 1: chữ thường, bỏ dấu thanh và dấu câu, gộp khoảng trắng."""
    text = unicodedata.normalize("NFD", str(value or "").lower())
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return " ".join(text.split())


def phon(value: str) -> str:
    """Tầng 2: gộp các cặp âm tiếng Việt mà ASR thường nghe lẫn.

    Digraph luôn được thay trước ký tự đơn. Các marker viết hoa không xuất hiện
    trong :func:`norm`, nên những phép thay sau không ăn lại kết quả trước.
    """
    text = norm(value)
    text = re.sub(r"tr|ch", "C", text)
    text = re.sub(r"ng|nh|n|l", "N", text)
    text = re.sub(r"gi|d|r", "D", text)
    text = re.sub(r"s|x", "S", text)
    # Sau NFD + bỏ combining, iê/i thành ie/i và ươ/ư thành uo/u.
    text = re.sub(r"ie|i", "I", text)
    text = re.sub(r"uo|u", "U", text)
    return text


def _phone_tail(contact: Mapping) -> str | None:
    raw = contact.get("phone_tail") or contact.get("phone_number") or ""
    digits = "".join(char for char in str(raw) if char.isdigit())
    if len(digits) >= 4:
        return digits[-4:]
    if len(digits) == 3:
        return digits
    return None


@dataclass(frozen=True)
class ContactCandidate:
    name: str
    contact_id: str | None
    phone_tail: str | None
    score: float
    spelling_score: float
    source_index: int

    def as_pending(self) -> dict:
        """Bản tối thiểu an toàn để giữ trong pending và gửi lại handler."""
        data = {"contact_name": self.name}
        if self.contact_id:
            data["contact_id"] = self.contact_id
        if self.phone_tail:
            data["phone_tail"] = self.phone_tail
        return data


@dataclass(frozen=True)
class MatchDecision:
    kind: str  # "confirm" | "select" | "no_match"
    candidates: tuple[ContactCandidate, ...]
    best_score: float
    margin: float


def _candidate(query: str, contact: Mapping, index: int) -> ContactCandidate | None:
    name = str(contact.get("name") or contact.get("contact_name") or "").strip()
    if not name:
        return None
    spelling = float(fuzz.WRatio(norm(query), norm(name)))
    phonetic = 0.95 * float(fuzz.WRatio(phon(query), phon(name)))
    score = max(spelling, phonetic)
    raw_id = contact.get("contact_id")
    return ContactCandidate(
        name=name,
        contact_id=str(raw_id) if raw_id not in (None, "") else None,
        phone_tail=_phone_tail(contact),
        score=round(score, 3),
        spelling_score=round(spelling, 3),
        source_index=index,
    )


def rank(query: str, contacts: Iterable[Mapping]) -> MatchDecision:
    """Xếp hạng contact và quyết định confirm/select/no_match theo D7."""
    normalized_query = norm(query)
    if len(normalized_query) < 2:
        return MatchDecision("no_match", (), 0.0, 0.0)

    scored = [
        candidate
        for index, contact in enumerate(contacts)
        if (candidate := _candidate(query, contact, index)) is not None
    ]
    scored.sort(key=lambda item: (-item.score, -item.spelling_score, item.source_index))
    if not scored:
        return MatchDecision("no_match", (), 0.0, 0.0)

    best = scored[0].score
    second = scored[1].score if len(scored) > 1 else 0.0
    margin = best - second if len(scored) > 1 else 100.0
    top = tuple(scored[:MAX_SPOKEN_CANDIDATES])

    if best < SELECT_SCORE:
        return MatchDecision("no_match", top, best, margin)
    if best >= CONFIRM_SCORE and margin >= CONFIRM_MARGIN:
        return MatchDecision("confirm", top, best, margin)
    return MatchDecision("select", top, best, margin)


def format_candidates(candidates: Iterable[ContactCandidate]) -> tuple[str, ...]:
    """Tên để đọc lên; chỉ thêm đuôi 3–4 số khi tên hiển thị trùng hệt."""
    candidates = tuple(candidates)
    counts = Counter(norm(candidate.name) for candidate in candidates)
    labels = []
    for candidate in candidates:
        if counts[norm(candidate.name)] > 1 and candidate.phone_tail:
            labels.append(f"{candidate.name}, số đuôi {candidate.phone_tail}")
        else:
            labels.append(candidate.name)
    return tuple(labels)


def sanitize_candidates(
    contacts: Iterable[Mapping], limit: int = MAX_SPOKEN_CANDIDATES
) -> tuple[ContactCandidate, ...]:
    """Giữ tên/id/đuôi số của ứng viên host trả về, loại số điện thoại đầy đủ."""
    sanitized = []
    for index, contact in enumerate(contacts):
        name = str(contact.get("name") or contact.get("contact_name") or "").strip()
        if not name:
            continue
        raw_id = contact.get("contact_id")
        sanitized.append(
            ContactCandidate(
                name=name,
                contact_id=str(raw_id) if raw_id not in (None, "") else None,
                phone_tail=_phone_tail(contact),
                score=0.0,
                spelling_score=0.0,
                source_index=index,
            )
        )
        if len(sanitized) >= limit:
            break
    return tuple(sanitized)


def choose_candidate(query: str, candidates: Iterable[Mapping]) -> dict | None:
    """Chọn một ứng viên bằng tên khi đủ chắc; trả bản pending đã khử số đầy đủ."""
    decision = rank(query, candidates)
    if decision.kind == "confirm" and decision.candidates:
        return decision.candidates[0].as_pending()
    if decision.kind == "select" and len(decision.candidates) == 1:
        return decision.candidates[0].as_pending()
    return None
