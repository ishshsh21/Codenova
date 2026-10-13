"""FYI feed: mail worth knowing about that isn't the user's work.

That is mail addressed to another class, newsletters, automated notices and
plain announcements. Nothing here is ranked or scheduled. If something here
really is the user's, "claim" turns it into a task.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.agenda.planner import fyi_query
from app.ai.audience import MINE, OTHER_CLASS
from app.ai.heuristic_extractor import classify_and_extract
from app.database import get_db
from app.gmail.sync import reprioritize
from app.models import EmailMessage, SourceRelationship, Task, TaskSource, TaskStatus, User
from app.schemas import FyiItemOut
from app.security import get_current_user

router = APIRouter(prefix="/api/fyi", tags=["fyi"])

FYI_LIMIT = 200
_GROUPS = {"NEWSLETTER": "NEWSLETTER", "AUTOMATED_NOTIFICATION": "AUTOMATED"}
_REASONS = {
    "NEWSLETTER": "Newsletter or digest",
    "AUTOMATED": "Automated notification",
    "NOTICE": "Announcement with nothing for you to do",
}


def _item(msg: EmailMessage) -> FyiItemOut:
    if msg.audience == OTHER_CLASS:
        group = OTHER_CLASS
        reason = f"For {msg.audience_label}, not your class" if msg.audience_label else "For a different class"
    else:
        group = _GROUPS.get(msg.classification, "NOTICE")
        reason = _REASONS[group]
    return FyiItemOut(
        id=msg.id, group=group, subject=msg.subject, sender_name=msg.sender_name,
        sender_email=msg.sender_email, snippet=msg.snippet, internal_date=msg.internal_date,
        gmail_url=f"https://mail.google.com/mail/u/0/#all/{msg.gmail_thread_id}",
        audience_label=msg.audience_label or "", reason=reason,
    )


@router.get("", response_model=list[FyiItemOut])
def list_fyi(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    messages = fyi_query(db, user).order_by(EmailMessage.internal_date.desc()).limit(FYI_LIMIT).all()
    return [_item(m) for m in messages]


@router.post("/{message_id}/claim")
def claim(message_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """The user says this message is theirs after all: make it a ranked task."""
    msg = db.get(EmailMessage, message_id)
    if not msg or msg.user_id != user.id:
        raise HTTPException(404, "Message not found")
    msg.audience = MINE
    msg.audience_locked = True

    source = db.query(TaskSource).filter_by(message_id=msg.id).first()
    task = db.get(Task, source.task_id) if source else None
    if task:
        task.status = TaskStatus.OPEN.value
    else:
        extraction = classify_and_extract(msg.sender_email, msg.subject, msg.normalized_body, 1)
        deadline = None
        if extraction.deadline_iso:
            try:
                deadline = datetime.fromisoformat(extraction.deadline_iso)
            except ValueError:
                deadline = None
        task = Task(
            user_id=user.id,
            title=extraction.task_title or msg.subject or "Task from email",
            description=msg.normalized_body[:500],
            status=TaskStatus.OPEN.value,
            action_type=extraction.action_type or "OTHER",
            deadline=deadline,
            deadline_raw=extraction.deadline_raw,
            deadline_confidence=extraction.deadline_confidence,
            estimated_effort_minutes=extraction.estimated_effort_minutes,
            confidence=1.0,
            audience=MINE,
        )
        db.add(task)
        db.flush()
        db.add(TaskSource(task_id=task.id, message_id=msg.id, relationship_type=SourceRelationship.ORIGIN.value))
    db.commit()
    reprioritize(db, user)
    return {"task_id": task.id}
