import unittest
from datetime import timedelta
from unittest.mock import patch

from app.gcal import sync
from app.gcal import timeutil as tu
from app.gcal.client import CalendarAuthError, CalendarError
from app.models import CalendarEvent, Notification, TaskFeedback, TaskStatus
from tests.support import DbTestCase, FakeCalendar, TZ_NAME


class PushTests(DbTestCase):
    def setUp(self):
        super().setUp()
        self.cal = FakeCalendar()
        self.connect_calendar()

    def run_sync(self):
        self.db.refresh(self.user)
        return sync.sync_user(self.db, self.user, client=self.cal)

    def test_task_with_deadline_becomes_one_event_with_stored_id(self):
        task = self.add_task("Submit physics lab", hours_ahead=3, effort=45)
        result = self.run_sync()
        self.db.refresh(task)
        self.assertEqual(result.created, 1)
        self.assertEqual(len(self.cal.live_events()), 1)
        event = self.cal.live_events()[0]
        self.assertEqual(task.calendar_event_id, event["id"])
        self.assertEqual(event["id"], sync.event_id_for_task(task.id))
        self.assertEqual(event["summary"], "Submit physics lab")
        self.assertEqual(event["start"]["timeZone"], TZ_NAME)
        # starts at the deadline's wall-clock time, lasts the estimated effort
        self.assertEqual(event["start"]["dateTime"], task.deadline.isoformat())
        self.assertEqual(event["end"]["dateTime"], (task.deadline + timedelta(minutes=45)).isoformat())

    def test_repeated_syncs_never_duplicate(self):
        self.add_task()
        for _ in range(4):
            self.run_sync()
        self.assertEqual(len(self.cal.live_events()), 1)
        self.assertEqual(self.cal.count("insert"), 1)
        self.assertEqual(self.cal.count("patch"), 0)

    def test_lost_link_adopts_existing_event_instead_of_duplicating(self):
        task = self.add_task()
        self.run_sync()
        task.calendar_event_id = task.calendar_etag = task.calendar_hash = None  # e.g. DB restored from backup
        self.db.commit()
        self.run_sync()
        self.assertEqual(len(self.cal.live_events()), 1)
        self.db.refresh(task)
        self.assertEqual(task.calendar_event_id, sync.event_id_for_task(task.id))

    def test_task_edit_updates_the_same_event(self):
        task = self.add_task()
        self.run_sync()
        task.title = "Submit physics lab report"
        task.deadline = task.deadline + timedelta(hours=1)
        self.db.commit()
        result = self.run_sync()
        self.assertEqual(result.updated, 1)
        event = self.cal.live_events()[0]
        self.assertEqual(len(self.cal.live_events()), 1)
        self.assertEqual(event["summary"], "Submit physics lab report")
        self.assertEqual(event["start"]["dateTime"], task.deadline.isoformat())

    def test_rescoring_a_task_does_not_touch_the_calendar(self):
        task = self.add_task()
        self.run_sync()
        task.priority, task.priority_score = "P0", 99.0  # what a scan's re-scoring does
        self.db.commit()
        self.run_sync()
        self.assertEqual(self.cal.count("patch"), 0)

    def test_completing_or_dismissing_removes_the_event_and_it_stays_gone(self):
        done, dismissed = self.add_task("Done one"), self.add_task("Dismissed one", hours_ahead=4)
        self.run_sync()
        self.assertEqual(len(self.cal.live_events()), 2)
        done.status, dismissed.status = TaskStatus.COMPLETED.value, TaskStatus.DISMISSED.value
        self.db.commit()
        result = self.run_sync()
        self.assertEqual(result.deleted, 2)
        self.assertEqual(self.cal.live_events(), [])
        self.run_sync()
        self.assertEqual(self.cal.live_events(), [])  # no resurrection

    def test_removing_the_deadline_removes_the_event(self):
        task = self.add_task()
        self.run_sync()
        task.deadline = None
        self.db.commit()
        self.run_sync()
        self.assertEqual(self.cal.live_events(), [])

    def test_tasks_outside_the_sync_window_are_not_pushed(self):
        self.add_task("Overdue", hours_ahead=-72)
        self.add_task("Far future", hours_ahead=24 * 90)
        self.add_task("No date", hours_ahead=None)
        self.run_sync()
        self.assertEqual(self.cal.live_events(), [])

    def test_new_event_overlapping_an_existing_one_is_reported_not_blocked(self):
        clash_start = self.now() + timedelta(hours=3)
        self.cal.user_creates("meeting1", "Team standup", clash_start, clash_start + timedelta(minutes=30))
        self.add_task("Submit physics lab", hours_ahead=3)
        result = self.run_sync()
        self.assertEqual(result.created, 1)
        self.assertEqual(len(result.conflicts), 1)
        self.assertEqual(result.conflicts[0]["conflicts_with"][0]["title"], "Team standup")


