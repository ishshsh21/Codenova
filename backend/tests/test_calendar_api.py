import unittest
import urllib.parse
from datetime import timedelta
from unittest.mock import patch

from app.config import get_settings
from app.models import CalendarConnection, CalendarEvent, Task, TaskStatus, User
from app.security import decrypt_token
from tests.support import DbTestCase, FakeCalendar, FakeGoogleHttp, api_client, state_from

CAL_SCOPE = "https://www.googleapis.com/auth/calendar.events"


class CalendarApiCase(DbTestCase):
    def setUp(self):
        super().setUp()
        self.cal = FakeCalendar()
        self.http = api_client(self.user)
        patcher = patch("app.gcal.sync.make_client", return_value=self.cal)
        patcher.start(); self.addCleanup(patcher.stop)


class ConnectFlowTests(CalendarApiCase):
    def start(self):
        response = self.http.post("/api/calendar/connect")
        self.assertEqual(response.status_code, 200)
        return response.json()["authorization_url"]

    def test_status_before_connecting(self):
        self.assertEqual(self.http.get("/api/calendar/status").json()["connected"], False)

    def test_consent_url_asks_only_for_calendar_events_and_lets_the_user_pick_an_account(self):
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.start()).query)
        scopes = query["scope"][0].split()
        self.assertIn(CAL_SCOPE, scopes)
        self.assertFalse([s for s in scopes if "gmail" in s])
        self.assertEqual(query["access_type"], ["offline"])
        self.assertEqual(query["prompt"], ["select_account consent"])
        self.assertEqual(query["code_challenge_method"], ["S256"])
        self.assertEqual(query["redirect_uri"], [get_settings().google_redirect_uri])  # no new URI to register

    def test_callback_stores_an_encrypted_token_and_lands_back_on_today(self):
        state = state_from(self.start())
        google = FakeGoogleHttp(email="me@school.edu", sub="sub-1", refresh_token="cal-refresh-123", scope=CAL_SCOPE)
        with patch("httpx.AsyncClient", google):
            response = self.http.get(f"/api/auth/google/callback?code=abc&state={state}")
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.headers["location"].endswith("/today?calendar=connected"))
        status = self.http.get("/api/calendar/status").json()
        self.assertEqual((status["connected"], status["google_account_email"], status["needs_reauth"]), (True, "me@school.edu", False))
        stored = self.db.query(CalendarConnection).one()
        self.assertNotIn("cal-refresh-123", stored.encrypted_refresh_token)
        self.assertEqual(decrypt_token(stored.encrypted_refresh_token), "cal-refresh-123")
        self.assertEqual(google.posts[0]["code_verifier"] is not None, True)  # PKCE verifier was sent

    def test_a_state_can_only_be_used_once(self):
        state = state_from(self.start())
        with patch("httpx.AsyncClient", FakeGoogleHttp(scope=CAL_SCOPE)):
            self.http.get(f"/api/auth/google/callback?code=abc&state={state}")
            replay = self.http.get(f"/api/auth/google/callback?code=abc&state={state}")
        self.assertEqual(replay.status_code, 400)

    def test_callback_without_the_starting_users_session_is_rejected(self):
        state = state_from(self.start())
        other = User(google_subject_id="sub-2", email="other@x.com", name="Other"); self.db.add(other); self.db.commit()
        for client in (api_client(other), self._anonymous()):
            state = state_from(self.start())
            with patch("httpx.AsyncClient", FakeGoogleHttp(scope=CAL_SCOPE)):
                response = client.get(f"/api/auth/google/callback?code=abc&state={state}")
            self.assertTrue(response.headers["location"].endswith("/today?calendar=error"))
        self.assertEqual(self.db.query(CalendarConnection).count(), 0)

    def _anonymous(self):
        from fastapi.testclient import TestClient
        from app.main import app
        return TestClient(app, base_url="http://localhost", follow_redirects=False)

    def test_denied_or_incomplete_consent_connects_nothing(self):
        cases = [
            ("error=access_denied", FakeGoogleHttp(scope=CAL_SCOPE)),                 # pressed Cancel
            ("code=abc", FakeGoogleHttp(scope="openid email")),                       # unticked the Calendar box
            ("code=abc", FakeGoogleHttp(scope=CAL_SCOPE, refresh_token=None)),        # no refresh token issued
        ]
        for params, google in cases:
            state = state_from(self.start())
            with patch("httpx.AsyncClient", google):
                response = self.http.get(f"/api/auth/google/callback?{params}&state={state}")
            self.assertTrue(response.headers["location"].endswith("/today?calendar=denied"), params)
        self.assertEqual(self.db.query(CalendarConnection).count(), 0)

    def test_connecting_a_different_google_account_drops_the_old_event_links(self):
        self.connect_calendar()
        self.db.query(CalendarConnection).update({"google_subject_id": "old-sub"})
        task = self.add_task(); task.calendar_event_id = "old-event"; self.db.commit()
        state = state_from(self.start())
        with patch("httpx.AsyncClient", FakeGoogleHttp(email="new@gmail.com", sub="new-sub", scope=CAL_SCOPE)):
            self.http.get(f"/api/auth/google/callback?code=abc&state={state}")
        self.db.refresh(task)
        self.assertIsNone(task.calendar_event_id)


