"""Централизованный http_get: ретраи, без лишних вызовов на 404."""

from unittest.mock import MagicMock, patch

import pytest


def _resp(code: int, headers=None):
    m = MagicMock()
    m.status_code = code
    m.headers = headers or {}
    return m


@patch("bit_trend.data.http_client.requests.get")
def test_http_get_retries_then_ok(mock_get, monkeypatch):
    monkeypatch.setenv("HTTP_MAX_RETRIES", "2")
    monkeypatch.setenv("HTTP_RATE_MIN_INTERVAL_SEC", "0")
    mock_get.side_effect = [_resp(503), _resp(503), _resp(200)]

    from bit_trend.data.http_client import http_get

    r = http_get("https://api.example.test/data", timeout=5)
    assert r.status_code == 200
    assert mock_get.call_count == 3


@patch("bit_trend.data.http_client.requests.get")
def test_http_get_no_retry_on_404(mock_get, monkeypatch):
    monkeypatch.setenv("HTTP_RATE_MIN_INTERVAL_SEC", "0")
    mock_get.return_value = _resp(404)

    from bit_trend.data.http_client import http_get

    assert http_get("https://api.example.test/miss").status_code == 404
    assert mock_get.call_count == 1


@patch("bit_trend.data.http_client.requests.get")
def test_http_get_respects_retry_after(mock_get, monkeypatch):
    monkeypatch.setenv("HTTP_MAX_RETRIES", "1")
    monkeypatch.setenv("HTTP_RATE_MIN_INTERVAL_SEC", "0")
    mock_get.side_effect = [_resp(429, {"Retry-After": "0"}), _resp(200)]

    from bit_trend.data.http_client import http_get

    with patch("bit_trend.data.http_client.time.sleep"):
        r = http_get("https://api.example.test/rl")
    assert r.status_code == 200
    assert mock_get.call_count == 2


@patch("bit_trend.data.http_client.requests.get")
def test_http_get_raises_after_network_failures(mock_get, monkeypatch):
    monkeypatch.setenv("HTTP_MAX_RETRIES", "1")
    monkeypatch.setenv("HTTP_RATE_MIN_INTERVAL_SEC", "0")
    import requests

    mock_get.side_effect = [
        requests.exceptions.ConnectionError("boom"),
        requests.exceptions.ConnectionError("boom"),
    ]

    from bit_trend.data.http_client import http_get

    with patch("bit_trend.data.http_client.time.sleep"):
        with pytest.raises(requests.exceptions.ConnectionError):
            http_get("https://api.example.test/net")
