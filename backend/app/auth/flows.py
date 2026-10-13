"""
Extra Google OAuth flows that run while the user is already signed in:

  * "calendar"       - Connect Google Calendar (calendar.events scope)
  * "gmail_account"  - add another Gmail account (gmail.readonly scope)

They reuse the sign-in OAuth client and redirect URI, so nothing new has to be
registered in Google Cloud: the callback in routers/auth.py hands any state it
recognises to complete_flow(). Each grant gets its own refresh token, encrypted
at rest, and the browser only ever sees a redirect back to the app.
"""
from __future__ import annotations

import base64
import hashlib
import os
import re
import time
import urllib.parse
from dataclasses import dataclass, field

import httpx
from fastapi import HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import CalendarConnection, CalendarEvent, GmailConnection, Task, User
from app.security import decode_session_token, encrypt_token

settings = get_settings()

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
FLOW_TTL_SECONDS = 600
MAX_LABEL_LENGTH = 30


@dataclass
class PendingFlow:
    purpose: str  # "calendar" | "gmail_account"
    user_id: str
    code_verifier: str
    label: str = ""
    created: float = field(default_factory=time.time)


# state -> flow. In-memory like the sign-in PKCE store (use Redis/DB in production).
_pending: dict[str, PendingFlow] = {}


def clean_label(label: str | None) -> str:
    """Short, single-line, printable account label (School, Personal, Work, ...)."""
    text = re.sub(r"[\x00-\x1f\x7f]", " ", label or "")
    return re.sub(r"\s+", " ", text).strip()[:MAX_LABEL_LENGTH]


def _purge_expired() -> None:
    cutoff = time.time() - FLOW_TTL_SECONDS
    for state in [s for s, flow in _pending.items() if flow.created < cutoff]:
        _pending.pop(state, None)


def start_flow(purpose: str, user: User, scopes: list[str], label: str = "") -> str:
    """Register a flow and return the Google consent URL for it."""
    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(
            500,
            "Google OAuth is not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET "
            "in backend/.env — see README.md for the full Google Cloud setup steps.",
        )
    _purge_expired()
    state = base64.urlsafe_b64encode(os.urandom(24)).decode()
    verifier = base64.urlsafe_b64encode(os.urandom(40)).decode().rstrip("=")
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    _pending[state] = PendingFlow(purpose=purpose, user_id=user.id, code_verifier=verifier, label=clean_label(label))
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes + ["openid", "email"]),
        "access_type": "offline",
        # Let the user pick which Google account to connect, and always return a refresh token.
        "prompt": "select_account consent",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    if purpose == "calendar":
        params["login_hint"] = user.email
    return f"{GOOGLE_AUTH_URL}?{urllib.parse.urlencode(params)}"


def pop_flow(state: str | None) -> PendingFlow | None:
    """Claim a pending flow (one use). None if unknown, used, or expired."""
    flow = _pending.pop(state, None) if state else None
    if flow and time.time() - flow.created > FLOW_TTL_SECONDS:
        return None
    return flow


def _landing(purpose: str, outcome: str) -> RedirectResponse:
    base = settings.frontend_url.rstrip("/")
    url = f"{base}/today?calendar={outcome}" if purpose == "calendar" else f"{base}/?gmail_account={outcome}"
    return RedirectResponse(url=url, status_code=303)


async def complete_flow(
    flow: PendingFlow, code: str | None, error: str | None, session_token: str | None, db: Session,
) -> RedirectResponse:
    """Finish a flow started by start_flow(). Always redirects back to the app."""
    if error or not code:
        return _landing(flow.purpose, "denied")
    # The session cookie must belong to the user who started the flow.
    if not session_token or decode_session_token(session_token) != flow.user_id:
        return _landing(flow.purpose, "error")
    user = db.get(User, flow.user_id)
    if not user:
        return _landing(flow.purpose, "error")

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            token_response = await client.post(GOOGLE_TOKEN_URL, data={
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "code": code,
                "code_verifier": flow.code_verifier,
                "grant_type": "authorization_code",
                "redirect_uri": settings.google_redirect_uri,
            })
            if token_response.status_code != 200:
                return _landing(flow.purpose, "error")
            tokens = token_response.json()
            info = (await client.get(
                GOOGLE_USERINFO_URL, headers={"Authorization": f"Bearer {tokens['access_token']}"},
            )).json()
    except (httpx.HTTPError, KeyError, ValueError):
        return _landing(flow.purpose, "error")

    refresh_token = tokens.get("refresh_token")
    needed = settings.calendar_scopes if flow.purpose == "calendar" else settings.gmail_scopes
    granted = set((tokens.get("scope") or "").split())
    # Granular consent lets users untick scopes; without ours the connection is useless.
    if not refresh_token or not info.get("sub") or not info.get("email") or not set(needed) <= granted:
        return _landing(flow.purpose, "denied")

    if flow.purpose == "calendar":
        _save_calendar(db, user, refresh_token, info)
        return _landing("calendar", "connected")
    return _landing("gmail_account", _save_gmail_account(db, user, refresh_token, info, flow.label))


def _save_calendar(db: Session, user: User, refresh_token: str, info: dict) -> None:
    connection = user.calendar_connection
    if connection and connection.google_subject_id not in (None, info["sub"]):
        # A different Google account: old event links no longer apply.
        db.query(Task).filter(Task.user_id == user.id).update({
            Task.calendar_event_id: None, Task.calendar_etag: None,
            Task.calendar_hash: None, Task.calendar_synced_at: None,
        })
        db.query(CalendarEvent).filter(CalendarEvent.user_id == user.id).delete()
    if not connection:
        connection = CalendarConnection(user_id=user.id)
        db.add(connection)
    connection.google_account_email = info["email"]
    connection.google_subject_id = info["sub"]
    connection.encrypted_refresh_token = encrypt_token(refresh_token)  # never store/log the raw token
    connection.scopes = " ".join(settings.calendar_scopes)
    connection.needs_reauth = False
    connection.last_error = None
    db.commit()


def _save_gmail_account(db: Session, user: User, refresh_token: str, info: dict, label: str) -> str:
    existing = next((
        c for c in user.gmail_connections
        if c.google_subject_id == info["sub"] or c.google_account_email.lower() == info["email"].lower()
    ), None)
    connection = existing or GmailConnection(user_id=user.id, is_primary=not user.gmail_connections)
    if not existing:
        db.add(connection)
    connection.google_account_email = info["email"]
    connection.google_subject_id = info["sub"]
    connection.encrypted_refresh_token = encrypt_token(refresh_token)  # never store/log the raw token
    connection.scopes = " ".join(settings.gmail_scopes)
    if label:
        connection.label = label
    db.flush()
    user.selected_gmail_account = connection.id  # show the account the user just connected
    db.commit()
    return "updated" if existing else "added"
