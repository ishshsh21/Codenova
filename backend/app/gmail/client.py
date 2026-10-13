"""
FR-01/02/03 Gmail API wrapper.
Thin client around google-api-python-client with pagination, metadata-first
fetching, and full-content retrieval only for candidate messages (FR-02).
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Optional

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.config import get_settings

settings = get_settings()


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
    def _with_retry(
        fn, retries: int = 6, backoff_seconds: float = 2.0, max_backoff_seconds: float = 30.0,
    ):
        """FR 5.5: exponential backoff (with jitter) for transient failures.

        Gmail's per-minute quotas are per-minute, so the waits have to be long
        enough for the window to roll over: 2s, 4s, 8s, 16s, 30s by default.
        """
        for attempt in range(retries):
            try:
                return fn()
            except HttpError as e:
                if not _is_retryable(e):
                    raise
                if attempt == retries - 1:
                    if is_rate_limit_error(e):
                        raise GmailRateLimitError(
                            "Gmail is rate-limiting this account right now."
                        ) from e
                    raise
                delay = min(backoff_seconds * (2 ** attempt), max_backoff_seconds)
                time.sleep(delay * random.uniform(0.75, 1.0))


class GmailRateLimitError(RuntimeError):
    """Gmail kept throttling us after every retry; waiting a minute usually fixes it."""


def is_rate_limit_error(e: HttpError) -> bool:
    """Gmail reports quota throttling as 429, or as a 403 whose reason is
    rateLimitExceeded / userRateLimitExceeded. Other 403s (missing scope,
    daily limit, disabled API) are real denials and must not be retried."""
    if e.resp.status == 429:
        return True
    if e.resp.status != 403:
        return False
    content = e.content.decode("utf-8", "ignore") if isinstance(e.content, bytes) else str(e.content)
    return "ratelimitexceeded" in content.lower()


def _is_retryable(e: HttpError) -> bool:
    return e.resp.status in (500, 502, 503, 504) or is_rate_limit_error(e)
