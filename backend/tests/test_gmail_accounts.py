import unittest
from datetime import datetime
from unittest.mock import patch

from sqlalchemy import text

from app.database import engine, migrate_sqlite_schema
from app.gmail import sync as gmail_sync
from app.models import EmailMessage, GmailConnection, ScanRun, Task, TaskSource, User
from app.security import decrypt_token, encrypt_token
from tests.support import DbTestCase, FakeGoogleHttp, api_client, state_from

GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"


class AccountsCase(DbTestCase):
    def setUp(self):
        super().setUp()
        self.school = GmailConnection(
            user_id=self.user.id, google_account_email="me@school.edu", google_subject_id="sub-1", is_primary=True,
            label="School", encrypted_refresh_token=encrypt_token("school-token"), scopes=GMAIL_SCOPE)
        self.db.add(self.school); self.db.commit()
        self.http = api_client(self.user)

    def add_personal(self, label="Personal"):
        conn = GmailConnection(user_id=self.user.id, google_account_email="me@gmail.com", google_subject_id="sub-p",
                               label=label, encrypted_refresh_token=encrypt_token("personal-token"), scopes=GMAIL_SCOPE)
        self.db.add(conn); self.db.commit()
        return conn

    def other_user(self):
        other = User(google_subject_id="sub-2", email="other@x.com", name="Other")
        self.db.add(other); self.db.commit()
        conn = GmailConnection(user_id=other.id, google_account_email="other@x.com", google_subject_id="sub-2",
                               is_primary=True, encrypted_refresh_token=encrypt_token("other-token"))
        self.db.add(conn); self.db.commit()
        return other, conn

    def message(self, conn, subject, user=None):
        msg = EmailMessage(user_id=(user or self.user).id, gmail_message_id=f"m-{subject}-{conn.id[:4]}", gmail_thread_id=f"t-{subject}",
                           subject=subject, normalized_body="", connection_id=conn.id, account_email=conn.google_account_email)
        self.db.add(msg); self.db.commit()
        return msg


class AddAccountTests(AccountsCase):
    def connect(self, label="Work"):
        response = self.http.post("/api/gmail/accounts/connect", json={"label": label})
        self.assertEqual(response.status_code, 200)
        return state_from(response.json()["authorization_url"]), response.json()["authorization_url"]

    def finish(self, state, **google):
        params = dict(email="work@corp.com", sub="sub-w", refresh_token="work-token", scope=GMAIL_SCOPE)
        params.update(google)
        with patch("httpx.AsyncClient", FakeGoogleHttp(**params)):
            return self.http.get(f"/api/auth/google/callback?code=abc&state={state}")

    def test_lists_the_existing_account_as_primary_and_all_selected(self):
        body = self.http.get("/api/gmail/accounts").json()
        self.assertEqual(body["selected"], "all")
        self.assertEqual([(a["email"], a["label"], a["is_primary"]) for a in body["accounts"]], [("me@school.edu", "School", True)])
        self.assertNotIn("token", str(body).lower())

    def test_adds_a_separately_authenticated_account_with_its_own_encrypted_token(self):
        state, url = self.connect("Work")
        self.assertIn("select_account", url)
        response = self.finish(state)
        self.assertTrue(response.headers["location"].endswith("/?gmail_account=added"))
        accounts = self.http.get("/api/gmail/accounts").json()
        self.assertEqual({a["label"] for a in accounts["accounts"]}, {"School", "Work"})
        work = self.db.query(GmailConnection).filter_by(google_account_email="work@corp.com").one()
        self.assertFalse(work.is_primary)
        self.assertNotIn("work-token", work.encrypted_refresh_token)
        self.assertEqual(decrypt_token(work.encrypted_refresh_token), "work-token")
        self.assertEqual(decrypt_token(self.school.encrypted_refresh_token), "school-token")  # untouched
        self.assertEqual(accounts["selected"], work.id)  # the new account is shown right away

    def test_connecting_the_same_google_account_again_updates_it_instead_of_duplicating(self):
        self.finish(self.connect("Work")[0])
        self.finish(self.connect("Office")[0], refresh_token="work-token-2")
        rows = self.db.query(GmailConnection).filter_by(google_account_email="work@corp.com").all()
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0].label, decrypt_token(rows[0].encrypted_refresh_token)), ("Office", "work-token-2"))

    def test_consent_without_gmail_access_adds_nothing(self):
        for google in ({"scope": "openid email"}, {"refresh_token": None}):
            response = self.finish(self.connect()[0], **google)
            self.assertTrue(response.headers["location"].endswith("gmail_account=denied"))
        self.assertEqual(self.db.query(GmailConnection).filter_by(user_id=self.user.id).count(), 1)

    def test_labels_are_cleaned_and_capped(self):
        self.finish(self.connect("  Work\n\t  Team " + "x" * 40)[0])
        label = self.db.query(GmailConnection).filter_by(google_account_email="work@corp.com").one().label
        self.assertEqual(label, ("Work Team " + "x" * 40)[:30])
        self.assertEqual(self.http.post("/api/gmail/accounts/connect", json={"label": "y" * 61}).status_code, 422)

    def test_account_limit(self):
        for i in range(9):
            self.db.add(GmailConnection(user_id=self.user.id, google_account_email=f"a{i}@x.com", encrypted_refresh_token="x"))
        self.db.commit()
        self.assertEqual(self.http.post("/api/gmail/accounts/connect", json={"label": "One too many"}).status_code, 400)


