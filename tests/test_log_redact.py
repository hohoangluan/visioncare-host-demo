"""Minor 6: access log của uvicorn không được chứa media token trên query string."""

import logging

import pytest

import app  # noqa: F401  (gắn filter lên logger uvicorn.access)


@pytest.mark.parametrize("name", ["uvicorn.access", "uvicorn.error"])  # WS accepted đi qua uvicorn.error (đo thật)
def test_uvicorn_access_log_redacts_token(caplog, name):
    logger = logging.getLogger(name)
    with caplog.at_level(logging.INFO, logger=name):
        logger.info('%s - "WebSocket %s" [accepted]', "1.2.3.4:5", "/v2/call?token=SECRET-abc_123&x=1")
        logger.info('%s - "%s %s HTTP/%s" %d', "1.2.3.4:5", "GET", "/v2/session?a=1&access_token=SECRET2", "1.1", 200)
        logger.info('%s - "GET %s" 200', "1.2.3.4:5", "/health")
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "SECRET" not in text
    assert "/v2/call?token=***&x=1" in text and "access_token=***" in text
    assert "/health" in text
