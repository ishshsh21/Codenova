"""
Calendar actions used by the AI assistant: list, create, update, delete.

Every function returns plain JSON-serialisable data for the model, and raises
CalendarOpsError (with a user-safe message) when it cannot proceed. Creating or
moving an event first checks the live calendar for conflicts and, unless told to
ignore them, returns the clash plus a suggested free slot instead of writing.
"""
from __future__ import annotations

import uuid
from datetime import datetime, time, timedelta

from sqlalchemy.orm import Session

from app.gcal import sync
from app.gcal import timeutil as tu
from app.gcal.client import CalendarAuthError, CalendarClient, CalendarError
from app.models import User

MAX_TITLE = 200
MAX_DESCRIPTION = 2000
MAX_LOCATION = 300
MAX_DURATION = timedelta(hours=24)
LIST_LIMIT = 25


class CalendarOpsError(Exception):
    """A problem the assistant can relay to the user as-is."""


def _context(db: Session, user: User):
    connection = user.calendar_connection
    if not connection:
        raise CalendarOpsError("Google Calendar is not connected. Use “Connect Calendar” on the Today page first.")
    if connection.needs_reauth:
        raise CalendarOpsError("Google Calendar needs to be reconnected on the Today page.")
    try:
        return sync.make_client(connection), tu.user_tz(user)
    except CalendarAuthError as exc:
        sync._mark_reauth(db, connection, str(exc))
        raise CalendarOpsError("Google Calendar needs to be reconnected on the Today page.") from exc


def _guarded(db: Session, user: User, fn):
    """Run a calendar call, turning API failures into CalendarOpsError."""
    try:
        return fn()
    except CalendarAuthError as exc:
        if user.calendar_connection:
            sync._mark_reauth(db, user.calendar_connection, str(exc))
        raise CalendarOpsError("Google Calendar needs to be reconnected on the Today page.") from exc
    except CalendarError as exc:
        raise CalendarOpsError(str(exc)) from exc


def _brief(event: dict, tz) -> dict:
    start, all_day = tu.from_google(event["start"], tz)
    end, _ = tu.from_google(event["end"], tz)
    return {
        "id": event["id"], "title": event.get("summary") or "(No title)",
        "start": start.isoformat(), "end": end.isoformat(), "all_day": all_day,
        "location": event.get("location") or "", "synced_with_task": bool(sync._marker(event)),
    }


def _clean(value: str | None, limit: int) -> str:
    return (value or "").strip()[:limit]


def _check_span(start: datetime, end: datetime) -> None:
    if end <= start:
        raise CalendarOpsError("The end time must be after the start time.")
    if end - start > MAX_DURATION:
        raise CalendarOpsError("Events longer than 24 hours aren't supported here.")


def suggest_free_slot(events: list[dict], tz, start: datetime, duration: timedelta,
                      workday_start: str, workday_end: str) -> datetime | None:
    """First gap of `duration` on start's day, inside working hours, at/after `start`."""
    day = start.date()
    open_at = datetime.combine(day, time(*map(int, workday_start.split(":"))))
    close_at = datetime.combine(day, time(*map(int, workday_end.split(":"))))
    busy = []
    for event in events:
        if event.get("status") == "cancelled" or event.get("transparency") == "transparent":
            continue
        ev_start, all_day = tu.from_google(event["start"], tz)
        ev_end, _ = tu.from_google(event["end"], tz)
        if not all_day:
            busy.append((ev_start, ev_end))
    cursor = max(start, open_at)
    for ev_start, ev_end in sorted(busy):
        if ev_end <= cursor:
            continue
        if ev_start >= cursor + duration:
            break
        cursor = max(cursor, ev_end)
    return cursor if cursor + duration <= close_at else None


def _conflict_reply(client: CalendarClient, user: User, tz, start: datetime, end: datetime,
                    conflicts: list[dict], action: str) -> dict:
    day_start = tu.start_of_day(start)
    day_events = client.list_events(tu.rfc3339(day_start, tz), tu.rfc3339(day_start + timedelta(days=1), tz))
    slot = suggest_free_slot(day_events, tz, start, end - start, user.workday_start or "09:00", user.workday_end or "18:00")
    return {
        action: False, "conflict": True, "conflicts": conflicts,
        "suggested_start": slot.isoformat() if slot else None,
        "message": "This overlaps an existing event. Tell the user, offer the suggested time, "
                   "and only retry with ignore_conflicts=true if they insist.",
    }


