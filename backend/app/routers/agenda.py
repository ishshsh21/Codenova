"""Now + Planner endpoints (see agenda/planner.py)."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.security import get_current_user
from app.schemas import NowOut, PlannerOut
from app.agenda.planner import build_now, build_planner

router = APIRouter(prefix="/api/agenda", tags=["agenda"])


@router.get("/now", response_model=NowOut)
def now(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return build_now(db, user)


@router.get("/planner", response_model=PlannerOut)
def planner(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return build_planner(db, user)
