"""Tests for the in-memory sliding-window rate limiter."""
import time
import pytest
from unittest.mock import patch

from services.rate_limiter import check_rate_limit, RATE_LIMIT_MAX, RATE_LIMIT_WINDOW, _requests, _lock


@pytest.fixture(autouse=True)
def clear_store():
    """Wipe rate limiter state before and after every test."""
    with _lock:
        _requests.clear()
    yield
    with _lock:
        _requests.clear()


class TestRateLimiter:
    def test_first_request_allowed(self):
        allowed, remaining, retry_after = check_rate_limit("1.2.3.4")
        assert allowed is True
        assert remaining == RATE_LIMIT_MAX - 1
        assert retry_after == 0

    def test_remaining_decrements(self):
        for i in range(3):
            allowed, remaining, _ = check_rate_limit("1.2.3.4")
            assert allowed is True
            assert remaining == RATE_LIMIT_MAX - i - 1

    def test_limit_blocks_when_exceeded(self):
        for _ in range(RATE_LIMIT_MAX):
            check_rate_limit("1.2.3.4")
        allowed, remaining, retry_after = check_rate_limit("1.2.3.4")
        assert allowed is False
        assert remaining == 0
        assert retry_after > 0

    def test_different_ips_are_independent(self):
        for _ in range(RATE_LIMIT_MAX):
            check_rate_limit("10.0.0.1")
        allowed, _, _ = check_rate_limit("10.0.0.2")
        assert allowed is True

    def test_retry_after_is_positive_on_block(self):
        for _ in range(RATE_LIMIT_MAX):
            check_rate_limit("1.2.3.4")
        _, _, retry_after = check_rate_limit("1.2.3.4")
        assert retry_after > 0
        assert retry_after <= RATE_LIMIT_WINDOW

    def test_old_requests_expire(self):
        now = time.time()
        # Simulate requests made just past the window
        with patch("time.time", return_value=now - RATE_LIMIT_WINDOW - 1):
            for _ in range(RATE_LIMIT_MAX):
                check_rate_limit("1.2.3.4")
        # At current time the window should be empty again
        allowed, remaining, _ = check_rate_limit("1.2.3.4")
        assert allowed is True
        assert remaining == RATE_LIMIT_MAX - 1

    def test_partial_expiry(self):
        now = time.time()
        # 3 requests in the old window, 2 in the current window
        with patch("time.time", return_value=now - RATE_LIMIT_WINDOW - 1):
            for _ in range(3):
                check_rate_limit("1.2.3.4")
        for _ in range(2):
            check_rate_limit("1.2.3.4")
        _, remaining, _ = check_rate_limit("1.2.3.4")
        # Only the 2 current-window requests + this one should count (3 total)
        assert remaining == RATE_LIMIT_MAX - 3
