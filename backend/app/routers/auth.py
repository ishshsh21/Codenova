"""
FR-01 Gmail Authentication via Google OAuth 2.0 (Authorization Code + PKCE).
Every login goes through real Google sign-in — there is no local/demo user
fallback. See README.md for the full Google Cloud OAuth setup.
"""
import hashlib
import base64
import os
import urllib.parse

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import (
    User, GmailConnection, EmailMessage, EmailThread, Task, TaskSource,
    TaskDependency, TaskFeedback, ScanRun, Notification,
)
from sqlalchemy import or_
from app.security import create_session_token, encrypt_token, SESSION_COOKIE_NAME, get_current_user
from app.schemas import UserOut, UserSettingsIn, DataSummaryOut
from app.gmail.sync import refresh_audiences, reprioritize

router = APIRouter(prefix="/api/auth", tags=["auth"])
settings = get_settings()

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"

_pkce_store: dict[str, str] = {}  # state -> code_verifier (MVP in-memory; use Redis in production)


def _set_session_cookie(response: Response, user_id: str):
    token = create_session_token(user_id)
    response.set_cookie(
        key=SESSION_COOKIE_NAME, value=token, httponly=True, samesite="lax",
        secure=False, max_age=7 * 24 * 3600,  # set secure=True behind HTTPS in production
    )


@router.get("/google")
def start_google_oauth():
    """Kicks off FR-01 — builds the Google consent screen URL (PKCE)."""
    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(
            500,
            "Google OAuth is not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET "
            "in backend/.env — see README.md for the full Google Cloud setup steps.",
        )

    state = base64.urlsafe_b64encode(os.urandom(24)).decode()
    code_verifier = base64.urlsafe_b64encode(os.urandom(40)).decode().rstrip("=")
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode()).digest()
    ).decode().rstrip("=")
    _pkce_store[state] = code_verifier

    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": " ".join(settings.gmail_scopes + ["openid", "email", "profile"]),
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return {"authorization_url": f"{GOOGLE_AUTH_URL}?{urllib.parse.urlencode(params)}"}


@router.get("/google/callback")
async def google_oauth_callback(code: str, state: str, db: Session = Depends(get_db)):
    import httpx

    code_verifier = _pkce_store.pop(state, None)
    if not code_verifier:
        raise HTTPException(400, "Invalid or expired OAuth state")

    async with httpx.AsyncClient() as client:
        token_resp = await client.post(GOOGLE_TOKEN_URL, data={
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "code": code,
            "code_verifier": code_verifier,
            "grant_type": "authorization_code",
            "redirect_uri": settings.google_redirect_uri,
        })
    if token_resp.status_code != 200:
        raise HTTPException(400, "Google token exchange failed")

    tokens = token_resp.json()
    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        raise HTTPException(400, "No refresh token returned — revoke prior consent and retry with prompt=consent")

    async with httpx.AsyncClient() as client:
        userinfo = (await client.get(
            "https://www.googleapis.com/oauth2/v3/userinfo",
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )).json()

    user = db.query(User).filter_by(google_subject_id=userinfo["sub"]).first()
    if not user:
        user = User(google_subject_id=userinfo["sub"], email=userinfo["email"], name=userinfo.get("name", ""))
        db.add(user)
        db.commit()
        db.refresh(user)

    connection = user.gmail_connection
    if not connection:
        connection = GmailConnection(user_id=user.id, google_account_email=userinfo["email"])
        db.add(connection)
    connection.encrypted_refresh_token = encrypt_token(refresh_token)  # never store/log raw token (Section 10)
    connection.scopes = " ".join(settings.gmail_scopes)
    connection.google_account_email = userinfo["email"]
    db.commit()

    # The callback is opened by the browser, so redirect it to the SPA instead
    # of returning the redirect target as JSON.
    redirect_response = RedirectResponse(url=settings.frontend_url, status_code=303)
    _set_session_cookie(redirect_response, user.id)
    return redirect_response


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(SESSION_COOKIE_NAME)
    return {"ok": True}