class SelectionTests(AccountsCase):
    def setUp(self):
        super().setUp()
        self.personal = self.add_personal()

    def select(self, account_id):
        return self.http.put("/api/gmail/accounts/selected", json={"account_id": account_id})

    def test_switching_persists_and_falls_back_to_all_if_the_account_disappears(self):
        self.assertEqual(self.select(self.personal.id).json()["selected"], self.personal.id)
        self.assertEqual(self.http.get("/api/gmail/accounts").json()["selected"], self.personal.id)
        self.assertEqual(self.select("all").json()["selected"], "all")
        self.select(self.personal.id)
        self.http.delete(f"/api/gmail/accounts/{self.personal.id}")
        self.assertEqual(self.http.get("/api/gmail/accounts").json()["selected"], "all")

    def test_scan_history_follows_the_selected_account(self):
        for conn in (self.school, self.personal, None):
            self.db.add(ScanRun(user_id=self.user.id, connection_id=conn.id if conn else None, status="COMPLETED", gmail_query="q"))
        self.db.commit()
        ids = lambda: sorted((s["account_email"] or "all") for s in self.http.get("/api/gmail/scans").json())
        self.assertEqual(ids(), ["all", "me@gmail.com", "me@school.edu"])
        self.select(self.personal.id)
        self.assertEqual(ids(), ["me@gmail.com"])
        self.select(self.school.id)
        self.assertEqual(ids(), ["me@school.edu"])

    def test_sync_scans_the_selected_account_or_all(self):
        seen = []
        def fake_run_sync(db, user, start_date=None, end_date=None, progress_callback=None, connection_id=None):
            seen.append(connection_id)
            return dict(messages_fetched=1, messages_processed=1, tasks_created=0, tasks_updated=0, duration_ms=1)
        with patch("app.routers.gmail.run_sync", fake_run_sync):
            self.select(self.personal.id); self.http.post("/api/gmail/sync", json={})
            self.select("all"); self.http.post("/api/gmail/sync", json={})
            self.http.post("/api/gmail/sync", json={"account_id": self.school.id})
        self.assertEqual(seen, [self.personal.id, "all", self.school.id])
        scans = {s.connection_id for s in self.db.query(ScanRun).all()}
        self.assertEqual(scans, {self.personal.id, None, self.school.id})

    def test_sync_rejects_an_account_that_is_not_yours(self):
        _, theirs = self.other_user()
        self.assertEqual(self.http.post("/api/gmail/sync", json={"account_id": theirs.id}).status_code, 404)

    def test_email_search_follows_the_selection(self):
        self.message(self.school, "Physics lab"); self.message(self.personal, "Physics club")
        search = lambda: sorted(e["subject"] for e in self.http.get("/api/search", params={"q": "physics"}).json()["emails"])
        self.assertEqual(search(), ["Physics club", "Physics lab"])  # All accounts
        self.select(self.school.id); self.assertEqual(search(), ["Physics lab"])
        self.select(self.personal.id); self.assertEqual(search(), ["Physics club"])

    def test_task_links_open_the_mailbox_the_email_came_from(self):
        task = Task(user_id=self.user.id, title="Join club"); self.db.add(task); self.db.commit()
        msg = self.message(self.personal, "Club")
        self.db.add(TaskSource(task_id=task.id, message_id=msg.id)); self.db.commit()
        url = self.http.get(f"/api/tasks/{task.id}").json()["sources"][0]["gmail_url"]
        self.assertEqual(url, "https://mail.google.com/mail/u/me@gmail.com/#all/t-Club")

    def test_rename_and_remove(self):
        renamed = self.http.patch(f"/api/gmail/accounts/{self.personal.id}", json={"label": "  Home "}).json()
        self.assertEqual(renamed["label"], "Home")
        self.message(self.personal, "Keep me")
        self.assertEqual(self.http.delete(f"/api/gmail/accounts/{self.personal.id}").json(), {"removed": True})
        self.assertEqual(self.db.query(GmailConnection).filter_by(user_id=self.user.id).count(), 1)
        self.assertEqual(self.db.query(EmailMessage).filter_by(subject="Keep me").count(), 1)  # imported data is kept

    def test_disconnect_defaults_to_the_sign_in_account_and_can_target_another(self):
        self.http.delete("/api/gmail/disconnect", params={"account_id": self.personal.id})
        self.assertEqual([c.google_account_email for c in self.db.query(GmailConnection).filter_by(user_id=self.user.id)], ["me@school.edu"])
        self.add_personal()
        self.http.delete("/api/gmail/disconnect")
        self.assertEqual([c.google_account_email for c in self.db.query(GmailConnection).filter_by(user_id=self.user.id)], ["me@gmail.com"])


