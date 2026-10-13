"""In-memory stand-in for the Google Calendar client, used by tests (and the manual e2e script)."""
import copy
from datetime import datetime
from zoneinfo import ZoneInfo

from app.gcal import timeutil as tu
from app.gcal.client import CalendarConflict

TZ_NAME = "Asia/Kolkata"


class FakeCalendar:
    """In-memory stand-in for CalendarClient with Google's relevant behaviour:
    custom-ID inserts 409 on a duplicate (even after delete), deleted events stay
    readable as status "cancelled", and listing hides cancelled events."""

    def __init__(self):
        self.events: dict[str, dict] = {}
        self.calls: list[tuple] = []
        self._version = 0
        self.fail_with: Exception | None = None

    def _touch(self, event):
        self._version += 1
        event["etag"] = f'"v{self._version}"'
        event["updated"] = datetime.utcnow().isoformat() + "Z"
        event.setdefault("htmlLink", f"https://calendar.google.com/event?eid={event['id']}")
        return event

    def _maybe_fail(self):
        if self.fail_with:
            raise self.fail_with

    @staticmethod
    def _span(event):
        def parse(point):
            if "date" in point:
                return datetime.fromisoformat(point["date"]).replace(tzinfo=ZoneInfo(TZ_NAME))
            value = datetime.fromisoformat(point["dateTime"])
            return value if value.tzinfo else value.replace(tzinfo=ZoneInfo(point.get("timeZone", TZ_NAME)))
        return parse(event["start"]), parse(event["end"])

    # ---- CalendarClient interface ----
    def list_events(self, time_min, time_max, limit=1000):
        self._maybe_fail(); self.calls.append(("list",))
        lo, hi = datetime.fromisoformat(time_min), datetime.fromisoformat(time_max)
        out = []
        for event in self.events.values():
            if event["status"] == "cancelled":
                continue
            start, end = self._span(event)
            if start < hi and end > lo:
                out.append(copy.deepcopy(event))
        return sorted(out, key=lambda e: self._span(e)[0])

    def get_event(self, event_id):
        self._maybe_fail(); self.calls.append(("get", event_id))
        return copy.deepcopy(self.events[event_id]) if event_id in self.events else None

    def insert_event(self, body):
        self._maybe_fail(); self.calls.append(("insert", body["id"]))
        if body["id"] in self.events:
            raise CalendarConflict("exists")
        event = {"status": "confirmed", **copy.deepcopy(body)}
        self.events[body["id"]] = self._touch(event)
        return copy.deepcopy(event)

    def patch_event(self, event_id, body):
        self._maybe_fail(); self.calls.append(("patch", event_id))
        if event_id not in self.events:
            return None
        self.events[event_id].update(copy.deepcopy(body))
        self._touch(self.events[event_id])
        return copy.deepcopy(self.events[event_id])

    def delete_event(self, event_id):
        self._maybe_fail(); self.calls.append(("delete", event_id))
        if event_id in self.events:
            self.events[event_id]["status"] = "cancelled"
            self._touch(self.events[event_id])

    # ---- helpers that act as "the user, in Google Calendar" ----
    def user_creates(self, event_id, summary, start, end, **extra):
        event = {"id": event_id, "status": "confirmed", "summary": summary,
                 "start": tu.to_google(start, ZoneInfo(TZ_NAME)), "end": tu.to_google(end, ZoneInfo(TZ_NAME)), **extra}
        self.events[event_id] = self._touch(event)

    def user_edits(self, event_id, **changes):
        self.events[event_id].update(changes)
        self._touch(self.events[event_id])

    def user_deletes(self, event_id):
        self.events[event_id]["status"] = "cancelled"
        self._touch(self.events[event_id])

    def count(self, kind):
        return sum(1 for call in self.calls if call[0] == kind)

    def live_events(self):
        return [e for e in self.events.values() if e["status"] != "cancelled"]
