"""
Two-way sync between app tasks and Google Calendar (Today page only).

Model
-----
* A task with a deadline becomes a calendar event: it starts at the deadline and
  lasts `estimated_effort_minutes`. The event ID is deterministic (derived from
  the task ID) AND stored on the task (Task.calendar_event_id), so a task can
  never produce a second event, even if a request is retried or interrupted.
* Events created in Google Calendar that don't belong to a task are cached in
  `calendar_events` and shown on Today next to the tasks. They are never turned
  into tasks, so Overview, This Week and the rest of the app are unaffected.
* Which side changed since the last sync is decided by an etag (remote) and a
  content hash (local) rather than timestamps, so unrelated task updates such
  as priority re-scoring never cause calendar writes.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from cryptography.fernet import InvalidToken
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.config import get_settings
from app.gcal import timeutil as tu
from app.gcal.client import CalendarAuthError, CalendarClient, CalendarConflict, CalendarError
from app.models import (
    CalendarConnection, CalendarEvent, Notification, Task, TaskFeedback, TaskStatus, User,
)
from app.security import decrypt_token

logger = logging.getLogger("workday_agent.calendar")
settings = get_settings()

MIN_EVENT_MINUTES = 5
MAX_EVENT_MINUTES = 24 * 60
MAX_REMOTE_LOOKUPS = 50  # per sync, for linked events that fell outside the listed window
TASK_MARKER = "workdaySignalTaskId"  # private extended property set on every event we create


def make_client(connection: CalendarConnection) -> CalendarClient:
    """The one place a Calendar client is built (tests replace this)."""
    try:
        refresh_token = decrypt_token(connection.encrypted_refresh_token)
    except InvalidToken as exc:  # e.g. FERNET_KEY changed since the grant was stored
        raise CalendarAuthError("Stored Google Calendar credentials could not be read") from exc
    return CalendarClient(refresh_token)


@dataclass
class SyncResult:
    connected: bool = True
    changed: bool = False
    created: int = 0
    updated: int = 0
    deleted: int = 0
    pulled: int = 0
    conflicts: list[dict] = field(default_factory=list)
    error: str | None = None
    needs_reauth: bool = False


# ---------------------------------------------------------------- task <-> event mapping

def event_id_for_task(task_id: str) -> str:
    """Deterministic Calendar event ID. Calendar IDs allow [a-v0-9]; hex is a subset."""
    return hashlib.sha1(f"workday-signal:{task_id}".encode()).hexdigest()


def _duration_minutes(task: Task) -> int:
    return max(MIN_EVENT_MINUTES, min(MAX_EVENT_MINUTES, task.estimated_effort_minutes or 30))


def wants_event(task: Task) -> bool:
    return task.status == TaskStatus.OPEN.value and task.deadline is not None


def task_hash(task: Task) -> str:
    """Fingerprint of everything that is mirrored to Calendar."""
    start = task.deadline.replace(microsecond=0).isoformat() if task.deadline else ""
    state = "open" if wants_event(task) else "closed"
    raw = "|".join([task.title or "", start, str(_duration_minutes(task)), state])
    return hashlib.sha1(raw.encode()).hexdigest()


def _event_times(task: Task, tz) -> dict:
    end = task.deadline + timedelta(minutes=_duration_minutes(task))
    return {"start": tu.to_google(task.deadline, tz), "end": tu.to_google(end, tz)}


def _patch_body(task: Task, tz) -> dict:
    # Only mirrored fields: a description the user typed in Calendar is left alone.
    return {"summary": (task.title or "Untitled task")[:1000], "status": "confirmed", **_event_times(task, tz)}


def _insert_body(task: Task, tz) -> dict:
    description = f"Synced from Workday Signal\nPriority: {task.priority}"
    if task.project:
        description += f"\nProject: {task.project}"
    return {
        **_patch_body(task, tz),
        "id": event_id_for_task(task.id),
        "description": description,
        "extendedProperties": {"private": {TASK_MARKER: task.id}},
    }


def _stamp(task: Task, remote: dict | None) -> None:
    task.calendar_etag = remote.get("etag") if remote else None
    task.calendar_hash = task_hash(task)
    task.calendar_synced_at = datetime.utcnow()


def _insert_or_adopt(db: Session, client: CalendarClient, task: Task, tz) -> dict:
    """Create the task's event, or adopt it if it already exists (retry / re-link)."""
    try:
        remote = client.insert_event(_insert_body(task, tz))
    except CalendarConflict:
        remote = client.patch_event(event_id_for_task(task.id), _patch_body(task, tz))
        if remote is None:
            raise CalendarError("Could not restore the existing calendar event")
    db.query(CalendarEvent).filter_by(user_id=task.user_id, google_event_id=remote["id"]).delete()
    return remote


