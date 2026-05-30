from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("classroom_sessions.id", ondelete="CASCADE"), nullable=False
    )
    segment_id: Mapped[str] = mapped_column(String(255), nullable=False)
    gloss_shown: Mapped[str] = mapped_column(String(1024), nullable=False)
    rating: Mapped[Literal[-1, 1]] = mapped_column(Integer, nullable=False)
    corrected_gloss: Mapped[str | None] = mapped_column(
        String(1024), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
