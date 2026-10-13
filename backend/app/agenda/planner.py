"""
FR-15 Agenda Generation — Today / Tomorrow / This Week / Later / No Action,
scheduled inside the user's working hours, ordered by priority + deadline.
"""
from datetime import datetime, timedelta, time as dtime

from sqlalchemy.orm import Session

from app.models import Task, TaskStatus, User, EmailMessage

NO_ACTION_CLASSIFICATIONS = ("FYI", "NEWSLETTER", "AUTOMATED_NOTIFICATION", "COMPLETED")

PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3, "P4": 4}


def _sort_key(task: Task):
    deadline = task.deadline or datetime.max
    return (PRIORITY_ORDER.get(task.priority, 5), deadline, -task.priority_score)


def _task_reason(task: Task) -> list[str]:
    return task.priority_reasons or []


def _schedule_slots(tasks: list[Task], workday_start: str, workday_end: str) -> dict[str, str]:
    """Greedy scheduling of today's tasks into working-hour slots (FR-15)."""
    h, m = map(int, workday_start.split(":"))
    cursor = datetime.combine(datetime.utcnow().date(), dtime(h, m))
    end_h, end_m = map(int, workday_end.split(":"))
    day_end = datetime.combine(datetime.utcnow().date(), dtime(end_h, end_m))

    slots = {}
    for task in tasks:
        if cursor >= day_end:
            break
        slots[task.id] = cursor.strftime("%H:%M")
        cursor += timedelta(minutes=max(task.estimated_effort_minutes, 15))
    return slots


def build_daily_agenda(db: Session, user: User, target_date: datetime | None = None) -> dict:
    now = target_date or datetime.utcnow()
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)

    open_tasks = [
        task for task in db.query(Task).filter_by(user_id=user.id, status=TaskStatus.OPEN.value).all()
        if not task.snoozed_until or task.snoozed_until <= now
    ]

    today_tasks = [
        t for t in open_tasks
        if (t.deadline and now <= t.deadline < day_end)
        or t.priority in ("P0", "P1")
    ]
    today_tasks.sort(key=_sort_key)

    # A deadline becomes overdue as soon as its timestamp passes, rather than
    # waiting for the next calendar day.
    overdue = [t for t in open_tasks if t.deadline and t.deadline < now]
    due_today = [t for t in open_tasks if t.deadline and now <= t.deadline < day_end]
    this_week_end = day_start + timedelta(days=7)
    this_week = [
        t for t in open_tasks
        if t.deadline and day_start <= t.deadline < this_week_end
    ]

    no_action_count = (
        db.query(EmailMessage)
        .filter(EmailMessage.user_id == user.id, EmailMessage.classification.in_(NO_ACTION_CLASSIFICATIONS))
        .count()
    )

    slots = _schedule_slots(today_tasks, user.workday_start, user.workday_end)

    timeline = [
        {
            "id": t.id,
            "title": t.title,
            "priority": t.priority,
            "priority_score": t.priority_score,
            "deadline": t.deadline,
            "estimated_effort_minutes": t.estimated_effort_minutes,
            "blocking": t.is_blocking,
            "reason": _task_reason(t),
            "scheduled_time": slots.get(t.id),
            "source_thread_id": None,
        }
        for t in today_tasks
    ]

    summary = {
        "actionable": len(open_tasks),
        "critical": len([t for t in open_tasks if t.priority == "P0"]),
        "due_today": len(due_today),
        "overdue": len(overdue),
        "this_week": len(this_week),
    }

    return {
        "date": now.date().isoformat(),
        "summary": summary,
        # The client uses these exact sets for KPI filtering, ensuring the
        # filtered task list and its corresponding card always agree.
        "task_ids": {
            "due_today": [t.id for t in due_today],
            "overdue": [t.id for t in overdue],
            "this_week": [t.id for t in this_week],
        },
        "timeline": timeline,
        "no_action_count": no_action_count,
    }


def build_weekly_agenda(db: Session, user: User, start: datetime | None = None) -> dict:
    start = (start or datetime.utcnow()).replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=7)

    open_tasks = [
        task for task in db.query(Task).filter_by(user_id=user.id, status=TaskStatus.OPEN.value).all()
        if not task.snoozed_until or task.snoozed_until <= datetime.utcnow()
    ]

    days: dict[str, list[dict]] = {}
    later: list[dict] = []

    for i in range(7):
        day = start + timedelta(days=i)
        key = day.date().isoformat()
        day_tasks = [t for t in open_tasks if t.deadline and t.deadline.date() == day.date()]
        day_tasks.sort(key=_sort_key)
        days[key] = [
            {
                "id": t.id, "title": t.title, "priority": t.priority,
                "priority_score": t.priority_score, "deadline": t.deadline,
                "estimated_effort_minutes": t.estimated_effort_minutes,
                "blocking": t.is_blocking, "reason": _task_reason(t),
                "scheduled_time": None, "source_thread_id": None,
            }
            for t in day_tasks
        ]

    for t in open_tasks:
        if not t.deadline or t.deadline >= end:
            later.append({
                "id": t.id, "title": t.title, "priority": t.priority,
                "priority_score": t.priority_score, "deadline": t.deadline,
                "estimated_effort_minutes": t.estimated_effort_minutes,
                "blocking": t.is_blocking, "reason": _task_reason(t),
                "scheduled_time": None, "source_thread_id": None,
            })
    later.sort(key=lambda x: PRIORITY_ORDER.get(x["priority"], 5))

    return {
        "week_start": start.date().isoformat(),
        "week_end": (end - timedelta(days=1)).date().isoformat(),
        "days": days,
        "later": later,
    }
