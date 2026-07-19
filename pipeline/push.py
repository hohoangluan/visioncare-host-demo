import logging

from pipeline import devices

log = logging.getLogger("push")


def send(device_id: str, action: dict) -> bool:
    """Đẩy action tới mobile app qua FCM.

    Giai đoạn stub: chỉ log payload. Không có token -> trả False.
    """
    token = devices.get_token(device_id)
    if not token:
        log.warning("push: chưa có token cho device_id=%s", device_id)
        return False
    # TODO: gọi FCM/APNs thật (firebase-admin) với token + action.
    log.info("PUSH -> device=%s action=%s", device_id, action)
    return True
