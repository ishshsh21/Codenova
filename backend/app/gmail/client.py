"""
FR-01/02/03 Gmail API wrapper.
Thin client around google-api-python-client with pagination, metadata-first
fetching, and full-content retrieval only for candidate messages (FR-02).
"""
from __future__ import annotations

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
    def _with_retry(fn, retries: int = 3, backoff_seconds: float = 1.0):
        """FR 5.5: exponential backoff for transient failures."""
        last_error = None
        for attempt in range(retries):
            try:
                return fn()
            except HttpError as e:
                last_error = e
                if e.resp.status in (429, 500, 502, 503):
                    time.sleep(backoff_seconds * (2 ** attempt))
                    continue
                raise
        raise last_error
