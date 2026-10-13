"""Shared test setup: a throwaway database and a fake Google Calendar."""
import copy
import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from tests import TEST_DB_DIR
from app.database import Base, SessionLocal, engine
from app.gcal import timeutil as tu
from app.gcal.client import CalendarConflict
from app.models import CalendarConnection, GmailConnection, Task, User
from app.security import encrypt_token
from tests.fake_calendar import FakeCalendar, TZ_NAME  # noqa: F401 - re-exported for the tests

class DbTestCase(unittest.TestCase):
    def setUp(self):
        # setUp drops every table: never let it run against a real database.
        assert str(engine.url).startswith(f"sqlite:///{TEST_DB_DIR}"), f"refusing to reset {engine.url!r}"
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        self.db = SessionLocal()
        self.tz = ZoneInfo(TZ_NAME)
        self.user = User(google_subject_id="sub-1", email="me@school.edu", name="Me", timezone=TZ_NAME)
        self.db.add(self.user)
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def now(self):
        return tu.now_local(self.tz).replace(second=0, microsecond=0)

    def connect_calendar(self):
        self.db.add(CalendarConnection(
            user_id=self.user.id, google_account_email="me@school.edu",
            encrypted_refresh_token=encrypt_token("calendar-refresh-token"), scopes="calendar.events"))
        self.db.commit()
        self.db.refresh(self.user)

    def add_task(self, title="Submit physics lab", hours_ahead=3, effort=30, **kw):
        task = Task(user_id=self.user.id, title=title, estimated_effort_minutes=effort,
                    deadline=(self.now() + timedelta(hours=hours_ahead)) if hours_ahead is not None else None, **kw)
        self.db.add(task)
        self.db.commit()
        return task


# ---------------------------------------------------------------- HTTP-level helpers

class FakeGoogleHttp:
    """Stands in for httpx.AsyncClient when the app talks to Google's token/userinfo endpoints."""

    def __init__(self, *, email="new@gmail.com", sub="sub-new", refresh_token="refresh-new", scope="", status=200):
        self.email, self.sub, self.refresh_token, self.scope, self.status = email, sub, refresh_token, scope, status
        self.posts = []

    def __call__(self, *args, **kwargs):  # httpx.AsyncClient(...)
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, data=None, **kwargs):
        from types import SimpleNamespace
        self.posts.append(data)
        body = {"access_token": "access-1", "refresh_token": self.refresh_token, "scope": self.scope}
        if not self.refresh_token:
            body.pop("refresh_token")
        return SimpleNamespace(status_code=self.status, json=lambda: body)

    async def get(self, url, headers=None, **kwargs):
        from types import SimpleNamespace
        return SimpleNamespace(status_code=200, json=lambda: {"sub": self.sub, "email": self.email, "name": "Test User"})


def api_client(user):
    """A TestClient signed in as `user` (no redirects followed, so 303s can be inspected)."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.security import SESSION_COOKIE_NAME, create_session_token
    client = TestClient(app, base_url="http://localhost", follow_redirects=False)
    client.cookies.set(SESSION_COOKIE_NAME, create_session_token(user.id))
    return client


def state_from(authorization_url):
    import urllib.parse
    return urllib.parse.parse_qs(urllib.parse.urlparse(authorization_url).query)["state"][0]