class PullTests(DbTestCase):
    def setUp(self):
        super().setUp()
        self.cal = FakeCalendar()
        self.connect_calendar()

    def run_sync(self):
        self.db.refresh(self.user)
        return sync.sync_user(self.db, self.user, client=self.cal)

    def test_event_created_in_calendar_appears_but_is_not_a_task(self):
        start = self.now() + timedelta(hours=2)
        self.cal.user_creates("ev1", "Dentist", start, start + timedelta(hours=1), location="Clinic")
        result = self.run_sync()
        self.assertTrue(result.changed)
        row = self.db.query(CalendarEvent).one()
        self.assertEqual((row.summary, row.location, row.origin), ("Dentist", "Clinic", "GOOGLE"))
        self.assertEqual(row.start_at, start)
        from app.models import Task
        self.assertEqual(self.db.query(Task).count(), 0)  # Overview/Week/etc. never see it

    def test_event_edited_and_deleted_in_calendar_is_reflected(self):
        start = self.now() + timedelta(hours=2)
        self.cal.user_creates("ev1", "Dentist", start, start + timedelta(hours=1))
        self.run_sync()
        self.cal.user_edits("ev1", summary="Dentist (moved)", start=tu.to_google(start + timedelta(hours=1), self.tz),
                            end=tu.to_google(start + timedelta(hours=2), self.tz))
        self.run_sync()
        row = self.db.query(CalendarEvent).one()
        self.assertEqual((row.summary, row.start_at), ("Dentist (moved)", start + timedelta(hours=1)))
        self.cal.user_deletes("ev1")
        self.run_sync()
        self.assertEqual(self.db.query(CalendarEvent).count(), 0)

    def test_unchanged_calendar_reports_no_change(self):
        start = self.now() + timedelta(hours=2)
        self.cal.user_creates("ev1", "Dentist", start, start + timedelta(hours=1))
        self.run_sync()
        self.assertFalse(self.run_sync().changed)

    def test_calendar_edit_of_a_synced_task_updates_the_task_without_echoing_back(self):
        task = self.add_task("Submit physics lab", hours_ahead=3)
        self.run_sync()
        event_id = task.calendar_event_id
        new_start = self.now() + timedelta(hours=6)
        self.cal.user_edits(event_id, summary="Submit physics lab (final)",
                            start=tu.to_google(new_start, self.tz), end=tu.to_google(new_start + timedelta(minutes=90), self.tz))
        patches_before = self.cal.count("patch")
        result = self.run_sync()
        self.db.refresh(task)
        self.assertEqual(result.pulled, 1)
        self.assertEqual((task.title, task.deadline, task.estimated_effort_minutes),
                         ("Submit physics lab (final)", new_start, 90))
        self.assertEqual(self.cal.count("patch"), patches_before)  # no echo write
        self.assertFalse(self.run_sync().changed)

    def test_event_in_other_timezone_maps_to_the_users_wall_clock(self):
        task = self.add_task(hours_ahead=3)
        self.run_sync()
        target = self.now() + timedelta(hours=5)  # IST wall time
        utc_equivalent = (target - timedelta(hours=5, minutes=30)).isoformat() + "Z"
        self.cal.user_edits(task.calendar_event_id, start={"dateTime": utc_equivalent},
                            end={"dateTime": (target + timedelta(minutes=30) - timedelta(hours=5, minutes=30)).isoformat() + "Z"})
        self.run_sync()
        self.db.refresh(task)
        self.assertEqual(task.deadline, target)

    def test_deleting_a_synced_event_in_calendar_dismisses_the_task_and_says_so(self):
        task = self.add_task("Submit physics lab")
        self.run_sync()
        self.cal.user_deletes(task.calendar_event_id)
        result = self.run_sync()
        self.db.refresh(task)
        self.assertEqual(task.status, TaskStatus.DISMISSED.value)
        self.assertEqual(result.pulled, 1)
        self.assertEqual(self.db.query(Notification).filter_by(title="Calendar event deleted").count(), 1)
        self.assertEqual(self.db.query(TaskFeedback).filter_by(feedback_type="calendar_event_deleted").count(), 1)
        self.run_sync()
        self.assertEqual(self.cal.live_events(), [])  # not re-created

    def test_local_edit_beats_a_remote_deletion(self):
        task = self.add_task("Submit physics lab")
        self.run_sync()
        self.cal.user_deletes(task.calendar_event_id)
        task.deadline = task.deadline + timedelta(hours=1)  # edited in the app before the next sync
        self.db.commit()
        self.run_sync()
        self.db.refresh(task)
        self.assertEqual(task.status, TaskStatus.OPEN.value)
        self.assertEqual(len(self.cal.live_events()), 1)
        self.assertEqual(self.cal.live_events()[0]["start"]["dateTime"], task.deadline.isoformat())

    def test_event_moved_outside_the_window_is_still_followed(self):
        task = self.add_task(hours_ahead=3)
        self.run_sync()
        far = self.now() + timedelta(days=60)
        self.cal.user_edits(task.calendar_event_id, start=tu.to_google(far, self.tz),
                            end=tu.to_google(far + timedelta(minutes=30), self.tz))
        self.run_sync()
        self.db.refresh(task)
        self.assertEqual(task.deadline, far)
        self.assertEqual(task.status, TaskStatus.OPEN.value)

    def test_task_events_are_not_listed_as_separate_calendar_events(self):
        self.add_task()
        self.run_sync()
        self.run_sync()
        self.assertEqual(self.db.query(CalendarEvent).count(), 0)


