import json
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import httplib2
from googleapiclient.errors import HttpError

from app.gmail import client as gmail_client
from app.gmail import sync as gmail_sync
from app.gmail.client import GmailClient, GmailMessageRef, GmailRateLimitError
from app.models import EmailMessage, EmailThread, GmailConnection, ScanRun, Task, Notification
from app.security import encrypt_token
from tests.support import DbTestCase, api_client


def http_error(status, reason):
    body = json.dumps({"error": {"code": status, "message": reason, "errors": [{"reason": reason, "domain": "usageLimits"}]}})
    return HttpError(httplib2.Response({"status": str(status)}), body.encode())


class RetryTests(unittest.TestCase):
    def setUp(self):
        gmail_client._cooldown_until = 0.0
        patcher = patch("app.gmail.client.time.sleep")
        self.sleep = patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(lambda: setattr(gmail_client, "_cooldown_until", 0.0))

    def flaky(self, failures, error):
        calls = {"n": 0}
        def fn():
            calls["n"] += 1
            if calls["n"] <= failures:
                raise error
            return "ok"
        return fn, calls

    def test_rate_limited_calls_are_retried_with_backoff_until_they_succeed(self):
        fn, calls = self.flaky(3, http_error(403, "rateLimitExceeded"))
        self.assertEqual(GmailClient._with_retry(fn), "ok")
        self.assertEqual(calls["n"], 4)
        waits = [c.args[0] for c in self.sleep.call_args_list]
        self.assertTrue(waits and all(0 < w <= gmail_client._RATE_LIMIT_MAX_WAIT + 1 for w in waits), waits)

    def test_user_rate_limit_and_429_count_as_rate_limits_too(self):
        for error in (http_error(403, "userRateLimitExceeded"), http_error(429, "rateLimitExceeded")):
            fn, calls = self.flaky(1, error)
            self.assertEqual(GmailClient._with_retry(fn), "ok")
            self.assertEqual(calls["n"], 2)

    def test_gives_up_with_a_clear_error_instead_of_a_raw_http_error(self):
        fn, calls = self.flaky(99, http_error(403, "rateLimitExceeded"))
        with self.assertRaises(GmailRateLimitError):
            GmailClient._with_retry(fn)
        self.assertEqual(calls["n"], gmail_client._RATE_LIMIT_ATTEMPTS)

    def test_real_permission_errors_are_not_retried(self):
        fn, calls = self.flaky(99, http_error(403, "insufficientPermissions"))
        with self.assertRaises(HttpError):
            GmailClient._with_retry(fn)
        self.assertEqual(calls["n"], 1)
        self.sleep.assert_not_called()

    def test_server_errors_keep_their_original_behaviour(self):
        fn, calls = self.flaky(99, http_error(503, "backendError"))
        with self.assertRaises(HttpError):
            GmailClient._with_retry(fn)
        self.assertEqual(calls["n"], 3)
        fn, calls = self.flaky(1, http_error(500, "backendError"))
        self.assertEqual(GmailClient._with_retry(fn), "ok")

    def test_one_workers_rate_limit_pauses_the_others(self):
        fn, _ = self.flaky(1, http_error(403, "rateLimitExceeded"))
        GmailClient._with_retry(fn)
        self.sleep.reset_mock()
        GmailClient._with_retry(lambda: "second worker")  # a different call, started during the cooldown
        self.assertTrue(self.sleep.called)


class FetchTests(unittest.TestCase):
    def refs(self, n):
        return [GmailMessageRef(id=f"m{i}", thread_id=f"t{i}") for i in range(n)]

    def run_fetch(self, refs, known, fetch):
        client = SimpleNamespace(list_message_ids=lambda q, n: refs)
        with patch.object(gmail_sync, "_fetch_one_email", fetch), patch.object(gmail_sync.settings, "sync_worker_count", 1):
            return gmail_sync._normalized_email_records_gmail(client, "tok", "q", 150, lambda ids: known)

    def known(self, ids):
        return {i: {"gmail_message_id": i, "gmail_thread_id": "t", "internal_date": datetime(2026, 1, 1)} for i in ids}

    def test_already_imported_messages_are_never_downloaded_again(self):
        fetched = []
        def fetch(token, ref):
            fetched.append(ref.id); return {"gmail_message_id": ref.id}
        records, unfetched = self.run_fetch(self.refs(5), self.known(["m0", "m1", "m2"]), fetch)
        self.assertEqual(sorted(fetched), ["m3", "m4"])
        self.assertEqual(sorted(r["gmail_message_id"] for r in records), ["m0", "m1", "m2", "m3", "m4"])
        self.assertEqual(unfetched, 0)

    def test_rate_limit_midway_keeps_what_was_fetched_and_stops_requesting(self):
        fetched = []
        def fetch(token, ref):
            fetched.append(ref.id)
            if len(fetched) > 3:
                raise GmailRateLimitError("limit")
            return {"gmail_message_id": ref.id}
        records, unfetched = self.run_fetch(self.refs(10), {}, fetch)
        self.assertEqual(len(records), 3)
        self.assertEqual(unfetched, 7)
        self.assertEqual(len(fetched), 4)  # the other six were cancelled, not sent to Gmail


