from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from auth import get_current_user
from db.database import get_db
from db.models import User
from schemas.chat import ChatRequest, ChatResponse
from services import chat_service

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("/", response_model=ChatResponse)
def post_chat(
    payload: ChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return chat_service.answer(db, current_user, payload)
    except ValueError as exc:
        raise HTTPException(502, str(exc)) from exc