class FailureTests(DbTestCase):
    def setUp(self):
        super().setUp()
        self.cal = FakeCalendar()
        self.connect_calendar()

    def test_revoked_access_flags_reconnect_and_stops_calling_google(self):
        self.add_task()
        self.cal.fail_with = CalendarAuthError("revoked")
        self.db.refresh(self.user)
        result = sync.sync_user(self.db, self.user, client=self.cal)
        self.assertTrue(result.needs_reauth)
        self.db.refresh(self.user)
        self.assertTrue(self.user.calendar_connection.needs_reauth)
        calls = len(self.cal.calls)
        self.assertTrue(sync.sync_user(self.db, self.user, client=self.cal).needs_reauth)
        self.assertEqual(len(self.cal.calls), calls)

    def test_calendar_outage_is_reported_and_loses_nothing(self):
        task = self.add_task()
        self.cal.fail_with = CalendarError("Could not reach Google Calendar")
        self.db.refresh(self.user)
        result = sync.sync_user(self.db, self.user, client=self.cal)
        self.assertEqual(result.error, "Could not reach Google Calendar")
        self.cal.fail_with = None
        self.assertEqual(sync.sync_user(self.db, self.user, client=self.cal).created, 1)
        self.db.refresh(task)
        self.assertIsNotNone(task.calendar_event_id)

    def test_single_task_hook_never_raises(self):
        task = self.add_task()
        self.cal.fail_with = RuntimeError("boom")
        self.db.refresh(self.user)
        with patch("app.gcal.sync.make_client", return_value=self.cal):
            sync.sync_task_safe(self.db, self.user, task)  # must not raise
        self.cal.fail_with = None
        with patch("app.gcal.sync.make_client", return_value=self.cal):
            sync.sync_task_safe(self.db, self.user, task)
        self.assertEqual(len(self.cal.live_events()), 1)

    def test_no_calendar_connection_is_a_quiet_noop(self):
        from app.models import CalendarConnection
        self.db.query(CalendarConnection).delete()
        self.db.commit()
        self.db.refresh(self.user)
        task = self.add_task()
        self.assertFalse(sync.sync_user(self.db, self.user, client=self.cal).connected)
        sync.sync_task_safe(self.db, self.user, task)
        self.assertEqual(self.cal.calls, [])


if __name__ == "__main__":
    unittest.main()