class IsolationTests(AccountsCase):
    def test_other_users_accounts_are_invisible_and_untouchable(self):
        other, theirs = self.other_user()
        self.message(theirs, "Secret plans", user=other)
        self.assertEqual([a["email"] for a in self.http.get("/api/gmail/accounts").json()["accounts"]], ["me@school.edu"])
        self.assertEqual(self.http.patch(f"/api/gmail/accounts/{theirs.id}", json={"label": "Mine now"}).status_code, 404)
        self.assertEqual(self.http.delete(f"/api/gmail/accounts/{theirs.id}").status_code, 404)
        self.assertEqual(self.http.put("/api/gmail/accounts/selected", json={"account_id": theirs.id}).status_code, 404)
        self.assertEqual(self.http.delete("/api/gmail/disconnect", params={"account_id": theirs.id}).json(), {"disconnected": True})
        self.assertEqual(self.db.query(GmailConnection).filter_by(id=theirs.id).count(), 1)
        self.assertEqual(self.http.get("/api/search", params={"q": "secret"}).json()["emails"], [])

    def test_requires_sign_in(self):
        from fastapi.testclient import TestClient
        from app.main import app
        anon = TestClient(app, base_url="http://localhost")
        for method, path in (("get", "/api/gmail/accounts"), ("post", "/api/gmail/accounts/connect"),
                             ("put", "/api/gmail/accounts/selected"), ("delete", "/api/gmail/accounts/x")):
            self.assertEqual(getattr(anon, method)(path).status_code, 401, path)


class SignInTests(AccountsCase):
    def sign_in(self, **google):
        anon = api_client(self.user)
        anon.cookies.clear()
        url = anon.get("/api/auth/google").json()["authorization_url"]
        with patch("httpx.AsyncClient", FakeGoogleHttp(**google)):
            return anon.get(f"/api/auth/google/callback?code=abc&state={state_from(url)}")

    def test_signing_in_refreshes_that_accounts_token_and_leaves_other_accounts_alone(self):
        personal = self.add_personal()
        response = self.sign_in(email="me@school.edu", sub="sub-1", refresh_token="school-token-NEW")
        self.assertEqual(response.status_code, 303)
        self.db.expire_all()
        self.assertEqual(decrypt_token(self.school.encrypted_refresh_token), "school-token-NEW")
        self.assertEqual(decrypt_token(personal.encrypted_refresh_token), "personal-token")
        self.assertEqual(self.db.query(GmailConnection).filter_by(user_id=self.user.id).count(), 2)

    def test_signing_in_again_after_removing_the_primary_does_not_overwrite_another_account(self):
        personal = self.add_personal()
        self.http.delete("/api/gmail/disconnect")  # removes the sign-in account
        self.sign_in(email="me@school.edu", sub="sub-1", refresh_token="school-token-2")
        self.db.expire_all()
        self.assertEqual(decrypt_token(personal.encrypted_refresh_token), "personal-token")
        rows = {c.google_account_email: c for c in self.db.query(GmailConnection).filter_by(user_id=self.user.id)}
        self.assertEqual(set(rows), {"me@school.edu", "me@gmail.com"})
        self.assertTrue(rows["me@school.edu"].is_primary)

    def test_a_brand_new_user_gets_a_primary_connection(self):
        self.sign_in(email="fresh@x.com", sub="sub-fresh", refresh_token="fresh-token")
        user = self.db.query(User).filter_by(google_subject_id="sub-fresh").one()
        (conn,) = user.gmail_connections
        self.assertEqual((conn.is_primary, conn.google_subject_id), (True, "sub-fresh"))