class ScanTests(DbTestCase):
    """_sync_connection end to end with a fake Gmail (no network)."""

    BODY = "Hi, please submit the report by Friday. Thanks"

    def setUp(self):
        super().setUp()
        self.conn = GmailConnection(user_id=self.user.id, google_account_email="me@school.edu", is_primary=True,
                                    encrypted_refresh_token=encrypt_token("t"))
        self.db.add(self.conn); self.db.commit(); self.db.refresh(self.user)
        self.threads = {"m0": "A", "m1": "A", "m2": "B", "m3": "C", "m4": "C", "m5": "C"}
        self.fetch_calls = []
        self.limit_after = None

    def scan(self, ids):
        refs = [GmailMessageRef(id=i, thread_id=self.threads[i]) for i in ids]
        client = SimpleNamespace(list_message_ids=lambda q, n: refs)
        def fetch(token, ref):
            self.fetch_calls.append(ref.id)
            if self.limit_after is not None and len(self.fetch_calls) > self.limit_after:
                raise GmailRateLimitError("limit")
            n = int(ref.id[1:])
            return {"gmail_message_id": ref.id, "gmail_thread_id": self.threads[ref.id],
                    "internal_date": datetime(2026, 1, 1) + timedelta(hours=n), "sender_name": "Prof", "sender_email": "prof@school.edu",
                    "subject": f"Report {self.threads[ref.id]}", "snippet": "", "normalized_body": self.BODY,
                    "has_attachments": False, "labels": []}
        with patch.object(gmail_sync, "GmailClient", lambda token: client), patch.object(gmail_sync, "_fetch_one_email", fetch), \
             patch.object(gmail_sync.settings, "sync_worker_count", 1):
            return gmail_sync._sync_connection(self.db, self.user, self.conn)

    def thread_counts(self):
        return {t.gmail_thread_id: t.message_count for t in self.db.query(EmailThread)}

    def test_a_repeat_scan_downloads_nothing_and_changes_nothing(self):
        ids = list(self.threads)
        first = self.scan(ids)
        self.assertEqual((first["messages_fetched"], first["messages_processed"], first["messages_unfetched"]), (6, 6, 0))
        tasks, counts, calls = self.db.query(Task).count(), self.thread_counts(), len(self.fetch_calls)
        second = self.scan(ids)
        self.assertEqual(len(self.fetch_calls), calls)                       # zero new downloads
        self.assertEqual((second["messages_fetched"], second["messages_processed"]), (6, 0))
        self.assertEqual((self.db.query(Task).count(), self.thread_counts()), (tasks, counts))
        self.assertEqual(self.db.query(EmailMessage).count(), 6)

    def test_skipping_known_messages_gives_the_same_thread_counts_as_downloading_everything(self):
        self.scan(list(self.threads))
        everything = self.thread_counts()
        self.setUp()                                  # fresh database
        self.scan(["m0", "m2", "m3"])                 # an earlier, smaller scan
        self.scan(list(self.threads))                 # the later scan re-lists them all
        self.assertEqual(self.thread_counts(), everything)
        self.assertEqual(everything, {"A": 2, "B": 1, "C": 3})

    def test_a_rate_limited_scan_saves_progress_and_the_rerun_finishes_the_job(self):
        ids = list(self.threads)
        self.limit_after = 2
        partial = self.scan(ids)
        self.assertEqual((partial["messages_fetched"], partial["messages_unfetched"]), (2, 4))
        self.assertEqual(self.db.query(EmailMessage).count(), 2)              # kept, not thrown away
        self.fetch_calls.clear(); self.limit_after = None
        done = self.scan(ids)
        self.assertEqual(sorted(self.fetch_calls), ["m2", "m3", "m4", "m5"])  # only the missing ones
        self.assertEqual((done["messages_unfetched"], self.db.query(EmailMessage).count()), (0, 6))
        self.assertEqual(self.thread_counts(), {"A": 2, "B": 1, "C": 3})


class ScanReportingTests(DbTestCase):
    def setUp(self):
        super().setUp()
        self.db.add(GmailConnection(user_id=self.user.id, google_account_email="me@school.edu", is_primary=True,
                                    encrypted_refresh_token=encrypt_token("t")))
        self.db.commit()
        self.http = api_client(self.user)

    def sync_with(self, behaviour):
        with patch("app.routers.gmail.run_sync", behaviour):
            self.http.post("/api/gmail/sync", json={})
        return self.http.get("/api/gmail/scans").json()[0], self.http.get("/api/gmail/notifications").json()[0]

    def test_a_partial_scan_is_reported_plainly_and_can_be_rerun(self):
        def run(*a, **k):
            return dict(messages_fetched=20, messages_processed=18, messages_unfetched=7, tasks_created=4, tasks_updated=0, duration_ms=9)
        scan, note = self.sync_with(run)
        self.assertEqual(scan["status"], "FAILED")
        self.assertIn("7 emails weren't downloaded", scan["error_message"])
        self.assertIn("rerun", scan["error_message"])
        self.assertEqual(scan["tasks_created"], 4)  # progress is recorded
        self.assertEqual((note["kind"], note["title"]), ("ERROR", "Scan paused by Gmail rate limit"))

    def test_hitting_the_limit_before_anything_downloads_is_reported_plainly(self):
        def run(*a, **k):
            raise GmailRateLimitError("limit")
        scan, note = self.sync_with(run)
        self.assertEqual(scan["status"], "FAILED")
        self.assertIn("rate limit", scan["error_message"])
        self.assertNotIn("backend logs", note["message"])

    def test_other_failures_and_normal_scans_are_unchanged(self):
        def boom(*a, **k):
            raise RuntimeError("something else")
        scan, note = self.sync_with(boom)
        self.assertEqual((scan["status"], note["title"]), ("FAILED", "Scan failed"))
        def ok(*a, **k):
            return dict(messages_fetched=5, messages_processed=5, messages_unfetched=0, tasks_created=1, tasks_updated=0, duration_ms=9)
        scan, note = self.sync_with(ok)
        self.assertEqual((scan["status"], note["title"]), ("COMPLETED", "Scan completed"))


if __name__ == "__main__":
    unittest.main()
