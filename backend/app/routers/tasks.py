"""FR-17 User Feedback + task CRUD/detail endpoints."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Task, TaskSource, EmailMessage, TaskDependency, TaskFeedback, TaskStatus, User
from app.security import get_current_user
from app.gcal.sync import sync_task_safe
from app.schemas import TaskOut, TaskUpdateIn, TaskFeedbackIn, TaskSourceOut

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


def _to_task_out(db: Session, task: Task) -> TaskOut:
    sources = (
        db.query(TaskSource, EmailMessage)
        .join(EmailMessage, TaskSource.message_id == EmailMessage.id)
        .filter(TaskSource.task_id == task.id)
        .all()
    )
    deps = db.query(TaskDependency).filter_by(task_id=task.id).all()

    return TaskOut(
        **{k: getattr(task, k) for k in [
            "id", "title", "description", "status", "priority", "priority_score",
            "action_type", "deadline", "deadline_raw", "deadline_confidence",
            "owner_type", "owner_label", "project", "project_confidence",
            "estimated_effort_minutes", "confidence", "is_blocking",
            "notes", "snoozed_until", "created_at", "updated_at",
        ]},
        priority_reasons=task.priority_reasons or [],
        depends_on=[d.depends_on_task_id for d in deps],
        calendar_synced=bool(task.calendar_event_id and task.status == TaskStatus.OPEN.value and task.deadline),
        sources=[
            TaskSourceOut(
                message_id=m.id, gmail_thread_id=m.gmail_thread_id,
                internal_date=m.internal_date,
                gmail_url=f"https://mail.google.com/mail/u/{m.account_email or 0}/#all/{m.gmail_thread_id}",
                subject=m.subject,
                sender_name=m.sender_name, sender_email=m.sender_email, snippet=m.snippet,
                relationship_type=ts.relationship_type,
            )
            for ts, m in sources
        ],
    )


@router.get("", response_model=list[TaskOut])
def list_tasks(
    status_filter: str | None = Query(default=None, alias="status"),
    priority: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(Task).filter_by(user_id=user.id)
    if status_filter:
        q = q.filter(Task.status == status_filter)
    if priority:
        q = q.filter(Task.priority == priority)
    tasks = q.order_by(Task.priority_score.desc()).all()
    return [_to_task_out(db, t) for t in tasks]


@router.get("/{task_id}", response_model=TaskOut)
def get_task(task_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if not task or task.user_id != user.id:
        raise HTTPException(404, "Task not found")
    return _to_task_out(db, task)


@router.post("", response_model=TaskOut)
def create_task(payload: TaskUpdateIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    task = Task(user_id=user.id, title=payload.title or "Untitled task", description=payload.description or "",
                priority=payload.priority or "P3", deadline=payload.deadline, project=payload.project)
    db.add(task)
    db.commit()
    db.refresh(task)
    sync_task_safe(db, user, task)
    return _to_task_out(db, task)


@router.patch("/{task_id}", response_model=TaskOut)
def update_task(task_id: str, payload: TaskUpdateIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if not task or task.user_id != user.id:
        raise HTTPException(404, "Task not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        old_value = getattr(task, field)
        setattr(task, field, value)
        db.add(TaskFeedback(task_id=task.id, user_id=user.id, feedback_type=f"edit:{field}",
                             old_value={"value": str(old_value)}, new_value={"value": str(value)}))
    task.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(task)
    sync_task_safe(db, user, task)
    return _to_task_out(db, task)


@router.post("/{task_id}/complete", response_model=TaskOut)
def complete_task(task_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if not task or task.user_id != user.id:
        raise HTTPException(404, "Task not found")
    task.status = TaskStatus.COMPLETED.value
    task.completed_at = datetime.utcnow()
    db.add(TaskFeedback(task_id=task.id, user_id=user.id, feedback_type="complete"))
    db.commit()
    db.refresh(task)
    sync_task_safe(db, user, task)
    return _to_task_out(db, task)


@router.post("/{task_id}/dismiss", response_model=TaskOut)
def dismiss_task(task_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if not task or task.user_id != user.id:
        raise HTTPException(404, "Task not found")
    task.status = TaskStatus.DISMISSED.value
    db.add(TaskFeedback(task_id=task.id, user_id=user.id, feedback_type="dismiss"))
    db.commit()
    db.refresh(task)
    sync_task_safe(db, user, task)
    return _to_task_out(db, task)


@router.post("/{task_id}/feedback")
def submit_feedback(task_id: str, payload: TaskFeedbackIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if not task or task.user_id != user.id:
        raise HTTPException(404, "Task not found")

    if payload.feedback_type == "not_my_task":
        task.status = TaskStatus.NOT_MY_TASK.value
    elif payload.feedback_type == "priority" and payload.new_value:
        task.priority = payload.new_value.get("priority", task.priority)
    elif payload.feedback_type == "deadline" and payload.new_value:
        raw = payload.new_value.get("deadline")
        task.deadline = datetime.fromisoformat(raw) if raw else None
    elif payload.feedback_type == "project" and payload.new_value:
        task.project = payload.new_value.get("project")

    db.add(TaskFeedback(task_id=task.id, user_id=user.id, feedback_type=payload.feedback_type,
                         new_value=payload.new_value))
    db.commit()
    sync_task_safe(db, user, task)
    return {"ok": True}