class SyncApiTests(CalendarApiCase):
    def setUp(self):
        super().setUp()
        self.connect_calendar()

    def test_sync_returns_todays_events_and_never_creates_tasks_from_them(self):
        start = self.now() + timedelta(minutes=30)
        self.cal.user_creates("ev1", "Dentist", start, start + timedelta(hours=1))
        self.add_task("Submit physics lab", hours_ahead=3)
        tasks_before = self.db.query(Task).count()
        body = self.http.post("/api/calendar/sync").json()
        self.assertTrue(body["changed"])
        self.assertEqual([e["title"] for e in body["events"]], ["Dentist"])  # the task's own event is not listed twice
        self.assertEqual(body["created"], 1)
        self.assertEqual(self.db.query(Task).count(), tasks_before)
        self.assertEqual([e["title"] for e in self.http.get("/api/calendar/events").json()], ["Dentist"])
        agenda = self.http.get("/api/agenda/today").json()   # Overview/Today KPIs are untouched
        self.assertEqual(agenda["summary"]["actionable"], 1)

    def test_task_changes_reach_the_calendar_immediately(self):
        created = self.http.post("/api/tasks", json={"title": "Read chapter 4", "deadline": (self.now() + timedelta(hours=4)).isoformat()})
        self.assertEqual(created.status_code, 200)
        self.assertTrue(created.json()["calendar_synced"])
        self.assertEqual([e["summary"] for e in self.cal.live_events()], ["Read chapter 4"])
        task_id = created.json()["id"]

        patched = self.http.patch(f"/api/tasks/{task_id}", json={"title": "Read chapter 5"}).json()
        self.assertTrue(patched["calendar_synced"])
        self.assertEqual([e["summary"] for e in self.cal.live_events()], ["Read chapter 5"])
        self.assertEqual(len(self.cal.live_events()), 1)  # same event, no duplicate

        done = self.http.post(f"/api/tasks/{task_id}/complete").json()
        self.assertFalse(done["calendar_synced"])
        self.assertEqual(self.cal.live_events(), [])

    def test_dismiss_and_not_my_task_remove_the_event(self):
        ids = []
        for title in ("A", "B"):
            ids.append(self.http.post("/api/tasks", json={"title": title, "deadline": (self.now() + timedelta(hours=4)).isoformat()}).json()["id"])
        self.assertEqual(len(self.cal.live_events()), 2)
        self.http.post(f"/api/tasks/{ids[0]}/dismiss")
        self.http.post(f"/api/tasks/{ids[1]}/feedback", json={"feedback_type": "not_my_task"})
        self.assertEqual(self.cal.live_events(), [])

    def test_a_calendar_outage_never_breaks_a_normal_task_edit(self):
        self.cal.fail_with = RuntimeError("calendar is down")
        response = self.http.post("/api/tasks", json={"title": "Still saved", "deadline": (self.now() + timedelta(hours=4)).isoformat()})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.db.query(Task).filter_by(title="Still saved").count(), 1)

    def test_nothing_happens_without_a_calendar_connection(self):
        self.db.query(CalendarConnection).delete(); self.db.commit()
        body = self.http.post("/api/calendar/sync").json()
        self.assertEqual((body["connected"], body["changed"]), (False, False))
        self.http.post("/api/tasks", json={"title": "No calendar", "deadline": (self.now() + timedelta(hours=4)).isoformat()})
        self.assertEqual(self.cal.calls, [])

    def test_disconnect_clears_links_but_keeps_tasks_and_google_events(self):
        task = self.add_task(); self.http.post("/api/calendar/sync"); self.db.refresh(task)
        self.assertIsNotNone(task.calendar_event_id)
        self.assertEqual(self.http.delete("/api/calendar/disconnect").json(), {"disconnected": True})
        self.db.refresh(task)
        self.assertIsNone(task.calendar_event_id)
        self.assertEqual(self.db.query(CalendarConnection).count(), 0)
        self.assertEqual(len(self.cal.live_events()), 1)   # left alone in Google Calendar
        self.assertEqual(task.status, TaskStatus.OPEN.value)

    def test_reconnecting_adopts_the_existing_events_without_duplicating_them(self):
        task = self.add_task(); self.http.post("/api/calendar/sync")
        self.http.delete("/api/calendar/disconnect")
        self.connect_calendar()
        self.http.post("/api/calendar/sync")
        self.assertEqual(len(self.cal.live_events()), 1)

    def test_users_cannot_see_each_others_calendar_data(self):
        start = self.now() + timedelta(minutes=30)
        self.cal.user_creates("ev1", "Private appointment", start, start + timedelta(hours=1))
        self.http.post("/api/calendar/sync")
        other = User(google_subject_id="sub-2", email="other@x.com", name="Other"); self.db.add(other); self.db.commit()
        theirs = api_client(other)
        self.assertEqual(theirs.get("/api/calendar/events").json(), [])
        self.assertEqual(theirs.get("/api/calendar/status").json()["connected"], False)
        self.assertEqual(theirs.post("/api/calendar/sync").json()["connected"], False)

    def test_requires_sign_in(self):
        from fastapi.testclient import TestClient
        from app.main import app
        anon = TestClient(app, base_url="http://localhost")
        for method, path in (("get", "/api/calendar/status"), ("post", "/api/calendar/connect"),
                             ("post", "/api/calendar/sync"), ("get", "/api/calendar/events"), ("delete", "/api/calendar/disconnect")):
            self.assertEqual(getattr(anon, method)(path).status_code, 401, path)


if __name__ == "__main__":
    unittest.main()
