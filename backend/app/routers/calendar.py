"""Google Calendar connection and two-way sync for the Today page."""
import threading
from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth.flows import start_flow
from app.config import get_settings
from app.database import get_db
from app.gcal import sync, timeutil as tu
from app.models import CalendarConnection, CalendarEvent, Task, User
from app.schemas import CalendarEventOut, CalendarStatusOut, CalendarSyncOut
from app.security import get_current_user

router = APIRouter(prefix="/api/calendar", tags=["calendar"])
settings = get_settings()

# One sync per user at a time: the page polls, and users can also press "Sync now".
_sync_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock_for(user_id: str) -> threading.Lock:
    with _locks_guard:
        return _sync_locks.setdefault(user_id, threading.Lock())


def _status(user: User) -> CalendarStatusOut:
    connection = user.calendar_connection
    if not connection:
        return CalendarStatusOut(connected=False)
    return CalendarStatusOut(
        connected=True,
        google_account_email=connection.google_account_email,
        last_synced_at=connection.last_synced_at,
        needs_reauth=connection.needs_reauth,
        error=connection.last_error,
    )


def _todays_events(db: Session, user: User) -> list[CalendarEventOut]:
    """Events on today's date (user's timezone) that don't belong to a task."""
    day_start = tu.start_of_day(tu.now_local(tu.user_tz(user)))
    rows = (
        db.query(CalendarEvent)
        .filter(CalendarEvent.user_id == user.id,
                CalendarEvent.start_at < day_start + timedelta(days=1), CalendarEvent.end_at > day_start)
        .order_by(CalendarEvent.all_day.desc(), CalendarEvent.start_at)
        .all()
    )
    return [
        CalendarEventOut(
            id=row.google_event_id, title=row.summary, start=row.start_at, end=row.end_at, all_day=row.all_day,
            location=row.location, html_link=row.html_link, origin=row.origin,
        )
        for row in rows
    ]


@router.get("/status", response_model=CalendarStatusOut)
def status(user: User = Depends(get_current_user)):
    return _status(user)


@router.post("/connect")
def connect(user: User = Depends(get_current_user)):
    """Start the Google consent flow for Calendar (a separate, narrower grant than Gmail)."""
    return {"authorization_url": start_flow("calendar", user, settings.calendar_scopes)}


@router.delete("/disconnect")
def disconnect(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Stop syncing. Tasks and the events already in Google Calendar are left as they are."""
    db.query(Task).filter(Task.user_id == user.id).update({
        Task.calendar_event_id: None, Task.calendar_etag: None,
        Task.calendar_hash: None, Task.calendar_synced_at: None,
    })
    db.query(CalendarEvent).filter(CalendarEvent.user_id == user.id).delete()
    db.query(CalendarConnection).filter(CalendarConnection.user_id == user.id).delete()
    db.commit()
    return {"disconnected": True}


@router.get("/events", response_model=list[CalendarEventOut])
def events(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _todays_events(db, user)


@router.post("/sync", response_model=CalendarSyncOut)
def sync_now(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Pull Calendar changes into Today, push task changes to Calendar."""
    lock = _lock_for(user.id)
    if not lock.acquire(blocking=False):
        return CalendarSyncOut(connected=bool(user.calendar_connection), events=_todays_events(db, user))
    try:
        result = sync.sync_user(db, user)
    finally:
        lock.release()
    db.refresh(user)
    return CalendarSyncOut(
        connected=result.connected, changed=result.changed, created=result.created, updated=result.updated,
        deleted=result.deleted, pulled=result.pulled, conflicts=result.conflicts, error=result.error,
        needs_reauth=result.needs_reauth, events=_todays_events(db, user),
    )
