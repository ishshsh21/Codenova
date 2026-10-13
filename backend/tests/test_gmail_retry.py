"""Gmail throttling: a per-minute quota 403 is retried; real denials are not."""
import json
import threading

import httplib2
import pytest
from googleapiclient.errors import HttpError

import app.gmail.sync as sync
from app.gmail import client as gmail_client
from app.gmail.client import GmailClient, GmailRateLimitError
from app.routers.gmail import _scan_error_message


def _http_error(status: int, reason: str) -> HttpError:
    body = {"error": {"code": status, "message": reason, "errors": [{"reason": reason}]}}
    return HttpError(httplib2.Response({"status": status}), json.dumps(body).encode())


@pytest.fixture()
def sleeps(monkeypatch):
    recorded: list[float] = []
    monkeypatch.setattr(gmail_client.time, "sleep", recorded.append)
    return recorded


def _flaky(failures: list[HttpError]):
    """A callable that raises each queued error in turn, then returns 'ok'."""
    queue = list(failures)

    def call():
        if queue:
            raise queue.pop(0)
        return "ok"
    return call


@pytest.mark.parametrize("reason", ["rateLimitExceeded", "userRateLimitExceeded"])
def test_quota_403_is_retried_until_it_succeeds(sleeps, reason):
    call = _flaky([_http_error(403, reason), _http_error(403, reason)])
    assert GmailClient._with_retry(call) == "ok"
    assert len(sleeps) == 2


def test_backoff_grows_and_is_capped(sleeps):
    call = _flaky([_http_error(429, "rateLimitExceeded")] * 5)
    GmailClient._with_retry(call, retries=6, backoff_seconds=2.0, max_backoff_seconds=10.0)
    # 2, 4, 8, 16->10, 32->10, each jittered down by at most 25%
    for delay, ceiling in zip(sleeps, [2, 4, 8, 10, 10]):
        assert ceiling * 0.75 <= delay <= ceiling


@pytest.mark.parametrize("status, reason", [
    (403, "insufficientPermissions"),
    (403, "dailyLimitExceeded"),
    (401, "authError"),
    (404, "notFound"),
])
def test_real_errors_are_not_retried(sleeps, status, reason):
    call = _flaky([_http_error(status, reason)])
    with pytest.raises(HttpError):
        GmailClient._with_retry(call)
    assert sleeps == []


def test_persistent_throttling_raises_a_rate_limit_error(sleeps):
    call = _flaky([_http_error(403, "rateLimitExceeded")] * 10)
    with pytest.raises(GmailRateLimitError):
        GmailClient._with_retry(call, retries=3)
    assert len(sleeps) == 2  # no sleep after the final attempt


def test_persistent_server_error_surfaces_the_original_http_error(sleeps):
    call = _flaky([_http_error(503, "backendError")] * 10)
    with pytest.raises(HttpError):
        GmailClient._with_retry(call, retries=3)


def test_scan_error_messages_are_plain_language():
    for exc in (GmailRateLimitError("x"), _http_error(403, "rateLimitExceeded")):
        message = _scan_error_message(exc)
        assert "HttpError" not in message and "googleapis" not in message
        assert "Run again" in message
    assert "HTTP 404" in _scan_error_message(_http_error(404, "notFound"))
    assert _scan_error_message(ValueError("boom")) == "boom"


def test_a_failed_fetch_cancels_the_queue(monkeypatch):
    """After one fetch fails for good, the queued ones must not keep hitting Gmail."""
    class Ref:
        def __init__(self, i):
            self.id = str(i)

    class FakeClient:
        def list_message_ids(self, *_):
            return [Ref(i) for i in range(60)]

    calls, lock = [], threading.Lock()

    def fetch(_token, ref):
        with lock:
            calls.append(ref.id)
        raise GmailRateLimitError("throttled")

    monkeypatch.setattr(sync, "_fetch_one_email", fetch)
    monkeypatch.setattr(sync.settings, "gmail_fetch_workers", 2)
    with pytest.raises(GmailRateLimitError):
        sync._normalized_email_records_gmail(FakeClient(), "token", "q", 60)
    assert len(calls) < 10
