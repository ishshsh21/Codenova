import json

import pytest
from googleapiclient.errors import HttpError
from httplib2 import Response

import app.gmail.client as client
from app.gmail.client import GmailClient, GmailRateLimited


def _error(status, reason):
    body = json.dumps({"error": {"errors": [{"reason": reason}]}}).encode()
    return HttpError(Response({"status": status}), body)


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(client.time, "sleep", lambda _s: None)


def test_quota_403_is_retried_until_it_succeeds():
    calls = []

    def fn():
        calls.append(1)
        if len(calls) < 3:
            raise _error(403, "rateLimitExceeded")
        return "ok"

    assert GmailClient._with_retry(fn) == "ok"
    assert len(calls) == 3


def test_persistent_quota_error_gives_a_readable_message():
    def fn():
        raise _error(403, "rateLimitExceeded")

    with pytest.raises(GmailRateLimited, match="Wait a minute"):
        GmailClient._with_retry(fn)


def test_permission_403_is_not_retried():
    calls = []

    def fn():
        calls.append(1)
        raise _error(403, "insufficientPermissions")

    with pytest.raises(HttpError):
        GmailClient._with_retry(fn)
    assert len(calls) == 1
