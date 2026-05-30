from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.session import ClassroomSession

router = APIRouter(prefix="/sessions", tags=["sessions"])


class CreateSessionRequest(BaseModel):
    teacher_name: str
    language: Literal["ISL", "ASL"] = "ISL"


class SessionResponse(BaseModel):
    id: uuid.UUID
    teacher_name: str
    language: str
    status: str


@router.post("", response_model=SessionResponse)
async def create_session(
    body: CreateSessionRequest,
    db: AsyncSession = Depends(get_db),
) -> SessionResponse:
    session = ClassroomSession(
        teacher_name=body.teacher_name,
        language=body.language,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return SessionResponse(
        id=session.id,
        teacher_name=session.teacher_name,
        language=session.language,
        status=session.status,
    )
