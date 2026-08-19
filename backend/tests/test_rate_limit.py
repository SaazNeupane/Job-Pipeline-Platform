from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.rate_limit import rate_limit


def _request(ip="1.2.3.4"):
    return SimpleNamespace(client=SimpleNamespace(host=ip))


def test_allows_calls_under_the_limit():
    limiter = rate_limit(3, 60)
    for _ in range(3):
        limiter(_request())  # must not raise


def test_blocks_calls_over_the_limit():
    limiter = rate_limit(3, 60)
    for _ in range(3):
        limiter(_request())
    with pytest.raises(HTTPException) as exc_info:
        limiter(_request())
    assert exc_info.value.status_code == 429


def test_limits_are_per_client_ip():
    limiter = rate_limit(1, 60)
    limiter(_request("1.1.1.1"))
    limiter(_request("2.2.2.2"))  # different IP, must not raise
