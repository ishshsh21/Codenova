"""AI Assistant endpoint."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.ai.assistant import respond
from app.database import get_db
from app.models import User
from app.schemas import AssistantChatIn, AssistantChatOut
from app.security import get_current_user

router = APIRouter(prefix="/api/assistant", tags=["assistant"])


@router.post("/chat", response_model=AssistantChatOut)
def chat(payload: AssistantChatIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    message, action_taken = respond(db, user, payload.message, [item.model_dump() for item in payload.history])
    return AssistantChatOut(message=message, action_taken=action_taken)