# ---------------------------------------------------------------- push (task -> event)

def push_task(db: Session, task: Task, client: CalendarClient, tz, window: tuple[datetime, datetime]) -> str:
    """Bring one task's event in line with the task. Returns created|updated|deleted|noop."""
    current = task_hash(task)
    if task.calendar_event_id:
        if task.calendar_hash == current:
            return "noop"
        if not wants_event(task):
            # Completed / dismissed / deadline removed: the event is ours, remove it.
            client.delete_event(task.calendar_event_id)
            _stamp(task, None)
            return "deleted"
        remote = client.patch_event(task.calendar_event_id, _patch_body(task, tz))
        if remote is None:
            remote = _insert_or_adopt(db, client, task, tz)
        task.calendar_event_id = remote["id"]
        _stamp(task, remote)
        return "updated"
    if not wants_event(task) or not (window[0] <= task.deadline <= window[1]):
        return "noop"
    remote = _insert_or_adopt(db, client, task, tz)
    task.calendar_event_id = remote["id"]
    _stamp(task, remote)
    return "created"


# ---------------------------------------------------------------- pull (event -> task / cache)

def pull_task(db: Session, user: User, task: Task, remote: dict | None, tz) -> str:
    """Apply a remote change to a linked task. Returns noop|updated|dismissed."""
    if task.status != TaskStatus.OPEN.value:
        return "noop"
    local_changed = task.calendar_hash != task_hash(task)

    if remote is None or remote.get("status") == "cancelled":
        if local_changed:
            return "noop"  # edited locally since the last sync: local wins, push recreates it
        old_title = task.title
        task.status = TaskStatus.DISMISSED.value
        _stamp(task, None)
        db.add(TaskFeedback(
            task_id=task.id, user_id=user.id, feedback_type="calendar_event_deleted",
            old_value={"event_id": task.calendar_event_id},
        ))
        db.add(Notification(
            user_id=user.id, kind="INFO", title="Calendar event deleted",
            message=f"“{old_title}” was removed from Today because its Google Calendar event was deleted.",
        ))
        return "dismissed"

    if remote.get("etag") and remote.get("etag") == task.calendar_etag:
        return "noop"
    if local_changed:
        # Both sides changed since the last sync: the later edit wins.
        remote_updated = tu.parse_google_timestamp(remote.get("updated"))
        if remote_updated is None or (task.updated_at and remote_updated <= task.updated_at):
            return "noop"

    start, all_day = tu.from_google(remote["start"], tz)
    if all_day:
        hour, minute = (int(part) for part in (user.workday_start or "09:00").split(":"))
        start = start.replace(hour=hour, minute=minute)
    else:
        end, _ = tu.from_google(remote["end"], tz)
        task.estimated_effort_minutes = max(
            MIN_EVENT_MINUTES, min(MAX_EVENT_MINUTES, int((end - start).total_seconds() // 60)))
    title = (remote.get("summary") or "").strip()
    if title:
        task.title = title
    task.deadline = start
    _stamp(task, remote)
    return "updated"


def _set(row, **values) -> bool:
    changed = False
    for key, value in values.items():
        if getattr(row, key) != value:
            setattr(row, key, value)
            changed = True
    return changed


def upsert_event_row(db: Session, user: User, remote: dict, tz, origin: str = "GOOGLE") -> bool:
    """Cache an unlinked event for Today. Returns True if anything changed."""
    if not remote.get("start") or not remote.get("end"):
        return False
    start, all_day = tu.from_google(remote["start"], tz)
    end, _ = tu.from_google(remote["end"], tz)
    row = db.query(CalendarEvent).filter_by(user_id=user.id, google_event_id=remote["id"]).first()
    created = row is None
    if created:
        row = CalendarEvent(user_id=user.id, google_event_id=remote["id"], origin=origin, start_at=start, end_at=end)
        db.add(row)
    changed = _set(
        row, summary=(remote.get("summary") or "(No title)")[:500], location=(remote.get("location") or "")[:300],
        html_link=remote.get("htmlLink") or "", start_at=start, end_at=end, all_day=all_day,
    )
    return created or changed


def _marker(remote: dict) -> str | None:
    return ((remote.get("extendedProperties") or {}).get("private") or {}).get(TASK_MARKER)


def reconcile_event(db: Session, user: User, client: CalendarClient, event_id: str, tz) -> None:
    """Re-read one event from Google and apply it locally (used after assistant writes)."""
    remote = client.get_event(event_id)
    task = db.query(Task).filter_by(user_id=user.id, calendar_event_id=event_id).first()
    if task:
        pull_task(db, user, task, remote, tz)
    elif remote is None or remote.get("status") == "cancelled":
        db.query(CalendarEvent).filter_by(user_id=user.id, google_event_id=event_id).delete()
    else:
        upsert_event_row(db, user, remote, tz)
    db.commit()


# ---------------------------------------------------------------- conflicts

def overlapping(events: list[dict], start: datetime, end: datetime, tz, *,
                ignore_id: str | None = None, include_task_events: bool = True) -> list[dict]:
    """Timed, busy events overlapping [start, end) — the calendar conflict check."""
    found = []
    for event in events:
        if event.get("id") == ignore_id or event.get("status") == "cancelled":
            continue
        if event.get("transparency") == "transparent":  # marked "free"
            continue
        if not include_task_events and _marker(event):
            continue
        if not event.get("start") or not event.get("end"):
            continue
        ev_start, all_day = tu.from_google(event["start"], tz)
        ev_end, _ = tu.from_google(event["end"], tz)
        if all_day:
            continue
        if ev_start < end and ev_end > start:
            found.append({
                "id": event.get("id"), "title": event.get("summary") or "(No title)",
                "start": ev_start.isoformat(), "end": ev_end.isoformat(),
            })
    return found


# ---------------------------------------------------------------- full sync

def sync_window(tz) -> tuple[datetime, datetime]:
    now = tu.now_local(tz)
    return tu.start_of_day(now), now + timedelta(days=settings.calendar_sync_window_days)


def _mark_reauth(db: Session, connection: CalendarConnection, message: str) -> None:
    connection.needs_reauth = True
    connection.last_error = message
    db.commit()


def sync_user(db: Session, user: User, client: CalendarClient | None = None) -> SyncResult:
    """Pull calendar changes into Today, then push task changes to Calendar."""
    connection = user.calendar_connection
    result = SyncResult(connected=bool(connection))
    if not connection:
        return result
    if connection.needs_reauth:
        result.needs_reauth = True
        result.error = connection.last_error or "Reconnect Google Calendar to resume syncing."
        return result

    tz = tu.user_tz(user)
    window = sync_window(tz)
    try:
        client = client or make_client(connection)
        remote_events = client.list_events(tu.rfc3339(window[0], tz), tu.rfc3339(window[1], tz))
    except CalendarAuthError as exc:
        _mark_reauth(db, connection, str(exc))
        result.needs_reauth, result.error = True, str(exc)
        return result
    except CalendarError as exc:
        result.error = str(exc)
        return result

    try:
        by_id = {event["id"]: event for event in remote_events if event.get("id")}

        # ---- pull: linked tasks ----
        linked = db.query(Task).filter(Task.user_id == user.id, Task.calendar_event_id.isnot(None)).all()
        linked_ids = {task.calendar_event_id for task in linked}
        known_task_ids = {task_id for (task_id,) in db.query(Task.id).filter(Task.user_id == user.id).all()}
        lookups = 0
        for task in linked:
            if task.status != TaskStatus.OPEN.value:
                continue
            remote = by_id.get(task.calendar_event_id)
            if remote is None:
                # Not in the listed window: it was moved out of it or deleted. Ask directly.
                if task.deadline is None or not (window[0] <= task.deadline <= window[1]) or lookups >= MAX_REMOTE_LOOKUPS:
                    continue
                lookups += 1
                remote = client.get_event(task.calendar_event_id)
            outcome = pull_task(db, user, task, remote, tz)
            if outcome != "noop":
                result.pulled += 1
                result.changed = True

        # ---- pull: events that don't belong to a task ----
        seen: set[str] = set()
        for event in remote_events:
            event_id = event.get("id")
            if not event_id or event.get("status") == "cancelled" or event_id in linked_ids:
                continue
            if _marker(event) in known_task_ids:
                continue  # our own task event whose link was lost; the push below re-adopts it
            seen.add(event_id)
            if upsert_event_row(db, user, event, tz):
                result.changed = True
        stale = db.query(CalendarEvent).filter(
            CalendarEvent.user_id == user.id, CalendarEvent.end_at > window[0], CalendarEvent.start_at < window[1],
        ).all()
        for row in stale:
            if row.google_event_id not in seen:
                db.delete(row)
                result.changed = True
        db.query(CalendarEvent).filter(
            CalendarEvent.user_id == user.id, CalendarEvent.end_at <= window[0] - timedelta(days=1),
        ).delete()
        db.commit()

        # ---- push: task -> event ----
        candidates = db.query(Task).filter(
            Task.user_id == user.id,
            or_(Task.calendar_event_id.isnot(None),
                and_(Task.status == TaskStatus.OPEN.value, Task.deadline.isnot(None))),
        ).all()
        for task in candidates:
            try:
                outcome = push_task(db, task, client, tz, window)
            except CalendarAuthError:
                raise
            except CalendarError as exc:
                logger.warning("Calendar push failed for a task: %s", exc)
                result.error = str(exc)
                db.rollback()
                continue
            if outcome == "noop":
                continue
            db.commit()
            result.changed = True
            setattr(result, outcome, getattr(result, outcome) + 1)
            if outcome == "created":
                clashes = overlapping(
                    remote_events, task.deadline, task.deadline + timedelta(minutes=_duration_minutes(task)),
                    tz, include_task_events=False)
                if clashes:
                    result.conflicts.append({"task_id": task.id, "title": task.title, "conflicts_with": clashes})

        connection.last_synced_at = datetime.utcnow()
        connection.last_error = None
        db.commit()
    except CalendarAuthError as exc:
        db.rollback()
        _mark_reauth(db, connection, str(exc))
        result.needs_reauth, result.error = True, str(exc)
    except CalendarError as exc:
        db.rollback()
        result.error = str(exc)
    return result


def sync_task_safe(db: Session, user: User, task: Task) -> None:
    """Mirror one task change to Calendar right away. Never raises: a Calendar
    problem must not make a normal task edit fail (the next full sync retries)."""
    connection = user.calendar_connection
    if not connection or connection.needs_reauth:
        return
    if not (task.calendar_event_id or wants_event(task)):
        return
    try:
        tz = tu.user_tz(user)
        push_task(db, task, make_client(connection), tz, sync_window(tz))
        db.commit()
    except CalendarAuthError as exc:
        db.rollback()
        _mark_reauth(db, connection, str(exc))
    except Exception:  # noqa: BLE001 - see docstring
        db.rollback()
        logger.exception("Calendar sync for a task failed")
