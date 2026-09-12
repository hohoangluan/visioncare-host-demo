"""Voice controls available only while an incoming call is ringing."""

from collections.abc import Iterator

from handlers import action_flow


_ANSWER_ACK = "Đang nghe máy."
_REJECT_ACK = "Đã từ chối cuộc gọi."
_CONTROL_FAILURE = "Điện thoại chưa xử lý được cuộc gọi."

STATIC_SPEECH: tuple[str, ...] = (_ANSWER_ACK, _REJECT_ACK, _CONTROL_FAILURE)


def handle_answer(
    image: bytes | None, command_text: str, params: dict | None = None
) -> Iterator[str]:
    del image, command_text, params
    yield from action_flow.run_action(
        "call_answer",
        "api/v1/service/call/answer",
        {},
        ack=_ANSWER_ACK,
        failure=_CONTROL_FAILURE,
    )


def handle_reject(
    image: bytes | None, command_text: str, params: dict | None = None
) -> Iterator[str]:
    del image, command_text, params
    yield from action_flow.run_action(
        "call_reject",
        "api/v1/service/call/reject",
        {},
        ack=_REJECT_ACK,
        failure=_CONTROL_FAILURE,
    )
