"""`GET /device/status`: app điện thoại hỏi kính có đang giữ phiên `/v2/session` không."""

import pytest
from fastapi.testclient import TestClient

import config
from app import app
from tests.conftest import TEST_DEVICE_TOKEN
from tests.test_v2_api import _gemma, _jpeg, world  # noqa: F401 (fixture)
from tests.test_v2_session import _hello

client = TestClient(app)


def _status(device="glasses-123", **kwargs):
    return client.get("/device/status", params={"device_id": device}, **kwargs)


def test_status_offline_then_online_then_offline(world, monkeypatch):  # noqa: F811
    monkeypatch.setattr(config, "VISIONCARE_DEVICE_ID", "glasses-123")
    body = _status().json()
    assert body["status"] == "ok"
    assert (body["data"]["known"], body["data"]["online"]) == (True, False)

    with client.websocket_connect("/v2/session") as glasses:
        _hello(glasses, device="glasses-123")
        assert glasses.receive_text()
        data = _status().json()["data"]
        assert (data["device_id"], data["known"], data["online"]) == ("glasses-123", True, True)
        assert _status("glasses-999").json()["data"]["online"] is False
    assert _status().json()["data"]["online"] is False


def test_status_unknown_device_is_not_known(world, monkeypatch):  # noqa: F811
    monkeypatch.setattr(config, "VISIONCARE_DEVICE_ID", "glasses-123")
    assert _status("glasses-777").json()["data"]["known"] is False


@pytest.mark.parametrize("headers", [{"x-device-token": "sai-token"}, {"authorization": "Bearer sai-token"}])
def test_status_bad_token_401(headers):
    assert _status(headers=headers).status_code == 401


def test_status_works_with_bearer_header():
    response = _status(headers={"authorization": f"Bearer {TEST_DEVICE_TOKEN}"})
    assert response.status_code == 200
