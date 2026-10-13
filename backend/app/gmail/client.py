"""
FR-01/02/03 Gmail API wrapper.
Thin client around google-api-python-client with pagination, metadata-first
fetching, and full-content retrieval only for candidate messages (FR-02).
"""
from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass
from typing import Optional

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.config import get_settings

settings = get_settings()


class GmailRateLimitError(RuntimeError):
    """Gmail's per-user quota was still exhausted after repeated, spaced-out retries."""


# Gmail charges quota units per call (messages.get = 20, messages.list = 5) against
# a per-user budget per minute, so a rate-limit error clears once the minute rolls
# over. Google's guidance is truncated exponential backoff with jitter.
_RATE_LIMIT_ATTEMPTS = 6
_RATE_LIMIT_MAX_WAIT = 32.0
_RATE_LIMIT_REASONS = ("ratelimitexceeded", "userratelimitexceeded")

# Shared by every worker thread: once one call is rate-limited, all of them pause
# instead of sending more requests that are certain to be rejected.
_cooldown_lock = threading.Lock()
_cooldown_until = 0.0  # time.monotonic() value


def _wait_for_cooldown() -> None:
    with _cooldown_lock:
        wait = _cooldown_until - time.monotonic()
    if wait > 0:
        time.sleep(wait)


def _extend_cooldown(seconds: float) -> None:
    global _cooldown_until
    with _cooldown_lock:
        _cooldown_until = max(_cooldown_until, time.monotonic() + seconds)


def _is_rate_limited(error: HttpError) -> bool:
    status = error.resp.status
    if status == 429:
        return True
    if status != 403:
        return False
    try:
        body = (error.content or b"").decode("utf-8", "ignore").lower()
    except AttributeError:
        return False
    # 403 is also used for real permission problems, so require a rate-limit reason.
    return any(reason in body for reason in _RATE_LIMIT_REASONS) or "resource_exhausted" in body


@dataclass
class GmailMessageRef:
    id: str
    thread_id: str


class GmailClient:
    def __init__(self, refresh_token: str):
        self._credentials = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            scopes=settings.gmail_scopes,
        )
        self._service = build("gmail", "v1", credentials=self._credentials, cache_discovery=False)

    # ---- FR-02 step 2: profile ----
    def get_profile(self) -> dict:
        return self._with_retry(lambda: self._service.users().getProfile(userId="me").execute())

    # ---- FR-02 step 3/4: list messages (metadata-first) ----
    def list_message_ids(self, query: str, max_results: int) -> list[GmailMessageRef]:
        refs: list[GmailMessageRef] = []
        page_token: Optional[str] = None
        while len(refs) < max_results:
            resp = self._with_retry(
                lambda pt=page_token: self._service.users()
                .messages()
                .list(userId="me", q=query, pageToken=pt, maxResults=min(100, max_results - len(refs)))
                .execute()
            )
            for m in resp.get("messages", []):
                refs.append(GmailMessageRef(id=m["id"], thread_id=m["threadId"]))
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        return refs[:max_results]

    # ---- FR-02 step 5: full content for candidate messages ----
    def get_message(self, message_id: str) -> dict:
        return self._with_retry(
            lambda: self._service.users().messages().get(userId="me", id=message_id, format="full").execute()
        )

    # ---- assistant: read a whole thread (used when the hosted Gmail MCP server is unavailable) ----
    def get_thread(self, thread_id: str) -> dict:
        return self._with_retry(
            lambda: self._service.users().threads().get(userId="me", id=thread_id, format="full").execute()
        )

    # ---- FR-03: incremental sync via History API ----
    def list_history(self, start_history_id: str) -> dict:
        return self._with_retry(
            lambda: self._service.users()
            .history()
            .list(userId="me", startHistoryId=start_history_id)
            .execute()
        )

    # ---- FR-03: Gmail watch registration ----
    def start_watch(self, topic_name: str) -> dict:
        body = {"topicName": topic_name, "labelIds": ["INBOX"]}
        return self._with_retry(lambda: self._service.users().watch(userId="me", body=body).execute())

    @staticmethod
    def _with_retry(fn, retries: int = 3, backoff_seconds: float = 1.0):
        """FR 5.5: exponential backoff for transient failures, and a longer,
        shared backoff for Gmail rate limits (see the notes above)."""
        server_failures = 0
        rate_limited = 0
        while True:
            _wait_for_cooldown()
            try:
                return fn()
            except HttpError as e:
                if _is_rate_limited(e):
                    rate_limited += 1
                    if rate_limited >= _RATE_LIMIT_ATTEMPTS:
                        raise GmailRateLimitError("Gmail rate limit reached") from e
                    _extend_cooldown(min(2 ** rate_limited + random.random(), _RATE_LIMIT_MAX_WAIT))
                    continue
                if e.resp.status in (500, 502, 503):
                    server_failures += 1
                    if server_failures >= retries:
                        raise
                    time.sleep(backoff_seconds * (2 ** (server_failures - 1)))
                    continue
                raise
