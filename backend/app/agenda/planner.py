"""
Builds the two task views. Each answers a different question, so they never
show the same thing in the same way:

- Now:     what needs doing right now (overdue, due today, then the next
           few by priority). The three lists are disjoint.
- Planner: when things are due over the next 7 days, plus undated work.

Tasks addressed to another class (audience OTHER_CLASS) appear in neither;
their mail lives in the FYI feed instead.
"""
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.ai.audience import OTHER_CLASS
from app.models import Task, TaskStatus, User, EmailMessage

FYI_CLASSIFICATIONS = ("FYI", "NEWSLETTER", "AUTOMATED_NOTIFICATION", "COMPLETED")
PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3, "P4": 4}
UP_NEXT_LIMIT = 3


def _sort_key(task: Task):
    return (PRIORITY_ORDER.get(task.priority, 5), task.deadline or datetime.max, -task.priority_score)


def _out(task: Task) -> dict:
    return {
        "id": task.id,
        "title": task.title,
        "priority": task.priority,
        "priority_score": task.priority_score,
        "deadline": task.deadline,
        "estimated_effort_minutes": task.estimated_effort_minutes,
        "blocking": task.is_blocking,
        "reason": task.priority_reasons or [],
    }


def _active_tasks(db: Session, user: User, now: datetime) -> list[Task]:
    return [
        task for task in db.query(Task).filter(
            Task.user_id == user.id,
            Task.status == TaskStatus.OPEN.value,
            Task.audience != OTHER_CLASS,
        ).all()
        if not task.snoozed_until or task.snoozed_until <= now
    ]


def fyi_query(db: Session, user: User):
    return db.query(EmailMessage).filter(
        EmailMessage.user_id == user.id,
        EmailMessage.audience_locked.is_(False),  # claimed by the user: it's a task now
        (EmailMessage.audience == OTHER_CLASS) | EmailMessage.classification.in_(FYI_CLASSIFICATIONS),
    )


def build_now(db: Session, user: User, now: datetime | None = None) -> dict:
    now = now or datetime.utcnow()
    day_end = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    tasks = sorted(_active_tasks(db, user, now), key=_sort_key)

    # A deadline is overdue as soon as its timestamp passes.
    overdue = [t for t in tasks if t.deadline and t.deadline < now]
    due_today = [t for t in tasks if t.deadline and now <= t.deadline < day_end]
    taken = {t.id for t in overdue + due_today}
    up_next = [t for t in tasks if t.id not in taken and t.priority != "P4"][:UP_NEXT_LIMIT]

    return {
        "date": now.date().isoformat(),
        "overdue": [_out(t) for t in overdue],
        "due_today": [_out(t) for t in due_today],
        "up_next": [_out(t) for t in up_next],
        "open_count": len(tasks),
        "fyi_count": fyi_query(db, user).count(),
        "planned_minutes_today": sum(t.estimated_effort_minutes for t in overdue + due_today),
    }


def build_planner(db: Session, user: User, start: datetime | None = None) -> dict:
    now = datetime.utcnow()
    start = (start or now).replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=7)
    tasks = sorted(_active_tasks(db, user, now), key=_sort_key)

    days: dict[str, list[dict]] = {}
    for i in range(7):
        day = (start + timedelta(days=i)).date()
        days[day.isoformat()] = [_out(t) for t in tasks if t.deadline and t.deadline.date() == day]

    return {
        "week_start": start.date().isoformat(),
        "week_end": (end - timedelta(days=1)).date().isoformat(),
        "days": days,
        "undated": [_out(t) for t in tasks if not t.deadline],
    }
