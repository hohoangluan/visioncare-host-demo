import logging

from pipeline import push, devices


def test_send_returns_true_when_token_registered():
    """Verify send returns True when a device has a registered token."""
    devices.register("device-alpha", "tok-alpha-secret", "android")
    assert push.send("device-alpha", {"type": "call", "name": "mẹ"}) is True


def test_send_returns_true_for_multiple_different_devices():
    """Verify send returns True for different registered devices with different tokens."""
    devices.register("device-beta", "tok-beta-secret", "android")
    devices.register("device-gamma", "tok-gamma-secret", "ios")
    assert push.send("device-beta", {"type": "call", "name": "ba"}) is True
    assert push.send("device-gamma", {"type": "sms", "msg": "hello"}) is True


def test_send_returns_false_when_no_token():
    """Verify send returns False for an unregistered device."""
    assert push.send("no-such-device", {"type": "call", "name": "x"}) is False


def test_token_not_logged_in_output(caplog):
    """Verify the FCM token does not appear in log output."""
    caplog.set_level(logging.INFO)

    distinctive_token = "fcm-tok-very-secret-abc123xyz"
    devices.register("device-secret", distinctive_token, "android")

    push.send("device-secret", {"type": "call", "name": "mẹ"})

    # Assert the token value is NOT in the log
    assert distinctive_token not in caplog.text
    # Assert the device_id IS in the log (for traceability)
    assert "device-secret" in caplog.text
