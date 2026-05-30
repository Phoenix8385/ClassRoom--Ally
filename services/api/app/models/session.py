from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ClassroomSession(Base):
    __tablename__ = "classroom_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4
    )
    teacher_name: Mapped[str] = mapped_column(String(255), nullable=False)
    language: Mapped[Literal["ISL", "ASL"]] = mapped_column(
        String(3), nullable=False, default="ISL"
    )
    status: Mapped[Literal["active", "ended"]] = mapped_column(
        String(6), nullable=False, default="active"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    total_segments: Mapped[int] = mapped_column(nullable=False, default=0)
