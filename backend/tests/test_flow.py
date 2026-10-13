"""End-to-end: scan mail for two classes, check Now/Planner/FYI and re-ranking."""
from datetime import datetime

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient

from app.main import app
from app.database import SessionLocal, get_db
from app.models import GmailConnection, User
from app.security import get_current_user
import app.gmail.sync as sync

MAIL = [
    ("m1", "Class B: lab record submission today", "Dear Class B students, can you submit the lab record today? Urgent."),
    ("m2", "Class A: lab record submission today", "Dear Class A students, can you submit the lab record today?"),
    ("m3", "Weekly newsletter", "Campus digest. Unsubscribe here."),
]


@pytest.fixture()
def client(monkeypatch):
    db = SessionLocal()
    user = User(google_subject_id=f"sub-{datetime.utcnow().timestamp()}", email="me@college.edu",
                name="Me", my_classes=["A"])
    db.add(user)
    db.flush()
    db.add(GmailConnection(user_id=user.id, google_account_email=user.email, encrypted_refresh_token="x"))
    db.commit()
    user_id = user.id
    db.close()

    def records(*_args, **_kwargs):
        return [{
            "gmail_message_id": mid, "gmail_thread_id": f"t-{mid}", "internal_date": datetime.utcnow(),
            "sender_name": "Office", "sender_email": "office@college.edu", "subject": subject,
            "snippet": body[:80], "normalized_body": body, "has_attachments": False, "labels": [],
        } for mid, subject, body in MAIL]

    monkeypatch.setattr(sync, "decrypt_token", lambda _: "token")
    monkeypatch.setattr(sync, "GmailClient", lambda _token: None)
    monkeypatch.setattr(sync, "_normalized_email_records_gmail", records)

    def current_user(db=Depends(get_db)):
        return db.get(User, user_id)
    app.dependency_overrides[get_current_user] = current_user
    with TestClient(app) as c:
        s = SessionLocal()
        sync.run_sync(s, s.get(User, user_id))
        s.close()
        yield c
    app.dependency_overrides.clear()


def _all_titles(now):
    return [t["title"] for key in ("overdue", "due_today", "up_next") for t in now[key]]


def test_other_class_mail_goes_to_fyi_not_now(client):
    now = client.get("/api/agenda/now").json()
    titles = _all_titles(now)
    assert any("Class A" in t for t in titles)
    assert not any("Class B" in t for t in titles)
    assert len(titles) == len(set(titles)), "a task appears in two Now lists"

    fyi = client.get("/api/fyi").json()
    groups = {item["subject"]: item["group"] for item in fyi}
    assert groups["Class B: lab record submission today"] == "OTHER_CLASS"
    assert groups["Weekly newsletter"] == "NEWSLETTER"
    assert "Class A: lab record submission today" not in groups


def test_changing_classes_reranks_existing_tasks(client):
    client.patch("/api/auth/settings", json={"my_classes": ["B"]})
    titles = _all_titles(client.get("/api/agenda/now").json())
    assert not any("Class A" in t for t in titles)
    fyi_subjects = [i["subject"] for i in client.get("/api/fyi").json()]
    assert "Class A: lab record submission today" in fyi_subjects


def test_claiming_fyi_mail_makes_it_a_task(client):
    item = next(i for i in client.get("/api/fyi").json() if i["group"] == "OTHER_CLASS")
    task_id = client.post(f"/api/fyi/{item['id']}/claim").json()["task_id"]
    task = client.get(f"/api/tasks/{task_id}").json()
    assert task["audience"] == "MINE"
    assert task["priority"] != "P4"
    assert item["id"] not in [i["id"] for i in client.get("/api/fyi").json()]