# ---------------------------------------------------------------- operations

def list_events(db: Session, user: User, start: datetime, end: datetime) -> dict:
    client, tz = _context(db, user)
    events = _guarded(db, user, lambda: client.list_events(tu.rfc3339(start, tz), tu.rfc3339(end, tz)))
    return {
        "timezone": tz.key,
        "events": [_brief(event, tz) for event in events[:LIST_LIMIT]],
        "truncated": len(events) > LIST_LIMIT,
    }


def create_event(db: Session, user: User, title: str, start: datetime, end: datetime,
                 description: str = "", location: str = "", ignore_conflicts: bool = False) -> dict:
    title = _clean(title, MAX_TITLE)
    if not title:
        raise CalendarOpsError("An event needs a title.")
    _check_span(start, end)
    client, tz = _context(db, user)

    def run() -> dict:
        nearby = client.list_events(tu.rfc3339(start, tz), tu.rfc3339(end, tz))
        conflicts = sync.overlapping(nearby, start, end, tz)
        if conflicts and not ignore_conflicts:
            return _conflict_reply(client, user, tz, start, end, conflicts, "created")
        event = client.insert_event({
            "id": uuid.uuid4().hex, "summary": title,
            "description": _clean(description, MAX_DESCRIPTION), "location": _clean(location, MAX_LOCATION),
            "start": tu.to_google(start, tz), "end": tu.to_google(end, tz),
            "extendedProperties": {"private": {"workdaySignalSource": "assistant"}},
        })
        sync.upsert_event_row(db, user, event, tz, origin="ASSISTANT")
        db.commit()
        return {"created": True, "event": _brief(event, tz), "ignored_conflicts": conflicts}

    return _guarded(db, user, run)


def update_event(db: Session, user: User, event_id: str, *, title: str | None = None,
                 start: datetime | None = None, end: datetime | None = None,
                 description: str | None = None, location: str | None = None,
                 ignore_conflicts: bool = False) -> dict:
    client, tz = _context(db, user)

    def run() -> dict:
        event = client.get_event(event_id)
        if event is None or event.get("status") == "cancelled":
            raise CalendarOpsError("That calendar event no longer exists.")
        current_start, _ = tu.from_google(event["start"], tz)
        current_end, _ = tu.from_google(event["end"], tz)
        new_start = start or current_start
        new_end = end or current_end
        if start and not end:
            new_end = start + (current_end - current_start)  # keep the length when only moving it
        _check_span(new_start, new_end)

        body: dict = {}
        if title is not None:
            if not _clean(title, MAX_TITLE):
                raise CalendarOpsError("An event needs a title.")
            body["summary"] = _clean(title, MAX_TITLE)
        if description is not None:
            body["description"] = _clean(description, MAX_DESCRIPTION)
        if location is not None:
            body["location"] = _clean(location, MAX_LOCATION)
        if start or end:
            body["start"], body["end"] = tu.to_google(new_start, tz), tu.to_google(new_end, tz)
            nearby = client.list_events(tu.rfc3339(new_start, tz), tu.rfc3339(new_end, tz))
            conflicts = sync.overlapping(nearby, new_start, new_end, tz, ignore_id=event_id)
            if conflicts and not ignore_conflicts:
                return _conflict_reply(client, user, tz, new_start, new_end, conflicts, "updated")
        if not body:
            raise CalendarOpsError("There was nothing to change.")

        updated = client.patch_event(event_id, body)
        if updated is None:
            raise CalendarOpsError("That calendar event no longer exists.")
        sync.reconcile_event(db, user, client, event_id, tz)
        return {"updated": True, "event": _brief(updated, tz)}

    return _guarded(db, user, run)


def delete_event(db: Session, user: User, event_id: str) -> dict:
    client, tz = _context(db, user)

    def run() -> dict:
        event = client.get_event(event_id)
        if event is None or event.get("status") == "cancelled":
            raise CalendarOpsError("That calendar event no longer exists.")
        title = event.get("summary") or "(No title)"
        client.delete_event(event_id)
        sync.reconcile_event(db, user, client, event_id, tz)
        return {"deleted": True, "title": title}

    return _guarded(db, user, run)