class MultiAccountScanTests(AccountsCase):
    def test_one_broken_account_does_not_stop_the_others_and_is_named(self):
        personal = self.add_personal()
        scanned = []
        def fake(db, user, connection, *args, **kwargs):
            scanned.append(connection.label)
            if connection.id == self.school.id:
                raise RuntimeError("token revoked")
            return dict(messages_fetched=3, messages_processed=2, tasks_created=1, tasks_updated=0, duration_ms=5)
        with patch.object(gmail_sync, "_sync_connection", fake):
            with self.assertRaises(RuntimeError) as caught:
                gmail_sync.run_sync(self.db, self.user, connection_id="all")
        self.assertEqual(sorted(scanned), ["Personal", "School"])
        self.assertIn("School", str(caught.exception))
        self.assertNotIn("token revoked", str(caught.exception))

    def test_all_accounts_totals_are_summed(self):
        self.add_personal()
        def fake(db, user, connection, *args, **kwargs):
            return dict(messages_fetched=3, messages_processed=2, tasks_created=1, tasks_updated=1, duration_ms=5,
                        start_date=None, end_date=None, gmail_query="q")
        with patch.object(gmail_sync, "_sync_connection", fake):
            totals = gmail_sync.run_sync(self.db, self.user, connection_id="all")
        self.assertEqual((totals["messages_fetched"], totals["tasks_created"]), (6, 2))

    def test_no_accounts_is_a_clear_400(self):
        from fastapi import HTTPException
        self.db.query(GmailConnection).delete(); self.db.commit(); self.db.refresh(self.user)
        with self.assertRaises(HTTPException) as caught:
            gmail_sync.run_sync(self.db, self.user)
        self.assertEqual(caught.exception.status_code, 400)


class MigrationTests(DbTestCase):
    NEW_COLUMNS = {
        "users": ["selected_gmail_account"],
        "tasks": ["calendar_event_id", "calendar_etag", "calendar_hash", "calendar_synced_at"],
        "scan_runs": ["connection_id"],
        "gmail_connections": ["label", "is_primary", "google_subject_id"],
        "email_messages": ["connection_id", "account_email"],
    }

    def test_an_existing_single_account_database_is_upgraded_in_place(self):
        conn = GmailConnection(user_id=self.user.id, google_account_email="me@school.edu", encrypted_refresh_token="enc")
        self.db.add(conn); self.db.flush()
        self.db.add(EmailMessage(user_id=self.user.id, gmail_message_id="m1", gmail_thread_id="t1"))
        self.db.add(ScanRun(user_id=self.user.id, status="COMPLETED", gmail_query="q"))
        self.db.add(Task(user_id=self.user.id, title="Old task"))
        self.db.commit()

        # Put the schema back the way the previous version left it.
        with engine.begin() as c:
            for index in ("ix_tasks_calendar_event_id", "ix_gmail_connections_google_subject_id",
                          "ix_email_messages_connection_id", "ix_scan_runs_connection_id"):
                c.execute(text(f'DROP INDEX IF EXISTS "{index}"'))
            for table, columns in self.NEW_COLUMNS.items():
                for column in columns:
                    c.execute(text(f'ALTER TABLE "{table}" DROP COLUMN "{column}"'))
            c.execute(text("DROP TABLE calendar_connections")); c.execute(text("DROP TABLE calendar_events"))
        self.db.close()

        migrate_sqlite_schema()
        migrate_sqlite_schema()  # a second start must change nothing

        with engine.connect() as c:
            row = c.execute(text("select id, is_primary, google_subject_id, label from gmail_connections")).one()
            self.assertEqual((row[1], row[2], row[3]), (1, "sub-1", ""))   # the sign-in account, keyed by its Google id
            self.assertEqual(c.execute(text("select connection_id, account_email from email_messages")).one(), (row[0], "me@school.edu"))
            self.assertEqual(c.execute(text("select connection_id from scan_runs")).scalar(), row[0])
            self.assertEqual(c.execute(text("select title, calendar_event_id from tasks")).one(), ("Old task", None))

        # Later "all accounts" scans (NULL) must survive another startup.
        with engine.begin() as c:
            c.execute(text("update scan_runs set connection_id = NULL"))
        migrate_sqlite_schema()
        with engine.connect() as c:
            self.assertIsNone(c.execute(text("select connection_id from scan_runs")).scalar())


if __name__ == "__main__":
    unittest.main()
