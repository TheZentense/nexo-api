from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ProjectVideo(Base):
    __tablename__ = "project_videos"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','processing','ready','failed')", name="status_values"
        ),
        CheckConstraint("size_bytes > 0", name="size_positive"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), index=True
    )
    original_key: Mapped[str] = mapped_column(String(300), unique=True)
    video_key: Mapped[str | None] = mapped_column(String(300))
    poster_key: Mapped[str | None] = mapped_column(String(300))
    size_bytes: Mapped[int]
    status: Mapped[str] = mapped_column(String(20), server_default="pending", index=True)
    error_code: Mapped[str | None] = mapped_column(String(40))
    attempt_id: Mapped[UUID | None]
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