@router.delete("/account")
def delete_account(response: Response, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Permanently delete the account and every record owned by the user."""
    task_ids = db.query(Task.id).filter(Task.user_id == user.id).subquery()
    db.query(TaskDependency).filter(
        or_(TaskDependency.task_id.in_(task_ids), TaskDependency.depends_on_task_id.in_(task_ids))
    ).delete(synchronize_session=False)
    db.query(TaskSource).filter(TaskSource.task_id.in_(task_ids)).delete(synchronize_session=False)
    db.query(TaskFeedback).filter(TaskFeedback.user_id == user.id).delete(synchronize_session=False)
    db.query(Task).filter(Task.user_id == user.id).delete(synchronize_session=False)
    db.query(EmailMessage).filter(EmailMessage.user_id == user.id).delete(synchronize_session=False)
    db.query(EmailThread).filter(EmailThread.user_id == user.id).delete(synchronize_session=False)
    db.query(Notification).filter(Notification.user_id == user.id).delete(synchronize_session=False)
    db.query(ScanRun).filter(ScanRun.user_id == user.id).delete(synchronize_session=False)
    db.query(GmailConnection).filter(GmailConnection.user_id == user.id).delete(synchronize_session=False)
    db.delete(user)
    db.commit()
    response.delete_cookie(SESSION_COOKIE_NAME)
    return {"deleted": True}


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


@router.patch("/settings", response_model=UserOut)
def update_settings(payload: UserSettingsIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    values = payload.model_dump(exclude_unset=True)
    if "default_scan_days" in values and not 1 <= values["default_scan_days"] <= 365:
        raise HTTPException(422, "default_scan_days must be between 1 and 365")
    if "my_classes" in values:
        values["my_classes"] = [c.strip() for c in values["my_classes"] or [] if c.strip()]
    classes_changed = "my_classes" in values and values["my_classes"] != (user.my_classes or [])
    ranking_changed = "vip_senders" in values and values["vip_senders"] != (user.vip_senders or [])
    for field, value in values.items():
        setattr(user, field, value)
    db.commit()
    # Re-rank right away so the Now and FYI screens reflect the new classes.
    if classes_changed:
        refresh_audiences(db, user)
    elif ranking_changed:
        reprioritize(db, user)
    db.refresh(user)
    return user


@router.get("/data-summary", response_model=DataSummaryOut)
def data_summary(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    connection = user.gmail_connection
    return DataSummaryOut(
        imported_emails=db.query(EmailMessage).filter_by(user_id=user.id).count(),
        tasks=db.query(Task).filter_by(user_id=user.id).count(),
        scans=db.query(ScanRun).filter_by(user_id=user.id).count(),
        notifications=db.query(Notification).filter_by(user_id=user.id).count(),
        gmail_connected=bool(connection),
        gmail_scopes=connection.scopes.split() if connection and connection.scopes else [],
    )


@router.delete("/imported-data")
def delete_imported_data(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    task_ids = db.query(Task.id).filter(Task.user_id == user.id).subquery()
    db.query(TaskDependency).filter(
        or_(TaskDependency.task_id.in_(task_ids), TaskDependency.depends_on_task_id.in_(task_ids))
    ).delete(synchronize_session=False)
    db.query(TaskSource).filter(TaskSource.task_id.in_(task_ids)).delete(synchronize_session=False)
    db.query(TaskFeedback).filter(TaskFeedback.user_id == user.id).delete(synchronize_session=False)
    db.query(Task).filter(Task.user_id == user.id).delete(synchronize_session=False)
    db.query(EmailMessage).filter(EmailMessage.user_id == user.id).delete(synchronize_session=False)
    db.query(EmailThread).filter(EmailThread.user_id == user.id).delete(synchronize_session=False)
    db.query(Notification).filter(Notification.user_id == user.id).delete(synchronize_session=False)
    db.query(ScanRun).filter(ScanRun.user_id == user.id).delete(synchronize_session=False)
    if user.gmail_connection:
        user.gmail_connection.last_synced_at = None
    db.commit()
    return {"deleted": True}
