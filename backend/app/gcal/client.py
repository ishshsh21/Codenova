"""
Thin wrapper around the Google Calendar v3 API.

Each call exchanges the user's encrypted refresh token for a short-lived access
token (handled by google-auth); tokens and event contents are never logged. All
writes pass sendUpdates="none" so this app never emails guests.
"""
from __future__ import annotations

import httplib2
from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials
from google_auth_httplib2 import AuthorizedHttp
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.config import get_settings

settings = get_settings()


class CalendarError(RuntimeError):
    """A Calendar request failed (message is safe to show; it never contains content)."""


class CalendarAuthError(CalendarError):
    """The Calendar grant is revoked, expired, or missing the needed scope."""


class CalendarConflict(CalendarError):
    """insert_event: an event with that ID already exists (HTTP 409)."""


class CalendarClient:
    def __init__(self, refresh_token: str, calendar_id: str | None = None):
        self._calendar_id = calendar_id or settings.calendar_id
        credentials = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            scopes=settings.calendar_scopes,
        )
        http = AuthorizedHttp(credentials, http=httplib2.Http(timeout=15))
        self._events = build("calendar", "v3", http=http, cache_discovery=False).events()

    # ---- reads ----
    def list_events(self, time_min: str, time_max: str, limit: int = 1000) -> list[dict]:
        """Events overlapping [time_min, time_max) with recurrences expanded."""
        events: list[dict] = []
        page_token = None
        while True:
            response = self._execute(self._events.list(
                calendarId=self._calendar_id, timeMin=time_min, timeMax=time_max,
                singleEvents=True, orderBy="startTime", maxResults=250,
                showDeleted=False, pageToken=page_token,
            ))
            events.extend(response.get("items", []))
            page_token = response.get("nextPageToken")
            if not page_token or len(events) >= limit:
                return events[:limit]

    def get_event(self, event_id: str) -> dict | None:
        """The event, including status "cancelled" if deleted; None if it is gone."""
        try:
            return self._execute(self._events.get(calendarId=self._calendar_id, eventId=event_id))
        except _NotFound:
            return None

    # ---- writes ----
    def insert_event(self, body: dict) -> dict:
        try:
            return self._execute(self._events.insert(
                calendarId=self._calendar_id, body=body, sendUpdates="none"))
        except _Duplicate as exc:
            raise CalendarConflict("An event with this ID already exists") from exc

    def patch_event(self, event_id: str, body: dict) -> dict | None:
        """Partial update; None if the event no longer exists."""
        try:
            return self._execute(self._events.patch(
                calendarId=self._calendar_id, eventId=event_id, body=body, sendUpdates="none"))
        except _NotFound:
            return None

    def delete_event(self, event_id: str) -> None:
        """Delete; already-deleted events count as success."""
        try:
            self._execute(self._events.delete(
                calendarId=self._calendar_id, eventId=event_id, sendUpdates="none"))
        except _NotFound:
            return None

    # ---- plumbing ----
    @staticmethod
    def _execute(request):
        try:
            return request.execute(num_retries=2)
        except RefreshError as exc:
            raise CalendarAuthError("Google Calendar access expired or was revoked") from exc
        except HttpError as exc:
            status = exc.resp.status
            if status in (404, 410):
                raise _NotFound() from exc
            if status == 409:
                raise _Duplicate() from exc
            body = (exc.content or b"").decode("utf-8", "ignore").lower()
            if status == 401 or (status == 403 and ("insufficient" in body or "scope" in body)):
                raise CalendarAuthError("Google Calendar access was denied") from exc
            raise CalendarError(f"Google Calendar request failed (HTTP {status})") from exc
        except (httplib2.HttpLib2Error, OSError) as exc:
            raise CalendarError("Could not reach Google Calendar") from exc


class _NotFound(Exception):
    pass


class _Duplicate(Exception):
    pass
