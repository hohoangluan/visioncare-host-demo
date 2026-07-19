from pipeline import devices


def test_register_and_get_token():
    devices.register("dev-1", "tok-abc", "android")
    assert devices.get_token("dev-1") == "tok-abc"


def test_get_unknown_returns_none():
    assert devices.get_token("khong-ton-tai") is None


def test_register_overwrites():
    devices.register("dev-2", "old")
    devices.register("dev-2", "new")
    assert devices.get_token("dev-2") == "new"
