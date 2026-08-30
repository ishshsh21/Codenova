"""GET /api/search?q= — structured search across tasks + source emails.
(TRD 4.2 designates pgvector semantic search as the production path; this MVP
uses SQL LIKE matching, with a documented swap-in point.)"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, Task, EmailMessage
from app.security import get_current_user

router = APIRouter(prefix="/api/search", tags=["search"])


@router.get("")
def search(q: str = Query(min_length=1), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    like = f"%{q}%"
    tasks = (
        db.query(Task)
        .filter(Task.user_id == user.id, or_(Task.title.ilike(like), Task.description.ilike(like)))
        .limit(20)
        .all()
    )
    messages = (
        db.query(EmailMessage)
        .filter(EmailMessage.user_id == user.id, or_(EmailMessage.subject.ilike(like), EmailMessage.normalized_body.ilike(like)))
        .limit(20)
        .all()
    )
    return {
        "tasks": [{"id": t.id, "title": t.title, "priority": t.priority, "status": t.status} for t in tasks],
        "emails": [{"id": m.id, "subject": m.subject, "sender_name": m.sender_name, "snippet": m.snippet} for m in messages],
    }
