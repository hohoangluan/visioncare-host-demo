from pipeline import push, devices


def test_send_returns_true_when_token_registered():
    devices.register("push-dev", "tok-1", "android")
    assert push.send("push-dev", {"type": "call", "name": "mẹ"}) is True


def test_send_returns_false_when_no_token():
    assert push.send("no-such-device", {"type": "call", "name": "x"}) is False
