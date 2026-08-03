from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.feedback import Feedback
from app.models.session import ClassroomSession

router = APIRouter(prefix="/feedback", tags=["feedback"])


class CreateFeedbackRequest(BaseModel):
    session_id: uuid.UUID
    segment_id: str
    gloss_shown: str
    rating: Literal[-1, 1]
    corrected_gloss: str | None = None


class FeedbackResponse(BaseModel):
    id: uuid.UUID
    session_id: uuid.UUID
    segment_id: str
    gloss_shown: str
    rating: int
    corrected_gloss: str | None
    created_at: datetime


def _to_response(row: Feedback) -> FeedbackResponse:
    return FeedbackResponse(
        id=row.id,
        session_id=row.session_id,
        segment_id=row.segment_id,
        gloss_shown=row.gloss_shown,
        rating=row.rating,
        corrected_gloss=row.corrected_gloss,
        created_at=row.created_at,
    )


@router.post("", response_model=FeedbackResponse, status_code=status.HTTP_201_CREATED)
async def create_feedback(
    body: CreateFeedbackRequest,
    db: AsyncSession = Depends(get_db),
) -> FeedbackResponse:
    """Record a thumbs-up / thumbs-down on one rendered gloss segment."""
    # Reject feedback for unknown sessions rather than relying on the FK to
    # surface as a 500 from the global handler.
    if await db.get(ClassroomSession, body.session_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        )

    row = Feedback(
        session_id=body.session_id,
        segment_id=body.segment_id,
        gloss_shown=body.gloss_shown,
        rating=body.rating,
        corrected_gloss=body.corrected_gloss,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _to_response(row)


@router.get("/{session_id}", response_model=list[FeedbackResponse])
async def list_feedback(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> list[FeedbackResponse]:
    """Every feedback row for one session, oldest first."""
    result = await db.execute(
        select(Feedback)
        .where(Feedback.session_id == session_id)
        .order_by(Feedback.created_at)
    )
    return [_to_response(row) for row in result.scalars().all()]
