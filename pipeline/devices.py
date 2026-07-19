# Map device_id -> fcm_token. In-memory cho prototype.
# TODO: thay bằng DB/Redis khi cần bền + nhiều thiết bị.
_store: dict[str, str] = {}


def register(device_id: str, fcm_token: str, platform: str = "") -> None:
    _store[device_id] = fcm_token


def get_token(device_id: str) -> str | None:
    return _store.get(device_id)
