"""FR-15/16 Agenda + Proactive Follow-Up endpoints."""
from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, Task, TaskStatus
from app.security import get_current_user
from app.schemas import DailyAgendaOut, WeeklyAgendaOut
from app.agenda.planner import build_daily_agenda, build_weekly_agenda
from app.gmail.sync import run_sync

router = APIRouter(prefix="/api/agenda", tags=["agenda"])


@router.get("/today", response_model=DailyAgendaOut)
def today(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return build_daily_agenda(db, user)


@router.get("/week", response_model=WeeklyAgendaOut)
def week(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return build_weekly_agenda(db, user)


@router.post("/replan", response_model=DailyAgendaOut)
def replan(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Re-syncs and rebuilds today's agenda in one call — used by the
    dashboard's 'Refresh' action."""
    run_sync(db, user)
    return build_daily_agenda(db, user)


@router.get("/follow-ups")
def follow_ups(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """FR-16 Proactive Follow-Up: approaching/overdue open tasks."""
    now = datetime.utcnow()
    tasks = (
        db.query(Task)
        .filter(Task.user_id == user.id, Task.status == TaskStatus.OPEN.value, Task.deadline.isnot(None))
        .all()
    )
    alerts = []
    for t in tasks:
        hours_left = (t.deadline - now).total_seconds() / 3600
        if hours_left <= 24:
            status_word = "overdue" if hours_left < 0 else "due soon"
            alerts.append({
                "task_id": t.id,
                "title": t.title,
                "message": f"Deadline {status_word}. Task still open. Estimated effort: {t.estimated_effort_minutes} minutes.",
                "hours_remaining": round(hours_left, 1),
            })
    return {"alerts": alerts}
